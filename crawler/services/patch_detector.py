import redis

from shared.config import settings
from shared.logging import get_logger
from crawler.db.clickhouse import drop_patch_partition, get_existing_patches
from crawler.services.match_parser import parse_game_version

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Redis client
# ---------------------------------------------------------------------------

redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)

# ---------------------------------------------------------------------------
# Redis keys
# ---------------------------------------------------------------------------

CURRENT_PATCH_KEY = "patch:current"


# ---------------------------------------------------------------------------
# Patch detection
# ---------------------------------------------------------------------------

def get_current_patch() -> str | None:
    """
    Returns the current patch version stored in Redis.
    Returns None if no patch has been recorded yet.
    """
    return redis_client.get(CURRENT_PATCH_KEY)


def set_current_patch(game_version: str) -> None:
    """
    Stores the current patch version in Redis.
    """
    redis_client.set(CURRENT_PATCH_KEY, game_version)


def detect_patch_change(raw_game_version: str) -> bool:
    """
    Checks if the given game version represents a new patch.
    Called by the save worker when processing each match.

    If a new patch is detected:
    - Drops old partitions from ClickHouse
    - Updates the current patch in Redis

    Returns True if a patch change was detected, False otherwise.
    """
    new_patch = parse_game_version(raw_game_version)
    current_patch = get_current_patch()

    if current_patch is None:
        # First time running — just record the current patch, no drop needed
        set_current_patch(new_patch)
        logger.info("initial patch recorded", patch=new_patch)
        return False

    if new_patch == current_patch:
        return False

    # Patch has changed
    logger.info(
        "patch change detected",
        old_patch=current_patch,
        new_patch=new_patch,
    )

    _handle_patch_change(old_patch=current_patch, new_patch=new_patch)
    return True


def _handle_patch_change(old_patch: str, new_patch: str) -> None:
    """
    Handles the transition to a new patch:
    1. Drops all existing ClickHouse partitions except the new patch
    2. Updates the current patch in Redis

    Drops all old partitions rather than just the previous one,
    in case the crawler was offline for multiple patches.
    """
    existing_patches = get_existing_patches()

    for patch in existing_patches:
        if patch != new_patch:
            try:
                drop_patch_partition(patch)
                logger.info("old patch partition dropped", patch=patch)
            except Exception as e:
                logger.error(
                    "failed to drop old patch partition",
                    patch=patch,
                    error=str(e),
                )

    set_current_patch(new_patch)
    logger.info("patch updated in redis", patch=new_patch)
