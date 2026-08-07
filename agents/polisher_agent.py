"""
语言润色 Agent —— 负责优化文笔、统一文风

输入：章节正文 + 文风指南
输出：润色后的正文文本
"""

from .base import BaseAgent


class PolisherAgent(BaseAgent):
    """语言润色 Agent"""

    name = "Polisher"
    description = "优化小说正文的文笔和风格"

    @property
    def system_prompt(self) -> str:
        return """你是一位资深文学编辑，擅长润色小说正文，提升文笔质量的同时保持原意不变。

## 润色原则

1. **保持原意**：不改变情节、对话、角色行为，只优化表达方式
2. **提升文笔**：
   - 句式更丰富（长短句交替，避免连续短句或长难句）
   - 词汇更精准（替换平淡词汇为更有表现力的表达）
   - 增强画面感（补充恰当的感官描写）
   - 优化节奏感（调整段落长短，控制阅读呼吸）
3. **统一文风**：保持全文风格一致，不出现文风跳跃
4. **不注水**：不为了字数增加无意义的内容

## 输出格式

直接输出润色后的完整正文。
在正文开头用【润色说明】简要列出主要修改点（3-5条）。"""

    def run(self, text: str, style_guide: str = "", **kwargs) -> str:
        """
        执行润色
        
        Args:
            text: 待润色的章节正文
            style_guide: 文风指南
            
        Returns:
            润色后的正文
        """
        user_msg = "请润色以下小说章节：\n\n"
        
        if style_guide:
            user_msg += f"## 文风要求\n{style_guide}\n\n"
        
        user_msg += f"## 原文\n{text}"

        response = self._call_llm(user_msg, temperature=0.6, max_tokens=6000)
        return response.strip()
