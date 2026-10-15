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

export interface AdminSettings {
  open_registration: boolean
  data_retention_days: number | null
  llm_daily_quota: number | null
}

export const getAdminSettings = () =>
  client.get<AdminSettings>('/admin/settings').then((r) => r.data)

export const patchAdminSettings = (patch: Partial<AdminSettings>) =>
  client
    .patch<AdminSettings>('/admin/settings', patch)
    .then((r) => r.data)

// ---- W8：审计日志与系统健康 ----

export interface AuditLogItem {
  id: number
  username: string | null
  action: string
  target: string | null
  detail: Record<string, unknown> | null
  ip: string | null
  created_at: string | null
}

export interface AuditLogPage {
  total: number
  items: AuditLogItem[]
}

export const listAuditLogs = (params: { action?: string; limit?: number; offset?: number } = {}) =>
  client.get<AuditLogPage>('/admin/audit-logs', { params }).then((r) => r.data)

export interface SystemStats {
  documents: number
  tasks_total: number
  tasks_by_state: Record<string, number>
  queues: Record<string, number>
  recent_audit: number
  db?: string
  valkey?: string
  minio?: string
}

export const getSystemStats = () =>
  client.get<SystemStats>('/admin/system/stats').then((r) => r.data)
