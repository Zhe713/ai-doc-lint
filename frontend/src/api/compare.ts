import client from './client'

export interface CompareGroup {
  id: string
  name: string
  status: string
  doc_count: number
  stats: Record<string, unknown> | null
  created_at: string | null
  finished_at: string | null
}

export interface CompareFinding {
  id: number
  rule_id: string
  severity: string
  message: string
  suggestion: string | null
  document_id: string
  related_document_id: string | null
}

export interface CompareMatrixCell {
  value_text: string | null
  value_number: number | null
  value_date: string | null
  source: string
  confidence: number
}

export interface CompareGroupDetail extends CompareGroup {
  documents: Array<{
    id: string
    filename: string
    doc_type: string
    status: string
  }>
  matrix: Record<string, Record<string, CompareMatrixCell>>
  findings: CompareFinding[]
}

export async function listCompareGroups(): Promise<CompareGroup[]> {
  const { data } = await client.get('/compare-groups')
  return data
}

export async function createCompareGroup(
  name: string,
  documentIds: string[]
): Promise<CompareGroup> {
  const { data } = await client.post('/compare-groups', {
    name,
    document_ids: documentIds
  })
  return data
}

export async function getCompareGroup(id: string): Promise<CompareGroupDetail> {
  const { data } = await client.get(`/compare-groups/${id}`)
  return data
}

export async function triggerCompare(
  id: string
): Promise<{ task_id: string; group_id: string; status: string }> {
  const { data } = await client.post(`/compare-groups/${id}/compare`)
  return data
}

export async function deleteCompareGroup(id: string): Promise<void> {
  await client.delete(`/compare-groups/${id}`)
}
