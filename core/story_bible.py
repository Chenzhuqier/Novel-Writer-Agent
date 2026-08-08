"""
故事圣经（Story Bible）—— 长篇小说一致性保障的核心数据层

改进点（v0.2）：
1. 版本控制（checkpoint/rollback）
2. 上下文压缩器（解决长篇 context 爆炸问题）
3. 更完善的数据校验

v0.2 修复：
- ✅ 补全缺失的 StoryBible 基类（原 VersionedStoryBible 继承了不存在的类）
"""

import json
import hashlib
import uuid
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, field, asdict


# ============================================================
# 数据模型（保持原有设计，增加版本字段）
# ============================================================

@dataclass
class Character:
    """角色卡片"""
    id: str = ""
    name: str = ""
    alias: list = field(default_factory=list)
    age: Optional[int] = None
    gender: str = ""
    appearance: str = ""
    personality: list = field(default_factory=list)
    abilities: dict = field(default_factory=dict)
    status: str = "alive"  # alive / dead / missing / injured
    relationships: list = field(default_factory=list)
    arc: str = ""
    first_appearance: str = ""
    notes: str = ""

    def __post_init__(self):
        if not self.id:
            self.id = f"char_{uuid.uuid4().hex[:6]}"

    def to_text(self) -> str:
        """转为文本用于向量检索"""
        rels = ", ".join([f"{r.get('type', '')}({r.get('target', '')})" for r in self.relationships])
        return (
            f"【{self.name}】{'/'.join(self.alias) if self.alias else ''}\n"
            f"  年龄:{self.age or '?'} 性别:{self.gender}\n"
            f"  外貌:{self.appearance}\n"
            f"  性格:{', '.join(self.personality)}\n"
            f"  能力:{json.dumps(self.abilities, ensure_ascii=False)}\n"
            f"  状态:{self.status}\n"
            f"  关系:{rels or '无'}\n"
            f"  角色弧线:{self.arc}"
        )


@dataclass
class Location:
    """地点"""
    id: str = ""
    name: str = ""
    type: str = ""
    description: str = ""
    related_characters: list = field(default_factory=list)
    significance: str = ""

    def __post_init__(self):
        if not self.id:
            self.id = f"loc_{uuid.uuid4().hex[:6]}"


@dataclass
class Item:
    """道具/物品"""
    id: str = ""
    name: str = ""
    description: str = ""
    owner_id: str = ""
    special_ability: str = ""
    status: str = ""
    first_mention: str = ""

    def __post_init__(self):
        if not self.id:
            self.id = f"item_{uuid.uuid4().hex[:6]}"


@dataclass
class Foreshadowing:
    """伏笔"""
    id: str = ""
    content: str = ""
    planted_in: str = ""
    resolved_in: Optional[str] = None
    resolved: bool = False
    hint: str = ""

    def __post_init__(self):
        if not self.id:
            self.id = f"fs_{uuid.uuid4().hex[:6]}"


@dataclass
class TimelineEvent:
    """时间线事件"""
    chapter: str = ""
    event: str = ""
    story_day: Optional[int] = None
    characters_involved: list = field(default_factory=list)


@dataclass
class ChapterSummary:
    """章节摘要"""
    chapter_num: int = 0
    title: str = ""
    summary: str = ""
    characters_present: list = field(default_factory=list)
    key_events: list = field(default_factory=list)
    character_state_changes: dict = field(default_factory=dict)
    new_foreshadowing: list = field(default_factory=list)
    resolved_foreshadowing: list = field(default_factory=list)


# ============================================================
# 基础故事圣经类（v0.2 修复：补全缺失的基类）
# ============================================================

class StoryBible:
    """
    故事圣经基础类 —— 管理小说的所有设定和状态数据

    这是 VersionedStoryBible 的基类，提供核心的数据存储和检索功能。
    所有实体（角色、地点、道具、伏笔等）都通过此类管理。
    """

    def __init__(self, title: str = "", genre: str = "", premise: str = ""):
        # 元信息
        self.meta = {
            "title": title,
            "genre": genre,
            "premise": premise,
            "created_at": datetime.now().isoformat(),
        }

        # 世界观备注和文风指南
        self.world_notes: str = ""
        self.style_guide: str = ""

        # 实体存储（使用字典以支持按 ID 检索）
        self.characters: dict[str, Character] = {}
        self.locations: dict[str, Location] = {}
        self.items: dict[str, Item] = {}
        self.foreshadowings: dict[str, Foreshadowing] = {}

        # 时间线和章节摘要
        self.timeline: list[TimelineEvent] = []
        self.chapter_summaries: dict[int, ChapterSummary] = {}

    # ============================================================
    # 角色管理
    # ============================================================

    def add_character(self, **kwargs) -> Character:
        """添加角色"""
        char = Character(**kwargs)
        self.characters[char.id] = char
        return char

    def get_character(self, name: str) -> Optional[Character]:
        """按名称查找角色（模糊匹配）"""
        for char in self.characters.values():
            if char.name == name or name in char.alias:
                return char
        return None

    def get_active_characters(self) -> list[Character]:
        """获取所有存活的角色"""
        return [c for c in self.characters.values() if c.status == "alive"]

    def update_character_status(self, name: str, status: str):
        """更新角色状态"""
        char = self.get_character(name)
        if char:
            char.status = status

    # ============================================================
    # 地点管理
    # ============================================================

    def add_location(self, **kwargs) -> Location:
        """添加地点"""
        loc = Location(**kwargs)
        self.locations[loc.id] = loc
        return loc

    def get_location(self, name: str) -> Optional[Location]:
        """按名称查找地点"""
        for loc in self.locations.values():
            if loc.name == name:
                return loc
        return None

    # ============================================================
    # 道具管理
    # ============================================================

    def add_item(self, **kwargs) -> Item:
        """添加道具"""
        item = Item(**kwargs)
        self.items[item.id] = item
        return item

    # ============================================================
    # 伏笔管理
    # ============================================================

    def add_foreshadowing(self, **kwargs) -> Foreshadowing:
        """添加伏笔"""
        fs = Foreshadowing(**kwargs)
        self.foreshadowings[fs.id] = fs
        return fs

    def resolve_foreshadowing(self, foreshadowing_id: str, resolved_in: str):
        """回收伏笔"""
        if foreshadowing_id in self.foreshadowings:
            fs = self.foreshadowings[foreshadowing_id]
            fs.resolved = True
            fs.resolved_in = resolved_in

    def get_unresolved_foreshadowings(self) -> list[Foreshadowing]:
        """获取所有未回收的伏笔"""
        return [fs for fs in self.foreshadowings.values() if not fs.resolved]

    def get_foreshadowings_planted_before(self, chapter_key: str) -> list[Foreshadowing]:
        """获取在指定章节之前埋设的未回收伏笔"""
        unresolved = self.get_unresolved_foreshadowings()
        # 简单实现：返回所有未回收伏笔（实际可根据 planted_in 过滤）
        return unresolved

    # ============================================================
    # 时间线管理
    # ============================================================

    def add_timeline_event(self, chapter: str, event: str,
                           characters_involved: list = None, story_day: int = None):
        """添加时间线事件"""
        evt = TimelineEvent(
            chapter=chapter,
            event=event,
            characters_involved=characters_involved or [],
            story_day=story_day,
        )
        self.timeline.append(evt)

    # ============================================================
    # 章节摘要管理
    # ============================================================

    def add_chapter_summary(self, summary: ChapterSummary):
        """添加章节摘要"""
        self.chapter_summaries[summary.chapter_num] = summary

    def get_recent_summaries(self, count: int = 3) -> list[ChapterSummary]:
        """获取最近的章节摘要"""
        sorted_chapters = sorted(self.chapter_summaries.keys())
        recent_nums = sorted_chapters[-count:] if len(sorted_chapters) >= count else sorted_chapters
        return [self.chapter_summaries[n] for n in recent_nums]

    # ============================================================
    # 序列化
    # ============================================================

    def to_dict(self) -> dict:
        """导出为字典"""
        data = {"meta": self.meta}
        data["characters"] = {k: asdict(v) for k, v in self.characters.items()}
        data["locations"] = {k: asdict(v) for k, v in self.locations.items()}
        data["items"] = {k: asdict(v) for k, v in self.items.items()}
        data["foreshadowings"] = {k: asdict(v) for k, v in self.foreshadowings.items()}
        data["timeline"] = [asdict(t) for t in self.timeline]
        data["chapter_summaries"] = {k: asdict(v) for k, v in self.chapter_summaries.items()}
        data["world_notes"] = self.world_notes
        data["style_guide"] = self.style_guide
        return data

    def to_json(self, filepath: str):
        """导出为 JSON 文件"""
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, filepath: str) -> "StoryBible":
        """从 JSON 文件导入"""
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        sb = cls(
            title=data["meta"].get("title", ""),
            genre=data["meta"].get("genre", ""),
            premise=data["meta"].get("premise", ""),
        )
        sb.meta = data["meta"]
        sb.world_notes = data.get("world_notes", "")
        sb.style_guide = data.get("style_guide", "")
        sb._from_dict(data)
        return sb

    def _from_dict(self, data: dict):
        """从字典恢复状态"""
        self.meta = data.get("meta", {})
        self.world_notes = data.get("world_notes", "")
        self.style_guide = data.get("style_guide", "")

        # 还原各实体
        self.characters.clear()
        for cid, cd in data.get("characters", {}).items():
            self.characters[cid] = Character(**cd)

        self.locations.clear()
        for lid, ld in data.get("locations", {}).items():
            self.locations[lid] = Location(**ld)

        self.items.clear()
        for iid, id_ in data.get("items", {}).items():
            self.items[iid] = Item(**id_)

        self.foreshadowings.clear()
        for fid, fd in data.get("foreshadowings", {}).items():
            self.foreshadowings[fid] = Foreshadowing(**fd)

        self.timeline.clear()
        for td in data.get("timeline", []):
            self.timeline.append(TimelineEvent(**td))

        self.chapter_summaries.clear()
        for num, sd in data.get("chapter_summaries", {}).items():
            self.chapter_summaries[int(num)] = ChapterSummary(**sd)

    def _touch(self):
        """标记修改（子类可重写）"""
        pass

    def __repr__(self):
        active = len(self.get_active_characters())
        return (
            f"<StoryBible '{self.meta['title']}' | "
            f"{len(self.characters)}角色({active}活跃) | "
            f"{len(self.foreshadowings)}伏笔({len(self.get_unresolved_foreshadowings())}未收) | "
            f"{len(self.chapter_summaries)}章已写>"
        )


# ============================================================
# 版本控制的故事圣经
# ============================================================

class StoryBibleVersion:
    """单个版本快照"""
    def __init__(self, version_id: int, reason: str, data: dict):
        self.version_id = version_id
        self.timestamp = datetime.now().isoformat()
        self.reason = reason
        self.data = data
        self.hash = hashlib.md5(json.dumps(data, ensure_ascii=False).encode()).hexdigest()


class VersionedStoryBible(StoryBible):
    """
    增强版故事圣经 —— 支持版本控制和上下文压缩

    改进点：
    - checkpoint/rollback 版本管理
    - 智能上下文组装（避免 context 爆炸）
    - Token 预估与截断
    """

    # 默认配置
    MAX_VERSIONS = 100          # 最大保留版本数（内存）
    PERSIST_MAX_VERSIONS = 10   # 落盘持久化的版本数（全量快照，限制文件体积）
    MAX_CONTEXT_CHARS = 8000     # 上下文最大字符数
    DEFAULT_RECENT_SUMMARIES = 3  # 默认获取最近几章摘要
    DEFAULT_MAX_CHARACTERS = 8   # 默认最大展示角色数

    def __init__(self, title: str = "", genre: str = "", premise: str = ""):
        super().__init__(title, genre, premise)

        # 版本控制
        self._versions: list[StoryBibleVersion] = []
        self._auto_checkpoint = True
        self._version_counter = 0

        # 创建初始版本
        self.checkpoint("初始化")

    # ============================================================
    # 版本控制接口
    # ============================================================

    def checkpoint(self, reason: str = "") -> StoryBibleVersion:
        """
        创建检查点 —— 保存当前状态到版本历史

        Args:
            reason: 创建此版本的原因描述

        Returns:
            版本对象
        """
        version = StoryBibleVersion(
            version_id=self._version_counter,
            reason=reason,
            # 快照使用基础 dict（不含版本历史），避免快照递归嵌套
            data=StoryBible.to_dict(self),
        )
        self._versions.append(version)
        self._version_counter += 1

        # 清理旧版本
        if len(self._versions) > self.MAX_VERSIONS:
            self._versions = self._versions[-self.MAX_VERSIONS:]

        return version

    def rollback(self, version_id: int = None) -> StoryBibleVersion:
        """
        回滚到指定版本

        Args:
            version_id: 目标版本号，None 表示回滚到上一版本

        Returns:
            回滚到的版本对象
        """
        if not self._versions:
            raise ValueError("没有可回滚的版本")

        if version_id is None:
            # 回滚到上一个版本
            if len(self._versions) < 2:
                raise ValueError("只有一个版本，无法回滚")
            target = self._versions[-2]
        else:
            # 找到指定版本
            target = None
            for v in self._versions:
                if v.version_id == version_id:
                    target = v
                    break
            if not target:
                raise ValueError(f"版本 {version_id} 不存在")

        # 从版本数据恢复
        self._from_dict(target.data)

        print(f"[StoryBible] 已回滚到版本 {target.version_id} ({target.timestamp})")
        return target

    @property
    def current_version(self) -> int:
        """当前版本号"""
        return self._version_counter - 1

    @property
    def version_count(self) -> int:
        """总版本数"""
        return len(self._versions)

    def get_version_history(self, limit: int = 20) -> list[dict]:
        """获取版本历史列表"""
        recent = self._versions[-limit:] if limit else self._versions
        return [
            {
                "version_id": v.version_id,
                "timestamp": v.timestamp,
                "reason": v.reason,
                "hash": v.hash[:12],
            }
            for v in reversed(recent)
        ]

    # ============================================================
    # 增强的上下文组装（解决长篇 context 爆炸）
    # ============================================================

    def build_context_for_chapter(
        self,
        chapter_num: int,
        chapter_outline: str = "",
        character_names: list[str] = None,
        max_chars: int = None,
        index=None,
    ) -> str:
        """
        为指定章节组装写作上下文（增强版）

        改进点：
        - 支持 max_chars 截断
        - 智能优先级排序
        - Token 预估
        - v0.3：传入可选 SemanticIndex 时，“待回收伏笔”“前情提要”改用语义召回，
          并输出“语义相关设定”段；无索引/未启用时行为与旧版完全一致。

        Args:
            chapter_num: 当前章节号
            chapter_outline: 本章大纲文本
            character_names: 指定的角色名列表
            max_chars: 最大字符限制（None 使用默认值）
            index: 可选的 SemanticIndex（禁用或为 None 时走原有逻辑）

        Returns:
            组装好的上下文字符串
        """
        max_chars = max_chars or self.MAX_CONTEXT_CHARS
        parts = []
        ch_key = f"ch{chapter_num}"
        use_vector = index is not None and getattr(index, "enabled", False)
        search_query = (chapter_outline or "")[:400]

        # === 1. 基本信息 ===
        parts.append("=== 故事设定 ===")
        parts.append(f"书名：{self.meta['title']}")
        parts.append(f"类型：{self.meta['genre']}")

        # === 2. 相关角色（按相关性排序）===
        target_chars = character_names or []
        chars_to_show = []
        for name in target_chars:
            c = self.get_character(name)
            if c:
                chars_to_show.append(c)

        # 如果没指定角色，展示所有活跃角色（限制数量）
        if not chars_to_show:
            active = self.get_active_characters()
            chars_to_show = active[:self.DEFAULT_MAX_CHARACTERS]

        if chars_to_show:
            parts.append("\n=== 角色信息 ===")
            for c in chars_to_show:
                parts.append(c.to_text())

        # === 3. 未回收伏笔（高优先级）===
        unresolved = self.get_foreshadowings_planted_before(ch_key)
        if unresolved:
            parts.append("\n=== 待回收伏笔 ===")
            shown_fs = unresolved[:5] if not use_vector else self._pick_foreshadowings(
                unresolved, index, search_query, 5,
            )
            for fs in shown_fs:
                parts.append(f"- [{fs.planted_in}] {fs.content} (提示:{fs.hint or '无'})")

        # === 3.5 语义相关设定（可选：角色/地点/道具补充召回）===
        shown_related = []
        if use_vector and search_query:
            related_hits = index.search(search_query, top_k=6)
            shown_related = self._pick_semantic_settings(related_hits)
            if shown_related:
                parts.append("\n=== 语义相关设定 ===")
                parts.extend(shown_related)

        # === 4. 最近章节摘要 ===
        recent = self.get_recent_summaries(self.DEFAULT_RECENT_SUMMARIES)
        if recent:
            parts.append("\n=== 前情提要 ===")
            shown_sums = recent
            if use_vector:
                shown_sums = self._pick_summaries(recent, index, search_query, 3)
                if not shown_sums:
                    shown_sums = recent[:3]
            for s in shown_sums:
                parts.append(f"第{s.chapter_num}章 {s.title}: {s.summary}")

        # === 5. 时间线（最近事件）===
        if self.timeline:
            parts.append("\n=== 近期时间线 ===")
            for evt in self.timeline[-8:]:  # 最近 8 条
                chars = ", ".join(evt.characters_involved) if evt.characters_involved else ""
                parts.append(f"[{evt.chapter}] {evt.event}" + (f" (涉及:{chars})" if chars else ""))

        # === 6. 世界观补充（如果空间允许）===
        if self.world_notes:
            parts.append(f"\n=== 世界观补充 ===\n{self.world_notes}")

        # === 7. 文风指南 ===
        if self.style_guide:
            parts.append(f"\n=== 文风要求 ===\n{self.style_guide}")

        # 组装并截断
        full_context = "\n".join(parts)

        if len(full_context) > max_chars:
            full_context = self._compress_context(full_context, max_chars, chapter_num)

        return full_context

    # ============================================================
    # 语义召回辅助（仅在 index.enabled 时被调用，否则上层走原逻辑）
    # ============================================================

    def _pick_foreshadowings(self, unresolved, index, query: str, top_k: int) -> list:
        """按语义相关度从未回收伏笔中挑选 top_k 条。"""
        hits = index.search(query, top_k=max(top_k * 3, 10), prefix="fs:")
        id_map = {f"fs:{fs.id}": fs for fs in unresolved}
        picked = []
        for h in hits:
            fs = id_map.get(h["doc_id"])
            if fs and fs not in picked:
                picked.append(fs)
            if len(picked) >= top_k:
                break
        return picked or unresolved[:top_k]

    def _pick_summaries(self, recent, index, query: str, top_k: int) -> list:
        """按语义相关度从最近摘要中挑选 top_k 条。"""
        hits = index.search(query, top_k=max(top_k * 2, 6))
        picked = []
        for h in hits:
            doc_id = h.get("doc_id", "")
            if not doc_id.startswith("sum:"):
                continue
            num = doc_id.split(":", 1)[1]
            for s in recent:
                if s.chapter_num == int(num) and s not in picked:
                    picked.append(s)
                    break
            if len(picked) >= top_k:
                break
        return picked

    def _pick_semantic_settings(self, related_hits: list, max_blocks: int = 3) -> list:
        """从语义命中里挑选角色/地点/道具/世界观的补充设定文本。"""
        blocks = []
        for h in related_hits:
            doc_id = h.get("doc_id", "")
            if not doc_id.startswith(("char:", "loc:", "item:", "world:")):
                continue
            text = h.get("text", "")
            if text and text not in blocks:
                blocks.append(text)
            if len(blocks) >= max_blocks:
                break
        return blocks

    def _compress_context(self, context: str, max_chars: int, chapter_num: int) -> str:
        """
        上下文压缩策略

        当上下文超长时，按优先级逐步裁剪：
        1. 裁剪世界观备注（保留前500字）
        2. 减少角色数量（只保留本章出场角色）
        3. 缩减时间线（只保留最近3条）
        4. 缩减前情提要（只保留最近1章）
        """
        lines = context.split("\n")
        sections = {}
        current_section = "__header__"
        section_lines = []

        for line in lines:
            if line.startswith("=== ") and line.endswith(" ==="):
                if current_section:
                    sections[current_section] = section_lines
                current_section = line.strip("= ").strip()
                section_lines = []
            else:
                section_lines.append(line)
        sections[current_section] = section_lines

        # 按优先级裁剪
        priority_order = [
            "故事设定",
            "角色信息",
            "待回收伏笔",
            "语义相关设定",
            "前情提要",
            "近期时间线",
            "世界观补充",
            "文风要求",
        ]

        result_parts = []
        total_chars = 0

        for section_name in priority_order:
            if section_name not in sections:
                continue

            section_content = "\n".join(sections[section_name])

            # 根据剩余空间决定是否保留完整内容
            remaining = max_chars - total_chars - 50  # 预留缓冲

            if remaining <= 0:
                break

            if len(section_content) <= remaining:
                # 完整保留此部分
                result_parts.append(f"\n=== {section_name} ===\n{section_content}")
                total_chars += len(section_content) + len(f"\n=== {section_name} ===\n")
            else:
                # 裁剪此部分
                truncated = self._truncate_section(section_name, section_content, remaining)
                result_parts.append(truncated)
                total_chars += len(truncated)
                break  # 一旦开始裁剪，后面的都跳过

        return "\n".join(result_parts)

    def _truncate_section(self, name: str, content: str, max_len: int) -> str:
        """根据section类型采用不同的裁剪策略"""
        if name == "角色信息":
            # 按字符预算保留尽量多的角色（行长度差异很大，不能按行数裁剪）
            lines = content.split("\n")
            header = f"\n=== {name} ===\n"
            budget = max_len - len(header) - len("... (更多角色已省略)")
            if budget <= 0:
                return header
            kept = []
            used = 0
            for line in lines:
                if used + len(line) + 1 > budget:
                    break
                kept.append(line)
                used += len(line) + 1
            if len(kept) < len(lines):
                return header + "\n".join(kept) + "\n... (更多角色已省略)"
            return header + "\n".join(kept)
        elif name == "近期时间线":
            # 只保留最后3条
            lines = content.strip().split("\n")
            return f"\n=== {name} ===\n" + "\n".join(lines[-3:]) if lines else ""
        elif name == "前情提要":
            # 只保留最后一章
            lines = content.strip().split("\n")
            return f"\n=== {name} ===\n" + lines[-1] if lines else ""
        elif name == "世界观补充":
            # 截断到固定长度
            return f"\n=== {name} ===\n" + content[:max_len - 30] + "\n..."
        else:
            return f"\n=== {name} ===\n" + content[:max_len - 30]

        return ""

    def estimate_context_tokens(self, chapter_num: int, **kwargs) -> int:
        """预估上下文的 token 数量（粗略估算：中文字符约 1.5 tokens/字）"""
        context = self.build_context_for_chapter(chapter_num, **kwargs)
        return int(len(context) * 1.5)

    # ============================================================
    # 重写 _touch 以支持自动 checkpoint
    # ============================================================

    def _touch(self):
        super()._touch()
        if self._auto_checkpoint:
            # 不是每次修改都存档，而是标记需要存档
            # 实际存档在关键节点手动调用 checkpoint()
            pass

    # ============================================================
    # 序列化（保持兼容）
    # ============================================================

    def to_dict(self) -> dict:
        data = super().to_dict()
        data["version_counter"] = self._version_counter
        data["versions"] = [
            {
                "version_id": v.version_id,
                "timestamp": v.timestamp,
                "reason": v.reason,
                "hash": v.hash,
                "data": v.data,
            }
            for v in self._versions[-self.PERSIST_MAX_VERSIONS:]
        ]
        return data

    def _from_dict(self, data: dict):
        """从字典恢复状态（含版本历史；兼容无 versions 字段的旧格式）"""
        super()._from_dict(data)

        self._versions = []
        for vd in data.get("versions", []):
            ver = StoryBibleVersion(
                version_id=vd.get("version_id", 0),
                reason=vd.get("reason", ""),
                data=vd.get("data", {}),
            )
            ver.timestamp = vd.get("timestamp", ver.timestamp)
            ver.hash = vd.get("hash", ver.hash)
            self._versions.append(ver)

        if not self._versions:
            # 旧格式数据：以当前状态补一条“恢复初始版本”，保证可回滚
            legacy = StoryBibleVersion(
                version_id=0,
                reason="恢复初始版本",
                data=StoryBible.to_dict(self),
            )
            self._versions.append(legacy)

        counter = data.get("version_counter", len(self._versions))
        self._version_counter = max(int(counter), len(self._versions))

    def to_json(self, filepath: str):
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, filepath: str) -> "VersionedStoryBible":
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        sb = cls(title=data["meta"].get("title", ""),
                 genre=data["meta"].get("genre", ""),
                 premise=data["meta"].get("premise", ""))
        sb.meta = data["meta"]
        sb.world_notes = data.get("world_notes", "")
        sb.style_guide = data.get("style_guide", "")
        sb._from_dict(data)
        return sb

    def __repr__(self):
        active = len(self.get_active_characters())
        return (
            f"<VersionedStoryBible '{self.meta['title']}' | "
            f"{len(self.characters)}角色({active}活跃) | "
            f"{len(self.foreshadowings)}伏笔({len(self.get_unresolved_foreshadowings())}未收) | "
            f"{len(self.chapter_summaries)}章已写 | "
            f"v{self.current_version}>"
        )
