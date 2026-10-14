<template>
  <div class="compare-page">
    <div class="page-head">
      <h2>交叉比对</h2>
      <el-button type="primary" @click="openCreate">
        <el-icon><Plus /></el-icon>新建比对组
      </el-button>
    </div>

    <el-row :gutter="16">
      <el-col :span="7">
        <el-card shadow="never" class="group-card">
          <template #header>
            <span>比对组</span>
          </template>
          <div v-if="groups.length === 0" class="empty">还没有比对组，先新建一个</div>
          <div
            v-for="g in groups"
            :key="g.id"
            class="group-item"
            :class="{ active: g.id === currentId }"
            @click="selectGroup(g.id)"
          >
            <div class="group-item-head">
              <span class="group-name">{{ g.name }}</span>
              <el-tag
                size="small"
                :type="g.status === 'parsed' ? 'success' : g.status === 'running' || g.status === 'pending' ? 'warning' : 'info'"
              >
                {{ statusLabel(g.status) }}
              </el-tag>
            </div>
            <div class="group-item-meta">
              {{ g.doc_count }} 份文档
              <span v-if="g.stats?.total != null">· {{ g.stats.total }} 条问题</span>
            </div>
          </div>
        </el-card>
      </el-col>

      <el-col :span="17">
        <el-card shadow="never">
          <template v-if="detail">
            <div class="detail-head">
              <div>
                <b>{{ detail.name }}</b>
                <el-tag
                  size="small"
                  style="margin-left: 8px"
                  :type="detail.status === 'parsed' ? 'success' : 'warning'"
                >
                  {{ statusLabel(detail.status) }}
                </el-tag>
              </div>
              <div>
                <el-button
                  type="primary"
                  size="small"
                  :loading="comparing"
                  :disabled="detail.status === 'running' || detail.status === 'pending'"
                  @click="runCompare"
                >
                  {{ detail.status === 'pending' || detail.status === 'running' ? '比对中…' : '触发比对' }}
                </el-button>
                <el-button size="small" type="danger" plain @click="removeGroup">
                  删除
                </el-button>
              </div>
            </div>

            <el-divider />

            <h4>文档矩阵（字段 × 文档）</h4>
            <el-table :data="matrixRows" border size="small" class="matrix-table">
              <el-table-column label="字段" min-width="150">
                <template #default="{ row }">
                  <div class="field-key">{{ row.key }}</div>
                  <div class="field-label">{{ row.label }}</div>
                </template>
              </el-table-column>
              <el-table-column
                v-for="d in detail.documents"
                :key="d.id"
                :label="d.filename"
                min-width="160"
              >
                <template #default="{ row }">
                  <div v-if="row.cells[d.id]" class="cell">
                    <div class="cell-value">
                      {{ cellText(row.cells[d.id]) }}
                    </div>
                    <div class="cell-meta">
                      <el-tag size="tiny" :type="cellSourceType(row.cells[d.id].source)" effect="plain">
                        {{ cellSourceLabel(row.cells[d.id].source) }}
                      </el-tag>
                    </div>
                  </div>
                  <div v-else class="cell empty">—</div>
                </template>
              </el-table-column>
            </el-table>

            <el-divider />

            <h4>比对发现（{{ detail.findings.length }}）</h4>
            <el-empty v-if="detail.findings.length === 0" description="未发现跨文档问题" :image-size="60" />
            <el-table v-else :data="detail.findings" border size="small">
              <el-table-column label="级别" width="80">
                <template #default="{ row }">
                  <el-tag size="small" :type="severityType(row.severity)">{{ row.severity }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="规则" width="190" prop="rule_id" />
              <el-table-column label="说明" prop="message" min-width="300" />
              <el-table-column label="对端文档" width="120">
                <template #default="{ row }">
                  {{ docName(row.related_document_id) }}
                </template>
              </el-table-column>
            </el-table>
          </template>
          <el-empty v-else description="在左侧选择一个比对组查看矩阵" :image-size="80" />
        </el-card>
      </el-col>
    </el-row>

    <el-dialog v-model="createVisible" title="新建比对组" width="480px">
      <el-form label-width="80px">
        <el-form-item label="组名称" required>
          <el-input v-model="newName" placeholder="如：主合同与补充协议" />
        </el-form-item>
        <el-form-item label="文档" required>
          <div v-if="docs.length === 0" class="empty">暂无已解析文档，请先在“文档校验”上传</div>
          <el-checkbox-group v-model="selectedDocs" class="doc-picker">
            <el-checkbox v-for="d in docs" :key="d.id" :value="d.id">
              <div class="doc-opt">
                <span class="doc-opt-name">{{ d.filename }}</span>
                <span class="doc-opt-meta">
                  <el-tag size="tiny" effect="plain">{{ d.doc_type }}</el-tag>
                  <span>{{ fmtTime(d.created_at) }}</span>
                  <span>{{ fmtSize(d.size_bytes) }}</span>
                </span>
              </div>
            </el-checkbox>
          </el-checkbox-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="createGroup">
          创建
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'

import {
  createCompareGroup,
  deleteCompareGroup,
  getCompareGroup,
  listCompareGroups,
  triggerCompare,
  type CompareGroup,
  type CompareGroupDetail,
  type CompareMatrixCell
} from '@/api/compare'
import { listDocuments } from '@/api/findings'

const groups = ref<CompareGroup[]>([])
const detail = ref<CompareGroupDetail | null>(null)
const currentId = ref<string | null>(null)
const docs = ref<Array<{ id: string; filename: string; doc_type: string }>>([])

const createVisible = ref(false)
const newName = ref('')
const selectedDocs = ref<string[]>([])
const creating = ref(false)
const comparing = ref(false)

function statusLabel(s: string): string {
  return { pending: '排队中', running: '比对中', parsed: '已完成', failed: '失败' }[s] ?? s
}

function severityType(s: string): 'danger' | 'warning' | 'info' {
  return { error: 'danger', warning: 'warning', info: 'info' }[s] ?? 'info'
}

function cellText(cell: CompareMatrixCell): string {
  if (cell.value_text != null) return cell.value_text
  if (cell.value_number != null) return String(cell.value_number)
  if (cell.value_date != null) return cell.value_date
  return '—'
}

function docName(id: string | null): string {
  if (!id) return '—'
  return detail.value?.documents.find((d) => d.id === id)?.filename ?? id.slice(0, 8)
}

const matrixRows = computed(() => {
  if (!detail.value) return []
  const keys = Object.keys(detail.value.matrix)
  return keys.map((k) => ({
    key: k,
    label: detail.value?.field_labels?.[k] ?? k,
    cells: detail.value!.matrix[k]
  }))
})

async function loadGroups() {
  groups.value = await listCompareGroups()
  if (currentId.value == null && groups.value.length > 0) {
    await selectGroup(groups.value[0].id)
  }
}

async function selectGroup(id: string) {
  currentId.value = id
  detail.value = await getCompareGroup(id)
}

async function runCompare() {
  if (!currentId.value) return
  comparing.value = true
  try {
    await triggerCompare(currentId.value)
    ElMessage.success('比对任务已提交')
    await pollUntilDone()
  } finally {
    comparing.value = false
  }
}

async function pollUntilDone() {
  for (let i = 0; i < 60; i++) {
    await new Promise((r) => setTimeout(r, 2000))
    if (!currentId.value) return
    const d = await getCompareGroup(currentId.value)
    detail.value = d
    if (d.status === 'parsed' || d.status === 'failed') {
      await loadGroups()
      return
    }
  }
}

async function removeGroup() {
  if (!currentId.value) return
  await ElMessageBox.confirm('删除比对组？关联的比对结果会一并清除', '提示', { type: 'warning' })
  await deleteCompareGroup(currentId.value)
  currentId.value = null
  detail.value = null
  await loadGroups()
}

async function openCreate() {
  docs.value = await listDocuments(200)
  newName.value = ''
  selectedDocs.value = []
  createVisible.value = true
}

async function createGroup() {
  if (!newName.value.trim()) {
    ElMessage.warning('请填写组名称')
    return
  }
  if (selectedDocs.value.length < 2) {
    ElMessage.warning('至少选择 2 份文档')
    return
  }
  creating.value = true
  try {
    const g = await createCompareGroup(newName.value.trim(), selectedDocs.value)
    createVisible.value = false
    ElMessage.success('比对组已创建，自动开始比对')
    await loadGroups()
    await selectGroup(g.id)
    // 创建后自动触发比对（P1-1 修复：无需用户再手动点“触发比对”）
    comparing.value = true
    try {
      await triggerCompare(g.id)
      await pollUntilDone()
    } finally {
      comparing.value = false
    }
  } finally {
    creating.value = false
  }
}

function cellSourceType(source: string): 'warning' | 'info' {
  return source === 'llm' ? 'warning' : 'info'
}
function cellSourceLabel(source: string): string {
  return source === 'llm' ? 'AI 提取' : '文本匹配'
}
function fmtTime(s: string | null): string {
  if (!s) return ''
  return new Date(s).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}
function fmtSize(n: number): string {
  if (n == null) return ''
  if (n >= 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`
  if (n >= 1024) return `${Math.round(n / 1024)} KB`
  return `${n} B`
}

onMounted(loadGroups)
</script>

<style scoped>
.page-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}
.page-head h2 {
  margin: 0;
  font-size: 20px;
}
.group-card {
  min-height: 420px;
}
.group-item {
  padding: 10px 12px;
  border-radius: 6px;
  cursor: pointer;
  margin-bottom: 6px;
  border: 1px solid #ebeef5;
  transition: all 0.15s;
}
.group-item:hover {
  border-color: #409eff;
}
.group-item.active {
  background: #ecf5ff;
  border-color: #409eff;
}
.group-item-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.group-name {
  font-weight: 600;
  font-size: 14px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.group-item-meta {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}
.detail-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.matrix-table :deep(.field-key) {
  font-weight: 600;
  font-size: 13px;
}
.matrix-table :deep(.field-label) {
  font-size: 12px;
  color: #909399;
}
.cell-value {
  font-size: 13px;
  word-break: break-all;
}
.cell-meta {
  margin-top: 2px;
}
.cell.empty {
  color: #c0c4cc;
}
.empty {
  color: #909399;
  font-size: 13px;
  padding: 8px 0;
}
.doc-picker {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 6px;
  max-height: 300px;
  overflow: auto;
}
.doc-opt {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.doc-opt-name {
  font-size: 13px;
}
.doc-opt-meta {
  display: flex;
  gap: 6px;
  align-items: center;
  font-size: 12px;
  color: #909399;
}
</style>
