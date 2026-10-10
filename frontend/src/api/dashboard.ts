import client from './client'

export interface DashboardStats {
  documents: number
  groups: number
  findings_total: number
  findings_by_severity: { error: number; warning: number; info: number }
  rule_packs: number
}

export async function getDashboardStats(): Promise<DashboardStats> {
  const { data } = await client.get('/dashboard/stats')
  return data
}
