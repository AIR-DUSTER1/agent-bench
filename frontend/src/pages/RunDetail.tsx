import { useState } from 'react'
import {
  App, Button, Card, Descriptions, Modal, Select, Space, Spin, Table, Tabs, Tag, Typography, Alert,
} from 'antd'
import type { TableColumnsType } from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'
import { api, errText } from '../api'
import type { CompareResult, DatasetListItem, EvalRun, RunTokens, TokenRow } from '../types'
import { StatusTag, fmtTime } from '../format'
import Chart from '../components/Chart'

const TERMINAL = ['done', 'failed', 'cancelled']
const ACTIVE = ['loading', 'executing', 'scoring', 'attributing', 'reporting', 'pending']

const SOURCE_LABEL: Record<string, { text: string; color: string }> = {
  api: { text: '精确', color: 'green' },
  approx_chars: { text: '近似（字符数）', color: 'gold' },
  none: { text: '未上报', color: 'default' },
}

export function SourceTag({ source }: { source: string }) {
  const s = SOURCE_LABEL[source] ?? { text: source, color: 'default' }
  return <Tag color={s.color}>{s.text}</Tag>
}

function UsageBrief({ s }: { s: { input_tokens: number; output_tokens: number; total_tokens: number } }) {
  return (
    <span style={{ fontSize: 12.5 }}>
      ↑{s.input_tokens.toLocaleString()} / ↓{s.output_tokens.toLocaleString()}
      {' '}(共 {s.total_tokens.toLocaleString()})
    </span>
  )
}

function TokenPanel({ runId }: { runId: number }) {
  const { data, isLoading } = useQuery({
    queryKey: ['run-tokens', runId],
    queryFn: () => api.get<RunTokens>(`/runs/${runId}/tokens`),
  })
  if (isLoading || !data) return <Spin />
  const noApi = data.agent_total.api_calls === 0 && data.judge_total.api_calls === 0

  // 按 Agent 聚合出堆叠柱状图（仅精确口径）
  const groups = new Map<string, { input: number; output: number }>()
  for (const r of data.rows) {
    if (r.usage.source !== 'api') continue
    const k = `${r.agent_name}/${r.agent_version}`
    const g = groups.get(k) ?? { input: 0, output: 0 }
    g.input += r.usage.input_tokens
    g.output += r.usage.output_tokens
    groups.set(k, g)
  }
  const names = [...groups.keys()]

  const columns: TableColumnsType<TokenRow> = [
    { title: '#', dataIndex: 'seq', width: 50 },
    { title: 'Agent', width: 200, render: (_, r) => `${r.agent_name}/${r.agent_version}` },
    {
      title: '被测 token（↑入 / ↓出）', key: 'usage',
      render: (_, r) => (
        <>
          <UsageBrief s={r.usage} /> <SourceTag source={r.usage.source} />
        </>
      ),
    },
    {
      title: 'Judge token（↑入 / ↓出）', key: 'judge',
      render: (_, r) => (
        <>
          <UsageBrief s={r.judge_usage} /> <SourceTag source={r.judge_usage.source} />
        </>
      ),
    },
  ]

  return (
    <>
      <Space size="large" style={{ marginBottom: 12 }} wrap>
        <Card size="small" title="被测侧合计" style={{ minWidth: 260 }}>
          <Typography.Title level={4} style={{ margin: 0 }}>
            {data.agent_total.total_tokens.toLocaleString()}
          </Typography.Title>
          <UsageBrief s={data.agent_total} />
          <div style={{ marginTop: 6 }}>
            精确 {data.agent_total.api_calls} · 近似 {data.agent_total.approx_calls} · 未上报 {data.agent_total.none_calls}
          </div>
        </Card>
        <Card size="small" title="Judge 侧合计" style={{ minWidth: 260 }}>
          <Typography.Title level={4} style={{ margin: 0 }}>
            {data.judge_total.total_tokens.toLocaleString()}
          </Typography.Title>
          <UsageBrief s={data.judge_total} />
          <div style={{ marginTop: 6 }}>
            精确 {data.judge_total.api_calls} · 近似 {data.judge_total.approx_calls} · 未上报 {data.judge_total.none_calls}
          </div>
        </Card>
      </Space>

      {noApi && (
        <Alert
          type="info"
          showIcon
          message="该任务没有精确 token 上报"
          description="内置 prompt/rag/Tool Agent 与 external_http 型 Agent 会精确上报；external_cli 型（命令行）无法获得用量，显示为「未上报」。重新跑一次评测即可看到新采集的数据。"
          style={{ marginBottom: 12 }}
        />
      )}

      {names.length > 0 && (
        <Card size="small" title="token 分布（按 Agent，仅精确口径）" style={{ marginBottom: 14 }}>
          <Chart
            height={260}
            option={{
              tooltip: { trigger: 'axis' as const },
              legend: {},
              xAxis: { type: 'category' as const, data: names },
              yAxis: { type: 'value' as const, name: 'tokens' },
              series: [
                { name: '输入', type: 'bar' as const, stack: 't', data: names.map((n) => groups.get(n)!.input) },
                { name: '输出', type: 'bar' as const, stack: 't', data: names.map((n) => groups.get(n)!.output) },
              ],
            }}
          />
        </Card>
      )}

      <Card size="small" title={`逐样本明细（${data.rows.length}）`}>
        <Table<TokenRow> rowKey="case_result_id" size="small" columns={columns} dataSource={data.rows} pagination={{ pageSize: 12 }} />
      </Card>
    </>
  )
}

// 升级对比：选一个历史 run 作基线，按 case.input 对齐逐题对照（delta = 本 run - 基线）
function ComparePanel({ runId }: { runId: number }) {
  const [baselineId, setBaselineId] = useState<number | null>(null)
  const { data: runs = [] } = useQuery({
    queryKey: ['runs'],
    queryFn: () => api.get<EvalRun[]>('/runs'),
  })
  const { data, isLoading } = useQuery({
    queryKey: ['compare', baselineId, runId],
    queryFn: () => api.get<CompareResult>(`/runs/${baselineId}/compare/${runId}`),
    enabled: baselineId !== null,
  })

  return (
    <>
      <Space style={{ marginBottom: 12 }}>
        <Typography.Text>基线任务（旧）：</Typography.Text>
        <Select
          style={{ width: 360 }}
          placeholder="选择用于对比的历史评测任务"
          value={baselineId ?? undefined}
          onChange={(v) => setBaselineId(v)}
          options={runs.filter((r) => r.id !== runId).map((r) => ({
            value: r.id,
            label: `#${r.id} ${r.name}（${r.status}）`,
          }))}
        />
      </Space>
      {data?.warning && <Alert type="warning" showIcon message={data.warning} style={{ marginBottom: 12 }} />}
      {isLoading && <Spin />}
      {data?.sides.map((s) => (
        <Card
          key={s.agent_version_id}
          size="small"
          title={`${s.agent_name}/${s.version} · 配对 ${s.paired} 题`}
          style={{ marginBottom: 14 }}
        >
          <Space size="large" wrap style={{ marginBottom: 10 }}>
            <Typography.Text>
              基线均分 <Typography.Text strong>{s.summary.a_mean ?? '-'}</Typography.Text>
              {' → '}本 run 均分 <Typography.Text strong>{s.summary.b_mean ?? '-'}</Typography.Text>
            </Typography.Text>
            <Typography.Text>
              变化 <Typography.Text type={s.summary.delta_mean === null ? 'secondary' : s.summary.delta_mean > 0 ? 'success' : s.summary.delta_mean < 0 ? 'danger' : 'secondary'}>
                {s.summary.delta_mean === null ? '-' : (s.summary.delta_mean > 0 ? '+' : '') + s.summary.delta_mean}
              </Typography.Text>
            </Typography.Text>
            <Typography.Text>
              <Tag color="green">升 {s.summary.win}</Tag>
              <Tag>平 {s.summary.tie}</Tag>
              <Tag color="red">降 {s.summary.loss}</Tag>
            </Typography.Text>
            {s.summary.significance && (
              <Typography.Text type="secondary">
                显著性：{s.summary.significance.method} · p = {s.summary.significance.p ?? '样本不足'}
                {s.summary.significance.p != null && (s.summary.significance.p < 0.05 ? '（显著）' : '（不显著）')}
              </Typography.Text>
            )}
          </Space>
          <Table
            rowKey="input"
            size="small"
            pagination={{ pageSize: 10 }}
            dataSource={s.rows}
            columns={[
              { title: 'input', dataIndex: 'input', ellipsis: true },
              { title: '基线得分', dataIndex: 'a_score', width: 90, render: (v: number | null) => v ?? '-' },
              { title: '本 run', dataIndex: 'b_score', width: 90, render: (v: number | null) => v ?? '-' },
              {
                title: 'Δ', dataIndex: 'delta', width: 80,
                render: (v: number | null) => v === null ? '-' : (
                  <Typography.Text type={v > 0 ? 'success' : v < 0 ? 'danger' : 'secondary'}>
                    {v > 0 ? '+' : ''}{v}
                  </Typography.Text>
                ),
              },
            ]}
          />
        </Card>
      ))}
    </>
  )
}

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

  // 复评：继承本 run 全部配置，只换数据集版本
  const [replayOpen, setReplayOpen] = useState(false)
  const [replayDs, setReplayDs] = useState<number | null>(null)
  const { data: datasets = [] } = useQuery({
    queryKey: ['datasets'],
    queryFn: () => api.get<DatasetListItem[]>('/datasets'),
    enabled: replayOpen,
  })
  const replayMut = useMutation({
    mutationFn: () => api.post<{ id: number }>(`/runs/${runId}/replay`, { dataset_version_id: replayDs }),
    onSuccess: (r) => {
      message.success(`已创建复评 Run #${r.id}`)
      setReplayOpen(false)
      navigate(`/runs/${r.id}`)
    },
    onError: (e) => message.error('复评失败：' + errText(e), 6),
  })

  if (isLoading || !run) return <Spin />
  const pct = run.total_cases ? Math.round((100 * run.progress) / run.total_cases) : 0

  const overview = (
    <>
      <Descriptions size="small" column={3}>
        <Descriptions.Item label="模式">{run.mode.toUpperCase()}</Descriptions.Item>
        <Descriptions.Item label="状态"><StatusTag status={run.status} /></Descriptions.Item>
        <Descriptions.Item label="进度">{run.progress}/{run.total_cases}（{pct}%）</Descriptions.Item>
          <Descriptions.Item label="Judge">{run.judge_model} · {run.judge_mode}</Descriptions.Item>
          <Descriptions.Item label="并发">{run.concurrency}</Descriptions.Item>
          {run.model_label && <Descriptions.Item label="覆盖模型"><Tag color="blue">{run.model_label}</Tag></Descriptions.Item>}
        <Descriptions.Item label="创建时间">{fmtTime(run.created_at)}</Descriptions.Item>
        <Descriptions.Item label="开始">{fmtTime(run.started_at)}</Descriptions.Item>
        <Descriptions.Item label="结束">{fmtTime(run.finished_at)}</Descriptions.Item>
        <Descriptions.Item label="维度">{run.dimension_codes.join(' / ') || '默认五维'}</Descriptions.Item>
      </Descriptions>
      {run.error && <Alert type="error" showIcon message={run.error} style={{ marginTop: 10 }} />}
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
            </Typography.Text>
          ) : (
            <Typography.Text type="secondary">报告尚未生成</Typography.Text>
          )}
        </Card>
      )}
    </>
  )

  return (
    <>
      <Space style={{ marginBottom: 12 }}>
        <Button onClick={() => navigate('/runs')}>← 返回列表</Button>
        {TERMINAL.includes(run.status)
          ? <Button onClick={() => retryMut.mutate()}>重跑</Button>
          : <Button danger onClick={() => cancelMut.mutate()}>取消任务</Button>}
        <Button type="primary" ghost onClick={() => setReplayOpen(true)}>复评（换数据集）</Button>
      </Space>

      <Modal
        title="复评：以本任务为模板，换用新数据集版本"
        open={replayOpen}
        okText="发起复评"
        cancelText="取消"
        okButtonProps={{ disabled: replayDs === null }}
        confirmLoading={replayMut.isPending}
        onCancel={() => setReplayOpen(false)}
        onOk={() => replayMut.mutate()}
      >
        <Typography.Paragraph type="secondary">
          继承本任务的 Agent 版本、并发与 Judge 配置；用于数据集升级后的对照验证。
        </Typography.Paragraph>
        <Select
          style={{ width: '100%' }}
          placeholder="选择已发布的数据集版本"
          value={replayDs ?? undefined}
          onChange={(v) => setReplayDs(v)}
          options={datasets.flatMap((d) =>
            d.versions.map((v) => ({ value: v.id, label: `${d.name} · ${v.version}（${v.case_count}）` })),
          )}
          showSearch
        />
      </Modal>

      <Card size="small" title={`Run #${run.id} · ${run.name}`}>
        <Tabs
          items={[
            { key: 'overview', label: '概览', children: overview },
            { key: 'tokens', label: 'Token 消耗', children: <TokenPanel runId={runId} /> },
            { key: 'compare', label: '升级对比', children: <ComparePanel runId={runId} /> },
          ]}
        />
      </Card>
    </>
  )
}
