"""
多视角审查 Agent —— 引入 story-review 的多视角对抗式审查

v0.1 要点：
1. 单一 LLM 调用内依次走 4 个视角：结构架构 / 角色对话 / 文字AI味 / 设定一致性
2. 注入审查基准包（通用 rubric + 禁用词 + 去AI味方法 + 平台 rubric），rubric 来源可标注
3. 输出 pydantic 校验（ReviewReport），失败回喂自修复（MAX_REPAIR_ATTEMPTS）
4. 一致性视角复用跨章入参（角色状态/未回收伏笔/前情摘要），与 CheckerAgent 对齐
5. verdict 由模型给出，代码按 S1/S2 计数做对账兜底
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, ValidationError

from .base import BaseAgent, register_demo

logger = logging.getLogger(__name__)

MAX_REPAIR_ATTEMPTS = 2
SEVERITIES = ("S1", "S2", "S3", "S4")
CATEGORIES = (
    "structure", "character", "prose", "consistency",
    "platform", "factual", "format", "causal", "rule_boundary",
)

PERSPECTIVES = (
    "structure: 主题对齐、大纲结构、钩子/反转质量、节奏、范围控制、剧情循环与高潮构建",
    "character: 角色语言一致性、对话质量、人物弧线、关系推进、好感度匹配",
    "prose: AI味检测、禁词/套话、格式合规、标点节奏、文字自然度、情绪烈度",
    "consistency: 事实矛盾、设定冲突、时间线自洽、伏笔状态（仅本章内部或给定参照）",
)


# ---------------------------------------------------------------------------
# 输出 Schema（与 prompt 中的 JSON 模板严格同构）
# ---------------------------------------------------------------------------

class ReviewFinding(BaseModel):
    severity: Literal["S1", "S2", "S3", "S4"]
    category: Literal[
        "structure", "character", "prose", "consistency",
        "platform", "factual", "format", "causal", "rule_boundary",
    ]
    location: str = Field(min_length=1)
    evidence: str = Field(min_length=4)
    issue: str = Field(min_length=4)
    fix: str = Field(min_length=4)


class ReviewReport(BaseModel):
    verdict: Literal["APPROVE", "CONCERNS", "REJECT"]
    findings: list[ReviewFinding] = Field(default_factory=list)
    rubric_source: str = "embedded fallback"
    perspective_notes: dict[str, str] = Field(default_factory=dict)
    summary: str = Field(min_length=8)


class ReviewError(RuntimeError):
    """自修复耗尽后抛出。"""


# ---------------------------------------------------------------------------
# Demo 响应（新增，非修改既有冻结项；与 schema 同步维护）
# ---------------------------------------------------------------------------

DEMO_REVIEW_RESULT: dict[str, Any] = {
    "verdict": "APPROVE",
    "findings": [
        {
            "severity": "S3",
            "category": "prose",
            "location": "[P4]",
            "evidence": "沈炼的眉头微微皱起",
            "issue": "轻微 AI 套话：表情类禁词『微微皱起』",
            "fix": "改为具体动作，如『他眉峰压了压』或直接删去",
        }
    ],
    "rubric_source": "demo",
    "perspective_notes": {
        "structure": "本章推进复仇主线，钩子明确。",
        "character": "对话符合沈炼隐忍人设。",
        "prose": "整体自然，个别套话待清。",
        "consistency": "时间线与设定一致。",
    },
    "summary": "本章整体质量良好，仅有一处轻微文字套话，可快速处理。",
}

register_demo("StoryReviewer", DEMO_REVIEW_RESULT, estimated_tokens=1800)


# ---------------------------------------------------------------------------
# Agent 本体
# ---------------------------------------------------------------------------

class ReviewerAgent(BaseAgent):
    """多视角对抗式审查 Agent"""

    name = "StoryReviewer"
    description = "从结构/角色/文字/一致性多视角审查章节质量"
    force_json_output = True

    # ------------------------------------------------------------------ prompt

    @property
    def system_prompt(self) -> str:
        return """你是一位极严苛的小说审稿主编，擅长从多视角找出章节的问题。你的任务是【找问题】，不是验证正确性。

## 审查视角（必须依次覆盖）

1. structure（结构架构）：主题是否推进、大纲结构是否完整、钩子/反转质量、节奏是否均匀、范围控制、剧情循环（目标→阻碍→行动→代价/反馈→新期待）与高潮构建（蓄能→假胜→崩解→反转/兑现）。
2. character（角色对话）：角色语言风格是否一致、对话是否千篇一律或信息过满、人物弧线是否连贯、角色行为是否符合动机、关系推进是否匹配当前关系阶段。
3. prose（文字自然度）：AI味检测（禁词/套话/总结体/解释腔）、格式合规（段落自然断开、对话独立成行）、标点节奏、句长节奏（叙述默认是逗号长句，碎句和电报体与 AI 腔同级处理，不因『短』放行）。
4. consistency（设定一致性）：事实矛盾、设定冲突、时间线自洽、伏笔状态；给出角色状态表/未回收伏笔/前情摘要时以此为准核查。

## 审查基准（user 消息中会注入 rubric，必须遵守）

以 user 消息中的『审查基准包』为准逐项对照，标记 PASS/WARN/FAIL。无 rubric 注入时使用 system prompt 中的通用规则。

## 严重度定义

- S1：会破坏主线、角色动机、世界规则或读者信任，需优先修。
- S2：明显影响章节效果、留存、节奏、人物可信度，建议本轮修。
- S3：局部质量问题，如措辞、轻微格式、局部节奏，可排期修。
- S4：建议项或风格微调，不阻塞发布。

## 输出要求

严格输出一个 JSON 对象，不要 markdown 代码围栏、不要任何额外文字：

{
  "verdict": "APPROVE 或 CONCERNS 或 REJECT",
  "findings": [
    {"severity": "S1|S2|S3|S4", "category": "structure|character|prose|consistency|platform|factual|format|causal|rule_boundary", "location": "文件路径:行号 或 [P3] 或 段落描述", "evidence": "引用原文或具体证据", "issue": "问题描述", "fix": "可执行修改建议"}
  ],
  "rubric_source": "file 或 embedded fallback 或 demo",
  "perspective_notes": {"structure": "…", "character": "…", "prose": "…", "consistency": "…"},
  "summary": "整体洞察（不要复述 findings）"
}

规则：
- findings 先列 S1/S2，再列 S3/S4；按严重度降序排列。
- 无问题的维度不必硬凑 finding；全部通过时 findings 可为空，verdict 为 APPROVE。
- 每条 finding 必须有原文证据（evidence）；无证据不要输出，改为在 summary 中标注『证据不足』。
- verdict 参考门槛：无 S1/S2 且 S3 可快速处理→APPROVE；有 S2 或 S3 数量多→CONCERNS；有 S1 或核心卖点/动机/规则崩坏→REJECT。"""

    # ------------------------------------------------------------------ 主流程

    def run(
        self,
        chapter_text: str,
        chapter_num: int,
        rubric: str = "",
        rubric_source: str = "embedded fallback",
        character_states: Optional[list[dict]] = None,
        open_foreshadowing: Optional[list[str]] = None,
        prev_chapter_digest: str = "",
        **kwargs,
    ) -> dict:
        """执行多视角审查，返回经对账后的 ReviewReport dict。

        Args:
            chapter_text: 待审正文
            chapter_num: 章节号
            rubric: 审查基准包文本（含通用 rubric + 禁用词 + 去AI味方法 + 平台 rubric）
            rubric_source: rubric 来源标注（file / embedded fallback / demo）
            character_states: 角色状态表（可选）
            open_foreshadowing: 未回收伏笔清单（可选）
            prev_chapter_digest: 前情摘要（可选）
        """
        self._validate_input(
            ["chapter_text", "chapter_num"],
            chapter_text=chapter_text, chapter_num=chapter_num,
        )

        user_msg = self._build_user_msg(
            chapter_text=chapter_text,
            chapter_num=chapter_num,
            rubric=rubric,
            rubric_source=rubric_source,
            character_states=character_states,
            open_foreshadowing=open_foreshadowing,
            prev_chapter_digest=prev_chapter_digest,
        )

        report = self._generate_with_repair(user_msg)
        return self._finalize(report)

    # ------------------------------------------------------------------ 输入组装

    def _build_user_msg(
        self, *, chapter_text, chapter_num, rubric, rubric_source,
        character_states, open_foreshadowing, prev_chapter_digest,
    ) -> str:
        parts = [f"请对第 {chapter_num} 章进行多视角审查。\n"]

        parts.append(f"## 审查基准包\n{rubric if rubric else '（未注入 rubric，使用 system prompt 通用规则）'}\n")
        parts.append(f"Rubric Source: {rubric_source}\n")

        if character_states:
            states = self._format_character_states(character_states)
            parts.append(f"## 角色状态表（截至上一章末）\n{states}\n")

        if open_foreshadowing:
            items = "\n".join(f"- {f}" for f in open_foreshadowing)
            parts.append(f"## 未回收伏笔清单\n{items}\n")

        if prev_chapter_digest:
            parts.append(f"## 前情摘要\n{prev_chapter_digest}\n")

        tagged = self._tag_paragraphs(chapter_text)
        parts.append(
            f"## 第{chapter_num}章正文\n<chapter_to_review>\n{tagged}\n</chapter_to_review>\n"
        )
        parts.append("请按 system prompt 要求输出完整 JSON 审查报告。")
        return "\n".join(parts)

    @staticmethod
    def _tag_paragraphs(text: str) -> str:
        paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        return "\n\n".join(f"[P{i}] {p}" for i, p in enumerate(paras, start=1))

    @staticmethod
    def _format_character_states(states: list[dict]) -> str:
        lines = []
        for c in states:
            status = ("存活" if c.get("alive", True)
                      else f"已死亡（第{c.get('died_at', '?')}章）")
            extras = "；".join(
                f"{k}={v}" for k, v in c.items()
                if k not in {"name", "alive", "died_at"}
            )
            lines.append(f"- {c.get('name', '?')}：{status}" + (f"；{extras}" if extras else ""))
        return "\n".join(lines)

    # ------------------------------------------------------------------ 生成与自修复

    def _generate_with_repair(self, user_msg: str) -> ReviewReport:
        prompt = user_msg
        last_err: Exception | None = None

        for attempt in range(1 + MAX_REPAIR_ATTEMPTS):
            raw = self._call(prompt)
            try:
                data = self._extract_json(raw)
                return ReviewReport.model_validate(data)
            except (json.JSONDecodeError, ValidationError, ValueError) as e:
                last_err = e
                logger.warning("StoryReviewer 输出校验失败（第%d次）：%s", attempt + 1, e)
                prompt = self._build_repair_msg(user_msg, raw, e)

        raise ReviewError(f"自修复 {MAX_REPAIR_ATTEMPTS} 次后仍无法得到合法报告：{last_err}")

    def _call(self, user_msg: str) -> str:
        structured = getattr(self, "_call_llm_structured", None)
        if callable(structured):
            return structured(user_msg, json_schema=ReviewReport.model_json_schema())
        return self._call_llm(user_msg)

    @staticmethod
    def _extract_json(raw: str) -> dict:
        if isinstance(raw, dict):
            return raw  # demo 兜底直接返回 dict 结构
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.MULTILINE)
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise json.JSONDecodeError("未找到 JSON 对象", text, 0)
        return json.loads(text[start:end + 1])

    @staticmethod
    def _build_repair_msg(user_msg: str, raw: str, err: Exception) -> str:
        return (
            f"{user_msg}\n\n## 上次输出校验失败\n"
            f"错误信息：{err}\n"
            f"上次输出（截断展示）：{raw[:2000]}\n"
            "请修正后重新输出完整合法的 JSON，不要输出任何解释。"
            "若上次输出疑似被截断，请压缩 perspective_notes 与 summary 的篇幅。"
        )

    # ------------------------------------------------------------------ 代码对账

    @staticmethod
    def _finalize(report: ReviewReport) -> dict:
        data = report.model_dump()

        # 对账：按 S1/S2 计数校正 verdict（不信任模型自评）
        s1 = sum(1 for f in data["findings"] if f["severity"] == "S1")
        s2 = sum(1 for f in data["findings"] if f["severity"] == "S2")
        model_verdict = data["verdict"]
        if s1 > 0:
            corrected = "REJECT"
        elif s2 > 0 or len(data["findings"]) >= 3:
            corrected = "CONCERNS"
        else:
            corrected = "APPROVE"
        if model_verdict != corrected:
            logger.info(
                "verdict 与 findings 矛盾（model=%s），已按 S1/S2 计数重算为 %s",
                model_verdict, corrected,
            )
        data["verdict"] = corrected

        # 按严重度排序：S1 > S2 > S3 > S4，同级保持原序
        order = {s: i for i, s in enumerate(SEVERITIES)}
        data["findings"] = sorted(
            data["findings"], key=lambda f: order.get(f["severity"], 9)
        )
        return data