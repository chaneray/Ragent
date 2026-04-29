import client from './client'

export function uploadDocumentApi(knowledgeBaseId: number, file: File) {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('knowledge_base_id', String(knowledgeBaseId))
  return client.post('/documents/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

export function getDocumentsApi(knowledgeBaseId: number) {
  return client.get(`/documents`, { params: { knowledge_base_id: knowledgeBaseId } })
}

export function deleteDocumentApi(documentId: number) {
  return client.delete(`/documents/${documentId}`)
}
