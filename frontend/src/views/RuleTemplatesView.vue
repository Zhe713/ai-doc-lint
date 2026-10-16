<template>
  <div>
    <el-row :gutter="16" style="margin-bottom: 16px">
      <el-col :span="10">
        <el-card shadow="never">
          <template #header><b>内置规则包</b></template>
          <el-table :data="builtins" size="small" border>
            <el-table-column prop="name" label="名称" min-width="150" />
            <el-table-column label="类型" width="100">
              <template #default="{ row }">
                <el-tag size="small">{{ packTypeLabel(row.pack_type) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="doc_type" label="文档类型" width="95" />
            <el-table-column label="操作" width="100" fixed="right">
              <template #default="{ row }">
                <el-button size="small" link type="primary" @click="onCopyBuiltin(row)">
                  复制为自定义
                </el-button>
              </template>
            </el-table-column>
          </el-table>
          <el-alert style="margin-top: 12px" type="info" :closable="false"
            title="内置规则包仅作参考模板，点击「复制为自定义」即可在右侧表单中修改后另存，用于定制自身业务的审查规则。" />
        </el-card>
      </el-col>
      <el-col :span="14">
        <el-card shadow="never">
          <template #header><b>创建自定义规则包（可视化配置，无需写代码）</b></template>
          <el-form label-width="90px" :model="form" size="small">
            <el-form-item label="包名称">
              <el-input v-model="form.name" placeholder="如：本公司付款条款审查包" />
            </el-form-item>
            <el-form-item label="类型">
              <el-select v-model="form.pack_type" style="width: 100%" @change="onPackTypeChange">
                <el-option v-for="t in packTypes" :key="t" :label="packTypeLabel(t)" :value="t" />
              </el-select>
            </el-form-item>
            <el-form-item label="文档类型">
              <el-input v-model="form.doc_type" placeholder="contract（格式规则请填 global）" />
            </el-form-item>
            <el-form-item label="说明">
              <el-input v-model="form.description" placeholder="可选" />
            </el-form-item>
            <el-form-item v-if="form.pack_type === 'clause'" label="条款">
              <div class="row-editor">
                <div v-for="(c, i) in visualClauses" :key="i" class="row-line">
                  <el-input v-model="c.name" size="small" placeholder="条款名称，如：付款期限" style="width: 170px" />
                  <el-input v-model="c.strong" size="small" placeholder="必备关键词（逗号分隔）" />
                  <el-input v-model="c.weak" size="small" placeholder="弱信号词（可选）" style="width: 120px" />
                  <el-select v-model="c.severity" size="small" style="width: 85px">
                    <el-option label="错误" value="error" />
                    <el-option label="警告" value="warning" />
                    <el-option label="提示" value="info" />
                  </el-select>
                  <el-button size="small" type="danger" plain @click="visualClauses.splice(i, 1)">删除</el-button>
                </div>
                <el-button size="small" @click="visualClauses.push({ name: '', strong: '', weak: '', severity: 'error' })">
                  + 添加一条条款
                </el-button>
              </div>
            </el-form-item>
            <el-form-item v-if="form.pack_type === 'field'" label="字段">
              <div class="row-editor">
                <div v-for="(c, i) in fieldRows" :key="i" class="row-line">
                  <el-input v-model="c.key" size="small" placeholder="字段键，如 amount_digits" style="width: 150px" />
                  <el-input v-model="c.label" size="small" placeholder="中文名，如：金额小写" style="width: 120px" />
                  <el-select v-model="c.type" size="small" style="width: 100px">
                    <el-option v-for="o in ['text', 'number', 'date', 'money', 'party']" :key="o" :label="o" :value="o" />
                  </el-select>
                  <el-input v-model="c.patterns" size="small" placeholder="抽取正则（逗号分隔）" />
                  <el-button size="small" type="danger" plain @click="fieldRows.splice(i, 1)">删除</el-button>
                </div>
                <el-button size="small" @click="fieldRows.push({ key: '', label: '', type: 'text', required: true, patterns: '' })">
                  + 添加一个字段
                </el-button>
              </div>
            </el-form-item>
            <el-form-item v-if="form.pack_type === 'cross'" label="勾稽规则">
              <div class="row-editor">
                <div v-for="(c, i) in crossRows" :key="i" class="row-line">
                  <el-input v-model="c.id" size="small" placeholder="规则 ID，如 amount.consistency" style="width: 160px" />
                  <el-input v-model="c.name" size="small" placeholder="规则名称，如：大小写金额一致" style="width: 160px" />
                  <el-input v-model="c.fields" size="small" placeholder="关联字段（逗号分隔）" />
                  <el-select v-model="c.severity" size="small" style="width: 85px">
                    <el-option label="错误" value="error" />
                    <el-option label="警告" value="warning" />
                    <el-option label="提示" value="info" />
                  </el-select>
                  <el-button size="small" type="danger" plain @click="crossRows.splice(i, 1)">删除</el-button>
                </div>
                <el-button size="small" @click="crossRows.push({ id: '', name: '', fields: '', severity: 'error', description: '' })">
                  + 添加一条勾稽规则
                </el-button>
              </div>
            </el-form-item>
            <template v-if="form.pack_type === 'format'">
              <el-form-item v-for="f in formatFields" :key="f.key" :label="f.label">
                <el-input v-if="f.type === 'string'" v-model="formatModel[f.key]" size="small" />
                <el-input v-else-if="f.type === 'number'" v-model.number="formatModel[f.key]" size="small" style="width: 160px" />
                <el-input v-else-if="f.type === 'string[]'" :model-value="arrToText(formatModel[f.key])"
                  @update:model-value="(v: string) => (formatModel[f.key] = textToArr(v))" size="small" placeholder="逗号分隔" />
                <el-input v-else-if="f.type === 'number[]'" :model-value="arrToText(formatModel[f.key])"
                  @update:model-value="(v: string) => (formatModel[f.key] = numArr(v))" size="small" placeholder="逗号分隔，如 210, 297" />
                <el-switch v-else-if="f.type === 'boolean'" v-model="formatModel[f.key]" />
                <el-select v-else-if="f.type === 'select'" v-model="formatModel[f.key]" size="small" style="width: 160px">
                  <el-option v-for="o in f.options" :key="o" :label="o" :value="o" />
                </el-select>
                <div v-if="f.help" class="hint">{{ f.help }}</div>
              </el-form-item>
            </template>
            <el-form-item>
              <el-button type="primary" :loading="uploading" @click="onUpload">保存并启用</el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-col>
    </el-row>

    <el-card shadow="never">
      <template #header><b>自定义规则包（{{ packs.length }}）</b></template>
      <el-table :data="packs" size="small" border>
        <el-table-column prop="name" label="名称" min-width="150" />
        <el-table-column label="类型" width="110">
          <template #default="{ row }">
            <el-tag size="small">{{ packTypeLabel(row.pack_type) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="doc_type" label="文档类型" width="100" />
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.enabled ? 'success' : 'info'" size="small">
              {{ row.enabled ? '启用' : '停用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="version" label="版本" width="70" />
        <el-table-column prop="description" label="说明" min-width="150" show-overflow-tooltip />
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="onToggle(row)">
              {{ row.enabled ? '停用' : '启用' }}
            </el-button>
            <el-button size="small" type="danger" plain @click="onDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-alert style="margin-top: 12px" type="info" :closable="false"
        title="启用的自定义包优先于内置包即时生效；停用/删除后自动回落内置规则。" />
    </el-card>
  </div>
</template>
<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import {
  type BuiltinPack,
  type PackType,
  type RulePack,
  type SchemaField,
  createRulePack,
  deleteRulePack,
  getBuiltinPackContent,
  listBuiltinPacks,
  listRulePacks,
  listRuleSchemas,
  packTypeLabel,
  toggleRulePack
} from '@/api/rules'

const packTypes: PackType[] = ['format', 'clause', 'field', 'cross']
const builtins = ref<BuiltinPack[]>([])
const packs = ref<RulePack[]>([])
const uploading = ref(false)
const formatFields = ref<SchemaField[]>([])

interface VisualClause { name: string; strong: string; weak: string; severity: string }
interface FieldRow { key: string; label: string; type: string; required: boolean; patterns: string }
interface CrossRow { id: string; name: string; fields: string; severity: string; description: string }

const visualClauses = ref<VisualClause[]>([])
const fieldRows = ref<FieldRow[]>([])
const crossRows = ref<CrossRow[]>([])
const formatModel = ref<Record<string, unknown>>({})

const form = ref({
  name: '',
  pack_type: 'clause' as PackType,
  doc_type: 'contract',
  description: '',
  yaml_content: ''
})

const split = (s: string) => s.split(/[,，、;\s]+/).map((x) => x.trim()).filter(Boolean)
const arrToText = (v: unknown) => (Array.isArray(v) ? v.join(', ') : '')
const textToArr = (v: string) => v.split(/[,，、;\s]+/).map((x) => x.trim()).filter(Boolean)
const numArr = (v: string) => textToArr(v).map((x) => Number(x))

function setPath(obj: Record<string, unknown>, path: string, value: unknown) {
  const keys = path.split('.')
  let cur = obj
  for (let i = 0; i < keys.length - 1; i += 1) {
    if (typeof cur[keys[i]] !== 'object' || cur[keys[i]] === null) cur[keys[i]] = {}
    cur = cur[keys[i]] as Record<string, unknown>
  }
  cur[keys[keys.length - 1]] = value
}

function getPath(obj: Record<string, unknown>, path: string): unknown {
  return path.split('.').reduce<unknown>((acc, k) => {
    if (acc && typeof acc === 'object') return (acc as Record<string, unknown>)[k]
    return undefined
  }, obj)
}

function onPackTypeChange() {
  resetEditors()
}

function resetEditors() {
  visualClauses.value = [{ name: '', strong: '', weak: '', severity: 'error' }]
  fieldRows.value = [{ key: '', label: '', type: 'text', required: true, patterns: '' }]
  crossRows.value = [{ id: '', name: '', fields: '', severity: 'error', description: '' }]
  formatModel.value = {}
}

function resetForm() {
  form.value = { name: '', pack_type: 'clause', doc_type: 'contract', description: '', yaml_content: '' }
  resetEditors()
}

/** 复制内置包内容到对应可视化编辑器 */
async function onCopyBuiltin(row: BuiltinPack) {
  try {
    const resp = await getBuiltinPackContent(row.file)
    const content = (typeof resp.content === 'string' ? JSON.parse(resp.content) : resp.content) as Record<string, unknown>
    form.value.name = `我的${row.name}`
    form.value.pack_type = row.pack_type
    form.value.doc_type = row.doc_type
    form.value.description = ''
    resetEditors()
    if (row.pack_type === 'clause') {
      const clauses = (content.clauses as Array<Record<string, unknown>>) || []
      visualClauses.value = clauses.map((c) => ({
        name: String(c.name || ''),
        strong: (c.strong as string[])?.join(', ') || '',
        weak: (c.weak as string[])?.join(', ') || '',
        severity: String(c.severity || 'error')
      }))
    } else if (row.pack_type === 'field') {
      const fields = (content.fields as Array<Record<string, unknown>>) || []
      fieldRows.value = fields.map((f) => ({
        key: String(f.key || ''),
        label: String(f.label || ''),
        type: String(f.type || 'text'),
        required: Boolean(f.required),
        patterns: (f.patterns as string[])?.join(', ') || ''
      }))
    } else if (row.pack_type === 'cross') {
      const checks = (content.checks as Array<Record<string, unknown>>) || []
      crossRows.value = checks.map((c) => ({
        id: String(c.id || ''),
        name: String(c.name || ''),
        fields: (c.fields as string[])?.join(', ') || '',
        severity: String(c.severity || 'error'),
        description: String(c.description || '')
      }))
    } else {
      formatFields.value = (await listRuleSchemas()).format.fields
      for (const f of formatFields.value) {
        formatModel.value[f.key] = getPath(content, f.key) ?? f.default
      }
    }
    ElMessage.success(`已载入「${row.name}」，可在右侧修改后保存`)
  } catch {
    ElMessage.error('载入内置规则包失败')
  }
}

/** 可视化表单 → JSON 内容 */
function buildJsonContent(): string {
  if (form.value.pack_type === 'clause') {
    const clauses = visualClauses.value
      .filter((r) => r.name.trim() && split(r.strong).length)
      .map((r, i) => ({
        id: `custom_${i + 1}`,
        name: r.name.trim(),
        required: true,
        severity: r.severity || 'error',
        strong: split(r.strong),
        weak: split(r.weak)
      }))
    return JSON.stringify({ version: 1, doc_types: [form.value.doc_type || 'contract'], clauses }, null, 2)
  }
  if (form.value.pack_type === 'field') {
    const fields = fieldRows.value
      .filter((r) => r.key.trim() && r.label.trim())
      .map((r) => ({
        key: r.key.trim(),
        label: r.label.trim(),
        type: r.type,
        required: r.required,
        patterns: split(r.patterns)
      }))
    return JSON.stringify({ version: 1, doc_types: [form.value.doc_type || 'contract'], fields }, null, 2)
  }
  if (form.value.pack_type === 'cross') {
    const checks = crossRows.value
      .filter((r) => r.id.trim() && r.fields.trim())
      .map((r) => ({
        id: r.id.trim(),
        name: r.name.trim(),
        fields: split(r.fields),
        severity: r.severity || 'error',
        description: r.description.trim() || undefined
      }))
    return JSON.stringify({ version: 1, doc_types: [form.value.doc_type || 'contract'], checks }, null, 2)
  }
  const root: Record<string, unknown> = { version: 1 }
  for (const f of formatFields.value) {
    setPath(root, f.key, formatModel.value[f.key])
  }
  return JSON.stringify(root, null, 2)
}

async function load() {
  const [b, p] = await Promise.all([listBuiltinPacks(), listRulePacks()])
  builtins.value = b
  packs.value = p
  formatFields.value = (await listRuleSchemas()).format.fields
}

function onUpload() {
  if (!form.value.name.trim()) {
    ElMessage.warning('请填写包名称')
    return
  }
  const json = buildJsonContent()
  if (form.value.pack_type === 'clause' && !json.includes('"clauses": [')) {
    ElMessage.warning('请至少填写一条条款：条款名称 + 必备关键词')
    return
  }
  if (form.value.pack_type === 'field' && !json.includes('"fields": [')) {
    ElMessage.warning('请至少添加一个字段：字段键 + 中文名')
    return
  }
  if (form.value.pack_type === 'cross' && !json.includes('"checks": [')) {
    ElMessage.warning('请至少添加一条勾稽规则：规则 ID + 关联字段')
    return
  }
  uploading.value = true
  createRulePack({
    name: form.value.name.trim(),
    pack_type: form.value.pack_type,
    doc_type: form.value.doc_type.trim() || 'contract',
    yaml_content: json,
    description: form.value.description.trim() || undefined
  })
    .then(() => {
      ElMessage.success('保存成功，已生效')
      resetForm()
      load()
    })
    .catch((e: { response?: { data?: { detail?: string } } }) => {
      ElMessage.error(e.response?.data?.detail || '保存失败')
    })
    .finally(() => {
      uploading.value = false
    })
}

async function onToggle(row: RulePack) {
  await toggleRulePack(row.id, !row.enabled)
  ElMessage.success(row.enabled ? '已停用' : '已启用')
  load()
}

async function onDelete(row: RulePack) {
  await ElMessageBox.confirm(`确认删除规则包「${row.name}」？`, '提示', { type: 'warning' })
  await deleteRulePack(row.id)
  ElMessage.success('已删除')
  load()
}

onMounted(() => {
  load()
  resetForm()
})
</script>

<style scoped>
.row-editor {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.row-line {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}
.hint {
  font-size: 12px;
  color: #909399;
  line-height: 1.6;
}
</style>
