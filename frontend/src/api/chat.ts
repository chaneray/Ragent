import client from './client'

export function createSessionApi() {
  return client.post('/sessions')
}

export function getSessionsApi() {
  return client.get('/sessions')
}

export function getSessionApi(id: number) {
  return client.get(`/sessions/${id}`)
}

export function deleteSessionApi(id: number) {
  return client.delete(`/sessions/${id}`)
}
