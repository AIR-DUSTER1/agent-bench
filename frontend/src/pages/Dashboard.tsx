import { Card, Col, Progress, Row, Statistic, Table, Typography } from 'antd'
import type { TableColumnsType } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '../api'
import type { EvalRun, Health, StatsEntry, TokenStats } from '../types'
import { StatusTag, fmtTime } from '../format'
import Chart from '../components/Chart'

// 仪表盘行：在 EvalRun 上拼装该 run 的 token 汇总（__ 前缀表示前端拼装、非后端字段）
type RunRow = EvalRun & { __tokens?: StatsEntry }

const runsColumns: TableColumnsType<RunRow> = [
  {
    title: 'ID', dataIndex: 'id', width: 60,
    render: (id: number) => <Link to={`/runs/${id}`}>#{id}</Link>,
  },
  {
    title: '名称', dataIndex: 'name',
    render: (name: string, r) => (
      <>
        <Link to={`/runs/${r.id}`}>{name}</Link>
        <div style={{ color: '#64748b', fontSize: 12 }}>
          {r.sides.map((s) => `${s.agent_name}/${s.version}`).join(' vs ')}
        </div>
      </>
    ),
  },
  { title: '模式', dataIndex: 'mode', width: 90, render: (m: string) => m.toUpperCase() },
  { title: '状态', dataIndex: 'status', width: 110, render: (s: string) => <StatusTag status={s} /> },
  {
    title: '进度', key: 'progress', width: 160,
    render: (_, r) => (
      <>
        {r.progress}/{r.total_cases}
        <Progress
          size="small"
          percent={r.total_cases ? Math.round((100 * r.progress) / r.total_cases) : 0}
        />
      </>
    ),
  },
  {
    title: 'token（被测/Judge）', key: 'tokens', width: 170,
    render: (_, r) => r.__tokens
      ? `${r.__tokens.agent.total_tokens.toLocaleString()} / ${r.__tokens.judge.total_tokens.toLocaleString()}`
      : '-',
  },
  { title: '创建时间', dataIndex: 'created_at', width: 150, render: (t: string) => fmtTime(t) },
]

const byRunColumns: TableColumnsType<StatsEntry> = [
  {
    title: '任务', key: 'run',
    render: (_, e) => (
      <>
        <Link to={`/runs/${e.run_id}`}>#{e.run_id} {e.name}</Link>
        <div style={{ color: '#64748b', fontSize: 12 }}>{fmtTime(e.created_at)}</div>
      </>
    ),
  },
  { title: '被测 ↑/↓', render: (_, e) => `${e.agent.input_tokens.toLocaleString()} / ${e.agent.output_tokens.toLocaleString()}` },
  { title: '被测合计', render: (_, e) => <Typography.Text strong>{e.agent.total_tokens.toLocaleString()}</Typography.Text> },
  { title: 'Judge 合计', render: (_, e) => e.judge.total_tokens.toLocaleString() },
]

const byAgentColumns: TableColumnsType<StatsEntry> = [
  { title: 'Agent / 版本', dataIndex: 'key', ellipsis: true },
  { title: '输入', render: (_, e) => e.agent.input_tokens.toLocaleString() },
  { title: '输出', render: (_, e) => e.agent.output_tokens.toLocaleString() },
  {
    title: '合计', render: (_, e) => <Typography.Text strong>{e.agent.total_tokens.toLocaleString()}</Typography.Text>,
    sorter: (a, b) => a.agent.total_tokens - b.agent.total_tokens,
    defaultSortOrder: 'descend',
  },
]

export default function Dashboard() {
  const { data: runs = [] } = useQuery({
    queryKey: ['runs'],
    queryFn: () => api.get<EvalRun[]>('/runs'),
    refetchInterval: 5000,
  })
  const { data: health } = useQuery({
    queryKey: ['health'],
    queryFn: () => api.get<Health>('/system/health'),
  })
  const { data: stats } = useQuery({
    queryKey: ['token-stats'],
    queryFn: () => api.get<TokenStats>('/stats/tokens'),
    refetchInterval: 30_000,
  })

  const done = runs.filter((r) => r.status === 'done')
  const active = runs.filter((r) => !['done', 'failed', 'cancelled', 'pending'].includes(r.status))

  // 把每run的 token 汇总挂到最近任务行上（key 前缀 __ 表示前端拼装字段）
  const tokenByRun = new Map((stats?.by_run ?? []).map((e) => [e.run_id, e]))
  const recentRuns: RunRow[] = [...runs].sort((a, b) => b.id - a.id).slice(0, 10)
    .map((r) => ({ ...r, __tokens: tokenByRun.get(r.id) }))

  const dates = stats?.by_date.map((e) => e.key ?? '') ?? []
  const lineOption = {
    tooltip: { trigger: 'axis' as const },
    legend: { bottom: 0 },
    grid: { top: 30, left: 60, right: 16 },
    xAxis: { type: 'category' as const, data: dates },
    yAxis: { type: 'value' as const, name: 'tokens' },
    series: [
      { name: '被测-输入', type: 'line' as const, smooth: true, data: stats?.by_date.map((e) => e.agent.input_tokens) ?? [] },
      { name: '被测-输出', type: 'line' as const, smooth: true, data: stats?.by_date.map((e) => e.agent.output_tokens) ?? [] },
      { name: 'Judge-输入', type: 'line' as const, smooth: true, lineStyle: { type: 'dashed' as const }, data: stats?.by_date.map((e) => e.judge.input_tokens) ?? [] },
      { name: 'Judge-输出', type: 'line' as const, smooth: true, lineStyle: { type: 'dashed' as const }, data: stats?.by_date.map((e) => e.judge.output_tokens) ?? [] },
    ],
  }

  return (
    <>
      <Row gutter={[12, 12]}>
        <Col span={4}><Card size="small"><Statistic title="评测任务" value={runs.length} /></Card></Col>
        <Col span={4}><Card size="small"><Statistic title="已完成" value={done.length} /></Card></Col>
        <Col span={4}><Card size="small"><Statistic title="运行中" value={active.length} /></Card></Col>
        <Col span={6}>
          <Card size="small">
            <Statistic title="被测累计 tokens" value={stats?.total.agent.total_tokens.toLocaleString() ?? '…'}
              suffix={<span style={{ fontSize: 12, color: '#64748b' }}>{stats ? `${stats.total.agent.calls} 次调用` : ''}</span>} />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic title="Judge 累计 tokens" value={stats?.total.judge.total_tokens.toLocaleString() ?? '…'}
              suffix={<span style={{ fontSize: 12, color: '#64748b' }}>{health ? `${health.llm_model}` : ''}</span>} />
          </Card>
        </Col>
      </Row>

      <Card size="small" title="最近评测任务" style={{ marginTop: 14 }}>
        <Table<RunRow>
          rowKey="id"
          size="small"
          columns={runsColumns}
          dataSource={recentRuns}
          pagination={false}
        />
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          共 {runs.length} 个任务；完整列表与操作见「评测任务」页
        </Typography.Text>
      </Card>

      <Row gutter={[12, 12]} style={{ marginTop: 14 }}>
        <Col span={14}>
          <Card size="small" title="每日消耗趋势">
            {dates.length ? <Chart option={lineOption} height={260} /> : <Typography.Text type="secondary">暂无数据</Typography.Text>}
          </Card>
        </Col>
        <Col span={10}>
          <Card size="small" title="Agent 消耗排行" styles={{ body: { paddingTop: 0 } }}>
            <Table<StatsEntry>
              rowKey={(e) => e.key ?? '?'}
              size="small"
              columns={byAgentColumns}
              dataSource={stats?.by_agent ?? []}
              pagination={false}
            />
          </Card>
        </Col>
      </Row>

      <Card size="small" title="按评测任务的 token 消耗" style={{ marginTop: 14 }}>
        <Table<StatsEntry>
          rowKey={(e) => String(e.run_id)}
          size="small"
          columns={byRunColumns}
          dataSource={stats?.by_run ?? []}
          pagination={{ pageSize: 8 }}
        />
      </Card>
    </>
  )
}
