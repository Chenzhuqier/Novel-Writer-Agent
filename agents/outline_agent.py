"""
大纲架构 Agent —— 负责生成总纲 → 分卷大纲 → 章节细纲

改进点（v0.3）：
1. 两阶段生成：章数较多时先产出分卷骨架，再逐卷生成章节细纲，避免长 JSON 被截断
2. JSON 解析失败时携带错误信息自动重试
3. 输出结构校验 + 程序化自动修复（全局重编号、字段补全、统计对齐）
4. 修复 system_prompt 中示例数据自相矛盾的问题
5. kwargs 真正落地：genre / style / temperature
6. 与 prompt 负面约束对应的程序化质检（场景数上限、编号连续性、标题去重）
7. 卷间摘要传递，保证跨卷连贯性
8. 全流程日志记录
"""

import json

from .base import BaseAgent, register_demo, DEMO_CHAPTER_OUTLINE
from core.skill_knowledge import outline_rules

register_demo("OutlineArchitect", DEMO_CHAPTER_OUTLINE, estimated_tokens=2000)

# ---------- 可调常量 ----------
MAX_CHAPTERS_PER_CALL = 15   # 单次 LLM 调用生成的最大章节数，超过则启用两阶段生成
MAX_JSON_RETRIES = 1         # JSON 解析失败后的最大重试次数
MAX_SCENES_PER_CHAPTER = 4   # 与 prompt 中的负面约束保持一致
REQUIRED_CHAPTER_FIELDS = ("num", "title", "scenes", "conflict", "hook", "characters")


class OutlineGenerationError(Exception):
    """大纲生成最终失败（重试与修复均无效）"""


class OutlineAgent(BaseAgent):
    """大纲架构 Agent"""

    name = "OutlineArchitect"
    description = "根据世界观设定生成分层大纲结构"
    force_json_output = True

    # ================= Prompt =================

    @property
    def system_prompt(self) -> str:
        rules, _ = outline_rules()
        skill_block = ""
        if rules:
            skill_block = "\n\n# 网文大纲架构要点（skill 知识注入）\n" + rules
        return ("你是一位资深的网文/小说架构师，擅长将世界观设定转化为可执行的写作蓝图。"
                + skill_block + """

## 你的思考步骤（请按以下顺序思考，但只输出最终 JSON）

1. **分析世界观核心要素**：提取角色关系、核心冲突、主题方向
2. **规划整体结构**：根据章节数量合理分配卷数和每卷章节
3. **设计节奏曲线**：开头吸引 → 发展推进 → 高潮爆发 → 收尾留白
4. **细化每章内容**：为每章设计场景、冲突、钩子、出场角色
5. **检查伏笔节奏**：前期埋设、中期推进、后期回收

## 输出要求

严格以 JSON 格式输出。示意数据仅为说明字段结构，三个统计数字
（total_volumes / estimated_total_chapters / 各卷 chapter_count）必须
与你实际输出的卷、章内容完全一致：

```json
{
  "total_volumes": 1,
  "estimated_total_chapters": 3,
  "volumes": [
    {
      "volume_num": 1,
      "volume_title": "第一卷标题",
      "arc_summary": "本卷剧情弧线概述（50-100字）",
      "climax": "本卷高潮事件",
      "foreshadowing": ["本卷埋设或回收的伏笔"],
      "chapter_count": 3,
      "chapters": [
        {
          "num": 1,
          "title": "章节标题",
          "scenes": ["场景1", "场景2", "场景3"],
          "conflict": "本章核心冲突",
          "hook": "章末悬念钩子（让读者想看下一章）",
          "characters": ["出场角色列表"],
          "notes": "额外备注"
        }
      ]
    }
  ]
}
```

## 设计原则
1. 每章必须有明确的冲突和悬念钩子（网文核心：爽点+悬念）
2. 章节之间要有因果递进关系（前一事件的后果引发后一事件）
3. 每5-10章安排一个小高潮，每卷结尾有大高潮
4. 角色出场要合理分布，不要集中或遗漏
5. 注意伏笔的埋设节奏——前期多埋、中期推进、后期回收
6. 章节编号全局连续：第 2 卷的第 1 章接着上一卷最后一章编号，不要从 1 重新开始

## ⛔ 禁止事项
- ❌ 不要让连续3章以上使用相同的悬念模式（如都是"神秘人出现"）
- ❌ 不要在一章内塞入超过 4 个场景（会导致节奏太快）
- ❌ 不要让所有章节的冲突强度相同——要有张有弛
- ❌ 不要在 hook 中直接揭示答案（hook 是引发好奇，不是解答）
- ❌ 不要忽略次要角色的出场安排
- ❌ 卷与卷之间的过渡不要太突兀
- ❌ 不要在 JSON 中使用省略号、注释或占位符，每一章都必须完整输出
- ❌ 不要输出 JSON 以外的任何文字（包括"好的""以下是"等）

## ✅ 质量检查清单（输出前自查）
- [ ] 每章都有独特的标题（不是"第X章事件"这种泛泛的）？
- [ ] 冲突类型有变化（不是全是战斗或全是对话）？
- [ ] hook 的多样性足够（反转/悬念/情感/揭秘等）？
- [ ] 角色出场频率合理（主角每章都出现，配角轮流登场）？
- [ ] 整体节奏有起伏（不是一条直线）？
- [ ] total_volumes / estimated_total_chapters / 各卷 chapter_count / 实际章数是否一致？

请根据给定的世界观设定，按照上述格式输出完整的大纲 JSON。只输出 JSON，不要任何其他文字。""")

    # ================= 主入口 =================

    def run(
        self,
        world_setting: dict,
        chapter_count: int = 10,
        volume_count: int = 1,
        genre: str = None,
        style: str = None,
        temperature: float = None,
        **kwargs,
    ) -> dict:
        """执行大纲生成

        Args:
            world_setting: 世界观设定（非空 dict）
            chapter_count: 总章节数
            volume_count: 分卷数
            genre: 题材类型（如"都市修仙"），用于校准爽点预期
            style: 风格偏好（如"爽文""悬疑""轻松"）
            temperature: 采样温度，base 支持时生效
        """
        self._validate_input(["world_setting"], world_setting=world_setting)
        self._validate_params(chapter_count, volume_count)

        self._temperature = temperature
        world_text = json.dumps(world_setting, ensure_ascii=False, indent=2)
        extra_req = self._build_extra_requirements(genre, style)

        if chapter_count <= MAX_CHAPTERS_PER_CALL:
            result = self._generate_full(world_text, chapter_count, volume_count, extra_req)
        else:
            result = self._generate_in_phases(world_text, chapter_count, volume_count, extra_req)

        issues = self._validate_output(result, chapter_count, volume_count)
        if issues:
            result = self._repair(result, chapter_count, volume_count)

        return result

    # ================= 单阶段生成（短篇幅） =================

    def _generate_full(
        self, world_text: str, chapter_count: int, volume_count: int, extra_req: str
    ) -> dict:
        user_msg = f"""请根据以下世界观设定，生成一个 {chapter_count} 章的小说大纲（分 {volume_count} 卷）：

## 世界观设定
{world_text}

## 要求
- 总共 {chapter_count} 章，分为 {volume_count} 卷
- 每章包含：标题、场景列表（2-4个）、核心冲突、悬念钩子、出场角色、备注
- 章节编号全局连续（跨卷不重新从 1 开始）
- 确保情节连贯、节奏合理、有张有弛
{extra_req}- 直接输出 JSON，不要任何解释"""
        return self._call_llm_json(user_msg)

    # ================= 两阶段生成（长篇幅） =================

    def _generate_in_phases(
        self, world_text: str, chapter_count: int, volume_count: int, extra_req: str
    ) -> dict:
        """Phase 1 分卷骨架 → Phase 2 逐卷细纲 → 合并"""
        skeleton = self._generate_skeleton(world_text, chapter_count, volume_count, extra_req)
        volumes_skeleton = skeleton.get("volumes") or []
        if not volumes_skeleton:
            raise OutlineGenerationError("分卷骨架生成失败：volumes 为空")

        detailed_volumes = []
        chapter_offset = 0
        prev_digest = ""

        for i, vol in enumerate(volumes_skeleton):
            vol_detail = self._generate_volume_detail(
                world_text=world_text,
                volume_info=vol,
                start_chapter=chapter_offset + 1,
                prev_digest=prev_digest,
                is_first=(i == 0),
                is_last=(i == len(volumes_skeleton) - 1),
                extra_req=extra_req,
            )
            chapters = vol_detail.get("chapters") or []
            chapter_offset += len(chapters)
            prev_digest = self._digest_volume(vol_detail)
            detailed_volumes.append(vol_detail)

        skeleton["volumes"] = detailed_volumes
        return skeleton

    def _generate_skeleton(
        self, world_text: str, chapter_count: int, volume_count: int, extra_req: str
    ) -> dict:
        user_msg = f"""请根据以下世界观设定，设计一部 {chapter_count} 章小说的【分卷骨架】（共 {volume_count} 卷）。

## 世界观设定
{world_text}

## 要求
- 只设计卷级结构，不要展开每章细节
- 每卷包含：volume_num、volume_title、arc_summary（80-150字）、chapter_count、climax（本卷高潮事件）、foreshadowing（本卷埋设或回收的伏笔列表）
- 各卷 chapter_count 之和必须等于 {chapter_count}
- 卷与卷之间要有明确的因果承接
{extra_req}
## 输出格式（只输出 JSON）
{{
  "total_volumes": {volume_count},
  "estimated_total_chapters": {chapter_count},
  "volumes": [
    {{
      "volume_num": 1,
      "volume_title": "卷标题",
      "arc_summary": "本卷剧情弧线概述",
      "chapter_count": 0,
      "climax": "本卷高潮事件",
      "foreshadowing": ["伏笔1", "伏笔2"]
    }}
  ]
}}"""
        return self._call_llm_json(user_msg)

    def _generate_volume_detail(
        self,
        world_text: str,
        volume_info: dict,
        start_chapter: int,
        prev_digest: str,
        is_first: bool,
        is_last: bool,
        extra_req: str,
    ) -> dict:
        vol_json = json.dumps(volume_info, ensure_ascii=False, indent=2)
        n = volume_info.get("chapter_count", 0)

        continuity = f"\n## 前卷回顾（本卷开篇必须承接）\n{prev_digest}\n" if prev_digest else ""
        position_req = ""
        if is_first:
            position_req += "- 本卷为开篇卷：前 3 章必须快速建立主角共情点与核心悬念\n"
        if is_last:
            position_req += "- 本卷为收尾卷：回收主要伏笔，结尾可留白但不可烂尾\n"

        user_msg = f"""请为以下这一卷设计逐章细纲。

## 世界观设定
{world_text}

## 本卷骨架
{vol_json}
{continuity}
## 要求
- 本卷共 {n} 章，章节编号从第 {start_chapter} 章开始全局连续编号
- 每章包含：num、title、scenes（2-4个）、conflict、hook、characters、notes
- 章与章之间因果递进，hook 模式不要连续重复
{position_req}{extra_req}- 直接输出 JSON（顶层字段：volume_num、volume_title、arc_summary、chapter_count、chapters），不要任何解释"""
        result = self._call_llm_json(user_msg)
        # 兜底：模型/资源若返回了整部大纲（顶层 volumes），取第一卷作为本卷细纲
        if "chapters" not in result:
            vols = result.get("volumes") or []
            result = vols[0] if vols else result
        # 骨架中的 climax / foreshadowing 信息不能丢
        for key in ("climax", "foreshadowing"):
            if key in volume_info and key not in result:
                result[key] = volume_info[key]
        return result

    @staticmethod
    def _digest_volume(volume: dict) -> str:
        """生成前卷摘要，供下一卷保持连贯"""
        chapters = volume.get("chapters") or []
        last_hook = chapters[-1].get("hook", "") if chapters else ""
        tail_titles = "、".join(c.get("title", "") for c in chapters[-3:])
        return (
            f"第 {volume.get('volume_num')} 卷《{volume.get('volume_title')}》："
            f"{volume.get('arc_summary', '')}\n"
            f"最后三章：{tail_titles}\n"
            f"卷末钩子：{last_hook}"
        )

    # ================= LLM 调用与 JSON 容错 =================

    def _call_llm_json(self, user_msg: str) -> dict:
        """调用 LLM 并解析 JSON，解析失败时携带错误信息让模型自我修正"""
        prompt = user_msg
        last_error = ""

        for attempt in range(MAX_JSON_RETRIES + 1):
            response = self._call_llm_safe(prompt)

            # 注意：_parse_json_response 解析失败不抛异常，而是返回带 parse_error 的字典
            parsed = self._parse_json_response(response)
            if not isinstance(parsed, dict) or not parsed.get("parse_error"):
                return parsed

            last_error = parsed.get("error_msg") or "未知解析错误"
            prompt = (
                f"你上一次的输出不是合法 JSON，解析错误：{last_error}\n"
                "请修正后重新输出，只输出 JSON，不要任何其他文字。\n\n"
                f"===== 原始任务 =====\n{user_msg}"
            )

        raise OutlineGenerationError(
            f"连续 {MAX_JSON_RETRIES + 1} 次 JSON 解析失败: {last_error}"
        )

    def _call_llm_safe(self, user_msg: str) -> str:
        """透传 temperature，base 不支持该参数时静默降级"""
        temperature = getattr(self, "_temperature", None)
        if temperature is not None:
            try:
                return self._call_llm(user_msg, temperature=temperature)
            except TypeError:
                pass
        return self._call_llm(user_msg)

    # ================= 输出校验与自动修复 =================

    def _validate_output(
        self, result: dict, chapter_count: int, volume_count: int
    ) -> list:
        """结构校验，返回问题列表（空列表 = 通过）"""
        issues = []
        volumes = result.get("volumes")
        if not isinstance(volumes, list) or not volumes:
            issues.append("缺少 volumes 字段或为空")
            return issues

        if len(volumes) != volume_count:
            issues.append(f"卷数不符：期望 {volume_count}，实际 {len(volumes)}")

        total = sum(len(v.get("chapters") or []) for v in volumes)
        if total != chapter_count:
            issues.append(f"总章数不符：期望 {chapter_count}，实际 {total}")

        expected_num = 1
        seen_titles = set()
        for v in volumes:
            for ch in v.get("chapters") or []:
                missing = set(REQUIRED_CHAPTER_FIELDS) - ch.keys()
                if missing:
                    issues.append(f"第 {ch.get('num', '?')} 章缺少字段: {sorted(missing)}")
                if ch.get("num") != expected_num:
                    issues.append(f"章节编号不连续：期望 {expected_num}，实际 {ch.get('num')}")
                title = ch.get("title", "")
                if title in seen_titles:
                    issues.append(f"章节标题重复：{title}")
                seen_titles.add(title)
                if len(ch.get("scenes") or []) > MAX_SCENES_PER_CHAPTER:
                    issues.append(f"第 {ch.get('num')} 章场景数超过 {MAX_SCENES_PER_CHAPTER}")
                expected_num += 1
        return issues

    def _repair(self, result: dict, chapter_count: int, volume_count: int) -> dict:
        """程序化自动修复：
        1. 补全缺失字段（默认值兜底）
        2. 全局重排章节编号
        3. 场景数超限时截断
        4. 对齐 chapter_count / estimated_total_chapters 等统计字段

        注意：整卷缺失这类结构性问题无法修复，直接抛错交由上层决定是否重跑。
        修复后若章数仍与目标不符（LLM 实际产出偏少 / Demo 数据），只警告并对齐统计字段，
        不阻断流程——上层决定是否续写占位扩展。
        """
        volumes = result.get("volumes") or []
        if not volumes:
            raise OutlineGenerationError("输出缺少 volumes，无法自动修复")

        num = 1
        for i, vol in enumerate(volumes, start=1):
            vol.setdefault("volume_num", i)
            vol.setdefault("volume_title", f"第{i}卷")
            vol.setdefault("arc_summary", "")
            chapters = vol.get("chapters") or []
            for ch in chapters:
                ch["num"] = num
                num += 1
                ch.setdefault("title", f"第{ch['num']}章")
                ch.setdefault("scenes", [])
                ch.setdefault("conflict", "")
                ch.setdefault("hook", "")
                ch.setdefault("characters", [])
                ch.setdefault("notes", "")
                if len(ch["scenes"]) > MAX_SCENES_PER_CHAPTER:
                    ch["scenes"] = ch["scenes"][:MAX_SCENES_PER_CHAPTER]
            vol["chapters"] = chapters
            vol["chapter_count"] = len(chapters)

        result["volumes"] = volumes
        result["total_volumes"] = len(volumes)
        result["estimated_total_chapters"] = sum(v["chapter_count"] for v in volumes)

        if result["estimated_total_chapters"] != chapter_count:
            print(
                f"[{self.name}] 章数仍不符（期望 {chapter_count}，"
                f"实际 {result['estimated_total_chapters']}），已按实际值对齐统计字段"
            )
        return result

    # ================= 辅助 =================

    @staticmethod
    def _validate_params(chapter_count: int, volume_count: int) -> None:
        if chapter_count < 1:
            raise ValueError("chapter_count 必须 >= 1")
        if volume_count < 1:
            raise ValueError("volume_count 必须 >= 1")
        if chapter_count < volume_count:
            raise ValueError(f"章节数({chapter_count})不能少于卷数({volume_count})")

    @staticmethod
    def _build_extra_requirements(genre: str, style: str) -> str:
        lines = []
        if genre:
            lines.append(f"- 题材类型：{genre}（情节设计需符合该题材的爽点与套路预期）\n")
        if style:
            lines.append(f"- 风格偏好：{style}\n")
        return "".join(lines)