# AGENTS.md — agent-bench 项目规范（AI 助手必读）

> 本文件约束所有在本仓库工作的 AI 助手与人。目标：**高可用、易维护、可读性高、单一职责**。
> 修改代码前先读完本文；与本文冲突的做法一律以本文为准。

## 0. 项目一句话定位

企业级 Agent 评测系统：评测集管理 → Agent 批量执行 → LLM-as-Judge 五维评分 → 三层归因 → 报告生成，支持 A/B 对比与外部项目接入（HTTP/CLI 适配器）。

- 技术栈：Python 3.11+ / FastAPI / SQLAlchemy 2（SQLite，可切 MySQL）/ langchain 1.x / 自实现 BM25 / 手写显著性检验
- 入口：`backend/app/main.py`；启动：`cd backend && .venv\Scripts\python -m uvicorn app.main:app --port 8000`
- 文档：`README.md`（使用）、`docs/PLAN.md`（设计）；API 自文档：`/docs`

## 1. 分层与单一职责（红线）

```
api（路由，薄）  →  evaluation / attribution / governance（引擎，业务）  →  models（ORM）+ integrations（外部）
agents/ 五类 Agent 只实现"执行一件事"，不碰评分与归因
```

**依赖方向只能从上往下**：`api → 引擎层 → models/integrations`。禁止反向 import、禁止引擎层 import api 层、禁止循环依赖。

| 目录 | 唯一职责 | 明确不做 |
|---|---|---|
| `app/api/` | 参数校验、调引擎、组装响应 | 不写业务计算、不直接写 LLM 调用 |
| `app/evaluation/` | 评分、流水线编排、统计口径、报告渲染 | 不做 HTTP 路由 |
| `app/attribution/` | 三层归因规则与建议模板 | 不调用 LLM 评分（规则优先，LLM 兜底也走 evaluation 的 llm 工厂） |
| `app/governance/` | 标签字典、质量校验 | 不做评分 |
| `app/agents/` | 五类 Agent 的执行适配，输出统一 `AgentOutput` | 不落库、不评分 |
| `app/models/` | ORM 定义 | 不含业务逻辑 |
| `app/integrations/` | LLM 工厂、Trace 上报（Langfuse/本地降级） | 不含业务判断 |
| `app/core/` | 配置与 DB 会话 | 改配置只改 `.env` + `config.py`，禁止散落硬编码 |
| `seed/` `scripts/` | 种子数据与一次性脚本 | 不被运行时代码 import |

**改动路由表**（改需求先定位这里，禁止跨层乱放）：

| 要改什么 | 去哪里改 |
|---|---|
| 评分标准/新增维度 | `evaluation/rubrics.py`（内置维度）或 `/api/dimensions`（自定义维度） |
| 指标计算（通过率/均分/P95/显著性） | **只能** `evaluation/metrics.py`，别处禁止重算（见 §2.2） |
| 流水线阶段/并发/断点续跑 | `evaluation/pipeline.py`，必须遵守 stage 协议（§2.4） |
| 归因规则/建议文案 | `attribution/engine.py`（`SUGGESTIONS`/`INJECTION_PATTERNS`） |
| 报告样式/新增图表 | `evaluation/report.py`（数据在 Python 侧预计算，Jinja 模板禁止写推导式） |
| 新增 Agent 类型 | `agents/` 新建适配器 + `base.py:build_agent` 注册，必须实现 `AgentOutput` 契约（§2.3） |
| 质检规则 | `governance/quality.py`，级别必须是 `blocker|warning` |
| 标签字典 | `governance/tags.py` 的 `BUILTIN_TAG_DICT` 或 API 维护 |
| 新增 API 端点 | `app/api/` + `schemas.py`，路由保持 REST 风格与现有命名 |

## 2. 核心不变量（改动前必须理解，破坏即引入线上事故级缺陷）

### 2.1 版本不可变
`dataset_version`（非 draft）与 `agent_version` 是**冻结快照**，发布后只读。一切修改走「草稿 → 新版本发布」；评测任务只绑定已发布版本。禁止提供任何"编辑已发布版本/历史 CaseResult"的接口。

### 2.2 统计口径唯一
通过率、均分、加权分、幻觉率、P95、A/B 检验的**唯一实现是 `metrics.py`**。报告、API、未来前端一律调用它。发现第二份同口径计算代码 = 必须重构合并的缺陷。
- 分数统一 0-5 正向口径（hallucination 分越高 = 幻觉越少）；`-1` 表示评分异常（Judge 解析失败），聚合时必须排除且单独计数，不得混入均值。

### 2.3 Agent 输出契约
所有 Agent 返回 `AgentOutput(output, intermediate, token_usage, latency_ms, error)`。`intermediate` 是归因引擎的数据源，格式约定：
```json
[{"type":"retrieval","query":"...","docs":[{"title":"...","score":0,"excerpt":"..."}]},
 {"type":"tool_call","name":"sql_query","args":{},"ok":true,"result":"..."}]
```
新增 Agent 类型必须产出兼容轨迹；归因层按 `type` 分派，缺轨迹的层自动跳过，不得报错。

### 2.4 断点续跑协议
`CaseResult.stage ∈ {pending, executed, judged}`。流水线每个阶段开始前先查 stage 跳过已完成部分；重跑同一阶段必须**先删旧产物再写**（评分删 `DimensionScore`，归因删 `AttributionFinding`），禁止 append 造成重复。改流水线时不得破坏该语义。

### 2.5 Trace 降级
`integrations/tracing.py`：Langfuse 可用则上报，否则本地 JSON 落盘。**上报失败绝不能影响评测主流程**（一律 try/except 吞掉并继续）。

### 2.6 密钥安全
- 密钥只存在于 `backend/.env`（已 gitignore）。代码、日志、报告、API 响应中**永不**出现明文密钥；对外回显必须脱敏（参考 `api/system.py` 的 `mask`）。
- 任何情况下不得提交 `.env`、不得把密钥写入测试或文档。

### 2.7 时间与时区
数据库时间一律 UTC（`models/base.utcnow`）。展示层才转本地时间。

## 3. 编码规范（可读性优先）

- **语言**：代码、注释、文档统一中文；标识符英文。
- **命名**：模块/函数 `snake_case`，类 `PascalCase`，常量 `UPPER_SNAKE`；名字表达意图，禁止单字母（循环计数除外）与无意义缩写。
- **类型注解**：公开函数必须有参数与返回类型注解（`from __future__ import annotations`）。
- **docstring**：每个模块头部一句话职责；公开函数写「做什么 + 关键约束」。**注释只写代码看不出来的约束与原因**（为什么这么写/坑在哪），不复述代码在干什么，更不写"本次修改说明"。
- **函数长度**：一个函数只做一件事；超过 ~60 行或出现 3 层以上嵌套时必须拆分。
- **异常**：预期错误显式捕获并给出业务语义的错误信息；顶层兜底 `except Exception` 必须记录日志/落库而不是静默吞掉；禁止裸 `except:`。
- **魔法值**：进 `config.py`（可配）或模块级常量（领域规则），禁止行内裸数字/字符串。
- **JSON 字段**：DB 中的 JSON 一律 `ensure_ascii=False`；读取用 `_j()` 风格的容错解析（`pipeline._j`），坏数据回落默认值而不是抛异常。
- **SQL**：只经 SQLAlchemy；面向用户的 SQL 工具只读（`tools/builtin.py` 的关键字黑名单不可移除）。
- **文件**：新文件先想清楚它属于 §1 表格哪一层、职责一句话能否说清；说不清就别建。

## 4. 高可用要求（所有改动的默认门槛）

1. **幂等**：任何可重试的操作（导入、发布、retry run、报告生成）重复执行结果一致。bootstrap 是幂等模板（存在即跳过）。
2. **超时与重试**：所有外部调用（LLM、HTTP、子进程）必须有超时（LLM/HTTP 默认走 `settings`，CLI 适配器自带 timeout）与有限重试；重试次数用 `JUDGE_MAX_RETRIES` 风格的配置。
3. **失败隔离**：单样本失败不得中断整批——Agent 异常落 `CaseResult.error` 继续；Judge 解析失败重试后记 `-1` 分继续。
4. **降级路径**：移除任何外部依赖（Langfuse、embedding、FAISS 替代品）后系统必须仍能完整跑通（当前：本地 Trace + BM25 + Jaccard 去重就是降级实现，不得删除）。
5. **并发**：并发度一律 `asyncio.Semaphore` 受控（执行/评分分别限流），禁止无界 gather；长任务可取消（`cancel_run`）。
6. **资源释放**：HTTP 客户端实现 `aclose()` 并在流水线结束时调用；子进程超时必须 kill。
7. **Windows 兼容**：路径用 `pathlib`；文件名生成必须清洗非法字符（`<>:"/\|?*`，见 `report.py`）；子进程经 `shutil.which` 解析（npm shim 是 .cmd）。
8. **数据库**：写操作及时 `commit`；流水线长事务内不要持有未提交的大批量变更；SQLite 下遵守现有 WAL/外键 pragma 设置。

## 5. 测试与验证

- **单测离线原则**：`backend/tests/` 不得调用真实 LLM（不耗配额、不依赖网络）。新增引擎逻辑必须配离线单测（现有 15 项是模板：rubrics/metrics/quality/attribution/judge 解析/BM25）。
- 统计函数的数值必须对齐已知分布表值（t 分布表等）后才能合入。
- 跑法：`cd backend && .venv\Scripts\python -m pytest tests -q`，**全绿是任何改动提交的前提**。
- 真实评测属于集成验证：用控制台或 API 显式发起，先小数据集（≤3 样本）验证链路，再上全量。
- 改动涉及 API 时用 `/api/system/health` + 对应端点做冒烟。

## 6. 禁止清单（违反即返工）

1. ❌ 提交 `.env`、`.venv/`、`backend/data/`、任何密钥或用户数据
2. ❌ 在 `metrics.py` 之外重复实现统计口径
3. ❌ 绕过 `rubrics.py` 硬编码评分标准；删除或绕过内置五维度的 Rubric
4. ❌ 修改已发布版本快照或历史评测结果（`CaseResult`/`DimensionScore` 只能由流水线写入）
5. ❌ `api/` 层写业务计算或直接调 LLM
6. ❌ 用同步阻塞调用（requests、time.sleep）阻塞事件循环
7. ❌ 引入重型依赖（celery/scipy/faiss 等）不写理由；当前"零重型依赖"是有意取舍
8. ❌ 在 Jinja 模板里写 Python 表达式推导式（渲染层只消费预计算数据）
9. ❌ 删除降级路径、删除工具只读防护、删除注入模式库条目
10. ❌ 跳过测试提交；`git push` 未经用户明确要求不执行

## 7. Git 与交付

- Commit message：`类型: 中文描述`（feat/fix/refactor/docs/test/chore），正文写清动机与影响面（参考仓库首个 commit）。
- 一次 commit 一件事；不把无关改动混入。
- 提交前自检：`pytest` 全绿、`git status` 无意外文件、`git diff` 中无密钥与调试输出（print/临时日志）。
- 需要新增依赖时：在 commit/PR 说明里写明用途与为什么现有依赖不够。

## 8. 常见任务正确姿势（速查）

- **调 Rubric 权重/文案** → 只改 `rubrics.py` 的 dict；跑 `pytest`；无需迁移（Dimension 启动时幂等种子，改文案需删维度行或手动 UPDATE——注意历史 run 的报告不回改）。
- **加归因规则** → `engine.py` 加检测函数 + `SUGGESTIONS`/`SEVERITY_BY_CODE` 补映射 + 单测覆盖触发与不触发两面。
- **加评测维度** → 优先运行时 API（`POST /api/dimensions`）；内置维度才动 `rubrics.py`。
- **接入新的外部 Agent** → 判断 HTTP 还是 CLI → `external_http.py`/`external_cli.py` 已覆盖通用场景，通常只需注册 Agent + 配置；只有新协议才写新适配器，且必须产出 `AgentOutput`。
- **排查评测失败** → 看 `run.error` → `backend/data/traces/<run_id>/` 本地 trace → 失败样本的 `DimensionScore.error` 与 `AttributionFinding.evidence`。
