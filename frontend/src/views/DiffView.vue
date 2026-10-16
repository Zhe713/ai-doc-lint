<template>
  <div>
    <el-card shadow="never" style="margin-bottom: 16px">
      <template #header>
        <b>版本对比（Diff）</b>
        <el-tag v-if="result && result.identical" type="success" style="margin-left: 10px">
          无差异，可放行
        </el-tag>
        <el-tag v-else-if="result && !result.bypass_ready" type="danger" style="margin-left: 10px">
          存在 {{ result.stats.add_lines }} 处新增 / {{ result.stats.del_lines }} 处删除
        </el-tag>
      </template>
      <div class="pick-bar">
        <el-select v-model="docA" filterable placeholder="选择对比文档 A" style="width: 300px">
          <el-option v-for="d in docs" :key="d.id" :label="d.filename" :value="d.id" />
        </el-select>
        <span class="vs">vs</span>
        <el-select v-model="docB" filterable placeholder="选择对比文档 B" style="width: 300px">
          <el-option v-for="d in docs" :key="d.id" :label="d.filename" :value="d.id" />
        </el-select>
        <el-switch v-model="autoBypass" active-text="无差异自动放行" style="margin-left: 16px" />
        <el-button type="primary" :loading="loading" @click="runDiff">开始对比</el-button>
      </div>
    </el-card>

    <el-card v-if="result" shadow="never">
      <template #header>
        <b>差异明细</b>
        <span class="meta">
          相同 {{ result.stats.same_lines }} 行 · 新增 {{ result.stats.add_lines }} 行 ·
          删除 {{ result.stats.del_lines }} 行 · 变更比例 {{ (result.stats.changed_ratio * 100).toFixed(1) }}%
          <el-tag v-if="result.truncated" type="warning" size="small">文本过长已截断前 6 万字符</el-tag>
        </span>
      </template>
      <el-switch v-model="showAll" active-text="显示全部行" inactive-text="仅显示差异（含前后 2 行上下文）"
        style="margin-bottom: 10px" />
      <div class="diff-box">
        <div v-for="(row, i) in visibleRows" :key="i" :class="['diff-row', row.type]">
          <span class="ln-a">{{ row.line_a ?? '' }}</span>
          <span class="mark">{{ row.type === 'add' ? '+' : row.type === 'del' ? '-' : ' ' }}</span>
          <span class="txt">{{ row.text || ' ' }}</span>
        </div>
        <el-empty v-if="!visibleRows.length" description="无可见差异" :image-size="60" />
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import client from '@/api/client'
import { runDocumentDiff } from '@/api/diff'

interface DiffRow { type: string; text: string; line_a: number | null; line_b: number | null }
interface DiffResp {
  doc_a: { id: string; filename: string }
  doc_b: { id: string; filename: string }
  identical: boolean
  bypass_ready: boolean
  stats: { same_lines: number; add_lines: number; del_lines: number; changed_ratio: number }
  truncated: boolean
  rows: DiffRow[]
}

const docs = ref<Array<{ id: string; filename: string }>>([])
const docA = ref('')
const docB = ref('')
const autoBypass = ref(true)
const loading = ref(false)
const result = ref<DiffResp | null>(null)
const showAll = ref(false)

onMounted(async () => {
  const resp = await client.get('/documents')
  docs.value = resp.data ?? []
})

async function runDiff() {
  if (!docA.value || !docB.value) return
  if (docA.value === docB.value) {
    result.value = null
    return
  }
  loading.value = true
  try {
    result.value = await runDocumentDiff(docA.value, docB.value, autoBypass.value)
  } finally {
    loading.value = false
  }
}

const visibleRows = computed(() => {
  if (!result.value) return []
  const rows = result.value.rows
  if (showAll.value) return rows
  // 仅显示差异行，连续相同行折叠为一行摘要
  const out: DiffRow[] = []
  let pending = 0
  for (const row of rows) {
    if (row.type === 'equal') {
      pending += 1
      continue
    }
    if (pending > 0) {
      out.push({ type: 'equal', text: `… ${pending} 行相同 …`, line_a: null, line_b: null })
      pending = 0
    }
    out.push({ ...row })
  }
  return out
})
</script>

<style scoped>
.pick-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.vs {
  color: #909399;
  font-weight: 600;
}
.meta {
  color: #909399;
  font-size: 12px;
  margin-left: 12px;
}
.diff-box {
  font-family: 'Consolas', 'Microsoft YaHei', monospace;
  font-size: 13px;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  max-height: 620px;
  overflow: auto;
  background: #fafafa;
}
.diff-row {
  display: flex;
  gap: 8px;
  padding: 2px 10px;
  white-space: pre-wrap;
  word-break: break-all;
}
.diff-row .ln-a {
  color: #c0c4cc;
  width: 44px;
  text-align: right;
  flex-shrink: 0;
  user-select: none;
}
.diff-row .mark {
  width: 16px;
  flex-shrink: 0;
  font-weight: 700;
  user-select: none;
}
.diff-row.add {
  background: #f0f9eb;
  color: #529b2e;
}
.diff-row.del {
  background: #fef0f0;
  color: #c45656;
}
.diff-row.equal {
  color: #606266;
}
</style>
