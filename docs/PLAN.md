# Agent-Bench：企业级 Agent 管理与评测系统 — 实施计划文档

> 版本：v1.0（待审核）
> 日期：2026-10-25
> 状态：**计划阶段，未开始编码**。审核通过后按本文档实施。

---

## 1. 项目概述

### 1.1 目标

构建一套企业级 Agent 管理与评测系统，提供从「评测数据管理 → Agent 执行 → 自动评分 → 归因分析 → 报告生成」的全链路自动化能力，帮助企业规模化、标准化地评估和优化 Agent 应用。

### 1.2 核心能力（六大模块）

| # | 模块 | 核心能力 |
|---|------|---------|
| 1 | 评测集管理 | 手动录入、JSON 批量导入、评测维度自定义、数据集版本管理 |
| 2 | 三类 Agent 评测 | 基于 LangChain 构建 Prompt Agent（纯推理）、RAG Agent（检索增强）、Tool Agent（工具调用） |
| 3 | LLM-as-Judge 自动评分 | 准确性 / 安全性 / 流畅性 / 任务完成度 / 幻觉检测五维评分，每维配备详细 Rubric，支持自定义维度 |
| 4 | 自动化评测流水线 | 评测集加载 → 批量执行 → Langfuse 追踪 → 多维评分 → 归因分析 → 报告生成；支持并行执行与 A/B 对比实验 |
| 5 | 三层归因分析 | Prompt 层 / RAG 层 / Tool 层失败根因自动定位，并生成优化建议 |
| 6 | 数据治理 | 统一标签体系、数据质量校验（重复/缺失/异常检测）、统计口径集中管理 |

### 1.3 交付物

- 后端服务（FastAPI，REST API）
- Web 管理控制台（React + Ant Design）
- 内置示例评测集（三类 Agent 各一套，用于演示与验收）
- Langfuse 追踪集成（可自托管或用云端；未配置时降级为本地 JSON Trace）
- 部署与使用文档（README + API 文档 FastAPI 自动生成）

---

## 2. 总体架构

### 2.1 技术选型

| 层 | 选型 | 说明 |
|----|------|------|
| 后端框架 | Python 3.11+ / FastAPI / Pydantic v2 | 异步 API，自动生成 OpenAPI 文档 |
| ORM / 迁移 | SQLAlchemy 2.x / Alembic | 同一套模型支持 SQLite 与 MySQL |
| 数据库 | 默认 SQLite（零配置），可通过连接串切换 MySQL 8 | 开发零依赖，生产可平迁 |
| Agent 框架 | LangChain（langchain-core / langchain-openai / langchain-community） | 基于 LCEL 与标准抽象构建 |
| LLM 接入 | OpenAI 兼容协议（base_url + api_key + model 全部可配置） | 兼容 GLM / OpenAI / DeepSeek / 本地 vLLM 等；被测模型与 Judge 模型独立配置 |
| 向量检索（RAG Agent） | FAISS（本地文件，轻量无外部依赖）+ 可配置 Embedding（OpenAI 兼容） | 知识库文档由系统内置 + 支持上传 |
| 追踪 | Langfuse Python SDK + `CallbackHandler` 注入 LangChain | 云端或 Docker 自托管；未配置时降级本地 JSON Trace，保证系统可独立运行 |
| 并发执行 | asyncio + Semaphore 限流（执行、评分分别限流） | v1 不引入 Celery 等重型队列，降低部署成本 |
| 前端 | React 18 + Vite + TypeScript + Ant Design 5 + ECharts | 报告可视化（雷达图 / 分布图 / 趋势图） |
| 统计检验 | SciPy（配对 t 检验 / Wilcoxon，用于 A/B 显著性） | — |

### 2.2 系统架构图（文字版）

```
┌─────────────────────────────────────────────────────────────┐
│                Web 控制台 (React + AntD + ECharts)           │
│  仪表盘 │ Agent管理 │ 评测集管理 │ 评测任务 │ 报告 │ 数据治理 │
└──────────────────────────┬──────────────────────────────────┘
                           │ REST API
┌──────────────────────────▼──────────────────────────────────┐
│                    后端服务 (FastAPI)                        │
│  ┌──────────┐ ┌──────────┐ ┌───────────┐ ┌───────────────┐  │
│  │Agent管理  │ │评测集管理 │ │ 评测流水线 │ │  数据治理      │  │
│  │(版本/配置)│ │(版本/导入)│ │ (编排/并发)│ │ (标签/质量/口径)│  │
│  └──────────┘ └──────────┘ └─────┬─────┘ └───────────────┘  │
│                              ┌───▼────────────────────┐     │
│                              │      评测执行引擎        │     │
│  ┌───────────────────────────┤ · Prompt/RAG/Tool Agent │     │
│  │                           │ · LLM-as-Judge 评分器    │     │
│  │                           │ · 三层归因分析引擎        │     │
│  │                           └───┬───────────┬────────┘     │
│  │                    LLM API ───┘           │              │
│  │              (OpenAI 兼容,被测/Judge 分开)  │ Trace 上报   │
└──┼───────────────────────────────────────────┼──────────────┘
   │                                    ┌──────▼──────┐
┌──▼───────────┐                        │   Langfuse   │
│  数据库       │                        │ (云/自托管/   │
│ SQLite/MySQL │                        │  本地降级)    │
└──────────────┘                        └─────────────┘
```

### 2.3 目录结构

```
agent-bench/
├── backend/
│   ├── app/
│   │   ├── main.py               # FastAPI 入口
│   │   ├── core/                 # 配置(.env)、数据库会话、公共依赖
│   │   ├── models/               # SQLAlchemy ORM 模型
│   │   ├── schemas/              # Pydantic 请求/响应模型
│   │   ├── api/                  # 路由: agents / datasets / dimensions / runs / governance / system
│   │   ├── agents/               # 三类 Agent（工厂模式）
│   │   │   ├── base.py           #   统一接口: ainvoke(case) -> AgentOutput
│   │   │   ├── prompt_agent.py   #   纯推理 LCEL 链
│   │   │   ├── rag_agent.py      #   向量检索 + 生成
│   │   │   ├── tool_agent.py     #   工具调用 Agent + 内置工具集
│   │   │   └── tools/            #   SQL 查询、计算器、知识检索等工具实现
│   │   ├── evaluation/
│   │   │   ├── judge.py          # LLM-as-Judge（结构化 JSON 输出）
│   │   │   ├── rubrics.py        # 五个内置维度的详细评分标准
│   │   │   ├── pipeline.py       # 流水线编排（阶段状态机 + 并发 + 断点续跑）
│   │   │   └── metrics.py        # 统计口径（唯一实现，所有报告共用）
│   │   ├── attribution/
│   │   │   ├── engine.py         # 归因编排：规则引擎 + LLM 辅助
│   │   │   ├── prompt_layer.py   # 指令设计 / Prompt 注入检测
│   │   │   ├── rag_layer.py      # 召回率 / 幻觉归因
│   │   │   ├── tool_layer.py     # 工具选择 / SQL 生成归因
│   │   │   └── suggestions.py    # 优化建议生成（模板 + LLM 润色）
│   │   ├── governance/
│   │   │   ├── tags.py           # 统一标签体系（领域/难度/场景/风险）
│   │   │   ├── quality.py        # 缺失/异常检测
│   │   │   └── dedup.py          # 精确 + 语义近似去重
│   │   └── integrations/
│   │       ├── llm.py            # LLM 工厂（读取配置构建模型实例）
│   │       └── tracing.py        # Langfuse 集成 / 本地降级
│   ├── alembic/                  # 数据库迁移
│   ├── tests/                    # pytest 单测 + 流水线集成测试
│   ├── pyproject.toml
│   └── .env.example
├── frontend/                     # React + Vite + AntD 控制台
├── seed/                         # 示例评测集(JSON) + RAG 知识库文档 + 演示数据库
├── docker-compose.yml            # Langfuse 自托管（可选，含 mysql/postgres）
├── docs/PLAN.md                  # 本文档
└── README.md
```

---

## 3. 核心数据模型

> 关键设计：**Agent 与数据集均采用不可变版本快照**，评测任务绑定具体版本，保证任何一次评测结果可复现、可回溯。

| 表 | 关键字段 | 说明 |
|----|---------|------|
| `agent` | id, name, description, type(`prompt`/`rag`/`tool`) | Agent 注册信息 |
| `agent_version` | agent_id, version, config(JSON), created_at | config 含模型、system prompt、temperature、工具列表、检索参数等；版本只增不改 |
| `dataset` | id, name, description | 评测集 |
| `dataset_version` | dataset_id, version, case_count, quality_summary, created_at | 发布时冻结快照，版本只增不改 |
| `eval_case` | dataset_version_id, seq, input, expected_output, reference_context, tools_spec, difficulty, tags(JSON), meta(JSON) | 单条评测样本；`reference_context` 供 RAG 幻觉比对；`tools_spec` 声明该用例预期工具行为 |
| `dimension` | code, name, description, rubric(文本), weight, is_builtin, applicable_agent_types | 评测维度；内置 5 个 + 用户自定义 |
| `eval_run` | id, name, mode(`single`/`ab`), status, agent_version_ids, dataset_version_id, judge_model, concurrency, config, started_at, finished_at | 一次评测任务；A/B 模式绑定 2 个 Agent 版本 |
| `case_result` | run_id, case_id, agent_version_id, output, error, status, latency_ms, token_usage, trace_id, raw_trace(JSON 降级时) | Agent 执行结果（含工具调用轨迹、检索到的文档列表） |
| `dimension_score` | case_result_id, dimension_code, score(0-5), rationale, evidence | Judge 逐维度评分及依据 |
| `attribution_finding` | case_result_id, layer(`prompt`/`rag`/`tool`), issue_code, severity, evidence, suggestion | 归因结论 |
| `report` | run_id, summary(JSON), html_path, md_path | 汇总报告 |
| `tag_dict` | category, value, parent_id, enabled | 统一标签字典 |

---

## 4. 模块详细设计

### 4.1 模块一：评测集管理

**功能点**

1. **手动录入**：表单逐条添加，字段校验（必填项、标签合法性、难度枚举）；支持复制已有样本微调。
2. **JSON 批量导入**：上传/粘贴 JSON 数组，格式模板一键导出；导入前先进入**预检**（逐条校验 + 质量扫描结果展示），确认后落库；错误行可下载回执（带失败原因）。
3. **评测维度自定义**：内置 5 维（见 4.3）不可删除但可调权重/停用；用户可新增自定义维度（code、名称、Rubric 描述、权重、适用 Agent 类型），评分时 Judge 按维度 Rubric 打分。
4. **版本管理**：数据集编辑状态（草稿）→ 发布生成新版本（冻结快照）；版本列表可查看 diff（新增/删除/修改条数）、可回滚为草稿继续编辑、可导出 JSON；评测任务只能引用已发布版本。

**JSON 导入格式（示例）**

```json
[
  {
    "input": "查询2024年华东区销售额最高的产品",
    "expected_output": "产品A，销售额1200万",
    "reference_context": "（RAG 用，可选）知识片段文本…",
    "tools_spec": {"expected_tool": "sql_query", "expected_args": "..."},
    "difficulty": "hard",
    "tags": {"domain": "数据分析", "scenario": "nl2sql", "risk": "low"}
  }
]
```

### 4.2 模块二：三类 Agent（LangChain 实现）

统一抽象：所有 Agent 实现 `async ainvoke(case: EvalCase) -> AgentOutput`，返回 `output`（最终回答）、`intermediate`（中间步骤：检索文档列表 / 工具调用序列 / 参数 / 结果）、`token_usage`、`latency_ms`。中间轨迹是后续归因分析的数据基础。

| Agent | 实现方式 | 说明 |
|-------|---------|------|
| **Prompt Agent**（纯推理） | LCEL：`ChatPromptTemplate \| llm \| StrOutputParser` | 考察指令遵循、推理、写作能力；config 可配置 system prompt、温度、few-shot 示例 |
| **RAG Agent**（检索增强） | FAISS 向量库 + retriever + LCEL 生成链 | 系统内置示例知识库；config 可配置 top_k、chunk 大小、是否引用标注；执行时记录召回文档列表与得分，用于召回率与幻觉归因 |
| **Tool Agent**（工具调用） | LangChain tool-calling Agent + 内置工具集 | 内置工具：①`sql_query`（对内置示例 SQLite/MySQL 演示库执行只读 SQL，含 SQL 注入防护）②`calculator` ③`knowledge_search`（查知识库）④`http_api_mock`（模拟 API）；执行时记录每次工具选择、参数、执行结果 |

Agent 管理还包括：注册新 Agent、创建新版本（保存 config 快照）、版本间 config diff 对比、按版本发起评测。

### 4.3 模块三：LLM-as-Judge 自动评分

**五个内置维度（0-5 分制，各配详细 Rubric，评分输出结构化 JSON）**

| 维度 | code | 评分要点（Rubric 摘要，完整版在 `rubrics.py`） |
|------|------|----------------------------------------------|
| 准确性 | `accuracy` | 与 expected_output 的事实/结论一致性；数值、实体、逻辑关系正确性；错误性质（关键错误 vs 细节瑕疵）分级扣分 |
| 安全性 | `safety` | 是否泄露敏感信息（PII/密钥）、有害内容、越权操作建议；面对诱导/注入输入是否守住边界；0 分=严重安全问题 |
| 流畅性 | `fluency` | 语言通顺、结构清晰、格式符合指令要求（列表/表格/字数等）；考察可读性而非内容正确性 |
| 任务完成度 | `task_completion` | 是否完成输入要求的全部子任务；有无遗漏、答非所问、过度发挥；多步任务的完成比例 |
| 幻觉检测 | `hallucination` | 对照 reference_context / expected_output 找无依据陈述；5 分=无幻觉，0 分=核心结论为编造；分数越高幻觉越少（正向指标统一口径） |

**Judge 设计要点**

1. **结构化输出**：强制 JSON Schema（`{dimension_code: {score, rationale, evidence}}`），解析失败自动重试，重试仍失败标记该维度评分异常并计入 run 错误统计。
2. **两种评分模式**（run 级配置）：`single-call`（一次调用评全部维度，省 token，默认）与 `per-dimension`（逐维度独立调用，干扰小，Rubric 更聚焦）。
3. **防偏差机制**：Rubric 中锚定分数量级（0/2/4/5 分典型样例描述）；Judge 模型与被测模型可配置为不同供应商，避免自我偏好。
4. **评分可追溯**：每次 Judge 调用上报 Langfuse（tags: run_id、case_id、dimension），rationale 与 evidence 落库，报告中可展开查看每条评分依据。
5. **权重与聚合**：维度加权总分 = Σ(score × weight) / Σweight；权重按 run 所用维度集合现算，统计口径集中在 `metrics.py`。

### 4.4 模块四：自动化评测流水线

**阶段状态机**

```
PENDING → LOADING → EXECUTING → SCORING → ATTRIBUTING → REPORTING → DONE
                    └──────────── 任意阶段失败 → FAILED（保留已完成结果，支持断点续跑）────────────┘
```

**流程**

1. **加载**：读取绑定的 dataset_version 全量样本，初始化进度计数。
2. **执行**（并行）：`asyncio.Semaphore` 控制并发（默认 5，可配）；逐样本调用 Agent；Langfuse `CallbackHandler` 自动埋点（run/case 两级 tag），记录 trace_id；Agent 异常不中断整批，错误信息落 `case_result`。
3. **评分**（并行）：对所有成功结果并发调用 Judge；A/B 模式下两版本结果使用**相同 Judge 配置与相同随机种子**评分，保证可比。
4. **归因**：对未达标样本（任一维度 < 阈值，默认 3 分）触发归因引擎（见 4.5）。
5. **报告**：聚合统计（口径见 4.6）→ 生成 HTML 报告 + Markdown 摘要 + 原始 JSON，落 `report` 表。
6. **断点续跑**：run 重启时按 `case_result` 已完成记录跳过，失败样本可选择单独重跑。

**A/B 对比实验**

- 创建 run 时选择 2 个 Agent 版本（如 v1 vs v2 prompt），同一数据集版本逐样本配对执行；
- 报告输出：各维度配对差值、胜/平/负计数、配对显著性检验（配对 t 检验，样本少时 Wilcoxon 符号秩检验）、按标签分组的差异切片（如「nl2sql 场景 v2 提升显著，闲聊场景无差异」）。

### 4.5 模块五：三层归因分析

**输入**：未达标样本的 `case_result`（含中间轨迹）+ 评分结果 + 用例元数据（expected、reference_context、tools_spec）。
**方法**：确定性规则引擎优先（可解释、稳定、零成本），LLM 辅助判定兜底（规则不确定时），两类结论都带 evidence。

| 层 | 检测项 | 归因依据（示例规则） | issue_code 示例 |
|----|--------|---------------------|----------------|
| **Prompt 层** | 指令设计缺陷 | 输出格式违背指令（要求 JSON 但输出散文）、漏答子问题、拒答/跑题、语言不符 | `PROMPT_FORMAT_VIOLATION`、`PROMPT_PARTIAL_COMPLETION`、`PROMPT_OFF_TOPIC` |
| | Prompt 注入命中 | 输入含注入模式（角色劫持、指令覆盖、越权诱导等规则库）且 Agent 输出被执行/泄露 → 归因为注入防御缺失 | `PROMPT_INJECTION_SUCCESS` |
| **RAG 层** | 召回失败 | expected 参考文档未出现在召回列表（召回率@k 计算）、召回为空 | `RAG_RECALL_MISS`、`RAG_EMPTY_RETRIEVAL` |
| | 生成幻觉 | 输出中的关键实体/数值在召回上下文中无支撑（嵌入相似度 + LLM 抽取断言比对） | `RAG_UNSUPPORTED_CLAIM` |
| | 引用错误 | 声称引用某文档但内容不符 | `RAG_CITATION_MISMATCH` |
| **Tool 层** | 工具选择错误 | 与 tools_spec.expected_tool 不符、Agent 循环空转、无工具调用直接作答 | `TOOL_WRONG_SELECTION`、`TOOL_NO_CALL`、`TOOL_LOOP` |
| | 参数错误 | 参数缺失/类型错误 | `TOOL_BAD_ARGS` |
| | SQL 生成问题 | SQL 语法错误（执行报错）、执行成功但结果与 expected 不符（语义错误） | `TOOL_SQL_SYNTAX`、`TOOL_SQL_SEMANTIC` |

**输出**：每条 finding = `{layer, issue_code, severity(high/medium/low), evidence(原始证据片段), suggestion}`。
**优化建议生成**：每个 issue_code 映射建议模板（如 `RAG_RECALL_MISS` → 建议「提高 top_k / 改进 chunk 切分 / 补充知识库覆盖」），再由 LLM 结合具体 case 内容润色为针对性建议；报告按层聚合 Top 失败模式。

### 4.6 模块六：数据治理

1. **统一标签体系**：四类受控标签字典 — `domain`（领域）、`difficulty`（难度）、`scenario`（场景）、`risk`（风险等级）；录入/导入时强校验；支持管理员维护字典；统计与 A/B 切片均基于该体系。
2. **数据质量校验**（导入预检 + 发布前检查 + 手动触发，产出质量报告）：
   - **重复检测**：精确（规范化后 hash）+ 近似（embedding 余弦相似度 ≥ 阈值，默认 0.92）；
   - **缺失检测**：必填字段、expected_output 为空、RAG 类数据集缺 reference_context 等场景化必填规则；
   - **异常检测**：超长/超短输入、乱码（不可打印字符比例）、语言与数据集主语言不一致、标签非法值、难度分布严重倾斜（提示但仅告警）。
   - 质量报告按 阻断（错误）/ 提示（告警） 分级，阻断项须修复才能发布版本。
3. **统计口径管理**：所有指标集中在 `evaluation/metrics.py` 唯一实现，避免多处计算不一致。核心口径：
   - 维度均分 = 该维度所有样本算术平均；
   - 通过率 = 全部启用维度均 ≥ 通过阈值（默认 3 分）的样本占比；
   - 幻觉率 = `hallucination ≤ 2` 分样本占比；
   - P95 延迟、token 消耗均值；
   - A/B 提升幅度 = (B 均分 − A 均分) / A 均分（逐维度、逐标签切片）。

---

## 5. API 设计概览（REST，前缀 `/api`）

| 资源 | 主要端点 |
|------|---------|
| Agents | `GET/POST /agents`，`GET /agents/{id}`，`POST /agents/{id}/versions`，`GET /agents/{id}/versions`，`POST /agents/{id}/versions/{vid}/test`（单样本试跑） |
| 数据集 | `GET/POST /datasets`，`POST /datasets/{id}/cases`，`PUT/DELETE /datasets/{id}/cases/{cid}`，`POST /datasets/{id}/import`（预检+确认两步），`POST /datasets/{id}/publish`，`GET /datasets/{id}/versions`，`GET /datasets/{id}/versions/{vid}/export` |
| 维度 | `GET /dimensions`，`POST /dimensions`，`PUT /dimensions/{code}` |
| 评测任务 | `POST /runs`（single/ab），`GET /runs`，`GET /runs/{id}`（含进度），`POST /runs/{id}/retry`，`GET /runs/{id}/report`（HTML/MD/JSON） |
| 归因 | `GET /runs/{id}/findings`，`GET /runs/{id}/findings?layer=rag` |
| 数据治理 | `GET/POST /governance/tags`，`POST /datasets/{id}/quality-check`，`GET /governance/quality-reports/{id}` |
| 系统 | `GET /system/health`，`GET/PUT /system/settings`（LLM/Langfuse 配置，密钥脱敏回显） |

---

## 6. Web 控制台页面规划

| 页面 | 内容 |
|------|------|
| 仪表盘 | 最近评测任务、平均分趋势、失败模式 Top5、数据集/Agent 统计卡片 |
| Agent 管理 | 列表 + 类型筛选；详情（版本时间线、config JSON、版本 diff、单样本试跑） |
| 评测集管理 | 列表；详情（样本表格、标签筛选、批量导入向导：上传→预检→确认；版本列表与 diff；质量报告入口） |
| 评测任务 | 新建向导（选 Agent 版本 → 选数据集版本 → 选维度/权重/并发/Judge 模式，A/B 勾选第二个版本）；列表与实时进度；任务详情（样本瀑布：执行中/完成/失败） |
| 评测报告 | 总分与维度雷达图、分数分布直方图、按标签切片对比、失败样本明细（输入/输出/评分依据/归因结论/建议）、A/B 对比页（配对差值 + 显著性 + 切片）、Langfuse trace 跳转链接 |
| 数据治理 | 标签字典管理；质量报告查看（问题清单定位到具体样本） |
| 系统设置 | LLM 配置（被测/Judge 分别配置）、Langfuse 配置、通过阈值等全局参数 |

---

## 7. 实施计划（里程碑）

> 每个里程碑结束产出可运行、可验证的增量；后端先行，前端在 M6 一次性对接。

| 阶段 | 内容 | 验收标准 |
|------|------|---------|
| **M1 工程脚手架** | 目录结构、依赖管理、配置加载（.env）、数据库模型 + Alembic 迁移、FastAPI 骨架、LLM 工厂与 Langfuse 集成（含本地降级） | 服务可启动，`/api/system/health` 正常，迁移可执行 |
| **M2 评测集 + 数据治理** | 数据集 CRUD、手动录入、JSON 导入（预检/回执）、版本发布/导出/diff、标签字典、质量校验引擎 | 用示例 JSON 完成导入→质检→发布→导出闭环 |
| **M3 三类 Agent** | 统一抽象、Prompt/RAG/Tool Agent、内置工具集（含演示数据库与示例知识库）、Agent 版本管理、单样本试跑 | 三类 Agent 各通过一组手工样本试跑 |
| **M4 评分 + 流水线** | 五维 Rubric、Judge 结构化评分、流水线状态机、并发执行、断点续跑、Langfuse 埋点 | 对示例评测集完成一次端到端 run（含评分落库） |
| **M5 归因 + 报告 + A/B** | 三层归因引擎与建议生成、metrics 统计口径、HTML/MD/JSON 报告、A/B 配对分析与显著性检验 | 人为构造的失败样本被正确归因；A/B 报告产出 |
| **M6 Web 控制台** | 全部页面 + API 对接 + 图表 | 从页面完成「建数据集→建 Agent→发起 A/B→看报告」全流程 |
| **M7 验收交付** | 内置三类示例评测集、端到端集成测试、README/部署文档（含 docker-compose 自托管 Langfuse） | 全链路演示通过；测试通过 |

---

## 8. 风险与应对

| 风险 | 应对 |
|------|------|
| Judge 评分不稳定 | Rubric 分级锚定 + per-dimension 模式 + 评分重试；后续可加多 Judge 投票（v1 预留接口不实现） |
| LLM API 成本与限流 | 并发可配 + 限流退避重试；single-call 评分模式省 token |
| Langfuse 未部署 | 本地 JSON Trace 降级方案，系统不依赖 Langfuse 也能完整运行 |
| 近似去重依赖 embedding 接口 | 精确去重不依赖网络；语义去重在配置了 embedding 后自动启用 |
| Windows 开发环境 | 纯 Python + SQLite + 本地 FAISS，无必须 Linux 的组件 |

---

## 9. 需要你确认的决策点

| # | 问题 | 默认方案（不回复则按默认执行） |
|---|------|------------------------------|
| 1 | LLM 供应商与模型（被测 + Judge） | 走 `.env` 配置 OpenAI 兼容接口，先留空占位，由你后续填入 base_url/api_key/model |
| 2 | Langfuse 接入方式 | 默认本地 JSON Trace 降级模式；docker-compose 自托管文件一并交付，你部署后填 key 即切换 |
| 3 | 数据库 | 默认 SQLite 零配置；提供 MySQL 连接串切换（你环境已有 MySQL） |
| 4 | 前端 | React + Ant Design（企业管理台常见栈） |
| 5 | 是否内置示例评测集 | 内置三类各 10~20 条示例样本 + 演示数据库 + 示例知识库，保证开箱即可跑通端到端 |

---

**审核确认后，我按 M1 → M7 顺序开始实施。** 如对架构、模块划分、技术选型有任何调整意见，请直接批注。
