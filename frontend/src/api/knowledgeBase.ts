import client from './client'

export function getKnowledgeBasesApi() {
  return client.get('/knowledge-bases')
}

export function createKnowledgeBaseApi(name: string, description: string) {
  return client.post('/knowledge-bases', { name, description })
}

export function getKnowledgeBaseApi(id: number) {
  return client.get(`/knowledge-bases/${id}`)
}

export function deleteKnowledgeBaseApi(id: number) {
  return client.delete(`/knowledge-bases/${id}`)
}
