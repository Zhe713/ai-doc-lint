"""基于 Valkey 的登录失败限流（按 用户名+IP 维度）。"""

import redis

from app.core.config import settings

_redis_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis.from_url(
            settings.valkey_url, decode_responses=True, socket_timeout=3
        )
    return _redis_client


def _key(username: str, ip: str) -> str:
    return f"login_fail:{username.lower()}:{ip}"


def is_locked(username: str, ip: str) -> bool:
    try:
        count = int(get_redis().get(_key(username, ip)) or 0)
        return count >= settings.login_max_failures
    except redis.RedisError:
        # 限流组件故障时放行，避免缓存故障导致全员无法登录（失败仍写审计表）
        return False


def record_failure(username: str, ip: str) -> int:
    try:
        client = get_redis()
        key = _key(username, ip)
        pipe = client.pipeline()
        pipe.incr(key)
        pipe.expire(key, settings.login_lock_seconds)
        count, _ = pipe.execute()
        return int(count)
    except redis.RedisError:
        return 0


def clear_failures(username: str, ip: str) -> None:
    try:
        get_redis().delete(_key(username, ip))
    except redis.RedisError:
        pass
