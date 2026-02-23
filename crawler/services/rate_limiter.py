import time
from datetime import datetime, timezone

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

PAUSE_UNTIL_KEY = "rate_limit:pause_until"

# ---------------------------------------------------------------------------
# Rate limit window in seconds — matches Riot's 2 minute window
# Used as TTL on the pause_until key so it never blocks after restart
# ---------------------------------------------------------------------------

RATE_LIMIT_WINDOW_SECONDS = 120


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def check_and_wait() -> None:
    """
    Checks if the shared pause_until flag is set in Redis.
    If set and still in the future, sleeps until the pause expires.

    Called by riot_client._make_request() before every API request.
    All workers share this signal through Redis — no direct coordination needed.
    """
    pause_until_str = redis_client.get(PAUSE_UNTIL_KEY)
    if not pause_until_str:
        return

    pause_until = float(pause_until_str)
    now = time.time()

    if now < pause_until:
        sleep_seconds = pause_until - now
        logger.info(
            "rate limit pause active, sleeping",
            sleep_seconds=round(sleep_seconds, 2),
        )
        time.sleep(sleep_seconds)


def update_rate_limit(headers: dict) -> None:
    """
    Parses rate limit headers from a Riot API response and sets
    the shared pause_until key in Redis if remaining calls are low.

    Called by riot_client._make_request() after every API response.

    Riot headers:
        X-App-Rate-Limit-Count: "8:10,45:600"  (calls made : window seconds)
        X-App-Rate-Limit: "20:10,100:600"       (max calls : window seconds)
    """
    try:
        count_header = headers.get("x-app-rate-limit-count", "")
        limit_header = headers.get("x-app-rate-limit", "")

        if not count_header or not limit_header:
            return

        # Parse both windows (short 10s and long 120s)
        # We care most about the 2-minute window
        counts = _parse_rate_limit_header(count_header)
        limits = _parse_rate_limit_header(limit_header)

        for window_seconds, calls_made in counts.items():
            max_calls = limits.get(window_seconds, 0)
            if max_calls == 0:
                continue

            remaining = max_calls - calls_made

            if remaining < settings.RATE_LIMIT_BUFFER:
                # Set pause until the window resets
                pause_until = time.time() + window_seconds
                redis_client.set(
                    PAUSE_UNTIL_KEY,
                    str(pause_until),
                    ex=window_seconds,  # TTL = window duration, auto-expires
                )
                logger.warning(
                    "rate limit buffer reached, pausing all workers",
                    remaining=remaining,
                    window_seconds=window_seconds,
                    pause_until=datetime.fromtimestamp(
                        pause_until, tz=timezone.utc
                    ).isoformat(),
                )
                break  # most conservative window takes priority

    except Exception as e:
        # Never let rate limit parsing crash the crawler
        logger.error("failed to parse rate limit headers", error=str(e))


def set_pause_for_retry(retry_after_seconds: int) -> None:
    """
    Sets pause_until based on a 429 Retry-After header value.
    Called by Celery tasks when they catch a RateLimitError.

    Args:
        retry_after_seconds: Value from Retry-After response header
    """
    pause_until = time.time() + retry_after_seconds
    redis_client.set(
        PAUSE_UNTIL_KEY,
        str(pause_until),
        ex=retry_after_seconds + 5,  # small buffer on TTL
    )
    logger.warning(
        "429 received, pausing all workers",
        retry_after_seconds=retry_after_seconds,
    )


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _parse_rate_limit_header(header: str) -> dict[int, int]:
    """
    Parses a Riot rate limit header into a dict of {window_seconds: count}.

    Example input: "8:10,45:600"
    Example output: {10: 8, 600: 45}
    """
    result = {}
    try:
        for part in header.split(","):
            count_str, window_str = part.strip().split(":")
            result[int(window_str)] = int(count_str)
    except Exception:
        pass
    return result
