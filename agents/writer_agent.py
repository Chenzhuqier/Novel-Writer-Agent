"""
正文写作 Agent —— 根据细纲 + 故事圣经上下文生成章节正文

输入：章节细纲 + 故事圣经检索到的上下文
输出：章节正文文本
"""

import json
from .base import BaseAgent


class WriterAgent(BaseAgent):
    """正文写作 Agent"""

    name = "Writer"
    description = "根据大纲和故事设定撰写小说正文"

    @property
    def system_prompt(self) -> str:
        return """你是一位才华横溢的小说家，擅长根据详细的大纲和设定写出引人入胜的章节正文。

## 你的写作原则

1. **严格遵循大纲**：按照给定的场景列表、冲突和悬念钩子来写，不要偏离
2. **保持角色一致**：严格按照角色卡片中的性格、能力、说话方式来写每个角色
3. **展示而非讲述**：用动作、对话、环境描写来展现故事，不要大量叙述性说明
4. **节奏把控**：
   - 开头要有吸引力（前3句决定读者是否继续）
   - 中间有冲突推进
   - 结尾必须有悬念钩子（这是网文的核心）
5. **文笔要求**：
   - 句式长短结合，有节奏感
   - 适当使用感官描写（视觉、听觉、触觉）
   - 对话要符合角色性格，每个人说话方式不同
6. **字数**：每章 2000-4000 字

## 输出格式

直接输出正文内容，以"第X章 标题"开头。
不需要任何解释或元数据注释。"""

    def run(self, chapter_outline: dict, context: str = "", 
             style_sample: str = "", **kwargs) -> str:
        """
        执行章节写作
        
        Args:
            chapter_outline: 当前章的细纲信息（标题、场景、冲突、钩子等）
            context: 从故事圣经检索到的上下文（角色、伏笔、前情提要等）
            style_sample: 文风范例（可选）
            
        Returns:
            章节正文文本
        """
        # 构建用户消息
        outline_text = json.dumps(chapter_outline, ensure_ascii=False, indent=2)
        
        user_msg = f"请根据以下大纲和设定，撰写完整的小说章节。\n\n"
        
        if style_sample:
            user_msg += f"## 文风参考\n{style_sample}\n\n"
        
        if context:
            user_msg += f"## 故事设定与上下文\n{context}\n\n"
        
        user_msg += f"## 本章大纲\n{outline_text}\n\n"
        user_msg += "请直接输出正文，以'第X章 标题'开头。"

        response = self._call_llm(user_msg, temperature=0.85, max_tokens=6000)
        return response.strip()
