<template>
  <el-card style="max-width: 640px">
    <template #header><b>系统设置</b></template>
    <el-form label-width="160px" v-loading="loading">
      <el-form-item label="开放注册">
        <el-switch v-model="openRegistration" @change="save" />
        <span style="margin-left: 12px; color: #909399; font-size: 12px">
          关闭后，新用户无法自行注册账号
        </span>
      </el-form-item>
      <el-form-item label="数据保留期限">
        <el-input-number v-model="dataRetentionDays" :min="0" :max="3650" style="width: 200px" />
        <span style="margin-left: 12px; color: #909399; font-size: 12px">
          天；0 表示不自动清理。到期文件将自动删除，请谨慎设置
        </span>
      </el-form-item>
      <el-form-item label="每日智能审查限额">
        <el-input-number v-model="llmDailyQuota" :min="0" :max="100000" style="width: 200px" />
        <span style="margin-left: 12px; color: #909399; font-size: 12px">
          次/天；0 表示不限制。达到限额后深度条款审查将暂缓
        </span>
      </el-form-item>
      <el-form-item>
        <el-button type="primary" :loading="saving" @click="saveAll">保存设置</el-button>
      </el-form-item>
      <el-alert type="info" :closable="false"
        title="提示：合同数据高度敏感。请在“用户管理”中核对账号列表，确认仅授权人员可访问本工具。" />
    </el-form>
  </el-card>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'

import { getAdminSettings, patchAdminSettings } from '@/api/auth'

const openRegistration = ref(true)
const dataRetentionDays = ref<number | null>(0)
const llmDailyQuota = ref<number | null>(0)
const loading = ref(false)
const saving = ref(false)

onMounted(async () => {
  loading.value = true
  try {
    const s = await getAdminSettings()
    openRegistration.value = s.open_registration
    dataRetentionDays.value = s.data_retention_days ?? 0
    llmDailyQuota.value = s.llm_daily_quota ?? 0
  } finally {
    loading.value = false
  }
})

async function saveAll() {
  saving.value = true
  try {
    const result = await patchAdminSettings({
      open_registration: openRegistration.value,
      data_retention_days: dataRetentionDays.value ?? 0,
      llm_daily_quota: llmDailyQuota.value ?? 0
    })
    openRegistration.value = result.open_registration
    dataRetentionDays.value = result.data_retention_days ?? 0
    llmDailyQuota.value = result.llm_daily_quota ?? 0
    ElMessage.success('设置已保存')
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail ?? '保存失败')
  } finally {
    saving.value = false
  }
}

async function save() {
  saving.value = true
  try {
    const result = await patchAdminSettings({ open_registration: openRegistration.value })
    openRegistration.value = result.open_registration
    ElMessage.success('设置已保存')
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail ?? '保存失败')
  } finally {
    saving.value = false
  }
}
</script>
