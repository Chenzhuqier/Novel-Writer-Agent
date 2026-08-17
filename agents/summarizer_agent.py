"""
章节摘要提取 Agent —— 负责从正文提取结构化摘要，供故事圣经与跨章状态追踪使用

改进点（v0.5）：
1. 新增 Pydantic schema 校验，输出字段与 core/story_bible.ChapterSummary 严格对齐
2. chapter_num 由代码强制覆盖，避免模型输出错号
3. 超长正文走「分块摘要 → 字段级合并」管线，突破 3000 字硬截断限制
4. 输入校验、解析失败回喂重试、结构化日志
5. 摘要质量兜底：逐字段类型强转补全，对超长 summary 做截断
6. title 支持外部传入或正则首行提取
7. 配置参数化：分块大小、token 限制、温度、重试次数均可通过 kwargs 覆盖
"""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field, field_validator

from .base import BaseAgent, register_demo, DEMO_SUMMARY

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schema – 与 core/story_bible.ChapterSummary 严格对齐
# ---------------------------------------------------------------------------


class ChapterSummarySchema(BaseModel):
    """章节摘要的结构化 Schema，用于 LLM 输出校验"""

    chapter_num: int = Field(default=0, description="章号")
    title: str = Field(default="", description="章节标题")
    summary: str = Field(default="", description="200字以内摘要")
    characters_present: List[str] = Field(default_factory=list, description="本章出场角色列表")
    key_events: List[str] = Field(default_factory=list, description="按时间顺序的关键事件")
    character_state_changes: Dict[str, str] = Field(
        default_factory=dict,
        description="角色状态变化（与上一章相比）",
    )
    new_foreshadowing: List[str] = Field(
        default_factory=list, description="本章新埋设的伏笔"
    )
    resolved_foreshadowing: List[str] = Field(
        default_factory=list, description="本章回收的既有伏笔"
    )

    @field_validator("summary")
    @classmethod
    def _truncate_summary(cls, v: str) -> str:
        """强制将 summary 截断至 200 字"""
        return v[:200] if len(v) > 200 else v


# ---------------------------------------------------------------------------
# Demo 注册（冻结约定：保持原样，不可改动）
# ---------------------------------------------------------------------------

register_demo("ChapterSummarizer", DEMO_SUMMARY, estimated_tokens=800)


# ---------------------------------------------------------------------------
# 默认配置常量（可通过 kwargs 覆盖）
# ---------------------------------------------------------------------------

_DEFAULT_MAX_TEXT_CHARS = 8000       # 单次摘要允许的最大正文长度（超过则分块）
_DEFAULT_CHUNK_CHARS = 6000          # 分块目标字数（按段落边界切分）
_DEFAULT_SUMMARY_MAX_LEN = 200       # 摘要硬上限
_DEFAULT_TEMPERATURE = 0.3
_DEFAULT_MAX_TOKENS = 1024
_DEFAULT_MAX_PARSE_RETRIES = 1       # 解析失败回喂重试次数
_MAX_CHUNKS = 8                      # 分块数上限（超长正文先做绝对上限保护）

# 正则：匹配常见章节标题格式（第X章 / Chapter X / 数字. 标题 等）
_TITLE_RE = re.compile(
    r"^(?:第[一二三四五六七八九十百千\d]+章[：:\s]*|"
    r"Chapter\s+\d+[：:\s]*|"
    r"\d+[\.\、\s]\s*)",
    re.IGNORECASE,
)


class ChapterSummarizerAgent(BaseAgent):
    """章节摘要提取 Agent

    改进点：
    - Pydantic schema 强校验，保证输出字段完整且类型安全
    - 长文本支持：超过 max_text_chars 的正文按段落分块、逐块摘要后字段级合并
    - 解析失败回喂错误重试，尽量拿到可用结构化结果
    - 错误分类：区分「解析失败」「字段缺失」「校验不通过」三类
    - 可观测性：每步关键操作均有 structured log
    """

    name = "ChapterSummarizer"
    description = "从章节正文提取结构化摘要"
    force_json_output = True

    # ------------------------------------------------------------------ #
    # Prompt
    # ------------------------------------------------------------------ #
    @property
    def system_prompt(self) -> str:
        return """你是一位严谨的小说编辑，负责从章节正文提取结构化摘要，供后续章节的写作与检查参考。

## 提取原则
1. **摘要精炼**：summary 控制在 200 字以内，概括本章核心剧情推进，不堆砌细节
2. **角色齐全**：characters_present 列出本章实际出场角色
3. **事件有序**：key_events 按时间顺序列出关键事件，每条一句话
4. **状态变化**：character_state_changes 只记录与上一章相比的状态变化（伤势/位置/心态/关系等），无变化则留空对象
5. **伏笔对账**：
   - new_foreshadowing 记录本章新埋设的伏笔（一句话一条）
   - resolved_foreshadowing 记录本章回收的既有伏笔（注明对应前文的伏笔）
   - 没有就留空数组，不要臆造

## 输出要求
请严格以 JSON 格式输出，字段如下：
```json
{
  "chapter_num": 章号,
  "title": "章节标题",
  "summary": "200字以内摘要",
  "characters_present": ["出场角色"],
  "key_events": ["关键事件1", "关键事件2"],
  "character_state_changes": {"角色名": "状态变化描述"},
  "new_foreshadowing": ["新埋设伏笔"],
  "resolved_foreshadowing": ["回收的伏笔"]
}
```

## ⛔ 禁止事项
- ❌ 不要编造正文中不存在的事件或角色
- ❌ 不要把"角色正常出场"误记为状态变化
- ❌ 不要在摘要中复述原文句子
- ❌ 不要在 JSON 外添加任何解释性文字"""

    # ------------------------------------------------------------------ #
    # 类型强转工具
    # ------------------------------------------------------------------ #
    @staticmethod
    def _to_str(v: Any) -> str:
        """任意值强转为字符串（None → 空串）"""
        return str(v) if v is not None else ""

    @staticmethod
    def _to_int(v: Any, default: int) -> int:
        """任意值强转为 int，失败用默认值"""
        try:
            return int(v)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _to_list(v: Any) -> List[str]:
        """任意值强转为字符串列表（list/分隔字符串 → 列表，其余 → 空列表）"""
        if isinstance(v, list):
            return [str(x) for x in v]
        if isinstance(v, str) and v.strip():
            return [x for x in re.split(r"[；;，,\n]", v) if x.strip()]
        return []

    @classmethod
    def _to_dict(cls, v: Any) -> Dict[str, str]:
        """任意值强转为 字符串→字符串 字典"""
        if isinstance(v, dict):
            return {str(k): cls._to_str(val) for k, val in v.items()}
        return {}

    # ------------------------------------------------------------------ #
    # 内部工具方法
    # ------------------------------------------------------------------ #
    @staticmethod
    def _extract_title_from_text(text: str) -> str:
        """尝试从正文首行提取章节标题；失败返回空串"""
        first_line = text.lstrip().split("\n", 1)[0].strip()
        m = _TITLE_RE.match(first_line)
        return first_line[m.end():].strip() if m else ""

    @staticmethod
    def _prepare_text(text: str, max_chars: int) -> str:
        """
        将正文裁剪到 max_chars 以内（绝对上限保护，供分块管线的前置步骤）。
        策略：优先保留头部（通常包含开头重要信息），
        若被截断则在末尾追加省略号提示。
        """
        if len(text) <= max_chars:
            return text
        logger.warning(
            "正文超长，从 %d 字截断至 %d 字", len(text), max_chars
        )
        return text[:max_chars].rstrip() + "\n…（后续内容已省略）"

    @staticmethod
    def _chunk_text(text: str, chunk_chars: int) -> List[str]:
        """
        按段落边界将文本切分为 ≤ chunk_chars 的块，尽量不切断句子。
        单段仍超长时按字符宽度硬分。
        """
        if not text:
            return []
        paragraphs = re.split(r"\n\s*\n", text)
        chunks: List[str] = []
        current = ""
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            if not current or len(current) + len(para) + 2 <= chunk_chars:
                current = f"{current}\n\n{para}" if current else para
                continue
            # 放不下：先落盘当前块
            if current:
                chunks.append(current)
            if len(para) <= chunk_chars:
                current = para
            else:
                # 单段超长：硬分
                for i in range(0, len(para), chunk_chars):
                    chunks.append(para[i:i + chunk_chars])
                current = ""
        if current:
            chunks.append(current)
        return chunks

    @staticmethod
    def _usable(result: Dict[str, Any]) -> bool:
        """判断解析结果是否可作为有效摘要使用"""
        return (
            isinstance(result, dict)
            and not result.get("parse_error")
            and bool(result.get("summary") or result.get("key_events"))
        )

    def _safe_parse(self, response: str, chapter_num: int) -> Dict[str, Any]:
        """
        三层解析 + 兜底：
        1) JSON 解析（失败 → 空结构 + parse_error 标记）
        2) Pydantic 校验（字段缺失时自动补默认值）
        3) 逐字段类型强转补全（校验仍失败时能塞多少塞多少）
        返回一个「一定可序列化、章号已强制」的 dict，绝不抛异常。
        """
        raw = self._parse_json_response(response)
        if not isinstance(raw, dict) or raw.get("parse_error"):
            logger.error("LLM 返回内容无法解析为 JSON: %s", str(response)[:200])
            empty = ChapterSummarySchema().model_dump()
            empty["chapter_num"] = chapter_num
            empty["parse_error"] = True
            empty["error_msg"] = (
                str(raw.get("error_msg")) if isinstance(raw, dict) else "无法解析为 JSON"
            )
            return empty

        try:
            schema = ChapterSummarySchema(**raw)
        except Exception as exc:
            logger.warning("Pydantic 校验未通过(%s)，逐字段强转兜底", exc)
            safe: Dict[str, Any] = {
                "chapter_num": self._to_int(raw.get("chapter_num"), chapter_num),
                "title": self._to_str(raw.get("title")),
                "summary": self._to_str(raw.get("summary"))[:_DEFAULT_SUMMARY_MAX_LEN],
                "characters_present": self._to_list(raw.get("characters_present")),
                "key_events": self._to_list(raw.get("key_events")),
                "character_state_changes": self._to_dict(raw.get("character_state_changes")),
                "new_foreshadowing": self._to_list(raw.get("new_foreshadowing")),
                "resolved_foreshadowing": self._to_list(raw.get("resolved_foreshadowing")),
            }
            schema = ChapterSummarySchema(**safe)

        result = schema.model_dump()
        # 章号由代码层强制覆盖，规避模型或 Demo 响应输出错号
        result["chapter_num"] = chapter_num
        logger.info(
            "章节 %d 摘要提取完成: %d 角色 / %d 事件 / %d 新伏笔 / %d 回收伏笔",
            chapter_num,
            len(result["characters_present"]),
            len(result["key_events"]),
            len(result["new_foreshadowing"]),
            len(result["resolved_foreshadowing"]),
        )
        return result

    def _summarize_chunk(
        self,
        chunk_text: str,
        chapter_num: int,
        resolved_title: str,
        chunk_idx: int,
        total_chunks: int,
        prior_summary: Optional[str],
        temperature: float,
        max_tokens: int,
        max_parse_retries: int,
    ) -> Dict[str, Any]:
        """对单个分块提取摘要，含解析失败回喂重试"""
        title_part = f"《{resolved_title}》" if resolved_title else ""
        if total_chunks > 1:
            heading = f"## 第{chapter_num}章{title_part}正文（第 {chunk_idx}/{total_chunks} 块）\n"
        else:
            heading = f"## 第{chapter_num}章{title_part}正文\n"
        prior_part = (
            f"\n## 前面内容摘要（供连续性参考，勿重复记录）\n{prior_summary}\n"
            if prior_summary
            else ""
        )
        user_msg = (
            f"请基于以下第{chapter_num}章正文提取结构化摘要。\n\n"
            f"{heading}{prior_part}{chunk_text}\n\n"
            "请直接输出 JSON，不要任何解释。"
        )

        logger.info(
            "开始提取第 %d 章第 %d/%d 块摘要，块长度=%d",
            chapter_num, chunk_idx, total_chunks, len(chunk_text),
        )
        result = self._safe_parse(
            self._call_llm(user_msg, temperature=temperature, max_tokens=max_tokens),
            chapter_num,
        )
        for attempt in range(1, max_parse_retries + 1):
            if self._usable(result):
                break
            logger.warning(
                "第 %d 章第 %d/%d 块摘要解析不可用，回喂错误重试 %d/%d",
                chapter_num, chunk_idx, total_chunks, attempt, max_parse_retries,
            )
            hint = result.get("error_msg") or "输出格式不符合要求，请严格按 JSON schema 输出"
            retry_msg = user_msg + (
                f"\n\n## 上一次输出不可用：{hint}\n"
                "请修正后重新输出严格 JSON，不要任何解释。"
            )
            result = self._safe_parse(
                self._call_llm(retry_msg, temperature=temperature, max_tokens=max_tokens),
                chapter_num,
            )
        return result

    @classmethod
    def _merge_partials(cls, partials: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        字段级合并各分块摘要：
        - summary：各块摘要用「；」连接后截断至 200 字
        - 列表字段：有序去重合并
        - character_state_changes：字典合并
        """
        if not partials:
            return ChapterSummarySchema().model_dump()

        def _dedup(items: List[str]) -> List[str]:
            seen: List[str] = []
            for it in items:
                s = str(it).strip()
                if s and s not in seen:
                    seen.append(s)
            return seen

        summary = "；".join(
            cls._to_str(p.get("summary")).strip() for p in partials
            if cls._to_str(p.get("summary")).strip()
        )[:_DEFAULT_SUMMARY_MAX_LEN]

        state_changes: Dict[str, str] = {}
        for p in partials:
            for k, v in cls._to_dict(p.get("character_state_changes")).items():
                state_changes[k] = v

        merged: Dict[str, Any] = {
            "chapter_num": next(
                (p["chapter_num"] for p in partials if p.get("chapter_num")), 0
            ),
            "title": next(
                (cls._to_str(p.get("title")) for p in partials if p.get("title")), ""
            ),
            "summary": summary,
            "characters_present": _dedup(
                sum((cls._to_list(p.get("characters_present")) for p in partials), [])
            ),
            "key_events": _dedup(
                sum((cls._to_list(p.get("key_events")) for p in partials), [])
            ),
            "character_state_changes": state_changes,
            "new_foreshadowing": _dedup(
                sum((cls._to_list(p.get("new_foreshadowing")) for p in partials), [])
            ),
            "resolved_foreshadowing": _dedup(
                sum((cls._to_list(p.get("resolved_foreshadowing")) for p in partials), [])
            ),
        }
        # 合并结果不保留解析/兜底标记字段
        return {k: v for k, v in merged.items()}

    # ------------------------------------------------------------------ #
    # 主入口
    # ------------------------------------------------------------------ #
    def run(
        self,
        chapter_text: str,
        chapter_num: int,
        title: Optional[str] = None,
        **kwargs: Any,
    ) -> dict:
        """提取章节摘要，返回可构造 ChapterSummary 的 dict

        Args:
            chapter_text: 章节正文
            chapter_num: 章号（代码层强制覆盖，不受模型输出影响）
            title: 可选的外部标题；若不传则尝试从正文首行提取
            **kwargs:
                max_text_chars: 单次摘要正文上限（默认 8000，超过走分块合并）
                chunk_chars: 分块目标字数（默认 6000）
                temperature: LLM 温度（默认 0.3）
                max_tokens: LLM 最大 token 数（默认 1024）
                max_parse_retries: 解析失败回喂重试次数（默认 1）

        Returns:
            符合 ChapterSummarySchema 的字典；所有分块均失败时带 parse_error 标记
        """
        self._validate_input(
            ["chapter_text", "chapter_num"],
            chapter_text=chapter_text,
            chapter_num=chapter_num,
        )

        # ---- 参数读取 ----
        max_text_chars: int = kwargs.get("max_text_chars", _DEFAULT_MAX_TEXT_CHARS)
        chunk_chars: int = kwargs.get("chunk_chars", _DEFAULT_CHUNK_CHARS)
        temperature: float = kwargs.get("temperature", _DEFAULT_TEMPERATURE)
        max_tokens: int = kwargs.get("max_tokens", _DEFAULT_MAX_TOKENS)
        max_parse_retries: int = kwargs.get("max_parse_retries", _DEFAULT_MAX_PARSE_RETRIES)

        # ---- 标题处理 ----
        resolved_title = title or self._extract_title_from_text(chapter_text)

        # ---- 正文长度分支：单次 or 分块合并 ----
        if len(chapter_text) <= max_text_chars:
            result = self._summarize_chunk(
                chapter_text, chapter_num, resolved_title,
                1, 1, None, temperature, max_tokens, max_parse_retries,
            )
        else:
            # 绝对上限保护后再分块，避免块数过多
            ceiling = max(max_text_chars, chunk_chars) * _MAX_CHUNKS
            prepared = self._prepare_text(chapter_text, ceiling)
            chunks = self._chunk_text(prepared, chunk_chars)
            logger.info(
                "第 %d 章正文 %d 字超长，分为 %d 块合并摘要",
                chapter_num, len(chapter_text), len(chunks),
            )
            partials = []
            for i, chunk in enumerate(chunks, start=1):
                prior = None
                if partials:
                    prior = self._merge_partials(partials).get("summary")
                partials.append(
                    self._summarize_chunk(
                        chunk, chapter_num, resolved_title,
                        i, len(chunks), prior, temperature, max_tokens, max_parse_retries,
                    )
                )
            result = self._merge_partials(partials)
            if not self._usable(result):
                result["parse_error"] = True
                result["error_msg"] = "所有分块摘要均解析失败"

        # 章号强制覆盖 + 标题回填
        result["chapter_num"] = chapter_num
        if not result.get("title") and resolved_title:
            result["title"] = resolved_title

        return result
