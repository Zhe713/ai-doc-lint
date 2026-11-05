<template>
  <el-card>
    <template #header>
      <div class="head">
        <b>用户管理</b>
        <span class="hint">停用后无法登录（已登录的令牌立即失效需重新登录）；改角色全量替换</span>
      </div>
    </template>

    <el-table :data="users" v-loading="loading" stripe>
      <el-table-column prop="username" label="用户名" min-width="150" />
      <el-table-column label="角色" min-width="200">
        <template #default="{ row }">
          <el-tag v-for="r in row.roles" :key="r" size="small" style="margin-right: 6px">
            {{ r === 'admin' ? '管理员' : '普通成员' }}
          </el-tag>
          <el-tag v-if="row.is_superuser" size="small" type="danger" effect="plain">超级管理员</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'info'" size="small">
            {{ row.is_active ? '正常' : '已停用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="created_at" label="创建时间" min-width="170">
        <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="280" fixed="right">
        <template #default="{ row }">
          <el-button size="small" link type="primary" :disabled="isSelf(row as UserInfo)" @click="toggleActive(row as UserInfo)">
            {{ row.is_active ? '停用' : '启用' }}
          </el-button>
          <el-button size="small" link type="primary" :disabled="isSelf(row as UserInfo)" @click="openRole(row as UserInfo)">
            改角色
          </el-button>
          <el-button size="small" link type="primary" @click="openReset(row as UserInfo)">重置密码</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="roleVisible" title="修改角色" width="380px">
      <div class="dialog-line">用户：<b>{{ target?.username }}</b></div>
      <el-radio-group v-model="roleChoice">
        <el-radio value="member">普通成员</el-radio>
        <el-radio value="admin">管理员</el-radio>
      </el-radio-group>
      <div class="dialog-hint">管理员可管理规则包、用户与系统设置。</div>
      <template #footer>
        <el-button @click="roleVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveRole">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="resetVisible" title="重置密码" width="380px">
      <div class="dialog-line">用户：<b>{{ target?.username }}</b></div>
      <el-input v-model="newPassword" type="password" show-password placeholder="新密码（至少 8 位）" />
      <div class="dialog-hint">重置后请通过安全渠道告知本人，并建议其尽快自行修改。</div>
      <template #footer>
        <el-button @click="resetVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="savePassword">确认重置</el-button>
      </template>
    </el-dialog>
  </el-card>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'

import { listUsers, updateUser, type UserInfo } from '@/api/auth'
import { useAuthStore } from '@/stores/auth'

const users = ref<UserInfo[]>([])
const loading = ref(false)
const saving = ref(false)
const auth = useAuthStore()

const roleVisible = ref(false)
const resetVisible = ref(false)
const target = ref<UserInfo | null>(null)
const roleChoice = ref<'admin' | 'member'>('member')
const newPassword = ref('')

function formatTime(iso: string) {
  return new Date(iso).toLocaleString('zh-CN')
}

// 后端同样会拦（不能停用/降级自己），前端先禁用避免用户白点一次
function isSelf(row: UserInfo) {
  return row.id === auth.user?.id
}

async function load() {
  loading.value = true
  try {
    users.value = await listUsers()
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail ?? '加载失败')
  } finally {
    loading.value = false
  }
}

async function toggleActive(row: UserInfo) {
  try {
    await updateUser(row.id, { is_active: !row.is_active })
    ElMessage.success(row.is_active ? '已停用' : '已启用')
    await load()
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail ?? '操作失败')
  }
}

function openRole(row: UserInfo) {
  target.value = row
  roleChoice.value = row.roles.includes('admin') ? 'admin' : 'member'
  roleVisible.value = true
}

async function saveRole() {
  if (!target.value) return
  saving.value = true
  try {
    await updateUser(target.value.id, { roles: [roleChoice.value] })
    ElMessage.success('角色已更新')
    roleVisible.value = false
    await load()
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail ?? '操作失败')
  } finally {
    saving.value = false
  }
}

function openReset(row: UserInfo) {
  target.value = row
  newPassword.value = ''
  resetVisible.value = true
}

async function savePassword() {
  if (!target.value) return
  if (newPassword.value.length < 8) {
    ElMessage.warning('密码至少 8 位')
    return
  }
  saving.value = true
  try {
    await updateUser(target.value.id, { password: newPassword.value })
    ElMessage.success('密码已重置')
    resetVisible.value = false
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail ?? '操作失败')
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.head {
  display: flex;
  align-items: baseline;
  gap: 12px;
}
.head .hint {
  color: #909399;
  font-size: 12px;
}
.dialog-line {
  margin-bottom: 12px;
}
.dialog-hint {
  color: #909399;
  font-size: 12px;
  margin-top: 10px;
}
</style>
