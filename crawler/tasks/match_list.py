from celery import shared_task

from shared.logging import get_logger
from crawler.services.riot_client import fetch_match_list as fetch_match_list_api, RateLimitError
from crawler.services.deduplication import check_and_mark_match
from crawler.services.rate_limiter import set_pause_for_retry
from crawler.db.postgres import upsert_player_crawl

logger = get_logger(__name__)


@shared_task(
    bind=True,
    name="crawler.tasks.match_list.fetch_match_list",
    queue="match_list",
    max_retries=5,
    default_retry_delay=60,
    acks_late=True,
)
def fetch_match_list(self, puuid: str) -> None:
    """
    Fetches the 20 most recent match IDs for a given puuid.
    For each new match ID, queues a fetch_match_detail task.

    If all 20 IDs are already known, the player is up to date — stop.
    """
    logger.info("fetching match list", puuid=puuid)

    try:
        from crawler.tasks.match_detail import fetch_match_detail

        match_ids: list[str] = fetch_match_list_api(puuid, count=20)

        if not match_ids:
            logger.info("empty match list returned", puuid=puuid)
            upsert_player_crawl(puuid, matches_found=0)
            return

        # Check each match ID — queue only new ones
        new_match_ids = []
        for match_id in match_ids:
            if check_and_mark_match(match_id):
                new_match_ids.append(match_id)

        # If all 20 are already known, player is fully up to date
        if not new_match_ids:
            logger.info("player fully up to date, no new matches", puuid=puuid)
            upsert_player_crawl(puuid, matches_found=0)
            return

        # Fan out — queue one match detail task per new match ID
        for match_id in new_match_ids:
            fetch_match_detail.apply_async(args=[match_id])

        upsert_player_crawl(puuid, matches_found=len(new_match_ids))

        logger.info(
            "match detail tasks queued",
            puuid=puuid,
            new_matches=len(new_match_ids),
            already_known=len(match_ids) - len(new_match_ids),
        )

    except RateLimitError as e:
        set_pause_for_retry(e.retry_after)
        raise self.retry(exc=e, countdown=e.retry_after)

    except Exception as e:
        logger.error("match list fetch failed", puuid=puuid, error=str(e))
        raise self.retry(exc=e)
