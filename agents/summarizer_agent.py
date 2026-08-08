"""
章节摘要提取 Agent —— 负责从正文提取结构化摘要，供故事圣经与跨章状态追踪使用

改进点（v0.4）：
1. 从 app.py 内嵌逻辑抽离为正式 Agent，统一走 BaseAgent 的 JSON 解析与 Demo 注册制
2. 输出 schema 与 core/story_bible.ChapterSummary 字段严格对齐
3. chapter_num 由代码强制覆盖，避免模型输出错号、也让 Demo 模式在各章都能正确落账
"""

from .base import BaseAgent, register_demo, DEMO_SUMMARY

register_demo("ChapterSummarizer", DEMO_SUMMARY, estimated_tokens=800)


class ChapterSummarizerAgent(BaseAgent):
    """章节摘要提取 Agent"""

    name = "ChapterSummarizer"
    description = "从章节正文提取结构化摘要"
    force_json_output = True

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

    def run(self, chapter_text: str, chapter_num: int, **kwargs) -> dict:
        """提取章节摘要，返回可构造 ChapterSummary 的 dict"""
        self._validate_input(
            ["chapter_text", "chapter_num"],
            chapter_text=chapter_text, chapter_num=chapter_num,
        )

        user_msg = (
            f"请基于以下第{chapter_num}章正文提取结构化摘要。\n\n"
            f"## 第{chapter_num}章正文\n{chapter_text[:3000]}\n\n"
            "请直接输出 JSON，不要任何解释。"
        )

        response = self._call_llm(user_msg, temperature=0.3, max_tokens=1024)
        result = self._parse_json_response(response)

        # 章号由代码层强制覆盖，规避模型或 Demo 响应输出错号
        if isinstance(result, dict) and not result.get("parse_error"):
            result["chapter_num"] = chapter_num

        return result