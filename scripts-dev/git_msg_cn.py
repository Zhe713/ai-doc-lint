# -*- coding: utf-8 -*-
"""git filter-branch --msg-filter 脚本：按英文主题行把提交消息改写为中文。
未命中映射的提交消息原样返回（不做任何改动）。"""
import sys

MAP = {
    "W1: project scaffold with auth and one-command Docker stack": "W1：工程骨架（鉴权 + 一键 Docker 部署栈）",
    "chore: ignore local verification screenshots": "chore：忽略本地验证截图",
    "test(day20): W4 acceptance - real-key docx E2E + 100-doc clause soak": "test(day20)：W4 验收 - 真实密钥 docx 端到端 + 100 份条款压测",
    "feat(day19): report chat assistant - 3-layer intent funnel over SSE": "feat(day19)：报告对话助手 - 三层意图漏斗 SSE",
    "feat(day18): annotate - native docx comments + checklist docx": "feat(day18)：批注 - 原生 docx 批注 + 检查清单 docx",
    "feat(day17): ClauseChecker - rule prescreen + batched LLM + quote anti-hallucination": "feat(day17)：条款检查器 - 规则预筛 + 批量 LLM + 引用防幻觉",
    "feat(day16): LLM client base - retry/circuit breaker/rate limit/usage logs": "feat(day16)：LLM 客户端基座 - 重试/熔断/限流/用量日志",
}


def main():
    msg = sys.stdin.read()
    first = msg.split("\n", 1)[0].strip()
    new_first = MAP.get(first)
    if new_first is not None:
        rest = msg.split("\n", 1)[1] if "\n" in msg else ""
        sys.stdout.write(new_first + rest)
    else:
        sys.stdout.write(msg)


if __name__ == "__main__":
    main()
