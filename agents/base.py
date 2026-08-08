"""
Agent 基类 —— 所有写作 Agent 的统一接口

改进点（v0.2）：
1. Token 追踪与成本统计
2. 多模型路由策略
3. JSON 强约束输出（response_format）
4. 带重试的 LLM 调用
5. Demo 模式类名注册制
6. 流式输出支持
"""

import os
import time
import json
from abc import ABC, abstractmethod
from typing import Optional, Generator, Any
from datetime import datetime


# ============================================================
# Token 追踪器
# ============================================================

class TokenTracker:
    """Token 使用追踪器 —— 记录每次 LLM 调用的 token 消耗和成本"""

    # 模型定价表（每 1K tokens，单位：USD）—— 2026 年参考价格
    PRICING = {
        "gpt-4o": {"input": 0.0025, "output": 0.01},
        "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
        "gpt-4-turbo": {"input": 0.01, "output": 0.03},
        "deepseek-chat": {"input": 0.00014, "output": 0.00028},
        "deepseek-reasoner": {"input": 0.00055, "output": 0.00219},
        "qwen-plus": {"input": 0.0004, "output": 0.002},
        "qwen-max": {"input": 0.0012, "output": 0.006},
        "claude-3.5-sonnet": {"input": 0.003, "output": 0.015},
        "default": {"input": 0.001, "output": 0.004},
    }

    def __init__(self):
        self.usage_log: list[dict] = []
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        self._total_cost = 0.0

    def track(self, agent_name: str, response: Any, model: str) -> dict:
        """记录一次 LLM 调用"""
        usage = getattr(response, 'usage', None)
        if not usage or not hasattr(usage, 'prompt_tokens'):
            entry = {
                "timestamp": datetime.now().isoformat(),
                "agent": agent_name,
                "model": model,
                "input_tokens": -1,
                "output_tokens": -1,
                "cost": 0,
                "note": "usage unavailable"
            }
            self.usage_log.append(entry)
            return entry

        input_tokens = usage.prompt_tokens
        output_tokens = usage.completion_tokens

        pricing = self.PRICING.get(model, self.PRICING["default"])
        cost = (input_tokens / 1000 * pricing["input"] +
                output_tokens / 1000 * pricing["output"])

        entry = {
            "timestamp": datetime.now().isoformat(),
            "agent": agent_name,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "cost_usd": round(cost, 6),
        }

        self.usage_log.append(entry)
        self._total_input_tokens += input_tokens
        self._total_output_tokens += output_tokens
        self._total_cost += cost

        return entry

    @property
    def total_calls(self) -> int:
        return len(self.usage_log)

    @property
    def total_input_tokens(self) -> int:
        return self._total_input_tokens

    @property
    def total_output_tokens(self) -> int:
        return self._total_output_tokens

    @property
    def total_cost_usd(self) -> float:
        return round(self._total_cost, 4)

    def get_summary(self) -> dict:
        """获取完整的使用统计"""
        by_agent: dict[str, dict] = {}
        for entry in self.usage_log:
            agent = entry["agent"]
            if agent not in by_agent:
                by_agent[agent] = {
                    "calls": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cost": 0,
                }
            by_agent[agent]["calls"] += 1
            by_agent[agent]["input_tokens"] += max(entry["input_tokens"], 0)
            by_agent[agent]["output_tokens"] += max(entry["output_tokens"], 0)
            by_agent[agent]["cost"] += entry.get("cost_usd", 0)

        return {
            "summary": {
                "total_calls": self.total_calls,
                "total_input_tokens": self.total_input_tokens,
                "total_output_tokens": self.total_output_tokens,
                "total_cost_usd": self.total_cost_usd,
                "estimated_cny": round(self.total_cost_usd * 7.2, 2),
            },
            "by_agent": by_agent,
            "recent_calls": self.usage_log[-10:] if self.usage_log else [],
        }

    def reset(self):
        """重置所有统计数据"""
        self.usage_log.clear()
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        self._total_cost = 0.0


# 全局 Token 追踪器实例
tracker = TokenTracker()


# ============================================================
# 多模型路由配置
# ============================================================

MODEL_ROUTING = {
    # 世界构建：需要高创造力，用强模型
    "WorldBuilder": {
        "primary": os.environ.get("LLM_MODEL", "gpt-4o"),
        "fallback": os.environ.get("LLM_FALLBACK_MODEL", "gpt-4o"),
        "temperature": 0.9,
        "max_tokens": 4096,
        "reasoning": False,
    },
    # 大纲规划：需要结构化思维，中等温度
    "OutlineArchitect": {
        "primary": os.environ.get("LLM_MODEL", "gpt-4o"),
        "fallback": os.environ.get("LLM_FALLBACK_MODEL", "gpt-4o-mini"),
        "temperature": 0.8,
        "max_tokens": 8192,
        "reasoning": False,
    },
    # 正文写作：需要文采，高温度
    "Writer": {
        "primary": os.environ.get("LLM_MODEL", "gpt-4o-mini"),
        "fallback": os.environ.get("LLM_FALLBACK_MODEL", "gpt-4o-mini"),
        "temperature": 0.85,
        "max_tokens": 8192,
        "reasoning": False,
    },
    # 检查员：需要严谨，低温度，可用弱模型
    "PlotChecker": {
        "primary": os.environ.get("LLM_MODEL", "gpt-4o-mini"),
        "fallback": os.environ.get("LLM_FALLBACK_MODEL", "gpt-4o-mini"),
        "temperature": 0.3,
        "max_tokens": 4096,
        "reasoning": False,
    },
    # 润色师：中等温度
    "Polisher": {
        "primary": os.environ.get("LLM_MODEL", "gpt-4o-mini"),
        "fallback": os.environ.get("LLM_FALLBACK_MODEL", "gpt-4o-mini"),
        "temperature": 0.6,
        "max_tokens": 8192,
        "reasoning": False,
    },
    # 摘要提取：需要严谨与精炼，低温度、短输出
    "ChapterSummarizer": {
        "primary": os.environ.get("LLM_MODEL", "gpt-4o-mini"),
        "fallback": os.environ.get("LLM_FALLBACK_MODEL", "gpt-4o-mini"),
        "temperature": 0.3,
        "max_tokens": 1024,
        "reasoning": False,
    },
}


def get_model_config(agent_name: str) -> dict:
    """
    获取指定 Agent 的模型配置

    v0.2 修复：优先使用 .env 环境变量中的模型配置，
    MODEL_ROUTING 只作为 temperature/max_tokens 等参数的参考。
    这样用户在 .env 中设置的 LLM_MODEL 会真正生效。
    """
    # 从环境变量读取用户配置的模型（最高优先级）
    env_primary = os.environ.get("LLM_MODEL", "").strip()
    env_fallback = os.environ.get("LLM_FALLBACK_MODEL", "").strip()

    # 获取路由表中的基础配置（temperature、max_tokens 等）
    routing_config = MODEL_ROUTING.get(agent_name, {})
    default_config = {
        "primary": env_primary or "gpt-4o-mini",
        "fallback": env_fallback or env_primary or "gpt-4o-mini",
        "temperature": routing_config.get("temperature", 0.7),
        "max_tokens": routing_config.get("max_tokens", 4096),
        "reasoning": routing_config.get("reasoning", False),
    }

    result = MODEL_ROUTING.get(agent_name, default_config)

    # 关键修复：如果用户在 .env 中配置了 LLM_MODEL，强制覆盖路由表中的模型名
    if env_primary:
        result["primary"] = env_primary
    if env_fallback:
        result["fallback"] = env_fallback
    elif env_primary:
        result["fallback"] = env_primary

    return result


# ============================================================
# LLM 调用封装
# ============================================================

def call_llm(
    system_prompt: str,
    user_message: str,
    model: str = None,
    temperature: float = 0.8,
    max_tokens: int = 4096,
    force_json: bool = False,
    agent_name: str = "Unknown",
) -> str:
    """
    统一的 LLM 调用接口

    改进点：
    - 支持 OpenAI Structured Outputs（force_json）
    - 自动 fallback 到备用模型
    - 带指数退避的重试机制
    - 自动记录 Token 使用量
    """
    api_key = os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    model = model or os.environ.get("LLM_MODEL", "gpt-4o-mini")

    if not api_key:
        return _demo_fallback(system_prompt, user_message, agent_name)

    max_retries = 2
    config = get_model_config(agent_name)
    models_to_try = [model or config["primary"], config["fallback"]]

    for attempt in range(max_retries + 1):
        try:
            import openai

            current_model = models_to_try[min(attempt, len(models_to_try) - 1)]
            client = openai.OpenAI(api_key=api_key, base_url=base_url)

            kwargs = {
                "model": current_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                "temperature": temperature,
                "max_tokens": max_tokens,
            }

            if force_json:
                kwargs["response_format"] = {"type": "json_object"}

            response = client.chat.completions.create(**kwargs)
            tracker.track(agent_name, response, current_model)

            content = response.choices[0].message.content or ""
            return content

        except Exception as e:
            print(f"[LLM 调用失败] 尝试 {attempt + 1}/{max_retries + 1}: {e}")
            if attempt < max_retries:
                wait_time = 2 ** attempt
                print(f"  → 等待 {wait_time}s 后重试...")
                time.sleep(wait_time)
            else:
                print(f"  → 所有尝试均失败，回退到 Demo 模式")
                return _demo_fallback(system_prompt, user_message, agent_name)


def stream_llm(
    system_prompt: str,
    user_message: str,
    model: str = None,
    temperature: float = 0.8,
    max_tokens: int = 4096,
    agent_name: str = "Unknown",
) -> Generator[str, None, None]:
    """流式 LLM 调用接口 —— Yields 文本片段"""
    api_key = os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    model = model or os.environ.get("LLM_MODEL", "gpt-4o-mini")

    if not api_key:
        yield _demo_fallback(system_prompt, user_message, agent_name)
        return

    try:
        import openai

        client = openai.OpenAI(api_key=api_key, base_url=base_url)
        stream = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )

        full_content = ""
        for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                full_content += delta
                yield delta

        class FakeResponse:
            class FakeUsage:
                prompt_tokens = 0
                completion_tokens = len(full_content) // 3
                total_tokens = 0
            usage = FakeUsage()

        tracker.track(agent_name, FakeResponse(), model)

    except Exception as e:
        print(f"[流式 LLM 调用失败] {e}")
        yield _demo_fallback(system_prompt, user_message, agent_name)


# ============================================================
# Demo 配置与回退
# ============================================================

class DemoConfig:
    """Demo 模式配置"""
    def __init__(self, agent_class_name: str, demo_response: str, estimated_tokens: int = 1500):
        self.agent_class_name = agent_class_name
        self.demo_response = demo_response
        self.estimated_tokens = estimated_tokens


DEMO_REGISTRY: dict[str, DemoConfig] = {}


def register_demo(agent_class_name: str, demo_response: str, estimated_tokens: int = 1500):
    """注册 Demo 响应"""
    DEMO_REGISTRY[agent_class_name] = DemoConfig(agent_class_name, demo_response, estimated_tokens)


def _demo_fallback(system_prompt: str, user_message: str, agent_name: str = "Unknown") -> str:
    """Demo 回退模式 —— 优先按类名查找"""
    if agent_name in DEMO_REGISTRY:
        return DEMO_REGISTRY[agent_name].demo_response

    # 向后兼容的关键词匹配
    sp_lower = system_prompt.lower()
    if "世界构建" in system_prompt or "world" in sp_lower:
        return DEMO_WORLD_BUILDING
    elif "大纲" in system_prompt and "章节" in system_prompt:
        return DEMO_CHAPTER_OUTLINE
    elif "正文" in system_prompt or "写作" in system_prompt or "writer" in sp_lower:
        return DEMO_NOVEL_CONTENT
    elif "检查" in system_prompt or "逻辑" in system_prompt or "checker" in sp_lower:
        return DEMO_CHECK_RESULT
    elif "润色" in system_prompt or "polish" in sp_lower:
        return DEMO_POLISHED_CONTENT
    elif "摘要" in system_prompt or "summary" in sp_lower:
        return DEMO_SUMMARY
    else:
        return "[Demo模式] 这是一个模拟的 Agent 响应。请配置 OPENAI_API_KEY 以获得真实 AI 输出。"


# ============================================================
# Demo 数据
# ============================================================

DEMO_WORLD_BUILDING = """{
  "world_name": "苍澜大陆",
  "genre": "玄幻/修仙",
  "power_system": "灵力修炼体系：炼气 → 筑基 → 金丹 → 元婴 → 化神 → 合道 → 渡劫",
  "geography": [
    {"name": "天剑宗", "type": "宗门", "description": "苍澜大陆第一剑修宗门，位于断云山脉之巅"},
    {"name": "幽冥海", "type": "禁地", "description": "大陆南端的死亡海域，传说封印着上古魔物"},
    {"name": "落星城", "type": "城池", "description": "大陆最大的贸易中心，三教九流汇聚之地"}
  ],
  "factions": [
    {"name": "天剑宗", "leader": "剑圣·顾长风", "goal": "维护正道秩序，对抗魔道势力"},
    {"name": "血月教", "leader": "教主·厉千行", "goal": "解开封印，释放幽冥海中的魔神"}
  ],
  "characters": [
    {
      "name": "沈炼", "alias": ["寒江剑客"], "age": 24, "gender": "男",
      "appearance": "身形清瘦，左眉有一道细长疤痕，常穿青灰色布衣，腰间佩一柄古朴长剑「寒江」",
      "personality": ["隐忍", "重诺", "外冷内热"],
      "abilities": {"剑术": "宗师级", "内功": "少阳诀第三重", "特殊能力": "能感知他人杀意"},
      "arc": "从复仇驱动的孤行者 → 学会信任与放下 → 守护所爱之人"
    },
    {
      "name": "苏清歌", "alias": ["药王谷小师妹"], "age": 19, "gender": "女",
      "appearance": "肤白如雪，眉心有一点朱砂痣，气质清冷如月下梨花",
      "personality": ["聪慧", "倔强", "心地善良"],
      "abilities": {"医术": "精通", "毒术": "略通", "轻功": "上乘"},
      "arc": "从被保护的温室花朵 → 独当一面 → 成为沈炼的精神支柱"
    },
    {
      "name": "厉千行", "alias": ["血月教主"], "age": 200, "gender": "男",
      "appearance": "面容俊美妖异，一双眸子呈暗红色，周身常年萦绕淡淡血雾",
      "personality": ["偏执", "深情", "不择手段"],
      "abilities": {"魔功": "血月天经大成", "特殊能力": "可操控死者尸傀"},
      "arc": "为复活亡妻而堕入魔道 → 与主角对立 → 最终选择自我牺牲"
    }
  ],
  "core_conflict": "沈炼追寻灭门仇人，却发现仇人之死与血月教的阴谋有关；而血月教主厉千行的真实目的并非毁灭世界，而是要打破一道封印——这道封印恰恰是沈炼家族世代守护之物。",
  "themes": ["复仇与宽恕", "守护与牺牲", "命运与抉择"],
  "style_notes": "文笔偏向古风但不晦涩，节奏明快，每章结尾留悬念钩子"
}"""

DEMO_CHAPTER_OUTLINE = """{
  "volumes": [{
    "volume_num": 1, "volume_title": "孤剑出山", "chapter_count": 10,
    "arc_summary": "沈炼离开隐居十年的山门，踏入江湖寻找灭门真相。初遇苏清歌，卷入天剑宗与血月教的冲突。",
    "chapters": [
      {"num": 1, "title": "寒江剑鸣", "scenes": ["沈炼在山中练剑", "收到神秘信件暗示灭门线索", "决定下山"], "conflict": "内心挣扎：十年隐居 vs 复仇使命", "hook": "信件末尾署名竟是他已故父亲的名字", "characters": ["沈炼"], "notes": ""},
      {"num": 2, "title": "落星城遇雨", "scenes": ["抵达落星城", "偶遇苏清歌被人追杀", "出手相救"], "conflict": "沈炼不想惹麻烦但无法袖手旁观", "hook": "追杀苏清歌的人认出了沈炼的剑法", "characters": ["沈炼", "苏清歌"], "notes": ""},
      {"num": 3, "title": "药王谷来客", "scenes": ["苏清歌身份揭晓", "得知她身上有重要秘密", "血月教暗杀者出现"], "conflict": "是否应该卷入更大的漩涡", "hook": "暗杀者临死前说出一句话：'你也姓沈……'", "characters": ["沈炼", "苏清歌"], "notes": ""}
    ]
  }]
}"""

DEMO_NOVEL_CONTENT = '''第一章 寒江剑鸣

断云山脉深处，晨雾未散。

一道剑光破开白茫茫的山岚，如游龙般在嶙峋怪石间穿梭。持剑的是个青年男子，青灰色布衣已被汗水浸透，贴在瘦削却结实的脊背上。他每一剑刺出都带着一种近乎执拗的精准——十万次重复锤炼出的肌肉记忆，容不得半分偏差。

沈炼收剑而立，胸膛剧烈起伏。

十年了。

他从十二岁那年被师父带上这座山，至今已是整整十年。三千六百五十个日夜，除了吃饭睡觉，便是练剑、打坐、再练剑。师父说，他的资质不算顶尖，但他比任何人都更能忍受枯燥。

"耐得住寂寞，方能成大器。"师父总是这样说。

可师父三年前坐化了，如今这断云山顶只剩他一人，和一座孤坟。

沈炼低头看向手中的剑。剑身狭长，泛着淡淡的青灰色光泽，不像寻常兵刃那样寒光逼人，倒像是一截凝固的江水。这是父亲留下的唯一遗物——寒江剑。

"寒江独钓，雪满山中。"父亲生前最爱这句诗，便给剑取了这个名字。

沈炼从未见过父亲。他在那场灭门惨案中丧生时，沈炼还在襁褓之中。关于父亲的一切，都来自师父零星的讲述和一个被反复摩挲至发白的木牌。

风从山谷深处吹来，带着秋叶的气息。

就在这时，沈炼的眉头微微皱起。

一种奇异的感觉自后颈蔓延至全身——不是危险，而是一种……被注视的感觉。这种感觉他并不陌生，过去十年中出现过三次，每一次都意味着有外人闯入了这片禁区。

他缓缓转身。

山道上空无一人。只有晨雾在松林间流淌，几只不知名的鸟儿惊惶地掠过树梢。

然而那种感觉并未消失。相反，它越来越清晰，像是一根无形的线，从某个方向牵引着他的注意力。

沈炼的目光落在山道旁的一块青石上。

那里多了一样东西。

一封信。

信封是普通的白色，没有任何署名，只用一滴暗红色的蜡封住了口。沈炼走过去，单手拾起。蜡封上没有印记，但他凑近一闻——

一股极淡的血腥气。

他的手指微微收紧。撕开信封，里面只有一张薄纸，上面用墨写着寥寥数语：

**"令尊沈啸天死于阴谋，非意外。若想知道真相，十月十五，落星城醉仙楼。"**

落款处只有一个字——

**"沈"。**

沈炼的手指僵住了。

这个字迹……他认识。在师父遗物中，有一封同样字迹的信，那是父亲写给师父的绝笔，日期正是沈家灭门当晚。

父亲的绝笔，怎么会出现在十年之后的一封信里？

除非写信的人，拥有那封绝笔。

一阵山风吹过，将信纸的一角吹得微微翘起。沈炼站在原地，久久不动。晨光照在他左眉那道疤痕上，让那道疤痕看起来像是一道干涸已久的河床。

良久，他将信折好，收入怀中。

然后转身走向身后的小屋。

该下山了。'''

DEMO_CHECK_RESULT = """{
  "passed": true,
  "issues": [],
  "warnings": [
    {"type": "consistency_check", "severity": "info", "detail": "第一章中沈炼的年龄设定为24岁，与故事圣经一致", "suggestion": "建议在世界构建阶段明确沈炼上山时的确切年龄"},
    {"type": "foreshadowing", "severity": "info", "detail": "本章埋设了3条伏笔：①信件署名之谜 ②寒江剑的特殊性 ③沈炼被注视的感觉", "suggestion": "伏笔记录已自动更新到故事圣经"}
  ],
  "character_status_ok": true,
  "timeline_consistent": true,
  "foreshadowing_notes": ["本章新埋设的伏笔：信件署名之谜、寒江剑秘密、感知能力觉醒"],
  "overall_quality_score": 8.5,
  "scores_by_dimension": {"角色一致性": 9.0, "设定合规性": 8.5, "情节逻辑": 8.5, "节奏把控": 8.0, "文笔质量": 8.5},
  "summary": "第一章整体质量良好，角色塑造生动，悬念设置到位。建议后续章节注意年龄设定的细节一致性。"
}"""

DEMO_POLISHED_CONTENT = '''第一章 寒江剑鸣

【润色说明】优化了部分句式节奏，增强了画面感和氛围渲染，统一了文风基调。

---

断云山脉深处，晨雾未散。

一道剑光破开漫山白岚，如游龙般穿梭于嶙峋怪石之间。持剑的青年一身青灰布衣，已被汗水浸透，紧贴在瘦削却线条分明的脊背上。每一剑刺出都带着近乎执拗的精准——十万次重复锤炼出的肌肉记忆，容不得半分偏差。

沈炼收剑而立，胸膛剧烈起伏，白雾从唇齿间滚滚涌出。

十年了。

他从十二岁那年被师父带上此山，至今整整十年。三千六百五十个日夜，除却吃饭睡觉，便是练剑、打坐、再练剑。师父常说，他的资质不算顶尖，却比任何人都能忍受枯燥。

"耐得住寂寞，方成大器。"——这话听了十年，刻进了骨头里。

可师父三年前坐化了。如今这断云山顶，只剩他一人，一剑，一冢孤坟。

沈炼垂眸，看向手中长剑。

剑身狭长，泛着淡青色的微光，不似寻常兵刃那般寒芒逼人，倒像是一截凝冻的江水。这是父亲留下的唯一遗物——寒江剑。

"寒江独钓，雪满山中。"父亲生前最爱这句诗，便以此命名。

沈炼从未见过父亲。他在那场灭门惨案中丧生时，沈炼尚在襁褓。关于父亲的一切，皆来自师父零碎的讲述，以及一块被反复摩挲至发白的木牌。

风自深谷吹来，裹挟着秋叶的气息。

就在这时，沈炼眉头微蹙。

一股异样的感觉自后颈蔓延至全身——非是危险，而是……被注视之感。这种感受他并不陌生，十年来出现过三次，每一次都意味着有外人踏入了这片禁地。

他缓缓转身。

山道上空无一人。唯见晨雾在松林间流淌，几只不知名的鸟儿惊惶掠过树梢。

然而那感觉未曾消退，反而愈发清晰，似有无形的线从某处牵动他的注意。

沈炼的目光，落在山道旁一块青石上。

那里多了一样东西。

一封信。

信封素白，无任何署名，只以一滴暗红蜡封口。沈炼走近拾起，蜡封上并无印记，但他凑近一闻——

一丝极淡的血腥气息。

指尖微紧。撕开信封，内里仅一张薄纸，墨书寥寥数语：

**"令尊沈啸天死于阴谋，非意外。若欲知真相，十月十五，落星城醉仙楼。"**

落款只有一个字——

**"沈"。**

沈炼的手指僵住了。

这笔迹……他认得。师父遗物之中，有一封同般字迹的信函——那是父亲写给师父的绝笔，日期正是沈家灭门之夜。

父亲的绝笔，怎会出现在十年后的信中？

除非写信之人，持有那封绝笔本身。

山风拂过，将信纸一角轻轻掀起。沈炼伫立良久，一动不动。晨光落在他左眉的疤痕上，使那道陈年旧痕宛如一道干涸的河床。

半晌，他将信折好，纳入怀中。

转身，回屋，收拾行装。

该下山了。'''

DEMO_SUMMARY = """{
  "chapter_num": 1,
  "title": "寒江剑鸣",
  "summary": "沈炼在断云山脉隐居十年后练剑时察觉异常，在山道青石上发现一封署名为'沈'的神秘信件，声称其父沈啸天之死另有隐情，约其十月十五于落星城醉仙楼相见。信件笔迹与其父绝笔相同，沈炼决定下山追寻真相。",
  "characters_present": ["沈炼"],
  "key_events": ["沈炼练剑展示实力", "发现神秘信件", "得知父亲死因疑点", "决定下山"],
  "character_state_changes": {"沈炼": "从隐居状态转为主动追寻真相的行动状态"},
  "new_foreshadowing": ["信件署名之谜——谁持有父亲绝笔？", "寒江剑是否有隐藏秘密？", "沈炼感知到被注视——特殊能力伏笔"],
  "resolved_foreshadowing": []
}"""


# ============================================================
# 抽象基类
# ============================================================

class BaseAgent(ABC):
    """
    所有 Agent 的抽象基类

    改进点（v0.2）：
    - 强制抽象方法约束
    - 内置输入校验
    - 自动多模型路由
    - 带 JSON 强约束的 LLM 调用
    - 重试机制封装
    """

    name: str = "BaseAgent"
    description: str = ""
    force_json_output: bool = True

    def __init__(self, model: str = None, temperature: float = None):
        config = get_model_config(self.name)
        self.model = model or config["primary"]
        self.temperature = temperature if temperature is not None else config["temperature"]
        self.max_tokens = config["max_tokens"]

    @property
    @abstractmethod
    def system_prompt(self) -> str:
        """每个 Agent 必须定义自己的 System Prompt"""
        ...

    @abstractmethod
    def run(self, **kwargs):
        """执行 Agent 逻辑，返回结构化结果"""
        ...

    def _validate_input(self, required_keys: list[str], **kwargs):
        """通用的输入校验"""
        missing = [k for k in required_keys if k not in kwargs or not kwargs[k]]
        if missing:
            raise ValueError(f"[{self.name}] 缺少必要参数: {', '.join(missing)}")

    def _call_llm(self, user_message: str, temperature: float = None,
                  max_tokens: int = None, force_json: bool = None) -> str:
        """带完整功能的 LLM 调用"""
        return call_llm(
            system_prompt=self.system_prompt,
            user_message=user_message,
            model=self.model,
            temperature=temperature or self.temperature,
            max_tokens=max_tokens or self.max_tokens,
            force_json=force_json if force_json is not None else self.force_json_output,
            agent_name=self.name,
        )

    def _call_llm_stream(self, user_message: str, temperature: float = None,
                         max_tokens: int = None):
        """流式 LLM 调用"""
        return stream_llm(
            system_prompt=self.system_prompt,
            user_message=user_message,
            model=self.model,
            temperature=temperature or self.temperature,
            max_tokens=max_tokens or self.max_tokens,
            agent_name=self.name,
        )

    def _parse_json_response(self, response: str) -> dict | str:
        """安全解析 JSON 响应"""
        try:
            clean = response.strip()
            if clean.startswith("```"):
                lines = clean.split("\n")
                start_idx = 0
                end_idx = len(lines)
                for i, line in enumerate(lines):
                    if line.startswith("```") and start_idx == 0:
                        start_idx = i + 1
                        continue
                    if line.startswith("```") and i > start_idx:
                        end_idx = i
                        break
                clean = "\n".join(lines[start_idx:end_idx])
            result = json.loads(clean)
            return result
        except json.JSONDecodeError as e:
            print(f"[{self.name}] JSON 解析失败: {e}")
            print(f"  原始响应前200字符: {response[:200]}...")
            return {"raw_output": response, "parse_error": True, "error_msg": str(e)}

    def __repr__(self):
        return f"<{self.name} | model={self.model} | temp={self.temperature}>"
