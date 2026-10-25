import { useState } from 'react'
import { App, Button, Form, Input, Modal, Select, Space, Table, Tag, Typography } from 'antd'
import type { TableColumnsType } from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, errText } from '../api'
import type { Agent, ModelEntryInfo, TestResult } from '../types'
import { AGENT_TYPE_LABELS } from '../format'

export default function Agents() {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const { data: agents = [], isLoading } = useQuery({
    queryKey: ['agents'],
    queryFn: () => api.get<Agent[]>('/agents'),
  })

  const [createOpen, setCreateOpen] = useState(false)
  const [form] = Form.useForm()
  const selectedType = Form.useWatch('type', form)
  const { data: modelEntries = [] } = useQuery({
    queryKey: ['model-entries'],
    queryFn: () => api.get<ModelEntryInfo[]>('/models'),
    enabled: createOpen,
  })
  const BUILTIN_TYPES = ['prompt', 'rag', 'tool']
  const [testAgent, setTestAgent] = useState<Agent | null>(null)
  const [testInput, setTestInput] = useState('法国的首都是哪里？')
  const [testResult, setTestResult] = useState<TestResult | null>(null)

  const createMut = useMutation({
    mutationFn: (body: Record<string, unknown>) => api.post<Agent>('/agents', body),
    onSuccess: () => {
      message.success('已创建')
      setCreateOpen(false)
      form.resetFields()
      void queryClient.invalidateQueries({ queryKey: ['agents'] })
    },
    onError: (e) => message.error('创建失败：' + errText(e), 6),
  })

  const testMut = useMutation({
    mutationFn: (id: number) => api.post<TestResult>(`/agents/${id}/test`, { input: testInput }),
    onSuccess: (r) => setTestResult(r),
    onError: (e) => message.error('试跑失败：' + errText(e), 6),
  })

  const submitCreate = () => {
    form.validateFields().then((v) => {
      let config: Record<string, unknown>
      try {
        config = JSON.parse(v.config || '{}')
      } catch {
        message.error('配置不是合法 JSON')
        return
      }
      // prompt/rag/tool：模型从注册表下拉选择，写入 model_id 引用（运行时解析）
      if (BUILTIN_TYPES.includes(v.type) && v.model_id) config.model_id = v.model_id
      createMut.mutate({ name: v.name, type: v.type, description: v.description, config })
    })
  }

  const columns: TableColumnsType<Agent> = [
    { title: 'ID', dataIndex: 'id', width: 60 },
    { title: '名称', dataIndex: 'name' },
    {
      title: '类型', dataIndex: 'type', width: 150,
      render: (t: string) => <Tag color="blue">{AGENT_TYPE_LABELS[t] ?? t}</Tag>,
    },
    { title: '描述', dataIndex: 'description', ellipsis: true },
    { title: '版本数', width: 80, render: (_, a) => a.versions.length },
    {
      title: '操作', width: 100,
      render: (_, a) => (
        <Button
          size="small"
          onClick={() => {
            setTestAgent(a)
            setTestResult(null)
            setTestInput('法国的首都是哪里？')
          }}
        >
          试跑
        </Button>
      ),
    },
  ]

  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
        <Typography.Title level={4} style={{ margin: 0 }}>
          Agent 列表（{agents.length}）
        </Typography.Title>
        <Button type="primary" onClick={() => setCreateOpen(true)}>
          + 注册 Agent
        </Button>
      </div>
      <Table<Agent> rowKey="id" size="small" loading={isLoading} columns={columns} dataSource={agents} pagination={false} />

      <Modal
        title="注册 Agent"
        open={createOpen}
        onOk={submitCreate}
        confirmLoading={createMut.isPending}
        onCancel={() => setCreateOpen(false)}
        okText="创建"
        cancelText="取消"
        destroyOnHidden
      >
        <Form form={form} layout="vertical" initialValues={{ type: 'prompt', config: '{}' }}>
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '必填' }]}>
            <Input placeholder="my-agent" />
          </Form.Item>
          <Form.Item name="type" label="类型" rules={[{ required: true }]}>
            <Select
              options={Object.entries(AGENT_TYPE_LABELS).map(([value, label]) => ({ value, label }))}
            />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input />
          </Form.Item>
          {BUILTIN_TYPES.includes(selectedType) && (
            <Form.Item name="model_id" label="模型" extra="从模型注册表选择；留空用 .env 全局模型（LLM_*）">
              <Select
                allowClear
                showSearch
                placeholder="选择供应商 / 模型"
                options={modelEntries.map((e) => ({ value: e.id, label: e.label + (e.enabled ? '' : '（停用）') }))}
              />
            </Form.Item>
          )}
          <Form.Item
            name="config"
            label="配置（JSON）"
            extra={BUILTIN_TYPES.includes(selectedType)
              ? 'temperature / system_prompt / few_shot / top_k / kb_dir 等类型参数'
              : 'base_url/model/system_prompt/argv 等完整配置'}
          >
            <Input.TextArea rows={5} style={{ fontFamily: 'monospace' }} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={`试跑 ${testAgent?.name ?? ''}`}
        open={testAgent !== null}
        footer={null}
        onCancel={() => setTestAgent(null)}
        width={680}
      >
        <Space.Compact style={{ width: '100%' }}>
          <Input.TextArea
            rows={3}
            value={testInput}
            onChange={(e) => setTestInput(e.target.value)}
            placeholder="输入"
          />
        </Space.Compact>
        <Button
          type="primary"
          style={{ marginTop: 10 }}
          loading={testMut.isPending}
          disabled={testAgent === null}
          onClick={() => testAgent && testMut.mutate(testAgent.id)}
        >
          执行
        </Button>
        {testResult && (
          <div style={{ marginTop: 14 }}>
            {testResult.error ? (
              <Typography.Paragraph type="danger">错误：{testResult.error}</Typography.Paragraph>
            ) : (
              <Typography.Paragraph>
                <pre style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', background: '#f8fafc', padding: 10, borderRadius: 6 }}>
                  {testResult.output}
                </pre>
              </Typography.Paragraph>
            )}
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              耗时 {testResult.latency_ms}ms · token：{JSON.stringify(testResult.token_usage)}
            </Typography.Text>
          </div>
        )}
      </Modal>
    </>
  )
}
