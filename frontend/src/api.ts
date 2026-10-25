// 统一请求层：Bearer token 注入 + 401 拦截（由 App 注册弹窗后重试一次）
export function getToken(): string {
  return localStorage.getItem('ab_token') ?? ''
}

export function setToken(t: string): void {
  if (t) localStorage.setItem('ab_token', t)
  else localStorage.removeItem('ab_token')
}

type TokenHandler = () => Promise<string | null>
let unauthorizedHandler: TokenHandler | null = null

export function setUnauthorizedHandler(h: TokenHandler | null): void {
  unauthorizedHandler = h
}

async function handle<T>(res: Response): Promise<T> {
  const data = (await res.json().catch(() => ({}))) as unknown
  if (!res.ok) throw data
  return data as T
}

async function request<T>(path: string, opt: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { ...(opt.headers as Record<string, string> | undefined) }
  if (opt.body) headers['Content-Type'] = 'application/json'
  const token = getToken()
  if (token) headers['Authorization'] = 'Bearer ' + token
  let res = await fetch('/api' + path, { ...opt, headers })
  if (res.status === 401 && unauthorizedHandler) {
    const t = await unauthorizedHandler()
    if (t) {
      setToken(t)
      headers['Authorization'] = 'Bearer ' + t
      res = await fetch('/api' + path, { ...opt, headers })
    }
  }
  return handle<T>(res)
}

export const api = {
  get: <T>(p: string) => request<T>(p),
  post: <T>(p: string, body?: unknown) =>
    request<T>(p, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) }),
  put: <T>(p: string, body?: unknown) =>
    request<T>(p, { method: 'PUT', body: body === undefined ? undefined : JSON.stringify(body) }),
  del: <T>(p: string) => request<T>(p, { method: 'DELETE' }),
}

// 后端错误统一为 {detail: string | object}，转成可读文案
export function errText(e: unknown): string {
  if (e && typeof e === 'object' && 'detail' in e) {
    const d = (e as { detail: unknown }).detail
    return typeof d === 'string' ? d : JSON.stringify(d)
  }
  return typeof e === 'object' ? JSON.stringify(e) : String(e)
}
