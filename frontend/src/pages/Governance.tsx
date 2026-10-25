import { useState } from 'react'
import { App, Button, Card, Col, Input, Row, Space, Table, Tag, Typography } from 'antd'
import type { TableColumnsType } from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, errText } from '../api'
import type { QualityReportRow, TagItem } from '../types'
import { fmtTime } from '../format'

export default function Governance() {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const { data: tags = {} } = useQuery({
    queryKey: ['tags'],
    queryFn: () => api.get<Record<string, TagItem[]>>('/governance/tags'),
  })
  const { data: reports = [] } = useQuery({
    queryKey: ['quality-reports'],
    queryFn: () => api.get<QualityReportRow[]>('/governance/quality-reports'),
  })

  const [category, setCategory] = useState('')
  const [value, setValue] = useState('')
  const [label, setLabel] = useState('')
  const addMut = useMutation({
    mutationFn: () => api.post('/governance/tags', { category, value, label: label || undefined }),
    onSuccess: () => {
      message.success('已添加')
      setValue('')
      setLabel('')
      void queryClient.invalidateQueries({ queryKey: ['tags'] })
    },
    onError: (e) => message.error('添加失败：' + errText(e), 6),
  })

  const reportColumns: TableColumnsType<QualityReportRow> = [
    { title: 'ID', dataIndex: 'id', width: 60 },
    { title: '数据集', dataIndex: 'dataset_id', width: 80, render: (id: number) => `#${id}` },
    { title: '触发', dataIndex: 'triggered_by', width: 100 },
    { title: '阻断', dataIndex: 'blockers', width: 70, render: (b: number) => b ? <Typography.Text type="danger">{b}</Typography.Text> : b },
    { title: '提醒', dataIndex: 'warnings', width: 70 },
    { title: '时间', dataIndex: 'created_at', render: (t: string) => fmtTime(t) },
  ]

  return (
    <>
      <Card size="small" style={{ marginBottom: 14 }}>
        <Space wrap>
          <Typography.Text strong>统一标签体系　</Typography.Text>
          <Input placeholder="类别" style={{ width: 110 }} value={category} onChange={(e) => setCategory(e.target.value)} />
          <Input placeholder="值" style={{ width: 140 }} value={value} onChange={(e) => setValue(e.target.value)} />
          <Input placeholder="显示名（可选）" style={{ width: 140 }} value={label} onChange={(e) => setLabel(e.target.value)} />
          <Button type="primary" loading={addMut.isPending} disabled={!category || !value} onClick={() => addMut.mutate()}>
            + 添加
          </Button>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            四类受控类别由后端校验；评测样本引用未登记标签会被质检拦下
          </Typography.Text>
        </Space>
      </Card>

      <Row gutter={[12, 12]}>
        {Object.entries(tags).map(([cat, list]) => (
          <Col span={12} key={cat}>
            <Card size="small" title={`${cat}（${list.length}）`}>
              {list.length === 0 ? <Typography.Text type="secondary">暂无</Typography.Text> : list.map((t) => (
                <Tag key={t.id} style={t.enabled ? undefined : { opacity: 0.4 }}>
                  {t.value}{t.label && t.label !== t.value ? ` (${t.label})` : ''}
                </Tag>
              ))}
            </Card>
          </Col>
        ))}
      </Row>

      <Card size="small" title="质量报告（最近 50 条）" style={{ marginTop: 14 }}>
        <Table<QualityReportRow>
          rowKey="id"
          size="small"
          columns={reportColumns}
          dataSource={reports}
          pagination={{ pageSize: 8 }}
        />
      </Card>
    </>
  )
}
