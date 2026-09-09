import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { api } from '../api/client'

export interface AuthUser {
  id: string
  name: string
  usergroups: number[]
  is_site_admin: boolean
  is_site_manager: boolean
}

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(localStorage.getItem('hirato_token'))
  const user = ref<AuthUser | null>(null)

  const isAuthenticated = computed(() => !!token.value)
  const isSiteAdmin = computed(() => !!user.value?.is_site_admin)
  const isSiteManager = computed(() => !!user.value?.is_site_manager)

  function setToken(newToken: string | null) {
    token.value = newToken
    if (newToken) localStorage.setItem('hirato_token', newToken)
    else localStorage.removeItem('hirato_token')
  }

  async function login(email: string, password: string): Promise<void> {
    const result = await api.post<{ token: string }>('/auth/login', { email, password })
    setToken(result.token)
    await fetchMe()
  }

  async function fetchMe(): Promise<void> {
    user.value = await api.get<AuthUser>('/auth/me')
  }

  function logout(): void {
    setToken(null)
    user.value = null
  }

  return { token, user, isAuthenticated, isSiteAdmin, isSiteManager, login, logout, fetchMe }
})
