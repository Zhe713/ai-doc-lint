<template>
  <div>
    <el-row :gutter="16">
      <el-col :span="6" v-for="card in cards" :key="card.title">
        <el-card shadow="hover">
          <div class="card-title">{{ card.title }}</div>
          <div class="card-value">{{ card.value }}</div>
          <div class="card-note">{{ card.note }}</div>
        </el-card>
      </el-col>
    </el-row>

    <el-card style="margin-top: 16px">
      <template #header><b>建设路线（8 周公测版）</b></template>
      <el-timeline>
        <el-timeline-item timestamp="W1（当前）" type="success">
          工程骨架：账号体系、权限、健康检查、一键 Docker 部署
        </el-timeline-item>
        <el-timeline-item timestamp="W2">文档解析（docling/PaddleOCR）+ Celery 异步队列 + 解析失败人工闸门</el-timeline-item>
        <el-timeline-item timestamp="W3">格式规则引擎 + 错别字检查</el-timeline-item>
        <el-timeline-item timestamp="W4">MVP：条款内容核查 + 网页报告 + Word 批注下载</el-timeline-item>
        <el-timeline-item timestamp="W5-W8">交叉比对、自定义模板、向量检索、自学习闭环、百份并发压测与开源发布</el-timeline-item>
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
const cards = [
  { title: '待解析文档', value: '—', note: 'W2 接入' },
  { title: '校验任务', value: '—', note: 'W2 接入' },
  { title: '发现问题', value: '—', note: 'W3/W4 接入' },
  { title: '规则包', value: '1（规划）', note: '合同规则包为首个内置包' }
]
</script>

<style scoped>
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
</style>
