import time
from unittest.mock import patch

import fakeredis
import pytest

# Patch the redis client before importing the module
@pytest.fixture(autouse=True)
def fake_redis(monkeypatch):
    """Replace the real Redis client with fakeredis for all tests."""
    server = fakeredis.FakeServer()
    fake_client = fakeredis.FakeRedis(server=server, decode_responses=True)
    monkeypatch.setattr("crawler.services.rate_limiter.redis_client", fake_client)
    return fake_client


from crawler.services.rate_limiter import (
    check_and_wait,
    update_rate_limit,
    set_pause_for_retry,
    _parse_rate_limit_header,
    PAUSE_UNTIL_KEY,
)


# ---------------------------------------------------------------------------
# _parse_rate_limit_header
# ---------------------------------------------------------------------------

class TestParseRateLimitHeader:

    def test_parses_single_window(self):
        result = _parse_rate_limit_header("8:10")
        assert result == {10: 8}

    def test_parses_two_windows(self):
        result = _parse_rate_limit_header("8:10,45:600")
        assert result == {10: 8, 600: 45}

    def test_handles_empty_string(self):
        result = _parse_rate_limit_header("")
        assert result == {}

    def test_handles_malformed_string(self):
        result = _parse_rate_limit_header("notvalid")
        assert result == {}


# ---------------------------------------------------------------------------
# check_and_wait
# ---------------------------------------------------------------------------

class TestCheckAndWait:

    def test_does_not_sleep_when_no_pause(self, fake_redis):
        # No pause_until key set — should return immediately
        with patch("time.sleep") as mock_sleep:
            check_and_wait()
            mock_sleep.assert_not_called()

    def test_does_not_sleep_when_pause_expired(self, fake_redis):
        # Set pause_until to the past
        fake_redis.set(PAUSE_UNTIL_KEY, str(time.time() - 10))
        with patch("time.sleep") as mock_sleep:
            check_and_wait()
            mock_sleep.assert_not_called()

    def test_sleeps_when_pause_active(self, fake_redis):
        # Set pause_until to 5 seconds in the future
        fake_redis.set(PAUSE_UNTIL_KEY, str(time.time() + 5))
        with patch("time.sleep") as mock_sleep:
            check_and_wait()
            mock_sleep.assert_called_once()
            sleep_duration = mock_sleep.call_args[0][0]
            assert 4 < sleep_duration <= 5


# ---------------------------------------------------------------------------
# update_rate_limit
# ---------------------------------------------------------------------------

class TestUpdateRateLimit:

    def test_sets_pause_when_buffer_reached(self, fake_redis):
        # 96 calls made out of 100 in 120s window — only 4 remaining, below buffer of 5
        headers = {
            "x-app-rate-limit-count": "96:120",
            "x-app-rate-limit": "100:120",
        }
        update_rate_limit(headers)
        pause_until = fake_redis.get(PAUSE_UNTIL_KEY)
        assert pause_until is not None
        assert float(pause_until) > time.time()

    def test_does_not_set_pause_when_plenty_remaining(self, fake_redis):
        # Only 10 calls made out of 100 — 90 remaining, well above buffer
        headers = {
            "x-app-rate-limit-count": "10:120",
            "x-app-rate-limit": "100:120",
        }
        update_rate_limit(headers)
        assert fake_redis.get(PAUSE_UNTIL_KEY) is None

    def test_handles_missing_headers_gracefully(self, fake_redis):
        # No rate limit headers — should not crash or set pause
        update_rate_limit({})
        assert fake_redis.get(PAUSE_UNTIL_KEY) is None

    def test_handles_malformed_headers_gracefully(self, fake_redis):
        headers = {
            "x-app-rate-limit-count": "notvalid",
            "x-app-rate-limit": "alsonotvalid",
        }
        update_rate_limit(headers)
        assert fake_redis.get(PAUSE_UNTIL_KEY) is None


# ---------------------------------------------------------------------------
# set_pause_for_retry
# ---------------------------------------------------------------------------

class TestSetPauseForRetry:

    def test_sets_pause_until_in_future(self, fake_redis):
        set_pause_for_retry(retry_after_seconds=60)
        pause_until = fake_redis.get(PAUSE_UNTIL_KEY)
        assert pause_until is not None
        assert float(pause_until) > time.time()
        assert float(pause_until) <= time.time() + 61

    def test_overwrites_existing_pause(self, fake_redis):
        # Set a short existing pause
        fake_redis.set(PAUSE_UNTIL_KEY, str(time.time() + 5))
        # Set a longer pause via 429
        set_pause_for_retry(retry_after_seconds=120)
        pause_until = float(fake_redis.get(PAUSE_UNTIL_KEY))
        # New pause should be roughly 120 seconds from now
        assert pause_until > time.time() + 100
