import axios, { AxiosError, type InternalAxiosRequestConfig } from 'axios'
import { ElMessage } from 'element-plus'

import { useAuthStore } from '@/stores/auth'

declare module 'axios' {
  export interface AxiosRequestConfig {
    /** 置 true 时不弹全局错误提示（用于后台轮询等不希望打扰用户的请求） */
    silent?: boolean
  }
}

const client = axios.create({
  baseURL: '/api/v1',
  timeout: 30000
})

client.interceptors.request.use((config) => {
  const auth = useAuthStore()
  if (auth.accessToken) {
    config.headers.Authorization = `Bearer ${auth.accessToken}`
  }
  return config
})

// ---- 401 静默刷新：同一时刻只刷新一次，并发请求排队等待 ----
let isRefreshing = false
let pendingQueue: Array<(token: string | null) => void> = []

function onRefreshed(token: string | null) {
  pendingQueue.forEach((cb) => cb(token))
  pendingQueue = []
}

// ---- 统一错误提示：避免每个页面各写一份 catch，也避免"失败却毫无反应" ----
// 同一句话 4 秒内只提示一次，防止轮询类请求把用户刷屏。
const lastToastAt = new Map<string, number>()

function toastOnce(message: string) {
  const now = Date.now()
  if (now - (lastToastAt.get(message) ?? 0) < 4000) return
  lastToastAt.set(message, now)
  ElMessage({ type: 'error', message, duration: 4000, showClose: true })
}

function describeError(error: AxiosError): string {
  const status = error.response?.status
  const data = error.response?.data as unknown
  const detail =
    data && typeof data === 'object' && 'detail' in data
      ? (data as { detail: unknown }).detail
      : undefined
  if (typeof detail === 'string' && detail.trim()) return detail
  // FastAPI 参数校验错误是数组
  if (Array.isArray(detail) && detail.length) {
    const first = detail[0] as { msg?: string; loc?: unknown[] }
    if (first?.msg) {
      const where = Array.isArray(first.loc) ? first.loc.slice(-1)[0] : ''
      return where ? `${String(where)}：${first.msg}` : first.msg
    }
  }
  if (error.code === 'ECONNABORTED') return '请求超时，请稍后重试'
  if (!error.response) return '无法连接服务器，请确认服务是否正常运行'
  if (status === 403) return '没有权限执行该操作'
  if (status === 404) return '请求的内容不存在或已被删除'
  if (status === 413) return '文件过大，超出服务端限制'
  if (status === 429) return '操作过于频繁或已达配额，请稍后再试'
  if (status && status >= 500) return '服务器处理失败，请稍后重试或查看系统健康'
  return `请求失败（HTTP ${status ?? '未知'}）`
}

client.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const auth = useAuthStore()
    const original = error.config as InternalAxiosRequestConfig & { _retried?: boolean; silent?: boolean }
    const url = original?.url ?? ''

    const isAuthEndpoint =
      url.includes('/auth/login') ||
      url.includes('/auth/refresh') ||
      url.includes('/auth/register') ||
      url.includes('/setup')

    if (error.response?.status === 401 && !original._retried && !isAuthEndpoint) {
      if (isRefreshing) {
        return new Promise((resolve, reject) => {
          pendingQueue.push((token) => {
            if (!token) {
              reject(error)
              return
            }
            original.headers.Authorization = `Bearer ${token}`
            resolve(client(original))
          })
        })
      }

      original._retried = true
      isRefreshing = true
      try {
        const newToken = await auth.tryRefresh()
        if (!newToken) {
          onRefreshed(null)
          auth.clearLocal()
          ElMessage.error('登录已过期，请重新登录')
          const redirect = encodeURIComponent(window.location.pathname + window.location.search)
          window.location.href = `/login?redirect=${redirect}`
          return Promise.reject(error)
        }
        onRefreshed(newToken)
        original.headers.Authorization = `Bearer ${newToken}`
        return client(original)
      } finally {
        isRefreshing = false
      }
    }
    // 401 已由上面统一跳登录，不再重复提示；其余错误统一兜底提示
    if (error.response?.status !== 401 && !original?.silent) {
      toastOnce(describeError(error))
    }
    return Promise.reject(error)
  }
)

export default client
