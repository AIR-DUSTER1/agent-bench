import { useState } from 'react'
import {
  App, Button, Card, Form, Input, Modal, Select, Space, Table, Tag, Typography,
} from 'antd'
import type { TableColumnsType } from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, errText } from '../api'
import type {
  DatasetDetail, DatasetListItem, DatasetVersion, EvalCase,
  ExportOut, ImportPreflight, ImportResult, PublishResult, QualitySummary,
} from '../types'
import { fmtTime } from '../format'

const TAG_COLORS: Record<string, string> = { easy: 'green', medium: 'gold', hard: 'red' }

function CaseTable({ cases }: { cases: EvalCase[] }) {
  const columns: TableColumnsType<EvalCase> = [
    { title: '#', dataIndex: 'seq', width: 50 },
    { title: '输入', dataIndex: 'input', ellipsis: true },
    { title: '期望输出', dataIndex: 'expected_output', ellipsis: true },
    { title: '难度', dataIndex: 'difficulty', width: 80, render: (d: string) => <Tag color={TAG_COLORS[d] ?? 'default'}>{d}</Tag> },
    {
      title: '标签', dataIndex: 'tags', width: 200,
      render: (tags: Record<string, string> | undefined) =>
        Object.entries(tags ?? {}).map(([k, v]) => (
          <Tag key={k}>{k}:{v}</Tag>
        )),
    },
  ]
  return (
    <Table<EvalCase>
      rowKey={(c) => String(c.id ?? c.seq)}
      size="small"
      columns={columns}
      dataSource={cases}
      pagination={cases.length > 15 ? { pageSize: 15 } : false}
    />
  )
}

function QualitySummaryView({ summary }: { summary: QualitySummary }) {
  return (
    <>
      <Typography.Paragraph>
        阻断 <Typography.Text type="danger" strong>{summary.blockers}</Typography.Text>
        {' · '}提醒 <Typography.Text type="warning" strong>{summary.warnings}</Typography.Text>
      </Typography.Paragraph>
      <Table
        rowKey={(i) => `${i.rule}-${i.seq}-${i.detail}`}
        size="small"
        pagination={false}
        dataSource={summary.issues}
        columns={[
          { title: '级别', dataIndex: 'level', width: 80, render: (l: string) => l === 'blocker' ? <Typography.Text type="danger">{l}</Typography.Text> : l },
          { title: '规则', dataIndex: 'rule', width: 140 },
          { title: '样本', dataIndex: 'seq', width: 60, render: (s: number | null) => (s == null ? '-' : `#${s}`) },
          { title: '详情', dataIndex: 'detail' },
        ]}
      />
    </>
  )
}

export default function Datasets() {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const { data: datasets = [], isLoading } = useQuery({
    queryKey: ['datasets'],
    queryFn: () => api.get<DatasetListItem[]>('/datasets'),
  })

  // 查看
  const [viewId, setViewId] = useState<number | null>(null)
  const { data: viewDetail } = useQuery({
    queryKey: ['dataset', viewId],
    queryFn: () => api.get<DatasetDetail>(`/datasets/${viewId}`),
    enabled: viewId !== null,
  })
  const [viewVersionId, setViewVersionId] = useState<number | 'draft' | null>(null)
  const versionCases = useQuery({
    queryKey: ['dataset-version', viewId, viewVersionId],
    queryFn: () => {
      const dsId = viewId as number
      return viewVersionId === 'draft'
        ? Promise.resolve((viewDetail as DatasetDetail).draft)
        : api.get<DatasetVersion>(`/datasets/${dsId}/versions/${viewVersionId}`)
    },
    enabled: viewId !== null && viewVersionId !== null,
  })

  // 导入
  const [importOpen, setImportOpen] = useState(false)
  const [importForm] = Form.useForm()
  const [importOut, setImportOut] = useState<string>('')
  const importMut = useMutation({
    mutationFn: async ({ confirm }: { confirm: boolean }) => {
      const name = importForm.getFieldValue('name') as string
      const targetTypes = (importForm.getFieldValue('target_types') as string) || ''
      const cases = JSON.parse(importForm.getFieldValue('cases') as string) as EvalCase[]
      const exist = datasets.find((d) => d.name === name)
      const dsId = exist ? exist.id
        : (await api.post<{ id: number }>('/datasets', { name, target_types: targetTypes })).id
      return api.post<ImportPreflight | ImportResult>(`/datasets/${dsId}/import`, { cases, confirm })
    },
    onSuccess: (r) => {
      if ('confirm_required' in r) {
        setImportOut(`预检完成：将导入 ${r.to_import} 条（草稿已有 ${r.draft_existing} 条）\n阻断 ${r.quality.blockers} · 提醒 ${r.quality.warnings}`)
      } else {
        setImportOut(`✓ 已导入 ${r.imported} 条`)
        void queryClient.invalidateQueries({ queryKey: ['datasets'] })
      }
    },
    onError: (e) => setImportOut('失败：' + errText(e)),
  })

  // 发布 / 质检
  const [publishId, setPublishId] = useState<number | null>(null)
  const [publishNote, setPublishNote] = useState('')
  const publishMut = useMutation({
    mutationFn: (id: number) => api.post<PublishResult>(`/datasets/${id}/publish`, { note: publishNote || 'console 发布' }),
    onSuccess: (r) => {
      message.success(`已发布 ${r.version}（${r.case_count} 样本）`)
      setPublishId(null)
      setPublishNote('')
      void queryClient.invalidateQueries({ queryKey: ['datasets'] })
    },
    onError: (e) => {
      if (e && typeof e === 'object' && 'detail' in e) {
        const d = (e as { detail: { quality?: QualitySummary } }).detail
        if (d?.quality) message.error(`发布被阻断（${d.quality.blockers} 项阻断）：${JSON.stringify(d.quality.by_rule ?? {})}`, 8)
        else message.error(errText(e), 6)
      } else message.error(errText(e), 6)
    },
  })

  const [qualityId, setQualityId] = useState<number | null>(null)
  const [qualitySummary, setQualitySummary] = useState<QualitySummary | null>(null)
  const qualityMut = useMutation({
    mutationFn: (id: number) => api.post<QualitySummary>(`/datasets/${id}/quality-check`, {}),
    onSuccess: (r) => {
      setQualitySummary(r)
      void queryClient.invalidateQueries({ queryKey: ['quality-reports'] })
    },
    onError: (e) => message.error(errText(e), 6),
  })

  const exportVersion = async (dsId: number, v: { id: number; version: string }) => {
    const data = await api.get<ExportOut>(`/datasets/${dsId}/versions/${v.id}/export`)
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `${data.dataset}_${data.version}.json`
    a.click()
    URL.revokeObjectURL(a.href)
  }

  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
        <Typography.Title level={4} style={{ margin: 0 }}>评测集（{datasets.length}）</Typography.Title>
        <Button type="primary" onClick={() => { setImportOut(''); setImportOpen(true) }}>
          ⬆ JSON 批量导入
        </Button>
      </div>

      {isLoading ? null : datasets.map((d) => (
        <Card
          key={d.id}
          size="small"
          style={{ marginBottom: 12 }}
          title={(
            <Space wrap>
              {d.name}
              <Tag>草稿 {d.draft_count} 条</Tag>
              <Typography.Text type="secondary" style={{ fontWeight: 400 }}>{d.description}</Typography.Text>
            </Space>
          )}
          extra={(
            <Space wrap>
              <Button size="small" onClick={() => { setViewId(d.id); setViewVersionId('draft') }}>查看</Button>
              <Button size="small" onClick={() => { setQualityId(d.id); setQualitySummary(null); qualityMut.mutate(d.id) }}>质检</Button>
              <Button size="small" onClick={() => setPublishId(d.id)}>发布新版本</Button>
            </Space>
          )}
        >
          {d.versions.length === 0 ? (
            <Typography.Text type="secondary">尚无已发布版本</Typography.Text>
          ) : (
            <Table
              rowKey="id"
              size="small"
              pagination={false}
              dataSource={d.versions}
              columns={[
                { title: '已发布版本', dataIndex: 'version', width: 120 },
                { title: '样本数', dataIndex: 'case_count', width: 100 },
                { title: '发布时间', dataIndex: 'created_at', render: (t: string) => fmtTime(t) },
                {
                  title: '', key: 'export', width: 120,
                  render: (_, v) => <Button size="small" type="link" onClick={() => void exportVersion(d.id, v)}>导出 JSON</Button>,
                },
              ]}
            />
          )}
        </Card>
      ))}

      {/* 查看：草稿或任一发布版本的样本明细 */}
      <Modal
        title={`${viewDetail?.name ?? ''} · 样本明细`}
        open={viewId !== null}
        footer={null}
        onCancel={() => setViewId(null)}
        width={860}
      >
        <Space style={{ marginBottom: 10 }}>
          <Select
            style={{ width: 220 }}
            placeholder="选择版本"
            value={viewVersionId ?? undefined}
            onChange={(v) => setViewVersionId(v)}
            options={[
              ...(viewDetail ? [{ value: 'draft' as const, label: `草稿（${viewDetail.draft.case_count}）` }] : []),
              ...(viewDetail?.versions ?? []).map((v) => ({ value: v.id, label: `${v.version}（${v.case_count}）` })),
            ]}
          />
        </Space>
        {versionCases.data?.cases && <CaseTable cases={versionCases.data.cases} />}
      </Modal>

      {/* JSON 批量导入（预检 → 确认） */}
      <Modal
        title="JSON 批量导入"
        open={importOpen}
        footer={null}
        onCancel={() => setImportOpen(false)}
        width={720}
      >
        <Form form={importForm} layout="vertical">
          <Space style={{ width: '100%' }} size="large">
            <Form.Item name="name" label="数据集名称" rules={[{ required: true, message: '必填' }]} style={{ minWidth: 220 }}>
              <Input placeholder="已存在则导入到该数据集" />
            </Form.Item>
            <Form.Item name="target_types" label="适用 Agent 类型">
              <Input placeholder="prompt,rag,tool" style={{ width: 200 }} />
            </Form.Item>
          </Space>
          <Form.Item
            name="cases"
            label="样本 JSON 数组"
            rules={[{ required: true, message: '必填' }]}
            extra='格式：[{"input": "...", "expected_output": "...", "difficulty": "easy|medium|hard", "tags": {}}]'
          >
            <Input.TextArea rows={8} style={{ fontFamily: 'monospace' }} placeholder='[{"input": "...", "expected_output": "..."}]' />
          </Form.Item>
        </Form>
        <Space>
          <Button loading={importMut.isPending} onClick={() => importMut.mutate({ confirm: false })}>① 预检</Button>
          <Button type="primary" loading={importMut.isPending} onClick={() => importMut.mutate({ confirm: true })}>② 确认导入</Button>
        </Space>
        {importOut && (
          <pre style={{ marginTop: 12, background: '#f8fafc', padding: 10, borderRadius: 6, whiteSpace: 'pre-wrap' }}>
            {importOut}
          </pre>
        )}
      </Modal>

      {/* 发布 */}
      <Modal
        title="发布新版本"
        open={publishId !== null}
        okText="发布"
        cancelText="取消"
        confirmLoading={publishMut.isPending}
        onCancel={() => setPublishId(null)}
        onOk={() => publishId !== null && publishMut.mutate(publishId)}
      >
        <Typography.Paragraph type="secondary">
          将把当前草稿复制为不可变快照（发布前会跑质检，存在阻断则拒绝）。
        </Typography.Paragraph>
        <Input.TextArea
          rows={2}
          placeholder="版本备注（可选）"
          value={publishNote}
          onChange={(e) => setPublishNote(e.target.value)}
        />
      </Modal>

      {/* 质检 */}
      <Modal
        title="质检报告"
        open={qualityId !== null}
        footer={null}
        onCancel={() => { setQualityId(null); setQualitySummary(null) }}
        width={760}
      >
        {qualitySummary ? (
          <QualitySummaryView summary={qualitySummary} />
        ) : (
          <Typography.Text type="secondary">质检完成（结果见上方提示）</Typography.Text>
        )}
      </Modal>
    </>
  )
}
