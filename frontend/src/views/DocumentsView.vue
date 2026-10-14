<template>
  <div class="doc-page">
    <el-alert
      title="AI 校对辅助，不构成法律意见；文件与解析结果仅存储在你自己部署的环境中。"
      type="info" :closable="false" show-icon style="margin-bottom: 14px" />

    <el-row :gutter="16">
      <!-- 左：上传 + 批次列表 -->
      <el-col :span="9">
        <el-card shadow="never">
          <template #header><b>上传文档</b></template>
          <el-upload drag multiple :auto-upload="false" :show-file-list="false"
            accept=".docx,.pdf,.txt,.md" :on-change="onPick" ref="uploadRef">
            <el-icon class="el-icon--upload"><upload-filled /></el-icon>
            <div class="el-upload__text">拖拽文件到此处，或<em>点击选择</em>（最多 100 份）</div>
            <template #tip>
              <div class="el-upload__tip">支持 .docx / .pdf / .txt / .md；.doc 请先另存为 .docx；单文件 ≤ 200MB</div>
            </template>
          </el-upload>
          <div v-if="picked.length" style="margin-top: 8px">
            <el-tag v-for="f in picked" :key="f.uid" closable style="margin: 2px"
              @close="removePicked(f.uid)">{{ f.name }}</el-tag>
            <el-button link type="danger" size="small" style="margin-left: 6px" @click="clearPicked">清空列表</el-button>
          </div>
          <el-divider content-position="left" style="margin: 12px 0 6px">校验选项</el-divider>
          <el-radio-group v-model="optDocType" size="small">
            <el-radio-button label="auto">自动识别</el-radio-button>
            <el-radio-button label="contract">合同</el-radio-button>
            <el-radio-button label="tender">招投标</el-radio-button>
            <el-radio-button label="policy">制度</el-radio-button>
            <el-radio-button label="report">报告</el-radio-button>
          </el-radio-group>
          <div style="margin-top: 8px">
            <el-checkbox-group v-model="optChecks" size="small">
              <el-checkbox label="format">格式校验</el-checkbox>
              <el-checkbox label="typo">错别字</el-checkbox>
              <el-checkbox label="clause">深度条款审查（更慢但更准）</el-checkbox>
            </el-checkbox-group>
          </div>
          <el-button type="primary" style="margin-top: 10px; width: 100%" :loading="uploading"
            :disabled="!picked.length" @click="doUpload">
            开始解析（{{ picked.length }} 份）
          </el-button>
        </el-card>

        <el-card shadow="never" style="margin-top: 14px">
          <template #header>
            <div class="card-head">
              <b>批次记录</b>
              <el-button link type="primary" @click="loadGroups">刷新</el-button>
            </div>
          </template>
          <el-empty v-if="!groups.length" description="暂无批次" :image-size="60" />
          <div v-for="g in groups" :key="g.id" class="group-item"
            :class="{ active: currentGroupId === g.id }" @click="selectGroup(g.id)">
            <div class="group-line">
              <span>{{ fmtTime(g.created_at) }}</span>
              <span>共 {{ g.total }} 份</span>
            </div>
            <el-progress :percentage="donePercent(g)" :stroke-width="8"
              :status="g.awaiting ? 'exception' : (g.failed ? 'warning' : (donePercent(g) === 100 ? 'success' : ''))" />
            <div class="group-counts">
              <el-tag size="small" type="success" class="count-tag"
                :class="{ 'count-active': filterStatus === 'parsed' }"
                @click="toggleFilter('parsed')">{{ g.succeeded }} 完成</el-tag>
              <el-tag v-if="g.running" size="small" type="warning" class="count-tag"
                :class="{ 'count-active': filterStatus === 'running' }"
                @click="toggleFilter('running')">{{ g.running }} 进行</el-tag>
              <el-tag v-if="g.pending" size="small" type="info" class="count-tag"
                :class="{ 'count-active': filterStatus === 'pending' }"
                @click="toggleFilter('pending')">{{ g.pending }} 排队</el-tag>
              <el-tag v-if="g.awaiting" size="small" type="danger" class="count-tag"
                :class="{ 'count-active': filterStatus === 'awaiting_decision' }"
                @click="toggleFilter('awaiting_decision')">{{ g.awaiting }} 待决策</el-tag>
              <el-tag v-if="g.failed" size="small" type="danger" class="count-tag"
                :class="{ 'count-active': filterStatus === 'failed' }"
                @click="toggleFilter('failed')">{{ g.failed }} 失败</el-tag>
              <el-tag v-if="g.cancelled" size="small" class="count-tag"
                :class="{ 'count-active': filterStatus === 'cancelled' }"
                @click="toggleFilter('cancelled')">{{ g.cancelled }} 取消</el-tag>
            </div>
          </div>
        </el-card>
      </el-col>

      <!-- 右：任务明细 -->
      <el-col :span="15">
        <el-card shadow="never">
          <template #header>
            <div class="card-head">
              <b>解析进度</b>
              <span class="ws-state">
                <el-icon v-if="wsConnected" color="#67c23a"><circle-check /></el-icon>
                <el-icon v-else color="#e6a23c"><loading /></el-icon>
                {{ wsConnected ? '实时连接' : '轮询模式' }}
              </span>
            </div>
          </template>
          <el-empty v-if="!tasks.length" description="选择左侧批次查看明细" />
          <el-table v-else :data="filteredTasks" size="small" :row-class-name="rowClass">
            <el-table-column label="文件" min-width="210" show-overflow-tooltip>
              <template #default="{ row }">
                <div>{{ row.filename }}</div>
                <div class="muted file-meta">{{ fmtTime(row.created_at) }}</div>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="130">
              <template #default="{ row }">
                <el-tag :type="statusType(row)" size="small">
                  {{ statusLabel(row) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="进度/结果" min-width="170">
              <template #default="{ row }">
                <span v-if="row.status === 'parsed'">
                  {{ row.stats?.page_count }} 页 / {{ row.stats?.char_count }} 字
                  <el-tag v-if="row.stats?.ocr_used" size="small" type="warning">OCR</el-tag>
                </span>
                <span v-else-if="row.status === 'awaiting_decision'" class="gate-text">
                  {{ gateLabel(row.gate_reason) }}
                </span>
                <span v-else-if="row.error_message" class="err-text">{{ row.error_message }}</span>
                <span v-else class="muted">{{ lastStage(row) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="200" align="right">
              <template #default="{ row }">
                <el-button v-if="row.status === 'awaiting_decision'" size="small" type="danger"
                  @click="openGate(row)">去决策</el-button>
                <el-button v-if="row.status === 'parsed'" size="small" type="primary"
                  :title="`查看「${row.filename}」的报告`"
                  @click="openReport(row)">查看报告</el-button>
                <el-button v-if="row.status === 'parsed'" size="small" @click="openPreview(row)">预览文本</el-button>
                <el-button v-if="['pending', 'running'].includes(row.status)" size="small"
                  @click="onCancel(row)">取消</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>

    <!-- 闸门弹窗 -->
    <el-dialog v-model="gateVisible" title="解析需要你的决定" width="560px">
      <el-result v-if="gateTask" :icon="gateIcon(gateTask.gate_reason)" :title="gateLabel(gateTask.gate_reason)"
        :sub-title="gateSub(gateTask)">
        <template #extra>
          <div style="width: 100%">
            <el-space wrap>
              <el-button type="primary" :loading="deciding"
                @click="decide('retry_ocr')">OCR 重新识别</el-button>
              <el-button type="warning" :loading="deciding"
                @click="decide('continue_with_warnings')">带警告继续</el-button>
              <el-button :loading="deciding" @click="decide('cancel')">取消，重新上传</el-button>
            </el-space>
            <div class="gate-tips">
              <p><b>OCR 重新识别</b>：用 OCR 重新解析这份文件，耗时较长，但能尽量还原扫描件内容。</p>
              <p><b>带警告继续</b>：按当前结果继续，报告中可能缺失内容或存在识别偏差，结果仅供辅助参考。</p>
              <p><b>取消，重新上传</b>：取消本次任务并丢弃该文件，请准备好清晰文件后重新上传。</p>
            </div>
          </div>
        </template>
      </el-result>
    </el-dialog>

    <!-- 文本预览 -->
    <el-drawer v-model="previewVisible" :title="previewTitle" size="50%">
      <div v-loading="previewLoading">
        <el-descriptions v-if="preview?.stats" :column="3" border size="small" style="margin-bottom: 12px">
          <el-descriptions-item label="页数">{{ preview.stats.page_count }}</el-descriptions-item>
          <el-descriptions-item label="字数">{{ preview.stats.char_count }}</el-descriptions-item>
          <el-descriptions-item label="表格数">{{ preview.stats.table_count }}</el-descriptions-item>
        </el-descriptions>
        <pre class="preview-text">{{ preview?.plaintext }}</pre>
        <el-alert v-if="preview?.truncated" type="warning" :closable="false"
          :title="`仅预览前 2 万字，全文共 ${preview.total_chars} 字（完整文本在报告阶段使用）`" />
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox, type UploadFile, type UploadFiles } from 'element-plus'
import { CircleCheck, Loading, UploadFilled } from '@element-plus/icons-vue'

import {
  cancelTask,
  decideGate,
  getGroup,
  getPreview,
  listGroups,
  uploadDocuments,
  type TaskGroup,
  type TaskItem
} from '@/api/documents'
import { useTaskProgress } from '@/composables/useTaskProgress'

const uploadRef = ref()
const picked = ref<UploadFiles>([])
const uploading = ref(false)
const optDocType = ref('auto')
const optChecks = ref<string[]>(['format', 'typo'])
const groups = ref<TaskGroup[]>([])
const currentGroupId = ref('')
const tasks = ref<TaskItem[]>([])
let pollTimer: number | undefined

const gateVisible = ref(false)
const gateTask = ref<TaskItem | null>(null)
const deciding = ref(false)

const previewVisible = ref(false)
const previewLoading = ref(false)
const previewTitle = ref('')
const preview = ref<Awaited<ReturnType<typeof getPreview>> | null>(null)

const { connected: wsConnected } = useTaskProgress(() => {
  if (currentGroupId.value) refreshGroup(currentGroupId.value)
})

const router = useRouter()

function openReport(row: TaskItem) {
  router.push({ name: 'reports', params: { docId: row.document_id } })
}

function onPick(_file: UploadFile, files: UploadFiles) {
  picked.value = files
}
function removePicked(uid: number) {
  picked.value = picked.value.filter((f) => f.uid !== uid)
}
function clearPicked() {
  picked.value = []
  uploadRef.value?.clearFiles()
}

const filterStatus = ref('')
function toggleFilter(s: string) {
  filterStatus.value = filterStatus.value === s ? '' : s
}
const filteredTasks = computed(() =>
  filterStatus.value ? tasks.value.filter((t) => t.status === filterStatus.value) : tasks.value
)

async function doUpload() {
  const bad = picked.value.find((f) => f.name.toLowerCase().endsWith('.doc'))
  if (bad) {
    ElMessage.error(`不支持 .doc 老格式，请另存为 .docx：${bad.name}`)
    return
  }
  uploading.value = true
  try {
    const files = picked.value.map((f) => f.raw as File)
    const res = await uploadDocuments(files, {
      doc_type: optDocType.value,
      checks: optChecks.value
    })
    ElMessage.success(`已受理 ${res.total} 份，开始排队解析`)
    picked.value = []
    uploadRef.value?.clearFiles()
    await loadGroups()
    await selectGroup(res.group_id)
  } catch (e: unknown) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    ElMessage.error(detail || '上传失败')
  } finally {
    uploading.value = false
  }
}

async function loadGroups() {
  groups.value = await listGroups()
}

async function selectGroup(id: string) {
  currentGroupId.value = id
  await refreshGroup(id)
}

async function refreshGroup(id: string) {
  const detail = await getGroup(id)
  tasks.value = detail.tasks
  const g = groups.value.find((x) => x.id === id)
  if (g) Object.assign(g, detail.group)
  // 还有未结束任务时保持轮询兜底
  const active = detail.tasks.some((t) => ['pending', 'running', 'retrying', 'awaiting_decision'].includes(t.status))
  if (active) {
    if (!pollTimer) pollTimer = window.setInterval(() => currentGroupId.value && refreshGroup(currentGroupId.value), 2500)
  } else if (pollTimer) {
    window.clearInterval(pollTimer)
    pollTimer = undefined
    loadGroups()
  }
}

function openGate(row: TaskItem) {
  gateTask.value = row
  gateVisible.value = true
}

async function decide(action: 'retry_ocr' | 'continue_with_warnings' | 'cancel') {
  if (!gateTask.value) return
  deciding.value = true
  try {
    await decideGate(gateTask.value.id, action)
    ElMessage.success('已提交决定')
    gateVisible.value = false
    if (currentGroupId.value) await refreshGroup(currentGroupId.value)
  } catch (e: unknown) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    ElMessage.error(detail || '操作失败')
  } finally {
    deciding.value = false
  }
}

async function onCancel(row: TaskItem) {
  await ElMessageBox.confirm(`确定取消「${row.filename}」的解析任务？`, '取消任务', { type: 'warning' })
  await cancelTask(row.id)
  ElMessage.success('已取消')
  if (currentGroupId.value) refreshGroup(currentGroupId.value)
}

async function openPreview(row: TaskItem) {
  previewVisible.value = true
  previewLoading.value = true
  previewTitle.value = `文本预览 · ${row.filename}`
  preview.value = null
  try {
    preview.value = await getPreview(row.id)
  } catch (e: unknown) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    ElMessage.error(detail || '预览不可用')
  } finally {
    previewLoading.value = false
  }
}

function donePercent(g: TaskGroup) {
  const settled = g.succeeded + g.failed + g.cancelled
  return Math.round((settled / Math.max(g.total, 1)) * 100)
}
function statusType(row: TaskItem) {
  if (row.status === 'parsed' && hasWarningContinue(row)) return 'danger'
  return ({
    pending: 'info',
    running: 'warning',
    retrying: 'warning',
    awaiting_decision: 'danger',
    parsed: 'success',
    failed: 'danger',
    cancelled: 'info'
  } as Record<string, string>)[row.status] || 'info'
}
function statusLabel(row: TaskItem) {
  if (row.status === 'parsed' && hasWarningContinue(row)) return '带警告完成'
  return ({
    pending: '排队中',
    running: '解析中',
    retrying: '重试中',
    awaiting_decision: '待决策',
    parsed: '已完成',
    failed: '失败',
    cancelled: '已取消'
  } as Record<string, string>)[row.status] || row.status
}
/** 该任务是否经「带警告继续」完成：结果可能缺失内容，须保留警示 */
function hasWarningContinue(row: TaskItem) {
  return Array.isArray(row.warnings) &&
    row.warnings.some((w) => (w as { code?: string })?.code === 'user_continued_with_warning')
}
function gateLabel(reason: string | null) {
  return ({
    ocr_required: '疑似扫描件，建议 OCR',
    parse_failed: '解析失败，需要处理',
    low_confidence: '文本抽取置信度过低',
    unsupported: '文件格式不支持'
  } as Record<string, string>)[reason || ''] || '需要人工决定'
}
function gateIcon(reason: string | null) {
  return reason === 'ocr_required' ? 'picture' : 'warning'
}
function gateSub(row: TaskItem) {
  const p = row.gate_payload || {}
  const parts = Object.entries(p).map(([k, v]) => `${k}: ${String(v)}`)
  return parts.length ? parts.join('；') : (row.error_message || '')
}
function lastStage(row: TaskItem) {
  const ev = row.events?.[row.events.length - 1]
  return ev?.message || ''
}
function rowClass({ row }: { row: TaskItem }) {
  return row.status === 'awaiting_decision' ? 'gate-row' : ''
}
function fmtTime(s: string) {
  return new Date(s).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

onMounted(loadGroups)
onUnmounted(() => pollTimer && window.clearInterval(pollTimer))
</script>

<style scoped>
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.group-item {
  padding: 8px;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  margin-bottom: 8px;
  cursor: pointer;
}
.group-item:hover {
  border-color: #409eff;
}
.group-item.active {
  border-color: #409eff;
  background: #ecf5ff;
}
.group-line {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  color: #606266;
  margin-bottom: 4px;
}
.group-counts {
  margin-top: 5px;
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}
.count-tag {
  cursor: pointer;
  user-select: none;
}
.count-active {
  outline: 2px solid #409eff;
  outline-offset: 1px;
}
.file-meta {
  font-size: 11px;
  line-height: 1.4;
}
.gate-tips {
  margin-top: 12px;
  text-align: left;
  font-size: 13px;
  color: #606266;
  line-height: 1.7;
  background: #f5f7fa;
  border-radius: 6px;
  padding: 10px 12px;
}
.gate-tips p {
  margin: 4px 0;
}
.gate-tips b {
  color: #303133;
}
.ws-state {
  font-size: 12px;
  color: #909399;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.gate-text {
  color: #f56c6c;
  font-size: 12px;
}
.err-text {
  color: #f56c6c;
  font-size: 12px;
}
.muted {
  color: #909399;
  font-size: 12px;
}
.preview-text {
  white-space: pre-wrap;
  word-break: break-word;
  font-family: 'Segoe UI', 'Microsoft YaHei', monospace;
  font-size: 13px;
  line-height: 1.7;
  background: #f8f9fb;
  padding: 12px;
  border-radius: 6px;
}
:deep(.gate-row) {
  background: #fef0f0;
}
</style>
