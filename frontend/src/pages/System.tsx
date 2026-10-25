import { useState } from 'react'
import {
  App, Button, Card, Descriptions, Form, Input, Modal, Space, Switch, Table, Tag, Typography,
} from 'antd'
import type { TableColumnsType } from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, errText } from '../api'
import type { Dimension, ModelEntryInfo, ModelProviderInfo, Settings } from '../types'

// ---------- 供应商弹窗 ----------

function ProviderModal({ open, initial, onClose }: {
  open: boolean
  initial: ModelProviderInfo | null
  onClose: () => void
}) {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const [form] = Form.useForm()
  // Modal 每次打开重填
  const afterOpenChange = (visible: boolean) => {
    if (visible) {
      form.setFieldsValue({
        name: initial?.name ?? '',
        base_url: initial?.base_url ?? 'https://',
        api_key: '',
        enabled: initial?.enabled ?? true,
      })
    }
  }

  const saveMut = useMutation({
    mutationFn: (v: Record<string, unknown>) =>
      initial
        ? api.put(`/models/providers/${initial.id}`, { ...v, api_key: v.api_key || '' })
        : api.post('/models/providers', v),
    onSuccess: () => {
      message.success(initial ? '已保存' : '已添加供应商')
      void queryClient.invalidateQueries({ queryKey: ['providers'] })
      void queryClient.invalidateQueries({ queryKey: ['model-entries'] })
      onClose()
    },
    onError: (e) => message.error(errText(e), 6),
  })

  return (
    <Modal
      title={initial ? `编辑供应商：${initial.name}` : '添加模型供应商'}
      open={open}
      afterOpenChange={afterOpenChange}
      okText="保存"
      cancelText="取消"
      confirmLoading={saveMut.isPending}
      onCancel={onClose}
      onOk={() => form.validateFields().then((v) => saveMut.mutate(v))}
    >
      <Form form={form} layout="vertical">
        <Form.Item name="name" label="名称" rules={[{ required: true, message: '必填' }]}>
          <Input placeholder="DeepSeek / OpenAI / 智谱 / 本地 vLLM…" />
        </Form.Item>
        <Form.Item name="base_url" label="Base URL（OpenAI 兼容端点）" rules={[{ required: true, message: '必填' }]}>
          <Input placeholder="https://api.deepseek.com" />
        </Form.Item>
        <Form.Item
          name="api_key"
          label={initial ? `API Key（已存 ${initial.api_key_masked}，留空不修改）` : 'API Key'}
          rules={initial ? [] : [{ required: true, message: '必填' }]}
        >
          <Input.Password placeholder="sk-…" autoComplete="new-password" />
        </Form.Item>
        <Form.Item name="enabled" label="启用" valuePropName="checked">
          <Switch />
        </Form.Item>
      </Form>
    </Modal>
  )
}

// ---------- 模型管理弹窗（某供应商下的模型列表） ----------

function ModelsModal({ provider, onClose }: { provider: ModelProviderInfo | null; onClose: () => void }) {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const [form] = Form.useForm()
  const { data: entries = [] } = useQuery({
    queryKey: ['model-entries'],
    queryFn: () => api.get<ModelEntryInfo[]>('/models'),
    enabled: provider !== null,
  })
  const list = entries.filter((e) => e.provider_id === provider?.id)

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['model-entries'] })
    void queryClient.invalidateQueries({ queryKey: ['providers'] })
  }
  const addMut = useMutation({
    mutationFn: (v: { name: string; display_name?: string }) =>
      api.post('/models', { provider_id: provider?.id, ...v }),
    onSuccess: () => {
      message.success('已添加模型')
      form.resetFields()
      invalidate()
    },
    onError: (e) => message.error(errText(e), 6),
  })
  const delMut = useMutation({
    mutationFn: (id: number) => api.del(`/models/${id}`),
    onSuccess: () => {
      message.success('已删除')
      invalidate()
    },
    onError: (e) => message.error(errText(e), 6),
  })
  const toggleMut = useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) => api.put(`/models/${id}`, { enabled }),
    onSuccess: invalidate,
    onError: (e) => message.error(errText(e), 6),
  })

  const columns: TableColumnsType<ModelEntryInfo> = [
    { title: '模型 ID', dataIndex: 'name' },
    { title: '显示名', dataIndex: 'display_name', render: (d: string) => d || '-' },
    {
      title: '启用', dataIndex: 'enabled', width: 80,
      render: (en: boolean, e) => <Switch size="small" checked={en} onChange={(v) => toggleMut.mutate({ id: e.id, enabled: v })} />,
    },
    {
      title: '', key: 'op', width: 70,
      render: (_, e) => <Button size="small" type="link" danger onClick={() => delMut.mutate(e.id)}>删除</Button>,
    },
  ]

  return (
    <Modal
      title={`模型管理：${provider?.name ?? ''}`}
      open={provider !== null}
      footer={null}
      onCancel={onClose}
      width={640}
    >
      <Form form={form} layout="inline" style={{ marginBottom: 12 }}>
        <Form.Item name="name" rules={[{ required: true, message: '必填' }]}>
          <Input placeholder="模型 ID，如 deepseek-flash" style={{ width: 240 }} />
        </Form.Item>
        <Form.Item name="display_name">
          <Input placeholder="显示名（可选）" style={{ width: 160 }} />
        </Form.Item>
        <Form.Item>
          <Button type="primary" loading={addMut.isPending}
            onClick={() => form.validateFields().then((v) => addMut.mutate(v)).catch(() => undefined)}>
            + 添加
          </Button>
        </Form.Item>
      </Form>
      <Table<ModelEntryInfo> rowKey="id" size="small" columns={columns} dataSource={list} pagination={false} />
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        删除/停用后，引用该模型的评测任务发起时会报「模型不存在或已停用」。
      </Typography.Text>
    </Modal>
  )
}

// ---------- 主页面 ----------

export default function System() {
  const { message, modal } = App.useApp()
  const queryClient = useQueryClient()
  const { data: s } = useQuery({
    queryKey: ['settings'],
    queryFn: () => api.get<Settings>('/system/settings'),
  })
  const { data: dims = [] } = useQuery({
    queryKey: ['dimensions'],
    queryFn: () => api.get<Dimension[]>('/dimensions'),
  })
  const { data: providers = [] } = useQuery({
    queryKey: ['providers'],
    queryFn: () => api.get<ModelProviderInfo[]>('/models/providers'),
  })

  const [providerModal, setProviderModal] = useState<{ open: boolean; initial: ModelProviderInfo | null }>({ open: false, initial: null })
  const [modelsOf, setModelsOf] = useState<ModelProviderInfo | null>(null)
  const delProvider = (p: ModelProviderInfo) => {
    modal.confirm({
      title: `删除供应商 ${p.name}？`,
      content: '其下所有模型一并删除；引用它们的 Agent 配置/评测任务在启动时会报模型不存在。',
      okText: '删除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        try {
          await api.del(`/models/providers/${p.id}`)
          message.success('已删除')
          void queryClient.invalidateQueries({ queryKey: ['providers'] })
          void queryClient.invalidateQueries({ queryKey: ['model-entries'] })
        } catch (e) {
          message.error(errText(e), 6)
        }
      },
    })
  }

  const providerColumns: TableColumnsType<ModelProviderInfo> = [
    { title: '名称', dataIndex: 'name' },
    { title: 'Base URL', dataIndex: 'base_url', ellipsis: true },
    { title: 'API Key', dataIndex: 'api_key_masked', width: 120 },
    {
      title: '状态', dataIndex: 'enabled', width: 80,
      render: (en: boolean) => (en ? <Tag color="green">启用</Tag> : <Tag>停用</Tag>),
    },
    {
      title: '操作', key: 'op', width: 220,
      render: (_, p) => (
        <Space>
          <Button size="small" type="link" onClick={() => setModelsOf(p)}>管理模型</Button>
          <Button size="small" type="link" onClick={() => setProviderModal({ open: true, initial: p })}>编辑</Button>
          <Button size="small" type="link" danger onClick={() => delProvider(p)}>删除</Button>
        </Space>
      ),
    },
  ]

  const dimColumns: TableColumnsType<Dimension> = [
    { title: 'code', dataIndex: 'code', width: 130 },
    { title: '名称', dataIndex: 'name', width: 110 },
    { title: '权重', dataIndex: 'weight', width: 70 },
    { title: '内置', dataIndex: 'is_builtin', width: 70, render: (b: boolean) => (b ? '✓' : '') },
    { title: '启用', dataIndex: 'enabled', width: 70, render: (b: boolean) => (b ? <Tag color="green">启用</Tag> : <Tag>停用</Tag>) },
    { title: 'Rubric 摘要', dataIndex: 'rubric', render: (r: string) => <Typography.Text type="secondary">{r.slice(0, 80)}…</Typography.Text> },
  ]

  return (
    <>
      <Card size="small" title="系统配置（.env）">
        {s && (
          <Descriptions size="small" column={1}>
            <Descriptions.Item label="被测 LLM 缺省">{s.llm_base_url} · {s.llm_model} · key {s.llm_api_key_masked}</Descriptions.Item>
            <Descriptions.Item label="Judge LLM">{s.judge_base_url} · {s.judge_model} · key {s.judge_api_key_masked}</Descriptions.Item>
            <Descriptions.Item label="并发（执行/评分）">{s.exec_concurrency} / {s.judge_concurrency}</Descriptions.Item>
            <Descriptions.Item label="通过阈值">{s.pass_threshold} / 5</Descriptions.Item>
            <Descriptions.Item label="Langfuse">
              {s.langfuse_enabled ? `已启用（${s.langfuse_host}）` : '未配置 → 本地 JSON Trace 降级'}
            </Descriptions.Item>
            <Descriptions.Item label="数据库">{s.database_url_masked}</Descriptions.Item>
          </Descriptions>
        )}
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          Judge 模型仍由 .env（JUDGE_*）配置；下方注册表用于被测 Agent 的模型选择与覆盖
        </Typography.Text>
      </Card>

      <Card
        size="small"
        title={`模型供应商（${providers.length}）`}
        style={{ marginTop: 14 }}
        extra={<Button size="small" type="primary" onClick={() => setProviderModal({ open: true, initial: null })}>+ 添加供应商</Button>}
      >
        <Table<ModelProviderInfo>
          rowKey="id"
          size="small"
          columns={providerColumns}
          dataSource={providers}
          pagination={false}
        />
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          供应商与模型注册后，注册 Agent（prompt/rag/tool）和发起评测时可直接下拉选择；key 仅存库、回显脱敏
        </Typography.Text>
      </Card>

      <Card size="small" title={`评测维度（${dims.length}）`} style={{ marginTop: 14 }}>
        <Table<Dimension> rowKey="id" size="small" columns={dimColumns} dataSource={dims} pagination={false} />
      </Card>

      <ProviderModal
        open={providerModal.open}
        initial={providerModal.initial}
        onClose={() => setProviderModal({ open: false, initial: null })}
      />
      <ModelsModal provider={modelsOf} onClose={() => setModelsOf(null)} />
    </>
  )
}
