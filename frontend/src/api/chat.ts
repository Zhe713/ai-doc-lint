import client from './client'

export interface ChatSessionInfo {
  id: string
  title: string
  document_id: string
}

export interface ChatMessageInfo {
  id: number
  role: 'user' | 'assistant'
  content: string
  route_layer?: string
  intent?: string
}

export async function createChatSession(documentId: string): Promise<ChatSessionInfo> {
  const { data } = await client.post('/chat/sessions', { document_id: documentId })
  return data
}

export async function getChatSession(sessionId: string): Promise<{
  id: string
  title: string
  messages: ChatMessageInfo[]
}> {
  const { data } = await client.get(`/chat/sessions/${sessionId}`)
  return data
}

export async function listChatSessions(): Promise<ChatSessionInfo[]> {
  const { data } = await client.get('/chat/sessions')
  return data
}

interface StreamHandlers {
  onDelta: (text: string) => void
  onDone: (messageId: number) => void
  onError: (text: string) => void
}

export async function streamChat(
  sessionId: string,
  content: string,
  handlers: StreamHandlers,
  buttonIntent?: string
): Promise<void> {
  const { useAuthStore } = await import('@/stores/auth')
  const token = useAuthStore().accessToken

  const resp = await fetch(`/api/v1/chat/sessions/${sessionId}/messages`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {})
    },
    body: JSON.stringify({ content, button_intent: buttonIntent ?? null })
  })

  // 非 2xx 时后端返回的是错误 JSON 而非 SSE，需提前终止并回调 onError
  if (!resp.ok) {
    let msg = `请求失败（${resp.status}）`
    try {
      const body = await resp.json()
      if (body?.detail) msg = typeof body.detail === 'string' ? body.detail : msg
    } catch {
      /* 忽略非 JSON 错误体 */
    }
    handlers.onError(msg)
    return
  }

  if (!resp.body) {
    handlers.onError('无响应内容')
    return
  }

  const reader = resp.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const chunks = buffer.split('\n\n')
      buffer = chunks.pop() || ''
      for (const chunk of chunks) {
        const line = chunk.trim()
        if (!line.startsWith('data:')) continue
        const evt = JSON.parse(line.slice(5).trim())
        if (evt.type === 'delta') handlers.onDelta(evt.text)
        else if (evt.type === 'done') handlers.onDone(evt.message_id)
        else if (evt.type === 'error') handlers.onError(evt.text)
      }
    }
  } catch (err) {
    handlers.onError(err instanceof Error ? err.message : '连接中断')
  }
}
