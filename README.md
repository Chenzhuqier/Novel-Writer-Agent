# 📖 小说写作 Agent (Novel Writer Agent)

> **基于多 Agent 协作的长篇小说智能创作系统**

一个完整可运行的 AI 小说写作系统原型，模拟专业作家的创作流程：**创意 → 世界观构建 → 大纲生成 → 正文写作 → 一致性检查 → 文笔润色**。

## ✨ 核心特性

- **🌍 多 Agent 流水线** — 5 个专职 Agent 分工协作（世界构建 / 大纲 / 写作 / 检查 / 润色）
- **📚 故事圣经（Story Bible）** — 结构化记忆库，保障百万字级别的人物/伏笔/时间线一致性
- **🔍 自动一致性校验** — 每章写完自动检测逻辑冲突、设定矛盾、伏笔遗漏
- **💎 文风润色** — 可选的文笔优化步骤
- **🖥️ Web UI 界面** — 实时进度监控、日志流、章节浏览、一键导出
- **🔑 双模式运行** — 支持 API Key 调用真实 LLM / 无 Key 时 Demo 模式演示完整流程

## 🏗️ 架构设计

```
用户创意 → [世界构建Agent] → 故事圣经(角色/地点/势力)
         ↓
    [大纲架构Agent] → 总纲 → 分卷大纲 → 章节细纲
         ↓
    [正文写作Agent] ← 从故事圣经检索上下文(RAG式注入)
         ↓
    [剧情检查Agent] → 一致性报告(通过/回炉)
         ↓
    [语言润色Agent] → 最终章节入库 + 更新故事圣经
```

## 📁 项目结构

```
novel-agent/
├── app.py                 # Flask 主应用 & API 路由 & 流水线编排
├── requirements.txt       # Python 依赖
├── README.md              # 本文档
│
├── core/                  # 核心数据层
│   ├── __init__.py
│   └── story_bible.py     # ★ 故事圣经 —— 结构化设定与记忆管理
│
├── agents/                # Agent 模块
│   ├── __init__.py
│   ├── base.py            # ★ 基类 & LLM调用封装 & Demo模式示例输出
│   ├── world_builder.py   # 世界构建 Agent
│   ├── outline_agent.py   # 大纲架构 Agent
│   ├── writer_agent.py    # 正文写作 Agent
│   ├── checker_agent.py   # 剧情检查 Agent
│   └── polisher_agent.py  # 语言润色 Agent
│
├── templates/             # Web UI 模板
│   └── index.html         # 单页应用界面
│
├── static/                # 静态资源
│   ├── css/style.css      # 样式表（暗色主题）
│   └── js/app.js          # 前端交互逻辑
│
└── data/                  # 运行时数据（自动生成）
    ├── story_bible.json   # 故事圣经持久化
    ├── outline.json       # 大纲数据
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

# 方式二：.env 文件
echo "OPENAI_API_KEY=sk-your-key" > .env
```

支持的模型：
- OpenAI (GPT-4o / GPT-4o-mini)
- DeepSeek (deepseek-chat / deepseek-reasoner)
- 通义千问 / 其他 OpenAI 兼容 API

### 3. 启动服务

```bash
python app.py
```

访问 http://localhost:5000 即可看到 Web 界面。

### 4. 使用流程

1. **输入创意** — 在工作台输入你的故事创意和类型偏好
2. **🌍 构建世界** — 点击按钮，Agent 自动生成世界观、人物卡、势力等
3. **📋 生成大纲** — 设定章节数量，生成分层大纲结构
4. **✍️ 写作全部** — 逐章自动写作（每章经历：写作→检查→润色→摘要提取）
5. **📥 导出** — 导出为 TXT 文本文件

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
| 上下文组装 | `build_context_for_chapter()` 为每章组装写作上下文 |

### Agent 系统

每个 Agent 继承 `BaseAgent`，定义独立的 `system_prompt` 和 `run()` 方法：

```
BaseAgent
├── WorldBuilderAgent   — 创意 → 完整世界观 JSON
├── OutlineAgent        — 世界观 → 分层大纲 JSON
├── WriterAgent         — 大纲+上下文 → 章节正文
├── CheckerAgent        — 正文+设定 → 检查报告 JSON
└── PolisherAgent       — 初稿 → 润色后正文
```

### 流水线编排

在 `app.py` 中实现，核心流程：

```python
run_pipeline_step("world_build")   # 步骤1: 世界构建
run_pipeline_step("outline")       # 步骤2: 大纲生成
run_pipeline_step("write_chapter", chapter_num=N)  # 步骤3-N: 逐章写作
```

每个步骤在后台线程中运行，前端通过轮询 `/api/status` 获取实时进度。

## 🎮 Demo 模式详解

当没有配置 `OPENAI_API_KEY` 时，系统进入 **Demo 模式**：

- 内置了一个完整的玄幻小说示例（"苍澜大陆"世界观）
- 包含 3 个主要角色（沈炼 / 苏清歌 / 厉千行）
- 示例大纲（3卷10章结构）
- 示例第一章正文（约2000字）
- 示例检查报告和润色结果

这让你可以**零配置体验完整的创作流程**，理解各 Agent 的输入输出格式。

## 🔮 后续可完善方向

这是 v0.1 Demo，以下方向可以逐步迭代：

### 近期改进
- [ ] **向量数据库 RAG** — 用 ChromaDB/Faiss 替代简单检索，提升上下文相关性
- [ ] **人机回环** — 大纲/正文确认后才进入下一步
- [ ] **单章重写** — 用户反馈后针对某章重新生成
- [ ] **Word/PDF 导出** — 格式化排版导出

### 中期增强
- [ ] **LangGraph 编排** — 用图状态机替代简单的函数流水线
- [ ] **多模型路由** — 不同 Agent 用不同模型（如推理模型做检查）
- [ ] **风格学习** — 导入参考作品让 Agent 学习文风
- [ ] **分支剧情支持** — 选择不同走向的情节分支

### 远期目标
- [ ] **协作编辑** — 多人同时在线编辑同一部小说
- [ ] **读者反馈闭环** — 收集读者评论影响后续剧情走向
- [ ] **多语言输出** — 同一故事生成中/英/日等多语种版本
- [ ] **IP 衍生** — 从小说自动生成人物立绘、章节封面等

## 🛠️ 技术栈

- **Python 3.10+**
- **Flask** — Web 服务与 API
- **OpenAI SDK** — LLM 调用（兼容多种 API）
- **纯数据驱动** — 无需数据库，JSON 文件持久化

## 📝 License

MIT License — 自由使用、修改和分发。

---

**作者**: 陈玉平 | **版本**: v0.1.1 | **日期**: 2026-08-07
