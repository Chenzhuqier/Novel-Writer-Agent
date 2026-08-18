# 📖 小说写作 Agent (Novel Writer Agent)

> **基于多 Agent 协作的网络小说智能创作系统**

一个完整可运行的 AI 小说写作系统原型，模拟专业作家的创作流程：**创意 → 世界观构建 → 大纲生成 → 正文写作 → 一致性检查 → 文笔润色**，并内置**短篇小说**独立流水线（框架 → 成文 → 去AI味润色 → 多视角审查 → node 预检）。

> **v0.4 长篇连贯性强化**：新增「世界状态账本 + 连续性契约 + 全史语义召回 + 周期性全量连贯性审计」，专门对抗长篇小说前文遗忘与前后不一致。

## ✨ 核心特性

- **🌍 多 Agent 流水线** — 9 个专职 Agent 分工协作（世界构建 / 大纲 / 写作 / 检查 / 润色 / 摘要 / 多视角审查 / 短篇 / 全量连贯性审计）
- **📚 故事圣经（Story Bible）** — 结构化记忆库，保障百万字级别的人物/伏笔/时间线一致性，支持版本快照与回滚
- **🔍 自动一致性校验** — 每章写完自动检测逻辑冲突、设定矛盾、伏笔遗漏（v0.3 CheckerAgent + StoryStateTracker 跨章台账）
- **📊 世界状态账本（v0.4）** — 摘要自动提取每章世界状态增量，累积成跨章快照，注入每章写作的「连贯性契约」（角色生死/位置/物品/伏笔搁置时长/当前剧情弧线）
- **🛡️ 全量连贯性审计（v0.4）** — 每 5 章自动对全书做一致性审计（S1-S4 分级整改清单），只报告不自动改，由你挑选对应章节定向重写
- **🖥️ 多视角审查 & node 预检** — ReviewerAgent 对账式审稿 + story-review skill 的 node 脚本机械校验
- **📕 短篇网文流水线** — 独立于长篇状态机：构思框架 → 成文 → 去AI味 → 审查 → 预检，注入 story-short-write skill 题材风格包
- **📦 Skill 知识注入** — 运行时加载 `~/.agents/skills/` 下已安装网文 skill 的 references（缺失时内嵌降级）
- **💎 文风润色** — 可选文笔优化，含去AI味（deslop）规则
- **🖥️ Web UI 界面** — 实时进度监控（SSE 流式）、日志流、章节/短篇浏览、世界状态与审计报告展示、一键导出
- **🔑 双模式运行** — 支持 API Key 调用真实 LLM / 无 Key 时 Demo 模式演示完整流程

## 🏗️ 架构设计

```
长篇：
用户创意 → [世界构建Agent] → 故事圣经(角色/地点/势力)
         ↓
    [大纲架构Agent] → 总纲 → 分卷大纲 → 章节细纲
         ↓
    [正文写作Agent] ← 从故事圣经检索上下文(RAG式注入)
         │              ├ 连贯性契约（世界状态/伏笔/弧线）★v0.4
         │              ├ 前情提要（语义召回+分桶历史脉络）★v0.4
         ↓
    [剧情检查Agent] → 一致性报告(通过/回炉) ← StoryStateTracker 跨章台账
         ↓
    [语言润色Agent] → 最终章节入库 + 更新故事圣经 + 世界状态账本★v0.4
         ↓
    [多视角审查Agent] → ReviewReport（/api/review/<num>）
         ↓
    node 预检（/api/precheck/<num>）
         ↓
    [全量连贯性审计Agent] → 每5章自动 AuditReport（/api/audit）★v0.4

短篇：
情绪/题材/创意 → [ShortStoryAgent 构思] → 框架JSON → 成文 → 去AI味润色 → 审查 → 预检
        （/api/short/architect → write → polish → review → precheck）
```

## 📁 项目结构

```
novel-agent/
├── app.py                 # Flask 主应用 & API 路由 & 流水线编排
├── requirements.txt       # Python 依赖
├── README.md              # 本文档
│
├── core/                  # 核心数据层
│   ├── story_bible.py     # ★ 故事圣经 —— 结构化设定与记忆管理（版本快照）
│   ├── state.py           # ★ StoryStateTracker —— 跨章台账（伏笔/摘要/历史问题）
│   ├── world_state.py     # ★ 世界状态账本 —— 跨章世界快照 + 连贯性契约 ★v0.4
│   ├── skill_knowledge.py # ★ Skill 知识加载器 —— references 注入 + 内嵌降级
│   ├── skill_precheck.py  # ★ node 预检 —— story-review 脚本机械校验
│   └── vector_index.py    # 向量索引（默认开启，缺依赖自动降级）
│
├── agents/                # Agent 模块
│   ├── base.py            # ★ 基类 & LLM调用封装 & Demo模式 & 模型路由
│   ├── world_builder.py   # 世界构建 Agent
│   ├── outline_agent.py   # 大纲架构 Agent
│   ├── writer_agent.py    # 正文写作 Agent
│   ├── checker_agent.py   # 剧情检查 Agent（v0.3 pydantic 校验）
│   ├── polisher_agent.py  # 语言润色 Agent（含去AI味）
│   ├── summarizer_agent.py# 章节摘要 Agent（含 world_state_delta 提取 ★v0.4）
│   ├── reviewer_agent.py  # 多视角审查 Agent
│   ├── audit_agent.py     # ★ 全量连贯性审计 Agent（ContinuityAuditor）
│   └── short_story_agent.py # ★ 短篇 Agent（构思框架 + 成文）
│
├── templates/             # Web UI 模板
│   └── index.html         # 单页应用界面（长篇 + 短篇标签页）
│
├── static/                # 静态资源
│   ├── css/style.css      # 样式表（暗色主题）
│   └── js/app.js          # 前端交互逻辑
│
└── data/                  # 运行时数据（自动生成，已 gitignore）
    ├── story_bible.json   # 故事圣经持久化
    ├── outline.json       # 大纲数据
    ├── chapters.json      # 章节正文
    ├── state.json         # 跨章台账
    ├── world_state.json   # 世界状态账本 ★v0.4
    ├── short_story.json   # 短篇流水线状态
    └── export.txt         # 导出的小说文本
```

## 🚀 快速开始

### 1. 安装依赖

```bash
cd novel-agent
pip install -r requirements.txt
```

### 2. 配置 LLM（可选）

不配置也可以运行！项目内置了 **Demo 模式**，会返回预设的示例输出让你体验完整流程。

如需使用真实 AI 输出：

```bash
# 方式一：环境变量
export OPENAI_API_KEY="sk-your-key-here"
export OPENAI_BASE_URL="https://api.openai.com/v1"     # 或其他兼容API
export LLM_MODEL="gpt-4o-mini"                          # 或 deepseek-chat 等
export LLM_FALLBACK_MODEL="deepseek-chat"               # 备用模型

# 方式二：.env 文件
echo "OPENAI_API_KEY=sk-your-key" > .env
```

支持的模型：
- OpenAI (GPT-4o / GPT-4o-mini)
- DeepSeek (deepseek-chat / deepseek-reasoner)
- 通义千问 / 其他 OpenAI 兼容 API

### 3. （可选）安装网文 Skill

从 `~/.agents/skills/` 注入写作知识（缺失时自动使用内嵌降级版，不影响运行）：

- `story-review` — 审查 rubric / 禁用词 / 去AI味 + 平台规则（fanqie/qidian/zhihu）+ node 预检脚本
- `story-long-write` — 长篇写作技巧 / 大纲结构理论
- `story-short-write` — 短篇技法 / 格式 / 投稿 / 反转工具箱 + `genre-styles/` 题材风格包（悬疑、追妻火葬场、甜宠…）

目录可通过环境变量 `SKILLS_DIR` 覆盖默认的 `~/.agents/skills`。

### 4. 启动服务

```bash
python app.py
```

访问 http://localhost:5000 即可看到 Web 界面。

### 5. 使用流程

**长篇：**
1. **输入创意** — 在工作台输入你的故事创意和类型偏好
2. **🌍 构建世界** — 点击按钮，Agent 自动生成世界观、人物卡、势力等
3. **📋 生成大纲** — 设定章节数量，生成分层大纲结构
4. **✍️ 写作全部** — 逐章自动写作（每章经历：写作→检查→润色→摘要提取→世界状态更新）
5. **🔎 审查/预检** — 对单章运行多视角审查与 node 预检（章节标签页内）
6. **🛡️ 连贯审计** — 每 5 章自动执行全量连贯性审计；也可随时点击「连贯审计」手动触发，按 S1-S4 分级整改清单挑选章节重写
7. **📥 导出** — 导出为 TXT 文本文件

**短篇：**
1. 在左侧「短篇小说模式」输入情绪/题材方向/短篇创意/目标字数/目标平台
2. **📐 构思框架** — 生成标题、核心反转、铺垫线索、情绪曲线、五段结构
3. **✍️ 成文** → **✨ 去AI味润色** → **🔎 审查** → **🔬 预检**
4. 在右侧「📕 短篇」标签页查看框架/初稿/润色稿/审查报告/预检报告

## 🔧 核心模块说明

### Story Bible（故事圣经）

整个系统的核心数据层，负责：

| 功能 | 说明 |
|------|------|
| 角色管理 | 角色卡片（外貌/性格/能力/关系/状态/弧线） |
| 地点/道具 | 结构化存储 |
| 伏笔追踪 | 埋设 → 待回收 → 已回收 全生命周期 |
| 时间线 | 按章节记录关键事件 |
| 章节摘要 | 滚动摘要链，支持前情提要注入 |
| 上下文组装 | `build_context_for_chapter()` 为每章组装写作上下文（超限自动压缩；v0.4 含连贯性契约 + 分桶历史脉络 + 全史语义召回） |
| 版本控制 | `checkpoint()` / `rollback()` 快照与回滚 |

### 世界状态账本（v0.4）

`core/world_state.py` 是跨章世界快照，专门对抗长篇小说前文遗忘：

- **增量提取**：`SummarizerAgent` 每章摘要自动提取 `world_state_delta`（角色/物品/地点/剧情线变化），`_update_world_state()` 累积进账本并持久化到 `data/world_state.json`
- **连贯性契约**：每次写作前把「当前世界状态 + 伏笔搁置时长 + 当前剧情弧线」渲染为 `=== 连贯性契约 ===` 段，作为最高优先级上下文注入 Writer（超限压缩时仍保留）
- **位置留痕**：角色位置变更自动记录 `location_history`，供审计识别「瞬移」类连贯性问题
- **伏笔老化**：未回收伏笔按「埋设了 N 章」标注，埋设过久（≥5 章）会在契约与 Checker 中提示，推动作者及时回收

### 全量连贯性审计（v0.4）

`agents/audit_agent.py` 的 **ContinuityAuditor** 对全书做一致性兜底审计：

- 输入全书已写章节抽样（首尾各 400 字）+ 世界状态 + 圣经摘要 + 历史问题，输出 **S1（必须改）→ S4（可选）** 分级整改清单
- 每写满 `AUDIT_INTERVAL = 5` 章自动触发一次，也可在章节标签页手动点击「🛡️ 连贯审计」（`POST /api/audit`，`GET` 查看最近报告）
- **只报告不自动改** — 审计结果告诉你该改哪一章、怎么改，由你选择重写，避免 AI 擅自改写破坏你已认可的内容

### Agent 系统

每个 Agent 继承 `BaseAgent`，定义独立的 `system_prompt` 和 `run()` 方法：

```
BaseAgent
├── WorldBuilderAgent   — 创意 → 完整世界观 JSON
├── OutlineAgent        — 世界观 → 分层大纲 JSON
├── WriterAgent         — 大纲+上下文 → 章节正文（【写作笔记】/【正文】）
├── CheckerAgent        — 正文+设定 → 检查报告（pydantic 校验 + 自动修复）
├── PolisherAgent       — 初稿 → 润色后正文（含去AI味）
├── SummarizerAgent     — 章节 → 摘要（含世界状态增量 ★v0.4）
├── ReviewerAgent       — 正文 → 多视角 ReviewReport（对账式）
├── AuditAgent          — 全书 → 全量连贯性 AuditReport（S1-S4 分级 ★v0.4）
└── ShortStoryAgent     — 情绪/题材/创意 → 短篇框架 JSON / 全篇正文
```

### Skill 知识注入

`core/skill_knowledge.py` 运行时读取已安装 skill 的 `references/*.md` 注入各 Agent 提示词：

- `get_knowledge(skill, path)` → `(text, source)`，`source ∈ {file, embedded}`
- `genre_style_rules(genre)` / `short_story_rules(genre)` — 短篇题材风格包
- 目录/文件缺失时回退 `EMBEDDED_*` 内嵌摘录，保证无 skill 环境照常工作

### node 预检

`core/skill_precheck.py` 调用 `story-review` skill 的 `scripts/precheck.mjs`（经 node）做机械校验（阻断/建议两档），输出归一化 `{ok, findings, severity_map}`；node 或脚本缺失时降级为纯 Python 内嵌实现。

### 流水线编排

在 `app.py` 中实现，核心流程：

```python
run_pipeline_step("world_build")   # 步骤1: 世界构建
run_pipeline_step("outline")       # 步骤2: 大纲生成
run_pipeline_step("write_chapter", chapter_num=N)  # 步骤3-N: 逐章写作
```

每个步骤在后台线程中运行，前端通过 SSE 流式 / `/api/status` 获取实时进度。所有对 `project.*` 状态的读写都经过 `project._lock` 保护。

## 🎮 Demo 模式详解

当没有配置 `OPENAI_API_KEY` 时，系统进入 **Demo 模式**：

- 内置了一个完整的玄幻小说示例（"苍澜大陆"世界观）
- 包含 3 个主要角色（沈炼 / 苏清歌 / 厉千行）
- 示例大纲（3卷10章结构）
- 示例第一章正文（约2000字）
- 示例检查报告、润色结果、审查报告、连贯性审计报告
- 短篇 demo：框架（寒江剑鸣）+ 短篇正文

这让你可以**零配置体验完整的创作流程**，理解各 Agent 的输入输出格式。

## 🛠️ 技术栈

- **Python 3.10+**
- **Flask** — Web 服务与 API（SSE 流式）
- **OpenAI SDK** — LLM 调用（兼容多种 API）
- **pydantic** — Checker/Reviewer/Audit 输出 schema 校验
- **node** — skill 预检脚本执行（可选）
- **sentence-transformers** — 语义召回（可选，缺失自动降级为滑动窗口；模型默认从**魔搭社区**拉取，失败回退 Hugging Face，详见 `requirements-rag.txt`）
- **纯数据驱动** — 无需数据库，JSON 文件持久化

## 📝 License

MIT License — 自由使用、修改和分发。

---

**作者**: 陈玉平 | **版本**: v0.4 | **日期**: 2026-08-17
