import client from './client'

export interface SetupStatus {
  needs_setup: boolean
  open_registration: boolean
}

export interface UserInfo {
  id: string
  username: string
  is_active: boolean
  is_superuser: boolean
  roles: string[]
  created_at: string
}

export interface TokenPair {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
}

export const getSetupStatus = () =>
  client.get<SetupStatus>('/setup/status').then((r) => r.data)

export const createInitialAdmin = (username: string, password: string) =>
  client.post('/setup/admin', { username, password })

export const login = (username: string, password: string) =>
  client.post<TokenPair>('/auth/login', { username, password }).then((r) => r.data)

export const register = (username: string, password: string) =>
  client.post<UserInfo>('/auth/register', { username, password }).then((r) => r.data)

export const refresh = (refresh_token: string) =>
  client.post<TokenPair>('/auth/refresh', { refresh_token }).then((r) => r.data)

export const logout = (accessToken: string, refreshToken: string) =>
  client.post(
    '/auth/logout',
    {},
    {
      headers: {
        Authorization: `Bearer ${accessToken}`,
        'x-refresh-token': refreshToken
      }
    }
  )

export const fetchMe = () => client.get<UserInfo>('/users/me').then((r) => r.data)

export const listUsers = () =>
  client.get<UserInfo[]>('/admin/users').then((r) => r.data)

export const getAdminSettings = () =>
  client.get<{ open_registration: boolean }>('/admin/settings').then((r) => r.data)

export const patchAdminSettings = (open_registration: boolean) =>
  client
    .patch<{ open_registration: boolean }>('/admin/settings', { open_registration })
    .then((r) => r.data)
