import { App, Button, Card, Descriptions, Space, Spin, Table, Typography, Alert } from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, errText } from '../api'
import type { EvalRun } from '../types'
import { StatusTag, fmtTime } from '../format'

const TERMINAL = ['done', 'failed', 'cancelled']
const ACTIVE = ['loading', 'executing', 'scoring', 'attributing', 'reporting', 'pending']

export default function RunDetail() {
  const { id } = useParams()
  const runId = Number(id)
  const { message } = App.useApp()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const { data: run, isLoading } = useQuery({
    queryKey: ['run', runId],
    queryFn: () => api.get<EvalRun>(`/runs/${runId}`),
    refetchInterval: (q) => {
      const s = q.state.data?.status
      return s && ACTIVE.includes(s) ? 3000 : false
    },
  })

  const retryMut = useMutation({
    mutationFn: () => api.post(`/runs/${runId}/retry`, {}),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['run', runId] }),
    onError: (e) => message.error(errText(e), 6),
  })
  const cancelMut = useMutation({
    mutationFn: () => api.post(`/runs/${runId}/cancel`, {}),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['run', runId] }),
    onError: (e) => message.error(errText(e), 6),
  })

  if (isLoading || !run) return <Spin />
  const pct = run.total_cases ? Math.round((100 * run.progress) / run.total_cases) : 0

  return (
    <>
      <Space style={{ marginBottom: 12 }}>
        <Button onClick={() => navigate('/runs')}>← 返回列表</Button>
        {TERMINAL.includes(run.status)
          ? <Button onClick={() => retryMut.mutate()}>重跑</Button>
          : <Button danger onClick={() => cancelMut.mutate()}>取消任务</Button>}
      </Space>

      <Card size="small" title={`Run #${run.id} · ${run.name}`}>
        <Descriptions size="small" column={3}>
          <Descriptions.Item label="模式">{run.mode.toUpperCase()}</Descriptions.Item>
          <Descriptions.Item label="状态"><StatusTag status={run.status} /></Descriptions.Item>
          <Descriptions.Item label="进度">{run.progress}/{run.total_cases}（{pct}%）</Descriptions.Item>
          <Descriptions.Item label="Judge">{run.judge_model} · {run.judge_mode}</Descriptions.Item>
          <Descriptions.Item label="并发">{run.concurrency}</Descriptions.Item>
          <Descriptions.Item label="创建时间">{fmtTime(run.created_at)}</Descriptions.Item>
          <Descriptions.Item label="开始">{fmtTime(run.started_at)}</Descriptions.Item>
          <Descriptions.Item label="结束">{fmtTime(run.finished_at)}</Descriptions.Item>
          <Descriptions.Item label="维度">{run.dimension_codes.join(' / ') || '默认五维'}</Descriptions.Item>
        </Descriptions>
        {run.error && <Alert type="error" showIcon message={run.error} style={{ marginTop: 10 }} />}
      </Card>

      <Card size="small" title="被测对象" style={{ marginTop: 14 }}>
        <Table
          rowKey="agent_version_id"
          size="small"
          pagination={false}
          dataSource={run.sides}
          columns={[
            { title: 'Agent', dataIndex: 'agent_name' },
            { title: '版本', dataIndex: 'version', width: 100 },
            { title: '类型', dataIndex: 'agent_type', width: 160 },
          ]}
        />
      </Card>

      {run.status === 'done' && (
        <Card size="small" title="评测报告" style={{ marginTop: 14 }}>
          {run.report_id ? (
            <Typography.Text>
              <a href={`/api/runs/${run.id}/report/html`} target="_blank" rel="noreferrer">
                📋 打开完整 HTML 报告
              </a>
              {' '}
              <Link to={`/runs/${run.id}`}>（详情含归因/统计见后续版本）</Link>
            </Typography.Text>
          ) : (
            <Typography.Text type="secondary">报告尚未生成</Typography.Text>
          )}
        </Card>
      )}
    </>
  )
}
