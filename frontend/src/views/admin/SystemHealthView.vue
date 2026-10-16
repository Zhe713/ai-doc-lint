<template>
  <div>
    <el-card>
      <template #header>
        <div class="card-header">
          <b>系统健康</b>
          <el-button :loading="loading" size="small" @click="load">刷新</el-button>
        </div>
      </template>

      <div class="grid">
        <el-card shadow="never" class="stat">
          <div class="stat-value">{{ stats.documents ?? '-' }}</div>
          <div class="stat-label">已校验文档</div>
        </el-card>
        <el-card shadow="never" class="stat">
          <div class="stat-value">{{ stats.tasks_total ?? '-' }}</div>
          <div class="stat-label">解析任务总数</div>
        </el-card>
        <el-card shadow="never" class="stat">
          <div class="stat-value">{{ stats.recent_audit ?? '-' }}</div>
          <div class="stat-label">近 24 小时操作记录</div>
        </el-card>
        <el-card shadow="never" class="stat">
          <div class="stat-value" :class="{ danger: (stats.alerts_active ?? 0) > 0 }">{{ stats.alerts_active ?? 0 }}</div>
          <div class="stat-label">未处理告警</div>
        </el-card>
        <el-card shadow="never" class="stat">
          <div class="stat-value">{{ queueDepth }}</div>
          <div class="stat-label">待处理任务</div>
        </el-card>
      </div>

      <div class="sections">
        <el-card shadow="never" class="section">
          <template #header><b>任务状态分布</b></template>
          <el-table :data="stateRows" size="small" stripe>
            <el-table-column label="状态" prop="label" />
            <el-table-column label="数量" prop="value" width="120" />
          </el-table>
        </el-card>

        <el-card shadow="never" class="section">
          <template #header><b>处理队列深度</b></template>
          <el-table :data="queueRows" size="small" stripe>
            <el-table-column label="队列" prop="label" />
            <el-table-column label="等待数" prop="value" width="120" />
          </el-table>
        </el-card>
      </div>

      <el-card shadow="never" class="section">
        <template #header><b>依赖连接状态</b></template>
        <el-space wrap>
          <el-tag v-for="(v, k) in depStatus" :key="k" :type="v === 'ok' ? 'success' : 'danger'" effect="plain">
            {{ depLabels[k] || k }}：{{ v === 'ok' ? '正常' : v }}
          </el-tag>
        </el-space>
        <p class="hint">监控指标端点：<code>/metrics</code>（Prometheus 文本格式，仅聚合计数，可匿名抓取）</p>
      </el-card>

      <el-card shadow="never" class="section">
        <template #header>
          <div class="card-header">
            <b>告警记录</b>
            <el-button size="small" @click="loadAlerts">刷新</el-button>
          </div>
        </template>
        <el-table :data="alertRows" size="small" stripe empty-text="暂无告警记录">
          <el-table-column label="时间" width="150">
            <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="级别" width="80">
            <template #default="{ row }">
              <el-tag :type="row.level === 'critical' ? 'danger' : 'warning'" size="small" effect="dark">
                {{ row.level === 'critical' ? '严重' : '提示' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="类型" width="110">
            <template #default="{ row }">{{ alertTypeLabels[row.alert_type] || row.alert_type }}</template>
          </el-table-column>
          <el-table-column label="内容" prop="message" show-overflow-tooltip />
          <el-table-column label="状态" width="80">
            <template #default="{ row }">
              <el-tag :type="row.status === 'active' ? 'danger' : 'info'" size="small" effect="plain">
                {{ row.status === 'active' ? '未处理' : '已解除' }}
              </el-tag>
            </template>
          </el-table-column>
        </el-table>
      </el-card>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { getAlerts, getSystemStats, type AlertItem, type SystemStats } from '@/api/auth'

const stateLabels: Record<string, string> = {
  pending: '排队中',
  running: '解析中',
  retrying: '重试中',
  awaiting_decision: '等待人工决策',
  parsed: '已完成',
  failed: '失败',
  cancelled: '已取消'
}

const queueLabels: Record<string, string> = {
  parse: '解析',
  review: '校验',
  annotate: '批注',
  learn: '学习诊断',
  cross_compare: '交叉比对',
  embed: '向量索引'
}

const depLabels: Record<string, string> = {
  db: '数据库',
  valkey: '缓存',
  minio: '对象存储'
}

const alertTypeLabels: Record<string, string> = {
  queue_backlog: '队列积压',
  parse_failure: '解析失败率',
  task_stalled: '任务卡死'
}

const stats = ref<SystemStats>({})
const alertRows = ref<AlertItem[]>([])
const loading = ref(false)

const stateRows = computed(() =>
  Object.entries(stats.value.tasks_by_state ?? {}).map(([k, v]) => ({ label: stateLabels[k] || k, value: v }))
)

const queueRows = computed(() =>
  Object.entries(stats.value.queues ?? {}).map(([k, v]) => ({ label: queueLabels[k] || k, value: v }))
)

const queueDepth = computed(() =>
  Object.values(stats.value.queues ?? {}).reduce((a, b) => a + (Number(b) || 0), 0)
)

const depStatus = computed(() => {
  const out: Record<string, string> = {}
  for (const k of ['db', 'valkey', 'minio'] as const) {
    if (stats.value[k] !== undefined) out[k] = String(stats.value[k])
  }
  return out
})

async function load() {
  loading.value = true
  try {
    stats.value = await getSystemStats()
  } finally {
    loading.value = false
  }
}

function fmtTime(s?: string) {
  if (!s) return '-'
  const d = new Date(s)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

async function loadAlerts() {
  try {
    const page = await getAlerts({ limit: 10 })
    alertRows.value = page.items
  } catch {
    alertRows.value = []
  }
}

onMounted(() => {
  load()
  loadAlerts()
})
</script>

<style scoped>
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}
.stat {
  text-align: center;
}
.stat-value {
  font-size: 28px;
  font-weight: 700;
  color: #409eff;
}
.stat-value.danger {
  color: #f56c6c;
}
.stat-label {
  color: #909399;
  font-size: 13px;
  margin-top: 4px;
}
.sections {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin-bottom: 16px;
}
.section {
  margin-bottom: 0;
}
.hint {
  color: #909399;
  font-size: 12px;
  margin-top: 10px;
}
@media (max-width: 720px) {
  .sections {
    grid-template-columns: 1fr;
  }
}
</style>
