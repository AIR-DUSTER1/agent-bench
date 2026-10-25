import { Alert, Card, Space, Spin, Table, Typography } from 'antd'
import type { TableColumnsType } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '../api'
import type { StatsEntry, TokenStats } from '../types'
import { fmtTime } from '../format'
import Chart from '../components/Chart'

export default function Stats() {
  const { data, isLoading } = useQuery({
    queryKey: ['token-stats'],
    queryFn: () => api.get<TokenStats>('/stats/tokens'),
  })
  if (isLoading || !data) return <Spin />

  const totalApi = data.total.agent.api_calls + data.total.judge.api_calls

  const agentColumns: TableColumnsType<StatsEntry> = [
    { title: 'Agent / 版本', dataIndex: 'key' },
    { title: '输入', render: (_, e) => e.agent.input_tokens.toLocaleString() },
    { title: '输出', render: (_, e) => e.agent.output_tokens.toLocaleString() },
    {
      title: '被测合计', render: (_, e) => (
        <Typography.Text strong>{e.agent.total_tokens.toLocaleString()}</Typography.Text>
      ),
      sorter: (a, b) => a.agent.total_tokens - b.agent.total_tokens,
      defaultSortOrder: 'descend',
    },
    { title: 'Judge 合计', render: (_, e) => e.judge.total_tokens.toLocaleString() },
    { title: '调用数', render: (_, e) => `${e.agent.calls + e.judge.calls}` },
  ]

  const runColumns: TableColumnsType<StatsEntry> = [
    {
      title: 'Run', key: 'run',
      render: (_, e) => (
        <>
          <Link to={`/runs/${e.run_id}`}>#{e.run_id} {e.name}</Link>
          <div style={{ color: '#64748b', fontSize: 12 }}>{fmtTime(e.created_at)}</div>
        </>
      ),
    },
    { title: '被测 ↑/↓', render: (_, e) => `${e.agent.input_tokens.toLocaleString()} / ${e.agent.output_tokens.toLocaleString()}` },
    { title: '被测合计', render: (_, e) => e.agent.total_tokens.toLocaleString() },
    { title: 'Judge 合计', render: (_, e) => e.judge.total_tokens.toLocaleString() },
  ]

  const dates = data.by_date.map((e) => e.key ?? '')
  const lineOption = {
    tooltip: { trigger: 'axis' as const },
    legend: {},
    xAxis: { type: 'category' as const, data: dates },
    yAxis: { type: 'value' as const, name: 'tokens' },
    series: [
      { name: '被测-输入', type: 'line' as const, smooth: true, data: data.by_date.map((e) => e.agent.input_tokens) },
      { name: '被测-输出', type: 'line' as const, smooth: true, data: data.by_date.map((e) => e.agent.output_tokens) },
      { name: 'Judge-输入', type: 'line' as const, smooth: true, lineStyle: { type: 'dashed' as const }, data: data.by_date.map((e) => e.judge.input_tokens) },
      { name: 'Judge-输出', type: 'line' as const, smooth: true, lineStyle: { type: 'dashed' as const }, data: data.by_date.map((e) => e.judge.output_tokens) },
    ],
  }

  return (
    <>
      <Space size="large" style={{ marginBottom: 14 }} wrap>
        <Card size="small" style={{ minWidth: 280 }}>
          <Typography.Text type="secondary">被测侧累计消耗</Typography.Text>
          <Typography.Title level={3} style={{ margin: 0 }}>
            {data.total.agent.total_tokens.toLocaleString()} tokens
          </Typography.Title>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            输入 {data.total.agent.input_tokens.toLocaleString()} · 输出 {data.total.agent.output_tokens.toLocaleString()} · {data.total.agent.calls} 次调用
          </Typography.Text>
        </Card>
        <Card size="small" style={{ minWidth: 280 }}>
          <Typography.Text type="secondary">Judge 侧累计消耗</Typography.Text>
          <Typography.Title level={3} style={{ margin: 0 }}>
            {data.total.judge.total_tokens.toLocaleString()} tokens
          </Typography.Title>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            输入 {data.total.judge.input_tokens.toLocaleString()} · 输出 {data.total.judge.output_tokens.toLocaleString()} · {data.total.judge.calls} 次调用
          </Typography.Text>
        </Card>
      </Space>

      {totalApi === 0 && (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 14 }}
          message="暂无精确 token 数据"
          description="历史数据早于采集功能。跑一次新评测（内置 Agent 或 external_http 型）即可看到统计。"
        />
      )}

      <Card size="small" title="每日消耗趋势" style={{ marginBottom: 14 }}>
        {dates.length ? <Chart option={lineOption} height={280} /> : <Typography.Text type="secondary">暂无数据</Typography.Text>}
      </Card>

      <Card size="small" title="Agent 消耗排行" style={{ marginBottom: 14 }}>
        <Table<StatsEntry> rowKey={(e) => e.key ?? '?'} size="small" columns={agentColumns} dataSource={data.by_agent} pagination={false} />
      </Card>

      <Card size="small" title="按评测任务">
        <Table<StatsEntry> rowKey={(e) => String(e.run_id)} size="small" columns={runColumns} dataSource={data.by_run} pagination={{ pageSize: 10 }} />
      </Card>
    </>
  )
}
