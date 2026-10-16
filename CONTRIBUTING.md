# 贡献指南（CONTRIBUTING）

首先感谢你考虑为 ai-doc-lint 贡献代码！无论是修 bug、加功能、写文档还是报 issue，都欢迎。

## 项目简介

ai-doc-lint 是一个自托管的 AI 文档校验工具：上传合同/文档，自动完成格式、错别字、条款完整性、金额勾稽等审查，输出可编辑的批注报告与意见书。技术栈：FastAPI + Vue3/TypeScript + PostgreSQL(pgvector) + Valkey + MinIO + Celery + Docker。

## 环境准备（开发环境）

前置依赖（本机已验证版本）：

- Docker Engine 28+ / Docker Compose v2（本项目开发、测试均在容器内进行，无需本机装 Python/Node）
- 可选：GitHub CLI（`gh`）

克隆并启动：

```bash
git clone https://github.com/<你的用户名>/ai-doc-lint.git
cd ai-doc-lint
cp .env.example .env        # 按需填入密钥；规则检查 0 token 可跑，LLM 功能需配 Key
docker compose up -d --build
```

前端入口 http://localhost:8080，首次访问需初始化管理员账号。

## 运行测试

```bash
powershell -ExecutionPolicy Bypass -File scripts-dev\run_tests.ps1
# 等价于在 api 容器内执行 pytest，当前基线 164 个用例
```

提交前请确保：**测试全绿 + 前端构建通过**。

```bash
cd frontend
npm run build     # 含 vue-tsc 类型检查
```

## 代码规范

- **提交信息一律使用中文**，格式建议：
  `改动：……` / `提升：……` / `优化：……` 三行，说明本次改了什么、提升了什么、优化了什么
- Python 代码遵循 PEP 8；前端遵循项目现有 Vue3 + TypeScript 风格
- 新增能力必须配套测试（后端 pytest 用例）与文档更新（README 相应小节）
- 禁止在代码/配置中硬编码密钥，一律走 `.env` 环境变量

## 提交流程

1. Fork 本仓库，新建分支：`git checkout -b fix/<简述>` 或 `feat/<简述>`
2. 完成修改并运行测试、构建，全绿后提交
3. 推送分支并创建 Pull Request，在 PR 描述中说明：改了什么、为什么改、测试结果

## Issue 规范

- Bug 类 issue：请使用模板，说明复现步骤、期望行为、实际行为、环境信息
- 功能建议：说明使用场景与期望效果

## 行为准则

参与本项目的所有讨论（issue / PR / 讨论区）请遵守 [CODE_OF_CONDUCT](CODE_OF_CONDUCT.md)。
