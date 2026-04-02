import json

import redis

from app.config import settings

_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            decode_responses=True,
        )
    return _client


def cache_get(key: str) -> dict | None:
    raw = get_redis().get(key)
    return json.loads(raw) if raw else None


def cache_set(key: str, value: dict, ttl: int = 300) -> None:
    get_redis().setex(key, ttl, json.dumps(value))


def cache_delete_pattern(pattern: str) -> None:
    r = get_redis()
    keys = r.keys(pattern)
    if keys:
        r.delete(*keys)
