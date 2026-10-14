"""L1 规则层（报告页对话）：按钮 intent 与关键词/正则，毫秒级、0 token。

命中即返回 intent code；未命中返回 None，交 L2。
"""

import re

# intent codes
INTENT_LIST = "list_findings"
INTENT_EXPLAIN = "explain_finding"
INTENT_SUGGEST = "suggest_fix"
INTENT_LOCATE = "locate_finding"
INTENT_SUMMARY = "summarize"

# “第 N 条”指代：命中时优先按具体某条处理（P1-4 修复：避免被 list 意图吞掉）
_ORDINAL_PAT = re.compile(r"第\s*[一二三四五六七八九十百\d]+\s*[条个]")

# 顺序即优先级：更具体的意图放前面
_RULES: list[tuple[str, list[str]]] = [
    (INTENT_SUMMARY, [r"总结", r"概况", r"整体情况", r"总体"]),
    (INTENT_LOCATE, [r"原文", r"在哪里", r"什么位置", r"定位", r"哪一句"]),
    (INTENT_SUGGEST, [r"怎么改", r"如何修改", r"修改建议", r"怎么处理",
                       r"如何处理", r"怎么办"]),
    (INTENT_EXPLAIN, [r"什么意思", r"为什么", r"解释一下", r"解释"]),
    (INTENT_LIST, [r"列出", r"有哪些", r"全部", r"所有", r"几条",
                    r"多少.*问题", r"问题", r"错误", r"警告"]),
]

_COMPILED = [
    (intent, [re.compile(p) for p in patterns])
    for intent, patterns in _RULES
]


def l1_match(text: str, *, button_intent: str | None = None):
    """返回 (intent, confidence)；未命中返回 (None, 0.0)。"""
    if button_intent:
        return button_intent, 1.0
    text = (text or "").strip()
    if not text:
        return None, 0.0
    for intent, patterns in _COMPILED:
        if any(p.search(text) for p in patterns):
            # “第 N 条 … 有什么问题”等：用户明确指向某一条，走 explain 定位
            if intent == INTENT_LIST and _ORDINAL_PAT.search(text):
                return INTENT_EXPLAIN, 0.9
            return intent, 0.9
    return None, 0.0
