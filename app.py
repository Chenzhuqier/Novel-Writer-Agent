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
"""

import json
import os
import threading
import time
from flask import Flask, render_template, request, jsonify, send_from_directory, Response
from core.story_bible import VersionedStoryBible, ChapterSummary
from agents import (
    WorldBuilderAgent,
    OutlineAgent,
    WriterAgent,
    CheckerAgent,
    PolisherAgent,
)
from agents.base import tracker as token_tracker

app = Flask(
    __name__,
    template_folder="templates",
    static_folder="static",
)

# ============================================================
# 全局状态管理（v0.2 增强）
# ============================================================

# 流水线步骤枚举
class PipelineStep:
    IDLE = "idle"
    INPUT = "input"
    WORLD_BUILDING = "world_building"
    WORLD_BUILT = "world_built"          # 等待用户确认
    OUTLINING = "outlining"
    OUTLINE_GENERATED = "outline_generated"  # 等待用户确认
    WRITING = "writing"
    CHAPTER_DONE = "chapter_done"         # 等待用户确认
    DONE = "done"
    ERROR = "error"


class NovelProject:
    """小说项目状态（v0.2 增强）"""

    MAX_RETRIES = 3  # Checker 失败后的最大重写次数

    def __init__(self):
        self.reset()

    def reset(self):
        self.premise = ""
        self.genre = ""
        self.bible: VersionedStoryBible = VersionedStoryBible()
        self.outline = {}
        self.chapters = {}  # {chapter_num: {"draft": str, "polished": str, "check_report": dict, "retry_count": int}}
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
        project.current_step = PipelineStep.ERROR
        project.status_message = f"错误：{str(e)}"
        _log(f"❌ 错误：{str(e)}")
        import traceback
        traceback.print_exc()
    finally:
        project.is_running = False


def _execute_world_build(**kwargs):
    """世界构建步骤"""
    project.current_step = PipelineStep.WORLD_BUILDING
    project.status_message = "正在构建世界观..."
    _log("🌍 开始构建世界观...")

    agent = WorldBuilderAgent(temperature=0.9)
    result = agent.run(premise=project.premise, genre=project.genre)

    # 将结果写入故事圣经
    _import_world_to_bible(result)

    # 创建版本快照
    project.bible.checkpoint("世界构建完成")

    project.bible.to_json("data/story_bible.json")
    project.current_step = PipelineStep.WORLD_BUILT
    project.status_message = "世界观构建完成！请确认后继续。"
    _log(f"✅ 世界观构建完成：{result.get('world_name', '未知世界')}")


def _execute_outline(**kwargs):
    """大纲生成步骤"""
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


def _execute_write_chapter_with_retry(chapter_num: int = None, **kwargs):
    """
    带反馈回路的章节写作（v0.2 核心改进）

    改进点：
    - Checker 发现 error 级问题时，将 issues 作为 revision_notes 传给 Writer 重写
    - 最多重试 MAX_RETRIES 次
    - 记录重试统计
    """
    chapter_num = chapter_num or kwargs.get("chapter_num", 1)
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
    )

    writer = WriterAgent(temperature=0.85)
    checker = CheckerAgent(temperature=0.3)
    polisher = PolisherAgent(temperature=0.6)

    draft = None
    check_result = None
    retry_count = 0

    for attempt in range(project.MAX_RETRIES + 1):  # 初始写 + 最多3次重写
        if attempt > 0:
            retry_count = attempt
            project.status_message = f"⚠️ 第 {chapter_num} 章检查未通过，正在进行第 {attempt} 次重写..."
            _log(f"🔄 第 {chapter_num} 章第 {attempt} 次重写...")

            # 构建修改建议文本
            issues_text = "\n".join([
                f"- [{i.get('severity', '?')}] {i.get('detail', '')}"
                f"\n  建议：{i.get('suggestion', '')}"
                for i in check_result.get("issues", [])
                if i.get("severity") in ("error", "warning")
            ])

            # 重写：传入 revision_notes
            draft = writer.run(
                chapter_outline=chapter_outline,
                context=context,
                revision_notes=f"以下是检查报告发现的问题，请在保持原有通过部分的基础上进行修改：\n\n{issues_text}",
            )
        else:
            # 首次写作
            draft = writer.run(
                chapter_outline=chapter_outline,
                context=context,
            )

        project.chapters[chapter_num] = {
            "draft": draft,
            "polished": "",
            "check_report": None,
            "retry_count": retry_count,
        }

        _log(f"📝 第 {chapter_num} 章初稿完成 ({len(draft)} 字)" +
              (f" [重写 #{retry_count}]" if retry_count > 0 else ""))

        # 检查
        project.status_message = f"正在检查第 {chapter_num} 章..."
        _log(f"🔍 检查第 {chapter_num} 章...")
        bible_summary = _build_bible_summary_for_check()
        check_result = checker.run(
            chapter_text=draft,
            chapter_num=chapter_num,
            story_bible_summary=bible_summary,
        )

        project.chapters[chapter_num]["check_report"] = check_result
        passed = check_result.get("passed", True)

        if passed:
            score = check_result.get('overall_quality_score', '?')
            _log(f"✅ 第 {chapter_num} 章检查通过 (评分: {score})" +
                  (f" [经过 {retry_count} 次重写]" if retry_count > 0 else ""))
            break  # 通过了，退出循环
        else:
            errors = [i for i in check_result.get("issues", []) if i.get("severity") == "error"]
            warnings = [i for i in check_result.get("issues", []) if i.get("severity") == "warning"]
            _log(f"⚠️ 第 {chapter_num} 章发现 {len(errors)} 个错误, {len(warnings)} 个警告")

            if attempt < project.MAX_RETRIES:
                continue  # 继续重写
            else:
                _log(f"❌ 第 {chapter_num} 章经过 {project.MAX_RETRIES} 次重写仍有问题，使用当前版本")
                project.write_stats["failed_chapters"].append(chapter_num)
                break  # 达到最大重试次数，使用当前版本

    # 更新重试统计
    if retry_count > 0:
        project.write_stats["total_retries"] += retry_count

    # 润色（无论是否通过都润色）
    project.status_message = f"正在润色第 {chapter_num} 章..."
    _log(f"💎 润色第 {chapter_num} 章...")

    polished = polisher.run(
        text=draft,
        style_guide=project.bible.style_guide,
    )

    project.chapters[chapter_num]["polished"] = polished
    _log(f"💎 第 {chapter_num} 章润色完成")

    # 提取摘要并更新故事圣经
    _extract_and_update_summary(chapter_num, draft)

    # 创建版本快照
    project.bible.checkpoint(f"第{chapter_num}章完成")

    project.status_message = f"第 {chapter_num} 章完成！"
    project.bible.to_json("data/story_bible.json")
    project.current_step = PipelineStep.CHAPTER_DONE
    project.write_stats["total_chapters_written"] += 1


def _execute_confirm(step: str = "", **kwargs):
    """人工确认步骤"""
    if step == "world":
        _log("✅ 用户确认世界观，准备生成大纲...")
        project.current_step = PipelineStep.INPUT  # 等待下一步操作
    elif step == "outline":
        _log("✅ 用户确认大纲，准备开始写作...")
        project.current_step = PipelineStep.INPUT
    elif step == "chapter":
        _log("✅ 用户确认章节，可继续下一章...")
        project.current_step = PipelineStep.INPUT


# ============================================================
# 辅助函数
# ============================================================

def _import_world_to_bible(world_data: dict):
    """将世界构建 Agent 的输出导入故事圣经"""
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


def _get_chapter_outline(chapter_num: int) -> dict:
    """从大纲中获取指定章节的细纲"""
    volumes = project.outline.get("volumes", [])
    for vol in volumes:
        for ch in vol.get("chapters", []):
            if ch.get("num") == chapter_num:
                return ch
    return {"num": chapter_num, "title": f"第{chapter_num}章", "scenes": [], "conflict": "", "hook": ""}


def _build_bible_summary_for_check() -> str:
    """为检查 Agent 构建简化的故事圣经摘要"""
    parts = []
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


def _extract_and_update_summary(chapter_num: int, text: str):
    """提取章节摘要并更新故事圣经"""
    from agents.base import call_llm

    prompt = """你是一位小说编辑。请为以下章节提取结构化摘要。
以 JSON 格式输出：
{
  "chapter_num": 章号,
  "title": "标题",
  "summary": "200字以内摘要",
  "characters_present": ["出场角色"],
  "key_events": ["关键事件"],
  "character_state_changes": {},
  "new_foreshadowing": [],
  "resolved_foreshadowing": []
}

只输出 JSON，不要任何解释。"""

    try:
        response = call_llm(prompt, text[:3000], temperature=0.3, max_tokens=1000,
                           agent_name="SummaryExtractor", force_json=True)
        clean = response.strip()
        if clean.startswith("```"):
            lines = clean.split("\n")
            clean = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        summary_data = json.loads(clean)
        summary = ChapterSummary(**summary_data)
        project.bible.add_chapter_summary(summary)
    except Exception as e:
        title = f"第{chapter_num}章"
        short_text = text[:200] + "..." if len(text) > 200 else text
        summary = ChapterSummary(
            chapter_num=chapter_num,
            title=title,
            summary=f"[自动摘要] {short_text}",
        )
        project.bible.add_chapter_summary(summary)


def _log(message: str):
    """添加日志"""
    from datetime import datetime
    timestamp = datetime.now().strftime("%H:%M:%S")
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

        project.current_step = PipelineStep.DONE
        project.status_message = "全部章节写作完成！"
        stats = project.write_stats
        _log(f"🎉 全部章节写作完成！" +
              f"共 {stats['total_chapters_written']} 章，" +
              f"重写 {stats['total_retries']} 次，" +
              f"失败 {len(stats['failed_chapters'])} 章")

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
            )

            writer = WriterAgent(temperature=0.85)

            # 流式调用 LLM
            full_content = []
            for chunk in writer._call_llm_stream(
                user_msg=(
                    f"请根据以下大纲和设定，撰写完整的小说章节。\n\n"
                    f"## 故事设定与上下文\n{context}\n\n"
                    f"## 本章大纲\n{json_mod.dumps(chapter_outline, ensure_ascii=False, indent=2)}\n\n"
                    f"请直接输出正文，以'第X章 标题'开头。"
                ),
            ):
                full_content.append(chunk)
                yield f"data: {json_mod.dumps({'type': 'chunk', 'content': chunk}, ensure_ascii=False)}\n\n"

            final_content = "".join(full_content)

            # 保存结果
            project.chapters[chapter_num] = {
                "draft": final_content,
                "polished": "",
                "check_report": None,
                "retry_count": 0,
            }

            yield f"data: {json_mod.dumps({'type': 'done', 'full_content': final_content, 'word_count': len(final_content)}, ensure_ascii=False)}\n\n"

        except Exception as e:
            yield f"data: {json_mod.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"

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
    """获取当前状态（v0.2 增强）"""
    return jsonify({
        "step": project.current_step,
        "message": project.status_message,
        "is_running": project.is_running,
        "current_chapter": project.current_chapter,
        "total_chapters": project.total_chapters,
        "written_chapters": list(project.chapters.keys()),
        "logs": project.logs[-20:],
        "bible_title": project.bible.meta.get("title", ""),
        "genre": project.bible.meta.get("genre", ""),
        "character_count": len(project.bible.characters),
        "foreshadowing_count": len(project.bible.foreshadowings),
        # v0.2 新增字段
        "bible_version": project.bible.current_version,
        "write_stats": project.write_stats,
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
    project.reset()
    _log("🔄 项目已重置")
    return jsonify({"status": "ok"})


# ============================================================
# 启动入口
# ============================================================

if __name__ == "__main__":
    os.makedirs("data", exist_ok=True)
    print("=" * 60)
    print("  📖 小说写作 Agent v0.2（改进版）")
    print("  访问 http://localhost:5000")
    print("-" * 60)
    print("  🆕 v0.2 改进内容：")
    print("    • Checker→Writer 反馈重写机制")
    print("    • 流式输出支持（SSE）")
    print("    • Token 成本追踪")
    print("    • Story Bible 版本控制")
    print("    • 多模型智能路由")
    print("    • Prompt 工程优化（CoT + 负面约束 + Few-Shot）")
    print("=" * 60)
    app.run(host="0.0.0.0", port=5000, debug=True)
