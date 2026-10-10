import client from './client'

export interface SearchResult {
  document_id: string
  filename: string
  doc_type: string
  chunk_index: number
  content: string
  distance: number
}

export interface SearchResponse {
  query: string
  total: number
  results: SearchResult[]
}

export interface SimilarDoc {
  document_id: string
  filename: string
  doc_type: string
  distance: number
}

export interface SimilarResponse {
  document_id: string
  total: number
  results: SimilarDoc[]
}

export async function semanticSearch(q: string, limit = 10): Promise<SearchResponse> {
  const { data } = await client.get('/search', { params: { q, limit } })
  return data
}

export async function similarDocuments(
  documentId: string,
  limit = 5
): Promise<SimilarResponse> {
  const { data } = await client.get(`/documents/${documentId}/similar`, {
    params: { limit }
  })
  return data
}
