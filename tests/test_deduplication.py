import fakeredis
import pytest


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch):
    """Replace the real Redis client with fakeredis for all tests."""
    server = fakeredis.FakeServer()
    fake_client = fakeredis.FakeRedis(server=server, decode_responses=True, lua_modules=True)
    monkeypatch.setattr("crawler.services.deduplication.redis_client", fake_client)
    return fake_client


from crawler.services.deduplication import (
    is_match_fetched,
    mark_match_fetched,
    check_and_mark_match,
    preload_match_ids,
    get_fetched_match_count,
    is_puuid_crawled_this_cycle,
    mark_puuid_crawled,
    get_crawled_puuid_count,
)


# ---------------------------------------------------------------------------
# is_match_fetched / mark_match_fetched
# ---------------------------------------------------------------------------

class TestMatchFetched:

    def test_new_match_is_not_fetched(self):
        assert is_match_fetched("EUW1_123") is False

    def test_marked_match_is_fetched(self):
        mark_match_fetched("EUW1_123")
        assert is_match_fetched("EUW1_123") is True

    def test_different_match_ids_are_independent(self):
        mark_match_fetched("EUW1_123")
        assert is_match_fetched("EUW1_456") is False


# ---------------------------------------------------------------------------
# check_and_mark_match (atomic)
# ---------------------------------------------------------------------------

class TestCheckAndMarkMatch:

    def test_returns_true_for_new_match(self):
        assert check_and_mark_match("EUW1_123") is True

    def test_returns_false_for_already_claimed_match(self):
        check_and_mark_match("EUW1_123")
        assert check_and_mark_match("EUW1_123") is False

    def test_marks_match_as_fetched_after_claim(self):
        check_and_mark_match("EUW1_123")
        assert is_match_fetched("EUW1_123") is True

    def test_two_different_matches_both_claimed(self):
        assert check_and_mark_match("EUW1_111") is True
        assert check_and_mark_match("EUW1_222") is True

    def test_simulates_race_condition(self):
        result_1 = check_and_mark_match("EUW1_RACE")
        result_2 = check_and_mark_match("EUW1_RACE")
        assert result_1 is True
        assert result_2 is False


# ---------------------------------------------------------------------------
# preload_match_ids
# ---------------------------------------------------------------------------

class TestPreloadMatchIds:

    def test_preloads_multiple_ids(self):
        ids = ["EUW1_1", "EUW1_2", "EUW1_3"]
        preload_match_ids(ids)
        assert get_fetched_match_count() == 3

    def test_preloaded_ids_are_marked_as_fetched(self):
        preload_match_ids(["EUW1_999"])
        assert is_match_fetched("EUW1_999") is True

    def test_empty_list_does_not_crash(self):
        preload_match_ids([])
        assert get_fetched_match_count() == 0

    def test_duplicate_ids_counted_once(self):
        preload_match_ids(["EUW1_1", "EUW1_1", "EUW1_1"])
        assert get_fetched_match_count() == 1


# ---------------------------------------------------------------------------
# puuid cycle deduplication
# ---------------------------------------------------------------------------

class TestPuuidCycleDedup:

    def test_new_puuid_is_not_crawled(self):
        assert is_puuid_crawled_this_cycle("puuid_abc") is False

    def test_marked_puuid_is_crawled(self):
        mark_puuid_crawled("puuid_abc")
        assert is_puuid_crawled_this_cycle("puuid_abc") is True

    def test_different_puuids_are_independent(self):
        mark_puuid_crawled("puuid_abc")
        assert is_puuid_crawled_this_cycle("puuid_xyz") is False

    def test_count_increments_with_each_mark(self):
        mark_puuid_crawled("puuid_1")
        mark_puuid_crawled("puuid_2")
        mark_puuid_crawled("puuid_3")
        assert get_crawled_puuid_count() == 3

    def test_marking_same_puuid_twice_counts_once(self):
        mark_puuid_crawled("puuid_1")
        mark_puuid_crawled("puuid_1")
        assert get_crawled_puuid_count() == 1
