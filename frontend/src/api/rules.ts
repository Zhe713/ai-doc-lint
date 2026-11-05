import client from './client'
import type { TagType } from './findings'

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

export interface BuiltinPackContent {
  name: string
  file: string
  content: unknown
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

export async function getBuiltinPackContent(file: string): Promise<BuiltinPackContent> {
  const { data } = await client.get(`/rules/packs/builtin/${file}`)
  return data
}

export async function listRuleSchemas(): Promise<Record<string, { label: string; item_label?: string; fields: SchemaField[] }>> {
  const { data } = await client.get('/rules/schemas')
  return data.schemas
}

export interface SchemaField {
  key: string
  label: string
  type: string
  required?: boolean
  default?: unknown
  help?: string
  example?: string
  options?: string[]
}

export interface GeneratedPack {
  pack_type: PackType
  doc_type: string
  content: Record<string, unknown>
  model: string
  valid: boolean
}

export async function generateRulePack(body: {
  description: string
  pack_type: PackType
  doc_type: string
}): Promise<GeneratedPack> {
  const { data } = await client.post('/rules/generate', body)
  return data
}

// ---------- 规则「人话」解释 ----------

export type RuleBasis = 'rule' | 'hybrid' | 'llm'

export interface ExplainedRule {
  title: string
  detail: string
  severity: string | null
  severity_label: string
  basis: RuleBasis
  basis_label: string
}

export interface ExplainResult {
  pack_type: PackType
  title: string
  total: number
  items: ExplainedRule[]
  counts: Record<RuleBasis, number>
}

export const BASIS_LABELS: Record<RuleBasis, string> = {
  rule: '规则判定',
  hybrid: '规则 + AI 复核',
  llm: 'AI 语义判定'
}

export const BASIS_TAG_TYPE: Record<RuleBasis, TagType> = {
  rule: 'info',
  hybrid: 'warning',
  llm: 'success'
}

/** 把任意规则包内容翻译成人话（解释口径由后端统一维护） */
export async function explainRulePack(packType: PackType, content: unknown): Promise<ExplainResult> {
  const { data } = await client.post('/rules/explain', { pack_type: packType, content })
  return data
}

/** 内置包的人话解释（直接按文件名取） */
export async function explainBuiltinPack(file: string): Promise<ExplainResult> {
  const { data } = await client.get(`/rules/packs/builtin/${file}/explain`)
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

// ---------- 单条规则停用（内置规则也能真停用） ----------

export interface DisabledRuleItem {
  id: string
  pack_type: string
  rule_id: string
  scope: 'global' | 'user'
  reason: string | null
  created_at: string | null
}

export async function listDisabledRules(): Promise<DisabledRuleItem[]> {
  const { data } = await client.get('/rules/disabled')
  return data.items
}

export async function disableRule(body: {
  pack_type: string
  rule_id: string
  scope?: 'user' | 'global'
  reason?: string
}): Promise<{ ok: boolean }> {
  const { data } = await client.post('/rules/disabled', body)
  return data
}

export async function enableRule(body: {
  pack_type: string
  rule_id: string
  scope?: 'user' | 'global'
}): Promise<{ ok: boolean }> {
  const { data } = await client.delete('/rules/disabled', { params: body })
  return data
}
