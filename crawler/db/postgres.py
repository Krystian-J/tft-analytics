from contextlib import contextmanager
from datetime import datetime
from typing import Generator

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from shared.config import settings
from shared.logging import get_logger
from shared.models.league import LeagueEntryModel, LeagueResponseModel
from shared.models.match import MatchResponseModel

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Engine & Session
# ---------------------------------------------------------------------------

engine = create_engine(
    settings.POSTGRES_URL,
    pool_pre_ping=True,   # checks connection health before using it from pool
    pool_size=5,
    max_overflow=10,
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """
    Context manager that provides a SQLAlchemy session.
    Automatically commits on success and rolls back on error.

    Usage:
        with get_session() as session:
            session.add(some_model)
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error("database session error", error=str(e))
        raise
    finally:
        session.close()


# ---------------------------------------------------------------------------
# League entries
# ---------------------------------------------------------------------------

def save_league_entries(response: LeagueResponseModel) -> int:
    """
    Saves all player entries from a league response to league_entries table.
    Each call inserts new rows — historical data is preserved for trend analysis.

    Returns the number of entries saved.
    """
    # Import here to avoid circular imports with models
    from crawler.db.models import LeagueEntry

    rows = []
    for entry in response.entries:
        rows.append(LeagueEntry(
            puuid=entry.puuid,
            tier=response.tier,
            rank=entry.rank,
            league_points=entry.leaguePoints,
            wins=entry.wins,
            losses=entry.losses,
            veteran=entry.veteran,
            inactive=entry.inactive,
            fresh_blood=entry.freshBlood,
            hot_streak=entry.hotStreak,
            raw_response=entry.model_dump(),
        ))

    with get_session() as session:
        session.add_all(rows)

    logger.info(
        "league entries saved",
        tier=response.tier,
        count=len(rows),
    )
    return len(rows)


# ---------------------------------------------------------------------------
# Player crawls
# ---------------------------------------------------------------------------

def upsert_player_crawl(puuid: str, matches_found: int) -> None:
    """
    Updates or inserts a player crawl record.
    Tracks when each player was last crawled and how many new matches were found.
    """
    from crawler.db.models import PlayerCrawl

    with get_session() as session:
        existing = session.execute(
            select(PlayerCrawl).where(PlayerCrawl.puuid == puuid)
        ).scalar_one_or_none()

        if existing:
            existing.last_crawled_at = datetime.utcnow()
            existing.matches_found = matches_found
        else:
            session.add(PlayerCrawl(
                puuid=puuid,
                last_crawled_at=datetime.utcnow(),
                matches_found=matches_found,
            ))

    logger.info("player crawl updated", puuid=puuid, matches_found=matches_found)


# ---------------------------------------------------------------------------
# Matches
# ---------------------------------------------------------------------------

def save_match(response: MatchResponseModel, raw_json: dict) -> bool:
    """
    Saves a match to the matches table.
    Returns True if saved, False if match already exists (duplicate guard).
    """
    from crawler.db.models import Match

    match_id = response.metadata.match_id

    with get_session() as session:
        existing = session.execute(
            select(Match).where(Match.match_id == match_id)
        ).scalar_one_or_none()

        if existing:
            logger.info("match already exists, skipping", match_id=match_id)
            return False

        game_datetime = datetime.utcfromtimestamp(
            response.info.game_datetime / 1000
        )

        session.add(Match(
            match_id=match_id,
            game_datetime=game_datetime,
            game_length=response.info.game_length,
            game_version=response.info.game_version,
            tft_set_number=response.info.tft_set_number,
            queue_id=response.info.queue_id,
            raw_response=raw_json,
        ))

    logger.info("match saved", match_id=match_id)
    return True


# ---------------------------------------------------------------------------
# Rank lookup — used by save worker to denormalize LP into ClickHouse rows
# ---------------------------------------------------------------------------

def get_player_ranks(puuids: list[str]) -> dict[str, dict]:
    """
    Looks up the most recent league entry for each puuid.
    Returns a dict mapping puuid → {tier, rank, lp}.

    Used by the save worker to denormalize rank data into ClickHouse rows
    before inserting unit stats.
    """
    from crawler.db.models import LeagueEntry

    result = {}

    with get_session() as session:
        for puuid in puuids:
            entry = session.execute(
                select(LeagueEntry)
                .where(LeagueEntry.puuid == puuid)
                .order_by(LeagueEntry.fetched_at.desc())
                .limit(1)
            ).scalar_one_or_none()

            if entry:
                result[puuid] = {
                    "tier": entry.tier,
                    "rank": entry.rank or "",
                    "lp": entry.league_points,
                }

    return result


# ---------------------------------------------------------------------------
# Startup — pre-populate Redis dedup set from PostgreSQL
# ---------------------------------------------------------------------------

def get_all_match_ids() -> list[str]:
    """
    Returns all match IDs stored in PostgreSQL.
    Called on crawler startup to pre-populate the Redis fetched_match_ids set,
    ensuring deduplication survives restarts.
    """
    from crawler.db.models import Match

    with get_session() as session:
        rows = session.execute(select(Match.match_id)).scalars().all()

    logger.info("loaded match ids from postgres", count=len(rows))
    return list(rows)
