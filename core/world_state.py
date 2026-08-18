"""
世界状态账本 —— 长篇连贯性的权威记忆源。

设计：
- 每章归档后产出「截至第 N 章的世界状态快照」：角色生死/位置/实力、物品归属、
  地点状态、未闭合剧情线、待回收伏笔（含埋设章与搁置时长）。
- 写下一章前，由 build_continuity_contract() 把账本渲染成「连贯性契约」注入
  Writer，同时传给 Checker 作为校验基准 —— 模型记忆错位时当场暴露。
- 依赖缺失/无数据时安全降级为空账本，不影响既有流程（与向量索引策略一致）。
"""

from __future__ import annotations

import re
from typing import Any, Optional


class WorldState:
    """世界状态账本：随章节推进增量更新，供上下文注入与审计。"""

    def __init__(self):
        self.as_of_chapter: int = 0
        self.characters: dict[str, dict] = {}    # name → {alive, location, power_level, relationships, last_change}
        self.items: dict[str, dict] = {}         # name → {owner, location, status, last_change}
        self.locations: dict[str, dict] = {}     # name → {current_state, significance, last_change}
        self.open_threads: list[str] = []        # 未闭合剧情线（一句话）
        self.pending_foreshadowings: list[dict] = []  # {content, planted_in, hint, age}

    # ============================================================
    # 增量更新
    # ============================================================

    def apply_delta(self, chapter_num: int, delta: dict) -> None:
        """把一章的世界状态增量合并进账本。delta 结构见 ChapterSummary.world_state_delta。"""
        self.as_of_chapter = max(self.as_of_chapter, int(chapter_num or 0))
        if not delta:
            return

        for name, fields in (delta.get("characters") or {}).items():
            if not isinstance(fields, dict):
                continue
            entry = self.characters.setdefault(str(name), {})
            for key in ("alive", "location", "power_level", "relationships", "status", "note"):
                if key in fields:
                    entry[key] = fields[key]
            entry["last_change"] = f"第{chapter_num}章"
            # 位置变更留痕（供审计识别「瞬间传送」类连贯性问题）
            if fields.get("location"):
                entry.setdefault("location_history", [])
                if not entry["location_history"] or entry["location_history"][-1] != fields["location"]:
                    entry["location_history"].append(fields["location"])
                    if len(entry["location_history"]) > 12:
                        entry["location_history"] = entry["location_history"][-12:]
            # 生死状态归一为 bool（兼容字符串 "存活"/"死亡"/"true"/"false"）
            if "alive" in entry:
                entry["alive"] = self._normalize_alive(entry["alive"])

        for name, fields in (delta.get("items") or {}).items():
            if not isinstance(fields, dict):
                continue
            entry = self.items.setdefault(str(name), {})
            for key in ("owner", "location", "status", "note"):
                if key in fields:
                    entry[key] = fields[key]
            entry["last_change"] = f"第{chapter_num}章"

        for name, fields in (delta.get("locations") or {}).items():
            if not isinstance(fields, dict):
                continue
            entry = self.locations.setdefault(str(name), {})
            for key in ("current_state", "significance", "note"):
                if key in fields:
                    entry[key] = fields[key]
            entry["last_change"] = f"第{chapter_num}章"

        for t in (delta.get("open_threads") or []):
            if isinstance(t, str) and t.strip() and t.strip() not in self.open_threads:
                self.open_threads.append(t.strip())

    # ============================================================
    # 伏笔台账同步（与 StoryBible / StoryStateTracker 一致）
    # ============================================================

    def set_foreshadowings(self, pending: list[dict], as_of_chapter: int) -> None:
        """从 Bible 未回收伏笔刷新台账，并计算搁置时长（age）。"""
        self.as_of_chapter = max(self.as_of_chapter, int(as_of_chapter or 0))
        fresh = []
        for fs in pending:
            planted = _parse_chapter_num(fs.get("planted_in", ""))
            age = self.as_of_chapter - planted if planted else 0
            fresh.append({
                "content": fs.get("content", ""),
                "planted_in": fs.get("planted_in", ""),
                "planted_chapter": planted,
                "hint": fs.get("hint", ""),
                "age": max(age, 0),
            })
        self.pending_foreshadowings = fresh

    # ============================================================
    # 渲染
    # ============================================================

    def to_text(self, char_limit: int = 800) -> str:
        """渲染为「世界状态」文本块（供契约 / 审计 / 展示）。超长按优先级裁剪。"""
        parts = [f"世界状态（截至第{self.as_of_chapter}章）："]

        # 角色：优先展示存活/位置/实力
        char_lines = []
        for name, c in self.characters.items():
            alive = c.get("alive", True)
            status = "存活" if alive else "已死亡"
            bits = [status]
            for key, label in (("location", "位置"), ("power_level", "实力")):
                if c.get(key):
                    bits.append(f"{label}={c[key]}")
            if c.get("last_change"):
                bits.append(f"({c['last_change']}变更)")
            char_lines.append(f"- {name}：{'，'.join(bits)}")
        if char_lines:
            parts.append("角色：" + "\n  ".join(char_lines))

        item_lines = []
        for name, it in self.items.items():
            bits = []
            for key, label in (("owner", "持有"), ("location", "位置"), ("status", "状态")):
                if it.get(key):
                    bits.append(f"{label}={it[key]}")
            if bits:
                item_lines.append(f"- {name}：{'，'.join(bits)}")
        if item_lines:
            parts.append("物品：" + "\n  ".join(item_lines))

        loc_lines = []
        for name, lo in self.locations.items():
            bits = []
            if lo.get("current_state"):
                bits.append(lo["current_state"])
            if lo.get("significance"):
                bits.append(f"重要性={lo['significance']}")
            if bits:
                loc_lines.append(f"- {name}：{'，'.join(bits)}")
        if loc_lines:
            parts.append("地点：" + "\n  ".join(loc_lines))

        if self.open_threads:
            parts.append("进行中剧情线：")
            parts.extend(f"- {t}" for t in self.open_threads[:8])

        if self.pending_foreshadowings:
            parts.append("待回收伏笔：")
            for fs in self.pending_foreshadowings[:8]:
                aging = f"[埋设{fs['age']}章未回收]" if fs["age"] >= 5 else ""
                parts.append(f"- {fs['content']}（{fs['planted_in'] or '章数不明'}埋设）{aging}")

        text = "\n".join(parts)
        if len(text) > char_limit:
            text = text[:char_limit].rstrip() + "\n…（世界状态已截断）"
        return text

    # ============================================================
    # 序列化
    # ============================================================

    def to_dict(self) -> dict:
        return {
            "as_of_chapter": self.as_of_chapter,
            "characters": self.characters,
            "items": self.items,
            "locations": self.locations,
            "open_threads": self.open_threads,
            "pending_foreshadowings": self.pending_foreshadowings,
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> "WorldState":
        ws = cls()
        if not data:
            return ws
        ws.as_of_chapter = int(data.get("as_of_chapter", 0) or 0)
        ws.characters = dict(data.get("characters", {}) or {})
        ws.items = dict(data.get("items", {}) or {})
        ws.locations = dict(data.get("locations", {}) or {})
        ws.open_threads = list(data.get("open_threads", []) or [])
        ws.pending_foreshadowings = list(data.get("pending_foreshadowings", []) or [])
        return ws

    @staticmethod
    def _normalize_alive(v: Any) -> bool:
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.strip() not in ("0", "false", "False", "死亡", "已死", "dead", "失踪")
        return bool(v)


# ============================================================
# 连续性契约生成
# ============================================================

def build_continuity_contract(world_state: WorldState,
                              unresolved_fs: list[Any] = None,
                              current_arc: str = "",
                              glossary: list[str] = None) -> str:
    """把世界状态账本渲染为「连贯性契约」文本，注入 Writer / Checker。

    Args:
        world_state: 世界状态账本（可空，空则降级）
        unresolved_fs: StoryBible 未回收伏笔对象列表（用于补齐账本缺失时的台账）
        current_arc: 当前卷/弧线描述（大纲卷的 arc_summary 等）
        glossary: 设定字典（角色/别名/地名/物品名权威映射，防名称漂移）
    """
    lines = ["=== 连贯性契约 ===", "（本章必须遵守，违反即前后不一致）"]

    if world_state is None:
        # 账本缺失时降级：仅渲染未回收伏笔与弧线
        ws_lines = []
    else:
        ws_text = world_state.to_text(char_limit=600)
        if ws_text.strip():
            lines.append(ws_text)

    if unresolved_fs:
        fs_lines = []
        as_of = getattr(world_state, "as_of_chapter", 0) or 0
        for fs in unresolved_fs[:8]:
            aging = ""
            planted = _parse_chapter_num(fs.planted_in or "")
            if planted and as_of >= planted:
                age = as_of - planted
                aging = f"[埋设{age}章未回收]" if age >= 5 else ""
            fs_lines.append(f"- {fs.content}（{fs.planted_in or '章数不明'}埋设）{aging}"
                            + (f" 提示:{fs.hint}" if fs.hint else ""))
        if fs_lines:
            lines.append("待回收伏笔：")
            lines.extend(fs_lines)

    if current_arc:
        lines.append(f"当前剧情弧线：{current_arc}")

    if glossary:
        lines.append("设定字典（名词必须使用以下权威写法）：" + "；".join(glossary[:40]))

    return "\n".join(lines)


def _parse_chapter_num(text: str) -> int:
    """从 '第12章' / '12' / '第X章' 解析章号；解析失败返回 0。"""
    if not text:
        return 0
    m = re.search(r"第\s*([0-9一二三四五六七八九十百]+)\s*章", text)
    if m:
        return _cn2num(m.group(1))
    m = re.search(r"(\d+)", text)
    return int(m.group(1)) if m else 0


_CN_DIGITS = {"零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9}


def _cn2num(s: str) -> int:
    if s.isdigit():
        return int(s)
    total, section = 0, 0
    for ch in s:
        if ch in _CN_DIGITS:
            section = section * 10 + _CN_DIGITS[ch]
        elif ch in ("十", "百"):
            section = section or 1
            unit = 10 if ch == "十" else 100
            total += section * unit
            section = 0
    return total + section
