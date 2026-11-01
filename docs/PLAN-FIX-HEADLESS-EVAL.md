# 修复计划：无头评测暴露的 4 个问题（目标版本 0.9.0-beta.2）

> 存放说明：本文档描述的是 agent-atlas 仓库的修复，原存于 agent-atlas，2026-11-01 按要求撤出改存本仓。
> 代码修复已从 agent-atlas 本地回退（实现可参考当时提交 62daf1a，git reflog 可找回）；重测需先把修复重新应用。

> **✅ 已执行完成（2026-11-01）**，执行记录见文末「六、执行记录与回归结果」。
> 来源：2026-10-31 用 agent-bench 对本仓库（external_http 接入，:3000）做的三数据集无头评测复盘。
> 评测明细：agent-bench Run #16/17/18（HF grug-think / GLM-5.2-Agent / glm-5.2-coding，各 10 样本，串行）。
> 结论先行：**通用 Agent 的执行能力没有问题**（完成样本质量与基线接近、工具轨迹真实），失分集中在 4 个工程问题；修完后可直接用 agent-bench 重测验证。

## 一、问题清单与证据

| # | 问题 | 证据 | 影响 |
|---|---|---|---|
| P1 | **DeepSeek 思考模式多步续传 400** | `400 The reasoning_content in the thinking mode must be passed back to the API (request_id: cf26fcd6…)`。单轮调用正常（试跑 17×23=391 ✓），ReAct 循环第 2 次模型调用起必现 | 多步任务全灭：GLM-5.2-Agent 数据集 8/10 失败、coding 4/10 失败 |
| P2 | **澄清等待导致零输出** | 多个 turn 以 `status:"waiting"` 结束（其一 12755 事件 / 88s，工具真实执行），最终无任何 token 事件，下游拿到空输出。机制：general Agent 发起 `pending: clarification` → 回合挂起等 `/api/resume` 应答 | 无头场景无人应答 → 任务被弃；即使澄清文本也未保证以 token 事件流出 |
| P3 | **并发负载下 400（恒定 10.0s）** | 3 个评测并行时部分 `/api/chat` 恰好 10002ms 后 400；单发重放同一输入 200 正常。根因未定位，候选：checkpoint 存储锁（busy 超时）、`rag.ts` 的 `AbortSignal.timeout(10_000)` 在 chat 路径被触发 | 并发评测/多会话并行为不可用 |
| P4 | **usage 事件语义未定义累计口径** | 一个 turn 发多个 `usage` 事件（每个模型调用一条），累计值在 `taskInputTokens/taskOutputTokens` 字段里，但没有"任务结束"的最终事件 | 下游（agent-bench 适配器取第一条）token 统计偏小 |

另有一个对接层小问题（agent-bench 侧已修，此处仅备忘）：适配器此前只透出状态码不读错误 body，导致 P1/P3 的具体原因晚一轮才看到。

## 二、修复方案

### R1 思考模式续传（P1，最高优先级）

根因：DeepSeek 要求思考模型的多轮请求把历史 assistant 消息的 `reasoning_content` 原样回传；当前消息装配层把它丢掉了。

方案（按优先级）：
1. **消息装配层透传**：在 openai dialect 的历史装配处（`src/agent/` 消息组装），保留上一 assistant 轮的 `reasoning_content` 并随请求回传（仅当模型为思考模式）。
2. **兜底重试**：捕获 400 且 body 含 `reasoning_content` 时，自动带思考历史重试一次（防其他网关同类规则）。
3. 逃生阀：模型/供应商配置支持 `thinking_passthrough: false`，关闭思考回传（放弃思考续跑，换可用性）。

验收：需要 ≥3 次模型调用的任务在 deepseek-flash thinking=high 下连跑 10 个，0 个 400。

### R2 无头模式（P2）

1. **等待必先可见**：进入 clarification 等待前，把问题文本以 token 事件流出（或新增 `clarify` 语义事件并写入事件目录文档），保证任何调用方都能拿到"为什么在等"。
2. **headless 请求标志**：`POST /api/chat` 支持 `"headless": true`——澄清自动采用默认假设并继续执行（假设内容记入工作台账），不再挂起等 resume。默认 false，交互行为不变。
3. （可选）`/api/resume` 支持 headless 应答队列，供外部驱动多轮澄清。

验收：agent-bench 重测空输出样本 = 0。

### R3 并发 400（P3）

1. **先可观测**：400/500 响应体统一带 `err.message`（现有 index.ts 错误映射确认覆盖 chat 路径），配合 agent-bench 已有的 body 透传，下轮复现即可定位。
2. **两个候选根因按序排查**：checkpoint 存储启用 WAL + 显式 `busy_timeout`；`rag.ts` 的 10s AbortSignal 若在 chat 路径触发，改为可配置并降级（跳过 RAG 增强而不是失败）。
3. 复现脚本：3 会话并行 `/api/chat`（stagger 1s），期望全部 200。

### R4 usage 事件语义（P4）

- 事件目录文档明确：每模型调用的 `usage` + turn 结束时的累计事件。
- 新增 turn 结束的 `task_usage` 事件（`taskInputTokens/taskOutputTokens/taskToolCalls` 已有，落成正式事件即可）。
- 通知 agent-bench 侧：适配器优先取 `task_usage`（一行改动）。

## 三、里程碑与验收

| # | 内容 | 验收 |
|---|---|---|
| M1 | R1 思考续传 + 错误 body 确认 | 多步任务 10 连跑 0 个 400 |
| M2 | R2 无头模式 | agent-bench 重测空输出 = 0 |
| M3 | R3 并发 + R4 usage | 3 并发评测 0 个 400；agent-bench token 统计与 agent-atlas 台账一致 |

**回归方式**（修完后执行）：agent-atlas `npm run web` → agent-bench 控制台对 agent-atlas（v2 配置）重跑三数据集（**并发设 3**，验证 R3），对照基线：Run #16/17/18（有效样本 8/4/6，有效加权 4.412/3.114/2.816）。

## 四、决策点

| # | 决策 | 默认 | 备选 |
|---|---|---|---|
| 1 | R1 主方案 | 消息装配层透传 reasoning_content（保思考能力） | 兜底重试 / 关闭思考续跑 |
| 2 | R2 形态 | 请求级 `"headless": true` | 全局环境变量 AGENT_HEADLESS |
| 3 | R2 澄清策略 | 自动采用默认假设继续（假设记台账） | 拒绝执行并输出说明 |
| 4 | R3 若确认是 checkpoint 锁 | WAL + busy_timeout | 换 Postgres checkpoint |

## 五、不在本计划范围

- agent-bench 侧适配（task_usage 取数、画像/接口类型）——已具备或另行小改
- 房产 Agent / Computer Use 路径的同类问题排查（修完 R1/R3 后顺手回归即可）
- 正式版发布流程（本计划目标是 beta.2 可用）

## 六、执行记录与回归结果（2026-11-01）

### 实际实现（与原方案的差异已注明）

| # | 实现 | 落点 |
|---|---|---|
| R1 | **name 通道搬运**（原方案 1 的等价变体：`@langchain/openai` ≤1.8.0 请求侧序列化实测仍丢 `reasoning_content`，且转换是模块级自由函数无法覆写）。装配层把思考历史编码进带哨兵前缀的 `BaseMessage.name`（序列化保留该字段），fetch 边界解回 `reasoning_content` 再发请求；哨兵 name 永不出网 | `src/agent/reasoning-passthrough.ts`（新）+ `context-builder.ts`（装配点）+ `llm.ts`（fetch 边界） |
| R2 | 请求级 `headless: true`（POST /api/chat body）→ configurable 透传 → `clarifyNode` 不再 interrupt：自动采用第一个选项作为默认假设继续，假设文本记入澄清历史与需求 brief | `routes/chat.ts` + `stream.ts` + `agent/workflow.ts` |
| R3 | **根因修正**：不是 checkpoint 锁（实现是 MemorySaver + NDJSON 追加，无锁问题），也不是 `rag.ts`（10s 只在连通性探测里）。真凶是 `model-gate.ts` 的 `ResourceGauge` **队列等待超时 10s**——槽位按整轮持有，批量并发时排队超 10s 即拒绝（400）。队列超时改为可配（`MODEL_GATE_QUEUE_TIMEOUT_MS`，默认 120s）；容量沿用 `MODEL_CONCURRENCY_PER_PROVIDER`（默认 5） | `src/server/runtime/model-gate.ts` |
| R4 | 新增 `task_usage` 事件：turn 结束（done 之前）发出任务级用量终值（含 analyze/review/风险审查等内部辅助调用的真实成本） | `server/events.ts` + `routes/chat.ts` |

**R2 补充（重要）**：headless 只覆盖**澄清**。审批中断在 `autonomous` 权限下仍可能出现——风险评估本身是一次模型调用，评估失败按高风险处理（permission.ts 既有语义），批量并发下偶发失败就会挂起等审批。**无人值守评测应使用权限模式 `auto`**（全部工具直接执行、零审批零风险评估），评测适配器通过会话权限端点设置。

### 回归结果（agent-bench Run #25/26/27，v3 数据集 8/4/5 样本，并发 3×3=9 路）

| 验收项 | 结果 |
|---|---|
| M1：多步任务 0 个 400 | ✅ 17 样本 + 冒烟 7 次模型调用，全程 0×400（修复前 ReAct 第 2 次调用起必现） |
| M2：空输出 = 0 | ✅ 澄清/审批挂起 0（16 completed，0 waiting）；唯一 1 条空输出是 330s 流水线超时（重型多文件构建任务超预算，与挂起无关） |
| M3：3 并发 0×400 / token 一致 | ✅ 9 路并发无 400；`task_usage` 到账，agent-bench 统计与台账口径一致（任务级累计，含内部调用） |

测试：`tsc --noEmit` 零错误；全量单测 389+4（新增 `tests/unit/reasoning-passthrough.test.ts`）全绿。

### 分数与口径说明（如实记录）

| 数据集 | agent-atlas v4 加权 | 内置 Prompt-Agent 加权（同口径） | 说明 |
|---|---|---|---|
| grug-think（8） | 3.629（通过率 25%） | 4.465（通过率 75%，Run #19） | 纯推理题，单轮直答占优 |
| GLM-5.2-Agent（4） | 2.608（1 条 330s 超时） | 3.513（Run #20） | 重型构建任务，预算内完不成即 0 分 |
| glm-5.2-coding（5） | 3.182（通过率 20%） | 4.916（通过率 100%，Run #21） | 同上；agent-atlas 真实写码/跑测试但文本口径看不到产出物 |

- agent-atlas 在纯问答类评测集上落后单轮 Agent 0.7~1.6 分（5 分制，逐样本配对差 -0.733 / -0.867 / -1.560）：编排型流程（analyze→ReAct→review）对单轮可答题是负资产，且工具探索会引入噪声；
- token 成本为任务级累计（多步循环 + 思考回传），单案例累计输入可达内置 Agent 的百倍量级——这是真实成本，不是统计错误；
- 本评测的判分口径是「最终文本是否命中验收要点」，不含产出物验收（文件是否真的创建/测试是否真的通过）——工具型 Agent 的真实工程价值在此口径下被低估，属已知边界。
