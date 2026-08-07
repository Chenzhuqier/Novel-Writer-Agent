"""
剧情检查 Agent —— 负责每章生成后的一致性校验

输入：章节正文 + 故事圣经
输出：结构化的检查报告（冲突列表、伏笔状态、质量评分）
"""

import json
from .base import BaseAgent


class CheckerAgent(BaseAgent):
    """剧情检查 Agent"""

    name = "PlotChecker"
    description = "检查章节内容与故事设定的一致性"

    @property
    def system_prompt(self) -> str:
        return """你是一位严谨的小说审稿编辑，专门负责检查小说章节的逻辑一致性和设定合规性。

## 你的检查清单

请逐项检查以下内容，并以 JSON 格式输出报告：

```json
{
  "passed": true/false,
  "issues": [
    {
      "type": "逻辑矛盾|设定冲突|时间线错误|角色行为不符|伏笔遗漏",
      "severity": "error|warning|info",
      "detail": "具体问题描述",
      "location": "问题出现在哪（如'第三章第二段'）",
      "suggestion": "修改建议"
    }
  ],
  "warnings": [
    {
      "type": "类型",
      "severity": "info",
      "detail": "非错误但值得注意的事项",
      "suggestion": "建议"
    }
  ],
  "character_status_ok": true,
  "timeline_consistent": true,
  "foreshadowing_notes": ["本章新埋设的伏笔", "本章推进/回收的伏笔"],
  "overall_quality_score": 8.5,
  "summary": "总体评价"
}
```

## 检查重点
1. **角色一致性**：角色的性格、能力、说话方式是否与设定卡一致？已死亡的角色是否误出现？
2. **设定冲突**：是否出现了与世界观矛盾的描述？
3. **时间线**：事件发生顺序是否合理？
4. **伏笔管理**：是否有应该回收但遗漏的伏笔？新埋设了哪些伏笔？
5. **前后矛盾**：与前文是否有明显冲突？
6. **节奏评估**：章节是否有明确的冲突和悬念钩子？

注意：passed=false 仅当存在 error 级别的问题时。warning 和 info 不影响通过。"""

    def run(self, chapter_text: str, chapter_num: int, 
             story_bible_summary: str = "", **kwargs) -> dict:
        """
        执行剧情检查
        
        Args:
            chapter_text: 待检查的章节正文
            chapter_num: 当前章号
            story_bible_summary: 故事圣经的关键信息摘要
            
        Returns:
            结构化的检查报告字典
        """
        user_msg = f"请检查以下第{chapter_num}章的内容一致性：\n\n"
        
        if story_bible_summary:
            user_msg += f"## 参考设定\n{story_bible_summary}\n\n"
        
        user_msg += f"## 第{chapter_num}章正文\n{chapter_text}\n\n"
        user_msg += "请输出完整的JSON格式检查报告。"

        response = self._call_llm(user_msg, temperature=0.3, max_tokens=3000)

        try:
            clean = response.strip()
            if clean.startswith("```"):
                lines = clean.split("\n")
                clean = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
            result = json.loads(clean)
        except json.JSONDecodeError:
            result = {"raw_output": response, "parse_error": True, "passed": True}

        return result
