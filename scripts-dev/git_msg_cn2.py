# -*- coding: utf-8 -*-
"""git filter-branch --msg-filter 第二轮：把第一轮已改中文主题行、但正文仍为英文的
7 个提交，替换为完整中文消息（主题+正文）。未命中映射原样返回。"""
import sys

MAP = {
    "W1：工程骨架（鉴权 + 一键 Docker 部署栈）": (
        "W1：工程骨架（鉴权 + 一键 Docker 部署栈）\n\n"
        "- FastAPI + SQLAlchemy 2.0 + Alembic（PostgreSQL 18 + pgvector）\n"
        "- JWT access/refresh 令牌轮换 + 服务端吊销（Valkey）\n"
        "- 一次性管理员初始化、开放注册开关、admin/member 权限分级\n"
        "- bcrypt 密码哈希与登录失败锁定\n"
        "- MinIO 存储桶初始化与 /health 依赖检查\n"
        "- Vue 3 + TypeScript + Element Plus 单页应用，带静默 token 刷新\n"
        "- docker compose：db/cache/storage/api/nginx，健康检查门控启动\n"
        "- 13 个后端测试覆盖初始化/鉴权/权限/锁定/刷新流程"
    ),
    "test(day20)：W4 验收 - 真实密钥 docx 端到端 + 100 份条款压测": (
        "test(day20)：W4 验收 - 真实密钥 docx 端到端 + 100 份条款压测\n\n"
        "- 好合同 0 条款发现；坏合同 price(error)/breach(warning)\n"
        "- 100 份条款压测：73.3s、20 次 LLM 调用、4018 tokens\n"
        "- UI 截图：报告页 + 助手抽屉\n"
        "- 全套 59 个测试全绿"
    ),
    "feat(day19)：报告对话助手 - 三层意图漏斗 SSE": (
        "feat(day19)：报告对话助手 - 三层意图漏斗 SSE\n\n"
        "- chat_sessions/chat_messages 表（0005 迁移），消息记录 route_layer\n"
        "- L1 按钮/正则意图；L2 槽位/指代澄清；L3 函数调用\n"
        "- 只读工具：get_findings / search_in_document / get_document_text\n"
        "- SSE 流式输出 + LLM 审计 + intent_routes domain=chat\n"
        "- ReportsView 增加 AI 助手抽屉与快捷意图\n"
        "- 6 个新测试（共 59 全绿）"
    ),
    "feat(day18)：批注 - 原生 docx 批注 + 检查清单 docx": (
        "feat(day18)：批注 - 原生 docx 批注 + 检查清单 docx\n\n"
        "- docx：python-docx 1.2 add_comment 锚定匹配片段；未匹配则汇总\n"
        "- pdf/txt/md：生成问题清单 docx\n"
        "- POST /documents/{id}/annotate、GET /tasks/{id}/artifact 下载\n"
        "- annotate 队列路由、ReportsView 轮询下载按钮\n"
        "- 5 个新测试（共 53 全绿）"
    ),
    "feat(day17)：条款检查器 - 规则预筛 + 批量 LLM + 引用防幻觉": (
        "feat(day17)：条款检查器 - 规则预筛 + 批量 LLM + 引用防幻觉\n\n"
        "- clause_contract.yaml：8 个条款，强弱信号关键词\n"
        "- 直接缺失=0-token 发现；强信号命中=存在；仅弱信号=批量 LLM\n"
        "- 严格 JSON、一次内容重试、引用必须匹配原文否则降级\n"
        "- UI：条款复选框（默认关闭）、报告筛选/标签\n"
        "- 7 个新测试（共 48 全绿）"
    ),
    "feat(day16)：LLM 客户端基座 - 重试/熔断/限流/用量日志": (
        "feat(day16)：LLM 客户端基座 - 重试/熔断/限流/用量日志\n\n"
        "- openai 兼容客户端，主+备提供商（BYOK 经 .env 配置）\n"
        "- 可重试错误自动重试；pybreaker 每提供商熔断\n"
        "- Valkey token-bucket RPM 限流（缓存异常时熔断放行）\n"
        "- llm_call_logs 表 + 迁移 0004\n"
        "- 6 个新测试（共 41 全绿）；真实 DashScope qwen-plus 冒烟通过"
    ),
}


def main():
    msg = sys.stdin.read()
    first = msg.split("\n", 1)[0].strip()
    new_full = MAP.get(first)
    if new_full is not None:
        sys.stdout.write(new_full + "\n")
    else:
        sys.stdout.write(msg)


if __name__ == "__main__":
    main()
