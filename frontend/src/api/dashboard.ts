import client from './client'

export interface DashboardStats {
  documents: number
  groups: number
  findings_total: number
  findings_by_severity: { error: number; warning: number; info: number }
  /** 问题来源分布：rule=纯规则命中，hybrid=规则+AI 复核，llm=AI 判定（后端必返） */
  findings_by_source: { rule: number; hybrid: number; llm: number }
  findings_pending: number
  findings_resolved: number
  recent_documents: Array<{ id: string; filename: string; created_at: string | null }>
  rule_packs: number
  chunks: number
  embedded_docs: number
}

export async function getDashboardStats(): Promise<DashboardStats> {
  const { data } = await client.get('/dashboard/stats')
  return data
}
