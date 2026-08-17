"""
短篇网文写作 Agent —— 引入 story-short-write 的短篇方法论

v1.0 要点：
1. 先定情绪，再定故事：构思阶段先锁定目标情绪（意难平/反转震撼/爽感释放/治愈温暖/细思极恐/共鸣感动）
2. 一个反转撑一篇：核心反转 + 至少 3 条铺垫线索，不多线、不铺世界观
3. 注入 skill 知识：short-craft（通用底座）+ short-format（格式）+ genre-styles/{题材}（题材风格包）
4. 输出分两步：run_framework 产出短篇框架（JSON），run_write 按框架成文（prose）
5. 全篇成文使用【写作笔记】/【正文】双标记，与 WriterAgent 一致
"""

import json
from .base import BaseAgent, register_demo, call_llm
from core.skill_knowledge import short_story_rules, genre_style_rules

# 构思框架 demo（JSON 字符串，与 run_framework 的解析路径一致）
DEMO_SHORT_FRAMEWORK = json.dumps({
    "title": "寒江剑鸣",
    "logline": "我爹的剑三年前被仇人夺走，今天却在一个病秧子手里见了血。",
    "emotion_goal": "反转震撼",
    "genre": "悬疑",
    "target_words": 8000,
    "platform": "知乎",
    "core_reversal": {
        "type": "身份反转",
        "content": "夺剑仇人早已死在仇家手里，持剑的病秧子其实是我爹的关门弟子，设局引我来认。",
        "foreshadowing": [
            "开篇：病秧子认得出剑的来历，却装作不懂",
            "中段：他咳嗽时指节上有剑茧",
            "结尾：他叫出我爹的剑诀，剑身嗡鸣认主",
        ],
    },
    "emotional_curve": {
        "opening": "压抑（7/10）",
        "middle": "升温（6/10）",
        "reversal": "爆发（9/10）",
        "ending": "余韵（8/10）",
    },
    "characters": [
        {"name": "我", "role": "主角", "one_line": "寻剑复仇的剑客之女，倔强偏执"},
        {"name": "病秧子", "role": "关键配角", "one_line": "藏剑的关门弟子，以病弱掩饰剑意"},
    ],
    "sections": [
        {"id": 1, "stage": "开头", "content": "发现仇人遗物里的剑出现在病秧子手中", "hook": "他认剑不认人"},
        {"id": 2, "stage": "铺垫", "content": "跟踪试探，反复印证他藏剑的理由", "hook": "剑茧与咳嗽"},
        {"id": 3, "stage": "升级", "content": "我拔剑逼问，他退到崖边", "hook": "他叫出剑诀"},
        {"id": 4, "stage": "反转", "content": "剑身认主，真相揭晓：他是爹的弟子", "hook": "仇人早已死"},
        {"id": 5, "stage": "结尾", "content": "我把剑还给他，转身下山", "hook": "他在身后叫出我小时候的名字"},
    ],
    "style_notes": "第一人称，短句收尾，情绪从压抑走向余韵，不以大段抒情收束",
}, ensure_ascii=False, indent=2)

# 成文 demo（prose，与 run_write 的正文路径一致）
DEMO_SHORT_STORY = """第一章 寒江剑鸣

我爹的剑，三年前被人夺走了。

那日他倒在祠堂门口，手里攥着的剑穗被人硬生生扯断，断口齐整，是高手所为。全族上下没人敢追，我娘把我关在柴房整整七日。七日后我出来，祠堂的匾额换了新字，谁都不再提那把剑。

可我记住了。剑叫寒江，是我爹十二岁那年铸的，剑身狭长，泛着青灰光泽，像一截凝冻的江水。我爹说，剑在人在。

今日我却在落霞镇的一个病秧子手里，见到了它。

他坐在茶棚里咳，咳得腰都直不起来，手里却攥着那柄寒江剑当拐杖拄。剑鞘上的缠绳被磨得发亮，是他自己的手指一遍遍摩挲出来的。我认得那柄剑，剑柄末梢刻着一个小小的"沈"字，是我爹的字。

我走过去，坐在他对面。

"这剑，"我说，"是借的？"

他抬头看我一眼，眼神平静得不像个病人："祖传的。"

祖传的。我爹死了三年，他的剑就成了这人的祖传。

我没有发作。我娘教过我，姑娘家在外面要学会忍。我坐在他对面喝茶，一盏茶喝了半个时辰，看他咳嗽时右手习惯性地蜷起指节——那是一个常年握剑的人，指节上有薄薄的剑茧。

一个病秧子，怎么会有剑茧？

我跟着他出了落霞镇。他走路很慢，走一段歇一段，可我总觉得他每一步都踩在某个我没看见的节拍上。他拐进一条窄巷，巷子尽头是座荒宅。他推门进去，门在身后合拢。

我在墙根下蹲了半宿。天快亮时，听见里面传来一声极轻的剑鸣，像是什么东西认出了谁。

第二天我提着剑堵在荒宅门口。

"把寒江还我。"我说。

他靠在门框上，又咳了两声："我若说不还呢？"

我拔剑。他却不退，只站在那里，看着我出剑的方向，忽然轻轻念了一句——

"寒江独钓，雪满山中。"

我的剑尖顿住了。这句话，是我爹教我剑诀时的起手式，全天下只有沈家人会念。我爹死了，我娘不识字，这世上不该再有第二个人念出这句话。

"你……"

"我是你爹的关门弟子。"他说，"三年前那晚，我赶到祠堂时，你爹已经不行了。他把剑交给我，让我藏起来，等你长大，等你来认。"

"仇人呢？"

"死了。"他说，"比你爹死得还早半个月。杀你爹的是个江湖散人，为了这把剑上的剑谱。他得了剑谱，却练不成，呕血而亡。剑转了三手，最后落到我手里。"

我握着剑，指节泛白："你藏了三年，为什么现在才让我看见？"

"因为今天是你十八岁生辰。"他说，"你爹说，满十八，剑归主。"

剑身在我手里轻轻震了一下，发出一声低鸣，像认出了久别的亲人。我低头看着那柄剑，三年了，剑还是那把剑，可我已经不是那个被关在柴房里哭的小丫头了。

我把剑插回他手里。

"剑你留着。"我说，"你是我爹的弟子，剑谱你该学。我只要那句话——我爹临终前，说了什么。"

他看着我的眼睛，忽然笑了："他说，让他闺女别惦记报仇，好好活着。"

我转身下山。走出巷口时，听见他在身后喊——

"沈清越！你爹说，若你执意要走这条路，就让你把这句话带走：剑在，人在。人不在，剑也要在。"

我没有回头。我把这句话在舌尖上嚼了又嚼，终于咽下去，像咽下一口热茶。

寒江在，我爹就不算白死。

"""

register_demo("ShortStory", DEMO_SHORT_FRAMEWORK, estimated_tokens=1500)
register_demo("ShortStoryWriter", DEMO_SHORT_STORY, estimated_tokens=3000)


class ShortStoryAgent(BaseAgent):
    """短篇网文写作 Agent"""

    name = "ShortStory"
    description = "从情绪目标到完整短篇正文，一个 Agent 完成构思与成文"
    force_json_output = True

    def __init__(self, model=None, temperature=None):
        # 短篇成文需要较高创造性
        super().__init__(model=model, temperature=0.85 if temperature is None else temperature)
        self._genre = ""

    def _call_llm(self, user_message: str, temperature: float = None,
                  max_tokens: int = None, force_json: bool = None,
                  agent_name: str = None) -> str:
        """与 BaseAgent 一致，但允许覆盖 agent_name（成文走 ShortStoryWriter demo）。"""
        return call_llm(
            system_prompt=self.system_prompt,
            user_message=user_message,
            model=self.model,
            temperature=temperature or self.temperature,
            max_tokens=max_tokens or self.max_tokens,
            force_json=force_json if force_json is not None else self.force_json_output,
            agent_name=agent_name or self.name,
        )

    @property
    def system_prompt(self) -> str:
        rules, source = short_story_rules(self._genre)
        skill_block = f"""
# 短篇写作知识（skill 知识注入，来源：{source}）
{rules}""" if rules else ""
        return f"""你是一位资深短篇网文作者，擅长在 8000-20000 字内完成一篇情绪完整、反转有力的短篇小说。{skill_block}

# 执行规则（最高优先级）
1. **先定情绪，再定故事**：所有内容为目标情绪服务。
2. **一个反转撑一篇**：所有铺垫为反转服务，不多线、不铺世界观。
3. **每句话必须有用**：不推动剧情、不铺垫反转、不推高情绪的句子→删。
4. **开头 3 句定生死**：开头必须包含钩子（冲突前置/信息差/反常行为/悬念句），前 100 字事件密度 ≥3。
5. **结尾定传播**：用安静细节收尾（一个物件、一个动作、一句短话），不写大段抒情。
6. **默认第一人称**，代入感最强；除非题材明确需要第三人称。

# 五段结构（按比例控制篇幅）
- 开头（前 300-500 字）：3 句内抓住读者，不做背景铺垫。
- 铺垫（30-40%）：埋入至少 3 条反转线索，分散在不同小节；贯穿道具第 1 次出现。
- 升级（20-30%）：冲突升级，插入倒计时/代价钩子；埋入误导信息。
- 反转（10-15%）：一节内完成揭示；铺垫线索可回溯；情绪冲击强度必须 > 前面所有节最高值。
- 结尾（5-10%）：安静细节收尾；贯穿道具第 3 次出现（回扣暴击）。

# 输出结构（最高优先级）
每次输出必须严格分为两段，顺序不可调换：
1. 第一行输出标记【写作笔记】，随后完成构思（情绪定位/反转确认/铺垫清单/节奏规划，简明扼要）
2. 然后独占一行输出标记【正文】，随后是完整短篇正文
除这两个标记外，不得输出任何解释、注释或元数据。"""

    def run(self, premise: str = "", emotion: str = "", genre: str = "",
            framework: dict = None, **kwargs) -> object:
        """统一入口：有 framework 则成文，否则先构思再成文。

        Returns:
            - framework 已给出 → 返回正文 str
            - 仅给出 premise → 返回 {"framework": ..., "draft": ...}
        """
        if framework:
            return self.run_write(framework, **kwargs)
        if premise:
            fw = self.run_framework(
                premise=premise, emotion=emotion, genre=genre, **kwargs
            )
            if isinstance(fw, dict) and fw.get("parse_error"):
                return fw
            draft = self.run_write(fw, **kwargs)
            return {"framework": fw, "draft": draft}
        raise ValueError("ShortStory.run 需要 framework 或 premise")

    def run_write(self, framework: dict, **kwargs) -> str:
        """按框架成文，返回剥离笔记后的纯正文"""
        self._validate_input(["framework"], framework=framework)
        self._genre = framework.get("genre", "")
        framework_text = json.dumps(framework, ensure_ascii=False, indent=2)
        user_msg = (
            "请根据以下短篇框架，撰写完整的短篇小说正文。\n\n"
            f"## 短篇框架\n{framework_text}\n\n"
            "请先输出【写作笔记】完成构思，再输出【正文】。正文需严格遵循框架的"
            "情绪曲线与五段结构，段落之间只用一个换行符，不得出现空行，"
            "对话引号风格全文统一。"
        )
        response = self._call_llm(user_msg, agent_name="ShortStoryWriter")
        return self._extract_body(response)

    def run_framework(self, premise: str, emotion: str = "", genre: str = "",
                      target_words: int = 8000, platform: str = "", **kwargs) -> dict:
        """构思短篇框架，返回 JSON 结构体"""
        self._validate_input(["premise"], premise=premise)
        self._genre = genre

        rules, source = genre_style_rules(genre)
        style_block = f"""
## 题材风格包（skill 知识注入，来源：{source}）
{rules}""" if rules else ""

        user_msg = f"""请为下面的短篇创意构思核心框架。

## 用户创意
{premise}

## 设计参数
- 目标情绪：{emotion or '（未指定，请推荐）'}
- 题材方向：{genre or '（未指定，请推荐）'}
- 目标字数：{target_words} 字
- 目标平台：{platform or '（未指定）'}{style_block}

请严格以 JSON 输出，包含以下字段：
{{
  "title": "标题（暂定）",
  "logline": "一句话梗概：主角+困境+反转+情绪落点",
  "emotion_goal": "目标情绪",
  "genre": "题材",
  "target_words": 目标字数,
  "platform": "目标平台",
  "core_reversal": {{
    "type": "反转类型（身份反转/视角反转/动机反转/时间线反转）",
    "content": "反转内容（一句话）",
    "foreshadowing": ["至少3个铺垫点，每个一句话，按出现顺序"]
  }},
  "emotional_curve": {{
    "opening": "开头情绪（强度1-10）",
    "middle": "中段情绪（强度1-10）",
    "reversal": "反转情绪（强度1-10，峰值）",
    "ending": "结尾情绪（强度1-10）"
  }},
  "characters": [
    {{"name": "角色名", "role": "主角/关键角色", "one_line": "一句话人设"}}
  ],
  "sections": [
    {{"id": 1, "stage": "开头", "content": "该段核心内容", "hook": "该段钩子"}}
  ],
  "style_notes": "写作风格建议"
}}
只输出 JSON，不要任何其他文字。"""
        response = self._call_llm(user_msg)
        result = self._parse_json_response(response)
        return result

    @staticmethod
    def _extract_body(response: str) -> str:
        """剥离写作笔记，只保留正文"""
        if "【正文】" in response:
            return response.split("【正文】", 1)[1].strip()
        return response.strip()