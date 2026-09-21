# ai-doc-lint

> 开源自托管的 **AI 文档校验工具**：让 AI 做校对，行家做判断。
> 合同校验是第一个内置规则包，后续可通过规则包/模板扩展到招投标文件、规章制度、报告等场景。
>
> 数据全部留在部署方本地；大模型采用 BYOK（自带密钥，通过环境变量注入），项目本身不收集任何数据。

## 当前进度

- **W1（本版本）**：一键启动的工程骨架 —— PostgreSQL 18 + pgvector、Valkey 9、MinIO、FastAPI、Vue3 前端；
  首次启动初始化管理员、注册开关、用户名密码登录（JWT 双令牌）、两级 RBAC、登录失败限流、健康检查。
- W2 起：文档解析（docling/PaddleOCR）、Celery 异步队列、解析失败人工闸门、规则引擎与校验报告。

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
| MinIO Console | http://localhost:9001 | 本地对象存储控制台（调试用） |
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
├── backend/                # FastAPI + SQLAlchemy2 + Alembic + Celery(W2)
└── frontend/               # Vue3 + TS + Vite + Element Plus（Nginx 托管）
```

## 安全与免责

- `.env` 已在 `.gitignore` 中，密钥不入库、不写日志；后台只显示掩码并提供连通测试。
- 本工具输出为 AI 辅助校对结果，**不构成法律意见**，正式文件请由专业人员复核。

## License

[MIT](./LICENSE)
