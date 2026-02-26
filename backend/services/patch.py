from backend.db.clickhouse import execute_query
from backend.services.cache import get_cached, set_cached, PATCH_CACHE_TTL
from backend.services.query_builder import build_available_patches_query
from shared.logging import get_logger

logger = get_logger(__name__)


def get_current_patch() -> str | None:
    """
    Returns the most recent patch available in ClickHouse.
    Cached in Redis for 5 minutes so patch changes are picked up quickly
    without querying ClickHouse on every request.
    """
    cached = get_cached("current_patch", {})
    if cached is not None:
        return cached

    try:
        results = execute_query(build_available_patches_query())
        if results:
            patch = results[0]["game_version"]
            set_cached("current_patch", {}, patch, ttl=PATCH_CACHE_TTL)
            return patch
    except Exception as e:
        logger.warning("could not detect current patch", error=str(e))
    return None
