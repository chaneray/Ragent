import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { loginApi, registerApi, getUserInfoApi } from '@/api/auth'
import type { User } from '@/types'

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(localStorage.getItem('token'))
  const user = ref<User | null>(null)

  const isLoggedIn = computed(() => !!token.value)

  async function login(account: string, password: string) {
    const res = await loginApi(account, password)
    token.value = res.data.access_token
    localStorage.setItem('token', res.data.access_token)
    await fetchUser()
  }

  async function register(username: string, email: string, password: string) {
    await registerApi(username, email, password)
  }

  async function fetchUser() {
    try {
      const res = await getUserInfoApi()
      user.value = res.data
    } catch {
      logout()
    }
  }

  function logout() {
    token.value = null
    user.value = null
    localStorage.removeItem('token')
  }

  return { token, user, isLoggedIn, login, register, fetchUser, logout }
})
