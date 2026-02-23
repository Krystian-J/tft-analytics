import clickhouse_connect
from clickhouse_connect.driver.client import Client

from shared.config import settings
from shared.logging import get_logger
from shared.models.unit import UnitRowModel

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

def get_client() -> Client:
    """
    Creates and returns a ClickHouse client connection.
    Called fresh for each operation — clickhouse-connect manages pooling internally.
    """
    return clickhouse_connect.get_client(
        host=settings.CLICKHOUSE_HOST,
        port=settings.CLICKHOUSE_PORT,
        database=settings.CLICKHOUSE_DB,
    )


# ---------------------------------------------------------------------------
# Unit stats insert
# ---------------------------------------------------------------------------

def insert_unit_rows(rows: list[UnitRowModel]) -> None:
    """
    Batch inserts a list of flat unit rows into ClickHouse tft.unit_stats table.
    All rows from a single match are inserted in one batch for efficiency.

    Args:
        rows: List of UnitRowModel instances produced by match_parser.explode_match_to_unit_rows()
    """
    if not rows:
        logger.warning("insert_unit_rows called with empty list, skipping")
        return

    # Column order must match CREATE TABLE definition in clickhouse_schema.sql
    column_names = [
        "match_id",
        "game_datetime",
        "game_version",
        "tft_set_number",
        "queue_id",
        "puuid",
        "placement",
        "level",
        "last_round",
        "gold_left",
        "players_eliminated",
        "total_damage_to_players",
        "tier",
        "rank",
        "lp",
        "character_id",
        "unit_name",
        "unit_tier",
        "unit_rarity",
        "item_1",
        "item_2",
        "item_3",
    ]

    # Convert Pydantic models to list of tuples for clickhouse-connect
    data = [
        [
            row.match_id,
            row.game_datetime,
            row.game_version,
            row.tft_set_number,
            row.queue_id,
            row.puuid,
            row.placement,
            row.level,
            row.last_round,
            row.gold_left,
            row.players_eliminated,
            row.total_damage_to_players,
            row.tier,
            row.rank,
            row.lp,
            row.character_id,
            row.unit_name,
            row.unit_tier,
            row.unit_rarity,
            row.item_1,
            row.item_2,
            row.item_3,
        ]
        for row in rows
    ]

    client = get_client()
    try:
        client.insert(
            table="unit_stats",
            data=data,
            column_names=column_names,
        )
        logger.info(
            "unit rows inserted into clickhouse",
            match_id=rows[0].match_id,
            row_count=len(rows),
        )
    except Exception as e:
        logger.error(
            "clickhouse insert failed",
            match_id=rows[0].match_id,
            error=str(e),
        )
        raise
    finally:
        client.close()


# ---------------------------------------------------------------------------
# Patch management
# ---------------------------------------------------------------------------

def drop_patch_partition(game_version: str) -> None:
    """
    Drops the ClickHouse partition for a given patch version.
    Called by patch_detector when a new patch is detected.

    Args:
        game_version: Patch string e.g. "16.3"
    """
    client = get_client()
    try:
        client.command(
            f"ALTER TABLE unit_stats DROP PARTITION '{game_version}'"
        )
        logger.info("partition dropped", game_version=game_version)
    except Exception as e:
        logger.error("partition drop failed", game_version=game_version, error=str(e))
        raise
    finally:
        client.close()


def get_existing_patches() -> list[str]:
    """
    Returns a list of all patch versions currently stored in ClickHouse.
    Used by patch_detector to determine which partitions exist.
    """
    client = get_client()
    try:
        result = client.query(
            "SELECT DISTINCT game_version FROM unit_stats ORDER BY game_version"
        )
        return [row[0] for row in result.result_rows]
    except Exception as e:
        logger.error("failed to fetch existing patches", error=str(e))
        return []
    finally:
        client.close()
