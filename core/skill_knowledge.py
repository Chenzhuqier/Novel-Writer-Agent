"""
Skill 知识加载器 —— 把已安装的网文 skill（story-deslop / story-review 等）的
references 运行时注入各 Agent 提示词。

设计：
- 运行时读取全局 skill 目录（env SKILLS_DIR，默认 ~/.agents/skills）
- 目录/文件缺失时回退到内嵌最小摘录（EMBEDDED_* 常量），保证无 skill 环境照常工作
- get_knowledge() 返回 (text, source)，source ∈ {"file", "embedded"} 供日志/UI 标注

注意：内嵌摘录是"增强提示词"，不属于 AGENTS.md 冻结的 Demo 罐头响应集。
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

# ---------------------------------------------------------------------------
# 内嵌降级摘录（skill 目录缺失时使用；保持精简，能指导模型即可）
# ---------------------------------------------------------------------------

EMBEDDED_DESLOP_RULES = """去AI味核心要点（内嵌降级版）：
1. 改味优先，别当改错：AI 味是风格问题不是语法错误，把过度工整、面面俱到的文字拉回具体、自然、可读。
2. 改最少效果最大：能改一个词就不改一句，能删一句就不重写一段；人名、地名、数字、专有名词优先保留。
3. 不得整段删除正文；删除比例上限：轻度 ≤15%、中度 ≤25%、重度 ≤35%；超限或不确定的内容标 [需复核] 而非删除。
4. 保留创作意图：只改"怎么说"，不改"说什么"；不新增原文没有的情节、设定、关系或时间线。
5. 最高优先级禁用句式：①"不是A，而是B"（直接写 B）②"，带着……"万能状语（删状语留主句）③"他/她知道……"（用行为展示）④章末总结体（"他终于明白……""新的篇章开始了"——用动作/对话/悬念收束）。
6. 一级禁用词（出现即替换）：仿佛、犹如、宛若、一丝、一抹、深吸一口气、眼中闪过、嘴角勾起、心头一震、心中一动、不容置疑、不由自主、话锋一转。
7. 弱化副词密度控制：缓缓/微微/轻轻/淡淡 每千字合计 ≤3。
8. Show Don't Tell：不写"他很紧张/愤怒/伤心"，写身体反应（"手心全是汗，筷子差点掉了"）。
9. 句长：叙述默认是逗号长句（逗号之间 8-12 字、整句 20-30 字）；短句只作偶尔的孤立重拍，不用碎句/电报体。
10. 标点：正文（含对话）不用破折号与省略号硬造停顿，用句号、逗号、短句或动作断句。"""

EMBEDDED_BANNED_WORDS = """AI 味禁用词速查（内嵌降级版）：
- 情态类：仿佛、犹如、宛若、如同、一丝、一抹、些许、几分、隐约、毫无征兆、微不可察
- 动作类：深吸一口气、不禁
- 表情类：眼中闪过、嘴角勾起、眉头微皱、瞳孔微缩、指节泛白、眼神锐利
- 心理类：心中一动、心头一震、心下了然、心中暗道、不由得、心中一凛
- 判断类：不容置疑、不容置喙、显而易见、毫无疑问、不可否认、前所未有
- 形容类：坚定、闪烁着光芒、狡黠、深邃、凛冽、冰冷
- 过渡类：不由自主、情不自禁、自然而然、话锋一转
- 套词（每千字 ≤3）：微微、缓缓、轻轻、淡淡
- 总结句式："终于明白""这才意识到""这一刻""从这一刻开始""才刚刚开始""命运/宿命+齿轮/棋局/獠牙"
- 排比句式：连续 3 句以上相同结构；"有的……有的……" "一边……一边……"
- 章末总结体：禁止总结性感悟、升华式感叹、哲理式收尾、伏笔式预告。"""

EMBEDDED_REVIEW_RUBRIC = """通用网文内容审查 Rubric（内嵌降级版）：
核心维度按 PASS/WARN/FAIL 评估，FAIL/WARN 转成统一 Findings：
- 核心卖点：本章是否围绕明确卖点推进？看不出卖点至少 S2。
- 冲突推进：是否有阻碍、选择、代价或关系变化？只解释/闲聊/总结至少 S2。
- 任务卡点：角色办事被卡住时，是否卡出信息、关系、代价、选择或伏笔变化？卡点只是流程细节至少 S3。
- 情绪曲线：是否有铺垫、升温、释放或反转？情绪平直或突兀 S2/S3。
- 钩子与期待：开头或结尾是否制造后续问题？没有悬念至少 S2。
- 开头新鲜度（仅开篇/前3章）：开局是题材默认模板、可整体换到任意同类书至少 S2/S3。
- 角色动机：行为符合目标、性格、处境和关系压力？为剧情服务而失真 S1/S2。
- 对话质量：有潜台词、信息控制、角色差异？说明书式对话至少 S2。
- 设定一致性：不违背已写规则、时间线、角色属性；明确事实冲突通常 S1。
- 文字自然度：具体、可感、动作承载信息；AI 腔、总结体 S2/S3。
- 句长节奏：叙述默认是逗号长句；碎句和电报体与 AI 腔同级。
- 标点节奏：标点服务语气/声线；通篇句号化或随机堆砌问号/感叹号 S2/S3。
- 格式可读性：段落短、对话独立、无多余空行；阻碍阅读按 S3、严重混乱按 S2。
- 剧情循环：目标→阻碍→行动→代价/反馈→新期待；缺目标/阻碍/反馈通常至少 S2。
- 高潮构建：蓄能→假胜→崩解→反转/兑现；高潮平铺、无代价或无兑现 S2/S3。
- 关系进展：互动尺度匹配当前关系阶段；突然亲密/信任/敌对需铺垫。
- 伏笔状态：伏笔需可追踪；密度只作结构风险提示，不直接升级 S2+。

严重度：S1 破坏主线/动机/规则/读者信任（优先修）；S2 明显影响章节效果/留存/节奏（本轮修）；
S3 局部质量问题（可排期修）；S4 风格建议（不阻塞）。
黄金三问：①读者为什么翻下一页？②本章改变了什么？③哪个证据支持判断（无证据只写"证据不足"）。
发布门槛：无 S1/S2 且 S3 可快速处理→APPROVE；有 S2 或 S3 多→CONCERNS；有 S1 或核心卖点/动机/规则崩坏→REJECT。"""

EMBEDDED_PLATFORM_RUBRIC = """平台 rubric 速查（内嵌降级版）：
- 番茄小说：强开局、强冲突、高频爽点/情绪反馈、低理解门槛；手机端短段、自然虚词、场内动作/对话推进。
- 起点中文网：设定自洽、升级路径清晰、长线期待、世界观承载力；不追求高频打脸，重长线布局。
- 知乎盐言：短篇钩子、反转密度、情绪兑现、信息差推进；段落更短但句内节奏与长篇一致。"""

EMBEDDED_WRITER_RULES = """网文写作要点（内嵌降级版）：
1. 节奏分配：开头约 10% 快速切入建立期待；中段约 70% 冲突推进、信息释放；收尾约 20% 高潮或转折。
2. 黄金三章（开篇卷前 3 章）：前 3 章必须快速建立主角共情点与核心悬念，让读者有明确的"为什么继续看"。
3. 爽点密度：让读者持续获得情绪反馈（身份揭晓、打脸、危机解除、能力兑现），但不要为爽而爽牺牲逻辑。
4. 钩子分级执行：strong=抛出明确钩子（新信息/危机升级/不速之客/两难抉择/异常细节）；weak=情绪余韵或细节暗示；none=自然收束。
5. 每 5-10 章安排一个小高潮，每卷结尾有大高潮；卷与卷之间因果递进。
6. 情绪靠动作与对话承载，不用"他很紧张/他感到愤怒"式的告知。"""

EMBEDDED_OUTLINE_RULES = """大纲架构要点（内嵌降级版）：
1. 黄金三章：开篇卷前 3 章快速建立主角共情点与核心悬念，避免同题材默认套路开局。
2. 节奏曲线：开头吸引→发展推进→高潮爆发→收尾留白；每 5-10 章小高潮、卷末大高潮。
3. 冲突多样性：不让连续 3 章以上使用相同悬念模式；冲突强度要有张有弛。
4. 伏笔节奏：前期多埋、中期推进、后期回收；伏笔埋设与回收路径可追踪。
5. 平台适配：番茄=高频爽点/低门槛；起点=设定自洽/长线期待；知乎=反转密度/信息差。"""

EMBEDDED_SHORT_STORY_RULES = """短篇网文写作要点（内嵌降级版）：
1. 先定情绪，再定故事：动笔前确定目标情绪（意难平/反转震撼/爽感释放/治愈温暖/细思极恐/共鸣感动），所有内容为情绪服务。
2. 一个反转撑一篇：所有铺垫为反转服务，不多线、不铺世界观。
3. 每句话必须有用：不推动剧情、不铺垫反转、不推高情绪的句子→删。
4. 开头 3 句定生死，结尾定传播：开头必须包含钩子（冲突前置/信息差/反常行为/悬念句），结尾必须有余韵。
5. 默认第一人称，代入感最强（除非题材明确需要第三人称）。
6. 五段结构：开头（前300-500字，前100字事件密度≥3）→铺垫（30-40%，埋≥3条反转线索、贯穿道具首次出现）→升级（20-30%，冲突升级、数字递增、一动一静）→反转（10-15%，一节内完成揭示、铺垫线索可回溯、情绪冲击峰值）→结尾（5-10%，安静细节收尾、贯穿道具第3次出现回扣暴击）。
7. 情绪宁烈不温，冲突前置、爽点具体、台词带刺；心死/余韵等以克制为爽感的桥段收敛。
8. 短篇以情绪为目标，所有内容为情绪服务；情节为情绪蓄力，不以事件堆砌充数。"""

EMBEDDED_SHORT_FORMAT_RULES = """短篇正文格式规范（内嵌降级版）：
1. 正文相邻段落之间只允许一个换行符，不得出现空行。
2. 对话引号风格全文统一（默认半角双引号，盐言可用「」）。
3. 短篇小节标记全文统一（默认 ###1. / ###2.）。
4. 叙事节奏：叙述默认是逗号长句（逗号之间 8-12 字、整句 20-30 字）；短句只作偶尔的孤立重拍，不用碎句/电报体。
5. 正文不用破折号与省略号硬造停顿，用句号、逗号、短句或动作断句。
6. 每句话必须有用：不推动剧情、不铺垫反转、不推高情绪的句子→删。
7. 字数：短篇通常 8000-20000 字，每节 ≥800 字（高信息密度题材 ≥500 字），不足必须补足。"""

# 题材关键词 → genre-styles 风格包文件（story-short-write）
_GENRE_STYLE_MAP: list[tuple[tuple[str, ...], str]] = [
    (("追妻", "火葬场", "意难平", "虐恋"), "追妻火葬场.md"),
    (("世情", "打脸", "爽文", "重生打脸"), "世情打脸.md"),
    (("复仇", "逆袭"), "复仇打脸.md"),
    (("总裁", "豪门"), "总裁豪门.md"),
    (("宅斗", "宫斗", "古言"), "宅斗宫斗.md"),
    (("民俗", "怪谈", "灵异"), "民俗怪谈.md"),
    (("悬疑", "推理", "惊悚", "反转"), "悬疑.md"),
    (("甜宠", "治愈", "先婚后爱"), "甜宠.md"),
    (("双男主", "耽美"), "双男主.md"),
    (("沙雕", "脑洞", "系统"), "沙雕脑洞.md"),
]

# ---------------------------------------------------------------------------
# skill 目录解析
# ---------------------------------------------------------------------------

_DEFAULT_SKILLS_DIR = Path.home() / ".agents" / "skills"


def resolve_skills_dir() -> Path:
    """返回全局 skill 目录（env SKILLS_DIR 优先）。"""
    env_dir = os.environ.get("SKILLS_DIR", "").strip()
    if env_dir:
        return Path(env_dir)
    return _DEFAULT_SKILLS_DIR


def is_available(skill: str) -> bool:
    """判断某个 skill 目录是否存在。"""
    return (resolve_skills_dir() / skill).is_dir()


@lru_cache(maxsize=32)
def _read_reference(skill: str, name: str) -> str | None:
    """读取 <skills_dir>/<skill>/references/<name>；不存在返回 None。"""
    if not name:
        return None
    path = resolve_skills_dir() / skill / "references" / name
    try:
        if not path.is_file():
            return None
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def load_reference(skill: str, name: str) -> str | None:
    """公开的 reference 读取（不做内嵌降级）；缺失返回 None。"""
    return _read_reference(skill, name)


# ---------------------------------------------------------------------------
# 内嵌摘录注册表
# ---------------------------------------------------------------------------

_EMBEDDED_BY_KEY: dict[tuple[str, str], str] = {
    ("story-deslop", "anti-ai-writing.md"): EMBEDDED_DESLOP_RULES,
    ("story-deslop", "banned-words.md"): EMBEDDED_BANNED_WORDS,
    ("story-review", "quality-rubric.md"): EMBEDDED_REVIEW_RUBRIC,
    ("story-review", "banned-words.md"): EMBEDDED_BANNED_WORDS,
    ("story-review", "anti-ai-writing.md"): EMBEDDED_DESLOP_RULES,
    ("story-review", "rubrics/fanqie.md"): EMBEDDED_PLATFORM_RUBRIC,
    ("story-review", "rubrics/qidian.md"): EMBEDDED_PLATFORM_RUBRIC,
    ("story-review", "rubrics/zhihu.md"): EMBEDDED_PLATFORM_RUBRIC,
    ("story-long-write", "writing-craft.md"): EMBEDDED_WRITER_RULES,
    ("story-long-write", "outline-structure-theory.md"): EMBEDDED_OUTLINE_RULES,
    ("story-short-write", "structure.md"): EMBEDDED_OUTLINE_RULES,
    ("story-short-write", "short-craft.md"): EMBEDDED_SHORT_STORY_RULES,
    ("story-short-write", "short-format.md"): EMBEDDED_SHORT_FORMAT_RULES,
    ("story-short-write", "submission-craft.md"): EMBEDDED_SHORT_STORY_RULES,
    ("story-short-write", "reversal-toolkit.md"): EMBEDDED_SHORT_STORY_RULES,
}


def get_knowledge(skill: str, name: str) -> tuple[str, str]:
    """优先读运行时文件，缺失回退内嵌摘录。

    Returns:
        (text, source)，source ∈ {"file", "embedded"}。
    """
    text = _read_reference(skill, name)
    if text is not None:
        return text, "file"
    embedded = _EMBEDDED_BY_KEY.get((skill, name))
    if embedded is not None:
        return embedded, "embedded"
    return "", "missing"


def knowledge_source_label(skill: str, name: str) -> str:
    """给 UI/日志用的一句话标注：file / embedded / missing。"""
    _, source = get_knowledge(skill, name)
    if source == "file":
        return f"{skill}/references/{name}（skill 文件）"
    if source == "embedded":
        return f"{skill}/{name}（内嵌降级）"
    return f"{skill}/{name}（缺失）"


# ---------------------------------------------------------------------------
# 按 Agent 组装的规则文本
# ---------------------------------------------------------------------------

def polisher_rules() -> tuple[str, str]:
    """Polisher 去AI味规则：(text, source)。"""
    deslop, s1 = get_knowledge("story-deslop", "anti-ai-writing.md")
    banned, s2 = get_knowledge("story-deslop", "banned-words.md")
    source = "file" if (s1 == "file" or s2 == "file") else ("embedded" if (s1 == "embedded" or s2 == "embedded") else "missing")
    return f"{deslop}\n\n{banned}", source


def reviewer_rules() -> tuple[str, str]:
    """Reviewer 审查基准包：(text, source)。"""
    rubric, s1 = get_knowledge("story-review", "quality-rubric.md")
    banned, s2 = get_knowledge("story-review", "banned-words.md")
    deslop, s3 = get_knowledge("story-review", "anti-ai-writing.md")
    source = "file" if any(s == "file" for s in (s1, s2, s3)) else (
        "embedded" if any(s == "embedded" for s in (s1, s2, s3)) else "missing"
    )
    return f"{rubric}\n\n{banned}\n\n{deslop}", source


def platform_rubric(platform: str) -> tuple[str, str]:
    """按平台取 rubric；platform 为 fanqie/qidian/zhihu，其他返回 generic（quality-rubric）。"""
    mapping = {
        "fanqie": ("story-review", "rubrics/fanqie.md"),
        "qidian": ("story-review", "rubrics/qidian.md"),
        "zhihu": ("story-review", "rubrics/zhihu.md"),
    }
    key = mapping.get(platform)
    if key is not None:
        text, source = get_knowledge(*key)
        return text, source
    return reviewer_rules()


def writer_rules() -> tuple[str, str]:
    """Writer 网文写作要点：(text, source)。"""
    return get_knowledge("story-long-write", "writing-craft.md")


def outline_rules() -> tuple[str, str]:
    """Outline 架构要点：(text, source)。"""
    return get_knowledge("story-long-write", "outline-structure-theory.md")


# ---------------------------------------------------------------------------
# 短篇小说（story-short-write）知识
# ---------------------------------------------------------------------------

def genre_style_rules(genre: str = "") -> tuple[str, str]:
    """按题材加载短篇风格包（genre-styles/{题材}.md）；无匹配返回空。

    Returns:
        (text, source)，source ∈ {"file", "embedded", "missing"}。
    """
    if not genre:
        return "", "missing"
    for keywords, fname in _GENRE_STYLE_MAP:
        if any(k in genre for k in keywords):
            return get_knowledge("story-short-write", f"genre-styles/{fname}")
    return "", "missing"


def short_story_rules(genre: str = "") -> tuple[str, str]:
    """短篇写作规则包：(text, source)。叠加题材风格包（若有）。"""
    core, s1 = get_knowledge("story-short-write", "short-craft.md")
    fmt, s2 = get_knowledge("story-short-write", "short-format.md")
    style, s3 = genre_style_rules(genre)
    parts = [core, fmt]
    if style:
        parts.append(style)
    text = "\n\n".join(p for p in parts if p)
    sources = [s for s in (s1, s2, s3) if s in ("file", "embedded")]
    source = "file" if "file" in sources else ("embedded" if "embedded" in sources else "missing")
    return text, source