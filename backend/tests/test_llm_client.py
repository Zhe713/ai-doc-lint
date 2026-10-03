"""LLM 客户端底座测试：成功审计、重试、主备切换、全失败、熔断。"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from openai import APIConnectionError, RateLimitError

from app.core.config import settings
from app.llm import client as client_mod
from app.llm.client import (
    LLMCallError,
    LLMNotConfiguredError,
    chat,
)
from app.models.llm import LLMCallLog
from conftest import TestSessionLocal


@pytest.fixture(autouse=True)
def _pristine(pristine):
    """每个用例前清空数据，避免用量日志跨用例累积。"""
    pass


def _rate_error() -> RateLimitError:
    return RateLimitError(
        "rate limited",
        response=MagicMock(status_code=429, headers={}),
        body=None,
    )


def _conn_error() -> APIConnectionError:
    return APIConnectionError(request=MagicMock())


def _ok(content="核查结果", prompt=100, completion=20):
    return SimpleNamespace(
        choices=[SimpleNamespace(
            message=SimpleNamespace(content=content), finish_reason="stop")],
        usage=SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion),
        model="qwen-plus",
    )


def _patch_sdk(monkeypatch, outcomes_by_name: dict):
    captured: dict = {}

    def make_create(outcomes):
        seq = iter(outcomes)

        def create(model, **kwargs):
            captured.setdefault("calls", []).append(kwargs)
            outcome = next(seq)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        return create

    sdks = {
        name: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
            create=make_create(outcomes))))
        for name, outcomes in outcomes_by_name.items()
    }
    monkeypatch.setattr(client_mod, "_sdk",
                        lambda name, url, key: sdks[name])
    # 重试退避不在单测中真实等待
    monkeypatch.setattr(client_mod.time, "sleep", lambda seconds: None)
    return captured


def _configure(monkeypatch, *, primary=True, fallback=False,
               retries=3, threshold=5):
    monkeypatch.setattr(settings, "llm_base_url", "http://primary" if primary else "")
    monkeypatch.setattr(settings, "llm_api_key", "pk" if primary else "")
    monkeypatch.setattr(settings, "llm_model", "qwen-plus" if primary else "")
    monkeypatch.setattr(settings, "llm_fallback_base_url",
                        "http://fallback" if fallback else "")
    monkeypatch.setattr(settings, "llm_fallback_api_key", "fk" if fallback else "")
    monkeypatch.setattr(settings, "llm_fallback_model",
                        "qwen-turbo" if fallback else "")
    monkeypatch.setattr(settings, "llm_max_retries", retries)
    monkeypatch.setattr(settings, "llm_circuit_fail_threshold", threshold)
    # 每个测试用独立且缓存的熔断实例，避免跨用例计数、同用例内重复创建
    breakers: dict = {}
    monkeypatch.setattr(
        client_mod, "_breaker",
        lambda name: breakers.setdefault(
            name, client_mod.pybreaker.CircuitBreaker(
                fail_max=threshold, reset_timeout=30, name=name)),
    )


def _logs():
    db = TestSessionLocal()
    try:
        return db.query(LLMCallLog).all()
    finally:
        db.close()


def test_not_configured(monkeypatch):
    _configure(monkeypatch, primary=False)
    with pytest.raises(LLMNotConfiguredError):
        chat([{"role": "user", "content": "hi"}], scene="clause")


def test_success_writes_log(monkeypatch):
    _configure(monkeypatch)
    captured = _patch_sdk(monkeypatch, {"primary": [_ok(content="OK结果")]})
    db = TestSessionLocal()
    result = chat(
        [{"role": "user", "content": "检查"}], scene="clause",
        json_mode=True, db=db,
    )
    db.close()
    assert result.content == "OK结果"
    assert result.provider == "primary"
    assert result.prompt_tokens == 100
    assert captured["calls"][0]["response_format"] == {"type": "json_object"}

    logs = _logs()
    assert len(logs) == 1
    assert logs[0].success is True
    assert logs[0].total_tokens == 120
    assert logs[0].scene == "clause"
    assert logs[0].model == "qwen-plus"


def test_retry_then_success(monkeypatch):
    _configure(monkeypatch, retries=3)
    _patch_sdk(monkeypatch, {"primary": [_rate_error(), _conn_error(), _ok()]})
    db = TestSessionLocal()
    result = chat([{"role": "user", "content": "检查"}], scene="clause", db=db)
    db.close()
    assert result.content == "核查结果"
    assert len(_logs()) == 1  # 只写最终成功行


def test_fallback_after_primary_fails(monkeypatch):
    _configure(monkeypatch, fallback=True, retries=2)
    _patch_sdk(monkeypatch, {
        "primary": [_rate_error(), _rate_error()],
        "fallback": [_ok(content="备结果")],
    })
    db = TestSessionLocal()
    result = chat([{"role": "user", "content": "检查"}], scene="chat", db=db)
    db.close()
    assert result.provider == "fallback"
    assert result.content == "备结果"
    logs = _logs()
    assert len(logs) == 1
    assert logs[0].provider == "fallback"
    assert logs[0].success is True


def test_all_providers_fail(monkeypatch):
    _configure(monkeypatch, fallback=True, retries=1)
    _patch_sdk(monkeypatch, {
        "primary": [_rate_error()],
        "fallback": [_conn_error()],
    })
    db = TestSessionLocal()
    with pytest.raises(LLMCallError):
        chat([{"role": "user", "content": "检查"}], scene="clause", db=db)
    db.close()
    logs = _logs()
    assert len(logs) == 1
    assert logs[0].success is False
    assert logs[0].error_code in ("RateLimitError", "APIConnectionError")


def test_circuit_opens_after_threshold(monkeypatch):
    _configure(monkeypatch, retries=1, threshold=3)
    _patch_sdk(monkeypatch, {
        "primary": [_rate_error(), _rate_error(), _rate_error(), _ok()],
    })
    db = TestSessionLocal()
    for _ in range(3):
        with pytest.raises(LLMCallError):
            chat([{"role": "user", "content": "检查"}], scene="clause", db=db)

    # 熔断打开后第四次调用快速失败，不再真正请求 SDK（故第 4 个 _ok 不会被消费）
    breaker = client_mod._breaker("primary")
    from pybreaker import STATE_OPEN

    assert breaker.current_state == STATE_OPEN
    with pytest.raises(LLMCallError):
        chat([{"role": "user", "content": "检查"}], scene="clause", db=db)
    db.close()
    # 熔断打开后的第四次逻辑调用仍审计为失败行，共 4 行
    assert len(_logs()) == 4
