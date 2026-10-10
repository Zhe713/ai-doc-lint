"""L3 Agent：LLM + function calling，漏斗最窄一层（目标流量 ≤10%）。

到这一层系统不猜意图：模型自主选择只读工具（get_findings /
search_in_document / get_document_text），取到证据后再组织回答。

不直接写库：以事件生成器形式返回 delta 与结束元信息，由 service 持久化。
"""

import json
import logging
import uuid

from openai import OpenAI

from app.chat import tools as chat_tools
from app.core.config import settings
from app.llm.client import LLMNotConfiguredError

log = logging.getLogger("chat.l3")


def _json_safe(v):
    """审计元数据写 JSONB 前递归把 UUID 等转成可 JSON 序列化类型。"""
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, dict):
        return {k: _json_safe(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_json_safe(x) for x in v]
    return v

SYSTEM_PROMPT = (
    "你是 ai-doc-lint 的文档校验助手。只能依据工具返回的内容回答，"
    "不得编造条款、数字或法律结论；回答简洁，先给结论再列依据。"
    "本工具为 AI 校对辅助，不构成法律意见。"
)

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "get_findings",
            "description": "查询当前文档的校验问题列表，可按严重度/状态过滤",
            "parameters": {
                "type": "object",
                "properties": {
                    "severity": {"type": "string",
                                 "enum": ["error", "warning", "info"]},
                    "status": {"type": "string",
                               "enum": ["open", "fixed", "ignored"]},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_in_document",
            "description": "在文档原文中检索关键词，返回上下文片段",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_document_text",
            "description": "读取文档原文的指定区间",
            "parameters": {
                "type": "object",
                "properties": {
                    "start": {"type": "integer"},
                    "length": {"type": "integer"},
                },
            },
        },
    },
]

TOOL_IMPL = {
    "get_findings": chat_tools.get_findings,
    "search_in_document": chat_tools.search_in_document,
    "get_document_text": chat_tools.get_document_text,
}


def build_client() -> tuple[OpenAI, str]:
    if not (settings.llm_base_url and settings.llm_api_key
            and settings.llm_model):
        raise LLMNotConfiguredError("LLM 未配置，无法进入 L3 对话")
    client = OpenAI(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        timeout=settings.llm_timeout_seconds,
        max_retries=1,
    )
    return client, settings.llm_model


def run_l3(db, document_id, history: list[dict], user_text: str):
    """生成器：yield ("delta", text)... 最后 ("end", meta)。"""
    client, model = build_client()
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history[-8:])
    messages.append({"role": "user", "content": user_text})

    first = client.chat.completions.create(
        model=model, messages=messages,
        tools=TOOLS_SCHEMA, tool_choice="auto",
        temperature=0.2,
    )
    msg = first.choices[0].message
    prompt_tokens = first.usage.prompt_tokens if first.usage else 0
    tool_audit: list[dict] = []

    if msg.tool_calls:
        messages.append(msg.model_dump(exclude_none=True))
        for call in msg.tool_calls:
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            args.setdefault("document_id", document_id)
            impl = TOOL_IMPL.get(call.function.name)
            if impl is None:
                content = json.dumps(
                    {"error": f"unknown tool {call.function.name}"},
                    ensure_ascii=False,
                )
            else:
                try:
                    result = impl(db, **args)
                except Exception as exc:  # noqa: BLE001
                    result = {"error": f"{type(exc).__name__}: {exc}"}
                content = json.dumps(result, ensure_ascii=False, default=str)
            tool_audit.append({"name": call.function.name,
                               "args": _json_safe(args)})
            messages.append({
                "role": "tool", "tool_call_id": call.id, "content": content,
            })

        stream = client.chat.completions.create(
            model=model, messages=messages, stream=True, temperature=0.3,
        )
        parts: list[str] = []
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta.content
            if delta:
                parts.append(delta)
                yield "delta", delta
        answer = "".join(parts)
    else:
        answer = msg.content or ""
        yield "delta", answer

    completion_tokens = first.usage.completion_tokens if first.usage else 0
    yield "end", {
        "tool_calls": tool_audit, "model": model,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens or max(1, len(answer) // 2),
    }
