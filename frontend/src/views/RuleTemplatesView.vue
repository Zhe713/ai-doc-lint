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
            <el-form-item label="YAML 内容">
              <el-input v-model="form.yaml_content" type="textarea" :rows="8"
                placeholder="version: 1&#10;clauses:&#10;  - id: xxx&#10;    name: 条款名&#10;    strong: [关键词]&#10;    weak: [弱关键词]" />
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
const form = ref({
  name: '',
  pack_type: 'clause' as PackType,
  doc_type: 'contract',
  description: '',
  yaml_content: ''
})

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
  if (!form.value.yaml_content.trim()) {
    ElMessage.warning('请填写 YAML 内容')
    return
  }
  uploading.value = true
  createRulePack({
    name: form.value.name.trim(),
    pack_type: form.value.pack_type,
    doc_type: form.value.doc_type.trim() || 'contract',
    yaml_content: form.value.yaml_content,
    description: form.value.description.trim() || undefined
  })
    .then(() => {
      ElMessage.success('上传成功，已生效')
      form.value = { name: '', pack_type: 'clause', doc_type: 'contract', description: '', yaml_content: '' }
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

onMounted(load)
</script>
