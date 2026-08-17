"""
小说写作 Agent —— 主应用入口（v0.2 改进版）

改进点：
1. ✅ Checker → Writer 反馈重写机制（最多 3 次重试）
2. ✅ 流式输出支持（SSE 端点）
3. ✅ Token 成本统计 API
4. ✅ Story Bible 版本控制集成
5. ✅ 上下文压缩器自动启用
6. ✅ 人工审核状态机
7. ✅ 更完善的错误处理

v0.2 修复：
- ✅ 修复 #2：添加 load_dotenv() 支持 .env 文件加载
- ✅ 修复 #3：添加线程安全锁保护全局状态
- ✅ 修复 #4：实现启动时数据恢复机制
"""

import json
import os
import threading
import time
from flask import Flask, render_template, request, jsonify, send_from_directory, Response

# ============================================================
# v0.2 修复 #2：加载 .env 配置文件
# ============================================================
try:
    from dotenv import load_dotenv

    load_dotenv()  # 现在可以正确读取 .env 文件了
except ImportError:
    pass  # python-dotenv 未安装时静默跳过

from core.story_bible import VersionedStoryBible, ChapterSummary
from core.state import StoryStateTracker
from core.vector_index import SemanticIndex
from core.skill_knowledge import (
    polisher_rules,
    reviewer_rules,
    platform_rubric,
    writer_rules,
    outline_rules,
    genre_style_rules,
    resolve_skills_dir,
    is_available,
)
from core.skill_precheck import run_precheck
from agents import (
    WorldBuilderAgent,
    OutlineAgent,
    WriterAgent,
    CheckerAgent,
    PolisherAgent,
    ChapterSummarizerAgent,
    ReviewerAgent,
    ShortStoryAgent,
)
from agents.base import tracker as token_tracker
from agents.checker_agent import QUALITY_FLOOR
from agents.outline_agent import MAX_CHAPTERS_PER_CALL

app = Flask(
    __name__,
    template_folder="templates",
    static_folder="static",
)


# ============================================================
# 全局状态管理（v0.2 增强 + 修复 #3：线程安全）
# ============================================================

# 流水线步骤枚举
class PipelineStep:
    IDLE = "idle"
    INPUT = "input"
    WORLD_BUILDING = "world_building"
    WORLD_BUILT = "world_built"  # 等待用户确认
    OUTLINING = "outlining"
    OUTLINE_GENERATED = "outline_generated"  # 等待用户确认
    WRITING = "writing"
    CHAPTER_DONE = "chapter_done"  # 等待用户确认
    DONE = "done"
    ERROR = "error"


class NovelProject:
    """小说项目状态（v0.2 增强 + 线程安全）"""

    MAX_RETRIES = 3  # Checker 失败后的最大重写次数

    def __init__(self):
        self.reset()
        # v0.2 修复 #3：线程锁，保护所有共享状态的读写
        self._lock = threading.RLock()

    def reset(self):
        """重置项目状态（需要在持有锁的情况下调用）"""
        self.premise = ""
        self.genre = ""
        self.bible: VersionedStoryBible = VersionedStoryBible()
        self.outline = {}
        self.chapters = {}  # {chapter_num: {"draft": str, "polished": str, "check_report": dict, "retry_count": int}}
        self.vector_index = SemanticIndex()  # 可选语义索引（默认禁用/降级）
        self.state_tracker = StoryStateTracker(index=self.vector_index)  # 跨章状态（角色/伏笔/前情/历史问题）
        self.current_step = PipelineStep.INPUT
        self.status_message = "准备就绪"
        self.is_running = False
        self.current_chapter = 0
        self.total_chapters = 0
        self.logs = []  # 操作日志
        self.write_stats = {
            "total_chapters_written": 0,
            "total_retries": 0,
            "failed_chapters": [],
        }
        # skill 集成开关（默认开启；node 缺失时预检自动跳过）
        self.skills_enabled = True
        self.review_enabled = True
        self.precheck_enabled = True
        # 短篇小说模式（独立于长篇流水线）
        self.short_story = {
            "framework": None,
            "draft": "",
            "polished": "",
            "review_report": {},
            "precheck": {},
        }

    # ============================================================
    # v0.2 修复 #4：数据持久化与恢复
    # ============================================================

    DATA_DIR = "data"

    def save_state(self):
        """保存当前状态到磁盘（线程安全）"""
        with self._lock:
            try:
                os.makedirs(self.DATA_DIR, exist_ok=True)

                # 保存故事圣经
                self.bible.to_json(os.path.join(self.DATA_DIR, "story_bible.json"))

                # 保存大纲
                with open(os.path.join(self.DATA_DIR, "outline.json"), "w", encoding="utf-8") as f:
                    json.dump(self.outline, f, ensure_ascii=False, indent=2)

                # 保存章节内容
                with open(os.path.join(self.DATA_DIR, "chapters.json"), "w", encoding="utf-8") as f:
                    json.dump(self.chapters, f, ensure_ascii=False, indent=2)

                # 保存元状态
                meta = {
                    "premise": self.premise,
                    "genre": self.genre,
                    "current_step": self.current_step,
                    "current_chapter": self.current_chapter,
                    "total_chapters": self.total_chapters,
                    "status_message": self.status_message,
                    "write_stats": self.write_stats,
                    "logs": self.logs[-50:],  # 只保留最近50条日志
                }
                with open(os.path.join(self.DATA_DIR, "project_meta.json"), "w", encoding="utf-8") as f:
                    json.dump(meta, f, ensure_ascii=False, indent=2)

                # 保存跨章状态追踪器
                with open(os.path.join(self.DATA_DIR, "state.json"), "w", encoding="utf-8") as f:
                    json.dump(self.state_tracker.to_dict(), f, ensure_ascii=False, indent=2)

                # 保存短篇小说模式状态
                with open(os.path.join(self.DATA_DIR, "short_story.json"), "w", encoding="utf-8") as f:
                    json.dump(self.short_story, f, ensure_ascii=False, indent=2)

            except Exception as e:
                print(f"[警告] 保存状态失败: {e}")

    def load_state(self) -> bool:
        """
        从磁盘恢复状态（v0.2 修复 #4）

        Returns:
            True 如果成功恢复，False 如果没有可恢复的数据
        """
        with self._lock:
            bible_path = os.path.join(self.DATA_DIR, "story_bible.json")
            meta_path = os.path.join(self.DATA_DIR, "project_meta.json")

            if not os.path.exists(bible_path) or not os.path.exists(meta_path):
                return False

            try:
                # 恢复故事圣经
                self.bible = VersionedStoryBible.from_json(bible_path)

                # 恢复大纲
                outline_path = os.path.join(self.DATA_DIR, "outline.json")
                if os.path.exists(outline_path):
                    with open(outline_path, "r", encoding="utf-8") as f:
                        self.outline = json.load(f)

                # 恢复章节
                chapters_path = os.path.join(self.DATA_DIR, "chapters.json")
                if os.path.exists(chapters_path):
                    with open(chapters_path, "r", encoding="utf-8") as f:
                        self.chapters = json.load(f)
                        # 将键转换为整数
                        self.chapters = {int(k): v for k, v in self.chapters.items()}

                # 恢复元状态
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                self.premise = meta.get("premise", "")
                self.genre = meta.get("genre", "")
                self.current_step = meta.get("current_step", PipelineStep.IDLE)
                self.current_chapter = meta.get("current_chapter", 0)
                self.total_chapters = meta.get("total_chapters", 0)
                self.status_message = meta.get("status_message", "已从上次进度恢复")
                self.write_stats = meta.get("write_stats", self.write_stats)
                self.logs = meta.get("logs", [])

                # 恢复跨章状态追踪器
                state_path = os.path.join(self.DATA_DIR, "state.json")
                if os.path.exists(state_path):
                    with open(state_path, "r", encoding="utf-8") as f:
                        self.state_tracker = StoryStateTracker.from_dict(json.load(f))
                self.state_tracker.index = self.vector_index

                # 恢复短篇小说模式状态
                short_path = os.path.join(self.DATA_DIR, "short_story.json")
                if os.path.exists(short_path):
                    with open(short_path, "r", encoding="utf-8") as f:
                        self.short_story = json.load(f)

                # 从恢复的故事圣经重建语义索引（幂等）
                self.sync_vector_index()

                print(f"[恢复] 成功恢复项目状态 | 书名:{self.bible.meta.get('title', '未命名')} | "
                      f"已写{len(self.chapters)}章")
                return True

            except Exception as e:
                print(f"[警告] 恢复状态失败: {e}，将使用空白状态")
                return False

    def sync_vector_index(self):
        """把当前故事圣经的实体/摘要同步进向量索引（幂等，按内容去重）。"""
        if not self.vector_index.enabled:
            return
        with self._lock:
            bible = self.bible
            for c in bible.characters.values():
                self.vector_index.add(f"char:{c.id}", f"【角色】{c.to_text()}")
            for loc in bible.locations.values():
                self.vector_index.add(
                    f"loc:{loc.id}",
                    f"【地点】{loc.name}: {loc.description or ''} 重要性:{loc.significance or '无'}",
                )
            for it in bible.items.values():
                self.vector_index.add(
                    f"item:{it.id}",
                    f"【道具】{it.name}: {it.description or ''} 能力:{it.special_ability or '无'}",
                )
            for fs in bible.foreshadowings.values():
                status = "（已回收）" if fs.resolved else ""
                self.vector_index.add(
                    f"fs:{fs.id}",
                    f"【伏笔】{fs.content} 埋设于:{fs.planted_in} 提示:{fs.hint or '无'}{status}",
                )
            for num, s in bible.chapter_summaries.items():
                self.vector_index.add(f"sum:{num}", f"第{num}章 {s.title}：{s.summary}")
            if bible.world_notes:
                self.vector_index.add("world:notes", f"【世界观】{bible.world_notes}")
            if bible.style_guide:
                self.vector_index.add("world:style", f"【文风】{bible.style_guide}")


# 全局项目实例
project = NovelProject()


# ============================================================
# 流水线编排核心逻辑（v0.2：增加反馈回路）
# ============================================================

def run_pipeline_step(step: str, **kwargs):
    """执行流水线的某个步骤，在后台线程中运行"""
    project.is_running = True

    try:
        if step == "world_build":
            _execute_world_build(**kwargs)

        elif step == "outline":
            _execute_outline(**kwargs)

        elif step == "write_chapter":
            _execute_write_chapter_with_retry(**kwargs)

        elif step == "confirm_step":
            _execute_confirm(**kwargs)

    except Exception as e:
        with project._lock:
            project.current_step = PipelineStep.ERROR
            project.status_message = f"错误：{str(e)}"
        _log(f"❌ 错误：{str(e)}")
        import traceback
        traceback.print_exc()
    finally:
        project.is_running = False


def _execute_world_build(**kwargs):
    """世界构建步骤"""
    with project._lock:
        project.current_step = PipelineStep.WORLD_BUILDING
        project.status_message = "正在构建世界..."
    _log("🌍 开始构建世界...")

    agent = WorldBuilderAgent(temperature=0.9)
    result = agent.run(premise=project.premise, genre=project.genre)

    # 将结果写入故事圣经
    _import_world_to_bible(result)

    # 创建版本快照
    with project._lock:
        project.bible.checkpoint("世界构建完成")
        project.bible.to_json("data/story_bible.json")
        project.current_step = PipelineStep.WORLD_BUILT
        project.status_message = "世界观构建完成！请确认后继续。"

    _log(f"✅ 世界观构建完成：{result.get('world_name', '未知世界')}")
    project.save_state()


def _execute_outline(**kwargs):
    """大纲生成步骤"""
    with project._lock:
        project.current_step = PipelineStep.OUTLINING
        project.status_message = "正在生成大纲..."
    _log("📋 开始生成大纲...")

    agent = OutlineAgent(temperature=0.8)
    world_dict = project.bible.to_dict()
    chapter_count = kwargs.get("chapter_count", 10)

    result = agent.run(
        world_setting=world_dict,
        chapter_count=chapter_count,
        volume_count=kwargs.get("volume_count", 1),
    )

    with project._lock:
        project.outline = result
        project.total_chapters = chapter_count

        # 保存大纲
        with open("data/outline.json", "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        # 创建版本快照
        project.bible.checkpoint(f"大纲生成完成 ({chapter_count}章)")
        project.current_step = PipelineStep.OUTLINE_GENERATED
        project.status_message = f"大纲生成完成！共 {chapter_count} 章。请确认后开始写作。"

    _log(f"✅ 大纲生成完成：{chapter_count} 章")
    project.save_state()


def _execute_write_chapter_with_retry(chapter_num: int = None, **kwargs):
    """
    带反馈回路的章节写作（v0.2 核心改进）

    改进点：
    - Checker 发现 error 级问题时，将 issues 作为 revision_notes 传给 Writer 重写
    - 最多重试 MAX_RETRIES 次
    - 记录重试统计
    """
    chapter_num = chapter_num or kwargs.get("chapter_num", 1)

    with project._lock:
        project.current_chapter = chapter_num
        project.current_step = PipelineStep.WRITING
        project.status_message = f"正在撰写第 {chapter_num} 章..."
    _log(f"✍️ 开始写第 {chapter_num} 章...")

    # 获取本章细纲
    chapter_outline = _get_chapter_outline(chapter_num)

    # 构建上下文（使用增强版的压缩功能）
    context = project.bible.build_context_for_chapter(
        chapter_num=chapter_num,
        chapter_outline=json.dumps(chapter_outline, ensure_ascii=False),
        index=project.vector_index,
    )

    writer = WriterAgent(temperature=0.85)
    checker = CheckerAgent(temperature=0.3)
    polisher = PolisherAgent(temperature=0.4)

    draft = None
    check_result = None
    retry_count = 0

    # 首次检查前把故事圣经角色同步进追踪器，并装配 Checker 的跨章入参
    _seed_tracker_characters()
    checker_inputs = project.state_tracker.build_checker_inputs()

    for attempt in range(project.MAX_RETRIES + 1):  # 初始写 + 最多3次重写
        if attempt > 0:
            retry_count = attempt
            with project._lock:
                project.status_message = f"⚠️ 第 {chapter_num} 章检查未通过，正在进行第 {attempt} 次重写..."
            _log(f"🔄 第 {chapter_num} 章第 {attempt} 次重写...")

            # 构建修改建议文本
            revision_notes = _build_revision_notes(check_result, chapter_num)

            # 重写：传入 revision_notes
            draft = writer.run(
                chapter_outline=chapter_outline,
                context=context,
                revision_notes=revision_notes,
                original_text=draft,
            )
        else:
            # 首次写作
            draft = writer.run(
                chapter_outline=chapter_outline,
                context=context,
            )

        with project._lock:
            project.chapters[chapter_num] = {
                "draft": draft,
                "polished": "",
                "check_report": None,
                "retry_count": retry_count,
            }

        _log(f"📝 第 {chapter_num} 章初稿完成 ({len(draft)} 字)" +
             (f" [重写 #{retry_count}]" if retry_count > 0 else ""))

        # 检查
        with project._lock:
            project.status_message = f"正在检查第 {chapter_num} 章..."
        _log(f"🔍 检查第 {chapter_num} 章...")
        bible_summary = _build_bible_summary_for_check()
        check_result = checker.run(
            chapter_text=draft,
            chapter_num=chapter_num,
            story_bible_summary=bible_summary,
            **checker_inputs,
        )

        with project._lock:
            project.chapters[chapter_num]["check_report"] = check_result
        needs_revision = check_result.get(
            "needs_revision", not check_result.get("passed", True)
        )

        if not needs_revision:
            score = check_result.get('overall_quality_score', '?')
            _log(f"✅ 第 {chapter_num} 章检查通过 (评分: {score})" +
                 (f" [经过 {retry_count} 次重写]" if retry_count > 0 else ""))
            break  # 通过了，退出循环
        else:
            errors = [i for i in check_result.get("issues", []) if i.get("severity") == "error"]
            warnings = [i for i in check_result.get("issues", []) if i.get("severity") == "warning"]
            _log(f"⚠️ 第 {chapter_num} 章需要修订: {len(errors)} 个错误, {len(warnings)} 个警告" +
                 f", 评分 {check_result.get('overall_quality_score', '?')}")

            if attempt < project.MAX_RETRIES:
                continue  # 继续重写
            else:
                _log(f"❌ 第 {chapter_num} 章经过 {project.MAX_RETRIES} 次重写仍需要修订，使用当前版本")
                with project._lock:
                    project.write_stats["failed_chapters"].append(chapter_num)
                break  # 达到最大重试次数，使用当前版本

    # 更新重试统计
    if retry_count > 0:
        with project._lock:
            project.write_stats["total_retries"] += retry_count

    # 润色（无论是否通过都润色）
    with project._lock:
        project.status_message = f"正在润色第 {chapter_num} 章..."
    _log(f"💎 润色第 {chapter_num} 章...")

    polished = polisher.run(
        text=draft,
        style_guide=project.bible.style_guide,
        quality_score=check_result.get("overall_quality_score") if check_result else None,
        protected_terms=_collect_protected_terms(),
        strict=True,
        deslop=True,
        deslop_rules=_load_polisher_rules(),
    )

    with project._lock:
        project.chapters[chapter_num]["polished"] = polished
    _log(f"💎 第 {chapter_num} 章润色完成")

    # skill 集成：多视角审查 + 确定性预检（仅记录，不阻塞流水线）
    _run_chapter_review(chapter_num, polished, checker_inputs)
    _run_chapter_precheck(chapter_num, polished)

    # 提取摘要并更新故事圣经
    _extract_and_update_summary(chapter_num, draft)

    # 回写跨章状态追踪器（伏笔台账/前情摘要/历史问题），并同步故事圣经
    if check_result:
        _writeback_state(chapter_num, check_result)

    # 创建版本快照
    with project._lock:
        project.bible.checkpoint(f"第{chapter_num}章完成")
        project.bible.to_json("data/story_bible.json")
        project.current_step = PipelineStep.CHAPTER_DONE
        project.status_message = f"第 {chapter_num} 章完成！"
        project.write_stats["total_chapters_written"] += 1

    project.save_state()


def _execute_confirm(step: str = "", **kwargs):
    """人工确认步骤"""
    if step == "world":
        _log("✅ 用户确认世界观，准备生成大纲...")
        with project._lock:
            project.current_step = PipelineStep.INPUT  # 等待下一步操作
    elif step == "outline":
        _log("✅ 用户确认大纲，准备开始写作...")
        with project._lock:
            project.current_step = PipelineStep.INPUT
    elif step == "chapter":
        _log("✅ 用户确认章节，可继续下一章...")
        with project._lock:
            project.current_step = PipelineStep.INPUT


# ============================================================
# 辅助函数
# ============================================================

def _import_world_to_bible(world_data: dict):
    """将世界构建 Agent 的输出导入故事圣经"""
    with project._lock:
        project.bible.meta["title"] = world_data.get("world_name", "未命名")
        project.bible.meta["genre"] = world_data.get("genre", "")
        project.bible.world_notes = (
            f"力量体系：{world_data.get('power_system', '')}\n\n"
            f"核心冲突：{world_data.get('core_conflict', '')}\n\n"
            f"主题：{' / '.join(world_data.get('themes', []))}"
        )

        if world_data.get("style_notes"):
            project.bible.style_guide = world_data["style_notes"]

        # 导入角色
        for char_data in world_data.get("characters", []):
            project.bible.add_character(**char_data)

        # 导入地点
        for loc_data in world_data.get("geography", []):
            project.bible.add_location(**loc_data)

        # 导入势力信息到世界备注
        factions = world_data.get("factions", [])
        if factions:
            project.bible.world_notes += "\n\n## 势力\n"
            for f in factions:
                project.bible.world_notes += f"- **{f['name']}** 首领:{f['leader']} 目标:{f['goal']}\n"

    # 同步角色/地点/设定进语义索引
    project.sync_vector_index()


def _get_chapter_outline(chapter_num: int) -> dict:
    """从大纲中获取指定章节的细纲。

    若章号超出当前大纲范围（续写场景），自动追加一条占位细纲并扩展总章数，
    使基于前文的续写有基本指引且不会写乱章号。
    """
    volumes = project.outline.get("volumes", [])
    for vol in volumes:
        for ch in vol.get("chapters", []):
            if ch.get("num") == chapter_num:
                return ch

    return _append_placeholder_outline(chapter_num, volumes)


def _append_placeholder_outline(chapter_num: int, volumes: list) -> dict:
    """为续写章追加占位细纲，写入末卷并按 num 排序，同时扩展总章数并落盘。"""
    placeholder = {
        "num": chapter_num,
        "title": f"第{chapter_num}章",
        "scenes": [],
        "conflict": "",
        "hook": "",
        "summary_type": "续写扩展章",
    }

    with project._lock:
        if not volumes:
            volumes = [{"volume_num": 1, "volume_title": "续写卷", "chapters": []}]
            project.outline["volumes"] = volumes
        target_vol = volumes[-1]
        target_vol.setdefault("chapters", []).append(placeholder)
        # 保持章节按 num 排序，避免写入乱序
        target_vol["chapters"].sort(key=lambda c: c.get("num", 0))

        if project.total_chapters < chapter_num:
            project.total_chapters = chapter_num

        # 更新大纲与元状态（outline.json / chapters.json / state.json 一起落盘）
        project.save_state()
    return placeholder


def _collect_protected_terms() -> list:
    """收集需在润色时原样保留的专有名词（角色/别名/地点/道具）"""
    terms = []
    with project._lock:
        for c in project.bible.characters.values():
            terms.append(c.name)
            terms.extend(c.alias)
        for loc in project.bible.locations.values():
            terms.append(loc.name)
        for it in project.bible.items.values():
            terms.append(it.name)
    return [t for t in dict.fromkeys(terms) if t]


def _load_polisher_rules() -> str:
    """加载去AI味规则（skill 知识，缺失回退内置摘要）"""
    text, _ = polisher_rules()
    return text


def _detect_platform() -> str:
    """按书名/题材粗判目标平台，供审查 rubric 选择。"""
    with project._lock:
        genre = (project.genre or "").strip()
        title = (project.bible.meta.get("title") or "").strip()
    blob = f"{genre} {title}".lower()
    if any(k in blob for k in ("番茄", "追读", "短篇", "盐言", "知乎")):
        return "zhihu" if ("知乎" in blob or "盐言" in blob or "短篇" in blob) else "fanqie"
    if any(k in blob for k in ("起点", "玄幻", "修仙", "仙侠", "都市", "连载")):
        return "qidian"
    return "generic"


def _run_chapter_review(chapter_num: int, text: str, checker_inputs: dict) -> dict:
    """对成稿跑多视角审查（story-review），结果存 chapters[num]["review_report"]。

    只记录不阻塞：verdict 非 APPROVE 仅影响报告展示，不改变 MAX_RETRIES 流程。
    """
    if not project.skills_enabled or not project.review_enabled:
        return {}

    try:
        reviewer = ReviewerAgent(temperature=0.3)
        rubric_text, rubric_src = _build_review_rubric()
        report = reviewer.run(
            chapter_text=text,
            chapter_num=chapter_num,
            rubric=rubric_text,
            rubric_source=rubric_src,
            character_states=checker_inputs.get("character_states"),
            open_foreshadowing=checker_inputs.get("open_foreshadowing"),
            prev_chapter_digest=checker_inputs.get("prev_chapter_digest"),
        )
        report["rubric_source"] = rubric_src
        with project._lock:
            project.chapters.setdefault(chapter_num, {})["review_report"] = report
        _log(f"🔎 第 {chapter_num} 章多视角审查完成：{report.get('verdict', '?')}"
             f"（{len(report.get('findings', []))} 条 findings）")
        return report
    except Exception as e:
        _log(f"⚠️ 第 {chapter_num} 章多视角审查失败：{e}")
        return {}


def _build_review_rubric() -> tuple[str, str]:
    """组装审查基准包：(rubric 文本, 来源标注)。"""
    platform = _detect_platform()
    if platform == "generic":
        text, source = reviewer_rules()
    else:
        platform_text, p_source = platform_rubric(platform)
        core_text, core_source = reviewer_rules()
        text = f"{platform_text}\n\n{core_text}"
        source = "file" if (p_source == "file" or core_source == "file") else (
            "embedded fallback" if (p_source == "embedded" or core_source == "embedded")
            else "missing"
        )
    return text, source


def _run_chapter_precheck(chapter_num: int, text: str) -> dict:
    """对成稿跑 node 确定性预检（story-review scripts），结果存 chapters[num]["precheck"]。"""
    if not project.skills_enabled or not project.precheck_enabled:
        return {}

    try:
        result = run_precheck(text)
        with project._lock:
            project.chapters.setdefault(chapter_num, {})["precheck"] = result
        if result.get("findings"):
            _log(f"🔬 第 {chapter_num} 章预检发现 {len(result['findings'])} 条机械问题")
        else:
            _log(f"🔬 第 {chapter_num} 章预检通过（{', '.join(result.get('scripts_run', [])) or '无脚本'}）")
        return result
    except Exception as e:
        _log(f"⚠️ 第 {chapter_num} 章预检失败：{e}")
        return {}


# ============================================================
# 短篇小说模式（story-short-write 集成）
# ============================================================

def _short_run_framework(premise: str, emotion: str, genre: str,
                         target_words: int, platform: str) -> dict:
    """构思短篇框架并存入 project.short_story。"""
    with project._lock:
        ss = project.short_story
        ss["premise"] = premise
        ss["emotion"] = emotion
        ss["genre"] = genre
        ss["target_words"] = target_words
        ss["platform"] = platform

    agent = ShortStoryAgent(temperature=0.85)
    framework = agent.run_framework(
        premise=premise, emotion=emotion, genre=genre,
        target_words=target_words, platform=platform,
    )
    if not isinstance(framework, dict) or framework.get("parse_error"):
        raise ValueError("短篇框架解析失败，请重试")
    with project._lock:
        project.short_story["framework"] = framework
        project.short_story["draft"] = ""
        project.short_story["polished"] = ""
        project.short_story["review_report"] = {}
        project.short_story["precheck"] = {}
    _log(f"📐 短篇框架生成：{framework.get('title', '未命名')}"
         f" | 反转：{framework.get('core_reversal', {}).get('type', '?')}")
    return framework


def _short_run_write() -> str:
    """按框架成文并存入 project.short_story。"""
    with project._lock:
        framework = project.short_story.get("framework")
    if not framework:
        raise ValueError("请先构思短篇框架")
    agent = ShortStoryAgent(temperature=0.85)
    draft = agent.run_write(framework)
    with project._lock:
        project.short_story["draft"] = draft
    _log(f"✍️ 短篇成文完成：{len(draft)} 字")
    return draft


def _short_run_polish() -> str:
    """去AI味润色短篇正文（复用 PolisherAgent 的 deslop 能力）。"""
    with project._lock:
        draft = project.short_story.get("draft", "")
    if not draft:
        raise ValueError("请先成文")
    polisher = PolisherAgent()
    polished = polisher.run(
        text=draft,
        deslop=True,
        deslop_rules=_load_polisher_rules(),
        strict=False,
    )
    with project._lock:
        project.short_story["polished"] = polished
    _log(f"✨ 短篇润色完成：{len(polished)} 字")
    return polished


def _short_run_review() -> dict:
    """对短篇跑多视角审查（复用 ReviewerAgent + 短篇题材风格包 rubric）。"""
    if not project.skills_enabled or not project.review_enabled:
        return {}
    with project._lock:
        text = project.short_story.get("polished") or project.short_story.get("draft", "")
        genre = project.short_story.get("genre", "")
    if not text:
        raise ValueError("请先成文或润色")
    reviewer = ReviewerAgent(temperature=0.3)
    rubric_text, rubric_src = _build_short_review_rubric(genre)
    report = reviewer.run(
        chapter_text=text,
        chapter_num=1,
        rubric=rubric_text,
        rubric_source=rubric_src,
    )
    report["rubric_source"] = rubric_src
    with project._lock:
        project.short_story["review_report"] = report
    _log(f"🔎 短篇审查完成：{report.get('verdict', '?')}"
         f"（{len(report.get('findings', []))} 条 findings）")
    return report


def _build_short_review_rubric(genre: str = "") -> tuple[str, str]:
    """组装短篇审查基准：题材风格包 + 通用审查规则。"""
    style_text, style_source = genre_style_rules(genre)
    core_text, core_source = reviewer_rules()
    if style_text:
        text = f"{style_text}\n\n{core_text}"
        source = "file" if (style_source == "file" or core_source == "file") else (
            "embedded fallback" if (style_source == "embedded" or core_source == "embedded")
            else "missing"
        )
    else:
        text, source = core_text, core_source
    return text, source


def _short_run_precheck() -> dict:
    """对短篇跑 node 确定性预检。"""
    if not project.skills_enabled or not project.precheck_enabled:
        return {}
    with project._lock:
        text = project.short_story.get("polished") or project.short_story.get("draft", "")
    if not text:
        raise ValueError("请先成文或润色")
    result = run_precheck(text)
    with project._lock:
        project.short_story["precheck"] = result
    if result.get("findings"):
        _log(f"🔬 短篇预检发现 {len(result['findings'])} 条机械问题")
    else:
        _log(f"🔬 短篇预检通过（{', '.join(result.get('scripts_run', [])) or '无脚本'}）")
    return result


def _build_bible_summary_for_check() -> str:
    """为检查 Agent 构建简化的故事圣经摘要"""
    parts = []
    with project._lock:
        parts.append(f"书名：{project.bible.meta['title']}")
        parts.append(f"角色列表：{', '.join(c.name for c in project.bible.characters.values())}")

        unresolved = project.bible.get_unresolved_foreshadowings()
        if unresolved:
            parts.append(f"未回收伏笔({len(unresolved)}条)：")
            for fs in unresolved[:5]:
                parts.append(f"  - [{fs.planted_in}] {fs.content}")

        recent = project.bible.get_recent_summaries(3)
        if recent:
            parts.append("前情提要：")
            for s in recent:
                parts.append(f"  第{s.chapter_num}章: {s.summary}")

    return "\n".join(parts)


def _seed_tracker_characters() -> None:
    """首次进入检查前，把故事圣经中的角色同步为追踪器的初始状态。"""
    with project._lock:
        if project.state_tracker.character_states:
            return
        for c in project.bible.characters.values():
            project.state_tracker.upsert_character(c.name, alive=c.status != "dead")


def _build_revision_notes(check_result: dict, chapter_num: int) -> str:
    """把检查结果汇总为重写反馈；评分过低但无具体 issue 时给出整体提示。"""
    lines = []
    for i in check_result.get("issues", []):
        if i.get("severity") in ("error", "warning"):
            lines.append(f"- [{i.get('severity', '?')}] {i.get('detail', '')}"
                         f"\n  建议：{i.get('suggestion', '')}")
    if not lines and check_result.get("overall_quality_score", 10) < QUALITY_FLOOR:
        score = check_result["overall_quality_score"]
        lines.append(f"- [整体质量] 综合评分 {score:.1f} 低于阈值 {QUALITY_FLOOR}，"
                     f"请针对文笔、节奏或结构薄弱处提升整体质量。")
    return ("以下是检查报告发现的问题，请在保持原有通过部分的基础上修改：\n\n"
            + "\n".join(lines))


def _writeback_state(chapter_num: int, check_result: dict) -> None:
    """检查定稿后回写追踪器（伏笔台账/前情摘要/历史问题），并同步故事圣经。"""
    with project._lock:
        s = project.bible.chapter_summaries.get(chapter_num)
        digest = ""
        if s:
            digest = s.summary or "；".join(s.key_events or [])

        tracker = project.state_tracker
        tracker.ingest_report(chapter_num, check_result, digest)

        # 角色状态变化（来自摘要提取的 ChapterSummary.character_state_changes）
        if s and s.character_state_changes:
            for name, change in s.character_state_changes.items():
                fields = change if isinstance(change, dict) else {"状态": change}
                tracker.upsert_character(str(name), **fields)

        # 伏笔台账与故事圣经双向一致（埋设/回收）
        for note in check_result.get("foreshadowing_notes", []):
            if note.startswith("【埋设】"):
                content = note.removeprefix("【埋设】").strip()
                if not any(
                    not fs.resolved and StoryStateTracker._similar(
                        fs.content, content, index=project.vector_index)
                    for fs in project.bible.foreshadowings.values()
                ):
                    project.bible.add_foreshadowing(content=content,
                                                    planted_in=f"第{chapter_num}章")
            elif note.startswith("【回收】"):
                content = note.removeprefix("【回收】").strip()
                for fs in project.bible.foreshadowings.values():
                    if not fs.resolved and StoryStateTracker._similar(
                            fs.content, content, index=project.vector_index):
                        project.bible.resolve_foreshadowing(fs.id, f"第{chapter_num}章")
                        break

    # 伏笔台账变化同步进语义索引
    project.sync_vector_index()


def _extract_and_update_summary(chapter_num: int, text: str):
    """提取章节摘要并更新故事圣经"""
    summarizer = ChapterSummarizerAgent(temperature=0.3)

    try:
        # 大纲标题优先（续写占位细纲的标题是通用「第N章」，交给正则从正文提取）
        outline = _get_chapter_outline(chapter_num)
        outline_title = None
        if outline and outline.get("summary_type") != "续写扩展章":
            outline_title = outline.get("title") or None
        summary_data = summarizer.run(
            chapter_text=text, chapter_num=chapter_num, title=outline_title
        )
        if not isinstance(summary_data, dict) or summary_data.get("parse_error"):
            raise ValueError("摘要解析失败")
        summary = ChapterSummary(**summary_data)
        with project._lock:
            project.bible.add_chapter_summary(summary)
    except Exception as e:
        title = f"第{chapter_num}章"
        short_text = text[:200] + "..." if len(text) > 200 else text
        summary = ChapterSummary(
            chapter_num=chapter_num,
            title=title,
            summary=f"[自动摘要] {short_text}",
        )
        with project._lock:
            project.bible.add_chapter_summary(summary)

    # 章节摘要同步进语义索引（供前情提要语义召回）
    project.sync_vector_index()


def _log(message: str):
    """添加日志"""
    from datetime import datetime
    timestamp = datetime.now().strftime("%H:%M:%S")
    with project._lock:
        project.logs.append(f"[{timestamp}] {message}")
        if len(project.logs) > 100:
            project.logs = project.logs[-100:]


# ============================================================
# Web 路由
# ============================================================

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/start", methods=["POST"])
def api_start():
    """初始化项目：接收创意和类型"""
    data = request.json
    with project._lock:
        project.premise = data.get("premise", "")
        project.genre = data.get("genre", "")
        project.reset()
        project.premise = data.get("premise", "")
        project.genre = data.get("genre", "")
    _log(f"🚀 新项目启动 | 类型:{project.genre} | 创意:{project.premise[:50]}...")
    return jsonify({"status": "ok"})


@app.route("/api/build-world", methods=["POST"])
def api_build_world():
    """触发世界构建"""
    if project.is_running:
        return jsonify({"error": "正在运行中，请等待"}), 400

    thread = threading.Thread(target=run_pipeline_step, args=("world_build",))
    thread.start()
    return jsonify({"status": "started"})


@app.route("/api/generate-outline", methods=["POST"])
def api_generate_outline():
    """触发大纲生成"""
    if project.is_running:
        return jsonify({"error": "正在运行中，请等待"}), 400

    data = request.json or {}
    chapter_count = data.get("chapter_count", 10)

    thread = threading.Thread(
        target=run_pipeline_step,
        args=("outline",),
        kwargs={"chapter_count": chapter_count},
    )
    thread.start()
    return jsonify({"status": "started"})


@app.route("/api/write-chapter/<int:chapter_num>", methods=["POST"])
def api_write_chapter(chapter_num):
    """触发指定章节的写作（带反馈回路）"""
    if project.is_running:
        return jsonify({"error": "正在运行中，请等待"}), 400

    thread = threading.Thread(
        target=run_pipeline_step,
        args=("write_chapter",),
        kwargs={"chapter_num": chapter_num},
    )
    thread.start()
    return jsonify({"status": "started"})


@app.route("/api/review/<int:chapter_num>", methods=["POST"])
def api_review_chapter(chapter_num):
    """对已写作章节做多视角审查（story-review），同步返回报告。"""
    if project.is_running:
        return jsonify({"error": "正在运行中，请等待"}), 400

    with project._lock:
        chapter = project.chapters.get(chapter_num)
    if not chapter:
        return jsonify({"error": f"第 {chapter_num} 章不存在，请先写作"}), 404

    text = chapter.get("polished") or chapter.get("draft") or ""
    if not text:
        return jsonify({"error": "章节正文为空"}), 400

    _seed_tracker_characters()
    checker_inputs = project.state_tracker.build_checker_inputs()
    report = _run_chapter_review(chapter_num, text, checker_inputs)
    if not report:
        return jsonify({"error": "审查未执行（skill 已关闭或发生异常）"}), 400
    project.save_state()
    return jsonify({"chapter": chapter_num, "review_report": report})


@app.route("/api/precheck/<int:chapter_num>", methods=["POST"])
def api_precheck_chapter(chapter_num):
    """对已写作章节做 node 确定性预检（story-review scripts）。"""
    if project.is_running:
        return jsonify({"error": "正在运行中，请等待"}), 400

    with project._lock:
        chapter = project.chapters.get(chapter_num)
    if not chapter:
        return jsonify({"error": f"第 {chapter_num} 章不存在，请先写作"}), 404

    text = chapter.get("polished") or chapter.get("draft") or ""
    if not text:
        return jsonify({"error": "章节正文为空"}), 400

    result = _run_chapter_precheck(chapter_num, text)
    project.save_state()
    return jsonify({"chapter": chapter_num, "precheck": result})


# ============================================================
# 短篇小说模式 API
# ============================================================

@app.route("/api/short/architect", methods=["POST"])
def api_short_architect():
    """构思短篇框架"""
    if project.is_running:
        return jsonify({"error": "正在运行中，请等待"}), 400

    data = request.get_json(silent=True) or {}
    premise = (data.get("premise") or "").strip()
    if not premise:
        return jsonify({"error": "请提供短篇创意（premise）"}), 400

    try:
        framework = _short_run_framework(
            premise=premise,
            emotion=(data.get("emotion") or "").strip(),
            genre=(data.get("genre") or "").strip(),
            target_words=int(data.get("target_words") or 8000),
            platform=(data.get("platform") or "").strip(),
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        _log(f"❌ 短篇构思失败：{e}")
        return jsonify({"error": f"短篇构思失败：{e}"}), 500

    project.save_state()
    return jsonify({"framework": framework})


@app.route("/api/short/write", methods=["POST"])
def api_short_write():
    """按框架成文"""
    if project.is_running:
        return jsonify({"error": "正在运行中，请等待"}), 400

    try:
        draft = _short_run_write()
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        _log(f"❌ 短篇成文失败：{e}")
        return jsonify({"error": f"短篇成文失败：{e}"}), 500

    project.save_state()
    return jsonify({"draft": draft, "word_count": len(draft)})


@app.route("/api/short/polish", methods=["POST"])
def api_short_polish():
    """去AI味润色短篇"""
    if project.is_running:
        return jsonify({"error": "正在运行中，请等待"}), 400

    try:
        polished = _short_run_polish()
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        _log(f"❌ 短篇润色失败：{e}")
        return jsonify({"error": f"短篇润色失败：{e}"}), 500

    project.save_state()
    return jsonify({"polished": polished, "word_count": len(polished)})


@app.route("/api/short/review", methods=["POST"])
def api_short_review():
    """对短篇跑多视角审查"""
    if project.is_running:
        return jsonify({"error": "正在运行中，请等待"}), 400

    try:
        report = _short_run_review()
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        _log(f"❌ 短篇审查失败：{e}")
        return jsonify({"error": f"短篇审查失败：{e}"}), 500

    project.save_state()
    return jsonify({"review_report": report})


@app.route("/api/short/precheck", methods=["POST"])
def api_short_precheck():
    """对短篇跑 node 确定性预检"""
    if project.is_running:
        return jsonify({"error": "正在运行中，请等待"}), 400

    try:
        result = _short_run_precheck()
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        _log(f"❌ 短篇预检失败：{e}")
        return jsonify({"error": f"短篇预检失败：{e}"}), 500

    project.save_state()
    return jsonify({"precheck": result})


@app.route("/api/short/status", methods=["GET"])
def api_short_status():
    """获取短篇小说模式当前状态"""
    with project._lock:
        ss = project.short_story
        return jsonify({
            "framework": ss.get("framework"),
            "draft": ss.get("draft", ""),
            "draft_word_count": len(ss.get("draft", "")),
            "polished": ss.get("polished", ""),
            "polished_word_count": len(ss.get("polished", "")),
            "review_report": ss.get("review_report", {}),
            "precheck": ss.get("precheck", {}),
            "premise": ss.get("premise", ""),
            "emotion": ss.get("emotion", ""),
            "genre": ss.get("genre", ""),
            "target_words": ss.get("target_words", 8000),
            "platform": ss.get("platform", ""),
        })


@app.route("/api/write-all", methods=["POST"])
def api_write_all():
    """逐章写作全部内容"""
    if project.is_running:
        return jsonify({"error": "正在运行中，请等待"}), 400

    def write_all_chapters():
        total = project.total_chapters or len(
            project.outline.get("volumes", [{}])[0].get("chapters", [])
        )
        for ch in range(1, total + 1):
            run_pipeline_step("write_chapter", chapter_num=ch)
            # 短暂暂停，避免请求过快
            time.sleep(0.5)

        with project._lock:
            project.current_step = PipelineStep.DONE
            project.status_message = "全部章节写作完成！"
            stats = project.write_stats
        _log(f"🎉 全部章节写作完成！" +
             f"共 {stats['total_chapters_written']} 章，" +
             f"重写 {stats['total_retries']} 次，" +
             f"失败 {len(stats['failed_chapters'])} 章")
        project.save_state()

    thread = threading.Thread(target=write_all_chapters)
    thread.start()
    return jsonify({"status": "started"})


@app.route("/api/confirm", methods=["POST"])
def api_confirm():
    """人工确认步骤"""
    data = request.json or {}
    step = data.get("step", "")

    valid_steps = {"world", "outline", "chapter"}
    if step not in valid_steps:
        return jsonify({"error": f"无效的确认步骤: {step}"}), 400

    if project.is_running:
        return jsonify({"error": "正在运行中，请等待"}), 400

    thread = threading.Thread(target=run_pipeline_step, args=("confirm_step",), kwargs={"step": step})
    thread.start()
    return jsonify({"status": "confirmed"})


# ============================================================
# 流式输出端点（v0.2 新增）
# ============================================================

@app.route("/api/stream-write/<int:chapter_num>", methods=["POST"])
def api_stream_write(chapter_num):
    """
    流式写作端点 —— 使用 SSE 实时返回生成的内容

    改进点：用户可以实时看到写作进度，无需等待整章完成
    """
    if project.is_running:
        return jsonify({"error": "正在运行中，请等待"}), 400

    def generate():
        import json as json_mod

        yield f"data: {json_mod.dumps({'type': 'start', 'chapter': chapter_num}, ensure_ascii=False)}\n\n"

        try:
            # 获取细纲和上下文
            chapter_outline = _get_chapter_outline(chapter_num)
            context = project.bible.build_context_for_chapter(
                chapter_num=chapter_num,
                chapter_outline=json_mod.dumps(chapter_outline, ensure_ascii=False),
                index=project.vector_index,
            )

            writer = WriterAgent(temperature=0.85)

            # 流式调用 LLM
            full_content = []
            for chunk in writer._call_llm_stream(
                    user_msg=(
                            f"请根据以下大纲和设定，撰写完整的小说章节。\n\n"
                            f"## 故事设定与上下文\n{context}\n\n"
                            f"## 本章大纲\n{json_mod.dumps(chapter_outline, ensure_ascii=False, indent=2)}\n\n"
                            f"请先输出【写作笔记】完成四步构思，再输出【正文】。\n"
                            f"展示而非讲述，钩子强度以大纲 hook_type 为准。"
                    ),
            ):
                full_content.append(chunk)
                yield f"data: {json_mod.dumps({'type': 'chunk', 'content': chunk}, ensure_ascii=False)}\n\n"

            final_content = "".join(full_content)

        except Exception as e:
            yield f"data: {json_mod.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
            return

        # 使用 WriterAgent 的 _extract_body 剥离写作笔记，只保留正文
        final_content = WriterAgent._extract_body(final_content)

        # 保存结果
        with project._lock:
            project.chapters[chapter_num] = {
                "draft": final_content,
                "polished": "",
                "check_report": None,
                "retry_count": 0,
            }

        yield f"data: {json_mod.dumps({'type': 'done', 'full_content': final_content, 'word_count': len(final_content)}, ensure_ascii=False)}\n\n"

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache",
                             "X-Accel-Buffering": "no"})


@app.route("/api/stream-world", methods=["POST"])
def api_stream_world():
    """
    流式世界构建端点 —— 使用 SSE 实时返回生成进度

    改进点：用户可以实时看到世界构建过程，无需等待完成
    """
    if project.is_running:
        return jsonify({"error": "正在运行中，请等待"}), 400

    def generate():
        import json as json_mod

        yield f"data: {json_mod.dumps({'type': 'start', 'step': 'world_build'}, ensure_ascii=False)}\n\n"

        try:
            with project._lock:
                project.current_step = PipelineStep.WORLD_BUILDING
                project.status_message = "正在构建世界..."
            _log("🌍 开始流式构建世界...")

            agent = WorldBuilderAgent(temperature=0.9)

            # 构建用户消息（与 run 方法一致）
            user_msg = (
                f"请根据以下创意构建完整的小说世界观。\n"
                f"## 创意 premise\n{project.premise}\n\n"
                f"## 类型 genre\n{project.genre}"
            )

            # 流式调用 LLM
            full_content = []
            for chunk in agent._call_llm_stream(user_msg):
                full_content.append(chunk)
                yield f"data: {json_mod.dumps({'type': 'chunk', 'content': chunk}, ensure_ascii=False)}\n\n"

            final_content = "".join(full_content)
            result = agent._parse_json_response(final_content)

            if isinstance(result, str) or result.get("parse_error"):
                yield f"data: {json_mod.dumps({'type': 'error', 'message': 'JSON 解析失败'}, ensure_ascii=False)}\n\n"
                return

            # 将结果写入故事圣经
            _import_world_to_bible(result)

            # 创建版本快照
            with project._lock:
                project.bible.checkpoint("世界构建完成")
                project.bible.to_json("data/story_bible.json")
                project.current_step = PipelineStep.WORLD_BUILT
                project.status_message = "世界观构建完成！请确认后继续。"

            _log(f"✅ 世界观构建完成：{result.get('world_name', '未知世界')}")
            project.save_state()

            yield f"data: {json_mod.dumps({'type': 'done', 'world': result}, ensure_ascii=False)}\n\n"

        except Exception as e:
            yield f"data: {json_mod.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
            with project._lock:
                project.current_step = PipelineStep.ERROR
                project.status_message = f"错误：{str(e)}"
            project.is_running = False

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache",
                             "X-Accel-Buffering": "no"})


@app.route("/api/stream-outline", methods=["POST"])
def api_stream_outline():
    """
    流式大纲生成端点 —— 使用 SSE 实时返回生成进度

    改进点：用户可以实时看到大纲生成过程，无需等待完成
    """
    if project.is_running:
        return jsonify({"error": "正在运行中，请等待"}), 400

    data = request.json or {}
    chapter_count = data.get("chapter_count", 10)
    volume_count = data.get("volume_count", 1) or 1

    def generate():
        import json as json_mod

        yield f"data: {json_mod.dumps({'type': 'start', 'step': 'outline', 'chapter_count': chapter_count}, ensure_ascii=False)}\n\n"

        try:
            with project._lock:
                project.current_step = PipelineStep.OUTLINING
                project.status_message = "正在生成大纲..."
            _log("📋 开始流式生成大纲...")

            agent = OutlineAgent(temperature=0.8)
            world_dict = project.bible.to_dict()

            if chapter_count > MAX_CHAPTERS_PER_CALL:
                # 长篇幅：走两阶段生成（分卷骨架 → 逐卷细纲），内部含解析重试与结构修复
                with project._lock:
                    project.status_message = f"章数较多（{chapter_count} 章），正在分两阶段生成大纲..."
                yield f"data: {json_mod.dumps({'type': 'phase', 'message': '两阶段生成：先分卷骨架，再逐卷细化章节…'}, ensure_ascii=False)}\n\n"
                try:
                    result = agent.run(
                        world_setting=world_dict,
                        chapter_count=chapter_count,
                        volume_count=volume_count,
                    )
                except Exception as e:
                    yield f"data: {json_mod.dumps({'type': 'error', 'message': f'大纲生成失败：{e}'}, ensure_ascii=False)}\n\n"
                    return
            else:
                # 短篇幅：构建用户消息（与 run 方法一致）并流式输出
                user_msg = (
                    f"请根据以下世界观设定，生成分层大纲结构。\n\n"
                    f"## 世界观设定\n{json_mod.dumps(world_dict, ensure_ascii=False, indent=2)}\n\n"
                    f"## 要求\n"
                    f"- 总章数：{chapter_count} 章\n"
                    f"- 总卷数：{volume_count} 卷\n"
                    f"- 请输出包含总纲、分卷大纲、章节细纲的完整 JSON"
                )

                full_content = []
                for chunk in agent._call_llm_stream(user_msg):
                    full_content.append(chunk)
                    yield f"data: {json_mod.dumps({'type': 'chunk', 'content': chunk}, ensure_ascii=False)}\n\n"

                final_content = "".join(full_content)
                result = agent._parse_json_response(final_content)

                if isinstance(result, str) or result.get("parse_error"):
                    yield f"data: {json_mod.dumps({'type': 'error', 'message': 'JSON 解析失败'}, ensure_ascii=False)}\n\n"
                    return

                # 输出结构校验 + 程序化修复（与 run 方法保持一致）
                issues = agent._validate_output(result, chapter_count, volume_count)
                if issues:
                    try:
                        result = agent._repair(result, chapter_count, volume_count)
                    except Exception as e:
                        yield f"data: {json_mod.dumps({'type': 'error', 'message': f'大纲结构无效：{e}'}, ensure_ascii=False)}\n\n"
                        return

            # 保存结果（两条路径共用）
            with project._lock:
                project.outline = result
                project.total_chapters = chapter_count

                # 保存大纲
                with open("data/outline.json", "w", encoding="utf-8") as f:
                    json.dump(result, f, ensure_ascii=False, indent=2)

                # 创建版本快照
                project.bible.checkpoint(f"大纲生成完成 ({chapter_count}章)")
                project.current_step = PipelineStep.OUTLINE_GENERATED
                project.status_message = f"大纲生成完成！共 {chapter_count} 章。请确认后开始写作。"

            _log(f"✅ 大纲生成完成：{chapter_count} 章")
            project.save_state()

            yield f"data: {json_mod.dumps({'type': 'done', 'outline': result}, ensure_ascii=False)}\n\n"

        except Exception as e:
            yield f"data: {json_mod.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
            with project._lock:
                project.current_step = PipelineStep.ERROR
                project.status_message = f"错误：{str(e)}"
            project.is_running = False

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache",
                             "X-Accel-Buffering": "no"})


@app.route("/api/stream-all", methods=["POST"])
def api_stream_all():
    """
    流式批量写作端点 —— 使用 SSE 实时返回每章的写作进度

    改进点：逐章流式写作，用户可以看到每一章的实时生成进度
    """
    if project.is_running:
        return jsonify({"error": "正在运行中，请等待"}), 400

    def generate():
        import json as json_mod

        total = project.total_chapters or len(
            project.outline.get("volumes", [{}])[0].get("chapters", [])
        )

        yield f"data: {json_mod.dumps({'type': 'start', 'step': 'write_all', 'total_chapters': total}, ensure_ascii=False)}\n\n"

        try:
            for ch in range(1, total + 1):
                # 发送章节开始事件
                yield f"data: {json_mod.dumps({'type': 'chapter_start', 'chapter_num': ch}, ensure_ascii=False)}\n\n"

                # 获取细纲和上下文
                chapter_outline = _get_chapter_outline(ch)
                context = project.bible.build_context_for_chapter(
                    chapter_num=ch,
                    chapter_outline=json_mod.dumps(chapter_outline, ensure_ascii=False),
                    index=project.vector_index,
                )

                writer = WriterAgent(temperature=0.85)

                # 流式调用 LLM 写作当前章节
                full_content = []
                for chunk in writer._call_llm_stream(
                        user_msg=(
                                f"请根据以下大纲和设定，撰写完整的小说章节。\n\n"
                                f"## 故事设定与上下文\n{context}\n\n"
                                f"## 本章大纲\n{json_mod.dumps(chapter_outline, ensure_ascii=False, indent=2)}\n\n"
                                f"请先输出【写作笔记】完成四步构思，再输出【正文】。\n"
                                f"展示而非讲述，钩子强度以大纲 hook_type 为准。"
                        ),
                ):
                    full_content.append(chunk)
                    yield f"data: {json_mod.dumps({'type': 'chunk', 'chapter_num': ch, 'content': chunk}, ensure_ascii=False)}\n\n"

                final_content = "".join(full_content)

                # 剥离写作笔记，只保留正文
                final_content = WriterAgent._extract_body(final_content)

                # 保存结果
                with project._lock:
                    project.chapters[ch] = {
                        "draft": final_content,
                        "polished": "",
                        "check_report": None,
                        "retry_count": 0,
                    }

                # 发送章节完成事件
                yield f"data: {json_mod.dumps({'type': 'chapter_done', 'chapter_num': ch, 'word_count': len(final_content)}, ensure_ascii=False)}\n\n"

                _log(f"📝 第 {ch}/{total} 章写作完成")

                # 短暂暂停，避免请求过快
                time.sleep(0.5)

            # 全部完成
            with project._lock:
                project.current_step = PipelineStep.DONE
                project.status_message = "全部章节写作完成！"
                stats = project.write_stats

            _log(f"🎉 全部章节写作完成！" +
                 f"共 {stats['total_chapters_written']} 章，" +
                 f"重写 {stats['total_retries']} 次，" +
                 f"失败 {len(stats['failed_chapters'])} 章")
            project.save_state()

            yield f"data: {json_mod.dumps({'type': 'done', 'stats': stats}, ensure_ascii=False)}\n\n"

        except Exception as e:
            yield f"data: {json_mod.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
            with project._lock:
                project.current_step = PipelineStep.ERROR
                project.status_message = f"错误：{str(e)}"
            project.is_running = False

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache",
                             "X-Accel-Buffering": "no"})


# ============================================================
# Token 统计 API（v0.2 新增）
# ============================================================

@app.route("/api/cost", methods=["GET"])
def api_cost():
    """获取 Token 使用统计和成本"""
    summary = token_tracker.get_summary()
    return jsonify(summary)


@app.route("/api/cost/reset", methods=["POST"])
def api_cost_reset():
    """重置 Token 统计"""
    token_tracker.reset()
    return jsonify({"status": "reset"})


# ============================================================
# Story Bible 版本控制 API（v0.2 新增）
# ============================================================

@app.route("/api/bible/versions", methods=["GET"])
def api_bible_versions():
    """获取 Story Bible 版本历史"""
    history = project.bible.get_version_history(limit=20)
    return jsonify({
        "current_version": project.bible.current_version,
        "total_versions": project.bible.version_count,
        "history": history,
    })


@app.route("/api/bible/rollback/<int:version_id>", methods=["POST"])
def api_bible_rollback(version_id):
    """回滚 Story Bible 到指定版本"""
    try:
        target = project.bible.rollback(version_id)
        project.bible.to_json("data/story_bible.json")
        project.sync_vector_index()  # 回滚后重建语义索引，保持一致
        _log(f"📦 Story Bible 已回滚到版本 {version_id}")
        return jsonify({
            "status": "rolled_back",
            "target_version": target.version_id,
            "timestamp": target.timestamp,
        })
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/bible/checkpoint", methods=["POST"])
def api_bible_checkpoint():
    """手动创建 Story Bible 快照"""
    data = request.json or {}
    reason = data.get("reason", "手动创建")
    version = project.bible.checkpoint(reason)
    return jsonify({
        "status": "checkpoint_created",
        "version_id": version.version_id,
        "timestamp": version.timestamp,
    })


# ============================================================
# 原有 API（保持兼容）
# ============================================================

@app.route("/api/status", methods=["GET"])
def api_status():
    """获取当前状态（v0.2 增强 + v0.3 续写回显）"""
    with project._lock:
        written = set(project.chapters.keys())
        next_ch = 1
        while next_ch in written:
            next_ch += 1
        return jsonify({
            "step": project.current_step,
            "message": project.status_message,
            "is_running": project.is_running,
            "current_chapter": project.current_chapter,
            "total_chapters": project.total_chapters,
            "written_chapters": list(project.chapters.keys()),
            "logs": project.logs[-20:],
            "bible_title": project.bible.meta.get("title", ""),
            "genre": project.genre,
            "character_count": len(project.bible.characters),
            "foreshadowing_count": len(project.bible.foreshadowings),
            # v0.2 新增字段
            "bible_version": project.bible.current_version,
            "write_stats": project.write_stats,
            # v0.3 续写回显字段
            "premise": project.premise,
            "next_chapter": next_ch,
            "chapter_meta": {
                num: {
                    "word_count": len(ch.get("polished") or ch.get("draft") or ""),
                    "has_polished": bool(ch.get("polished")),
                    "retry_count": ch.get("retry_count", 0),
                    "has_review": bool(ch.get("review_report")),
                    "has_precheck": bool(ch.get("precheck")),
                }
                for num, ch in project.chapters.items()
            },
            # skill 集成状态
            "skills": {
                "enabled": project.skills_enabled,
                "review_enabled": project.review_enabled,
                "precheck_enabled": project.precheck_enabled,
                "skills_dir_available": is_available("story-review"),
                "skills_dir": str(resolve_skills_dir()),
            },
        })


@app.route("/api/bible", methods=["GET"])
def api_bible():
    """获取故事圣经数据"""
    return jsonify(project.bible.to_dict())


@app.route("/api/outline", methods=["GET"])
def api_outline():
    """获取大纲数据"""
    return jsonify(project.outline)


@app.route("/api/chapter/<int:chapter_num>", methods=["GET"])
def api_get_chapter(chapter_num):
    """获取指定章节的内容"""
    ch = project.chapters.get(chapter_num)
    if not ch:
        return jsonify({"error": "章节不存在"}), 404
    return jsonify(ch)


@app.route("/api/export", methods=["GET"])
def api_export():
    """导出全部正文为文本"""
    lines = []
    for num in sorted(project.chapters.keys()):
        ch = project.chapters[num]
        content = ch.get("polished") or ch.get("draft", "")
        lines.append(content)
        lines.append("\n" + "=" * 40 + "\n")

    export_text = "\n".join(lines)

    export_path = "data/export.txt"
    os.makedirs("data", exist_ok=True)
    with open(export_path, "w", encoding="utf-8") as f:
        f.write(export_text)

    return send_from_directory("data", "export.txt", as_attachment=True,
                               download_name=f"{project.bible.meta.get('title', 'novel')}.txt")


@app.route("/api/reset", methods=["POST"])
def api_reset():
    """重置项目"""
    with project._lock:
        project.reset()
    _log("🔄 项目已重置")
    return jsonify({"status": "ok"})


# ============================================================
# 启动入口
# ============================================================

if __name__ == "__main__":
    # v0.2 修复 #4：启动时尝试恢复上次的状态
    os.makedirs("data", exist_ok=True)

    print("=" * 60)
    print("  📖 小说写作 Agent v0.2（改进版+修复版）")
    print("  访问 http://localhost:5000")
    print("-" * 60)
    print("  🆕 v0.2 改进内容：")
    print("    • Checker→Writer 反馈重写机制")
    print("    • 流式输出支持（SSE）")
    print("    • Token 成本追踪")
    print("    • Story Bible 版本控制")
    print("    • 多模型智能路由")
    print("    • Prompt 工程优化（CoT + 负面约束 + Few-Shot）")
    print("-" * 60)
    print("  🔧 v0.2 修复内容：")
    print("    • ✅ 补全 StoryBible 基类（解决 ImportError）")
    print("    • ✅ 支持 .env 配置文件加载")
    print("    • ✅ 线程安全锁保护全局状态")
    print("    • ✅ 启动时自动恢复上次进度")
    print("=" * 60)

    # 尝试恢复状态
    if project.load_state():
        print(f"\n  ✅ 已恢复上次的项目状态！")
    else:
        print(f"\n  ℹ️  未找到历史记录，将以空白状态启动")

    app.run(host="0.0.0.0", port=5000, debug=True)
