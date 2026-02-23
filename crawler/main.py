from celery import Celery

from shared.config import settings
from shared.logging import get_logger, setup_logging

# ---------------------------------------------------------------------------
# Setup logging before anything else
# ---------------------------------------------------------------------------

setup_logging()
logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Celery app
# ---------------------------------------------------------------------------

app = Celery("tft_crawler")
app.config_from_object("crawler.celeryconfig")

# ---------------------------------------------------------------------------
# Auto-discover tasks from all task modules
# ---------------------------------------------------------------------------

app.autodiscover_tasks([
    "crawler.tasks.league",
    "crawler.tasks.match_list",
    "crawler.tasks.match_detail",
    "crawler.tasks.save",
])

# ---------------------------------------------------------------------------
# Startup — pre-populate Redis deduplication set from PostgreSQL
# This ensures the crawler never re-fetches matches after a restart
# ---------------------------------------------------------------------------

@app.on_after_configure.connect
def on_startup(sender, **kwargs) -> None:
    """
    Runs once when the Celery worker starts up.
    Pre-populates the Redis fetched_match_ids set from PostgreSQL.
    """
    logger.info("crawler starting up, preloading match ids from postgres")

    try:
        from crawler.db.postgres import get_all_match_ids
        from crawler.services.deduplication import preload_match_ids

        match_ids = get_all_match_ids()
        preload_match_ids(match_ids)

        logger.info("startup complete", preloaded_match_ids=len(match_ids))
    except Exception as e:
        logger.error("startup preload failed", error=str(e))
        # Do not raise — crawler should still start even if preload fails
        # Deduplication will still work via PostgreSQL fallback in save task
