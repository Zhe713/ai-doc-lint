import { ref, onUnmounted } from 'vue'

import { useAuthStore } from '@/stores/auth'

export interface ProgressEvent {
  task_id: string
  group_id: string | null
  user_id: string
  event_type: string
  stage: string | null
  message: string | null
  payload: Record<string, unknown>
}

/**
 * 任务进度 WebSocket：access token 走查询参数。
 * 断线指数退避重连；调用方应同时保留 2s 轮询作为兜底（WS 不通也不影响进度）。
 */
export function useTaskProgress(onEvent: (e: ProgressEvent) => void) {
  const connected = ref(false)
  let ws: WebSocket | null = null
  let retry = 0
  let closed = false
  let timer: number | undefined

  const auth = useAuthStore()

  function connect() {
    if (closed) return
    const token = auth.accessToken
    if (!token) return
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const url = `${proto}://${window.location.host}/api/v1/ws?token=${encodeURIComponent(token)}`
    ws = new WebSocket(url)

    ws.onopen = () => {
      connected.value = true
      retry = 0
    }
    ws.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data) as ProgressEvent
        if (data.event_type) onEvent(data)
      } catch {
        // 忽略非 JSON / 心跳
      }
    }
    ws.onclose = () => {
      connected.value = false
      if (closed) return
      retry += 1
      timer = window.setTimeout(connect, Math.min(1000 * 2 ** retry, 15000))
    }
    ws.onerror = () => ws?.close()
  }

  function close() {
    closed = true
    if (timer) window.clearTimeout(timer)
    ws?.close()
  }

  connect()
  onUnmounted(close)

  return { connected }
}
