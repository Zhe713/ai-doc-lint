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
