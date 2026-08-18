"""
长篇连贯性审计 Agent —— 周期性强一致性检查（v0.4）。

职责：
- 每 N 章（或手动触发）对「全部已写章节 + 世界状态账本 + 故事圣经」做一次
  全量一致性审计，扫描：已死角色复现 / 角色属性漂移 / 物品归属矛盾 /
  地名漂移 / 时间线矛盾 / 长线伏笔断链。
- 输出 pydantic 校验的 AuditReport（整改清单），只报告不自动改写，
  由用户挑选问题手动重写对应章节。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, ValidationError

from .base import BaseAgent, register_demo

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

MAX_REPAIR_ATTEMPTS = 2        # 校验失败后的最大自修复次数
SEVERITIES = ("S1", "S2", "S3", "S4")

FINDING_CATEGORIES = (
    "dead_character_reappears",   # 已死角色复现
    "attribute_drift",            # 角色属性/外貌/能力/关系漂移
    "item_contradiction",         # 物品归属/状态矛盾
    "location_drift",             # 地名/地点状态漂移
    "timeline_conflict",          # 时间线矛盾
    "foreshadowing_break",        # 长线伏笔断链（埋设超期未回收/无推进）
    "setting_conflict",           # 设定冲突
)


# ---------------------------------------------------------------------------
# 输出 Schema（与 prompt 中的 JSON 模板严格同构）
# ---------------------------------------------------------------------------

class AuditFinding(BaseModel):
    severity: Literal["S1", "S2", "S3", "S4"]
    category: Literal[
        "dead_character_reappears", "attribute_drift", "item_contradiction",
        "location_drift", "timeline_conflict", "foreshadowing_break",
        "setting_conflict",
    ]
    chapter: int = Field(ge=0)            # 问题出现的章节号（0 表示跨章/全局）
    evidence: str = Field(min_length=4)   # 证据（引用原文或账本条目）
    issue: str = Field(min_length=4)      # 问题描述
    fix: str = Field(min_length=4)        # 修改建议


class AuditReport(BaseModel):
    findings: list[AuditFinding] = Field(default_factory=list)
    summary: str = Field(min_length=8)
    audited_chapters: int = 0
    as_of_chapter: int = 0


class AuditError(RuntimeError):
    """自修复耗尽后抛出。"""


# ---------------------------------------------------------------------------
# Demo 响应（新增，非修改既有冻结项；与 schema 同步维护）
# ---------------------------------------------------------------------------

DEMO_AUDIT_RESULT: dict[str, Any] = {
    "findings": [
        {
            "severity": "S2",
            "category": "foreshadowing_break",
            "chapter": 3,
            "evidence": "第3章埋设「神秘令牌来历」，至第15章仍未回收或推进",
            "issue": "长线伏笔搁置过久，读者记忆衰减，回收时缺乏呼应",
            "fix": "在近期章节安排一次该伏笔的再次提及或局部揭示",
        },
        {
            "severity": "S3",
            "category": "attribute_drift",
            "chapter": 12,
            "evidence": "第12章描述沈炼佩剑为「青霜」，与前文设定卡「寒江」不一致",
            "issue": "道具名称漂移，影响设定一致性",
            "fix": "统一为设定字典中的权威名称「寒江」",
        },
    ],
    "summary": "全局一致性总体良好；发现 1 条长线伏笔搁置与 1 处道具名称漂移，建议按 chapter 定向重写处理。",
    "audited_chapters": 15,
    "as_of_chapter": 15,
}

register_demo("ContinuityAuditor", DEMO_AUDIT_RESULT, estimated_tokens=1800)


# ---------------------------------------------------------------------------
# Agent 本体
# ---------------------------------------------------------------------------

class AuditAgent(BaseAgent):
    """全量连贯性审计 Agent"""

    name = "ContinuityAuditor"
    description = "对全书章节做一致性审计，产出整改清单"
    force_json_output = True

    # ------------------------------------------------------------------ prompt

    @property
    def system_prompt(self) -> str:
        return """你是一位极度严谨的小说版本编辑，负责对长篇连载做「前后一致性」全量审计。
你的任务是【找出贯穿全书的前后矛盾】，不是逐章找毛病。

## 审计视角（必须逐项核查）

1. dead_character_reappears（已死角色复现）：已确认死亡的角色的名字/身份再次以活人身份出现。
2. attribute_drift（角色属性漂移）：同一角色的外貌、年龄、能力、性格、称号在不同章节描述不一致。
3. item_contradiction（物品矛盾）：同一物品的持有者、位置、状态在不同章节互相矛盾。
4. location_drift（地名漂移）：同一地点的名称、描述、状态前后不一致；同一名称被用于不同地点。
5. timeline_conflict（时间线矛盾）：事件先后顺序、故事内时间推进与章节顺序冲突。
6. foreshadowing_break（伏笔断链）：埋设超过 8 章未回收、且无任何推进/呼应提示的伏笔。
7. setting_conflict（设定冲突）：与故事圣经中的力量体系、世界观规则冲突。

## 判定标准
- S1：致命矛盾（已死角色复现、时间线根本冲突），必须整改
- S2：明显矛盾（物品归属冲突、长线伏笔断链），应整改
- S3：轻微漂移（名称/描述小差异），建议统一
- S4：仅供参考的观察，可不处理

## 输出要求
请严格以 JSON 格式输出，字段如下：
```json
{
  "findings": [
    {
      "severity": "S1|S2|S3|S4",
      "category": "dead_character_reappears|attribute_drift|item_contradiction|location_drift|timeline_conflict|foreshadowing_break|setting_conflict",
      "chapter": 问题出现章节号（0表示跨章/全局）,
      "evidence": "证据：引用原文或账本条目",
      "issue": "问题描述",
      "fix": "修改建议"
    }
  ],
  "summary": "全量审计结论（100字以内）",
  "audited_chapters": 已审计章节数,
  "as_of_chapter": 当前章节号
}
```

## ⛔ 禁止事项
- ❌ 不要把同一章节内的临时性状态变化误判为矛盾（如角色受伤又痊愈）
- ❌ 不要臆造前文不存在的事件作为「证据」
- ❌ 不要输出 JSON 以外的任何文字"""

    # ------------------------------------------------------------------ 主流程

    def run(
        self,
        chapters_text: str,
        world_state_text: str = "",
        bible_summary: str = "",
        issue_history_text: str = "",
        as_of_chapter: int = 0,
        **kwargs,
    ) -> dict:
        """执行全量一致性审计，返回 AuditReport dict。

        Args:
            chapters_text: 全部已写章节的正文（超长由调用方抽样/压缩）
            world_state_text: 世界状态账本渲染文本（可选）
            bible_summary: 故事圣经摘要（可选）
            issue_history_text: 历史问题记录（可选）
            as_of_chapter: 当前已写到第几章
        """
        self._validate_input(["chapters_text"], chapters_text=chapters_text)

        user_msg = self._build_user_msg(
            chapters_text=chapters_text,
            world_state_text=world_state_text,
            bible_summary=bible_summary,
            issue_history_text=issue_history_text,
            as_of_chapter=as_of_chapter,
        )

        report = self._generate_with_repair(user_msg)
        return self._finalize(report, as_of_chapter)

    # ------------------------------------------------------------------ 输入组装

    def _build_user_msg(
        self, *, chapters_text, world_state_text, bible_summary,
        issue_history_text, as_of_chapter,
    ) -> str:
        parts = [f"请对截至第 {as_of_chapter} 章的全书做一致性审计。\n"]

        if world_state_text:
            parts.append(f"## 世界状态账本（截至第{as_of_chapter}章）\n{world_state_text}\n")
        if bible_summary:
            parts.append(f"## 故事圣经摘要\n{bible_summary}\n")
        if issue_history_text:
            parts.append(f"## 历史问题记录\n{issue_history_text}\n")

        parts.append("## 全部已写章节正文\n<chapters_to_audit>\n")
        parts.append(chapters_text[:12000])  # 绝对上限保护，防单次审计输入爆炸
        parts.append("\n</chapters_to_audit>\n")
        parts.append("请按 system prompt 要求输出完整 JSON 审计报告。")
        return "\n".join(parts)

    # ------------------------------------------------------------------ 生成与自修复

    def _generate_with_repair(self, user_msg: str) -> AuditReport:
        prompt = user_msg
        last_err: Exception | None = None

        for attempt in range(1 + MAX_REPAIR_ATTEMPTS):
            raw = self._call(prompt)
            try:
                data = self._extract_json(raw)
                return AuditReport.model_validate(data)
            except (json.JSONDecodeError, ValidationError, ValueError) as e:
                last_err = e
                logger.warning("ContinuityAuditor 输出校验失败（第%d次）：%s", attempt + 1, e)
                prompt = self._build_repair_msg(user_msg, raw, e)

        raise AuditError(f"自修复 {MAX_REPAIR_ATTEMPTS} 次后仍无法得到合法报告：{last_err}")

    def _call(self, user_msg: str) -> str:
        structured = getattr(self, "_call_llm_structured", None)
        if callable(structured):
            return structured(user_msg, json_schema=AuditReport.model_json_schema())
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
            "若上次输出疑似被截断，请压缩 summary 与 evidence 的篇幅。"
        )

    # ------------------------------------------------------------------ 代码对账

    @staticmethod
    def _finalize(report: AuditReport, as_of_chapter: int) -> dict:
        data = report.model_dump()
        data["as_of_chapter"] = int(as_of_chapter or 0)

        # 按严重度排序：S1 > S2 > S3 > S4，同级按章节升序
        order = {s: i for i, s in enumerate(SEVERITIES)}
        data["findings"] = sorted(
            data["findings"],
            key=lambda f: (order.get(f["severity"], 9), f.get("chapter", 0)),
        )
        return data
