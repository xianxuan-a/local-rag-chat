import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { getRuntimeAccessToken, setRuntimeAccessToken } from '@/api/auth'
import { authApi } from '@/api/authApi'
import { apiConfig } from '@/api/client'
import { AppError, type AuthenticatedUser } from '@/types'

export const useAuthStore = defineStore('auth', () => {
  type AuthStatus =
    'idle' | 'submitting' | 'authenticated' | 'unauthenticated' | 'error'

  const user = ref<AuthenticatedUser | null>(null)
  const initialized = ref(false)
  const hasAccessToken = ref(
    apiConfig.mode === 'mock' || getRuntimeAccessToken() !== null,
  )
  const status = ref<AuthStatus>(apiConfig.mode === 'mock' ? 'authenticated' : 'idle')
  const authenticating = computed(() => status.value === 'submitting')

  const isAuthenticated = computed(
    () => apiConfig.mode === 'mock' || hasAccessToken.value,
  )

  async function initialize(): Promise<void> {
    if (initialized.value) return
    if (apiConfig.mode === 'mock') {
      status.value = 'authenticated'
      initialized.value = true
      return
    }
    hasAccessToken.value = getRuntimeAccessToken() !== null
    if (!hasAccessToken.value) {
      status.value = 'unauthenticated'
      initialized.value = true
      return
    }
    try {
      user.value = await authApi.getCurrentUser()
      status.value = 'authenticated'
    } catch (error) {
      if (error instanceof AppError && error.status === 401) {
        clearSession()
        return
      }
      status.value = 'error'
      throw error
    } finally {
      initialized.value = true
    }
  }

  async function login(identity: string, password: string): Promise<void> {
    status.value = 'submitting'
    try {
      const session = await authApi.login(identity.trim(), password)
      setRuntimeAccessToken(session.accessToken)
      hasAccessToken.value = true
      user.value = session.user
      initialized.value = true
      status.value = 'authenticated'
    } catch (error) {
      status.value = 'error'
      throw error
    }
  }

  async function register(
    username: string,
    email: string,
    password: string,
  ): Promise<void> {
    status.value = 'submitting'
    try {
      const normalizedUsername = username.trim()
      await authApi.register(normalizedUsername, email.trim() || null, password)
      const session = await authApi.login(normalizedUsername, password)
      setRuntimeAccessToken(session.accessToken)
      hasAccessToken.value = true
      user.value = session.user
      initialized.value = true
      status.value = 'authenticated'
    } catch (error) {
      status.value = 'error'
      throw error
    }
  }

  function clearSession(): void {
    setRuntimeAccessToken(null)
    hasAccessToken.value = apiConfig.mode === 'mock'
    user.value = null
    initialized.value = true
    status.value = apiConfig.mode === 'mock' ? 'authenticated' : 'unauthenticated'
  }

  return {
    user,
    initialized,
    status,
    authenticating,
    isAuthenticated,
    initialize,
    login,
    register,
    clearSession,
  }
})
