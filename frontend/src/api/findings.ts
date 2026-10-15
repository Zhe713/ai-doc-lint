import client from './client'

export interface Finding {
  id: number
  document_id: string
  task_id: string | null
  checker: string
  rule_id: string
  severity: string
  location: Record<string, unknown> | null
  message: string
  suggestion: string | null
  status: string
  feedback_reason: string | null
  feedback_cause: string | null
  created_at: string
}

export interface DocItem {
  id: string
  filename: string
  ext: string
  doc_type: string
  status: string
  size_bytes: number
  created_at: string
}

export async function listDocuments(limit = 100): Promise<DocItem[]> {
  const { data } = await client.get('/documents', { params: { limit } })
  return data
}

export interface DocFlags {
  continued_with_warning: boolean
  checker_degraded: boolean
  checker_warning_detail: unknown[]
}

export interface FindingsResult {
  document_id: string
  total: number
  items: Finding[]
  doc_flags?: DocFlags
}

export async function listFindings(
  docId: string,
  filters: { checker?: string; severity?: string; status?: string } = {}
): Promise<FindingsResult> {
  const { data } = await client.get(`/documents/${docId}/findings`, {
    params: filters
  })
  return data
}

export type FindingStatus = 'open' | 'ignored' | 'fixed'
export type FeedbackReason = 'false_positive' | 'confirmed' | 'fixed_by_user' | null
// W7-5 误报原因标签（与后端 FEEDBACK_CAUSES 对齐）
export const FEEDBACK_CAUSE_OPTIONS: { value: string; label: string }[] = [
  { value: 'lexicon', label: '词表外合法用法（专有名词/方言等）' },
  { value: 'rule_strict', label: '规则误判/过于严格' },
  { value: 'context', label: '上下文不符（未考虑语境）' },
  { value: 'other', label: '其他' }
]
export type FeedbackCause = 'lexicon' | 'rule_strict' | 'context' | 'other' | null

export async function setFindingStatus(
  id: number,
  status: FindingStatus,
  feedback_reason?: FeedbackReason,
  feedback_cause?: FeedbackCause
): Promise<Finding> {
  const { data } = await client.patch(`/findings/${id}`, {
    status,
    ...(feedback_reason ? { feedback_reason } : {}),
    ...(feedback_cause ? { feedback_cause } : {})
  })
  return data
}

// ---------- W7 学习闭环 ----------

export interface FeedbackStat {
  checker: string
  rule_id: string
  hit_count: number
  false_count: number
  confirmed_count: number
  false_rate: number
  last_feedback_at: string | null
  // W7-5 误报原因分布：{ cause_code: count }
  causes: Record<string, number>
}

export interface SuggestionItem {
  id: number
  checker: string
  rule_id: string
  reason: string
  hit_count: number
  false_count: number
  false_rate: number
  status: string
  created_at: string | null
  resolved_at: string | null
}

export interface LearningLogItem {
  id: number
  action: string
  detail: Record<string, unknown> | null
  created_at: string | null
}

export interface TuningSummary {
  ok: boolean
  trigger: string
  whitelist_added: number
  whitelist_total: number
  whitelist_pending: string[]
  suggested_rules: string[]
  at: string
}

export async function getLearningFeedback(): Promise<FeedbackStat[]> {
  const { data } = await client.get('/admin/learning/feedback')
  return data.items
}

export async function getLearningSuggestions(status = 'pending'): Promise<SuggestionItem[]> {
  const { data } = await client.get('/admin/learning/suggestions', { params: { status } })
  return data.items
}

export async function decideSuggestion(id: number, action: 'confirm' | 'reject'): Promise<{ ok: boolean; disabled_pack: string | null }> {
  const { data } = await client.post(`/admin/learning/suggestions/${id}/decision`, { action })
  return data
}

export async function getLearningLogs(limit = 50): Promise<LearningLogItem[]> {
  const { data } = await client.get('/admin/learning/logs', { params: { limit } })
  return data.items
}

export async function runTuningManually(): Promise<TuningSummary> {
  const { data } = await client.post('/admin/learning/run-tuning')
  return data
}
