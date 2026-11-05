# 贡献指南（CONTRIBUTING）

感谢你考虑为 ai-doc-lint 贡献！无论是修 bug、加功能、改进文档还是反馈问题，都欢迎。

## 项目是什么

ai-doc-lint 是一个**自托管**的 AI 文档校验工具：上传合同/文档，自动完成格式、错别字、条款完整性、金额勾稽等审查，输出可编辑的批注报告与意见书。

- 后端：FastAPI · SQLAlchemy 2 · Celery · PostgreSQL(pgvector) · Valkey · MinIO
- 前端：Vue 3 · TypeScript · Vite · Element Plus · Pinia
- 理念：**让 AI 做校对，行家做判断**。确定性检查 0 token，只有需要理解的才调大模型（BYOK）。

## 快速上手（开发环境）

所有开发、测试都在容器内进行，本机只需 Docker：

```bash
git clone https://github.com/Zhe713/ai-doc-lint.git
cd ai-doc-lint
cp .env.example .env          # 规则检查 0 token 可跑；LLM 功能需配 Key
docker compose up -d --build  # 首次约 5-10 分钟
```

前端入口 http://localhost:8080（首次访问初始化管理员）。

### 改后端后如何验证

容器内 `/app` 是镜像副本，不挂载工作区。改了 `backend/app/` 后需同步进容器：

```bash
MSYS_NO_PATHCONV=1 docker cp backend/app/. ai-doc-lint-backend-api-1:/app/app/
docker restart ai-doc-lint-backend-api-1 ai-doc-lint-celery-worker-1
```

### 改前端后如何验证

`web-frontend` 是 `COPY dist` 进镜像，**必须重建镜像**才生效：

```bash
cd frontend && npx vite build
cd .. && docker compose build web-frontend && docker compose up -d web-frontend
```

## 运行测试

```bash
# 后端全量测试（179 用例，含覆盖率门禁 ≥70%）
docker compose exec backend-api pytest

# 前端类型检查 + 构建
cd frontend && npm run build   # 含 vue-tsc 类型检查
```

提交前请确保：**后端测试全绿 + 前端构建通过**。

## 提交规范

- **提交信息用中文**，遵循 [Conventional Commits](https://www.conventionalcommits.org/zh-hans/) 风格：
  - `feat: 新功能`
  - `fix: 修复`
  - `docs: 文档`
  - `test: 测试`
  - `chore: 杂项`
- 一条提交只做一件事，便于回溯。
- 新增能力必须配套测试；涉及对外行为时同步更新 README / CHANGELOG。
- **禁止硬编码密钥**，一律走 `.env` 环境变量（`.env` 已在 `.gitignore`）。

## 提交流程

1. Fork 本仓库，新建分支：`git checkout -b feat/<简述>` 或 `fix/<简述>`
2. 完成修改，跑通测试与构建
3. 推送并创建 Pull Request，描述里说明：**改了什么、为什么、测试结果**

## 目录速览

```
backend/app/
  api/        # 接口层（FastAPI 路由）
  checkers/   # 四类校验器：format / typo / clause / cross
  chat/       # 三层意图漏斗：L1 规则 → L2 补槽 → L3 大模型
  services/   # 解析、检索、覆盖率、规则覆盖等
  tasks/      # Celery 异步任务与定时任务
  models/     # SQLAlchemy 模型
frontend/src/
  views/      # 页面（首页/文档/报告/比对/规则/助手/搜索/管理）
  api/        # 后端接口封装（类型契约）
  stores/     # Pinia 状态
```

## 行为准则

参与本项目所有讨论请遵守 [行为准则](CODE_OF_CONDUCT.md)。发现漏洞请走 [安全策略](SECURITY.md)，不要公开披露。
