import { useMemo } from 'react'
import {
  App, Button, Card, Form, Input, InputNumber, Progress, Select, Table, Typography,
} from 'antd'
import type { TableColumnsType } from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router-dom'
import { api, errText } from '../api'
import type { Agent, DatasetListItem, EvalRun, ModelEntryInfo } from '../types'
import { StatusTag } from '../format'

const TERMINAL = ['done', 'failed', 'cancelled']

export default function Runs() {
  const { message } = App.useApp()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [form] = Form.useForm()

  const { data: runs = [] } = useQuery({
    queryKey: ['runs'],
    queryFn: () => api.get<EvalRun[]>('/runs'),
    refetchInterval: 5000,
  })
  const { data: agents = [] } = useQuery({
    queryKey: ['agents'],
    queryFn: () => api.get<Agent[]>('/agents'),
  })
  const { data: datasets = [] } = useQuery({
    queryKey: ['datasets'],
    queryFn: () => api.get<DatasetListItem[]>('/datasets'),
  })
  const { data: modelEntries = [] } = useQuery({
    queryKey: ['model-entries'],
    queryFn: () => api.get<ModelEntryInfo[]>('/models'),
  })

  const avOptions = useMemo(
    () => agents.flatMap((a) => a.versions.map((v) => ({ value: v.id, label: `${a.name} · ${v.version}（${a.type}）` }))),
    [agents],
  )
  const dsOptions = useMemo(
    () => datasets.flatMap((d) => d.versions.map((v) => ({ value: v.id, label: `${d.name} · ${v.version}` }))),
    [datasets],
  )

  const createMut = useMutation({
    mutationFn: (body: Record<string, unknown>) => api.post<{ id: number }>('/runs', body),
    onSuccess: (r) => {
      message.success(`已创建 Run #${r.id}，正在后台执行`)
      void queryClient.invalidateQueries({ queryKey: ['runs'] })
      navigate(`/runs/${r.id}`)
    },
    onError: (e) => message.error('创建失败：' + errText(e), 6),
  })
  const retryMut = useMutation({
    mutationFn: (id: number) => api.post(`/runs/${id}/retry`, {}),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['runs'] }),
    onError: (e) => message.error(errText(e), 6),
  })
  const cancelMut = useMutation({
    mutationFn: (id: number) => api.post(`/runs/${id}/cancel`, {}),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['runs'] }),
    onError: (e) => message.error(errText(e), 6),
  })

  const submit = () => {
    form.validateFields().then((v) => {
      const ids = [v.agentA as number]
      if (v.agentB) ids.push(v.agentB as number)
      createMut.mutate({
        name: v.name,
        agent_version_ids: ids,
        dataset_version_id: v.datasetVersion,
        concurrency: v.concurrency,
        model_id: v.model || undefined,
      })
    })
  }

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
      title: '进度', key: 'progress', width: 170,
      render: (_, r) => (
        <>
          {r.progress}/{r.total_cases}
          <Progress size="small" percent={r.total_cases ? Math.round((100 * r.progress) / r.total_cases) : 0} />
        </>
      ),
    },
    {
      title: '操作', width: 100,
      render: (_, r) => TERMINAL.includes(r.status) ? (
        <Button size="small" onClick={() => retryMut.mutate(r.id)}>重跑</Button>
      ) : (
        <Button size="small" onClick={() => cancelMut.mutate(r.id)}>取消</Button>
      ),
    },
  ]

  return (
    <>
      <Card size="small" title="新建评测任务" style={{ marginBottom: 14 }}>
        <Form form={form} layout="inline" initialValues={{ concurrency: 3 }}>
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '必填' }]}
            initialValue={`评测 ${new Date().toISOString().slice(0, 16).replace('T', ' ')}`}>
            <Input style={{ width: 210 }} />
          </Form.Item>
          <Form.Item name="agentA" label="A（被测）" rules={[{ required: true, message: '必选' }]}>
            <Select options={avOptions} placeholder="选择 Agent 版本" style={{ width: 230 }} showSearch />
          </Form.Item>
          <Form.Item name="agentB" label="B（对比）">
            <Select options={avOptions} allowClear placeholder="— 单独评测 —" style={{ width: 230 }} showSearch />
          </Form.Item>
          <Form.Item name="datasetVersion" label="数据集版本" rules={[{ required: true, message: '必选' }]}>
            <Select options={dsOptions} placeholder="已发布版本" style={{ width: 230 }} showSearch />
          </Form.Item>
          <Form.Item name="model" label="模型覆盖">
            <Select
              options={modelEntries.filter((e) => e.enabled).map((e) => ({ value: e.id, label: e.label }))}
              allowClear
              placeholder="留空用 Agent 配置的模型"
              style={{ width: 220 }}
              showSearch
            />
          </Form.Item>
          <Form.Item name="concurrency" label="并发">
            <InputNumber min={1} max={8} />
          </Form.Item>
          <Form.Item>
            <Button type="primary" loading={createMut.isPending} onClick={submit}>🚀 发起评测</Button>
          </Form.Item>
        </Form>
      </Card>

      <Card size="small" title={`任务列表（${runs.length}）`}>
        <Table<EvalRun>
          rowKey="id"
          size="small"
          columns={columns}
          dataSource={runs}
          pagination={{ pageSize: 15 }}
        />
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          运行中任务每 5 秒自动刷新
        </Typography.Text>
      </Card>
    </>
  )
}
