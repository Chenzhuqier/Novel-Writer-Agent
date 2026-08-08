"""
语言润色 Agent —— 负责优化文笔、统一文风

改进点（v0.3）：
1. 差异化润色策略真正生效：支持传入原文质量评分，自动匹配策略并注入 prompt
2. 专有名词保护：protected_terms 注入 prompt，输出后逐项校验
3. 结构化输出：固定分隔符分离【润色说明】与正文，PolishResult + 容错解析
   （同时修复旧版正文里残留润色说明/分隔符的问题）
4. 输出质量校验：字数比例 / 保护词 / 对话保留三重检查，strict 模式自动重试
5. 生成参数可控：默认低温度（0.4）；prompt 分段组装；补充输入参数校验
"""

from dataclasses import dataclass, field
import re

from .base import BaseAgent, register_demo, DEMO_POLISHED_CONTENT

register_demo("Polisher", DEMO_POLISHED_CONTENT, estimated_tokens=3000)

_NOTES_TAG = "【润色说明】"
# 说明与正文之间的固定分隔符：比 "---" 更不易与正文撞车，且方便程序解析
_CONTENT_DELIMITER = "===POLISHED_CONTENT==="
# 旧格式 / Demo 兜底用分隔符
_LEGACY_DELIMITER = "---"

# 对话内容提取（中文弯引号；若作品使用「」或直引号，可自行扩展）
_DIALOG_RE = re.compile(r'"([^"\n]{1,300})"')

# 默认润色温度：要求"保持原意"，低温度更稳；需要更有创造力的改写时可调高
DEFAULT_TEMPERATURE = 0.4

_SYSTEM_PROMPT = f"""你是一位资深文学编辑，擅长润色小说正文，提升文笔质量的同时保持原意不变。

## 润色原则

### ✅ 必须做到

1. **保持原意**：不改变情节、对话、角色行为，只优化表达方式
2. **提升文笔**：
   - 句式更丰富（长短句交替，避免连续短句或长难句）
   - 词汇更精准（替换平淡词汇为更有表现力的表达）
   - 增强画面感（补充恰当的感官描写）
   - 优化节奏感（调整段落长短，控制阅读呼吸）
3. **统一文风**：保持全文风格一致，不出现文风跳跃
4. **不注水**：不为了字数增加无意义的内容

### ⛔ 绝对禁止

1. **禁止改变原意**：
   - ❌ 对话内容必须逐字保留（包括语气词和标点）
   - ❌ 不要改变动作的先后顺序
   - ❌ 不要增加原文没有的信息

2. **禁止过度修饰**：
   - ❌ 不要每句都加形容词（会显得矫揉造作）
   - ❌ 不要使用生僻字（要保持可读性）
   - ❌ 不要把简洁的句子改复杂

3. **禁止丢失原文优点**：
   - ❌ 不要删掉原文中有力的短句
   - ❌ 不要替换掉原文中精彩的比喻
   - ❌ 不要破坏原文已有的节奏感

4. **禁止风格偏离**：
   - ❌ 不要把古风改成白话（除非原文就是白话）
   - ❌ 不要把正式语体改成网络用语
   - ❌ 不要改变叙述视角

5. **禁止破坏结构**：
   - ❌ 保持段落结构与原文一致（不随意合并或拆分段落）
   - ❌ 保留原文中的专有名词（人名、地名、功法名等），不得替换或改写

## 差异化润色策略

调用方会给出原文质量评分及对应策略；若未给出，请自行评估原文质量并参照下表选择力度：

| 原文质量 | 策略 |
|----------|------|
| 优秀（8分+） | 微调为主，只改明显瑕疵 |
| 良好（6-8分） | 局部优化，重点提升薄弱段落 |
| 一般（4-6分） | 全面润色，重构问题段落 |
| 较差（4分以下） | 尽力润色，并在【润色说明】中标注建议大改的部分 |

## 输出格式（严格遵守）

先输出【润色说明】，简要列出主要修改点（3-5 条），每条一行：

【润色说明】
1. 第X段：优化了XXX，增强了画面感
2. 第X段：调整了句式节奏，使XXX更流畅

然后另起一行，只输出以下分隔符：
{_CONTENT_DELIMITER}

分隔符之后输出润色后的完整正文。除上述内容外，不要输出任何其他标记或解释。"""


@dataclass
class PolishResult:
    """一次润色的完整结果。"""

    content: str = ""                                    # 润色后的正文
    notes: list = field(default_factory=list)            # 润色说明（逐条）
    raw: str = ""                                        # 模型原始输出，便于排查
    warnings: list = field(default_factory=list)          # 校验警告


class PolisherAgent(BaseAgent):
    """语言润色 Agent"""

    name = "Polisher"
    description = "优化小说正文的文笔和风格"
    force_json_output = False

    _STRATEGY_MAP = (
        (8.0, "微调", "原文质量优秀。仅修正明显瑕疵（错别字、病句、标点），其余尽量保持原样。"),
        (6.0, "局部优化", "原文质量良好。重点提升薄弱段落，写得好的部分保持不变。"),
        (4.0, "全面润色", "原文质量一般。可以重构问题段落，但不得改变情节走向与对话内容。"),
        (0.0, "重写建议", "原文质量较差。在尽力润色的同时，于【润色说明】中标注建议大改的部分及原因。"),
    )

    # 输出校验阈值：润色后字数 / 原文字数 应落在该区间内
    min_length_ratio = 0.7
    max_length_ratio = 1.4

    def __init__(self, model=None, temperature=None):
        # 默认低温度：润色要求"保持原意"，0.4 更稳（调用方可显式覆盖）
        super().__init__(
            model=model,
            temperature=DEFAULT_TEMPERATURE if temperature is None else temperature,
        )

    @property
    def system_prompt(self) -> str:
        return _SYSTEM_PROMPT

    # ================= 对外接口 =================

    def run(
        self,
        text: str,
        style_guide: str = "",
        quality_score=None,
        protected_terms=None,
        strict: bool = False,
        **kwargs,
    ) -> str:
        """执行润色，返回润色后的正文（与 v0.2 签名兼容）。

        Args:
            text: 待润色的章节正文
            style_guide: 文风要求（可选）
            quality_score: 原文质量评分 0-10（可选），用于匹配差异化策略
            protected_terms: 必须原样保留的专有名词列表（可选）
            strict: 输出校验未通过时是否自动重试一次
        """
        return self.run_detailed(
            text,
            style_guide=style_guide,
            quality_score=quality_score,
            protected_terms=protected_terms,
            strict=strict,
            **kwargs,
        ).content

    def run_detailed(
        self,
        text: str,
        style_guide: str = "",
        quality_score: float = None,
        protected_terms=None,
        strict: bool = False,
        **kwargs,
    ) -> PolishResult:
        """执行润色并返回完整结果（含润色说明与校验警告）。"""
        self._validate_input(["text"], text=text)
        if kwargs:
            print(f"[{self.name}] 忽略未识别的参数：{sorted(kwargs)}")

        text = text.strip()
        if not text:
            raise ValueError("待润色文本为空")

        protected_terms = [t.strip() for t in (protected_terms or []) if t and t.strip()]
        if quality_score is not None and not 0 <= quality_score <= 10:
            raise ValueError(f"quality_score 应在 0-10 之间，当前为 {quality_score}")

        strategy = self._strategy_for(quality_score)
        user_msg = self._build_user_msg(text, style_guide, quality_score, strategy, protected_terms)

        print(
            f"[{self.name}] 开始润色：原文 {len(text)} 字，策略「{strategy[0]}」，"
            f"保护词 {len(protected_terms)} 个"
        )

        result = self._polish_once(user_msg, text, protected_terms)

        # strict 模式：首次输出未通过校验时，带着问题清单重试一次
        if strict and result.warnings:
            print(f"[{self.name}] 首次输出未通过校验，自动重试一次：{result.warnings}")
            retry_msg = (
                user_msg
                + "\n\n## 重要提醒\n你上一次的输出存在以下问题，请逐项修正后重新完整输出：\n"
                + "\n".join(f"- {w}" for w in result.warnings)
            )
            retry_result = self._polish_once(retry_msg, text, protected_terms)
            # 只有重试结果确实更好时才采用，避免越改越差
            if len(retry_result.warnings) < len(result.warnings):
                result = retry_result

        print(
            f"[{self.name}] 润色完成：正文 {len(result.content)} 字（比例 "
            f"{len(result.content) / max(len(text), 1):.2f}），警告 {len(result.warnings)} 条"
        )
        return result

    # ================= 内部方法 =================

    def _polish_once(self, user_msg: str, original_text: str, protected_terms: list) -> PolishResult:
        """调用一次 LLM 并完成解析与校验。"""
        raw = self._call_llm(user_msg, temperature=self.temperature)
        result = self._parse_output(raw)
        result.warnings.extend(
            self._validate_output(original_text, result.content, protected_terms)
        )
        return result

    def _build_user_msg(
        self,
        text: str,
        style_guide: str,
        quality_score: float,
        strategy: tuple,
        protected_terms: list,
    ) -> str:
        """分段组装 user prompt，替代脆弱的 += 拼接。"""
        parts = ["请润色以下小说章节。"]

        if style_guide and style_guide.strip():
            parts.append(f"## 文风要求\n{style_guide.strip()}")

        level, desc = strategy
        if quality_score is not None:
            parts.append(
                f"## 润色策略\n原文质量评分 {quality_score:.1f}/10，"
                f"请采用「{level}」策略：{desc}"
            )
        else:
            parts.append(f"## 润色策略\n{desc}")

        if protected_terms:
            parts.append(
                "## 必须原样保留的专有名词\n"
                "以下词汇是作品设定，润色后必须逐字保留、不得替换或改写：\n"
                + "、".join(protected_terms)
            )

        parts.append(f"## 原文\n{text}")
        return "\n\n".join(parts)

    @classmethod
    def _strategy_for(cls, quality_score: float) -> tuple:
        """根据质量评分匹配差异化策略；未提供评分时交给模型自行判断。"""
        if quality_score is None:
            return ("自动判断", "请自行评估原文质量，并参照系统提示中的策略表选择合适力度。")
        for threshold, level, desc in cls._STRATEGY_MAP:
            if quality_score >= threshold:
                return (level, desc)
        return cls._STRATEGY_MAP[-1][1:]

    @staticmethod
    def _parse_output(raw: str) -> PolishResult:
        """按固定分隔符/旧版 --- 拆分【润色说明】与正文；两者都缺失时容错为整体正文。"""
        raw = (raw or "").strip()
        result = PolishResult(content="", raw=raw)

        if _CONTENT_DELIMITER in raw:
            notes_part, _, content = raw.partition(_CONTENT_DELIMITER)
            result.content = content.strip()
        elif _LEGACY_DELIMITER in raw:
            # 兼容旧版提示词与 Demo 数据（【润色说明】... --- 正文）
            notes_part, _, content = raw.partition(_LEGACY_DELIMITER)
            result.content = content.strip()
        else:
            result.content = raw
            result.warnings.append(
                f"输出中未检测到分隔符 {_CONTENT_DELIMITER}，已按纯正文处理"
            )
            return result

        notes_text = notes_part.replace(_NOTES_TAG, "", 1).strip()
        if notes_text:
            for line in notes_text.splitlines():
                line = re.sub(r"^\s*\d+\s*[.、．)]\s*", "", line).strip()
                if line and not line.startswith("-"):
                    result.notes.append(line)

        if not result.content:
            result.warnings.append("分隔符后正文为空")
        return result

    def _validate_output(self, original: str, polished: str, protected_terms: list) -> list:
        """三重校验：字数比例、专有名词保留、对话逐字保留。"""
        if not polished:
            return []  # 为空的情况已由解析层报告

        warnings = []

        # 1) 字数比例：防止大幅缩水或注水
        ratio = len(polished) / max(len(original), 1)
        if ratio < self.min_length_ratio:
            warnings.append(f"正文字数缩水过多（{ratio:.0%}），可能遗漏了内容")
        elif ratio > self.max_length_ratio:
            warnings.append(f"正文字数膨胀过多（{ratio:.0%}），可能注水")

        # 2) 专有名词：作品设定不得被"优化"掉
        missing_terms = [t for t in protected_terms if t not in polished]
        if missing_terms:
            warnings.append("以下专有名词在润色后丢失：" + "、".join(missing_terms))

        # 3) 对话：逐字保留
        missing_dialogs = [d for d in _DIALOG_RE.findall(original) if d not in polished]
        if missing_dialogs:
            preview = "；".join(f"「{d[:15]}…」" for d in missing_dialogs[:3])
            warnings.append(f"有 {len(missing_dialogs)} 段对话被改动，例如：{preview}")

        return warnings