import httpx

from shared.config import settings
from shared.logging import get_logger
from crawler.services.rate_limiter import check_and_wait, update_rate_limit, set_pause_for_retry

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Base URLs per region
# ---------------------------------------------------------------------------

REGION_BASE_URLS = {
    "europe": "https://europe.api.riotgames.com",
    "americas": "https://americas.api.riotgames.com",
    "asia": "https://asia.api.riotgames.com",
    "sea": "https://sea.api.riotgames.com",
}

PLATFORM_BASE_URLS = {
    "europe": "https://euw1.api.riotgames.com",
    "americas": "https://na1.api.riotgames.com",
    "asia": "https://kr.api.riotgames.com",
    "sea": "https://sg2.api.riotgames.com",
}

# How long to pause all workers when a 403 is detected (seconds)
# Long enough to update the key and restart the crawler
INVALID_KEY_PAUSE_SECONDS = 3600


def _get_headers() -> dict:
    return {
        "X-Riot-Token": settings.RIOT_API_KEY,
        "Accept": "application/json",
    }


def _get_base_url(regional: bool = True) -> str:
    region = settings.RIOT_REGION.lower()
    if regional:
        return REGION_BASE_URLS.get(region, REGION_BASE_URLS["europe"])
    return PLATFORM_BASE_URLS.get(region, PLATFORM_BASE_URLS["europe"])


# ---------------------------------------------------------------------------
# Core request function
# ---------------------------------------------------------------------------

def _make_request(url: str) -> dict:
    """
    Makes a single GET request to the Riot API.

    - Checks pause_until before firing (rate limit coordination)
    - Parses rate limit headers from response and updates pause_until
    - Raises on 4xx/5xx except handles 429 by raising with retry delay info
    - Raises InvalidKeyError on 403 and pauses all workers for 1 hour

    Returns parsed JSON response as dict.
    """
    # Check shared rate limit pause before firing
    check_and_wait()

    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(url, headers=_get_headers())

        # Always update rate limit state from response headers
        update_rate_limit(response.headers)

        if response.status_code == 429:
            retry_after = int(response.headers.get("Retry-After", 60))
            logger.warning(
                "rate limit exceeded",
                url=url,
                retry_after=retry_after,
            )
            raise RateLimitError(retry_after=retry_after)

        if response.status_code == 403:
            logger.error(
                "riot api key invalid or expired — pausing all workers for 1 hour, "
                "update RIOT_API_KEY in .env and restart the crawler",
                url=url,
            )
            set_pause_for_retry(retry_after_seconds=INVALID_KEY_PAUSE_SECONDS)
            raise InvalidKeyError()

        if response.status_code == 404:
            raise NotFoundError(url=url)

        response.raise_for_status()
        return response.json()

    except httpx.TimeoutException:
        logger.error("request timed out", url=url)
        raise
    except httpx.HTTPError as e:
        logger.error("http error", url=url, error=str(e))
        raise


# ---------------------------------------------------------------------------
# Riot API endpoint wrappers
# ---------------------------------------------------------------------------

def fetch_league(tier: str) -> dict:
    """
    Fetches the full league for a given tier.
    e.g. tier = "challenger", "grandmaster", "master", "diamond"

    For challenger/grandmaster/master:
        GET /tft/league/v1/{tier}
    For diamond and below:
        GET /tft/league/v1/entries/RANKED_TFT/{tier}/I
    """
    base_url = _get_base_url(regional=False)
    tier_lower = tier.lower()

    if tier_lower in ("challenger", "grandmaster", "master"):
        url = f"{base_url}/tft/league/v1/{tier_lower}"
    else:
        url = f"{base_url}/tft/league/v1/entries/RANKED_TFT/{tier.upper()}/I"

    logger.info("fetching league", tier=tier)
    return _make_request(url)


def fetch_match_list(puuid: str, count: int = 20) -> list[str]:
    """
    Fetches the most recent match IDs for a given puuid.
    Returns a plain list of match ID strings.
    """
    base_url = _get_base_url(regional=True)
    url = f"{base_url}/tft/match/v1/matches/by-puuid/{puuid}/ids?count={count}"

    logger.info("fetching match list", puuid=puuid)
    return _make_request(url)


def fetch_match(match_id: str) -> dict:
    """
    Fetches full match data for a given match ID.
    Returns the raw match JSON dict.
    """
    base_url = _get_base_url(regional=True)
    url = f"{base_url}/tft/match/v1/matches/{match_id}"

    logger.info("fetching match", match_id=match_id)
    return _make_request(url)


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class RateLimitError(Exception):
    """Raised when Riot API returns 429. Contains retry_after seconds."""
    def __init__(self, retry_after: int = 60):
        self.retry_after = retry_after
        super().__init__(f"Rate limit exceeded, retry after {retry_after}s")


class NotFoundError(Exception):
    """Raised when Riot API returns 404."""
    def __init__(self, url: str):
        self.url = url
        super().__init__(f"Resource not found: {url}")


class InvalidKeyError(Exception):
    """Raised when Riot API returns 403 — key is expired or invalid.
    All workers are paused for INVALID_KEY_PAUSE_SECONDS automatically.
    To recover: update RIOT_API_KEY in .env and restart the crawler.
    """
    def __init__(self):
        super().__init__(
            "Riot API key invalid or expired. "
            "Update RIOT_API_KEY in .env and restart the crawler."
        )
