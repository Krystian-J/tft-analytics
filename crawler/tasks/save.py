from celery import shared_task
from pydantic import ValidationError

from shared.logging import get_logger
from shared.models.match import MatchResponseModel
from crawler.services.match_parser import explode_match_to_unit_rows
from crawler.services.patch_detector import detect_patch_change
from crawler.db.postgres import save_match as save_match_postgres, get_player_ranks
from crawler.db.clickhouse import insert_unit_rows

logger = get_logger(__name__)


@shared_task(
    bind=True,
    name="crawler.tasks.save.save_match",
    queue="save",
    max_retries=3,
    default_retry_delay=30,
    acks_late=True,
)
def save_match(self, raw_json: dict) -> None:
    """
    Validates, saves and explodes a raw match JSON response.

    Steps:
    1. Validate raw JSON with Pydantic
    2. Save raw JSON to PostgreSQL
    3. Detect patch change — drop old ClickHouse partitions if needed
    4. Look up player ranks from PostgreSQL for LP denormalization
    5. Explode match into flat unit rows
    6. Batch insert unit rows into ClickHouse
    """
    match_id = raw_json.get("metadata", {}).get("match_id", "unknown")
    logger.info("save task started", match_id=match_id)

    try:
        # Step 1 — Validate with Pydantic
        try:
            match = MatchResponseModel(**raw_json)
        except ValidationError as e:
            logger.error(
                "match validation failed, discarding",
                match_id=match_id,
                error=str(e),
            )
            return  # Do not retry — invalid data will always fail validation

        # Step 2 — Save raw JSON to PostgreSQL
        saved = save_match_postgres(match, raw_json)
        if not saved:
            # Match already exists in PostgreSQL — discard silently
            return

        # Step 3 — Detect patch change
        detect_patch_change(match.info.game_version)

        # Step 4 — Look up player ranks for LP denormalization
        puuids = [p.puuid for p in match.info.participants]
        player_ranks = get_player_ranks(puuids)

        # Step 5 — Explode match into flat unit rows
        unit_rows = explode_match_to_unit_rows(match, player_ranks)

        if not unit_rows:
            logger.warning("no unit rows produced", match_id=match_id)
            return

        # Step 6 — Batch insert into ClickHouse
        insert_unit_rows(unit_rows)

        logger.info(
            "match saved successfully",
            match_id=match_id,
            unit_rows=len(unit_rows),
            participants=len(match.info.participants),
        )

    except Exception as e:
        logger.error("save task failed", match_id=match_id, error=str(e))
        raise self.retry(exc=e)
