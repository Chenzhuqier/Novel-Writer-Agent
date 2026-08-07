"""
大纲架构 Agent —— 负责生成总纲 → 分卷大纲 → 章节细纲

输入：故事圣经（世界观设定）+ 用户确认的核心方向
输出：树状大纲结构（卷 → 章 → 场景/冲突/悬念）
"""

import json
from .base import BaseAgent


class OutlineAgent(BaseAgent):
    """大纲架构 Agent"""

    name = "OutlineArchitect"
    description = "根据世界观设定生成分层大纲结构"

    @property
    def system_prompt(self) -> str:
        return """你是一位资深的网文/小说架构师，擅长将世界观设定转化为可执行的写作蓝图。

你的任务是根据给定的世界观设定，生成详细的分层大纲。

## 输出要求

请严格以 JSON 格式输出：

```json
{
  "total_volumes": 1,
  "estimated_total_chapters": 30,
  "volumes": [
    {
      "volume_num": 1,
      "volume_title": "第一卷标题",
      "arc_summary": "本卷剧情弧线概述（50-100字）",
      "chapter_count": 10,
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
2. 章节之间要有因果递进关系
3. 每5-10章安排一个小高潮，每卷结尾有大高潮
4. 角色出场要合理分布，不要集中或遗漏
5. 注意伏笔的埋设节奏——前期多埋、中期推进、后期回收"""

    def run(self, world_setting: dict, chapter_count: int = 10, 
             volume_count: int = 1, **kwargs) -> dict:
        """
        执行大纲生成
        
        Args:
            world_setting: 世界构建 Agent 输出的设定字典
            chapter_count: 总章节数（默认10章用于Demo）
            volume_count: 分卷数
            
        Returns:
            结构化的大纲字典
        """
        # 构建用户消息
        world_text = json.dumps(world_setting, ensure_ascii=False, indent=2)
        
        user_msg = f"""请根据以下世界观设定，生成一个{chapter_count}章的小说大纲（分{volume_count}卷）：

## 世界观设定
{world_text}

## 要求
- 总共 {chapter_count} 章，分为 {volume_count} 卷
- 每章包含：标题、场景列表、核心冲突、悬念钩子、出场角色
- 确保情节连贯、节奏合理"""

        response = self._call_llm(user_msg, temperature=0.8, max_tokens=6000)

        try:
            clean = response.strip()
            if clean.startswith("```"):
                lines = clean.split("\n")
                clean = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
            result = json.loads(clean)
        except json.JSONDecodeError:
            result = {"raw_output": response, "parse_error": True}

        return result
