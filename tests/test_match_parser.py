import json
from pathlib import Path

import pytest

from shared.models.match import MatchResponseModel
from crawler.services.match_parser import (
    explode_match_to_unit_rows,
    parse_game_version,
    get_item_slots,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "match_response.json"


@pytest.fixture
def raw_match() -> dict:
    return json.loads(FIXTURE_PATH.read_text())


@pytest.fixture
def match(raw_match) -> MatchResponseModel:
    return MatchResponseModel(**raw_match)


@pytest.fixture
def player_ranks(match) -> dict:
    """Simulate rank lookups for all participants in the fixture match."""
    return {
        p.puuid: {"tier": "CHALLENGER", "rank": "", "lp": 1000}
        for p in match.info.participants
    }


# ---------------------------------------------------------------------------
# parse_game_version
# ---------------------------------------------------------------------------

class TestParseGameVersion:

    def test_extracts_major_minor(self):
        raw = "Linux Version 16.4.746.5697 (Feb 12 2026/17:29:09) [PUBLIC] <Releases/16.4>"
        assert parse_game_version(raw) == "16.4"

    def test_handles_different_patch(self):
        raw = "Linux Version 14.1.123.456 (Jan 01 2024/12:00:00) [PUBLIC] <Releases/14.1>"
        assert parse_game_version(raw) == "14.1"

    def test_handles_unparseable_version(self):
        # Should return the raw string rather than crashing
        result = parse_game_version("something unexpected")
        assert isinstance(result, str)
        assert len(result) > 0


# ---------------------------------------------------------------------------
# get_item_slots
# ---------------------------------------------------------------------------

class TestGetItemSlots:

    def test_three_items_unchanged(self):
        items = ["item_a", "item_b", "item_c"]
        assert get_item_slots(items) == ("item_a", "item_b", "item_c")

    def test_two_items_padded(self):
        items = ["item_a", "item_b"]
        assert get_item_slots(items) == ("item_a", "item_b", "")

    def test_one_item_padded(self):
        items = ["item_a"]
        assert get_item_slots(items) == ("item_a", "", "")

    def test_zero_items_padded(self):
        items = []
        assert get_item_slots(items) == ("", "", "")


# ---------------------------------------------------------------------------
# explode_match_to_unit_rows
# ---------------------------------------------------------------------------

class TestExplodeMatchToUnitRows:

    def test_returns_list_of_unit_rows(self, match, player_ranks):
        rows = explode_match_to_unit_rows(match, player_ranks)
        assert isinstance(rows, list)
        assert len(rows) > 0

    def test_all_rows_have_correct_match_id(self, match, player_ranks):
        rows = explode_match_to_unit_rows(match, player_ranks)
        for row in rows:
            assert row.match_id == "EUW1_7742482483"

    def test_all_rows_have_correct_patch(self, match, player_ranks):
        rows = explode_match_to_unit_rows(match, player_ranks)
        for row in rows:
            assert row.game_version == "16.4"

    def test_all_rows_have_correct_set_number(self, match, player_ranks):
        rows = explode_match_to_unit_rows(match, player_ranks)
        for row in rows:
            assert row.tft_set_number == 16

    def test_placement_values_are_valid(self, match, player_ranks):
        rows = explode_match_to_unit_rows(match, player_ranks)
        placements = {row.placement for row in rows}
        assert placements.issubset(set(range(1, 9)))

    def test_item_slots_always_have_three_values(self, match, player_ranks):
        rows = explode_match_to_unit_rows(match, player_ranks)
        for row in rows:
            # All three slots must exist — empty string, not None
            assert row.item_1 is not None
            assert row.item_2 is not None
            assert row.item_3 is not None

    def test_unit_with_three_items_populated_correctly(self, match, player_ranks):
        rows = explode_match_to_unit_rows(match, player_ranks)
        # TFT16_Renekton in fixture has 3 items
        renekton_rows = [r for r in rows if r.character_id == "TFT16_Renekton"]
        assert len(renekton_rows) == 1
        row = renekton_rows[0]
        assert row.item_1 == "TFT_Item_Bloodthirster"
        assert row.item_2 == "TFT9_Item_OrnnHullbreaker"
        assert row.item_3 == "TFT_Item_Quicksilver"

    def test_unit_with_no_items_has_empty_slots(self, match, player_ranks):
        rows = explode_match_to_unit_rows(match, player_ranks)
        # TFT16_Orianna in fixture has no items
        orianna_rows = [r for r in rows if r.character_id == "TFT16_Orianna"]
        assert len(orianna_rows) == 1
        row = orianna_rows[0]
        assert row.item_1 == ""
        assert row.item_2 == ""
        assert row.item_3 == ""

    def test_rank_data_denormalized_correctly(self, match, player_ranks):
        rows = explode_match_to_unit_rows(match, player_ranks)
        for row in rows:
            assert row.tier == "CHALLENGER"
            assert row.rank == ""
            assert row.lp == 1000

    def test_missing_rank_defaults_to_empty(self, match):
        # Pass empty player_ranks — should default gracefully
        rows = explode_match_to_unit_rows(match, {})
        for row in rows:
            assert row.tier == ""
            assert row.rank == ""
            assert row.lp == 0

    def test_first_place_participant_has_placement_1(self, match, player_ranks):
        rows = explode_match_to_unit_rows(match, player_ranks)
        # puuid of placement 1 player from fixture
        first_place_puuid = "ZP1wmaEbpfzau1nWbtG3Sl3kZckalRyZVHSJod1p0fznCM-Bh9H7eXF6cxQ0qy89OaxEVHBDZBMErA"
        first_place_rows = [r for r in rows if r.puuid == first_place_puuid]
        assert len(first_place_rows) > 0
        for row in first_place_rows:
            assert row.placement == 1

    def test_game_datetime_is_datetime_object(self, match, player_ranks):
        from datetime import datetime
        rows = explode_match_to_unit_rows(match, player_ranks)
        for row in rows:
            assert isinstance(row.game_datetime, datetime)
