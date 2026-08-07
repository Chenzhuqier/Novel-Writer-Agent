"""
故事圣经（Story Bible）—— 长篇小说一致性保障的核心数据层

职责：
1. 结构化存储所有设定：人物、势力、地点、道具、伏笔、时间线
2. 提供检索接口，供写作 Agent 在生成新章节时按需注入上下文
3. 每章写完后自动更新状态（人物变化、伏笔推进等）
"""

import json
import uuid
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, field, asdict


@dataclass
class Character:
    """角色卡片"""
    id: str = ""
    name: str = ""
    alias: list = field(default_factory=list)  # 别名/称号
    age: Optional[int] = None
    gender: str = ""
    appearance: str = ""  # 外貌描述
    personality: list = field(default_factory=list)  # 性格标签
    abilities: dict = field(default_factory=dict)  # 能力/技能
    status: str = "alive"  # alive / dead / missing / injured
    relationships: list = field(default_factory=list)  # [{target_id, type, desc}]
    arc: str = ""  # 角色弧线描述
    first_appearance: str = ""  # 首次出场章节
    notes: str = ""

    def __post_init__(self):
        if not self.id:
            self.id = f"char_{uuid.uuid4().hex[:6]}"


@dataclass
class Location:
    """地点"""
    id: str = ""
    name: str = ""
    type: str = ""  # city / forest / building / etc.
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
    owner_id: str = ""  # 持有者角色ID
    special_ability: str = ""
    status: str = ""  # 当前状态
    first_mention: str = ""

    def __post_init__(self):
        if not self.id:
            self.id = f"item_{uuid.uuid4().hex[:6]}"


@dataclass
class Foreshadowing:
    """伏笔"""
    id: str = ""
    content: str = ""
    planted_in: str = ""  # 埋设章节
    resolved_in: Optional[str] = None  # 回收章节
    resolved: bool = False
    hint: str = ""  # 给写作Agent的提示

    def __post_init__(self):
        if not self.id:
            self.id = f"fs_{uuid.uuid4().hex[:6]}"


@dataclass
class TimelineEvent:
    """时间线事件"""
    chapter: str = ""
    event: str = ""
    story_day: Optional[int] = None  # 故事内第几天
    characters_involved: list = field(default_factory=list)


@dataclass
class ChapterSummary:
    """章节摘要"""
    chapter_num: int = 0
    title: str = ""
    summary: str = ""  # 200字以内摘要
    characters_present: list = field(default_factory=list)
    key_events: list = field(default_factory=list)
    character_state_changes: dict = field(default_factory=dict)  # {char_id: 变化描述}
    new_foreshadowing: list = field(default_factory=list)
    resolved_foreshadowing: list = field(default_factory=list)


class StoryBible:
    """
    故事圣经 —— 全局设定与记忆管理器
    
    设计原则：
    - 所有设定结构化存储，不依赖模型"记住"
    - 提供精确检索接口，支持 RAG 式的上下文组装
    - 支持序列化到 JSON，便于持久化和版本控制
    """

    def __init__(self, title: str = "", genre: str = "", premise: str = ""):
        self.meta = {
            "title": title,
            "genre": genre,
            "premise": premise,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "version": "0.1",
        }
        self.characters: dict[str, Character] = {}
        self.locations: dict[str, Location] = {}
        self.items: dict[str, Item] = {}
        self.foreshadowings: dict[str, Foreshadowing] = {}
        self.timeline: list[TimelineEvent] = []
        self.chapter_summaries: dict[int, ChapterSummary] = {}
        self.world_notes: str = ""  # 自由格式世界观笔记
        self.style_guide: str = ""  # 文风指南

    # ====== 角色操作 ======

    def add_character(self, **kwargs) -> Character:
        char = Character(**kwargs)
        self.characters[char.id] = char
        self._touch()
        return char

    def get_character(self, name_or_id: str) -> Optional[Character]:
        # 先按ID找
        if name_or_id in self.characters:
            return self.characters[name_or_id]
        # 再按名字找
        for c in self.characters.values():
            if c.name == name_or_id or name_or_id in c.alias:
                return c
        return None

    def update_character_status(self, char_id: str, status: str, note: str = ""):
        if char_id in self.characters:
            self.characters[char_id].status = status
            self.characters[char_id].notes += f"\n[{datetime.now().isoformat()}] {note}"
            self._touch()

    def get_active_characters(self) -> list[Character]:
        """获取所有存活且在故事中的角色"""
        return [c for c in self.characters.values() if c.status == "alive"]

    # ====== 地点操作 ======

    def add_location(self, **kwargs) -> Location:
        loc = Location(**kwargs)
        self.locations[loc.id] = loc
        self._touch()
        return loc

    # ====== 道具操作 ======

    def add_item(self, **kwargs) -> Item:
        item = Item(**kwargs)
        self.items[item.id] = item
        self._touch()
        return item

    # ====== 伏笔操作 ======

    def plant_foreshadowing(self, content: str, chapter: str, hint: str = "") -> Foreshadowing:
        fs = Foreshadowing(content=content, planted_in=chapter, hint=hint)
        self.foreshadowings[fs.id] = fs
        self._touch()
        return fs

    def resolve_foreshadowing(self, fs_id: str, chapter: str):
        if fs_id in self.foreshadowings:
            self.foreshadowings[fs_id].resolved = True
            self.foreshadowings[fs_id].resolved_in = chapter
            self._touch()

    def get_unresolved_foreshadowings(self) -> list[Foreshadowing]:
        return [fs for fs in self.foreshadowings.values() if not fs.resolved]

    def get_foreshadowings_planted_before(self, chapter: str) -> list[Foreshadowing]:
        """获取某章节之前埋设的所有伏笔"""
        # 简单实现：按章节号比较
        try:
            ch_num = int(chapter.replace("ch", "").replace("第", "").replace("章", ""))
            result = []
            for fs in self.foreshadowings.values():
                fs_ch = int(fs.planted_in.replace("ch", "").replace("第", "").replace("章", ""))
                if fs_ch < ch_num and not fs.resolved:
                    result.append(fs)
            return result
        except ValueError:
            return [fs for fs in self.foreshadowings.values() if not fs.resolved]

    # ====== 时间线操作 ======

    def add_timeline_event(self, chapter: str, event: str, 
                           story_day: int = None, characters: list = None):
        evt = TimelineEvent(
            chapter=chapter, event=event,
            story_day=story_day, characters_involved=characters or []
        )
        self.timeline.append(evt)
        self._touch()

    # ====== 章节摘要操作 ======

    def add_chapter_summary(self, summary: ChapterSummary):
        self.chapter_summaries[summary.chapter_num] = summary
        self._touch()

    def get_recent_summaries(self, count: int = 3) -> list[ChapterSummary]:
        """获取最近N章摘要"""
        nums = sorted(self.chapter_summaries.keys(), reverse=True)[:count]
        return [self.chapter_summaries[n] for n in sorted(nums)]

    def get_all_summaries_text(self) -> str:
        """获取全部摘要拼接文本（用于全局概览）"""
        lines = []
        for num in sorted(self.chapter_summaries.keys()):
            s = self.chapter_summaries[num]
            lines.append(f"【第{s.chapter_num}章 {s.title}】{s.summary}")
        return "\n".join(lines)

    # ====== 上下文组装（核心检索接口）=====

    def build_context_for_chapter(self, chapter_num: int, chapter_outline: str,
                                   character_names: list[str] = None) -> str:
        """
        为指定章节组装写作上下文
        
        这是整个系统最关键的接口 —— 写作 Agent 调用它来获取：
        1. 相关角色卡片
        2. 相关地点信息
        3. 未回收的伏笔
        4. 最近几章摘要
        5. 时间线近况
        """
        parts = []
        ch_key = f"ch{chapter_num}"

        parts.append("=== 故事设定 ===")
        parts.append(f"书名：{self.meta['title']}")
        parts.append(f"类型：{self.meta['genre']}")

        # 相关角色
        target_chars = character_names or []
        chars_to_show = []
        for name in target_chars:
            c = self.get_character(name)
            if c:
                chars_to_show.append(c)
        # 如果没指定角色，展示所有活跃角色
        if not chars_to_show:
            chars_to_show = self.get_active_characters()[:8]

        if chars_to_show:
            parts.append("\n=== 角色信息 ===")
            for c in chars_to_show:
                rels = ", ".join([f"{r['type']}({r.get('target','')})" for r in c.relationships])
                parts.append(
                    f"【{c.name}】{'/'.join(c.alias) if c.alias else ''}\n"
                    f"  年龄:{c.age or '?'} 性别:{c.gender}\n"
                    f"  外貌:{c.appearance}\n"
                    f"  性格:{', '.join(c.personality)}\n"
                    f"  能力:{json.dumps(c.abilities, ensure_ascii=False)}\n"
                    f"  状态:{c.status}\n"
                    f"  关系:{rels or '无'}\n"
                    f"  角色弧线:{c.arc}"
                )

        # 未回收伏笔
        unresolved = self.get_foreshadowings_planted_before(ch_key)
        if unresolved:
            parts.append("\n=== 待回收伏笔 ===")
            for fs in unresolved:
                parts.append(f"- [{fs.planted_in}] {fs.content} (提示:{fs.hint or '无'})")

        # 最近章节摘要
        recent = self.get_recent_summaries(3)
        if recent:
            parts.append("\n=== 前情提要 ===")
            for s in recent:
                parts.append(f"第{s.chapter_num}章 {s.title}: {s.summary}")

        # 时间线
        if self.timeline:
            parts.append("\n=== 近期时间线 ===")
            for evt in self.timeline[-10:]:
                chars = ", ".join(evt.characters_involved) if evt.characters_involved else ""
                parts.append(f"[{evt.chapter}] {evt.event}" + (f" (涉及:{chars})" if chars else ""))

        # 世界观备注
        if self.world_notes:
            parts.append(f"\n=== 世界观补充 ===\n{self.world_notes}")

        # 文风指南
        if self.style_guide:
            parts.append(f"\n=== 文风要求 ===\n{self.style_guide}")

        return "\n".join(parts)

    # ====== 序列化 ======

    def to_dict(self) -> dict:
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
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, filepath: str) -> "StoryBible":
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        sb = cls(title=data["meta"].get("title", ""),
                 genre=data["meta"].get("genre", ""),
                 premise=data["meta"].get("premise", ""))
        sb.meta = data["meta"]
        sb.world_notes = data.get("world_notes", "")
        sb.style_guide = data.get("style_guide", "")
        # 还原各实体
        for cid, cd in data.get("characters", {}).items():
            sb.characters[cid] = Character(**cd)
        for lid, ld in data.get("locations", {}).items():
            sb.locations[lid] = Location(**ld)
        for iid, id_ in data.get("items", {}).items():
            sb.items[iid] = Item(**id_)
        for fid, fd in data.get("foreshadowings", {}).items():
            sb.foreshadowings[fid] = Foreshadowing(**fd)
        for td in data.get("timeline", []):
            sb.timeline.append(TimelineEvent(**td))
        for num, sd in data.get("chapter_summaries", {}).items():
            sb.chapter_summaries[int(num)] = ChapterSummary(**sd)
        return sb

    def _touch(self):
        self.meta["updated_at"] = datetime.now().isoformat()

    def __repr__(self):
        active = len(self.get_active_characters())
        return (f"<StoryBible '{self.meta['title']}' | "
                f"{len(self.characters)}角色({active}活跃) | "
                f"{len(self.foreshadowings)}伏笔({len(self.get_unresolved_foreshadowings())}未收) | "
                f"{len(self.chapter_summaries)}章已写>")
