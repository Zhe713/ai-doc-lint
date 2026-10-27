# ai-doc-lint 面试演示脚本（从开机开始）

> 项目地址：https://github.com/Zhe713/ai-doc-lint
> 访问入口：http://localhost:8080
> 7 个容器名字都是自解释的，面试官一眼能看懂。

---

## 阶段 0：开机后 2 分钟准备

1. 开机后**先开 Docker Desktop**（任务栏鲸鱼图标变绿，约 30 秒）。
2. 准备好 1-2 份演示用合同 PDF/Word，放桌面提前打开文件夹。
3. 浏览器提前开好 GitHub 仓库页备用。

## 阶段 1：一条命令起服务

打开 PowerShell：

```powershell
cd D:\projects\ai-doc-lint
docker compose up -d --wait
```

等 7 个容器都 healthy（约 30-60 秒），另开一个窗口看状态：

```powershell
docker compose ps
```

**边等边说**：
> "这套服务一共 7 个容器，名字都是按'干什么'起的：web-frontend 是前端网页，backend-api 是 FastAPI 后端，celery-worker 是后台异步任务，celery-scheduler 是定时巡检，postgres-database 是带 pgvector 的 PostgreSQL，valkey-cache 是缓存和队列，minio-storage 是文件存储。一条 compose 命令全起来，一键复现。"

正常状态应该看到：

```
NAME                              STATUS
ai-doc-lint-postgres-database-1   Up (healthy)
ai-doc-lint-valkey-cache-1        Up (healthy)
ai-doc-lint-minio-storage-1       Up (healthy)
ai-doc-lint-backend-api-1         Up (healthy)
ai-doc-lint-celery-worker-1       Up
ai-doc-lint-celery-scheduler-1    Up
ai-doc-lint-web-frontend-1        Up
```

## 阶段 2：打开页面

浏览器访问 **http://localhost:8080**

- 看到登录/上传页 = 成功
- 白屏就等 10 秒刷新（前端首次加载慢）
- 可以顺手开个新标签访问 http://localhost:8080/health，展示 `{"status":"ok","checks":{"postgres":"ok","valkey":"ok","minio":"ok"}}`

## 阶段 3：主流程演示（核心 2 分钟）

### 3.1 上传合同
拖一份真实合同 PDF 到上传区。

话术：
> "支持 PDF / Word / Text 多格式。PDF 这条链路是三级降级的——pdfium 先抽文本，抽不动走 docling 结构化抽取，扫描件走 RapidOCR 兜底，解析失败走人工闸门不静默丢数据。"

### 3.2 看报告
等解析完成，展示报告页：格式问题、错别字、条款缺失、交叉比对不一致，每条都有严重级别和位置定位。

话术（被追问技术细节时）：
> "检索是 pgvector 向量 + BM25 双路召回，RRF 融合后接 bge-reranker 精排，Top-1 相关度实测 99%。"

### 3.3 批注下载
点"批注下载"，解释：
> "下载下来是 Word 批注格式，直接在 Word 里改、改完能覆盖重传。"

### 3.4 对话助手
在报告页随便问一句："这份合同的付款周期是多久？" 展示它从合同里检索答案。

话术：
> "意图识别是三层漏斗——L1 正则先拦（0 token），L2 槽位指代消解，L3 才调 function calling，大模型调用压到 10% 以内，核心校验本地跑 bge 模型，0 token。"

## 阶段 4：加分演示（时间够再上，30 秒一个点）

- **批次记录页**：展示历史批次列表，成功/失败/待处理有统计标签。
- **异常注入**：传一个损坏或非法文件，展示友好报错不崩。
- **可观测性**：被问稳定性时说："LLM 全量审计日志、Prometheus 指标、主备双供应商切换、pybreaker 熔断、令牌桶限流，163 条 pytest 用例 71% 覆盖率进 CI 门禁。"

## 阶段 5：收尾

- 不要现场停服务，保持页面开着让面试官自己点。
- 收尾话术：
> "工程上有 golden 回归集把误报从 391 压到 7，7 容器 Docker 一键部署，已经开源在 GitHub。"

---

## 保命提醒

1. **演示前一晚先完整跑一遍**：确认镜像已拉好（离线不挂）、8080 端口没被占、合同样本能正常出报告。
2. **准备兜底录屏**：万一台面 Docker 抽风，直接切视频，不现场修。
3. 常用排障命令：
   ```powershell
   docker compose ps              # 看状态
   docker compose logs backend-api # 看后端日志
   docker compose restart web-frontend  # 前端抽风就重启
   ```
