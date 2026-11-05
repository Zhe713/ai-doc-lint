import client from './client'

export interface DiffRow {
  type: 'equal' | 'add' | 'del'
  text: string
  line_a: number | null
  line_b: number | null
}

export interface DiffResponse {
  doc_a: { id: string; filename: string; chars: number }
  doc_b: { id: string; filename: string; chars: number }
  identical: boolean
  auto_bypass: boolean
  bypass_ready: boolean
  stats: { same_lines: number; add_lines: number; del_lines: number; changed_ratio: number }
  truncated: boolean
  rows: DiffRow[]
}

export async function runDocumentDiff(
  docA: string,
  docB: string,
  autoBypass = true
): Promise<DiffResponse> {
  const { data } = await client.get('/compare/diff', {
    params: { doc_a_id: docA, doc_b_id: docB, auto_bypass: autoBypass }
  })
  return data
}

export interface ReleaseResult {
  ok: boolean
  released: {
    id: string
    kind: string
    label: string
    baseline_document_id: string | null
    changed_ratio: number | null
    note: string | null
    created_at: string | null
  }
  diff: { same_lines: number; add_lines: number; del_lines: number; changed_ratio: number }
}

/** 放行：服务端会重新校验差异，只有确实无差异才允许「自动放行」 */
export async function releaseDocument(
  documentId: string,
  baselineDocumentId: string,
  kind: 'diff_auto' | 'manual' = 'diff_auto',
  note?: string
): Promise<ReleaseResult> {
  const { data } = await client.post('/compare/release', {
    document_id: documentId,
    baseline_document_id: baselineDocumentId,
    kind,
    ...(note ? { note } : {})
  })
  return data
}

export async function revokeRelease(documentId: string): Promise<{ ok: boolean; revoked: number }> {
  const { data } = await client.delete(`/compare/release/${documentId}`)
  return data
}
