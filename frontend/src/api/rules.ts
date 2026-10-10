import client from './client'

export type PackType = 'format' | 'clause' | 'field' | 'cross'

export interface RulePack {
  id: string
  name: string
  pack_type: PackType
  doc_type: string
  description: string | null
  version: number
  enabled: boolean
  source: string
  yaml_content: string
  created_at: string | null
  updated_at: string | null
}

export interface BuiltinPack {
  name: string
  pack_type: PackType
  doc_type: string
  file: string
}

const PACK_TYPE_LABELS: Record<PackType, string> = {
  format: '格式规则',
  clause: '条款规则',
  field: '字段抽取',
  cross: '交叉勾稽'
}

export function packTypeLabel(t: PackType): string {
  return PACK_TYPE_LABELS[t] || t
}

export async function listBuiltinPacks(): Promise<BuiltinPack[]> {
  const { data } = await client.get('/rules/packs/builtin')
  return data
}

export async function listRulePacks(packType?: PackType): Promise<RulePack[]> {
  const { data } = await client.get('/rules/packs', {
    params: packType ? { pack_type: packType } : {}
  })
  return data
}

export async function createRulePack(body: {
  name: string
  pack_type: PackType
  doc_type: string
  yaml_content: string
  description?: string
  enabled?: boolean
}): Promise<RulePack> {
  const { data } = await client.post('/rules/packs', body)
  return data
}

export async function updateRulePack(
  id: string,
  body: { name?: string; description?: string; yaml_content?: string }
): Promise<RulePack> {
  const { data } = await client.put(`/rules/packs/${id}`, body)
  return data
}

export async function toggleRulePack(id: string, enabled: boolean): Promise<RulePack> {
  const { data } = await client.patch(`/rules/packs/${id}/toggle`, { enabled })
  return data
}

export async function deleteRulePack(id: string): Promise<void> {
  await client.delete(`/rules/packs/${id}`)
}
