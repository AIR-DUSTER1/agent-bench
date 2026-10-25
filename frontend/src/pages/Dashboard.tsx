import { Card, Col, Progress, Row, Statistic, Table, Typography } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '../api'
import type { EvalRun, Health } from '../types'
import { StatusTag, fmtTime } from '../format'
import type { TableColumnsType } from 'antd'

const columns: TableColumnsType<EvalRun> = [
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
  { title: '创建时间', dataIndex: 'created_at', width: 150, render: (t: string) => fmtTime(t) },
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
  const done = runs.filter((r) => r.status === 'done')
  const active = runs.filter(
    (r) => !['done', 'failed', 'cancelled', 'pending'].includes(r.status),
  )

  return (
    <>
      <Row gutter={[12, 12]}>
        <Col span={6}><Card><Statistic title="评测任务" value={runs.length} /></Card></Col>
        <Col span={6}><Card><Statistic title="已完成" value={done.length} /></Card></Col>
        <Col span={6}><Card><Statistic title="运行中" value={active.length} /></Card></Col>
        <Col span={6}>
          <Card>
            <Statistic title="LLM / Judge" value={health ? `${health.llm_model} / ${health.judge_model}` : '…'} />
          </Card>
        </Col>
      </Row>
      <Card title="最近评测任务" style={{ marginTop: 14 }}>
        <Table<EvalRun>
          rowKey="id"
          size="small"
          columns={columns}
          dataSource={[...runs].sort((a, b) => b.id - a.id).slice(0, 10)}
          pagination={false}
        />
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          共 {runs.length} 个任务，完整列表见「评测任务」页
        </Typography.Text>
      </Card>
    </>
  )
}
