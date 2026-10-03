<template>
  <div>
    <el-row :gutter="16">
      <el-col :span="6" v-for="card in cards" :key="card.title">
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
        <el-timeline-item timestamp="W4 · 进行中" type="primary">
          MVP：条款内容核查 + 报告增强 + Word 批注下载 + 对话助手（L3）
        </el-timeline-item>
        <el-timeline-item timestamp="W5-W8 · 规划中">
          交叉比对、自定义模板、向量检索、自学习闭环、百份并发压测与开源发布
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
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { listDocuments } from '@/api/findings'
import { listGroups } from '@/api/documents'

const router = useRouter()
const docCount = ref<number | string>('—')
const groupCount = ref<number | string>('—')

const cards = ref([
  { title: '文档总数', value: docCount, note: '已上传到本环境', to: '/documents' },
  { title: '上传批次', value: groupCount, note: '批量受理记录', to: '/documents' },
  { title: '发现问题', value: '—', note: '在文档校验报告中查看', to: '/documents' },
  { title: '规则包', value: '1', note: '格式/错别字内置规则包', to: null }
])

onMounted(async () => {
  try {
    const [docs, groups] = await Promise.all([listDocuments(200), listGroups()])
    docCount.value = docs.length
    groupCount.value = groups.length
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
