<template>
  <div>
    <el-card shadow="never" style="margin-bottom: 16px">
      <div class="search-bar">
        <el-input v-model="query" placeholder="输入你想查的内容，如：付款条款、违约责任、合同期限…"
          size="large" clearable @keyup.enter="onSearch" />
        <el-button type="primary" size="large" :loading="searching" @click="onSearch">
          语义检索
        </el-button>
      </div>
      <div style="margin-top: 8px; color: #909399; font-size: 12px">
        在已解析的文档中智能搜索相似条款或段落，无需消耗额外费用
      </div>
    </el-card>

    <template v-if="results.length">
      <el-card shadow="never" style="margin-bottom: 12px">
        <template #header>
          <b>检索结果（{{ results.length }}）</b>
        </template>
        <div v-for="(r, i) in results" :key="i" class="result-item">
          <div class="result-head">
            <el-tag size="small" type="info">{{ r.doc_type }}</el-tag>
            <span class="filename">{{ r.filename }}</span>
            <span class="dist">相似度 {{ (1 - r.distance).toFixed(3) }}</span>
            <el-button size="small" text type="primary" @click="goReport(r.document_id)">
              查看报告
            </el-button>
          </div>
          <div class="content" v-html="highlight(r.content)" />
        </div>
      </el-card>
    </template>
    <el-empty v-else-if="searched" description="未检索到相关条款" />

    <el-card v-if="similarDocs.length" shadow="never" style="margin-top: 16px">
      <template #header><b>相似文档</b></template>
      <div v-for="(d, i) in similarDocs" :key="i" class="similar-item">
        <el-tag size="small" type="info">{{ d.doc_type }}</el-tag>
        <span class="filename">{{ d.filename }}</span>
        <span class="dist">相似度 {{ (1 - d.distance).toFixed(3) }}</span>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'

import { type SearchResult, semanticSearch, similarDocuments } from '@/api/search'

const router = useRouter()
const query = ref('')
const results = ref<SearchResult[]>([])
const similarDocs = ref<Array<{ filename: string; doc_type: string; distance: number }>>([])
const searching = ref(false)
const searched = ref(false)

function highlight(text: string): string {
  const q = query.value.trim()
  if (!q) return text
  const escaped = q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  return text.replace(new RegExp(escaped, 'gi'), (m) => `<mark>${m}</mark>`)
}

async function onSearch() {
  if (!query.value.trim()) return
  searching.value = true
  try {
    const resp = await semanticSearch(query.value.trim())
    results.value = resp.results
    searched.value = true
    if (resp.results.length) {
      const sim = await similarDocuments(resp.results[0].document_id)
      similarDocs.value = sim.results
    } else {
      similarDocs.value = []
    }
  } finally {
    searching.value = false
  }
}

function goReport(docId: string) {
  router.push(`/reports/${docId}`)
}
</script>

<style scoped>
.search-bar {
  display: flex;
  gap: 12px;
}
.result-item {
  padding: 10px 0;
  border-bottom: 1px solid #f0f0f0;
}
.result-item:last-child {
  border-bottom: none;
}
.result-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
}
.filename {
  font-weight: 600;
  color: #303133;
}
.dist {
  color: #909399;
  font-size: 12px;
  margin-left: auto;
}
.content {
  color: #606266;
  font-size: 13px;
  line-height: 1.7;
  white-space: pre-wrap;
  background: #fafafa;
  border-radius: 6px;
  padding: 8px 12px;
}
.similar-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 0;
}
</style>
