from shared.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Tiers where LP filtering is meaningful
# ---------------------------------------------------------------------------

LP_ELIGIBLE_TIERS = {"MASTER", "GRANDMASTER", "CHALLENGER"}

ALL_TIERS = [
    "IRON", "BRONZE", "SILVER", "GOLD", "PLATINUM",
    "EMERALD", "DIAMOND", "MASTER", "GRANDMASTER", "CHALLENGER",
]


def _tier_filter_clause(tiers: list[str] | None) -> str:
    """
    Returns a SQL WHERE clause fragment for tier filtering.
    e.g. tiers=["CHALLENGER", "GRANDMASTER"] → tier IN ('CHALLENGER', 'GRANDMASTER')
    """
    if not tiers:
        return ""
    valid = [t.upper() for t in tiers if t.upper() in ALL_TIERS]
    if not valid:
        return ""
    tiers_str = ", ".join(f"'{t}'" for t in valid)
    return f"AND tier IN ({tiers_str})"


def _lp_filter_clause(min_lp: int | None, tiers: list[str] | None) -> str:
    """
    LP filter is only applied when filtering Master+ tiers exclusively.
    If any non-Master tier is selected, LP filter is ignored.
    """
    if min_lp is None:
        return ""
    if not tiers:
        return ""
    # Only apply LP filter if all selected tiers are LP-eligible
    selected = {t.upper() for t in tiers}
    if not selected.issubset(LP_ELIGIBLE_TIERS):
        return ""
    return f"AND lp >= {int(min_lp)}"


def build_champion_stats_query(
    patch: str | None,
    tiers: list[str] | None,
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

    tier_clause = _tier_filter_clause(tiers)
    lp_clause = _lp_filter_clause(min_lp, tiers)
    where = " AND ".join(conditions) + f" {tier_clause} {lp_clause}"

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
    tiers: list[str] | None,
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

    tier_clause = _tier_filter_clause(tiers)
    lp_clause = _lp_filter_clause(min_lp, tiers)
    where = " AND ".join(conditions) + f" {tier_clause} {lp_clause}"

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
