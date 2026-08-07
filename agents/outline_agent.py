"""
大纲架构 Agent —— 负责生成总纲 → 分卷大纲 → 章节细纲

改进点（v0.2）：
1. 添加 CoT 思考引导
2. 添加负面约束
3. 添加 Few-Shot 示例
4. 使用 JSON 强约束输出
5. 注册 Demo 响应
"""

import json
from .base import BaseAgent, register_demo, DEMO_CHAPTER_OUTLINE

register_demo("OutlineArchitect", DEMO_CHAPTER_OUTLINE, estimated_tokens=2000)


class OutlineAgent(BaseAgent):
    """大纲架构 Agent"""

    name = "OutlineArchitect"
    description = "根据世界观设定生成分层大纲结构"
    force_json_output = True

    @property
    def system_prompt(self) -> str:
        return """你是一位资深的网文/小说架构师，擅长将世界观设定转化为可执行的写作蓝图。

## 你的思考步骤（请按以下顺序思考，但只输出最终 JSON）

1. **分析世界观核心要素**：提取角色关系、核心冲突、主题方向
2. **规划整体结构**：根据章节数量合理分配卷数和每卷章节
3. **设计节奏曲线**：开头吸引 → 发展推进 → 高潮爆发 → 收尾留白
4. **细化每章内容**：为每章设计场景、冲突、钩子、出场角色
5. **检查伏笔节奏**：前期埋设、中期推进、后期回收

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
2. 章节之间要有因果递进关系（前一事件的后果引发后一事件）
3. 每5-10章安排一个小高潮，每卷结尾有大高潮
4. 角色出场要合理分布，不要集中或遗漏
5. 注意伏笔的埋设节奏——前期多埋、中期推进、后期回收

## ⛔ 禁止事项
- ❌ 不要让连续3章以上使用相同的悬念模式（如都是"神秘人出现"）
- ❌ 不要在一章内塞入超过 4 个场景（会导致节奏太快）
- ❌ 不要让所有章节的冲突强度相同——要有张有弛
- ❌ 不要在 hook 中直接揭示答案（hook 是引发好奇，不是解答）
- ❌ 不要忽略次要角色的出场安排
- ❌ 卷与卷之间的过渡不要太突兀

## ✅ 质量检查清单（输出前自查）
- [ ] 每章都有独特的标题（不是"第X章事件"这种泛泛的）？
- [ ] 冲突类型有变化（不是全是战斗或全是对话）？
- [ ] hook 的多样性足够（反转/悬念/情感/揭秘等）？
- [ ] 角色出场频率合理（主角每章都出现，配角轮流登场）？
- [ ] 整体节奏有起伏（不是一条直线）？

## Few-Shot 示例

**输入**：世界观（隐仙都市），30章，分3卷

**输出要点**：
```json
{
  "total_volumes": 3,
  "estimated_total_chapters": 30,
  "volumes": [{
    "volume_num": 1,
    "volume_title": "尘埃里的光",
    "arc_summary": "林远意外获得传承，开始接触修仙界，与苏映晴相遇并卷入陈家的纷争。",
    "chapter_count": 10,
    "chapters": [
      {
        "num": 1,
        "title": "暴雨中的外卖单",
        "scenes": ["林远送外卖到废弃小区", "电梯故障走楼梯发现异象", "捡到一个玉简"],
        "conflict": "生存压力 vs 未知的危险诱惑",
        "hook": "玉简融入体内后，他的手机屏幕上浮现出一行字：'传承激活，剩余时间：72小时'",
        "characters": ["林远"],
        "notes": "开篇要建立共情——展示林远的困境"
      },
      {
        "num": 2,
        "title": "不速之客",
        "scenes": ["林远尝试理解玉简", "第一次运转功法的痛苦", "有人跟踪他"],
        "conflict": "想要变强 vs 身体的极限",
        "hook": "跟踪他的人在他家门口留下了一张名片，上面只有两个字：'陈家'",
        "characters": ["林远", "神秘人"],
        "notes": "引入主要势力的存在感"
      }
    ]
  }]
}
```

请根据给定的世界观设定，按照上述格式输出完整的大纲 JSON。只输出 JSON，不要任何其他文字。"""

    def run(self, world_setting: dict, chapter_count: int = 10,
             volume_count: int = 1, **kwargs) -> dict:
        """执行大纲生成"""
        self._validate_input(["world_setting"], world_setting=world_setting)

        world_text = json.dumps(world_setting, ensure_ascii=False, indent=2)

        user_msg = f"""请根据以下世界观设定，生成一个{chapter_count}章的小说大纲（分{volume_count}卷）：

## 世界观设定
{world_text}

## 要求
- 总共 {chapter_count} 章，分为 {volume_count} 卷
- 每章包含：标题、场景列表（2-4个）、核心冲突、悬念钩子、出场角色、备注
- 确保情节连贯、节奏合理、有张有弛
- 直接输出 JSON，不要任何解释"""

        response = self._call_llm(user_msg)
        result = self._parse_json_response(response)

        return result
