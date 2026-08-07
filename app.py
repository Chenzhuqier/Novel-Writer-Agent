"""
小说写作 Agent —— 主应用入口

功能：
1. Web UI 界面（Flask）
2. 完整的写作流水线编排
3. 状态管理与进度跟踪
4. API 接口供前端调用
"""

import json
import os
import threading
from flask import Flask, render_template, request, jsonify, send_from_directory
from core.story_bible import StoryBible, ChapterSummary
from agents import (
    WorldBuilderAgent,
    OutlineAgent,
    WriterAgent,
    CheckerAgent,
    PolisherAgent,
)

app = Flask(
    __name__,
    template_folder="templates",
    static_folder="static",
)

# ============================================================
# 全局状态管理（生产环境应使用数据库/Redis）
# ============================================================

class NovelProject:
    """小说项目状态"""

    def __init__(self):
        self.reset()

    def reset(self):
        self.premise = ""
        self.genre = ""
        self.bible: StoryBible = StoryBible()
        self.outline = {}
        self.chapters = {}  # {chapter_num: {"draft": str, "polished": str, "check_report": dict}}
        self.current_step = "input"  # input → world_building → outline → writing → done
        self.status_message = "准备就绪"
        self.is_running = False
        self.current_chapter = 0
        self.total_chapters = 0
        self.logs = []  # 操作日志


# 全局项目实例
project = NovelProject()


# ============================================================
# 流水线编排核心逻辑
# ============================================================

def run_pipeline_step(step: str, **kwargs):
    """执行流水线的某个步骤，在后台线程中运行"""
    project.is_running = True
    
    try:
        if step == "world_build":
            project.current_step = "world_building"
            project.status_message = "正在构建世界观..."
            _log("🌍 开始构建世界观...")
            
            agent = WorldBuilderAgent(temperature=0.9)
            result = agent.run(premise=project.premise, genre=project.genre)
            
            # 将结果写入故事圣经
            _import_world_to_bible(result)
            
            project.bible.to_json("data/story_bible.json")
            project.current_step = "outline"
            project.status_message = "世界观构建完成！"
            _log(f"✅ 世界观构建完成：{result.get('world_name', '未知世界')}")
            
        elif step == "outline":
            project.current_step = "outlining"
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
            
            project.current_step = "writing"
            project.status_message = f"大纲生成完成！共 {chapter_count} 章"
            _log(f"✅ 大纲生成完成：{chapter_count} 章")
            
        elif step == "write_chapter":
            chapter_num = kwargs.get("chapter_num", 1)
            project.current_chapter = chapter_num
            project.current_step = "writing"
            project.status_message = f"正在撰写第 {chapter_num} 章..."
            _log(f"✍️ 开始写第 {chapter_num} 章...")
            
            # 1. 获取本章细纲
            chapter_outline = _get_chapter_outline(chapter_num)
            
            # 2. 构建上下文
            context = project.bible.build_context_for_chapter(
                chapter_num=chapter_num,
                chapter_outline=json.dumps(chapter_outline, ensure_ascii=False),
            )
            
            # 3. 写作
            writer = WriterAgent(temperature=0.85)
            draft = writer.run(
                chapter_outline=chapter_outline,
                context=context,
            )
            
            project.chapters[chapter_num] = {
                "draft": draft,
                "polished": "",
                "check_report": None,
            }
            
            _log(f"📝 第 {chapter_num} 章初稿完成 ({len(draft)} 字)")
            
            # 4. 检查
            project.status_message = f"正在检查第 {chapter_num} 章..."
            _log(f"🔍 检查第 {chapter_num} 章...")
            
            checker = CheckerAgent(temperature=0.3)
            bible_summary = _build_bible_summary_for_check()
            check_result = checker.run(
                chapter_text=draft,
                chapter_num=chapter_num,
                story_bible_summary=bible_summary,
            )
            
            project.chapters[chapter_num]["check_report"] = check_result
            passed = check_result.get("passed", True)
            
            if passed:
                _log(f"✅ 第 {chapter_num} 章检查通过 (评分: {check_result.get('overall_quality_score', '?')})")
            else:
                issues = check_result.get("issues", [])
                _log(f"⚠️ 第 {chapter_num} 章发现 {len(issues)} 个问题")
            
            # 5. 润色
            project.status_message = f"正在润色第 {chapter_num} 章..."
            _log(f"💎 润色第 {chapter_num} 章...")
            
            polisher = PolisherAgent(temperature=0.6)
            polished = polisher.run(
                text=draft,
                style_guide=project.bible.style_guide,
            )
            
            project.chapters[chapter_num]["polished"] = polished
            _log(f"💎 第 {chapter_num} 章润色完成")
            
            # 6. 提取摘要并更新故事圣经
            _extract_and_update_summary(chapter_num, draft)
            
            project.status_message = f"第 {chapter_num} 章完成！"
            project.bible.to_json("data/story_bible.json")
            
    except Exception as e:
        project.status_message = f"错误：{str(e)}"
        _log(f"❌ 错误：{str(e)}")
    finally:
        project.is_running = False


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
        char = project.bible.add_character(**char_data)
        
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
    """提取章节摘要并更新故事圣经（简化版）"""
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
}"""
    
    try:
        response = call_llm(prompt, text[:3000], temperature=0.3, max_tokens=1000)
        clean = response.strip()
        if clean.startswith("```"):
            lines = clean.split("\n")
            clean = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        summary_data = json.loads(clean)
        summary = ChapterSummary(**summary_data)
        project.bible.add_chapter_summary(summary)
    except Exception as e:
        # 如果摘要提取失败，创建一个基础摘要
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
    """触发指定章节的写作"""
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
        total = project.total_chapters or len(project.outline.get("volumes", [{}])[0].get("chapters", []))
        for ch in range(1, total + 1):
            run_pipeline_step("write_chapter", chapter_num=ch)
        project.current_step = "done"
        project.status_message = "全部章节写作完成！"
        _log("🎉 全部章节写作完成！")
    
    thread = threading.Thread(target=write_all_chapters)
    thread.start()
    return jsonify({"status": "started"})


@app.route("/api/status", methods=["GET"])
def api_status():
    """获取当前状态"""
    return jsonify({
        "step": project.current_step,
        "message": project.status_message,
        "is_running": project.is_running,
        "current_chapter": project.current_chapter,
        "total_chapters": project.total_chapters,
        "written_chapters": list(project.chapters.keys()),
        "logs": project.logs[-20:],  # 最近20条日志
        "bible_title": project.bible.meta.get("title", ""),
        "genre": project.bible.meta.get("genre", ""),
        "character_count": len(project.bible.characters),
        "foreshadowing_count": len(project.bible.foreshadowings),
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
    
    return send_from_directory("data", "export.txt", as_attachment=True, download_name=f"{project.bible.meta.get('title', 'novel')}.txt")


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
    print("=" * 50)
    print("  📖 小说写作 Agent Demo")
    print("  访问 http://localhost:5000")
    print("=" * 50)
    app.run(host="0.0.0.0", port=5000, debug=True)
