# Agent-Bench V2 计划：React 前端重构 + Token 统计 + 评测集维护升级

> 状态：待审核。批准后按里程碑执行，每个里程碑收尾跑全量离线测试 + 浏览器冒烟。

## 一、目标与范围

1. **前端重构**：把手写单文件 `index.html` 控制台重构为 React + TypeScript + Vite + Ant Design 的现代化前端工程，功能对齐不丢失。
2. **Token 统计**：补全 token 采集缺口（内置 prompt/rag Agent、Judge），提供单次评测的逐样本 token 明细与全局 token 聚合统计。
3. **评测集维护与升级**：补齐数据集日常维护界面（样本编辑），新增版本 diff 与"升级验证"闭环（新版数据集发布后一键复评对照）。

不在本期范围：多用户/角色权限体系、移动端适配、报告模板更换。

## 二、前端重构方案

### 技术选型（主版本固定，minor 以安装时最新稳定为准）

| 依赖 | 用途 |
|---|---|
| React 19 + react-dom | UI 框架 |
| TypeScript 5 | 类型约束（API 响应全部建类型） |
| Vite 7 | 构建/开发服务器（dev 时 proxy `/api` → `127.0.0.1:8000`） |
| Ant Design 5 | 组件库（Table/Modal/message/Form/布局）——原生 alert/dialog 全部消灭 |
| ECharts 6 | token 趋势/分布图（antd 官方 charts 体积大，echarts 按需引入） |
| React Router 7 | 页面路由（六页签 → 六路由 + 详情子路由） |
| TanStack Query 5 | 数据请求缓存 + 评测任务状态轮询（替代手写 setInterval 刷新） |

### 工程结构

```
frontend/
├── src/
│   ├── api/          # 请求层：fetch 封装 + Bearer token + 401 拦截 → 登录弹窗
│   ├── types/        # 后端响应的 TS 类型定义（与 models 一一对应）
│   ├── pages/        # dashboard / agents / datasets / runs / runDetail / stats / governance / system
│   ├── components/   # 通用组件（TokenTable、VersionDiff、StatusTag…）
│   └── App.tsx       # 布局（antd Layout 侧边栏）+ 路由
├── vite.config.ts    # build.outDir = ../backend/app/static/dist
└── package.json
```

### 与后端的集成

- **构建产物**：`npm run build` 输出到 `backend/app/static/dist/`，FastAPI 改为挂载该目录并回退 `index.html`（SPA 路由）。开发时 `npm run dev`（Vite :5173 + proxy），互不干扰。
- **鉴权迁移**：沿用 `localStorage ab_token`；请求层统一拦截 401，弹 antd Modal 输入 token 后重试，逻辑与现在一致。
- **安全不变量**（写入 AGENTS.md）：React 默认转义兜底，禁止对不可信内容用 `dangerouslySetInnerHTML`；token 不打印到控制台日志；CORS 保持默认关闭（同源托管，无需开放）。
- **旧 index.html**：构建成功后直接替换（git 历史可回溯），不保留双入口。

### 功能对齐清单（验收用，缺一即不合并）

现有 6 页签全部能力：仪表盘（健康状态/最近任务）、Agent 管理（注册/试跑/列表）、评测集（导入预检→确认/发布/质检/查看/导出）、评测任务（发起含 A/B、取消/重跑、详情、报告 HTML 查看）、数据治理（标签字典）、系统设置；以及 toast 提示、鉴权弹窗。

## 三、Token 统计

### 现状与缺口

| 采集点 | 现状 | 动作 |
|---|---|---|
| tool 内置 Agent | ✅ 精确 token（langchain usage_metadata） | 无 |
| external_http（learn-agent） | ✅ 精确 token（SSE usage 事件） | 无 |
| prompt/rag 内置 Agent | ⚠️ 仅字符数近似 | 去掉 `StrOutputParser`，直接 `ainvoke` 拿 `AIMessage.usage_metadata`（精确 token），字符数保留为降级值 |
| Judge（LLM 阅卷） | ❌ 未采集 | `ainvoke` 响应的 usage_metadata 存入新列 `CaseResult.judge_usage` |
| external_cli（dsh） | ❌ CLI 本身不输出用量 | 不硬造，标记 source=none，UI 显示"未上报" |

### 数据与迁移

- `CaseResult` 新增 `judge_usage: Text = "{}"`；启动时幂等轻量迁移（`ALTER TABLE ... ADD COLUMN`，封装在 `core/db.py`，SQLite/MySQL 双兼容）。
- 用量统一口径（存 JSON）：`{"input_tokens": int, "output_tokens": int, "total_tokens": int, "source": "api" | "approx_chars" | "none"}`。
- **聚合口径集中**：token 汇总/聚合函数只写在 `metrics.py`（遵守 AGENTS.md 单一口径原则）。

### API（新增 2 个，增强 1 个）

- `GET /api/runs/{id}/tokens`：逐样本表（agent 输入/输出/合计 + judge 输入/输出/合计）+ 汇总，供 Run 详情页签。
- `GET /api/stats/tokens`：全局聚合——按 run、按 Agent、按日期三视图（从 CaseResult 全表聚合，量小直查即可，不做预聚合表）。
- `GET /api/runs/{id}` 响应增加 `token_summary` 字段（总数 + agent/judge 分项），列表页直接展示。

### 前端

- **Run 详情新增「Token 消耗」页签**：汇总卡片（Agent 侧 / Judge 侧 / 合计，标注精度来源）+ 逐样本表格 + 输入/输出分布图（ECharts）。
- **新增「统计」页（侧边栏第 7 项）**：token 按日趋势折线、Agent 维度消耗排行、最近 run token 卡片；无数据时给引导空态。

## 四、评测集维护与升级

### 1. 样本维护界面（后端 API 已有 POST/PUT/DELETE `/datasets/{id}/cases`，纯前端补齐）

- 数据集详情页：样本表格支持行内新增/编辑/删除（antd Drawer 表单：输入、期望输出、难度、标签四类受控输入），仅对**草稿**生效（发布版本只读，不可变原则不变）。
- 编辑动作后自动触发轻量质检提示（调现有 quality-check，仅展示提醒级问题，不阻断输入）。

### 2. 版本 diff（后端新增）

- `GET /api/datasets/{id}/versions/{a_id}/diff/{b_id}`：以 `input` 文本为对齐键，输出新增/删除/修改三组样本明细。
- `GET /api/datasets/{id}/draft/diff`：草稿相对最近已发布版本的 diff——发布前预览"这次升级改了什么"。
- 前端：发布确认弹窗内嵌 diff 摘要（+N 新增 / -N 删除 / ~N 修改，可展开明细）；版本列表任意两版本可发起 diff 视图。

### 3. 升级验证闭环（后端新增 + 前端串起来）

- `POST /api/runs/{id}/replay`：以既有 run 为模板（同 Agent 版本、同并发），换用指定的新数据集版本创建新 run。场景：v1 上跑过评测 → 数据集升级到 v2 → 一键复评。
- **双 run 对比视图**：Run 详情页"与历史 run 对比"，选一个同 Agent 的旧 run，按样本（对齐键 input）逐题对照两个版本的得分变化，配对显著性复用 `metrics.ab_compare`（口径不变，仅对齐逻辑从 agent 配对换到 run 配对，函数签名保持兼容）。

## 五、里程碑

| # | 内容 | 交付物 |
|---|---|---|
| M1 | 前端脚手架 + 六页签功能对齐迁移 + 鉴权/toast | 新控制台替换旧 index.html，冒烟通过 |
| M2 | Token 采集补全（prompt/rag/judge）+ 迁移 + 聚合 API | pytest 新增用例全绿 |
| M3 | Token 前端（Run 详情页签 + 统计页） | 浏览器实测截图 |
| M4 | 数据集样本维护 UI + 版本 diff API | diff 单测 + 界面 |
| M5 | 升级验证（replay API + 双 run 对比视图） | 端到端演示（小数据集真跑一次） |
| M6 | 收尾：README/AGENTS.md 增补前端规范、全量回归、构建冒烟 | 提交推送（经确认） |

每个里程碑独立提交，不合并不满足"功能对齐清单"的 PR。

## 六、测试与验收

- **后端离线单测**（不耗 LLM 配额）：usage 解析与口径归一、token 聚合（含 source=approx/none 混合）、judge_usage 迁移幂等、diff 对齐算法（新增/删除/修改/乱序）、replay 配置复制。
- **前端**：`tsc && vite build` 零错误为门槛；六页面 Playwright 冒烟（登录流程、发起评测、token 页签、diff 视图）。
- **真跑验收**（集成，小样本 ≤3）：一次含 Judge 的评测在 Run 详情能看到 agent+judge 两列 token；一次数据集 v1→v2 升级 + replay 对照。

## 七、决策点（默认值已选，审核时可改）

| # | 决策 | 默认 | 理由 |
|---|---|---|---|
| 1 | 构建产物 dist 是否提交 git | **提交** | 部署机只需 Python 环境即可跑（与现状一致）；代价是每次前端改动 diff 变大 |
| 2 | UI 组件库 | **Ant Design 5** | 你点名 antd；企业后台事实标准，Table/Form/Modal 覆盖本系统全部场景 |
| 3 | 旧 index.html 处置 | **直接替换** | git 历史可回溯，双入口徒增维护面 |
| 4 | Node 版本要求 | **≥ 20** | Vite 7 最低要求；本机若低于此先升级 Node |
| 5 | 统计页数据规模 | 直查聚合，不建预聚合表 | 当前量级（个位数 run）足够；数据量上万再优化 |
