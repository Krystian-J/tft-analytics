import hashlib
import json

import redis

from shared.config import settings
from shared.logging import get_logger

logger = get_logger(__name__)

redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)

DEFAULT_CACHE_TTL = 3600   # 1 hour for query results
PATCH_CACHE_TTL   = 300    # 5 minutes for current patch detection


def _make_cache_key(prefix: str, params: dict) -> str:
    serialized = json.dumps(params, sort_keys=True)
    hashed = hashlib.md5(serialized.encode()).hexdigest()
    return f"cache:{prefix}:{hashed}"


def get_cached(prefix: str, params: dict) -> list | str | None:
    key = _make_cache_key(prefix, params)
    try:
        value = redis_client.get(key)
        if value:
            logger.info("cache hit", key=key)
            return json.loads(value)
    except Exception as e:
        logger.warning("cache get failed", error=str(e))
    return None


def set_cached(prefix: str, params: dict, data: list | str, ttl: int = DEFAULT_CACHE_TTL) -> None:
    key = _make_cache_key(prefix, params)
    try:
        redis_client.set(key, json.dumps(data), ex=ttl)
        logger.info("cache set", key=key, ttl=ttl)
    except Exception as e:
        logger.warning("cache set failed", error=str(e))
