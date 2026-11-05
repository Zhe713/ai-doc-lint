import client from './client'

export type FindingSource = 'rule' | 'llm' | 'hybrid'

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
  /** 问题来源：rule=纯规则命中，hybrid=规则初筛+大模型复核，llm=大模型语义判定 */
  source?: FindingSource
  /** 大模型给出该结论的理由（source=hybrid/llm 时有值） */
  llm_reason?: string | null
  /** 实际参与判定的模型名 */
  llm_model?: string | null
  created_at: string
}

export const SOURCE_LABELS: Record<FindingSource, string> = {
  rule: '规则命中',
  hybrid: '规则 + AI 复核',
  llm: 'AI 判定'
}

/** Element Plus 标签配色联合类型（原先用 string 导致所有 :type 绑定都无法类型检查） */
export type TagType = 'primary' | 'success' | 'warning' | 'info' | 'danger'

export const SOURCE_TAG_TYPE: Record<FindingSource, TagType> = {
  rule: 'info',
  hybrid: 'warning',
  llm: 'success'
}

/** 「是不是 AI 参与判定的」——报告页用它做过滤与统计 */
export function isAiAssisted(f: Finding): boolean {
  return f.source === 'hybrid' || f.source === 'llm'
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

export interface SkippedCheck {
  checker: string
  label: string
  rules: string[]
  whole_check: boolean
}

export interface ReleaseInfo {
  id: string
  kind: string
  label: string
  baseline_document_id: string | null
  changed_ratio: number | null
  note: string | null
  created_at: string | null
}

/** 审查覆盖率：后端 CoverageOut 的镜像，接口只返回这一份口径 */
export interface Coverage {
  checks_requested: string[]
  checks_executed: string[]
  checks_skipped: SkippedCheck[]
  /** 被「规则停用」抑制的规则（不是没查出，是被关掉了） */
  suppressed_rules: string[]
  checker_degraded: boolean
  checker_warning_detail: string[]
  review_pending: boolean
  review_failed: boolean
  continued_with_warning: boolean
  complete: boolean
  released: ReleaseInfo | null
}

export interface FindingsResult {
  document_id: string
  total: number
  items: Finding[]
  coverage?: Coverage
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

/** 单独取覆盖率（批量矩阵等页面不必拉全量 findings） */
export async function getCoverage(docId: string): Promise<Coverage> {
  const { data } = await client.get(`/documents/${docId}/coverage`)
  return data
}

/** 自动抽取的字段（金额/日期/当事人等），以前只在比对矩阵里露脸 */
export interface DocumentField {
  id: number
  document_id: string
  field_key: string
  field_label: string
  value_type: string | null
  value_text: string | null
  value_number: number | null
  value_date: string | null
  confidence: number | null
  source: string
  location: Record<string, unknown> | null
}

export async function listFields(docId: string): Promise<DocumentField[]> {
  const { data } = await client.get(`/documents/${docId}/fields`)
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

export async function decideSuggestion(
  id: number,
  action: 'confirm' | 'reject'
): Promise<{ ok: boolean; disabled_rule?: { pack_type: string; rule_id: string; scope: string } }> {
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
