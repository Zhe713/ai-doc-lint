"""Valkey 令牌桶限流：所有 LLM 调用共享每分钟额度（LLM_RPM）。

令牌桶算法用 Lua 保证原子性；Valkey 故障时放行（fail-open），
避免缓存组件故障把整条业务流水线堵死。
"""

import time

import redis

from app.core.config import settings

_BUCKET_KEY = "llm:rpm"
_MAX_WAIT_SECONDS = 60.0

_LUA = """
local capacity = tonumber(ARGV[1])
local rate = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local requested = tonumber(ARGV[4])
local data = redis.call('HMGET', KEYS[1], 'tokens', 'ts')
local tokens = tonumber(data[1])
local ts = tonumber(data[2])
if tokens == nil then tokens = capacity end
if ts == nil then ts = now end
local delta = math.max(0, now - ts)
tokens = math.min(capacity, tokens + delta * rate)
local allowed = tokens >= requested
local wait_ms = 0
if allowed then
  tokens = tokens - requested
else
  wait_ms = math.ceil((requested - tokens) / rate * 1000)
end
redis.call('HMSET', KEYS[1], 'tokens', tokens, 'ts', now)
redis.call('EXPIRE', KEYS[1], 120)
return {allowed and 1 or 0, wait_ms}
"""

_client: redis.Redis | None = None


def _redis() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.Redis.from_url(
            settings.valkey_url, decode_responses=True, socket_timeout=3
        )
    return _client


class RateLimitTimeout(Exception):
    """等待令牌超过上限仍未获取额度。"""


def acquire(tokens: int = 1) -> None:
    """阻塞获取令牌；rpm<=0 表示不限流；缓存异常放行。"""
    if settings.llm_rpm <= 0:
        return
    rate_per_second = max(settings.llm_rpm / 60.0, 0.01)
    deadline = time.monotonic() + _MAX_WAIT_SECONDS
    try:
        script = _redis().register_script(_LUA)
        while True:
            allowed, wait_ms = script(
                keys=[_BUCKET_KEY],
                args=[settings.llm_rpm, rate_per_second, time.time(), tokens],
            )
            if allowed:
                return
            wait_s = min(int(wait_ms) / 1000.0 + 0.05, 5.0)
            if time.monotonic() + wait_s > deadline:
                raise RateLimitTimeout("等待 LLM 限流令牌超时")
            time.sleep(wait_s)
    except redis.RedisError:
        # Valkey 故障：放行，避免缓存故障堵死流水线
        return
