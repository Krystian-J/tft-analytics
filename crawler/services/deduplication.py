import redis

from shared.config import settings
from shared.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Redis client
# ---------------------------------------------------------------------------

redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)

# ---------------------------------------------------------------------------
# Redis keys
# ---------------------------------------------------------------------------

FETCHED_MATCH_IDS_KEY = "dedup:fetched_match_ids"
CRAWLED_PUUIDS_CYCLE_KEY = "dedup:crawled_puuids_cycle"

# TTL for per-cycle puuid tracking — matches crawler cooldown
# After this expires, players can be re-crawled in the next cycle
CRAWLED_PUUIDS_TTL_SECONDS = settings.CRAWLER_COOLDOWN_MINUTES * 60


# ---------------------------------------------------------------------------
# Match ID deduplication
# ---------------------------------------------------------------------------

def is_match_fetched(match_id: str) -> bool:
    """
    Checks if a match ID has already been fetched.
    Uses Redis SISMEMBER — O(1) operation.
    """
    return bool(redis_client.sismember(FETCHED_MATCH_IDS_KEY, match_id))


def mark_match_fetched(match_id: str) -> None:
    """
    Marks a match ID as fetched in the Redis set.
    Called after a match is successfully saved to PostgreSQL and ClickHouse.
    """
    redis_client.sadd(FETCHED_MATCH_IDS_KEY, match_id)


def check_and_mark_match(match_id: str) -> bool:
    """
    Atomically checks if a match ID is new and marks it as fetched if so.
    Uses a Redis Lua script to ensure check + mark is a single atomic operation,
    preventing race conditions when multiple workers process overlapping match lists.

    Returns True if the match is new and was successfully claimed.
    Returns False if the match was already fetched by another worker.
    """
    # Lua script: atomically check + add to set
    # Returns 1 if added (new match), 0 if already existed
    lua_script = """
        if redis.call('SISMEMBER', KEYS[1], ARGV[1]) == 0 then
            redis.call('SADD', KEYS[1], ARGV[1])
            return 1
        else
            return 0
        end
    """
    result = redis_client.eval(lua_script, 1, FETCHED_MATCH_IDS_KEY, match_id)
    is_new = bool(result)

    if not is_new:
        logger.info("match already claimed, skipping", match_id=match_id)

    return is_new


def preload_match_ids(match_ids: list[str]) -> None:
    """
    Bulk loads match IDs into the Redis deduplication set.
    Called on crawler startup to pre-populate from PostgreSQL,
    ensuring deduplication survives restarts.

    Uses a pipeline for efficiency when loading large sets.
    """
    if not match_ids:
        return

    pipeline = redis_client.pipeline()
    for match_id in match_ids:
        pipeline.sadd(FETCHED_MATCH_IDS_KEY, match_id)
    pipeline.execute()

    logger.info("match ids preloaded into redis", count=len(match_ids))


def get_fetched_match_count() -> int:
    """Returns the total number of match IDs currently in the dedup set."""
    return redis_client.scard(FETCHED_MATCH_IDS_KEY)


# ---------------------------------------------------------------------------
# Per-cycle puuid deduplication
# ---------------------------------------------------------------------------

def is_puuid_crawled_this_cycle(puuid: str) -> bool:
    """
    Checks if a player has already been crawled in the current cycle.
    Prevents the same player from being queued multiple times when they
    appear in multiple tier responses (e.g. both Challenger and Grandmaster).
    """
    return bool(redis_client.sismember(CRAWLED_PUUIDS_CYCLE_KEY, puuid))


def mark_puuid_crawled(puuid: str) -> None:
    """
    Marks a puuid as crawled in the current cycle.
    The key has a TTL equal to CRAWLER_COOLDOWN_MINUTES so it auto-resets
    between cycles without any manual cleanup needed.
    """
    pipeline = redis_client.pipeline()
    pipeline.sadd(CRAWLED_PUUIDS_CYCLE_KEY, puuid)
    # Refresh TTL on every add — key expires after last addition + cooldown
    pipeline.expire(CRAWLED_PUUIDS_CYCLE_KEY, CRAWLED_PUUIDS_TTL_SECONDS)
    pipeline.execute()


def get_crawled_puuid_count() -> int:
    """Returns the number of puuids crawled in the current cycle."""
    return redis_client.scard(CRAWLED_PUUIDS_CYCLE_KEY)
