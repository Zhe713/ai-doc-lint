# ai-doc-lint

> 开源自托管的 **AI 文档校验工具**：让 AI 做校对，行家做判断。
> 合同校验是第一个内置规则包，后续可通过规则包/模板扩展到招投标文件、规章制度、报告等场景。
>
> 数据全部留在部署方本地；大模型采用 BYOK（自带密钥，通过环境变量注入），项目本身不收集任何数据。

## 当前进度

- **W1**：一键启动的工程骨架 —— PostgreSQL 18 + pgvector、Valkey 9、MinIO、FastAPI、Vue3 前端；
  首次启动初始化管理员、注册开关、用户名密码登录（JWT 双令牌）、两级 RBAC、登录失败限流、健康检查。
- **W2（本版本）**：Celery 异步任务体系（parse/review/annotate/learn 四队列 + Beat 定时巡检）；
  批量上传受理（单批最多 100 份、在途配额、sha256 去重、.doc 老格式明确拒绝）；
  解析流水线（txt/md 直解、pdfium 零成本文本探测、docling 结构化抽取、扫描件 RapidOCR 兜底，
  docling 不可用时自动回退 pdfium，离线可用）；
  人工闸门三选一（OCR 重试 / 带警告继续 / 取消）；WebSocket + 轮询双通道实时进度；
  卡死任务巡检与断电/重启自动对账恢复。
- W3 起：格式规则、错别字检查、意图漏斗 L1/L2 流水线路由、校验报告。

## 快速开始（Docker Desktop / Linux 均可）

前置要求：安装 Docker Engine 28+ 与 Docker Compose v2（本机已验证 Docker 29.8 / Compose v5.5）。

```bash
# 1. 复制环境变量文件，并按需修改密钥/密码/大模型 Key
cp .env.example .env

# 2. 一键构建并启动（首次约 5-10 分钟，取决于网络）
docker compose up -d --build

# 3. 浏览器打开
#    http://localhost:8080
#    首次访问进入「初始化管理员」页面，仅可创建一次
```

服务与端口：

| 服务 | 地址 | 说明 |
| --- | --- | --- |
| 前端（Nginx） | http://localhost:8080 | 唯一入口，反向代理 `/api` |
| API 文档 | http://localhost:8080/docs | FastAPI 自动生成的接口文档 |
| API 健康检查 | http://localhost:8080/health | 依赖项连通性 |

## 常用命令

```bash
docker compose ps                 # 查看容器状态（应全部 healthy）
docker compose logs -f api        # 跟踪后端日志
docker compose exec api pytest    # 运行后端测试
docker compose down               # 停止（数据保留在命名卷中）
docker compose down -v            # 停止并删除全部数据（谨慎）
```

## 目录结构

```
ai-doc-lint/
├── docker-compose.yml      # 一键编排
├── .env.example            # 全部环境变量（密钥只走这里）
├── backend/                # FastAPI + SQLAlchemy2 + Alembic + Celery
├── frontend/               # Vue3 + TS + Vite + Element Plus（Nginx 托管）
└── scripts-dev/            # 本地开发/浸泡/恢复验证脚本（非分发内容）
```

## 安全与免责

- `.env` 已在 `.gitignore` 中，密钥不入库、不写日志；后台只显示掩码并提供连通测试。
- 本工具输出为 AI 辅助校对结果，**不构成法律意见**，正式文件请由专业人员复核。

## License

[MIT](./LICENSE)
