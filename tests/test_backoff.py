"""
Unit tests for exponential backoff with full jitter.

Tests verify:
- Delay increases exponentially with retry count
- Full jitter randomizes delay within [0, calculated_max]
- Delay never exceeds configured cap
- PlexNotFound uses longer base delay and higher cap
"""

import pytest


class TestCalculateDelay:
    """Tests for calculate_delay function."""

    def test_retry_zero_returns_value_in_zero_to_base(self):
        """Retry 0, base=5 should return delay in [0, 5]."""
        from worker.backoff import calculate_delay

        # Use seed for deterministic test
        delay = calculate_delay(retry_count=0, base=5.0, cap=80.0, jitter_seed=42)
        assert 0 <= delay <= 5.0

    def test_retry_one_returns_value_in_zero_to_double_base(self):
        """Retry 1, base=5 should return delay in [0, 10]."""
        from worker.backoff import calculate_delay

        delay = calculate_delay(retry_count=1, base=5.0, cap=80.0, jitter_seed=42)
        assert 0 <= delay <= 10.0

    def test_retry_two_returns_value_in_zero_to_quadruple_base(self):
        """Retry 2, base=5 should return delay in [0, 20]."""
        from worker.backoff import calculate_delay

        delay = calculate_delay(retry_count=2, base=5.0, cap=80.0, jitter_seed=42)
        assert 0 <= delay <= 20.0

    def test_retry_three_returns_value_in_expected_range(self):
        """Retry 3, base=5 should return delay in [0, 40]."""
        from worker.backoff import calculate_delay

        delay = calculate_delay(retry_count=3, base=5.0, cap=80.0, jitter_seed=42)
        assert 0 <= delay <= 40.0

    def test_retry_four_returns_value_in_expected_range(self):
        """Retry 4, base=5 should return delay in [0, 80]."""
        from worker.backoff import calculate_delay

        delay = calculate_delay(retry_count=4, base=5.0, cap=80.0, jitter_seed=42)
        assert 0 <= delay <= 80.0

    def test_retry_five_capped_at_cap_value(self):
        """Retry 5 with base=5, cap=80 should return delay in [0, 80] (capped)."""
        from worker.backoff import calculate_delay

        # Without cap, base * 2^5 = 5 * 32 = 160
        # With cap=80, should be in [0, 80]
        delay = calculate_delay(retry_count=5, base=5.0, cap=80.0, jitter_seed=42)
        assert 0 <= delay <= 80.0

    def test_high_retry_count_respects_cap(self):
        """Very high retry count should still respect cap."""
        from worker.backoff import calculate_delay

        delay = calculate_delay(retry_count=100, base=5.0, cap=80.0, jitter_seed=42)
        assert 0 <= delay <= 80.0

    def test_seeded_random_is_deterministic(self):
        """Same seed should produce same delay."""
        from worker.backoff import calculate_delay

        delay1 = calculate_delay(retry_count=2, base=5.0, cap=80.0, jitter_seed=42)
        delay2 = calculate_delay(retry_count=2, base=5.0, cap=80.0, jitter_seed=42)
        assert delay1 == delay2

    def test_different_seeds_produce_different_delays(self):
        """Different seeds should produce different delays."""
        from worker.backoff import calculate_delay

        delay1 = calculate_delay(retry_count=2, base=5.0, cap=80.0, jitter_seed=42)
        delay2 = calculate_delay(retry_count=2, base=5.0, cap=80.0, jitter_seed=123)
        assert delay1 != delay2

    def test_specific_seed_value(self):
        """Verify specific known value for seed=42, retry=0, base=5."""
        from worker.backoff import calculate_delay

        delay = calculate_delay(retry_count=0, base=5.0, cap=80.0, jitter_seed=42)
        # With seed=42, random.uniform(0, 5) should give consistent value
        # We verify it's in range and deterministic
        assert 0 <= delay <= 5.0
        # Verify it's the same on subsequent calls
        delay2 = calculate_delay(retry_count=0, base=5.0, cap=80.0, jitter_seed=42)
        assert delay == delay2


class TestGetRetryParams:
    """Tests for get_retry_params function."""

    def test_plex_not_found_returns_longer_delays(self):
        """PlexNotFound's core (early) attempts keep (30.0, 600.0), but
        max_retries is now 15 to accommodate the long tail (#12/D2) that
        extends the schedule to ~24h instead of exhausting at ~1.4h."""
        from worker.backoff import get_retry_params
        from plex.exceptions import PlexNotFound

        error = PlexNotFound("Item not found")
        base, cap, max_retries = get_retry_params(error)

        assert base == 30.0
        assert cap == 600.0
        assert max_retries == 15

    def test_plex_not_found_core_attempts_unchanged(self):
        """Attempts 1-12 (retry_count 0-11) keep the original 30s/600s schedule."""
        from worker.backoff import get_retry_params
        from plex.exceptions import PlexNotFound

        error = PlexNotFound("Item not found")
        for retry_count in range(0, 12):
            base, cap, max_retries = get_retry_params(error, retry_count)
            assert base == 30.0
            assert cap == 600.0
            assert max_retries == 15

    def test_plex_not_found_tail_extends_to_roughly_24h(self):
        """Attempts 13-15 (retry_count 12-14) escalate to ~6h/12h/24h caps
        so a job survives roughly until Plex's next scheduled scan."""
        from worker.backoff import get_retry_params
        from plex.exceptions import PlexNotFound

        error = PlexNotFound("Item not found")

        base, cap, max_retries = get_retry_params(error, retry_count=12)
        assert base == 30.0
        assert cap == 6 * 3600.0
        assert max_retries == 15

        base, cap, max_retries = get_retry_params(error, retry_count=13)
        assert cap == 12 * 3600.0

        base, cap, max_retries = get_retry_params(error, retry_count=14)
        assert cap == 24 * 3600.0

        # Beyond the defined tail, stay at the final (24h) cap rather than
        # growing further or raising.
        base, cap, max_retries = get_retry_params(error, retry_count=20)
        assert cap == 24 * 3600.0

    def test_plex_temporary_error_returns_standard_delays(self):
        """PlexTemporaryError should return (5.0, 80.0, 5)."""
        from worker.backoff import get_retry_params
        from plex.exceptions import PlexTemporaryError

        error = PlexTemporaryError("Network error")
        base, cap, max_retries = get_retry_params(error)

        assert base == 5.0
        assert cap == 80.0
        assert max_retries == 5

    def test_transient_error_returns_standard_delays(self):
        """Generic TransientError should return (5.0, 80.0, 5)."""
        from worker.backoff import get_retry_params
        from worker.processor import TransientError

        error = TransientError("Some transient error")
        base, cap, max_retries = get_retry_params(error)

        assert base == 5.0
        assert cap == 80.0
        assert max_retries == 5

    def test_permanent_error_returns_standard_delays(self):
        """PermanentError should return standard delays (won't retry anyway)."""
        from worker.backoff import get_retry_params
        from worker.processor import PermanentError

        error = PermanentError("Auth failed")
        base, cap, max_retries = get_retry_params(error)

        assert base == 5.0
        assert cap == 80.0
        assert max_retries == 5

    def test_unknown_error_returns_standard_delays(self):
        """Unknown error types should return standard delays."""
        from worker.backoff import get_retry_params

        error = ValueError("Some random error")
        base, cap, max_retries = get_retry_params(error)

        assert base == 5.0
        assert cap == 80.0
        assert max_retries == 5
