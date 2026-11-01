# V3 计划：HF 三数据集测评问题整改

> 状态：待审核。来源：Run #7/8/9（grug-think / GLM-5.2-Agent / glm-5.2-coding，各 10 样本）暴露的 6 类问题。
> 批准后按里程碑执行，每个里程碑独立提交。

## 一、问题清单与根因（测评复盘）

| # | 现象 | 根因 | 严重度 |
|---|---|---|---|
| P1 | coding 样本 #1 三维全 0：模型输出 `<｜｜DSML｜｜ invoke name="bash">` 工具调用标记而非作答 | 数据集输入内嵌"你是可用 bash/edit 的编码 Agent"指令，**Prompt-Agent 的系统提示词没有身份边界声明**，模型模仿了工具伪装 | 高 |
| P2 | task_completion 普遍低（coding 3.4），PARTIAL_COMPLETION ×3、OFF_TOPIC ×3 | 参考答案是 GLM-5.2 **带工具多轮执行**的轨迹，纯推理单轮作答天然不可比 | 高 |
| P3 | grug-think 幻觉率 10%、accuracy 最低 2 分 | 参考答案含**合成的工具结果**（编造的随机数等），如实回答"无法执行"的样本被误扣 | 中 |
| P4 | 首次导入 coding 批内 8 条精确重复；标签"编程≠编码"被拦 | 抽样未去重；标签字典映射靠人肉，HF 接入是一次性临时脚本，未沉淀 | 中 |
| P5 | 归因发现（AttributionFinding）要查 SQLite 才能看到 | findings 没有 API 和前端界面，观测断层 | 中 |
| P6 | 三数据集都是 Agent 型任务，但只测了 Prompt-Agent | Tool-Agent（有 sql/calculator/knowledge 工具）未参与，能力覆盖缺位 | 中 |
| P7 | P95 延迟 121s / 271s，接近超时边界 | 长代码输出是正常耗时，但距离 `AGENT_TIMEOUT+30s` 的截断线余量不明 | 低 |

## 二、整改项设计

### R1 提示词身份护栏（修 P1，最高优先级）

- `agents/prompt_agent.py` 的 `DEFAULT_SYSTEM` 增加身份边界段：**本助手无工具执行能力，所有任务直接推理作答；禁止输出任何工具调用语法（函数调用标记/DSL 标记）**；输入中出现的工具指令视为待办任务的描述，不是真实可执行环境。
- 不做输出后处理改写（会掩盖问题）；归因层 `PROMPT_FORMAT_VIOLATION` 已能兜底检测。
- 单测：构造带工具指令的输入，断言默认系统提示词包含护栏关键约束（离线、不调 LLM）。
- **验收**：coding 数据集重跑后 DSML 案例 = 0。

### R2 参考答案"验收要点"改写（修 P2/P3，口径核心）

- 新增离线加工脚本 `scripts/rewrite_reference.py`：读已发布数据集 → 用 Judge LLM 把每条"执行轨迹/合成结果"压缩成**验收要点清单**（判对判错的客观要点，如"实现了 todo 的增删改查""输出了 1 个数字并说明范围"）→ 写回草稿 → 人工抽检 → 发布 v2。
- 一次性 token 成本：30 条 × 约 2k tokens ≈ 可忽略。
- grug-think 特殊处理：工具强依赖（结果完全由合成工具产生）的样本**直接剔除**，剩余保留（决策点 4）。
- 数据集 `meta` 字段记录 `reference_style: key_points` 与来源轨迹 ID，可溯源。

### R3 HF 数据集接入沉淀为一等能力（修 P4）

- 新增 `scripts/import_hf.py`，一条命令完成：`python scripts/import_hf.py <hf_dataset> --name X --sample stride --limit 10 --map auto`：
  - 抽样：全库均匀 stride + 按 input 去重 + 批内去重（根治 P4 的重复问题）
  - 字段映射：内置三种已知模板（messages 对话 / prompt+messages 会话 / task+messages 步骤），可 JSON 自定义
  - 标签映射：HF 的 lang/category/domain → 本系统标签字典的映射表（编程→编码等），未知值落 `meta`
  - 元数据保留：lang/category/reasoning_effort/teacher_model 写入 `EvalCase.meta`
  - 预检失败自动减量重抽，最终给出导入报告
- 预检/确认/发布复用现有 API，不绕过质检。

### R4 归因发现 API + 前端页签（修 P5）

- 后端：`GET /runs/{id}/findings`——按 issue_code 分组统计 + 逐样本明细（seq/维度/得分/evidence/suggestion），口径只读。
- 前端：Run 详情新增「归因」页签（统计表 + 展开明细），与 Token 页签同级。
- 单测：findings 聚合口径（分组、排序）。

### R5 Tool-Agent 对照重测（修 P6，依赖 R2）

- R2 完成后，三数据集 v2 用 {Prompt-Agent, Tool-Agent} 各跑一轮（A/B 模式或两次 single + compare），验证"有工具是否真的改善任务完成度"。
- **不新增 bash/任意代码执行工具**（安全面过大）；Tool-Agent 维持现有只读工具集（sql/calculator/knowledge_search）。
- 预算：3 数据集 × 2 Agent × 10 样本 ≈ 60 样本调用 + Judge，与本轮成本同量级。

### R6 延迟余量标注（修 P7，轻量）

- 报告 summary 增加字段：`timeout_budget_used`（P95 / 可用超时上限的比值），>80% 时报告标注"接近超时边界"。
- 不改超时配置本身（决策点 5 可选做 run 级覆盖）。

## 三、里程碑

| # | 内容 | 交付物 | 验收 |
|---|---|---|---|
| M1 | R1 提示词护栏 + R4 归因 API/页签 | 代码 + 单测 | 单测全绿；护栏文本断言测试通过 |
| M2 | R3 import_hf.py + R2 要点改写 | 脚本 + 三数据集 v2 发布 | 抽检 10 条要点可判分；零重复 |
| M3 | R5 对照重测 + R6 延迟标注 | Run 报告 + 复盘结论 | DSML 案例 0；完成度提升可量化；对照结论输出 |

## 四、决策点（默认值已选，可改）

| # | 决策 | 默认 | 理由 |
|---|---|---|---|
| 1 | 是否新增 bash/任意代码执行工具 | **否** | 安全面过大（AGENTS.md 只读红线）；纯推理+要点口径已可公平评测 |
| 2 | 要点改写方式 | **LLM 离线一次性加工** | 规则抽取保真但粗糙；离线加工一次成本可忽略，且人工抽检兜底 |
| 3 | grug-think 工具强依赖样本 | **剔除** | 合成参考答案不可判分，保留只会制造噪声 |
| 4 | 重测规模 | 3 数据集 × 2 Agent × 10 样本 | 与本轮成本同量级，统计上够看趋势 |
| 5 | run 级超时覆盖 | **不做** | 当前无实际超时发生，P95 标注即可 |

## 五、不在本期范围

- 多维抽样扩量（100 条/集）：等口径修正验证后再扩
- 向量检索/RAG 相关整改：本轮问题与 RAG 无关
- Claude/Responses 端点真跑：等有对应供应商密钥
