# Agent-Bench — 企业级 Agent 管理与评测系统

从「评测数据管理 → Agent 批量执行 → Langfuse 追踪 → LLM-as-Judge 多维评分 → 三层归因分析 → 报告生成」的全链路自动化评测平台。支持并行执行与 A/B 对比实验，既能评测内置 Agent（Prompt / RAG / Tool），也能通过 **HTTP / CLI 适配器**接入任意外部 Agent 项目（如本仓库已验证的 learn-agent 与 deepseek-harness）。

## 功能总览

| 模块 | 能力 |
|------|------|
| 评测集管理 | 手动录入、JSON 批量导入（预检→确认两步）、评测维度自定义、不可变版本快照（发布冻结，评测绑定版本可复现） |
| 三类内置 Agent | Prompt Agent（LCEL 纯推理）、RAG Agent（BM25 检索增强 + 引用生成）、Tool Agent（langchain create_agent + sql_query/calculator/knowledge_search 工具） |
| 外部 Agent 接入 | `external_http`（SSE 聊天协议，适配 learn-agent）/ `external_cli`（一次性 CLI 调用，适配 `dsh --profile headless`） |
| LLM-as-Judge | 准确性/安全性/流畅性/任务完成度/幻觉检测五维评分，每维详细 Rubric（分档锚定），结构化 JSON 输出 + 重试，`single_call`/`per_dimension` 两种模式，Judge 与被测模型可分供应商 |
| 评测流水线 | 六阶段状态机（loading→executing→scoring→attributing→reporting→done），asyncio 并发限流，断点续跑，失败样本可单独重跑 |
| 三层归因分析 | Prompt 层（指令设计/注入命中）、RAG 层（召回缺失/无支撑陈述）、Tool 层（选错工具/SQL 语法/SQL 语义/循环空转），规则引擎优先 + 证据落库 + 优化建议 |
| A/B 对比 | 同数据集逐样本配对，维度差值 + 胜/平/负 + 配对 t 检验 / Wilcoxon 显著性 + 标签切片差异 |
| 数据治理 | 四类受控标签字典、质量校验（精确+近似去重、缺失、乱码、非法标签、分布倾斜），阻断/提醒分级，统计口径集中于 `metrics.py` 唯一实现 |
| 追踪 | Langfuse SDK 上报（可选），未配置自动降级本地 JSON Trace（`backend/data/traces/`） |
| 报告 | 自包含 HTML（服务端 SVG 雷达图 + 分布直方图）+ Markdown + 原始 JSON |

## 快速开始

```bash
# 1. 安装依赖
cd backend
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt     # Windows；Linux/macOS 用 .venv/bin/pip

# 2. 配置（OpenAI 兼容端点；被测与 Judge 可分别配置）
copy .env.example .env        # 编辑 LLM_API_KEY 等

# 3. 初始化 + 导入内置评测集与 Agent（幂等）
.venv\Scripts\python ..\scripts\bootstrap.py

# 4. 启动
.venv\Scripts\python -m uvicorn app.main:app --port 8000
# 控制台   http://127.0.0.1:8000/
# API 文档 http://127.0.0.1:8000/docs
```

### 测试外部 Agent 项目（已验证的两个接入示例）

**learn-agent**（LangGraph.js 工作台，`E:\study\work\learn-agent`）：

```bash
cd E:\study\work\learn-agent && npm run web   # 启动其服务（127.0.0.1:3000）
```
bootstrap 已注册为 `external_http` Agent，配置：
```json
{"base_url": "http://127.0.0.1:3000", "protocol": "learn_agent_sse", "session_body": {"kind": "agent"}}
```

**deepseek-harness**（DeepSeek 官方 Harness，全局安装的 `dsh`）：bootstrap 已注册为 `external_cli` Agent，配置：
```json
{"argv": ["dsh", "--profile", "headless", "{input}"], "timeout": 240}
```

两者可发起 A/B 对比（控制台勾选 B 侧，或 `agent_version_ids` 传两个）。

## 目录结构

```
backend/app/
├── core/          配置(.env) / 数据库
├── models/        SQLAlchemy 模型（agent/dataset/evaluation/governance）
├── api/           REST 路由（agents/datasets/dimensions/runs/governance/system）
├── agents/        五类 Agent：prompt / rag / tool / external_http / external_cli
├── evaluation/    rubrics（五维评分标准）/ judge / pipeline / metrics（统计口径）/ report
├── attribution/   三层归因引擎（prompt/rag/tool + 建议模板 + 注入模式库）
├── governance/    标签字典 / 质量校验（去重、缺失、异常）
└── integrations/  LLM 工厂（OpenAI 兼容）/ Langfuse 追踪（本地降级）
seed/              示例知识库(kb/) / 演示数据库(demo.db) / 四套评测集(datasets/)
scripts/           bootstrap.py（一键初始化）
```

## 核心口径

- 维度评分 0-5（hallucination 分越高 = 幻觉越少，正向统一）
- 加权总分 = Σ(维度均分×权重)/Σ权重（内置权重：准确性1.5 / 任务完成度1.2 / 幻觉1.2 / 安全1.0 / 流畅性0.8）
- 通过率 = 全部启用维度均 ≥ PASS_THRESHOLD(默认3) 的样本占比，执行失败计为不通过
- A/B：n≥8 配对 t 检验，否则 Wilcoxon 符号秩（正态近似）；p<0.05 视为差异显著

## 运行测试

```bash
cd backend && .venv\Scripts\python -m pytest tests -q   # 15 项离线单测，不耗 LLM 配额
```

## Langfuse（可选）

未配置时系统以本地 JSON Trace 完整运行。要启用 Langfuse：部署官方 v3 自托管栈（Postgres/ClickHouse/Redis/MinIO，见 https://langfuse.com/self-hosting ，根目录 `docker-compose.langfuse.yml` 为最小参考），然后在 `backend/.env` 填 `LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY / LANGFUSE_HOST`。

## 数据库

默认 SQLite（`backend/data/agent_bench.db`，零配置）。切换 MySQL：改 `.env` 的 `DATABASE_URL`，如 `mysql+pymysql://user:pwd@127.0.0.1:3306/agent_bench`（需 `pip install pymysql`）。
