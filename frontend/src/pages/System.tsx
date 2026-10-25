import { Card, Descriptions, Table, Tag, Typography } from 'antd'
import type { TableColumnsType } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import type { Dimension, Settings } from '../types'

export default function System() {
  const { data: s } = useQuery({
    queryKey: ['settings'],
    queryFn: () => api.get<Settings>('/system/settings'),
  })
  const { data: dims = [] } = useQuery({
    queryKey: ['dimensions'],
    queryFn: () => api.get<Dimension[]>('/dimensions'),
  })

  const columns: TableColumnsType<Dimension> = [
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
            <Descriptions.Item label="被测 LLM">{s.llm_base_url} · {s.llm_model} · key {s.llm_api_key_masked}</Descriptions.Item>
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
          修改配置请编辑 backend/.env 后重启服务
        </Typography.Text>
      </Card>
      <Card size="small" title={`评测维度（${dims.length}）`} style={{ marginTop: 14 }}>
        <Table<Dimension> rowKey="id" size="small" columns={columns} dataSource={dims} pagination={false} />
      </Card>
    </>
  )
}
