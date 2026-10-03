import client from './client'

export async function requestAnnotated(docId: string): Promise<{
  task_id: string
  document_id: string
  status: string
}> {
  const { data } = await client.post(`/documents/${docId}/annotate`)
  return data
}

export function artifactDownloadUrl(taskId: string): string {
  return `/api/v1/tasks/${taskId}/artifact`
}

export async function downloadAnnotated(taskId: string): Promise<void> {
  const { data } = await client.get(`/tasks/${taskId}/artifact`, {
    responseType: 'blob'
  })
  const url = window.URL.createObjectURL(data as Blob)
  const a = document.createElement('a')
  a.href = url
  a.download = '批注版.docx'
  document.body.appendChild(a)
  a.click()
  a.remove()
  window.URL.revokeObjectURL(url)
}
