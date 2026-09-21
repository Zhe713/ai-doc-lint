import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import * as authApi from '@/api/auth'
import type { SetupStatus, UserInfo } from '@/api/auth'

const ACCESS_KEY = 'aidoc_access_token'
const REFRESH_KEY = 'aidoc_refresh_token'

export const useAuthStore = defineStore('auth', () => {
  const accessToken = ref<string>(localStorage.getItem(ACCESS_KEY) ?? '')
  const refreshToken = ref<string>(localStorage.getItem(REFRESH_KEY) ?? '')
  const user = ref<UserInfo | null>(null)

  const needsSetup = ref<boolean | null>(null)
  const openRegistration = ref<boolean>(true)
  const bootstrapped = ref(false)

  const isLoggedIn = computed(() => !!accessToken.value)
  const isAdmin = computed(
    () => !!user.value && (user.value.is_superuser || user.value.roles.includes('admin'))
  )

  function setTokens(pair: { access_token: string; refresh_token: string }) {
    accessToken.value = pair.access_token
    refreshToken.value = pair.refresh_token
    localStorage.setItem(ACCESS_KEY, pair.access_token)
    localStorage.setItem(REFRESH_KEY, pair.refresh_token)
  }

  function clearLocal() {
    accessToken.value = ''
    refreshToken.value = ''
    user.value = null
    localStorage.removeItem(ACCESS_KEY)
    localStorage.removeItem(REFRESH_KEY)
  }

  async function bootstrap(): Promise<SetupStatus> {
    const status = await authApi.getSetupStatus()
    needsSetup.value = status.needs_setup
    openRegistration.value = status.open_registration
    bootstrapped.value = true
    if (accessToken.value) {
      try {
        user.value = await authApi.fetchMe()
      } catch {
        clearLocal()
      }
    }
    return status
  }

  async function login(username: string, password: string) {
    const pair = await authApi.login(username, password)
    setTokens(pair)
    user.value = await authApi.fetchMe()
  }

  async function register(username: string, password: string) {
    return authApi.register(username, password)
  }

  async function tryRefresh(): Promise<string | null> {
    if (!refreshToken.value) return null
    try {
      const pair = await authApi.refresh(refreshToken.value)
      setTokens(pair)
      return pair.access_token
    } catch {
      clearLocal()
      return null
    }
  }

  async function logout() {
    try {
      if (accessToken.value && refreshToken.value) {
        await authApi.logout(accessToken.value, refreshToken.value)
      }
    } finally {
      clearLocal()
    }
  }

  return {
    accessToken,
    refreshToken,
    user,
    needsSetup,
    openRegistration,
    bootstrapped,
    isLoggedIn,
    isAdmin,
    bootstrap,
    login,
    register,
    tryRefresh,
    logout,
    clearLocal,
    setTokens
  }
})
