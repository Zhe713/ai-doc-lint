import axios, { AxiosError, type InternalAxiosRequestConfig } from 'axios'
import { ElMessage } from 'element-plus'

import { useAuthStore } from '@/stores/auth'

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

client.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const auth = useAuthStore()
    const original = error.config as InternalAxiosRequestConfig & { _retried?: boolean }
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
    return Promise.reject(error)
  }
)

export default client
