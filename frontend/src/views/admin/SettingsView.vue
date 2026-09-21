<template>
  <el-card style="max-width: 560px">
    <template #header><b>系统设置</b></template>
    <el-form label-width="140px" v-loading="loading">
      <el-form-item label="开放注册">
        <el-switch v-model="openRegistration" @change="save" />
        <span style="margin-left: 12px; color: #909399; font-size: 12px">
          关闭后，新用户无法自行注册账号
        </span>
      </el-form-item>
    </el-form>
  </el-card>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'

import { getAdminSettings, patchAdminSettings } from '@/api/auth'

const openRegistration = ref(true)
const loading = ref(false)

onMounted(async () => {
  loading.value = true
  try {
    openRegistration.value = (await getAdminSettings()).open_registration
  } finally {
    loading.value = false
  }
})

async function save() {
  try {
    const result = await patchAdminSettings(openRegistration.value)
    openRegistration.value = result.open_registration
    ElMessage.success('设置已保存')
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail ?? '保存失败')
  }
}
</script>
