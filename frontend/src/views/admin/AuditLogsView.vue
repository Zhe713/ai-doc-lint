<template>
  <div>
    <el-card>
      <template #header>
        <div class="card-header">
          <b>审计日志</b>
          <span class="hint">关键操作留痕：登录、上传、设置变更、学习诊断。合同内容本身不记录。</span>
        </div>
      </template>

      <div class="toolbar">
        <el-select v-model="actionFilter" clearable placeholder="全部动作" style="width: 220px" @change="load(1)">
          <el-option v-for="(label, value) in actionLabels" :key="value" :label="label" :value="value" />
        </el-select>
        <el-button :loading="loading" @click="load(1)">刷新</el-button>
        <span class="total">共 {{ total }} 条</span>
      </div>

      <el-table :data="items" v-loading="loading" stripe>
        <el-table-column label="时间" width="180">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="动作" width="140">
          <template #default="{ row }">
            <el-tag :type="tagType(row.action)" effect="plain" size="small">
              {{ actionLabels[row.action] || row.action }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="username" label="操作人" width="130" />
        <el-table-column label="详情" min-width="260">
          <template #default="{ row }">
            <span class="detail">{{ formatDetail(row) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="ip" label="来源 IP" width="140" />
      </el-table>

      <div class="pager">
        <el-pagination
          layout="prev, pager, next"
          :page-size="pageSize"
          :total="total"
          :current-page="page"
          @current-change="load"
        />
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { listAuditLogs, type AuditLogItem } from '@/api/auth'

const actionLabels: Record<string, string> = {
  login_success: '登录成功',
  login_fail: '登录失败',
  register: '注册账号',
  upload_batch: '上传批次',
  admin_setting: '系统设置变更',
  rule_decision: '规则建议处理',
  learning_tuning: '学习诊断'
}

const items = ref<AuditLogItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const actionFilter = ref<string | undefined>()
const loading = ref(false)

async function load(targetPage = 1) {
  page.value = targetPage
  loading.value = true
  try {
    const data = await listAuditLogs({
      action: actionFilter.value || undefined,
      limit: pageSize,
      offset: (targetPage - 1) * pageSize
    })
    items.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}

function formatTime(v: string | null) {
  if (!v) return '-'
  return new Date(v).toLocaleString('zh-CN', { hour12: false })
}

function tagType(action: string): 'success' | 'danger' | 'info' | 'warning' {
  if (action === 'login_success' || action === 'register') return 'success'
  if (action === 'login_fail') return 'danger'
  if (action === 'rule_decision' || action === 'learning_tuning') return 'warning'
  return 'info'
}

function formatDetail(row: AuditLogItem) {
  if (row.action === 'login_success' || row.action === 'register') return '-'
  if (row.action === 'upload_batch') {
    return `上传 ${row.detail?.count ?? '?'} 份合同`
  }
  if (row.action === 'login_fail') {
    return `失败原因：${row.detail?.reason ?? '-'}`
  }
  if (row.action === 'admin_setting') {
    const parts: string[] = []
    if (row.detail?.open_registration !== undefined) parts.push(`开放注册=${row.detail.open_registration}`)
    if (row.detail?.data_retention_days !== undefined) parts.push(`数据保留=${row.detail.data_retention_days} 天`)
    if (row.detail?.llm_daily_quota !== undefined) parts.push(`每日审查限额=${row.detail.llm_daily_quota}`)
    return parts.join('；') || '-'
  }
  if (row.action === 'rule_decision') {
    return `决策=${row.detail?.decision === 'confirm' ? '采纳' : '忽略'}，检查器=${row.detail?.checker ?? '-'}`
  }
  if (row.action === 'learning_tuning') {
    return `新增白名单 ${row.detail?.whitelist_added ?? 0} 条`
  }
  return JSON.stringify(row.detail || {})
}

onMounted(() => load(1))
</script>

<style scoped>
.card-header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
}
.hint {
  color: #909399;
  font-size: 12px;
}
.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}
.total {
  color: #909399;
  font-size: 13px;
}
.detail {
  color: #606266;
  font-size: 13px;
}
.pager {
  margin-top: 12px;
  display: flex;
  justify-content: flex-end;
}
</style>
