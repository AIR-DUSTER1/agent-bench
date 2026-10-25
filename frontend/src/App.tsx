import { useEffect, useRef, useState } from 'react'
import { Input, Layout, Menu, Modal, Typography } from 'antd'
import {
  BarChartOutlined, DatabaseOutlined, DashboardOutlined, RobotOutlined,
  SettingOutlined, TagsOutlined, ThunderboltOutlined,
} from '@ant-design/icons'
import { Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api, getToken, setToken, setUnauthorizedHandler } from './api'
import type { Health } from './types'
import Dashboard from './pages/Dashboard'
import Agents from './pages/Agents'
import Datasets from './pages/Datasets'
import Runs from './pages/Runs'
import RunDetail from './pages/RunDetail'
import Stats from './pages/Stats'
import Governance from './pages/Governance'
import System from './pages/System'

const MENU_ITEMS = [
  { key: '/', icon: <DashboardOutlined />, label: '仪表盘' },
  { key: '/agents', icon: <RobotOutlined />, label: 'Agent 管理' },
  { key: '/datasets', icon: <DatabaseOutlined />, label: '评测集管理' },
  { key: '/runs', icon: <ThunderboltOutlined />, label: '评测任务' },
  { key: '/stats', icon: <BarChartOutlined />, label: '统计' },
  { key: '/governance', icon: <TagsOutlined />, label: '数据治理' },
  { key: '/system', icon: <SettingOutlined />, label: '系统设置' },
]

// 401 时弹出的鉴权输入框：解析 Promise 后由请求层带新 token 重试一次
function TokenModal() {
  const [open, setOpen] = useState(false)
  const [value, setValue] = useState('')
  const resolverRef = useRef<((v: string | null) => void) | null>(null)

  useEffect(() => {
    setUnauthorizedHandler(
      () =>
        new Promise<string | null>((resolve) => {
          setValue(getToken())
          resolverRef.current = resolve
          setOpen(true)
        }),
    )
    return () => setUnauthorizedHandler(null)
  }, [])

  const finish = (v: string | null) => {
    setOpen(false)
    resolverRef.current?.(v)
    resolverRef.current = null
  }
  const submit = () => {
    const t = value.trim()
    setToken(t)
    finish(t || null)
  }

  return (
    <Modal
      title="需要鉴权"
      open={open}
      okText="确定"
      cancelText="取消"
      onCancel={() => finish(null)}
      onOk={submit}
      destroyOnHidden
    >
      <Typography.Paragraph type="secondary">
        服务已启用 AUTH_TOKEN，请输入 Bearer Token：
      </Typography.Paragraph>
      <Input.Password
        autoFocus
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onPressEnter={submit}
        placeholder="AUTH_TOKEN"
      />
    </Modal>
  )
}

function HealthBadge() {
  const { data } = useQuery({
    queryKey: ['health'],
    queryFn: () => api.get<Health>('/system/health'),
    refetchInterval: 30_000,
  })
  if (!data) return null
  return (
    <Typography.Text style={{ color: '#94a3b8', fontSize: 12.5 }}>
      {data.llm_model} · trace: {data.trace_mode}
    </Typography.Text>
  )
}

export default function App() {
  const navigate = useNavigate()
  const location = useLocation()
  const selected = '/' + (location.pathname.split('/')[1] ?? '')

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Layout.Header style={{ display: 'flex', alignItems: 'center', gap: 24 }}>
        <Typography.Text strong style={{ color: '#fff', fontSize: 16, whiteSpace: 'nowrap' }}>
          ⚖ Agent-Bench 控制台
        </Typography.Text>
        <Menu
          theme="dark"
          mode="horizontal"
          selectedKeys={[selected]}
          items={MENU_ITEMS}
          onClick={({ key }) => navigate(key)}
          style={{ flex: 1, minWidth: 0 }}
        />
        <HealthBadge />
      </Layout.Header>
      <Layout.Content style={{ padding: 20, maxWidth: 1240, margin: '0 auto', width: '100%' }}>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/agents" element={<Agents />} />
          <Route path="/datasets" element={<Datasets />} />
          <Route path="/runs" element={<Runs />} />
          <Route path="/runs/:id" element={<RunDetail />} />
          <Route path="/stats" element={<Stats />} />
          <Route path="/governance" element={<Governance />} />
          <Route path="/system" element={<System />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Layout.Content>
      <TokenModal />
    </Layout>
  )
}
