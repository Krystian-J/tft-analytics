import pytest

from backend.services.query_builder import (
    build_champion_stats_query,
    build_item_combos_query,
    build_available_patches_query,
    _tier_filter_clause,
    _lp_filter_clause,
    LP_ELIGIBLE_TIERS,
)


# ---------------------------------------------------------------------------
# _tier_filter_clause
# ---------------------------------------------------------------------------

class TestTierFilterClause:

    def test_returns_empty_when_no_tiers(self):
        assert _tier_filter_clause(None) == ""
        assert _tier_filter_clause([]) == ""

    def test_single_tier(self):
        result = _tier_filter_clause(["CHALLENGER"])
        assert "tier IN ('CHALLENGER')" in result

    def test_multiple_tiers(self):
        result = _tier_filter_clause(["CHALLENGER", "GRANDMASTER"])
        assert "CHALLENGER" in result
        assert "GRANDMASTER" in result
        assert "tier IN" in result

    def test_case_insensitive(self):
        result = _tier_filter_clause(["challenger", "grandmaster"])
        assert "CHALLENGER" in result
        assert "GRANDMASTER" in result

    def test_invalid_tier_ignored(self):
        result = _tier_filter_clause(["INVALID_TIER"])
        assert result == ""

    def test_mixed_valid_and_invalid(self):
        result = _tier_filter_clause(["CHALLENGER", "INVALID"])
        assert "CHALLENGER" in result
        assert "INVALID" not in result

    def test_all_tiers_included(self):
        tiers = ["IRON", "BRONZE", "SILVER", "GOLD", "PLATINUM",
                 "EMERALD", "DIAMOND", "MASTER", "GRANDMASTER", "CHALLENGER"]
        result = _tier_filter_clause(tiers)
        for tier in tiers:
            assert tier in result


# ---------------------------------------------------------------------------
# _lp_filter_clause
# ---------------------------------------------------------------------------

class TestLpFilterClause:

    def test_returns_empty_when_no_min_lp(self):
        assert _lp_filter_clause(None, ["CHALLENGER"]) == ""

    def test_returns_empty_when_no_tiers(self):
        assert _lp_filter_clause(200, None) == ""
        assert _lp_filter_clause(200, []) == ""

    def test_applied_for_master_only(self):
        result = _lp_filter_clause(200, ["MASTER"])
        assert "lp >= 200" in result

    def test_applied_for_grandmaster(self):
        result = _lp_filter_clause(300, ["GRANDMASTER"])
        assert "lp >= 300" in result

    def test_applied_for_challenger(self):
        result = _lp_filter_clause(500, ["CHALLENGER"])
        assert "lp >= 500" in result

    def test_applied_for_all_master_plus(self):
        result = _lp_filter_clause(200, ["MASTER", "GRANDMASTER", "CHALLENGER"])
        assert "lp >= 200" in result

    def test_not_applied_when_diamond_included(self):
        result = _lp_filter_clause(200, ["DIAMOND", "MASTER"])
        assert result == ""

    def test_not_applied_for_diamond_alone(self):
        result = _lp_filter_clause(200, ["DIAMOND"])
        assert result == ""

    def test_not_applied_for_low_tiers(self):
        for tier in ["IRON", "BRONZE", "SILVER", "GOLD", "PLATINUM", "EMERALD"]:
            result = _lp_filter_clause(200, [tier])
            assert result == "", f"LP filter should not apply to {tier}"

    def test_lp_value_zero(self):
        result = _lp_filter_clause(0, ["CHALLENGER"])
        assert "lp >= 0" in result


# ---------------------------------------------------------------------------
# build_champion_stats_query
# ---------------------------------------------------------------------------

class TestBuildChampionStatsQuery:

    def test_returns_tuple(self):
        query, params = build_champion_stats_query(None, None, None)
        assert isinstance(query, str)
        assert isinstance(params, dict)

    def test_contains_required_select_fields(self):
        query, _ = build_champion_stats_query(None, None, None)
        assert "character_id" in query
        assert "avg_placement" in query
        assert "top4_rate" in query
        assert "win_rate" in query
        assert "pick_count" in query

    def test_patch_added_to_params(self):
        _, params = build_champion_stats_query("16.4", None, None)
        assert params["patch"] == "16.4"

    def test_patch_filter_in_query(self):
        query, _ = build_champion_stats_query("16.4", None, None)
        assert "game_version" in query

    def test_no_patch_means_no_version_filter(self):
        query, params = build_champion_stats_query(None, None, None)
        assert "patch" not in params
        assert "game_version" not in query

    def test_tier_filter_included_when_tiers_given(self):
        query, _ = build_champion_stats_query(None, ["CHALLENGER"], None)
        assert "tier IN" in query

    def test_lp_filter_included_for_master_plus(self):
        query, _ = build_champion_stats_query(None, ["MASTER"], 200)
        assert "lp >=" in query

    def test_lp_filter_excluded_for_diamond(self):
        query, _ = build_champion_stats_query(None, ["DIAMOND"], 200)
        assert "lp >=" not in query

    def test_groups_by_character_id(self):
        query, _ = build_champion_stats_query(None, None, None)
        assert "GROUP BY character_id" in query

    def test_orders_by_avg_placement(self):
        query, _ = build_champion_stats_query(None, None, None)
        assert "ORDER BY avg_placement ASC" in query

    def test_having_clause_present(self):
        query, _ = build_champion_stats_query(None, None, None)
        assert "HAVING" in query


# ---------------------------------------------------------------------------
# build_item_combos_query
# ---------------------------------------------------------------------------

class TestBuildItemCombosQuery:

    def test_returns_tuple(self):
        query, params = build_item_combos_query("TFT16_Jinx", None, None, None)
        assert isinstance(query, str)
        assert isinstance(params, dict)

    def test_champion_in_params(self):
        _, params = build_item_combos_query("TFT16_Jinx", None, None, None)
        assert params["champion"] == "TFT16_Jinx"

    def test_filters_empty_item_slots(self):
        query, _ = build_item_combos_query("TFT16_Jinx", None, None, None)
        assert "item_1 != ''" in query or "item_1 !=" in query

    def test_patch_added_to_params(self):
        _, params = build_item_combos_query("TFT16_Jinx", "16.4", None, None)
        assert params["patch"] == "16.4"

    def test_limit_in_params(self):
        _, params = build_item_combos_query("TFT16_Jinx", None, None, None, limit=5)
        assert params["limit"] == 5

    def test_default_limit_is_10(self):
        _, params = build_item_combos_query("TFT16_Jinx", None, None, None)
        assert params["limit"] == 10

    def test_tier_filter_included(self):
        query, _ = build_item_combos_query("TFT16_Jinx", None, ["CHALLENGER"], None)
        assert "tier IN" in query

    def test_lp_filter_included_for_master_plus(self):
        query, _ = build_item_combos_query("TFT16_Jinx", None, ["MASTER"], 200)
        assert "lp >=" in query

    def test_items_sorted(self):
        query, _ = build_item_combos_query("TFT16_Jinx", None, None, None)
        assert "arraySort" in query

    def test_orders_by_avg_placement(self):
        query, _ = build_item_combos_query("TFT16_Jinx", None, None, None)
        assert "ORDER BY avg_placement ASC" in query


# ---------------------------------------------------------------------------
# build_available_patches_query
# ---------------------------------------------------------------------------

class TestBuildAvailablePatchesQuery:

    def test_returns_string(self):
        assert isinstance(build_available_patches_query(), str)

    def test_selects_game_version(self):
        assert "game_version" in build_available_patches_query()

    def test_orders_descending(self):
        assert "DESC" in build_available_patches_query()

    def test_queries_correct_table(self):
        assert "tft.unit_stats" in build_available_patches_query()
