<template>
  <div>
    <el-row :gutter="16">
      <el-col :span="4" v-for="card in cards" :key="card.title">
        <el-card shadow="hover" class="stat-card" @click="card.to && router.push(card.to)">
          <div class="card-title">{{ card.title }}</div>
          <div class="card-value">{{ card.value }}</div>
          <div class="card-note">{{ card.note }}</div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="16" style="margin-top: 16px">
      <el-col :span="8" v-for="step in steps" :key="step.title">
        <el-card shadow="hover" class="step-card">
          <div class="step-num">{{ step.num }}</div>
          <div class="step-title">{{ step.title }}</div>
          <div class="step-desc">{{ step.desc }}</div>
          <el-button link type="primary" @click="router.push(step.to)">前往{{ step.action }}</el-button>
        </el-card>
      </el-col>
    </el-row>

    <el-card style="margin-top: 16px">
      <template #header><b>使用提示</b></template>
      <el-alert
        title="AI 输出为辅助校对结果，不构成法律意见，正式文件请由专业人员复核。"
        type="warning"
        :closable="false"
      />
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { getDashboardStats } from '@/api/dashboard'

const router = useRouter()

const stats = ref({
  documents: '—' as number | string,
  groups: '—' as number | string,
  findings_total: '—' as number | string,
  findings_by_severity: { error: 0, warning: 0, info: 0 },
  rule_packs: '—' as number | string,
  chunks: '—' as number | string,
  embedded_docs: '—' as number | string
})

const cards = computed(() => [
  { title: '文档总数', value: stats.value.documents, note: '已上传到本环境', to: '/documents' },
  { title: '上传批次', value: stats.value.groups, note: '批量受理记录', to: '/documents' },
  { title: '发现问题', value: stats.value.findings_total, note: '在文档校验报告中查看', to: '/documents' },
  { title: '规则包', value: stats.value.rule_packs, note: '内置+自定义，可启停', to: '/rules' },
  { title: '已建立智能索引', value: stats.value.embedded_docs, note: '文档可参与智能搜索', to: '/search' },
  { title: '已智能拆解段落', value: stats.value.chunks, note: '供智能搜索定位原文', to: '/search' }
])

const steps = [
  { num: 1, title: '上传文档', desc: '支持 Word / PDF / 纯文本，一次最多 100 份，可自动识别文档类型。', action: '上传', to: '/documents' },
  { num: 2, title: '查看校验报告', desc: '格式、错别字、条款完整性、金额一致性检查，结果可按级别筛选并标记处理。', action: '查看', to: '/documents' },
  { num: 3, title: '深入核对', desc: '用文档助手提问、交叉比对多份文档、智能搜索相关条款，全程不消耗额外费用。', action: '使用', to: '/chat' }
]

onMounted(async () => {
  try {
    const s = await getDashboardStats()
    stats.value = s
  } catch {
    // 未登录或接口不可用时保持占位
  }
})
</script>

<style scoped>
.stat-card {
  cursor: pointer;
}
.step-card {
  height: 100%;
}
.step-num {
  width: 24px;
  height: 24px;
  line-height: 24px;
  text-align: center;
  border-radius: 50%;
  background: #409eff;
  color: #fff;
  font-weight: 700;
  font-size: 13px;
  margin-bottom: 8px;
}
.step-title {
  font-weight: 600;
  font-size: 15px;
  margin-bottom: 6px;
}
.step-desc {
  font-size: 13px;
  color: #606266;
  line-height: 1.6;
  margin-bottom: 8px;
}
.card-title {
  color: #909399;
  font-size: 13px;
}
.card-value {
  font-size: 26px;
  font-weight: 700;
  margin: 6px 0;
}
.card-note {
  font-size: 12px;
  color: #c0c4cc;
}
:deep(.el-timeline-item__node--primary) {
  background-color: #409eff;
}
</style>
