"""
世界构建 Agent —— 负责从用户创意生成完整的世界观设定

输入：用户的创意/题材/核心概念
输出：结构化的世界观（人物、地点、势力、力量体系、核心冲突等）
结果会写入 Story Bible
"""

import json
from .base import BaseAgent


class WorldBuilderAgent(BaseAgent):
    """世界构建 Agent"""

    name = "WorldBuilder"
    description = "根据用户创意生成完整的小说世界观设定"

    @property
    def system_prompt(self) -> str:
        return """你是一位资深的奇幻/网文世界观设计师，擅长从简单的创意出发，构建出完整、自洽、有深度的虚构世界。

你的任务是根据用户提供的信息，生成一套完整的世界观设定。

## 输出要求

请严格以 JSON 格式输出，包含以下字段：

```json
{
  "world_name": "世界名称",
  "genre": "类型标签（如：玄幻/修仙/都市/科幻/悬疑）",
  "power_system": "力量体系描述（如有）",
  "geography": [
    {"name": "地名", "type": "类型", "description": "描述"}
  ],
  "factions": [
    {"name": "势力名", "leader": "首领", "goal": "目标"}
  ],
  "characters": [
    {
      "name": "角色名",
      "alias": ["别名"],
      "age": 年龄,
      "gender": "性别",
      "appearance": "外貌描述（50字以内）",
      "personality": ["性格标签1", "性格标签2"],
      "abilities": {"能力名": "等级/描述"},
      "arc": "角色弧线简述"
    }
  ],
  "core_conflict": "核心冲突描述（100-200字）",
  "themes": ["主题1", "主题2"],
  "style_notes": "写作风格建议"
}
```

## 设计原则
1. 角色至少3个主要人物（主角+重要配角+反派）
2. 每个角色要有明确的性格、目标和成长弧线
3. 核心冲突要有层次感（个人层面 + 世界层面）
4. 力量体系要自洽且有升级空间
5. 地点和势力要服务于剧情需要"""

    def run(self, premise: str, genre: str = "", **kwargs) -> dict:
        """
        执行世界构建
        
        Args:
            premise: 用户的核心创意描述
            genre: 可选的类型指定
            
        Returns:
            结构化的世界观字典
        """
        user_msg = f"请根据以下创意构建一个完整的小说世界观：\n\n创意：{premise}"
        if genre:
            user_msg += f"\n类型偏好：{genre}"

        response = self._call_llm(user_msg, temperature=0.9, max_tokens=4096)

        # 尝试解析 JSON
        try:
            # 清理可能包裹在 markdown 代码块中的 JSON
            clean = response.strip()
            if clean.startswith("```"):
                lines = clean.split("\n")
                clean = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
            result = json.loads(clean)
        except json.JSONDecodeError:
            # 如果解析失败，返回原始文本包装
            result = {"raw_output": response, "parse_error": True}

        return result
