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

export async function listFindings(
  docId: string,
  filters: { checker?: string; severity?: string; status?: string } = {}
): Promise<{ document_id: string; total: number; items: Finding[] }> {
  const { data } = await client.get(`/documents/${docId}/findings`, {
    params: filters
  })
  return data
}

export async function setFindingStatus(
  id: number,
  status: 'open' | 'ignored' | 'fixed'
): Promise<Finding> {
  const { data } = await client.patch(`/findings/${id}`, { status })
  return data
}
