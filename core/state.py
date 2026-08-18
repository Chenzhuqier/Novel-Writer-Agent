"""
跨章状态追踪器：为 PlotChecker 提供角色状态/伏笔台账/前情摘要/历史问题，
并在检查通过后回写报告产出的状态变化，形成闭环。
"""

from __future__ import annotations

import re
from collections import deque
from typing import Any, Optional


class StoryStateTracker:
    """角色状态与伏笔台账由生成流程（或人工）维护，本类负责装配与回写。"""

    def __init__(self, digest_window: int = 3, index=None, as_of_chapter: int = 0):
        self.character_states: list[dict] = []
        self.open_foreshadowing: list[str] = []
        self._digests: deque[str] = deque(maxlen=digest_window)
        self.issue_history: list[dict] = []
        # 可选语义索引：接入后伏笔匹配走向量相似度，否则回退子串
        self.index = index
        self.as_of_chapter = int(as_of_chapter or 0)  # 供伏笔搁置时长计算

    # ---------------- 角色状态维护（由生成 Agent / 人工调用） ----------------

    def upsert_character(self, name: str, **fields: Any) -> dict:
        for c in self.character_states:
            if c.get("name") == name:
                c.update(fields)
                return c
        entry = {"name": name, "alive": True, **fields}
        self.character_states.append(entry)
        return entry

    def mark_dead(self, name: str, chapter: int) -> None:
        self.upsert_character(name, alive=False, died_at=chapter)

    # ---------------- 与 CheckerAgent 的接口 ----------------

    def build_checker_inputs(self) -> dict:
        """生成 checker.run() 的关键字参数。"""
        return {
            "character_states": self.character_states or None,
            "open_foreshadowing": self._aged_foreshadowings() or None,
            "prev_chapter_digest": "\n".join(self._digests),
            "issue_history": list(self.issue_history),
        }

    def _aged_foreshadowings(self) -> list[str]:
        """给未回收伏笔标注埋设章与搁置时长（埋设超过 5 章未回收给 warning 提示）。"""
        out = []
        for f in self.open_foreshadowing:
            line = str(f)
            m = re.search(r"第\s*(\d+)\s*章", line)
            if m:
                planted = int(m.group(1))
                age = self.as_of_chapter - planted
                if 5 <= age <= 8:
                    out.append(f"{line}（已埋设{age}章，建议近期推进）")
                elif age > 8:
                    out.append(f"{line}（已埋设{age}章未回收，建议安排回收）")
                else:
                    out.append(line)
            else:
                out.append(line)
        return out

    def mark_chapter(self, chapter_num: int) -> None:
        """更新账本已知章节号（供伏笔搁置时长计算）。"""
        self.as_of_chapter = max(self.as_of_chapter, int(chapter_num or 0))

    def ingest_report(self, chapter_num: int, report: dict,
                      chapter_digest: str = "", index=None) -> None:
        """检查通过（或修订完成）后回写：更新伏笔台账、摘要与历史问题。"""
        self.index = index if index is not None else self.index
        for note in report.get("foreshadowing_notes", []):
            if note.startswith("【埋设】"):
                self.open_foreshadowing.append(note.removeprefix("【埋设】").strip())
            elif note.startswith("【回收】"):
                content = note.removeprefix("【回收】").strip()
                self.open_foreshadowing = [
                    f for f in self.open_foreshadowing
                    if not self._similar(f, content, index=self.index)
                ]
            # 【推进】不改变台账

        if chapter_digest:
            self._digests.append(f"第{chapter_num}章：{chapter_digest}")

        self.issue_history.append({
            "chapter": chapter_num,
            "issue_types": sorted({
                i["type"] for i in report.get("issues", [])
                if i.get("severity") in ("error", "warning")
            }),
        })

    @staticmethod
    def _similar(a: str, b: str, index=None, threshold: float = 0.75) -> bool:
        """伏笔匹配：接入向量索引时按相似度阈值，否则用宽松子串匹配。

        index: 可选的 SemanticIndex；为 None 或已禁用/编码失败时回退子串匹配。
        """
        if index is not None:
            score = getattr(index, "similarity", None)
            if score is not None:
                try:
                    sim = score(a, b)
                except Exception:
                    sim = None
                if sim is not None:
                    return sim >= threshold
        return a[:12] in b or b[:12] in a

    # ---------------- 序列化（配合 NovelProject.save_state / load_state） ----------------

    def to_dict(self) -> dict:
        return {
            "character_states": self.character_states,
            "open_foreshadowing": self.open_foreshadowing,
            "digests": list(self._digests),
            "issue_history": self.issue_history,
            "as_of_chapter": self.as_of_chapter,
        }

    @classmethod
    def from_dict(cls, data: dict, digest_window: int = 3) -> "StoryStateTracker":
        tracker = cls(digest_window=digest_window,
                      as_of_chapter=data.get("as_of_chapter", 0))
        tracker.character_states = list(data.get("character_states", []))
        tracker.open_foreshadowing = list(data.get("open_foreshadowing", []))
        for d in data.get("digests", []):
            tracker._digests.append(d)
        tracker.issue_history = list(data.get("issue_history", []))
        return tracker