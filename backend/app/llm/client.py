"""OpenAI 兼容 LLM 客户端：重试、熔断、主备切换、限流、用量审计。

所有供应商标配 OpenAI 兼容协议（DashScope/DeepSeek/GLM/通义/硅基流动），
业务侧只面对 chat() 一个入口；密钥仅从 settings（.env / 环境变量）读取。
"""

import functools
import logging
import time
from dataclasses import dataclass

import pybreaker
from openai import (
    APIConnectionError,
    APITimeoutError,
    InternalServerError,
    OpenAI,
    RateLimitError,
)
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.llm import rate_limiter
from app.models.llm import LLMCallLog

log = logging.getLogger("llm")


class LLMNotConfiguredError(RuntimeError):
    """未配置任何可用 LLM 供应商。"""


class LLMCallError(RuntimeError):
    """所有供应商（含重试）均失败。"""


@dataclass(frozen=True)
class Provider:
    name: str
    base_url: str
    api_key: str
    model: str


@dataclass
class LLMResult:
    content: str
    model: str
    provider: str
    prompt_tokens: int
    completion_tokens: int
    finish_reason: str | None


# 仅对瞬时/限流/服务端错误重试；参数错误、鉴权错误立即抛出
_RETRYABLE = (RateLimitError, APIConnectionError, APITimeoutError, InternalServerError)


def _providers() -> list[Provider]:
    out: list[Provider] = []
    if settings.llm_base_url and settings.llm_api_key and settings.llm_model:
        out.append(Provider("primary", settings.llm_base_url,
                            settings.llm_api_key, settings.llm_model))
    if (settings.llm_fallback_base_url and settings.llm_fallback_api_key
            and settings.llm_fallback_model):
        out.append(Provider("fallback", settings.llm_fallback_base_url,
                            settings.llm_fallback_api_key, settings.llm_fallback_model))
    return out


@functools.lru_cache(maxsize=8)
def _sdk(name: str, base_url: str, api_key: str) -> OpenAI:
    return OpenAI(
        base_url=base_url, api_key=api_key,
        timeout=settings.llm_timeout_seconds, max_retries=0,
    )


@functools.lru_cache(maxsize=8)
def _breaker(name: str) -> pybreaker.CircuitBreaker:
    return pybreaker.CircuitBreaker(
        fail_max=settings.llm_circuit_fail_threshold,
        reset_timeout=settings.llm_circuit_recovery_seconds,
        name=name,
    )


def _call_once(provider: Provider, create_kwargs: dict):
    """单次调用：限流 → 熔断包裹的 SDK 请求；返回 (resp, latency_ms, error)。"""
    rate_limiter.acquire()
    t0 = time.perf_counter()
    try:
        client = _sdk(provider.name, provider.base_url, provider.api_key)
        resp = _breaker(provider.name).call(
            client.chat.completions.create,
            model=provider.model, **create_kwargs,
        )
        return resp, int((time.perf_counter() - t0) * 1000), None
    except Exception as exc:  # noqa: BLE001 - 统一转交给上层做切换/审计
        return None, int((time.perf_counter() - t0) * 1000), exc


def _call_with_retry(provider: Provider, create_kwargs: dict):
    """单供应商内手动重试（_call_once 以返回值形式给出错误，无法用 tenacity 捕获）。

    仅对 _RETRYABLE 类型重试，其余错误立即返回；退避 1,2,4... 上限 8s。
    """
    max_attempts = max(settings.llm_max_retries, 1)
    last = (None, 0, None)
    for attempt in range(1, max_attempts + 1):
        last = _call_once(provider, create_kwargs)
        error = last[2]
        if error is None or not isinstance(error, _RETRYABLE):
            return last
        if attempt < max_attempts:
            time.sleep(min(2 ** (attempt - 1), 8))
    return last


def _write_log(
    db: Session, *, user_id, scene: str, provider: Provider,
    latency_ms: int, success: bool, usage=None, error=None,
) -> None:
    prompt_tokens = completion_tokens = 0
    if usage is not None:
        prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
        completion_tokens = getattr(usage, "completion_tokens", 0) or 0
    db.add(LLMCallLog(
        user_id=user_id, scene=scene, provider=provider.name,
        model=provider.model,
        prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
        latency_ms=latency_ms, success=success,
        error_code=type(error).__name__ if error else None,
    ))
    db.commit()


def chat(
    messages: list[dict],
    *,
    scene: str,
    user_id=None,
    db: Session | None = None,
    temperature: float = 0.2,
    max_tokens: int | None = None,
    json_mode: bool = False,
) -> LLMResult:
    """发起一次聊天补全：依次尝试主/备供应商，成功或全部失败均写审计日志。"""
    providers = _providers()
    if not providers:
        raise LLMNotConfiguredError("未配置 LLM，请在 .env 中设置 LLM_BASE_URL/API_KEY/MODEL")

    create_kwargs: dict = {"messages": messages, "temperature": temperature}
    if max_tokens is not None:
        create_kwargs["max_tokens"] = max_tokens
    if json_mode:
        create_kwargs["response_format"] = {"type": "json_object"}

    own_session = db is None
    session = db or SessionLocal()
    last_error: Exception | None = None
    total_latency = 0
    try:
        for provider in providers:
            resp, latency, error = _call_with_retry(provider, create_kwargs)
            total_latency += latency
            if error is None:
                _write_log(
                    session, user_id=user_id, scene=scene, provider=provider,
                    latency_ms=latency, success=True, usage=getattr(resp, "usage", None),
                )
                choice = resp.choices[0]
                return LLMResult(
                    content=choice.message.content or "",
                    model=getattr(resp, "model", provider.model),
                    provider=provider.name,
                    prompt_tokens=getattr(resp.usage, "prompt_tokens", 0) or 0,
                    completion_tokens=getattr(resp.usage, "completion_tokens", 0) or 0,
                    finish_reason=getattr(choice, "finish_reason", None),
                )
            last_error = error
            log.warning("LLM 供应商 %s 失败: %s", provider.name, type(error).__name__)

        _write_log(
            session, user_id=user_id, scene=scene, provider=providers[-1],
            latency_ms=total_latency, success=False, error=last_error,
        )
        raise LLMCallError(
            f"LLM 调用失败（{len(providers)} 个供应商均不可用）：{type(last_error).__name__}"
        ) from last_error
    finally:
        if own_session:
            session.close()
