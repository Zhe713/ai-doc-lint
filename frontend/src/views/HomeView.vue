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

    <el-card style="margin-top: 16px">
      <template #header><b>建设路线（8 周公测版）</b></template>
      <el-timeline>
        <el-timeline-item timestamp="W1 · 已完成" type="success">
          工程骨架：账号体系、权限、健康检查、一键 Docker 部署
        </el-timeline-item>
        <el-timeline-item timestamp="W2 · 已完成" type="success">
          文档解析（docling/RapidOCR）+ Celery 异步队列 + 解析失败人工闸门
        </el-timeline-item>
        <el-timeline-item timestamp="W3 · 已完成" type="success">
          格式规则引擎 + 错别字检查 + 意图漏斗 L1/L2 + 网页校验报告
        </el-timeline-item>
        <el-timeline-item timestamp="W4 · 已完成" type="success">
          MVP：条款内容核查 + 报告增强 + Word 批注下载 + 对话助手（L3）
        </el-timeline-item>
        <el-timeline-item timestamp="W5 · 已完成" type="success">
          交叉比对：字段抽取 + 文档内勾稽 + 跨文档比对矩阵（真实合同验收 515 份）
        </el-timeline-item>
        <el-timeline-item timestamp="W6 · 已完成" type="success">
          规则包自定义（内置格式/条款/字段/勾稽包 + 上传/启停管理）+ bge 本地语义检索（0 token，pgvector Top-K + 相似文档）
        </el-timeline-item>
        <el-timeline-item timestamp="W7-W8 · 规划中">
          自学习闭环、百份并发压测与开源发布
        </el-timeline-item>
      </el-timeline>
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
  { title: '已向量化', value: stats.value.embedded_docs, note: '文档已生成语义向量', to: '/search' },
  { title: '语义分块', value: stats.value.chunks, note: '可参与语义检索', to: '/search' }
])

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
