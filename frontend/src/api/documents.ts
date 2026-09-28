import client from './client'

export interface UploadedTask {
  task_id: string
  document_id: string
  filename: string
  status: string
}

export interface UploadResult {
  group_id: string
  total: number
  tasks: UploadedTask[]
}

export interface TaskGroup {
  id: string
  total: number
  pending: number
  running: number
  succeeded: number
  awaiting: number
  failed: number
  cancelled: number
  finished_at: string | null
  created_at: string
}

export interface TaskEvent {
  event_type: string
  stage: string | null
  message: string | null
  created_at: string
}

export interface TaskItem {
  id: string
  document_id: string
  group_id: string | null
  filename: string
  task_type: string
  status: string
  gate_reason: string | null
  gate_payload: Record<string, unknown> | null
  warnings: unknown[] | null
  stats: Record<string, unknown> | null
  error_code: string | null
  error_message: string | null
  created_at: string
  updated_at: string
  events?: TaskEvent[]
}

export interface GroupDetail {
  group: TaskGroup
  tasks: TaskItem[]
}

export interface UploadOptions {
  doc_type?: string
  checks?: string[]
}

export async function uploadDocuments(
  files: File[],
  options: UploadOptions = {}
): Promise<UploadResult> {
  const form = new FormData()
  files.forEach((f) => form.append('files', f))
  form.append('doc_type', options.doc_type ?? 'auto')
  form.append('checks', (options.checks ?? []).join(','))
  const { data } = await client.post('/documents/upload', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 300000
  })
  return data
}

export async function listGroups(): Promise<TaskGroup[]> {
  const { data } = await client.get('/task-groups')
  return data
}

export async function getGroup(id: string): Promise<GroupDetail> {
  const { data } = await client.get(`/task-groups/${id}`)
  return data
}

export async function getTask(id: string): Promise<TaskItem> {
  const { data } = await client.get(`/tasks/${id}`)
  return data
}

export async function getPreview(id: string): Promise<{
  filename: string
  plaintext: string
  truncated: boolean
  total_chars: number
  stats: Record<string, unknown> | null
}> {
  const { data } = await client.get(`/tasks/${id}/preview`)
  return data
}

export async function cancelTask(id: string): Promise<{ status: string }> {
  const { data } = await client.post(`/tasks/${id}/cancel`)
  return data
}

export async function decideGate(
  id: string,
  action: 'retry_ocr' | 'continue_with_warnings' | 'cancel'
): Promise<{ status: string; action: string }> {
  const { data } = await client.post(`/tasks/${id}/decision`, { action })
  return data
}
