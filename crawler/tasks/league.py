from celery import shared_task

from shared.logging import get_logger
from crawler.services.league_seeder import collect_puuids_for_cycle

logger = get_logger(__name__)


@shared_task(
    bind=True,
    name="crawler.tasks.league.fetch_league",
    queue="league",
    max_retries=3,
    default_retry_delay=60,
    acks_late=True,
)
def fetch_league(self) -> None:
    """
    Entry point for each crawl cycle.
    Collects puuids from top tier leagues using the cascading seeder strategy,
    then queues a fetch_match_list task for each new puuid.

    Triggered by Celery Beat when queue:match_list drains to empty.
    """
    logger.info("league fetch started")

    try:
        from crawler.tasks.match_list import fetch_match_list

        puuids = collect_puuids_for_cycle()

        if not puuids:
            logger.warning("no new puuids collected, cycle ending")
            return

        # Fan out — queue one match list task per puuid
        for puuid in puuids:
            fetch_match_list.apply_async(args=[puuid])

        logger.info("match list tasks queued", count=len(puuids))

    except Exception as e:
        logger.error("league fetch failed", error=str(e))
        raise self.retry(exc=e)
