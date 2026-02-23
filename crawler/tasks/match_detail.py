from celery import shared_task

from shared.logging import get_logger
from crawler.services.riot_client import fetch_match as fetch_match_api, RateLimitError, NotFoundError
from crawler.services.rate_limiter import set_pause_for_retry

logger = get_logger(__name__)


@shared_task(
    bind=True,
    name="crawler.tasks.match_detail.fetch_match_detail",
    queue="match_detail",
    max_retries=5,
    default_retry_delay=60,
    acks_late=True,
)
def fetch_match_detail(self, match_id: str) -> None:
    """
    Fetches full match data for a given match ID from Riot API.
    On success, queues a save_match task with the raw JSON response.
    """
    logger.info("fetching match detail", match_id=match_id)

    try:
        from crawler.tasks.save import save_match

        raw_json = fetch_match_api(match_id)

        # Queue save task with raw JSON
        save_match.apply_async(args=[raw_json])

        logger.info("match detail fetched, save task queued", match_id=match_id)

    except RateLimitError as e:
        set_pause_for_retry(e.retry_after)
        raise self.retry(exc=e, countdown=e.retry_after)

    except NotFoundError:
        # Match not found — log and discard, no retry needed
        logger.warning("match not found, discarding", match_id=match_id)
        return

    except Exception as e:
        logger.error("match detail fetch failed", match_id=match_id, error=str(e))
        raise self.retry(exc=e)
