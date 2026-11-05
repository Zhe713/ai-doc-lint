<template>
  <div>
    <!-- 顶部操作 -->
    <el-card style="margin-bottom: 16px">
      <div style="display: flex; justify-content: space-between; align-items: center">
        <div>
          <b>学习反馈</b>
          <span style="margin-left: 12px; color: #909399; font-size: 12px">
            系统根据用户反馈自动学习：误报越用越少、漏报越用越补
          </span>
        </div>
        <div>
          <el-button type="primary" :loading="tuning" @click="triggerTuning">
            立即诊断一次
          </el-button>
          <el-button @click="reloadAll" :loading="loading">刷新</el-button>
        </div>
      </div>
      <div v-if="tuning && summary" style="margin-top: 10px">
        <el-alert type="success" :closable="false"
          :title="`诊断完成：新增白名单词 ${summary.whitelist_added} 个（共 ${summary.whitelist_total} 个）；${(summary.whitelist_pending ?? []).length ? `拦截未验证候选词 ${summary.whitelist_pending.length} 个；` : ''}建议停用规则 ${summary.suggested_rules.length} 条`" />
      </div>
    </el-card>

    <!-- 反馈统计 -->
    <el-card style="margin-bottom: 16px">
      <template #header><b>规则反馈统计</b></template>
      <el-table :data="stats" stripe v-loading="loading" max-height="420">
        <el-table-column label="检查器" width="110">
          <template #default="{ row }">{{ checkerLabel[row.checker] ?? row.checker }}</template>
        </el-table-column>
        <el-table-column label="规则" prop="rule_id" min-width="180" show-overflow-tooltip />
        <el-table-column label="命中数" prop="hit_count" width="90" align="right" />
        <el-table-column label="误报数" prop="false_count" width="90" align="right">
          <template #default="{ row }">
            <span :class="{ 'text-danger': row.false_rate >= 0.3 }">{{ row.false_count }}</span>
          </template>
        </el-table-column>
        <el-table-column label="确认有效" prop="confirmed_count" width="90" align="right" />
        <el-table-column label="误报率" width="100" align="right">
          <template #default="{ row }">
            <el-tag :type="rateTag(row.false_rate)" size="small">
              {{ (row.false_rate * 100).toFixed(1) }}%
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="最近反馈" width="150">
          <template #default="{ row }">{{ fmtTime(row.last_feedback_at) }}</template>
        </el-table-column>
      </el-table>
      <!-- W7-5 误报原因分布（结构化归因） -->
      <div v-if="causeTags.length" style="margin-top: 12px; display: flex; align-items: center; flex-wrap: wrap; gap: 6px">
        <span style="color: #909399; font-size: 13px">误报原因分布：</span>
        <el-tag v-for="t in causeTags" :key="t.label" size="small" type="info">
          {{ t.label }} × {{ t.count }}
        </el-tag>
      </div>
      <el-empty v-if="!stats.length" description="暂无用户反馈数据。在报告页把问题标记为「误报」或「确认」后，这里会出现学习信号。" />
    </el-card>

    <!-- 停用建议（人工闸门） -->
    <el-card style="margin-bottom: 16px">
      <template #header>
        <b>规则停用建议</b>
        <span style="margin-left: 12px; color: #909399; font-size: 12px">
          误报率超过 30% 的规则自动挂起，需管理员确认后停用
        </span>
      </template>
      <el-tabs v-model="suggTab">
        <el-tab-pane label="待确认" name="pending">
          <el-table :data="suggestions" stripe v-loading="loading">
            <el-table-column label="检查器" width="110">
              <template #default="{ row }">{{ checkerLabel[row.checker] ?? row.checker }}</template>
            </el-table-column>
            <el-table-column label="规则" prop="rule_id" min-width="160" show-overflow-tooltip />
            <el-table-column label="误报情况" width="120" align="right">
              <template #default="{ row }">{{ row.false_count }} / {{ row.hit_count }}（{{ (row.false_rate * 100).toFixed(1) }}%）</template>
            </el-table-column>
            <el-table-column label="原因" prop="reason" min-width="220" show-overflow-tooltip />
            <el-table-column label="操作" width="160">
              <template #default="{ row }">
                <el-button size="small" type="danger" @click="decide(row as SuggestionItem, 'confirm')">确认停用</el-button>
                <el-button size="small" @click="decide(row as SuggestionItem, 'reject')">拒绝</el-button>
              </template>
            </el-table-column>
          </el-table>
          <el-empty v-if="!suggestions.length" description="没有待确认的停用建议" />
        </el-tab-pane>
        <el-tab-pane label="已处理" name="resolved">
          <el-table :data="resolvedSuggestions" stripe>
            <el-table-column label="检查器" width="110">
              <template #default="{ row }">{{ checkerLabel[row.checker] ?? row.checker }}</template>
            </el-table-column>
            <el-table-column label="规则" prop="rule_id" min-width="160" show-overflow-tooltip />
            <el-table-column label="误报率" width="100" align="right">
              <template #default="{ row }">{{ (row.false_rate * 100).toFixed(1) }}%</template>
            </el-table-column>
            <el-table-column label="结果" width="90">
              <template #default="{ row }">
                <el-tag :type="row.status === 'confirmed' ? 'danger' : 'info'" size="small">
                  {{ row.status === 'confirmed' ? '已停用' : '已拒绝' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="处理时间" width="150">
              <template #default="{ row }">{{ fmtTime(row.resolved_at) }}</template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </el-card>

    <!-- 学习日志 -->
    <el-card>
      <template #header><b>学习操作日志</b></template>
      <el-table :data="logs" stripe max-height="360">
        <el-table-column label="时间" width="170">
          <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="动作" width="130">
          <template #default="{ row }">{{ actionLabel[row.action] ?? row.action }}</template>
        </el-table-column>
        <el-table-column label="详情" min-width="320">
          <template #default="{ row }">
            <span style="white-space: pre-wrap;">{{ fmtDetail(row as LearningLogItem) }}</span>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  FEEDBACK_CAUSE_OPTIONS,
  FeedbackStat,
  LearningLogItem,
  SuggestionItem,
  TagType,
  TuningSummary,
  decideSuggestion,
  getLearningFeedback,
  getLearningLogs,
  getLearningSuggestions,
  runTuningManually
} from '@/api/findings'

const loading = ref(false)
const tuning = ref(false)
const summary = ref<TuningSummary | null>(null)
const stats = ref<FeedbackStat[]>([])
const suggestions = ref<SuggestionItem[]>([])
const resolvedSuggestions = ref<SuggestionItem[]>([])
const logs = ref<LearningLogItem[]>([])
const suggTab = ref('pending')

const checkerLabel: Record<string, string> = {
  format: '格式', typo: '错别字', clause: '条款', cross: '勾稽', cross_doc: '跨文档'
}
const actionLabel: Record<string, string> = {
  whitelist_add: '白名单扩充',
  whitelist_skipped: '白名单拦截',
  rule_suggest: '生成停用建议',
  suggestion_confirm: '确认停用',
  suggestion_reject: '拒绝建议',
  tuning_run: '学习诊断'
}

// W7-5 误报原因分布：汇总所有规则的 causes
const causeTags = computed<{ label: string; count: number }[]>(() => {
  const agg: Record<string, number> = {}
  for (const s of stats.value) {
    for (const [code, cnt] of Object.entries(s.causes ?? {})) {
      agg[code] = (agg[code] ?? 0) + cnt
    }
  }
  const order = FEEDBACK_CAUSE_OPTIONS.map(c => c.value)
  return Object.entries(agg)
    .map(([code, count]) => ({
      label: FEEDBACK_CAUSE_OPTIONS.find(c => c.value === code)?.label ?? code,
      count
    }))
    .sort((a, b) => {
      const ia = order.indexOf(a.label) >= 0 ? order.indexOf(a.label) : 99
      const ib = order.indexOf(b.label) >= 0 ? order.indexOf(b.label) : 99
      return ia - ib || b.count - a.count
    })
})

function rateTag(rate: number): TagType {
  if (rate >= 0.3) return 'danger'
  if (rate >= 0.15) return 'warning'
  return 'success'
}

function fmtTime(s: string | null): string {
  if (!s) return '-'
  return s.replace('T', ' ').slice(0, 19)
}

// 日志 detail 是自由 JSON：读之前先收敛类型，别指望 TS 知道里面有什么
function asList(v: unknown): string[] {
  return Array.isArray(v) ? v.map((x) => String(x)) : []
}
function asNum(v: unknown): number {
  return typeof v === 'number' ? v : 0
}
function asText(v: unknown): string {
  return v == null ? '' : String(v)
}

function fmtDetail(row: LearningLogItem): string {
  const d = row.detail ?? {}
  if (row.action === 'whitelist_add') {
    return `新增白名单词 ${asNum(d.added)} 个（共 ${asNum(d.total)} 个）：${asList(d.words).join('、')}；回滚方式：删除 typo_whitelist_auto.txt`
  }
  if (row.action === 'whitelist_skipped') {
    return `未通过验证不自动生效（${asList(d.words).join('、')}）：${Object.values((d.reasons as Record<string, unknown>) ?? {}).map(asText).join('；')}`
  }
  if (row.action === 'rule_suggest') {
    return `建议停用规则：${asList(d.rules).join('、')}（阈值 ${asNum(d.threshold_rate) * 100}%）`
  }
  if (row.action === 'suggestion_confirm') {
    return `已停用规则 ${asText(d.rule_id)}（${asText(d.pack_type ?? d.checker)}，${d.scope === 'global' ? '全员生效' : '仅自己'}）`
  }
  if (row.action === 'suggestion_reject') {
    return `拒绝停用规则 ${asText(d.rule_id)}`
  }
  if (row.action === 'tuning_run') {
    const pending = asList(d.whitelist_pending).length
    return `触发方式：${d.trigger === 'daily' ? '每日定时' : '手动'}；新增白名单词 ${asNum(d.whitelist_added)} 个；${pending ? `拦截 ${pending} 个候选词（未通过验证）；` : ''}建议停用 ${asList(d.suggested_rules).length} 条规则`
  }
  return JSON.stringify(d)
}

async function reloadAll() {
  loading.value = true
  try {
    const [s, p, r, l] = await Promise.all([
      getLearningFeedback(),
      getLearningSuggestions('pending'),
      getLearningSuggestions('confirmed'),
      getLearningLogs(50)
    ])
    stats.value = s
    suggestions.value = p
    resolvedSuggestions.value = [...r, ...(await getLearningSuggestions('rejected'))].sort(
      (a, b) => (b.resolved_at ?? '').localeCompare(a.resolved_at ?? '')
    )
    logs.value = l
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail ?? '加载学习反馈失败')
  } finally {
    loading.value = false
  }
}

async function triggerTuning() {
  tuning.value = true
  try {
    summary.value = await runTuningManually()
    ElMessage.success('学习诊断完成')
    await reloadAll()
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail ?? '诊断执行失败')
  } finally {
    tuning.value = false
  }
}

async function decide(row: SuggestionItem, action: 'confirm' | 'reject') {
  if (action === 'confirm') {
    try {
      await ElMessageBox.confirm(
        `确认停用规则「${row.rule_id}」？误报率 ${(row.false_rate * 100).toFixed(1)}%。停用后该规则不再参与检查。`,
        '确认停用',
        { confirmButtonText: '确认停用', cancelButtonText: '取消', type: 'warning' }
      )
    } catch {
      return
    }
  }
  try {
    const res = await decideSuggestion(row.id, action)
    ElMessage.success(
      action === 'confirm'
        ? `已停用规则「${res.disabled_rule?.rule_id ?? row.rule_id}」，后续审查不再执行它`
        : '已拒绝该建议'
    )
    await reloadAll()
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail ?? '操作失败')
  }
}

onMounted(reloadAll)
</script>

<style scoped>
.text-danger {
  color: #f56c6c;
  font-weight: 600;
}
</style>
