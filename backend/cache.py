import hashlib
import json

import redis

from shared.config import settings
from shared.logging import get_logger

logger = get_logger(__name__)

redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)

CACHE_TTL_SECONDS = 3600  # 1 hour


def _make_cache_key(prefix: str, params: dict) -> str:
    """Creates a deterministic cache key from a prefix and filter params."""
    serialized = json.dumps(params, sort_keys=True)
    hashed = hashlib.md5(serialized.encode()).hexdigest()
    return f"cache:{prefix}:{hashed}"


def get_cached(prefix: str, params: dict) -> list | None:
    """Returns cached result or None if not found."""
    key = _make_cache_key(prefix, params)
    try:
        value = redis_client.get(key)
        if value:
            logger.info("cache hit", key=key)
            return json.loads(value)
    except Exception as e:
        logger.warning("cache get failed", error=str(e))
    return None


def set_cached(prefix: str, params: dict, data: list) -> None:
    """Stores result in Redis with TTL."""
    key = _make_cache_key(prefix, params)
    try:
        redis_client.set(key, json.dumps(data), ex=CACHE_TTL_SECONDS)
        logger.info("cache set", key=key, ttl=CACHE_TTL_SECONDS)
    except Exception as e:
        logger.warning("cache set failed", error=str(e))
