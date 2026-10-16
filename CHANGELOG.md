# 更新日志（CHANGELOG）

本文件遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 格式。版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [1.0.0] - 2026-10-16

首次开源发布。项目从竞赛作品演进为完整的独立文档校验工具（W1-W8 全部完成 + P1/P2/P3 产品迭代 + UX 修复 + 零成本演示环境）。

### 新增（核心能力）

- 文档校验：格式、错别字、条款完整性、金额勾稽全自动审查，规则引擎 + LLM 双通道，全部产出可审计
- 报告体系：四段式报告工作台（总览 / 风险销项 / 条款明细 / 原文对照三色高亮）、docx 批注下载、意见书 PDF + Excel 明细 + 高管摘要导出（0 token）
- 文档助手：基于检索的对话问答，LLM 回答带原文引用（防幻觉）
- 交叉比对：多份文档字段级差异对比、版本 diff 红绿渲染、批量矩阵报告 CSV 导出
- 语义检索：本地 bge 嵌入 + pgvector + BM25 混合检索 + 重排，全部 0 token
- 规则管理：内置 4 个业务规则包，界面化配置（无需写 YAML），支持复制内置包为自定义
- 自学习闭环：反馈采集 → 诊断看板 → 自动调优 → golden 基准回归（F1）
- 工程设施：7 容器 Docker 编排、异步任务队列（parse/review/annotate/learn）、RBAC、审计、监控告警、数据保留自动清理、CI/CD

### 质量数据（实测）

- 后端测试 164 用例全绿，CI 双 job（后端 pytest + 前端 vue-tsc 构建）
- golden 基准集：40 份网络公开真实合同（CUAD / 政府采购 / 示范文本库），误报率 391 → 7
- 混合检索相关度 99%（golden 检索回归）
- 零成本演示：本地一键启动 / Cloudflare 免费隧道外网演示（`scripts-dev/demo_start.ps1`）

### 安全

- Nginx 安全响应头（CSP、nosniff）、上传 MIME 魔数校验、密钥不入库
