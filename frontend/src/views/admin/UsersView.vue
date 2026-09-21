<template>
  <el-card>
    <template #header><b>用户管理</b></template>
      <el-table :data="users" v-loading="loading" stripe>
        <el-table-column prop="username" label="用户名" min-width="160" />
        <el-table-column label="角色" min-width="140">
          <template #default="{ row }">
            <el-tag v-for="r in row.roles" :key="r" size="small" style="margin-right: 6px">
              {{ r === 'admin' ? '管理员' : '普通成员' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'info'" size="small">
              {{ row.is_active ? '正常' : '停用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" min-width="180">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
      </el-table>
  </el-card>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'

import { listUsers, type UserInfo } from '@/api/auth'

const users = ref<UserInfo[]>([])
const loading = ref(false)

function formatTime(iso: string) {
  return new Date(iso).toLocaleString('zh-CN')
}

onMounted(async () => {
  loading.value = true
  try {
    users.value = await listUsers()
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail ?? '加载失败')
  } finally {
    loading.value = false
  }
})
</script>
