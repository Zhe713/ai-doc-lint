<template>
  <div v-loading="loading">
    <div class="page-header">
      <el-button link @click="router.back()">返回</el-button>
      <h3 class="title">校验报告</h3>
      <el-button type="primary" plain @click="openAssistant">
        AI 助手
      </el-button>
      <el-button type="primary" plain :loading="annotating"
        @click="onAnnotate">
        生成批注版（Word）
      </el-button>
    </div>

    <el-alert v-if="docFlags?.continued_with_warning" type="error" :closable="false" show-icon
      title="该文件经「带警告继续」完成解析，内容可能缺失或存在识别偏差"
      description="下方结果仅供辅助参考，请务必对照原文件核实后再决策。" style="margin-bottom: 12px" />
    <el-alert v-if="docFlags?.checker_degraded" type="warning" :closable="false" show-icon
      title="错别字检查当前覆盖范围有限"
      description="专业词库未完全就绪，部分错别字可能未被检出，建议结合人工复核。" style="margin-bottom: 12px" />

    <el-tabs v-model="severity" class="sev-tabs">
      <el-tab-pane label="全部" name="all" />
      <el-tab-pane :label="`错误 ${counts.error}`" name="error" />
      <el-tab-pane :label="`警告 ${counts.warning}`" name="warning" />
      <el-tab-pane :label="`提示 ${counts.info}`" name="info" />
    </el-tabs>

    <div class="filters">
      <el-select v-model="checker" placeholder="检查器（格式 / 错别字 / 条款）" clearable style="width: 220px">
        <el-option label="格式检查" value="format" />
        <el-option label="错别字" value="typo" />
        <el-option label="条款检查" value="clause" />
      </el-select>
      <el-select v-model="fstatus" placeholder="处理状态（待处理 / 已忽略 / 已修复）" clearable style="width: 240px">
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
      <el-table-column label="操作" width="240">
        <template #default="{ row }">
          <el-button v-if="row.status !== 'fixed'" link type="success"
                     @click="change(row, 'fixed', 'fixed_by_user')">标已修复</el-button>
          <el-button v-if="row.status !== 'ignored'" link type="warning"
                     @click="markFalsePositive(row)">误报</el-button>
          <el-button link type="primary" @click="markConfirmed(row)">确认</el-button>
          <el-button v-if="row.status !== 'open'" link @click="change(row, 'open')">重开</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-drawer v-model="assistantOpen" title="AI 文档助手" size="420px"
               append-to-body destroy-on-close>
      <div class="chat-wrap">
        <div class="chat-quick">
          <el-button size="small" round
            @click="sendQuick('summarize')">整体总结</el-button>
          <el-button size="small" round
            @click="sendQuick('list_findings')">列出问题</el-button>
          <el-button size="small" round
            @click="sendQuick('locate_finding')">原文位置</el-button>
        </div>

        <div ref="chatBody" class="chat-body">
          <div v-for="m in chatMessages" :key="m.localKey"
               class="chat-msg" :class="m.role">
            <div class="bubble" style="white-space: pre-wrap;">{{ m.display }}<span
              v-if="m.streaming || m.pending" class="caret">▍</span></div>
          </div>
        </div>

        <div class="chat-input">
          <el-input v-model="chatDraft" placeholder="问问这份文档的问题，Enter 发送"
                    size="default" @keyup.enter="sendChat" />
          <el-button type="primary" :loading="chatSending"
                     @click="sendChat">发送</el-button>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Finding, listFindings, setFindingStatus } from '@/api/findings'
import { downloadAnnotated, requestAnnotated } from '@/api/annotate'
import { createChatSession, streamChat } from '@/api/chat'
import { getTask } from '@/api/documents'

const route = useRoute()
const router = useRouter()
const docId = route.params.docId as string

const loading = ref(false)
const findings = ref<Finding[]>([])
const severity = ref('all')
const checker = ref('')
const fstatus = ref('')
const docFlags = ref<import('@/api/findings').DocFlags | null>(null)

const sevType: Record<string, string> = { error: 'danger', warning: 'warning', info: 'info' }
const sevLabel: Record<string, string> = { error: '错误', warning: '警告', info: '提示' }
const checkerLabel: Record<string, string> = { format: '格式', typo: '错别字', clause: '条款' }

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
    docFlags.value = res.doc_flags ?? null
  } finally {
    loading.value = false
  }
}

async function change(
  row: Finding,
  status: 'open' | 'ignored' | 'fixed',
  feedback_reason?: 'false_positive' | 'confirmed' | 'fixed_by_user'
) {
  await setFindingStatus(row.id, status, feedback_reason)
  ElMessage.success('状态已更新')
  await reload()
}

// W7：误报反馈（负例）——确认后加入学习闭环
async function markFalsePositive(row: Finding) {
  try {
    await ElMessageBox.confirm(
      '将本条问题标记为误报，系统会学习此反馈并降低同类误报。确认继续？',
      '标记误报',
      { confirmButtonText: '确认误报', cancelButtonText: '取消', type: 'warning' }
    )
  } catch {
    return
  }
  await change(row, 'ignored', 'false_positive')
  ElMessage.success('已记录误报反馈')
}

// W7：确认有效（正例）——补充学习信号
async function markConfirmed(row: Finding) {
  await change(row, 'open', 'confirmed')
  ElMessage.success('已记录，谢谢反馈')
}

const annotating = ref(false)

async function onAnnotate() {
  annotating.value = true
  let taskId = ''
  try {
    const created = await requestAnnotated(docId)
    taskId = created.task_id
    // 轮询批注任务直到终态
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

onMounted(reload)

// ---------------- AI 助手 ----------------

interface UIMessage {
  localKey: number
  role: 'user' | 'assistant'
  content: string
  display: string      // 已渲染文本（打字机逐步增长）
  pending: string      // 待渲染文本
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

function pushMessage(role: 'user' | 'assistant', content: string,
                    streaming = false): UIMessage {
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

// ---- 打字机渲染：每 24ms 移入 1 字符（约 40 字/秒）；流结束后剩余内容同样慢速上屏 ----
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
        onDone: () => { reply.streaming = false },   // 不灌剩余，打字机继续慢速渲染
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
.chat-wrap {
  display: flex;
  flex-direction: column;
  height: 100%;
}
.chat-quick {
  display: flex;
  gap: 8px;
  padding: 0 16px 10px;
}
.chat-body {
  flex: 1;
  overflow-y: auto;
  padding: 8px 16px;
}
.chat-msg {
  display: flex;
  margin-bottom: 10px;
}
.chat-msg.user {
  justify-content: flex-end;
}
.chat-msg .bubble {
  max-width: 82%;
  padding: 8px 12px;
  border-radius: 10px;
  font-size: 14px;
  line-height: 1.5;
}
.chat-msg.user .bubble {
  background: #409eff;
  color: #fff;
}
.chat-msg.assistant .bubble {
  background: #f4f4f5;
  color: #303133;
}
.caret {
  animation: blink 1s steps(1) infinite;
}
@keyframes blink {
  50% { opacity: 0; }
}
.chat-input {
  display: flex;
  gap: 8px;
  padding: 12px 16px;
  border-top: 1px solid #ebeef5;
}
</style>
