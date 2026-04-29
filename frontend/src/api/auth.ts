import client from './client'

export function loginApi(account: string, password: string) {
  return client.post('/auth/login', { account, password })
}

export function registerApi(username: string, email: string, password: string) {
  return client.post('/auth/register', { username, email, password })
}

export function getUserInfoApi() {
  return client.get('/auth/me')
}
