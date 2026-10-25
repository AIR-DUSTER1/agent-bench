# Agent-Bench — Agent 评测平台

一句话：**给 Agent 组织考试的系统**。你出题（评测集），Agent 逐题作答，AI 阅卷打分，最后告诉你它差在哪、该怎么改。

## 它能做什么

- **内置 3 个 Agent**（Prompt / RAG / Tool），装好就能跑通全流程，用来演示和对照
- **接入你自己的 Agent**，两种方式：调它的 HTTP 接口，或者当命令行程序调用。本仓库已接入两个真实项目验证（见下文）
- **自动阅卷**：用另一个 LLM 当裁判（Judge），按 5 个维度打分——准确性、安全性、流畅性、任务完成度、幻觉检测，每个维度都有明确的评分标准
- **A/B 对比**：两个 Agent 做同一套题，逐题配对比较，并用统计检验告诉你差距是不是真的（不是运气）
- **归因分析**：不只给分，还定位问题——是 Prompt 没写好、检索没查到、还是工具选错了，并给出修改建议
- **报告**：一份 HTML 报告（雷达图 + 分数分布 + 逐题明细），另有 Markdown 和 JSON

## 快速开始

```bash
# 1. 装依赖
cd backend
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt     # Windows；Linux/macOS 用 .venv/bin/pip

# 2. 配置模型
copy .env.example .env        # 填上你的 LLM_API_KEY（OpenAI 兼容接口即可）

# 3. 初始化（自动导入示例评测集和内置 Agent，重复执行无副作用）
.venv\Scripts\python ..\scripts\bootstrap.py

# 4. 启动
.venv\Scripts\python -m uvicorn app.main:app --port 8000
```

启动后：

- **管理界面**：http://127.0.0.1:8000/ （发起评测、看报告、管数据集都在这，不需要敲 API）
- **API 文档**：http://127.0.0.1:8000/docs

> 要对外提供服务时，在 `.env` 里设置 `AUTH_TOKEN`，所有 API 会要求 Bearer token。

## 接入你自己的 Agent

在管理界面「Agent 管理 → 注册 Agent」里选类型：

| 类型 | 适合什么 | 配置示例 |
|------|---------|---------|
| `external_http` | 有聊天接口的服务 | `{"base_url": "http://127.0.0.1:3000", "protocol": "learn_agent_sse"}` |
| `external_cli` | 命令行程序，吃输入吐输出 | `{"argv": ["dsh", "--profile", "headless", "{input}"]}` |

已验证的两个真实例子：

- **learn-agent**（LangGraph 工作台）：先 `cd E:\study\work\learn-agent && npm run web` 启动它的服务，agent-bench 里已注册为 HTTP 型
- **deepseek-harness**：全局装好的 `dsh` 命令，注册为 CLI 型

两个都注册后，在发起评测时同时勾选 A、B 两侧，就是 A/B 对比。

## 几个概念，30 秒看完

- **评测集**：一堆「输入 + 期望输出」。支持 JSON 批量导入（先预检再确认，格式问题会在预检时拦住）。发布后版本冻结，之后改题目不影响已跑过的结果——保证可复现
- **评分维度**：默认 5 个维度，每个维度有详细的分档标准（Rubric）。可以自定义加维度
- **Judge**：负责打分的 LLM。可以和被测 Agent 用不同的模型，避免"自己给自己打分"
- **归因**：按 Agent 类型分层找原因。RAG 型查"检索有没有召回、回答有没有依据"，Tool 型查"工具有没有选对、SQL 对不对"，Prompt 型查"指令设计问题"

## 记分规则

- 每个维度 0~5 分，加权汇总成总分（内置权重：准确性 1.5、任务完成度 1.2、幻觉 1.2、安全 1.0、流畅性 0.8）
- 「通过」= 所有维度都不低于 3 分；Agent 调用失败直接算不通过
- A/B 显著性：题目 ≥ 8 道用配对 t 检验，否则用 Wilcoxon；p < 0.05 视为差异显著

## 其他你需要知道的

- **数据库**：默认 SQLite（`backend/data/agent_bench.db`），零配置开箱即用。要换 MySQL，改 `.env` 里的 `DATABASE_URL` 即可
- **追踪（可选）**：配置了 Langfuse 就上报到 Langfuse；不配置也没关系，trace 存本地 JSON（`backend/data/traces/`），功能完整可用
- **测试**：`cd backend && .venv\Scripts\python -m pytest tests -q` —— 21 项离线单测，不调真实 LLM，不花 API 钱

## 目录结构（想改代码时看）

```
backend/app/
├── api/           REST 接口（薄层，只做转发）
├── agents/        五类 Agent：prompt / rag / tool / external_http / external_cli
├── evaluation/    评分标准 / Judge / 评测流水线 / 统计 / 报告生成
├── attribution/   三层归因引擎
├── governance/    标签字典 / 数据质量校验
├── models/        数据库表定义
├── core/          配置(.env) / 数据库连接
└── integrations/  LLM 工厂 / Langfuse 追踪
seed/              示例知识库、演示数据库、四套评测集
scripts/           bootstrap.py 一键初始化
```

详细的架构约束和开发规范见 [AGENTS.md](AGENTS.md)。
