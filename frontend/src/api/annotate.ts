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

function filenameFromDisposition(disposition: string | undefined): string {
  if (!disposition) {
    return '批注版'
  }
  const utf8Match = disposition.match(/filename\*=UTF-8''([^;]+)/i)
  if (utf8Match) {
    return decodeURIComponent(utf8Match[1])
  }
  const plainMatch = disposition.match(/filename="?([^";]+)"?/i)
  if (plainMatch) {
    return plainMatch[1]
  }
  return '批注版'
}

export async function downloadAnnotated(taskId: string): Promise<void> {
  const response = await client.get(`/tasks/${taskId}/artifact`, {
    responseType: 'blob'
  })
  const blob = response.data as Blob
  const url = window.URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filenameFromDisposition(response.headers['content-disposition'])
  document.body.appendChild(a)
  a.click()
  a.remove()
  window.URL.revokeObjectURL(url)
}
