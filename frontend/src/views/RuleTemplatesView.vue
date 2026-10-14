<template>
  <div>
    <el-row :gutter="16" style="margin-bottom: 16px">
      <el-col :span="12">
        <el-card shadow="never">
          <template #header><b>内置规则包（只读）</b></template>
          <el-table :data="builtins" size="small" border>
            <el-table-column prop="name" label="名称" min-width="160" />
            <el-table-column label="类型" width="110">
              <template #default="{ row }">
                <el-tag size="small">{{ packTypeLabel(row.pack_type) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="doc_type" label="文档类型" width="100" />
            <el-table-column prop="file" label="文件" min-width="180" />
          </el-table>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card shadow="never">
          <template #header><b>上传自定义规则包</b></template>
          <el-form label-width="90px" :model="form" size="small">
            <el-form-item label="包名称">
              <el-input v-model="form.name" placeholder="如：付款条款增强包" />
            </el-form-item>
            <el-form-item label="类型">
              <el-select v-model="form.pack_type" style="width: 100%">
                <el-option v-for="t in packTypes" :key="t" :label="packTypeLabel(t)" :value="t" />
              </el-select>
            </el-form-item>
            <el-form-item label="文档类型">
              <el-input v-model="form.doc_type" placeholder="contract（格式规则请填 global）" />
            </el-form-item>
            <el-form-item label="说明">
              <el-input v-model="form.description" placeholder="可选" />
            </el-form-item>
            <el-form-item v-if="form.pack_type === 'clause'" label="配置方式">
              <el-radio-group v-model="mode" size="small">
                <el-radio-button value="visual">可视化配置</el-radio-button>
                <el-radio-button value="yaml">高级（直接写规则）</el-radio-button>
              </el-radio-group>
            </el-form-item>
            <template v-if="form.pack_type === 'clause' && mode === 'visual'">
              <el-form-item label="条款规则">
                <div class="clause-editor">
                  <div v-for="(c, i) in visualClauses" :key="i" class="clause-row">
                    <el-input v-model="c.name" size="small" placeholder="条款名称，如：付款期限" style="width: 180px" />
                    <el-input v-model="c.strong" size="small" placeholder="必备关键词，逗号分隔，如：付款, 支付" />
                    <el-input v-model="c.weak" size="small" placeholder="弱信号关键词（可选），如：结算" style="width: 140px" />
                    <el-select v-model="c.severity" size="small" style="width: 90px">
                      <el-option label="错误" value="error" />
                      <el-option label="警告" value="warning" />
                      <el-option label="提示" value="info" />
                    </el-select>
                    <el-button size="small" type="danger" plain @click="visualClauses.splice(i, 1)">删除</el-button>
                  </div>
                  <el-button size="small" @click="addClause">+ 添加一条条款</el-button>
                  <div class="clause-hint">
                    缺少必备关键词时报告缺失；同时存在弱信号但无法确认时才会调用智能审查。
                  </div>
                </div>
              </el-form-item>
            </template>
            <el-form-item v-if="form.pack_type !== 'clause' || mode === 'yaml'" label="规则内容">
              <el-input v-model="form.yaml_content" type="textarea" :rows="8"
                :placeholder="form.pack_type === 'clause'
                  ? 'version: 1\nclauses:\n  - id: xxx\n    name: 条款名\n    strong: [关键词]\n    weak: [弱关键词]'
                  : form.pack_type === 'format'
                    ? 'version: 1\npage:\n  size:\n    expected_mm: [210, 297]\n  ...（格式包请参照内置包结构）'
                    : form.pack_type === 'field'
                      ? 'version: 1\nfields:\n  - key: xxx\n    label: 字段名\n    type: text\n    patterns: [正则]'
                      : 'version: 1\nchecks:\n  - id: xxx\n    name: 勾稽项\n    fields: [a, b]\n    severity: error'" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="uploading" @click="onUpload">上传并启用</el-button>
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
  createRulePack,
  deleteRulePack,
  listBuiltinPacks,
  listRulePacks,
  packTypeLabel,
  toggleRulePack
} from '@/api/rules'

const packTypes: PackType[] = ['format', 'clause', 'field', 'cross']
const builtins = ref<BuiltinPack[]>([])
const packs = ref<RulePack[]>([])
const uploading = ref(false)
const mode = ref<'visual' | 'yaml'>('visual')
interface VisualClause {
  name: string
  strong: string
  weak: string
  severity: string
}
const visualClauses = ref<VisualClause[]>([])
const form = ref({
  name: '',
  pack_type: 'clause' as PackType,
  doc_type: 'contract',
  description: '',
  yaml_content: ''
})

function addClause() {
  visualClauses.value.push({ name: '', strong: '', weak: '', severity: 'error' })
}

function resetForm() {
  form.value = { name: '', pack_type: 'clause', doc_type: 'contract', description: '', yaml_content: '' }
  visualClauses.value = [{ name: '', strong: '', weak: '', severity: 'error' }]
  mode.value = 'visual'
}

/** 可视化条款 → 符合后端校验的 YAML（version=1, clauses[]） */
function buildClauseYaml(rows: VisualClause[]): string {
  const split = (s: string) => s.split(/[,，、;\s]+/).map((x) => x.trim()).filter(Boolean)
  const clauses = rows
    .filter((r) => r.name.trim() && split(r.strong).length)
    .map((r, i) => ({
      id: `custom_${i + 1}`,
      name: r.name.trim(),
      severity: r.severity || 'error',
      strong: split(r.strong),
      weak: split(r.weak)
    }))
  const lines = ['version: 1', 'clauses:']
  for (const c of clauses) {
    lines.push(`  - id: ${JSON.stringify(c.id)}`)
    lines.push(`    name: ${JSON.stringify(c.name)}`)
    lines.push(`    severity: ${JSON.stringify(c.severity)}`)
    lines.push(`    strong: ${JSON.stringify(c.strong)}`)
    lines.push(`    weak: ${JSON.stringify(c.weak)}`)
  }
  return lines.join('\n')
}

async function load() {
  const [b, p] = await Promise.all([listBuiltinPacks(), listRulePacks()])
  builtins.value = b
  packs.value = p
}

function onUpload() {
  if (!form.value.name.trim()) {
    ElMessage.warning('请填写包名称')
    return
  }
  let yaml = form.value.yaml_content
  if (form.value.pack_type === 'clause' && mode.value === 'visual') {
    const built = buildClauseYaml(visualClauses.value)
    if (!built.includes('custom_1')) {
      ElMessage.warning('请至少填写一条条款：条款名称 + 必备关键词')
      return
    }
    yaml = built
  }
  if (!yaml.trim()) {
    ElMessage.warning('请填写规则内容')
    return
  }
  uploading.value = true
  createRulePack({
    name: form.value.name.trim(),
    pack_type: form.value.pack_type,
    doc_type: form.value.doc_type.trim() || 'contract',
    yaml_content: yaml,
    description: form.value.description.trim() || undefined
  })
    .then(() => {
      ElMessage.success('上传成功，已生效')
      resetForm()
      load()
    })
    .catch((e: { response?: { data?: { detail?: string } } }) => {
      ElMessage.error(e.response?.data?.detail || '上传失败')
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
.clause-editor {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.clause-row {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}
.clause-hint {
  font-size: 12px;
  color: #909399;
  line-height: 1.6;
}
</style>
