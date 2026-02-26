from shared.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Tier ordering for >= filtering
# ---------------------------------------------------------------------------

TIER_ORDER = [
    "IRON", "BRONZE", "SILVER", "GOLD", "PLATINUM",
    "EMERALD", "DIAMOND", "MASTER", "GRANDMASTER", "CHALLENGER",
]


def _tier_filter_clause(min_tier: str | None) -> str:
    """
    Returns a SQL WHERE clause fragment for tier filtering.
    e.g. min_tier=DIAMOND → tier IN ('DIAMOND', 'MASTER', 'GRANDMASTER', 'CHALLENGER')
    """
    if not min_tier:
        return ""
    min_tier = min_tier.upper()
    if min_tier not in TIER_ORDER:
        return ""
    valid_tiers = TIER_ORDER[TIER_ORDER.index(min_tier):]
    tiers_str = ", ".join(f"'{t}'" for t in valid_tiers)
    return f"AND tier IN ({tiers_str})"


def build_champion_stats_query(
    patch: str | None,
    min_tier: str | None,
    min_lp: int | None,
) -> tuple[str, dict]:
    """
    Builds a ClickHouse query that returns per-champion stats.

    Returns (query_string, params_dict).
    """
    conditions = ["1=1"]
    params = {}

    if patch:
        conditions.append("game_version = {patch:String}")
        params["patch"] = patch
    if min_lp is not None:
        conditions.append("lp >= {min_lp:UInt16}")
        params["min_lp"] = min_lp

    tier_clause = _tier_filter_clause(min_tier)
    where = " AND ".join(conditions) + f" {tier_clause}"

    query = f"""
        SELECT
            character_id,
            round(avg(placement), 2)                                        AS avg_placement,
            round(countIf(placement <= 4) / count() * 100, 1)              AS top4_rate,
            round(countIf(placement = 1) / count() * 100, 1)               AS win_rate,
            count()                                                          AS pick_count,
            count(DISTINCT match_id)                                         AS unique_matches
        FROM tft.unit_stats
        WHERE {where}
        GROUP BY character_id
        HAVING pick_count >= 10
        ORDER BY avg_placement ASC
    """
    return query, params


def build_item_combos_query(
    champion: str,
    patch: str | None,
    min_tier: str | None,
    min_lp: int | None,
    limit: int = 10,
) -> tuple[str, dict]:
    """
    Builds a ClickHouse query that returns top item combinations for a champion.

    Returns (query_string, params_dict).
    """
    conditions = ["character_id = {champion:String}"]
    params = {"champion": champion}

    if patch:
        conditions.append("game_version = {patch:String}")
        params["patch"] = patch
    if min_lp is not None:
        conditions.append("lp >= {min_lp:UInt16}")
        params["min_lp"] = min_lp

    tier_clause = _tier_filter_clause(min_tier)
    where = " AND ".join(conditions) + f" {tier_clause}"

    query = f"""
        SELECT
            arraySort([item_1, item_2, item_3])                             AS items,
            round(avg(placement), 2)                                        AS avg_placement,
            round(countIf(placement <= 4) / count() * 100, 1)              AS top4_rate,
            round(countIf(placement = 1) / count() * 100, 1)               AS win_rate,
            count()                                                          AS pick_count
        FROM tft.unit_stats
        WHERE {where}
            AND (item_1 != '' OR item_2 != '' OR item_3 != '')
        GROUP BY items
        HAVING pick_count >= 5
        ORDER BY avg_placement ASC
        LIMIT {{limit:UInt16}}
    """
    params["limit"] = limit
    return query, params


def build_available_patches_query() -> str:
    """Returns query to fetch all available patches ordered by most recent first."""
    return """
        SELECT DISTINCT game_version
        FROM tft.unit_stats
        ORDER BY game_version DESC
    """
