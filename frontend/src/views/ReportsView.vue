<template>
  <div v-loading="loading">
    <div class="page-header">
      <el-button link @click="router.back()">返回</el-button>
      <h3 class="title">校验报告</h3>
    </div>

    <el-tabs v-model="severity" class="sev-tabs">
      <el-tab-pane label="全部" name="all" />
      <el-tab-pane :label="`错误 ${counts.error}`" name="error" />
      <el-tab-pane :label="`警告 ${counts.warning}`" name="warning" />
      <el-tab-pane :label="`提示 ${counts.info}`" name="info" />
    </el-tabs>

    <div class="filters">
      <el-select v-model="checker" placeholder="检查器" clearable style="width: 150px">
        <el-option label="格式检查" value="format" />
        <el-option label="错别字" value="typo" />
      </el-select>
      <el-select v-model="fstatus" placeholder="处理状态" clearable style="width: 150px">
        <el-option label="待处理" value="open" />
        <el-option label="已忽略" value="ignored" />
        <el-option label="已修复" value="fixed" />
      </el-select>
      <el-button @click="reload">刷新</el-button>
    </div>

    <el-empty v-if="!filtered.length" description="没有符合条件的问题" />

    <el-table v-else :data="filtered" stripe>
      <el-table-column label="级别" width="80">
        <template #default="{ row }">
          <el-tag :type="sevType[row.severity]" size="small">{{ sevLabel[row.severity] }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="检查器" width="100">
        <template #default="{ row }">{{ checkerLabel[row.checker] ?? row.checker }}</template>
      </el-table-column>
      <el-table-column label="问题与建议" min-width="320">
        <template #default="{ row }">
          <div>{{ row.message }}</div>
          <div v-if="row.suggestion" class="sugg">建议：{{ row.suggestion }}</div>
          <div v-if="row.location?.snippet" class="snippet">原文：…{{ row.location.snippet }}…</div>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag v-if="row.status === 'open'" type="warning" size="small">待处理</el-tag>
          <el-tag v-else-if="row.status === 'ignored'" size="small" type="info">已忽略</el-tag>
          <el-tag v-else size="small" type="success">已修复</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="170">
        <template #default="{ row }">
          <el-button v-if="row.status !== 'fixed'" link type="success"
                     @click="change(row, 'fixed')">标已修复</el-button>
          <el-button v-if="row.status !== 'ignored'" link type="info"
                     @click="change(row, 'ignored')">忽略</el-button>
          <el-button v-if="row.status !== 'open'" link @click="change(row, 'open')">重开</el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Finding, listFindings, setFindingStatus } from '@/api/findings'

const route = useRoute()
const router = useRouter()
const docId = route.params.docId as string

const loading = ref(false)
const findings = ref<Finding[]>([])
const severity = ref('all')
const checker = ref('')
const fstatus = ref('')

const sevType: Record<string, string> = { error: 'danger', warning: 'warning', info: 'info' }
const sevLabel: Record<string, string> = { error: '错误', warning: '警告', info: '提示' }
const checkerLabel: Record<string, string> = { format: '格式', typo: '错别字' }

const counts = computed(() => {
  const c = { error: 0, warning: 0, info: 0 }
  findings.value.forEach((f) => {
    if (f.severity in c) c[f.severity as 'error'] += 1
  })
  return c
})

const filtered = computed(() =>
  findings.value.filter(
    (f) =>
      (severity.value === 'all' || f.severity === severity.value) &&
      (!checker.value || f.checker === checker.value) &&
      (!fstatus.value || f.status === fstatus.value)
  )
)

async function reload() {
  loading.value = true
  try {
    const res = await listFindings(docId)
    findings.value = res.items
  } finally {
    loading.value = false
  }
}

async function change(row: Finding, status: 'open' | 'ignored' | 'fixed') {
  await setFindingStatus(row.id, status)
  ElMessage.success('状态已更新')
  await reload()
}

onMounted(reload)
</script>

<style scoped>
.page-header {
  display: flex;
  align-items: center;
  gap: 12px;
}
.title {
  margin: 0;
}
.filters {
  display: flex;
  gap: 12px;
  margin-bottom: 12px;
}
.sugg {
  color: #67c23a;
  font-size: 13px;
}
.snippet {
  color: #909399;
  font-size: 12px;
}
</style>
