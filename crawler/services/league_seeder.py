from shared.config import settings
from shared.logging import get_logger
from shared.models.league import LeagueResponseModel
from crawler.services.riot_client import fetch_league, NotFoundError
from crawler.services.deduplication import (
    is_puuid_crawled_this_cycle,
    mark_puuid_crawled,
    get_crawled_puuid_count,
)
from crawler.db.postgres import save_league_entries

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Tier cascade order for season start fallback
# Starts from top tiers and works down until MIN_PLAYERS_THRESHOLD is met
# ---------------------------------------------------------------------------

TIER_CASCADE = [
    "challenger",
    "grandmaster",
    "master",
    "DIAMOND",
    "EMERALD",
    "PLATINUM",
    "GOLD"
]


# ---------------------------------------------------------------------------
# Main seeder
# ---------------------------------------------------------------------------

def collect_puuids_for_cycle() -> list[str]:
    """
    Collects puuids for the current crawl cycle using a cascading tier strategy.

    1. Starts with Challenger, Grandmaster, Master
    2. If total unique puuids < MIN_PLAYERS_THRESHOLD, continues down the ladder
    3. Always injects SEED_PUUIDS from config as additional fallback
    4. Skips puuids already crawled this cycle

    Returns a list of new puuids to queue for match list fetching.
    """
    collected_puuids: set[str] = set()

    # Always inject seed puuids first as baseline
    if settings.SEED_PUUIDS:
        for puuid in settings.SEED_PUUIDS:
            if puuid and not is_puuid_crawled_this_cycle(puuid):
                collected_puuids.add(puuid)
        logger.info("seed puuids injected", count=len(collected_puuids))

    # Cascade through tiers until threshold is met
    for tier in TIER_CASCADE:
        if len(collected_puuids) >= settings.MIN_PLAYERS_THRESHOLD:
            logger.info(
                "player threshold reached, stopping cascade",
                count=len(collected_puuids),
                threshold=settings.MIN_PLAYERS_THRESHOLD,
            )
            break

        try:
            new_puuids = _fetch_tier_puuids(tier)
            before = len(collected_puuids)
            collected_puuids.update(new_puuids)
            added = len(collected_puuids) - before

            logger.info(
                "tier fetched",
                tier=tier,
                new_puuids=added,
                total=len(collected_puuids),
            )

        except NotFoundError:
            logger.warning("tier endpoint not found, skipping", tier=tier)
            continue
        except Exception as e:
            logger.error("failed to fetch tier", tier=tier, error=str(e))
            continue

    # Mark all collected puuids as crawled this cycle
    for puuid in collected_puuids:
        mark_puuid_crawled(puuid)

    logger.info(
        "cycle seeding complete",
        total_puuids=len(collected_puuids),
        already_crawled_this_cycle=get_crawled_puuid_count() - len(collected_puuids),
    )

    return list(collected_puuids)


def _fetch_tier_puuids(tier: str) -> list[str]:
    """
    Fetches all puuids from a single tier league endpoint.
    Saves league entries to PostgreSQL and returns list of new puuids
    (excluding those already crawled this cycle).
    """
    raw_response = fetch_league(tier)

    # Top tiers return a single object with entries[]
    # Lower tiers (Diamond+) return a list of entries directly
    tier_upper = tier.upper()

    if tier_upper in ("CHALLENGER", "GRANDMASTER", "MASTER"):
        league_response = LeagueResponseModel(**raw_response)
        save_league_entries(league_response)
        all_puuids = [entry.puuid for entry in league_response.entries]
    else:
        # Entries endpoint returns a list — wrap it to reuse LeagueResponseModel
        entries = raw_response if isinstance(raw_response, list) else []
        all_puuids = [
            entry["puuid"]
            for entry in entries
            if "puuid" in entry
        ]
        # Save raw entries individually
        _save_lower_tier_entries(entries, tier_upper)

    # Filter out puuids already crawled this cycle
    new_puuids = [
        puuid for puuid in all_puuids
        if not is_puuid_crawled_this_cycle(puuid)
    ]

    return new_puuids


def _save_lower_tier_entries(entries: list[dict], tier: str) -> None:
    """
    Saves lower tier (Diamond and below) league entries to PostgreSQL.
    These come from a different endpoint format than top tiers.
    """
    from crawler.db.models import LeagueEntry
    from crawler.db.postgres import get_session

    rows = []
    for entry in entries:
        rows.append(LeagueEntry(
            puuid=entry.get("puuid", ""),
            tier=tier,
            rank=entry.get("rank", "I"),
            league_points=entry.get("leaguePoints", 0),
            wins=entry.get("wins", 0),
            losses=entry.get("losses", 0),
            veteran=entry.get("veteran", False),
            inactive=entry.get("inactive", False),
            fresh_blood=entry.get("freshBlood", False),
            hot_streak=entry.get("hotStreak", False),
            raw_response=entry,
        ))

    if rows:
        with get_session() as session:
            session.add_all(rows)
        logger.info("lower tier entries saved", tier=tier, count=len(rows))
