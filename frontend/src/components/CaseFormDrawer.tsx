import { useEffect } from 'react'
import { Drawer, Form, Input, Select } from 'antd'
import type { EvalCase } from '../types'

const DIFFICULTIES = ['easy', 'medium', 'hard']

// 新增/编辑草稿样本的抽屉表单（tags 以 JSON 编辑，后端质检兜底）
export default function CaseFormDrawer({ open, initial, saving, onSave, onClose }: {
  open: boolean
  initial: EvalCase | null
  saving: boolean
  onSave: (v: { input: string; expected_output?: string; difficulty?: string; tags: Record<string, string> }) => void
  onClose: () => void
}) {
  const [form] = Form.useForm()

  useEffect(() => {
    if (!open) return
    form.setFieldsValue({
      input: initial?.input ?? '',
      expected_output: initial?.expected_output ?? '',
      difficulty: initial?.difficulty,
      tagsText: JSON.stringify(initial?.tags ?? {}, null, 0),
    })
  }, [open, initial, form])

  const submit = () => {
    form.validateFields().then((v) => {
      let tags: unknown = {}
      try {
        tags = JSON.parse(v.tagsText || '{}')
      } catch {
        form.setFields([{ name: 'tagsText', errors: ['tags 不是合法 JSON'] }])
        return
      }
      onSave({
        input: v.input,
        expected_output: v.expected_output || undefined,
        difficulty: v.difficulty || undefined,
        tags: tags as Record<string, string>,
      })
    })
  }

  return (
    <Drawer
      title={initial ? '编辑样本' : '新增样本'}
      open={open}
      onClose={onClose}
      width={520}
      destroyOnHidden
      extra={
        <a onClick={submit} style={{ fontWeight: 600, opacity: saving ? 0.5 : 1, pointerEvents: saving ? 'none' : 'auto' }}>
          {saving ? '保存中…' : '保存'}
        </a>
      }
    >
      <Form form={form} layout="vertical">
        <Form.Item name="input" label="输入（题目）" rules={[{ required: true, message: '必填' }]}>
          <Input.TextArea rows={4} />
        </Form.Item>
        <Form.Item name="expected_output" label="期望输出（可选）">
          <Input.TextArea rows={3} />
        </Form.Item>
        <Form.Item name="difficulty" label="难度">
          <Select allowClear placeholder="easy / medium / hard" options={DIFFICULTIES.map((d) => ({ value: d, label: d }))} />
        </Form.Item>
        <Form.Item name="tagsText" label="标签（JSON，须为标签字典内已登记的值）">
          <Input.TextArea rows={2} style={{ fontFamily: 'monospace' }} placeholder='{"difficulty_hint": "..."}' />
        </Form.Item>
      </Form>
    </Drawer>
  )
}
