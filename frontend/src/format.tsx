import { Tag } from 'antd'

export const fmtTime = (iso?: string | null): string =>
  iso ? iso.slice(0, 19).replace('T', ' ') : '-'

// 运行中（活动状态）黄色、终态绿/红、待执行灰
export function StatusTag({ status }: { status: string }) {
  const active = ['loading', 'executing', 'scoring', 'attributing', 'reporting']
  const color = status === 'done' ? 'green' : status === 'failed' ? 'red'
    : status === 'cancelled' ? 'default' : active.includes(status) ? 'orange' : 'blue'
  return <Tag color={color}>{status}</Tag>
}

export const AGENT_TYPE_LABELS: Record<string, string> = {
  prompt: 'Prompt（纯推理）',
  rag: 'RAG（检索增强）',
  tool: 'Tool（工具调用）',
  external_http: '外部 HTTP',
  external_cli: '外部 CLI',
}
