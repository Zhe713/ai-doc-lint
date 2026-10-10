<template>
  <div class="chat-page">
    <!-- 左栏：文档列表 -->
    <aside class="doc-side">
      <div class="side-title">选择要对话的文档</div>
      <div v-loading="docsLoading" class="doc-list">
        <div
          v-for="d in docs"
          :key="d.id"
          class="doc-item"
          :class="{ active: d.id === currentDocId, disabled: d.status !== 'parsed' }"
          @click="openDoc(d)"
        >
          <div class="doc-name" :title="d.filename">{{ d.filename }}</div>
          <div class="doc-meta">
            <el-tag size="small" :type="d.status === 'parsed' ? 'success' : 'info'">
              {{ statusLabel(d.status) }}
            </el-tag>
          </div>
        </div>
        <el-empty v-if="!docsLoading && docs.length === 0" description="暂无文档" :image-size="60" />
      </div>
    </aside>

    <!-- 右栏：对话区 -->
    <section class="chat-main">
      <template v-if="currentDocId">
        <div class="chat-head">
          <div class="head-doc">{{ currentDocName }}</div>
          <el-button size="small" text type="primary" @click="resetSession">新会话</el-button>
        </div>
        <div class="chat-wrap">
          <div class="chat-quick">
            <el-button size="small" plain @click="sendQuick('summarize')">总结文档</el-button>
            <el-button size="small" plain @click="sendQuick('list_findings')">列出问题</el-button>
            <el-button size="small" plain @click="sendQuick('locate_finding')">定位原文</el-button>
          </div>
          <div ref="chatBody" class="chat-body">
            <div
              v-for="m in chatMessages"
              :key="m.localKey"
              class="chat-msg"
              :class="m.role"
            >
              <div class="bubble">
                <div v-if="m.layer" class="layer-tag">{{ layerLabel(m.layer) }}</div>
                <div class="msg-text">{{ m.content }}</div>
                <div v-if="m.streaming" class="stream-dot">▍</div>
              </div>
            </div>
          </div>
          <div class="chat-input">
            <el-input
              v-model="chatDraft"
              placeholder="问问这份文档，Enter 发送"
              :disabled="chatSending"
              @keyup.enter="sendChat"
            />
            <el-button type="primary" :loading="chatSending" :disabled="chatSending" @click="sendChat">
              发送
            </el-button>
          </div>
        </div>
      </template>
      <div v-else class="chat-empty">
        <el-empty description="从左侧选择一份已解析文档开始对话" />
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'

import { createChatSession, getChatSession, streamChat } from '@/api/chat'
import { DocItem, listDocuments } from '@/api/findings'

interface UIMessage {
  localKey: number
  role: 'user' | 'assistant'
  content: string
  streaming?: boolean
  layer?: string
}

const docs = ref<DocItem[]>([])
const docsLoading = ref(false)
const currentDocId = ref('')
const currentDocName = ref('')
const chatMessages = ref<UIMessage[]>([])
const chatDraft = ref('')
const chatSending = ref(false)
const chatBody = ref<HTMLElement | null>(null)
let chatSessionId = ''
let localSeq = 0

const statusLabel = (s: string): string =>
  ({ parsed: '已解析', failed: '解析失败', pending: '排队中', running: '解析中', awaiting: '待确认' })[s] ?? s

const layerLabel = (l: string): string =>
  ({ l1: 'L1 规则直答', l2: 'L2 上下文', l3: 'L3 工具检索' })[l] ?? l

async function loadDocs() {
  docsLoading.value = true
  try {
    docs.value = await listDocuments(200)
  } catch {
    ElMessage.error('加载文档列表失败')
  } finally {
    docsLoading.value = false
  }
}

function scrollBottom() {
  requestAnimationFrame(() => {
    const el = chatBody.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

function pushMessage(role: 'user' | 'assistant', content: string,
                     streaming = false, layer?: string): UIMessage {
  const msg: UIMessage = { localKey: localSeq++, role, content, streaming, layer }
  chatMessages.value.push(msg)
  scrollBottom()
  return msg
}

async function openDoc(d: DocItem) {
  if (d.status !== 'parsed') {
    ElMessage.warning('该文档尚未解析完成，无法对话')
    return
  }
  if (d.id === currentDocId.value) return
  currentDocId.value = d.id
  currentDocName.value = d.filename
  chatSessionId = ''
  chatMessages.value = []
  await ensureSession()
}

async function ensureSession() {
  if (chatSessionId) return
  try {
    const session = await createChatSession(currentDocId.value)
    chatSessionId = session.id
    pushMessage('assistant', '你好，我是这份文档的校验助手。可以问我：有哪些问题、这条什么意思、怎么改、原文在哪里。')
  } catch {
    ElMessage.error('创建会话失败')
  }
}

async function resetSession() {
  chatSessionId = ''
  chatMessages.value = []
  await ensureSession()
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
        onDelta: (t) => { reply.content += t; scrollBottom() },
        onDone: () => { reply.streaming = false },
        onError: (t) => {
          reply.streaming = false
          reply.content = t
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

onMounted(loadDocs)
</script>

<style scoped>
.chat-page {
  display: flex;
  height: calc(100vh - 120px);
  gap: 12px;
}
.doc-side {
  width: 280px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  overflow: hidden;
}
.side-title {
  padding: 12px 14px;
  font-weight: 600;
  font-size: 14px;
  border-bottom: 1px solid #e4e7ed;
  background: #f8f9fb;
}
.doc-list {
  flex: 1;
  overflow-y: auto;
  padding: 6px 0;
}
.doc-item {
  padding: 10px 14px;
  cursor: pointer;
  border-left: 3px solid transparent;
  transition: background 0.15s;
}
.doc-item:hover {
  background: #f5f7fa;
}
.doc-item.active {
  background: #ecf5ff;
  border-left-color: #409eff;
}
.doc-item.disabled {
  cursor: not-allowed;
  opacity: 0.55;
}
.doc-name {
  font-size: 13px;
  word-break: break-all;
  line-height: 1.4;
  margin-bottom: 4px;
}
.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  overflow: hidden;
  min-width: 0;
}
.chat-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid #e4e7ed;
  background: #f8f9fb;
}
.head-doc {
  font-weight: 600;
  font-size: 14px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.chat-wrap {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
}
.chat-quick {
  display: flex;
  gap: 8px;
  padding: 10px 16px 0;
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
  max-width: 78%;
  padding: 8px 12px;
  border-radius: 8px;
  background: #f0f2f5;
  color: #303133;
  font-size: 14px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}
.chat-msg.user .bubble {
  background: #409eff;
  color: #fff;
}
.layer-tag {
  display: inline-block;
  font-size: 11px;
  color: #409eff;
  background: #ecf5ff;
  border-radius: 4px;
  padding: 0 6px;
  margin-bottom: 4px;
}
.chat-msg.user .layer-tag {
  color: #fff;
  background: rgba(255, 255, 255, 0.25);
}
.stream-dot {
  display: inline-block;
  animation: blink 1s infinite;
}
@keyframes blink {
  50% { opacity: 0; }
}
.chat-input {
  display: flex;
  gap: 8px;
  padding: 12px 16px;
  border-top: 1px solid #e4e7ed;
  background: #fff;
}
.chat-empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}
</style>
