<template>
  <div v-loading="loading">
    <div class="page-header">
      <el-button link @click="router.back()">返回</el-button>
      <h3 class="title">校验报告<span v-if="docName" class="doc-name">：{{ docName }}</span></h3>
      <el-button type="primary" plain @click="openAssistant">AI 助手</el-button>
      <el-button type="primary" plain :loading="annotating" @click="onAnnotate">
        生成批注版
      </el-button>
      <el-button plain :disabled="!docId" @click="downloadPdf">意见书 PDF</el-button>
      <el-button plain :disabled="!docId" @click="downloadXlsx">Excel 明细</el-button>
    </div>

    <el-alert v-if="coverage?.continued_with_warning" type="error" :closable="false" show-icon
      title="该文件经「带警告继续」完成解析，内容可能缺失或存在识别偏差"
      description="下方结果仅供辅助参考，请务必对照原文件核实后再决策。" style="margin-bottom: 12px" />
    <el-alert v-if="coverage?.checker_degraded" type="warning" :closable="false" show-icon
      title="部分检查能力降级，检出范围有限"
      :description="degradedText" style="margin-bottom: 12px" />

    <!-- 放行状态：不是徽标，是落过库的事实 -->
    <el-alert v-if="coverage?.released" type="success" :closable="false" show-icon
      style="margin-bottom: 12px">
      <template #title>
        该版本已放行（{{ coverage.released.label }}）
        <span class="release-meta">
          {{ coverage.released.changed_ratio != null ? `与基线差异 ${(coverage.released.changed_ratio * 100).toFixed(1)}% · ` : '' }}
          {{ coverage.released.created_at ? formatTime(coverage.released.created_at) : '' }}
        </span>
      </template>
      <div class="release-body">
        放行表示这一版经确认无需再改；下方问题清单仍保留可追溯。
        <el-button link type="danger" @click="onRevokeRelease">撤销放行</el-button>
      </div>
    </el-alert>

    <!-- 未执行的检查必须显式告知：否则「没检查」会被误读成「检查了没问题」 -->
    <el-alert v-if="wholeSkipped.length" type="warning" :closable="false" show-icon
      title="有整类检查未执行，本报告不是完整的审查结论" style="margin-bottom: 12px">
      <div class="skipped-line">
        未执行：<b>{{ wholeSkipped.map((s) => s.label).join('、') }}</b>
      </div>
      <div class="skipped-hint">
        常见原因：该文档类型没有对应的规则包。请改用匹配的文档类型重新上传，
        或只把这份报告当作「已执行那几项」的结论。
      </div>
    </el-alert>
    <div v-if="partialSkipped.length" class="skipped-minor">
      另有 {{ partialSkippedTotal }} 条单项规则因格式限制未执行（{{ partialSkipped.map((s) => s.label).join('、') }}），
      属已知能力边界。
    </div>

    <!-- 被主动停用的规则要说出来：否则同样被误读成「查过没问题」 -->
    <div v-if="coverage?.suppressed_rules?.length" class="skipped-minor">
      已停用规则：<b>{{ coverage.suppressed_rules.join('、') }}</b>
      （这些规则本次没有执行，可在「审查规则」页恢复）
    </div>

    <el-alert v-if="coverage?.review_pending" type="info" :closable="false" show-icon
      title="审查仍在进行中，当前结果可能不完整"
      description="页面会自动刷新；在结果稳定前请不要据此下结论。" style="margin-bottom: 12px" />
    <el-alert v-if="coverage?.review_failed" type="error" :closable="false" show-icon
      title="本次审查执行失败，结论不可用"
      description="检查任务未能正常完成，请重新上传文档或稍后重试；下方若有结果也不代表完整审查。" style="margin-bottom: 12px" />

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

    <!-- 判定来源分布：回答「哪些是规则命中，哪些是大模型判的」 -->
    <div class="source-bar">
      <span class="source-bar-title">判定来源</span>
      <span class="src-item rule">纯规则命中 <b>{{ sourceCounts.rule }}</b></span>
      <span class="src-item hybrid">规则 + AI 复核 <b>{{ sourceCounts.hybrid }}</b></span>
      <span class="src-item llm">AI 判定 <b>{{ sourceCounts.llm }}</b></span>
      <span class="src-note">
        <template v-if="aiCount">
          本报告 {{ counts.total }} 条问题中，{{ aiCount }} 条有大模型参与判定，
          点开每条可看到 AI 给出的依据。
        </template>
        <template v-else>本报告问题全部由确定性规则命中，未调用大模型。</template>
      </span>
    </div>

    <!-- 自动抽取的关键字段：金额/日期/当事人等，审查结论要和它们对得上 -->
    <el-card v-if="fields.length" shadow="never" class="fields-card">
      <template #header>
        <div class="fields-head">
          <b>自动提取的关键信息</b>
          <span class="fields-note">
            共 {{ fields.length }} 项。抽取结果直接用于数值勾稽，请核对是否与合同一致。
          </span>
        </div>
      </template>
      <div class="fields-grid">
        <div v-for="f in fields" :key="f.id" class="field-item">
          <div class="field-label">
            {{ f.field_label }}
            <el-tag size="small" :type="f.source === 'llm' ? 'warning' : 'info'" effect="plain">
              {{ f.source === 'llm' ? 'AI 提取' : '规则提取' }}
            </el-tag>
          </div>
          <div class="field-value" :class="{ empty: !fieldText(f) }">
            {{ fieldText(f) || '未识别到' }}
          </div>
        </div>
      </div>
    </el-card>

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
        <el-select v-model="sourceFilter" placeholder="判定来源" clearable style="width: 160px">
          <el-option label="纯规则命中" value="rule" />
          <el-option label="规则 + AI 复核" value="hybrid" />
          <el-option label="AI 判定" value="llm" />
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
              <el-tag
                size="small"
                effect="plain"
                :type="SOURCE_TAG_TYPE[(row.source as FindingSource) || 'rule']"
              >
                {{ SOURCE_LABELS[(row.source as FindingSource) || 'rule'] }}
              </el-tag>
              <span v-if="row.status === 'fixed'" class="risk-done">已处理</span>
              <span v-else-if="row.status === 'ignored'" class="risk-ignored">已忽略</span>
            </div>
            <div class="risk-msg">{{ row.message }}</div>
            <div v-if="row.suggestion" class="risk-sugg">建议：{{ row.suggestion }}</div>
            <!-- 错别字：整句 + 高亮被判定有误的词，用户能自己判断对错 -->
            <div v-if="row.location?.snippet" class="risk-snippet">
              原文：<template v-for="(part, pi) in snippetParts(row)" :key="pi"><span
                v-if="part.hit" class="wrong-word">{{ part.text }}</span><template v-else>{{ part.text }}</template></template>
            </div>
            <div v-if="row.llm_reason" class="risk-ai">
              <span class="ai-dot">AI</span>
              <span class="ai-reason">{{ row.llm_reason }}</span>
              <span v-if="row.llm_model" class="ai-model">{{ row.llm_model }}</span>
            </div>
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
          <el-tag size="small" effect="plain" :type="SOURCE_TAG_TYPE[(f.source as FindingSource) || 'rule']">
            {{ SOURCE_LABELS[(f.source as FindingSource) || 'rule'] }}
          </el-tag>
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
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  type Coverage,
  type DocumentField,
  type Finding,
  type FindingSource,
  FEEDBACK_CAUSE_OPTIONS,
  type FeedbackCause,
  SOURCE_LABELS,
  SOURCE_TAG_TYPE,
  type TagType,
  isAiAssisted,
  listFields,
  listFindings,
  setFindingStatus
} from '@/api/findings'
import { revokeRelease } from '@/api/diff'
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
const sourceFilter = ref('')
const coverage = ref<Coverage | null>(null)
const fields = ref<DocumentField[]>([])
const view = ref('overview')
// 审查未完成时的自动续等（30 次 × 3s ≈ 90s 上限，避免无限轮询）
let pendingTimer: number | undefined
let pendingPolls = 0

const skippedChecks = computed(() => coverage.value?.checks_skipped ?? [])
// 整类未执行（如该文档类型没有条款规则包）才是真风险；个别规则跳过属能力边界，只做轻提示
const wholeSkipped = computed(() => skippedChecks.value.filter((s) => s.whole_check))
const partialSkipped = computed(() => skippedChecks.value.filter((s) => !s.whole_check))
const partialSkippedTotal = computed(() =>
  partialSkipped.value.reduce((n, s) => n + s.rules.length, 0)
)
const degradedText = computed(() => {
  const detail = coverage.value?.checker_warning_detail ?? []
  if (!detail.length) return '部分检查器运行在受限模式，检出范围可能不足，建议结合人工复核。'
  return detail.join('；')
})

const sevType: Record<string, TagType> = { error: 'danger', warning: 'warning', info: 'info' }
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

/** 判定来源分布：规则命中 / 规则+AI 复核 / AI 判定 */
const sourceCounts = computed(() => {
  const c = { rule: 0, hybrid: 0, llm: 0 }
  findings.value.forEach((f) => {
    const s = (f.source as FindingSource) || 'rule'
    if (s in c) c[s] += 1
  })
  return c
})

/** 有大模型参与判定的条数（hybrid + llm） */
const aiCount = computed(() => findings.value.filter(isAiAssisted).length)

const filtered = computed(() =>
  findings.value.filter(
    (f) =>
      (!severity.value || f.severity === severity.value) &&
      (!checker.value || f.checker === checker.value) &&
      (!fstatus.value || f.status === fstatus.value) &&
      (!sourceFilter.value || ((f.source as FindingSource) || 'rule') === sourceFilter.value)
  )
)

/**
 * 把 snippet 里被判定有误的词单独切出来高亮。
 * 错别字类 finding 的 message 形如「疑似错别字：「由其」建议改为「尤其」」，
 * 取第一个「」里的词作为命中词，用户看整句上下文即可自己判断是否真错。
 */
function snippetParts(row: Finding): { text: string; hit: boolean }[] {
  const snip = (row.location?.snippet as string | undefined) ?? ''
  if (!snip) return []
  const m = /「([^」]{1,8})」/.exec(row.message)
  const wrong = m?.[1] ?? ''
  if (!wrong) return [{ text: snip, hit: false }]
  const idx = snip.indexOf(wrong)
  if (idx < 0) return [{ text: snip, hit: false }]
  return [
    { text: snip.slice(0, idx), hit: false },
    { text: wrong, hit: true },
    { text: snip.slice(idx + wrong.length), hit: false }
  ]
}

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
    coverage.value = res.coverage ?? null
    docName.value = ''
    // 字段与问题清单分开取：字段可能为空，但空也要显示「未识别到」
    fields.value = await listFields(docId).catch(() => [])
    if (res.items.length) {
      loadText()
    }
    // 审查尚未跑完：自动续等，避免用户在「0 问题」的中间态下得出错误结论
    if (res.coverage?.review_pending && pendingPolls < 30) {
      pendingPolls += 1
      if (pendingTimer) window.clearTimeout(pendingTimer)
      pendingTimer = window.setTimeout(() => reload(), 3000)
    }
  } finally {
    loading.value = false
  }
}

function formatTime(iso: string) {
  return new Date(iso).toLocaleString('zh-CN')
}

/** 字段值展示：数字/日期/文本三套类型统一成一行可读文本 */
function fieldText(f: DocumentField): string {
  if (f.value_number != null) return String(f.value_number)
  if (f.value_date) return f.value_date
  return (f.value_text ?? '').trim()
}

async function onRevokeRelease() {
  await revokeRelease(docId)
  ElMessage.success('已撤销放行')
  await reload()
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
  // 语义澄清：确认有效 = 这条问题是真的（不是误报），但合同还没改，所以仍留在待处理。
  // 之前提示「已记录，谢谢反馈」会让人以为已处置完成，这里把下一步说清楚。
  await change(row, 'open', 'confirmed')
  ElMessage.success('已确认为真实问题；改完合同后请点「标记已修复」')
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
        ElMessage.info('与原文件同格式：PDF 高亮批注、Word 原生批注、txt/md 行内批注，原文内容不改动')
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
onUnmounted(() => {
  if (pendingTimer) window.clearTimeout(pendingTimer)
})

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
  try {
    const session = await createChatSession(docId)
    chatSessionId = session.id
  } catch {
    ElMessage.error('创建会话失败，请稍后重试')
    assistantOpen.value = false
    return
  }
  const greeting = '你好，我是这份文档的校验助手。可以问我：有哪些问题、这条什么意思、怎么改、原文在哪里。'
  chatMessages.value = [{
    localKey: localSeq++, role: 'assistant', content: greeting,
    display: greeting, pending: '', streaming: false
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
.release-meta { color: #67c23a; font-size: 12px; margin-left: 8px; }
.release-body { color: #606266; font-size: 13px; }
.fields-card { margin: 12px 0; }
.fields-head { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
.fields-note { color: #909399; font-size: 12px; }
.fields-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 10px;
}
.field-item {
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 8px 10px;
  background: #fafafa;
}
.field-label {
  color: #909399;
  font-size: 12px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.field-value {
  margin-top: 4px;
  font-size: 14px;
  color: #303133;
  word-break: break-all;
}
.field-value.empty { color: #c0c4cc; }

.page-header { display: flex; align-items: center; gap: 12px; }
.title { margin: 0; }
.doc-name { color: #909399; font-size: 14px; font-weight: 400; }
.filters { display: flex; gap: 12px; margin-bottom: 12px; }

/* 未执行检查的提示 */
.skipped-line { font-size: 13px; margin-bottom: 4px; }
.skipped-hint { font-size: 12px; color: #909399; line-height: 1.6; }
.skipped-minor {
  font-size: 12px;
  color: #909399;
  background: #fafafa;
  border: 1px dashed #e4e7ed;
  border-radius: 6px;
  padding: 8px 12px;
  margin-bottom: 12px;
  line-height: 1.6;
}

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

/* 判定来源条：一眼看出哪些是大模型判的 */
.source-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  padding: 10px 14px;
  margin: 12px 0 4px;
  background: #f5f7fa;
  border-radius: 8px;
  font-size: 13px;
}
.source-bar-title { color: #303133; font-weight: 600; }
.src-item { padding: 2px 10px; border-radius: 12px; font-size: 12px; }
.src-item b { font-size: 14px; margin-left: 2px; }
.src-item.rule { background: #e9e9eb; color: #606266; }
.src-item.hybrid { background: #fdf6ec; color: #b88230; }
.src-item.llm { background: #f0f9eb; color: #529b2e; }
.src-note { color: #909399; font-size: 12px; margin-left: auto; }

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
.risk-snippet { color: #909399; font-size: 12px; margin-top: 4px; line-height: 1.7; }
.wrong-word { color: #f56c6c; font-weight: 600; text-decoration: underline wavy #f56c6c; }

/* AI 判定依据：让「AI 到底做了什么」可见 */
.risk-ai {
  display: flex;
  align-items: baseline;
  gap: 6px;
  margin-top: 6px;
  padding: 6px 10px;
  background: #f0f9eb;
  border-radius: 6px;
  font-size: 12px;
  color: #529b2e;
}
.ai-dot {
  flex: none;
  padding: 0 5px;
  border-radius: 4px;
  background: #67c23a;
  color: #fff;
  font-size: 11px;
  font-weight: 700;
  line-height: 16px;
}
.ai-reason { flex: 1; color: #4a7c2f; }
.ai-model { flex: none; color: #a0c98a; font-size: 11px; }
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
