from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel

from backend.db.clickhouse import execute_query
from backend.services.cache import get_cached, set_cached
from backend.services.query_builder import (
    build_champion_stats_query,
    build_item_combos_query,
    build_available_patches_query,
)
from shared.logging import get_logger
from backend.services.patch import get_current_patch

logger = get_logger(__name__)

router = APIRouter(prefix="/api")


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class ChampionStats(BaseModel):
    character_id: str
    avg_placement: float
    top4_rate: float
    win_rate: float
    pick_count: int
    unique_matches: int


class ItemCombo(BaseModel):
    items: list[str]
    avg_placement: float
    top4_rate: float
    win_rate: float
    pick_count: int


class ChampionDetailResponse(BaseModel):
    character_id: str
    stats: ChampionStats
    top_item_combos: list[ItemCombo]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/patches", response_model=list[str])
def get_patches():
    """Returns all available patches in the database, most recent first."""
    cached = get_cached("patches", {})
    if cached is not None:
        return cached

    results = execute_query(build_available_patches_query())
    patches = [row["game_version"] for row in results]
    set_cached("patches", {}, patches)
    return patches


@router.get("/champions", response_model=list[ChampionStats])
def get_champion_stats(
    patch: str | None = Query(None, description="Game version e.g. 16.4. Defaults to current patch."),
    tiers: list[str] | None = Query(None, description="Filter by tiers e.g. CHALLENGER,GRANDMASTER"),
    min_lp: int | None = Query(None, description="Minimum LP — only applied when filtering Master+ tiers"),
):
    """
    Returns stats for all champions matching the given filters.
    Results are ordered by average placement ascending (best first).
    Patch defaults to the current patch if not specified.
    """
    effective_patch = patch or get_current_patch()
    params = {"patch": effective_patch, "tiers": tiers, "min_lp": min_lp}

    cached = get_cached("champions", params)
    if cached is not None:
        return cached

    query, query_params = build_champion_stats_query(effective_patch, tiers, min_lp)
    try:
        results = execute_query(query, query_params)
    except Exception as e:
        logger.error("champion stats query failed", error=str(e))
        raise HTTPException(status_code=500, detail="Query failed")

    set_cached("champions", params, results)
    return results


@router.get("/champions/{character_id}", response_model=ChampionDetailResponse)
def get_champion_detail(
    character_id: str,
    patch: str | None = Query(None),
    tiers: list[str] | None = Query(None),
    min_lp: int | None = Query(None),
    item_combos_limit: int = Query(10, ge=1, le=50),
):
    """
    Returns stats for a single champion plus their top item combinations.
    Patch defaults to the current patch if not specified.
    """
    effective_patch = patch or get_current_patch()
    params = {
        "character_id": character_id,
        "patch": effective_patch,
        "tiers": tiers,
        "min_lp": min_lp,
        "item_combos_limit": item_combos_limit,
    }
    cached = get_cached("champion_detail", params)
    if cached is not None:
        return cached

    # Fetch overall stats for this champion
    stats_query, stats_params = build_champion_stats_query(effective_patch, tiers, min_lp)
    stats_query = stats_query.replace(
        "GROUP BY character_id",
        f"AND character_id = '{character_id}'\n        GROUP BY character_id"
    )
    stats_results = execute_query(stats_query, stats_params)
    if not stats_results:
        raise HTTPException(status_code=404, detail=f"Champion {character_id} not found")

    # Fetch top item combos
    combos_query, combos_params = build_item_combos_query(
        character_id, effective_patch, tiers, min_lp, item_combos_limit
    )
    combos_results = execute_query(combos_query, combos_params)

    response = {
        "character_id": character_id,
        "stats": stats_results[0],
        "top_item_combos": combos_results,
    }
    set_cached("champion_detail", params, response)
    return response


@router.get("/items", response_model=list[ItemCombo])
def get_item_combos(
    champion: str = Query(..., description="Champion character_id e.g. TFT16_Jinx"),
    patch: str | None = Query(None),
    tiers: list[str] | None = Query(None),
    min_lp: int | None = Query(None),
    limit: int = Query(10, ge=1, le=50),
):
    """
    Returns the top item combinations for a given champion.
    Results are ordered by average placement ascending (best first).
    Patch defaults to the current patch if not specified.
    """
    effective_patch = patch or get_current_patch()
    params = {
        "champion": champion,
        "patch": effective_patch,
        "tiers": tiers,
        "min_lp": min_lp,
        "limit": limit,
    }
    cached = get_cached("items", params)
    if cached is not None:
        return cached

    query, query_params = build_item_combos_query(champion, effective_patch, tiers, min_lp, limit)
    try:
        results = execute_query(query, query_params)
    except Exception as e:
        logger.error("item combos query failed", error=str(e))
        raise HTTPException(status_code=500, detail="Query failed")

    set_cached("items", params, results)
    return results
