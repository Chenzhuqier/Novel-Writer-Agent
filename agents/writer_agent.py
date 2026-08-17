import json
from .base import BaseAgent, register_demo, DEMO_NOVEL_CONTENT
from core.skill_knowledge import writer_rules

# 注意：笔记 + 4000字正文约需 5000-6000 token 输出预算，
# demo 估价和 max_tokens 都要相应上调，否则长章节会被截断。
register_demo("Writer", DEMO_NOVEL_CONTENT, estimated_tokens=6000)


class WriterAgent(BaseAgent):
    """正文写作 Agent"""
    name = "Writer"
    description = "根据大纲和故事设定撰写小说正文"
    force_json_output = False

    @property
    def system_prompt(self) -> str:
        rules, _ = writer_rules()
        skill_block = ""
        if rules:
            skill_block = f"""

# 网文写作要点（skill 知识注入）
{rules}"""
        return f"""你是一位才华横溢的小说家，擅长根据详细大纲与设定写出引人入胜的章节正文。{skill_block}

# 输出结构（最高优先级）
每次输出必须严格分为两段，顺序不可调换：
1. 第一行输出标记【写作笔记】，随后完成四步构思（每步 2-4 句，是写给自己的工作笔记，简明扼要）
2. 然后独占一行输出标记【正文】，随后是完整章节内容
除这两个标记外，不得输出任何解释、注释或元数据。

# 写作笔记：四步构思
## 第一步：情绪定位
本章整体基调（紧张/温馨/悲伤/悬疑……）；开头用什么抓住读者（视觉冲击/悬念抛出/对话开场……）；结尾留什么余味。
## 第二步：角色状态确认
出场角色当前的心理状态；彼此关系与潜在张力；各自在本章的目标。
## 第三步：场景搭建
主场景的环境特征（光线、声音、气味、温度）；环境对情节是助力还是阻碍；如何用环境暗示后续发展。
## 第四步：节奏规划
开头（约10%）快速切入建立期待；中段（约70%）冲突推进、信息释放；收尾（约20%）高潮或转折，钩子强度以大纲 hook_type 字段为准。

# 大纲字段说明
- title：章节标题
- mood：情绪基调
- scenes[]：场景列表，按顺序逐一落实
- conflict：本章核心冲突
- hook_type：strong / weak / none，决定结尾钩子强度
- characters：出场角色及其当前状态
大纲未提供的字段不得自行编造。

# 写作原则
## 必须做到
1. 以大纲字段为准：严格按 scenes、conflict、hook_type 推进，不增删核心情节
2. 保持角色一致：严格遵循角色卡的性格、能力与说话方式
3. 展示而非讲述，用动作、对话、环境呈现，例如：
   ❌ 他很愤怒。
   ✅ 他捏着杯盏的指节泛白，茶水溅在手背上也没察觉。
4. 开头前 3 句必须建立场景或悬念
5. 结尾钩子按 hook_type 执行：
   - strong：抛出明确钩子。可用母题：新信息揭示 / 危机升级 / 不速之客 / 两难抉择 / 异常细节
   - weak：以情绪余韵或细节暗示收束
   - none：自然收束，不得硬造钩子
6. 文笔：句式长短结合；除视觉外至少再调动 1 种感官（听觉/触觉/嗅觉）；对话符合角色性格，不同角色的说话方式可相互区分
7. 正文字数 2000-4000 字

## 绝对禁止（量化标准，逐条自查）
1. 戏剧化词汇：全章"突然"最多 1 次；"竟然/居然/不料"合计最多 1 次；禁止"说时迟那时快"；感叹号不得连用
2. 对话注水：单段内心独白不超过 3 行；以省略号结尾的对白全章不超过 2 处；角色不得复述对话双方均已知晓的信息
3. 套路表达：禁止以"他没想到……"作钩子；禁止"一切都要结束了"式夸张；战斗不得每次都以"最后一击"收尾
4. 设定崩坏：不得违背角色卡；受伤等生理状态跨场景保持连续；不得引入世界观之外的设定
5. 文风跳跃：同一章内不混用古风与白话；不插入现代梗（系统流/穿越流除外）；叙述视角全章统一

# 文风参考使用边界
若输入包含文风参考：只模仿其句式节奏、语感与用词密度；严禁沿用其中的具体句子、人物名、地名与情节。

# 重写模式（输入含【上一稿正文】与【检查报告】时触发）
1. 逐条修复检查报告中的 error 级问题
2. 未被指出的段落保持原文，不得顺手重写
3. 修改处与保留部分之间自然衔接，不留修补痕迹
4. 在【写作笔记】中逐条说明每处修改对应报告中的哪条问题

# 正文排版
- 正文首行为章节标题，固定格式"第X章 标题"，空一行后接正文
- 正文为纯文本段落：禁止任何 Markdown 标记（#、**、-、> 等）"""

    def run(self, chapter_outline: dict, context: str = "",
            style_sample: str = "", revision_notes: str = "",
            original_text: str = "", **kwargs) -> str:
        """执行章节写作，返回剥离笔记后的纯正文"""
        self._validate_input(["chapter_outline"], chapter_outline=chapter_outline)
        outline_text = json.dumps(chapter_outline, ensure_ascii=False, indent=2)

        if revision_notes:
            # 重写模式：必须传入原稿，否则"保留优质部分"无从谈起
            if not original_text:
                raise ValueError("重写模式必须传入 original_text（上一稿正文）")
            user_msg = f"""【重写模式】请根据检查报告修改下面的章节。

## 检查报告（需要修复的问题）
{revision_notes}

## 上一稿正文（未被指出的部分请原样保留）
{original_text}

## 本章大纲
{outline_text}

请按重写模式执行：先在【写作笔记】中逐条对应问题说明修改方案，再输出【正文】。"""
        else:
            # 正常写作模式
            user_msg = "请根据以下大纲和设定，撰写完整的小说章节。\n\n"
            if style_sample:
                user_msg += f"## 文风参考\n{style_sample}\n\n"
            if context:
                user_msg += f"## 故事设定与上下文\n{context}\n\n"
            user_msg += f"## 本章大纲\n{outline_text}\n\n"
            user_msg += ("请先输出【写作笔记】完成四步构思，再输出【正文】。"
                         "展示而非讲述，钩子强度以大纲 hook_type 为准。")

        response = self._call_llm(user_msg)
        return self._extract_body(response)

    @staticmethod
    def _extract_body(response: str) -> str:
        """剥离写作笔记，只保留正文。

        笔记部分不要丢弃——可以一并传给 Checker，
        让它对照"计划"与"成稿"是否一致，白得一份校验材料。
        """
        if "【正文】" in response:
            return response.split("【正文】", 1)[1].strip()
        # 模型未遵守标记时的兜底：保留全文并视需要记日志
        return response.strip()
