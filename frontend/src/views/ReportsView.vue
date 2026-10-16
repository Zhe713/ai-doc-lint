<template>
  <div v-loading="loading">
    <div class="page-header">
      <el-button link @click="router.back()">返回</el-button>
      <h3 class="title">校验报告<span v-if="docName" class="doc-name">：{{ docName }}</span></h3>
      <el-button type="primary" plain @click="openAssistant">AI 助手</el-button>
      <el-button type="primary" plain :loading="annotating" @click="onAnnotate">
        生成批注版（Word）
      </el-button>
      <el-button plain :disabled="!docId" @click="downloadPdf">意见书 PDF</el-button>
      <el-button plain :disabled="!docId" @click="downloadXlsx">Excel 明细</el-button>
    </div>

    <el-alert v-if="docFlags?.continued_with_warning" type="error" :closable="false" show-icon
      title="该文件经「带警告继续」完成解析，内容可能缺失或存在识别偏差"
      description="下方结果仅供辅助参考，请务必对照原文件核实后再决策。" style="margin-bottom: 12px" />
    <el-alert v-if="docFlags?.checker_degraded" type="warning" :closable="false" show-icon
      title="错别字检查当前覆盖范围有限"
      description="专业词库未完全就绪，部分错别字可能未被检出，建议结合人工复核。" style="margin-bottom: 12px" />

    <!-- ① 总览看板 -->
    <div class="overview">
      <div class="stat-card">
        <div class="stat-value">{{ counts.total }}</div>
        <div class="stat-label">发现问题总数</div>
      </div>
      <div class="stat-card danger">
        <div class="stat-value">{{ counts.error }}</div>
        <div class="stat-label">错误</div>
      </div>
      <div class="stat-card warn">
        <div class="stat-value">{{ counts.warning }}</div>
        <div class="stat-label">警告</div>
      </div>
      <div class="stat-card info">
        <div class="stat-value">{{ counts.info }}</div>
        <div class="stat-label">提示</div>
      </div>
      <div class="stat-card ok">
        <div class="stat-value">{{ processedCount }}</div>
        <div class="stat-label">已处理</div>
      </div>
      <div class="progress-card">
        <div class="progress-label">处理进度 <b>{{ progressPercent }}%</b></div>
        <el-progress :percentage="progressPercent" :stroke-width="10" :show-text="false" />
      </div>
    </div>

    <!-- 视图切换 -->
    <el-tabs v-model="view" class="sev-tabs">
      <el-tab-pane label="风险清单" name="overview" />
      <el-tab-pane label="条款明细" name="clauses" />
      <el-tab-pane label="原文对照" name="compare" />
    </el-tabs>

    <!-- ② 风险清单（逐条销项） -->
    <div v-show="view === 'overview'">
      <div class="filters">
        <el-select v-model="severity" placeholder="全部级别" clearable style="width: 150px">
          <el-option label="错误" value="error" />
          <el-option label="警告" value="warning" />
          <el-option label="提示" value="info" />
        </el-select>
        <el-select v-model="checker" placeholder="检查类型" clearable style="width: 160px">
          <el-option label="格式检查" value="format" />
          <el-option label="错别字" value="typo" />
          <el-option label="条款检查" value="clause" />
        </el-select>
        <el-select v-model="fstatus" placeholder="处理状态" clearable style="width: 150px">
          <el-option label="待处理" value="open" />
          <el-option label="已忽略" value="ignored" />
          <el-option label="已修复" value="fixed" />
        </el-select>
        <el-button @click="reload">刷新</el-button>
      </div>

      <el-empty v-if="!filtered.length" description="没有符合条件的问题" />

      <div v-else class="risk-list">
        <div v-for="row in filtered" :key="row.id" class="risk-item" :class="row.severity">
          <div class="risk-left">
            <div class="risk-head">
              <el-tag :type="sevType[row.severity]" size="small" effect="dark">{{ sevLabel[row.severity] }}</el-tag>
              <span class="risk-checker">{{ checkerLabel[row.checker] ?? row.checker }}</span>
              <span v-if="row.status === 'fixed'" class="risk-done">已处理</span>
              <span v-else-if="row.status === 'ignored'" class="risk-ignored">已忽略</span>
            </div>
            <div class="risk-msg">{{ row.message }}</div>
            <div v-if="row.suggestion" class="risk-sugg">建议：{{ row.suggestion }}</div>
            <div v-if="row.location?.snippet" class="risk-snippet">原文：…{{ row.location.snippet }}…</div>
          </div>
          <div class="risk-actions">
            <el-button v-if="row.status !== 'fixed'" size="small" type="success" plain
              @click="change(row, 'fixed', 'fixed_by_user')">已修复</el-button>
            <el-button v-if="row.status !== 'ignored'" size="small" type="warning" plain
              @click="markFalsePositive(row)">误报</el-button>
            <el-button size="small" plain @click="markConfirmed(row)">确认有效</el-button>
            <el-button v-if="row.status !== 'open'" size="small" link @click="change(row, 'open')">重开</el-button>
          </div>
        </div>
      </div>
    </div>

    <!-- ③ 条款明细 -->
    <div v-show="view === 'clauses'">
      <el-empty v-if="!clauseGroups.length" description="暂无条款检查明细" />
      <el-card v-for="g in clauseGroups" :key="g.rule_id" shadow="never" class="clause-card">
        <template #header>
          <div class="clause-head">
            <b>{{ g.title }}</b>
            <div>
              <el-tag size="small" :type="g.error ? 'danger' : g.warning ? 'warning' : 'info'">
                命中 {{ g.total }} 条
              </el-tag>
              <el-tag v-if="g.error" size="small" type="danger" effect="plain">错误 {{ g.error }}</el-tag>
              <el-tag v-if="g.warning" size="small" type="warning" effect="plain">警告 {{ g.warning }}</el-tag>
              <el-tag v-if="g.open" size="small" type="info" effect="plain">待处理 {{ g.open }}</el-tag>
            </div>
          </div>
        </template>
        <div v-for="f in g.items" :key="f.id" class="clause-item">
          <span class="clause-msg">{{ f.message }}</span>
          <el-tag v-if="f.status === 'open'" size="small" type="warning">待处理</el-tag>
          <el-tag v-else-if="f.status === 'ignored'" size="small" type="info">已忽略</el-tag>
          <el-tag v-else size="small" type="success">已处理</el-tag>
        </div>
      </el-card>
    </div>

    <!-- ④ 原文对照（左原文 + 右风险双栏） -->
    <div v-show="view === 'compare'" class="compare-wrap" v-loading="textLoading">
      <div class="compare-left">
        <div class="compare-title">原文</div>
        <div v-if="plaintext" class="doc-text">
          <template v-for="(seg, i) in textSegs" :key="i">
            <span v-if="seg.hit" class="hit" :class="seg.severity">{{ seg.text }}</span>
            <template v-else>{{ seg.text }}</template>
          </template>
        </div>
        <el-empty v-else description="未找到可对照的原文（可能仍在解析或为扫描件）" :image-size="60" />
        <p v-if="textTruncated" class="trunc-hint">原文较长，仅展示前 20000 字</p>
      </div>
      <div class="compare-right">
        <div class="compare-title">风险定位</div>
        <el-empty v-if="!findings.length" description="暂无风险" :image-size="60" />
        <div v-for="row in findings" :key="row.id" class="risk-pin" :class="row.severity"
             :style="row.id === activeFinding ? 'border-color:#409eff' : ''"
             @click="scrollToSnippet(row)">
          <div class="risk-pin-head">
            <el-tag :type="sevType[row.severity]" size="small">{{ sevLabel[row.severity] }}</el-tag>
            <span class="pin-type">{{ checkerLabel[row.checker] ?? row.checker }}</span>
          </div>
          <div class="pin-msg">{{ row.message }}</div>
        </div>
      </div>
    </div>

    <el-drawer v-model="assistantOpen" title="AI 文档助手" size="420px" append-to-body destroy-on-close>
      <div class="chat-wrap">
        <div class="chat-quick">
          <el-button size="small" round @click="sendQuick('summarize')">整体总结</el-button>
          <el-button size="small" round @click="sendQuick('list_findings')">列出问题</el-button>
          <el-button size="small" round @click="sendQuick('locate_finding')">原文位置</el-button>
        </div>
        <div ref="chatBody" class="chat-body">
          <div v-for="m in chatMessages" :key="m.localKey" class="chat-msg" :class="m.role">
            <div class="bubble" style="white-space: pre-wrap;">{{ m.display }}<span
              v-if="m.streaming || m.pending" class="caret">▍</span></div>
          </div>
        </div>
        <div class="chat-input">
          <el-input v-model="chatDraft" placeholder="问问这份文档的问题，Enter 发送" size="default" @keyup.enter="sendChat" />
          <el-button type="primary" :loading="chatSending" @click="sendChat">发送</el-button>
        </div>
      </div>
    </el-drawer>

    <el-dialog v-model="fpDialogOpen" title="标记误报" width="440px" append-to-body>
      <p style="margin:0 0 4px;color:#606266">将本条问题标记为误报，系统会学习此反馈并降低同类误报。</p>
      <p style="margin:0 0 12px;color:#909399;font-size:13px">{{ fpTarget?.message }}</p>
      <el-form label-width="96px" @submit.prevent>
        <el-form-item label="误报原因" required>
          <el-select v-model="fpCause" placeholder="请选择原因（便于系统归因）" style="width:100%">
            <el-option v-for="c in FEEDBACK_CAUSE_OPTIONS" :key="c.value" :label="c.label" :value="c.value" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="fpDialogOpen = false">取消</el-button>
        <el-button type="warning" :disabled="!fpCause" @click="confirmFalsePositive">确认误报</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Finding, FEEDBACK_CAUSE_OPTIONS, FeedbackCause, listFindings, setFindingStatus } from '@/api/findings'
import { downloadAnnotated, requestAnnotated } from '@/api/annotate'
import client from '@/api/client'
import { createChatSession, streamChat } from '@/api/chat'
import { getPreview, getTask } from '@/api/documents'

const route = useRoute()
const router = useRouter()
const docId = route.params.docId as string

const loading = ref(false)
const findings = ref<Finding[]>([])
const severity = ref('')
const checker = ref('')
const fstatus = ref('')
const docFlags = ref<import('@/api/findings').DocFlags | null>(null)
const view = ref('overview')

const sevType: Record<string, string> = { error: 'danger', warning: 'warning', info: 'info' }
const sevLabel: Record<string, string> = { error: '错误', warning: '警告', info: '提示' }
const checkerLabel: Record<string, string> = { format: '格式', typo: '错别字', clause: '条款' }

const counts = computed(() => {
  const c = { total: 0, error: 0, warning: 0, info: 0 }
  findings.value.forEach((f) => {
    c.total += 1
    if (f.severity in c) c[f.severity as 'error'] += 1
  })
  return c
})

const processedCount = computed(() =>
  findings.value.filter((f) => f.status !== 'open').length
)

const progressPercent = computed(() =>
  counts.value.total ? Math.round((processedCount.value / counts.value.total) * 100) : 0
)

const filtered = computed(() =>
  findings.value.filter(
    (f) =>
      (!severity.value || f.severity === severity.value) &&
      (!checker.value || f.checker === checker.value) &&
      (!fstatus.value || f.status === fstatus.value)
  )
)

const clauseGroups = computed(() => {
  const map = new Map<string, { rule_id: string; title: string; items: Finding[]; total: number; error: number; warning: number; info: number; open: number }>()
  findings.value.forEach((f) => {
    if (f.checker !== 'clause') return
    const key = f.rule_id
    const g = map.get(key) ?? { rule_id: key, title: key, items: [], total: 0, error: 0, warning: 0, info: 0, open: 0 }
    g.items.push(f)
    g.total += 1
    if (f.severity === 'error') g.error += 1
    else if (f.severity === 'warning') g.warning += 1
    else g.info += 1
    if (f.status === 'open') g.open += 1
    map.set(key, g)
  })
  return [...map.values()].sort((a, b) => b.total - a.total)
})

async function reload() {
  loading.value = true
  try {
    const res = await listFindings(docId)
    findings.value = res.items
    docFlags.value = res.doc_flags ?? null
    docName.value = ''
    if (res.items.length) {
      loadText()
    }
  } finally {
    loading.value = false
  }
}

async function change(
  row: Finding,
  status: 'open' | 'ignored' | 'fixed',
  feedback_reason?: 'false_positive' | 'confirmed' | 'fixed_by_user',
  feedback_cause?: FeedbackCause
) {
  await setFindingStatus(row.id, status, feedback_reason, feedback_cause)
  ElMessage.success('状态已更新')
  await reload()
}

// W7：误报反馈（负例）
const fpDialogOpen = ref(false)
const fpTarget = ref<Finding | null>(null)
const fpCause = ref<FeedbackCause>(null)

function markFalsePositive(row: Finding) {
  fpTarget.value = row
  fpCause.value = null
  fpDialogOpen.value = true
}

async function confirmFalsePositive() {
  if (!fpTarget.value || !fpCause.value) return
  const row = fpTarget.value
  fpDialogOpen.value = false
  await change(row, 'ignored', 'false_positive', fpCause.value)
  ElMessage.success('已记录误报反馈')
}

async function markConfirmed(row: Finding) {
  await change(row, 'open', 'confirmed')
  ElMessage.success('已记录，谢谢反馈')
}

// ---------- 原文对照 ----------
const docName = ref('')
const plaintext = ref('')
const textTruncated = ref(false)
const textLoading = ref(false)
const activeFinding = ref<number | null>(null)
const compareLeft = ref<HTMLElement | null>(null)

interface Seg { text: string; hit: boolean; severity?: string }

const textSegs = computed<Seg[]>(() => {
  const text = plaintext.value
  if (!text) return []
  const hits: { start: number; end: number; severity: string }[] = []
  findings.value.forEach((f) => {
    const snip = (f.location?.snippet as string | undefined) ?? ''
    if (!snip) return
    const idx = text.indexOf(snip)
    if (idx >= 0) {
      const start = Math.max(0, idx - 12)
      const end = Math.min(text.length, idx + snip.length + 12)
      hits.push({ start, end, severity: f.severity })
    }
  })
  if (!hits.length) return [{ text, hit: false }]
  const sorted = hits.sort((a, b) => a.start - b.start)
  const segs: Seg[] = []
  let pos = 0
  sorted.forEach((h) => {
    if (h.start > pos) segs.push({ text: text.slice(pos, h.start), hit: false })
    segs.push({ text: text.slice(h.start, h.end), hit: true, severity: h.severity })
    pos = h.end
  })
  if (pos < text.length) segs.push({ text: text.slice(pos), hit: false })
  return segs
})

async function loadText() {
  const taskId = findings.value.find((f) => f.task_id)?.task_id
  if (!taskId) return
  textLoading.value = true
  try {
    const p = await getPreview(taskId)
    plaintext.value = p.plaintext
    textTruncated.value = p.truncated
    docName.value = p.filename
  } catch {
    // 无文本预览（扫描件等）时静默，对照区显示空态
  } finally {
    textLoading.value = false
  }
}

function scrollToSnippet(row: Finding) {
  activeFinding.value = row.id
  if (view.value !== 'compare') view.value = 'compare'
  const snip = (row.location?.snippet as string | undefined) ?? ''
  if (!snip) return
  requestAnimationFrame(() => {
    const root = document.querySelector('.compare-left .doc-text')
    if (!root) return
    // 找到第一个命中段（高亮 span）
    const marks = root.querySelectorAll('span.hit')
    for (const m of Array.from(marks)) {
      if ((m.textContent ?? '').includes(snip)) {
        m.scrollIntoView({ block: 'center', behavior: 'smooth' })
        return
      }
    }
  })
}

const annotating = ref(false)

async function onAnnotate() {
  annotating.value = true
  let taskId = ''
  try {
    const created = await requestAnnotated(docId)
    taskId = created.task_id
    for (let i = 0; i < 60; i += 1) {
      await new Promise((r) => setTimeout(r, 2000))
      const task = await getTask(taskId)
      if (task.status === 'parsed') {
        await downloadAnnotated(taskId)
        ElMessage.success('批注版已生成并开始下载')
        ElMessage.info('Word 文档：问题以批注形式标在原文；txt/pdf 文档：附完整原文可修改后重新上传')
        return
      }
      if (task.status === 'failed') {
        ElMessage.error(task.error_message || '生成失败')
        return
      }
    }
    ElMessage.warning('生成超时，请稍后在任务中查看')
  } catch (e: unknown) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    ElMessage.error(detail || '生成批注版失败')
  } finally {
    annotating.value = false
  }
}

async function downloadPdf() {
  const resp = await client.get(`/documents/${docId}/export/pdf`, { responseType: 'blob' })
  saveBlob(resp.data, `${docName.value || '合同'}_意见书.pdf`)
  ElMessage.success('意见书 PDF 已下载（含高管摘要与问题清单）')
}

async function downloadXlsx() {
  const resp = await client.get(`/documents/${docId}/export/xlsx`, { responseType: 'blob' })
  saveBlob(resp.data, `${docName.value || '合同'}_问题明细.xlsx`)
  ElMessage.success('Excel 明细已下载（含汇总表，可在 Word/Excel 打开）')
}

function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

onMounted(reload)

// ---------- AI 助手 ----------
interface UIMessage {
  localKey: number
  role: 'user' | 'assistant'
  content: string
  display: string
  pending: string
  streaming?: boolean
}

const assistantOpen = ref(false)
const chatMessages = ref<UIMessage[]>([])
const chatDraft = ref('')
const chatSending = ref(false)
const chatBody = ref<HTMLElement | null>(null)
let chatSessionId = ''
let localSeq = 0

function scrollBottom() {
  requestAnimationFrame(() => {
    const el = chatBody.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

async function openAssistant() {
  assistantOpen.value = true
  if (chatSessionId) return
  const session = await createChatSession(docId)
  chatSessionId = session.id
  chatMessages.value = [{
    localKey: localSeq++, role: 'assistant',
    content: '你好，我是这份文档的校验助手。可以问我：有哪些问题、这条什么意思、怎么改、原文在哪里。'
  }]
}

function pushMessage(role: 'user' | 'assistant', content: string, streaming = false): UIMessage {
  const msg: UIMessage = {
    localKey: localSeq++, role, content,
    display: streaming ? '' : content,
    pending: streaming ? '' : '',
    streaming,
  }
  chatMessages.value.push(msg)
  scrollBottom()
  return msg
}

let typer: number | undefined

function startTyper() {
  if (typer !== undefined) return
  typer = window.setInterval(() => {
    let active = false
    for (const m of chatMessages.value) {
      if (m.pending) {
        m.display += m.pending.slice(0, 1)
        m.pending = m.pending.slice(1)
        active = true
      }
    }
    if (active) scrollBottom()
    else { clearInterval(typer); typer = undefined }
  }, 24)
}

function flushPending(m: UIMessage) {
  if (m.pending) {
    m.display += m.pending
    m.pending = ''
  }
}

async function fire(content: string, buttonIntent?: string) {
  if (!content.trim()) return
  chatSending.value = true
  pushMessage('user', content)
  const reply = pushMessage('assistant', '', true)
  try {
    await streamChat(
      chatSessionId, content,
      {
        onDelta: (t) => { reply.pending += t; startTyper() },
        onDone: () => { reply.streaming = false },
        onError: (t) => {
          reply.streaming = false
          flushPending(reply)
          reply.content = t
          reply.display = t
        }
      },
      buttonIntent
    )
  } finally {
    reply.streaming = false
    chatSending.value = false
  }
}

function sendChat() {
  const text = chatDraft.value
  chatDraft.value = ''
  fire(text)
}

function sendQuick(intent: string) {
  const map: Record<string, string> = {
    summarize: '总结一下这份文档',
    list_findings: '列出所有待处理问题',
    locate_finding: '这个问题在原文哪里'
  }
  fire(map[intent], intent)
}
</script>

<style scoped>
.page-header { display: flex; align-items: center; gap: 12px; }
.title { margin: 0; }
.doc-name { color: #909399; font-size: 14px; font-weight: 400; }
.filters { display: flex; gap: 12px; margin-bottom: 12px; }

/* ① 总览 */
.overview {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 10px;
  margin-bottom: 8px;
}
.stat-card {
  background: #f5f7fa;
  border-radius: 8px;
  padding: 10px 12px;
  text-align: center;
}
.stat-card .stat-value { font-size: 26px; font-weight: 700; color: #303133; }
.stat-card.danger .stat-value { color: #f56c6c; }
.stat-card.warn .stat-value { color: #e6a23c; }
.stat-card.info .stat-value { color: #909399; }
.stat-card.ok .stat-value { color: #67c23a; }
.stat-card .stat-label { color: #909399; font-size: 12px; margin-top: 2px; }
.progress-card {
  grid-column: span 2;
  background: #f5f7fa;
  border-radius: 8px;
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 6px;
}
.progress-label { color: #606266; font-size: 13px; }

/* ② 风险清单（卡片逐条销项） */
.risk-list { display: flex; flex-direction: column; gap: 10px; }
.risk-item {
  display: flex;
  justify-content: space-between;
  gap: 14px;
  border: 1px solid #ebeef5;
  border-left: 4px solid #909399;
  border-radius: 8px;
  padding: 12px 14px;
  background: #fff;
}
.risk-item.error { border-left-color: #f56c6c; }
.risk-item.warning { border-left-color: #e6a23c; }
.risk-item.info { border-left-color: #909399; }
.risk-left { flex: 1; min-width: 0; }
.risk-head { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.risk-checker { color: #606266; font-size: 13px; }
.risk-done { color: #67c23a; font-size: 12px; font-weight: 600; }
.risk-ignored { color: #909399; font-size: 12px; font-weight: 600; }
.risk-msg { font-size: 14px; color: #303133; line-height: 1.5; }
.risk-sugg { color: #67c23a; font-size: 13px; margin-top: 4px; }
.risk-snippet { color: #909399; font-size: 12px; margin-top: 4px; }
.risk-actions { display: flex; align-items: center; gap: 4px; flex-shrink: 0; }

/* ③ 条款明细 */
.clause-card { margin-bottom: 12px; }
.clause-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.clause-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 6px 0;
  border-bottom: 1px dashed #ebeef5;
}
.clause-item:last-child { border-bottom: none; }
.clause-msg { flex: 1; min-width: 0; color: #303133; font-size: 13px; }

/* ④ 原文对照 */
.compare-wrap { display: grid; grid-template-columns: 1fr 340px; gap: 12px; height: 62vh; }
.compare-left {
  border: 1px solid #ebeef5;
  border-radius: 8px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.compare-title {
  padding: 8px 12px;
  background: #f5f7fa;
  font-weight: 600;
  font-size: 13px;
  border-bottom: 1px solid #ebeef5;
  flex-shrink: 0;
}
.doc-text {
  flex: 1;
  overflow-y: auto;
  padding: 12px 14px;
  font-size: 14px;
  line-height: 1.7;
  color: #303133;
  white-space: pre-wrap;
  word-break: break-word;
}
.hit {
  background: #fef0f0;
  color: #f56c6c;
  border-radius: 3px;
  padding: 0 2px;
  cursor: pointer;
}
.hit.warning { background: #fdf6ec; color: #e6a23c; }
.hit.info { background: #f4f4f5; color: #909399; }
.trunc-hint { color: #909399; font-size: 12px; padding: 0 12px 8px; }
.compare-right {
  border: 1px solid #ebeef5;
  border-radius: 8px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}
.risk-pin {
  margin: 8px 10px;
  border: 1px solid #ebeef5;
  border-left: 3px solid #909399;
  border-radius: 6px;
  padding: 8px 10px;
  cursor: pointer;
}
.risk-pin.error { border-left-color: #f56c6c; }
.risk-pin.warning { border-left-color: #e6a23c; }
.risk-pin.info { border-left-color: #909399; }
.risk-pin-head { display: flex; align-items: center; gap: 6px; }
.pin-type { color: #606266; font-size: 12px; }
.pin-msg { font-size: 13px; color: #303133; margin-top: 4px; }

.chat-wrap { display: flex; flex-direction: column; height: 100%; }
.chat-quick { display: flex; gap: 8px; padding: 0 16px 10px; }
.chat-body { flex: 1; overflow-y: auto; padding: 8px 16px; }
.chat-msg { display: flex; margin-bottom: 10px; }
.chat-msg.user { justify-content: flex-end; }
.chat-msg .bubble { max-width: 82%; padding: 8px 12px; border-radius: 10px; font-size: 14px; line-height: 1.5; }
.chat-msg.user .bubble { background: #409eff; color: #fff; }
.chat-msg.assistant .bubble { background: #f4f4f5; color: #303133; }
.caret { animation: blink 1s steps(1) infinite; }
@keyframes blink { 50% { opacity: 0; } }
.chat-input { display: flex; gap: 8px; padding: 12px 16px; border-top: 1px solid #ebeef5; }

@media (max-width: 900px) {
  .overview { grid-template-columns: repeat(3, 1fr); }
  .progress-card { grid-column: span 3; }
  .compare-wrap { grid-template-columns: 1fr; height: auto; }
  .compare-right { max-height: 40vh; }
  .risk-item { flex-direction: column; }
}
</style>
