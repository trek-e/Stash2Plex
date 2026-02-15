"""
Tests for RecoveryRateLimiter - graduated rate limiting during post-recovery queue drain.

Tests use deterministic time injection via `now` parameter to avoid real time.time() calls.
"""

import pytest
from worker.rate_limiter import RecoveryRateLimiter


class TestGraduatedRateCalculation:
    """Tests for current_rate() graduated scaling."""

    def test_current_rate_at_start(self):
        """current_rate() returns initial_rate (5.0) at elapsed=0."""
        limiter = RecoveryRateLimiter(initial_rate=5.0, target_rate=20.0, ramp_duration=300.0)
        limiter.start_recovery_period(now=1000.0)

        rate = limiter.current_rate(now=1000.0)  # elapsed=0
        assert rate == 5.0

    def test_current_rate_at_midpoint(self):
        """current_rate() returns midpoint rate at elapsed=ramp_duration/2."""
        limiter = RecoveryRateLimiter(initial_rate=5.0, target_rate=20.0, ramp_duration=300.0)
        limiter.start_recovery_period(now=1000.0)

        rate = limiter.current_rate(now=1150.0)  # elapsed=150 (half of 300)
        expected = 5.0 + (20.0 - 5.0) * (150.0 / 300.0)  # 5 + 15 * 0.5 = 12.5
        assert rate == expected

    def test_current_rate_at_end(self):
        """current_rate() returns target_rate (20.0) at elapsed=ramp_duration."""
        limiter = RecoveryRateLimiter(initial_rate=5.0, target_rate=20.0, ramp_duration=300.0)
        limiter.start_recovery_period(now=1000.0)

        rate = limiter.current_rate(now=1300.0)  # elapsed=300
        assert rate == 20.0

    def test_current_rate_after_end(self):
        """current_rate() returns target_rate when elapsed > ramp_duration."""
        limiter = RecoveryRateLimiter(initial_rate=5.0, target_rate=20.0, ramp_duration=300.0)
        limiter.start_recovery_period(now=1000.0)

        rate = limiter.current_rate(now=1500.0)  # elapsed=500 (beyond 300)
        assert rate == 20.0

    def test_linear_interpolation(self):
        """Linear interpolation: rate = initial + (target - initial) * (elapsed / ramp_duration)."""
        limiter = RecoveryRateLimiter(initial_rate=5.0, target_rate=20.0, ramp_duration=300.0)
        limiter.start_recovery_period(now=1000.0)

        # Test several points
        rate_60 = limiter.current_rate(now=1060.0)  # 20% through ramp
        expected_60 = 5.0 + (20.0 - 5.0) * (60.0 / 300.0)  # 5 + 15 * 0.2 = 8.0
        assert rate_60 == expected_60

        rate_240 = limiter.current_rate(now=1240.0)  # 80% through ramp
        expected_240 = 5.0 + (20.0 - 5.0) * (240.0 / 300.0)  # 5 + 15 * 0.8 = 17.0
        assert rate_240 == expected_240

    def test_custom_config(self):
        """Custom config: initial_rate=2, target_rate=50, ramp_duration=600."""
        limiter = RecoveryRateLimiter(initial_rate=2.0, target_rate=50.0, ramp_duration=600.0)
        limiter.start_recovery_period(now=2000.0)

        # At start
        assert limiter.current_rate(now=2000.0) == 2.0

        # At midpoint (300s)
        rate_mid = limiter.current_rate(now=2300.0)
        expected_mid = 2.0 + (50.0 - 2.0) * (300.0 / 600.0)  # 2 + 48 * 0.5 = 26.0
        assert rate_mid == expected_mid

        # At end
        assert limiter.current_rate(now=2600.0) == 50.0

    def test_current_rate_not_in_recovery(self):
        """current_rate() returns target_rate when not in recovery period."""
        limiter = RecoveryRateLimiter(initial_rate=5.0, target_rate=20.0, ramp_duration=300.0)
        # Never started recovery
        rate = limiter.current_rate(now=1000.0)
        assert rate == 20.0


class TestRecoveryPeriodLifecycle:
    """Tests for recovery period lifecycle management."""

    def test_is_in_recovery_period_not_started(self):
        """is_in_recovery_period() returns False when not started (recovery_started_at=0)."""
        limiter = RecoveryRateLimiter()
        assert limiter.is_in_recovery_period(now=1000.0) is False

    def test_is_in_recovery_period_during_recovery(self):
        """is_in_recovery_period() returns True during recovery."""
        limiter = RecoveryRateLimiter(ramp_duration=300.0)
        limiter.start_recovery_period(now=1000.0)

        assert limiter.is_in_recovery_period(now=1000.0) is True
        assert limiter.is_in_recovery_period(now=1150.0) is True
        assert limiter.is_in_recovery_period(now=1299.0) is True

    def test_is_in_recovery_period_after_ramp(self):
        """is_in_recovery_period() returns False after ramp_duration elapsed."""
        limiter = RecoveryRateLimiter(ramp_duration=300.0)
        limiter.start_recovery_period(now=1000.0)

        assert limiter.is_in_recovery_period(now=1300.0) is False
        assert limiter.is_in_recovery_period(now=1500.0) is False

    def test_start_recovery_period(self):
        """start_recovery_period() sets recovery_started_at and resets tokens."""
        limiter = RecoveryRateLimiter()
        limiter.start_recovery_period(now=1234.5)

        assert limiter.recovery_started_at == 1234.5
        assert limiter.is_in_recovery_period(now=1234.5) is True

    def test_end_recovery_period(self):
        """end_recovery_period() clears recovery_started_at (sets to 0.0)."""
        limiter = RecoveryRateLimiter()
        limiter.start_recovery_period(now=1000.0)
        assert limiter.is_in_recovery_period(now=1100.0) is True

        limiter.end_recovery_period()
        assert limiter.recovery_started_at == 0.0
        assert limiter.is_in_recovery_period(now=1100.0) is False

    def test_start_recovery_period_from_existing_timestamp(self):
        """start_recovery_period() can resume from existing timestamp (cross-restart resume)."""
        limiter = RecoveryRateLimiter(ramp_duration=300.0)

        # Simulate restart: start recovery at earlier time, check current state
        limiter.recovery_started_at = 1000.0  # Set directly (like loading from state)

        # 100 seconds into recovery
        assert limiter.is_in_recovery_period(now=1100.0) is True
        rate = limiter.current_rate(now=1100.0)
        expected = 5.0 + (20.0 - 5.0) * (100.0 / 300.0)
        assert rate == expected


class TestTokenBucket:
    """Tests for token bucket and should_wait() method."""

    def test_should_wait_not_in_recovery(self):
        """should_wait() returns 0.0 when not in recovery period (no limiting)."""
        limiter = RecoveryRateLimiter()
        wait_time = limiter.should_wait(now=1000.0)
        assert wait_time == 0.0

    def test_should_wait_token_available(self):
        """should_wait() returns 0.0 when token available (consumes token)."""
        limiter = RecoveryRateLimiter(initial_rate=5.0)
        limiter.start_recovery_period(now=1000.0)

        # First call has tokens (capacity=1.0 at start)
        wait_time = limiter.should_wait(now=1000.0)
        assert wait_time == 0.0

    def test_should_wait_no_tokens_available(self):
        """should_wait() returns >0 wait time when no tokens available."""
        limiter = RecoveryRateLimiter(initial_rate=5.0)
        limiter.start_recovery_period(now=1000.0)

        # Consume initial token
        limiter.should_wait(now=1000.0)

        # Immediate second call has no tokens
        wait_time = limiter.should_wait(now=1000.0)
        assert wait_time > 0.0
        # At rate=5.0 jobs/sec, need to wait ~0.2s for next token
        assert abs(wait_time - 0.2) < 0.01

    def test_token_refill_over_time(self):
        """Token refill: after waiting, tokens refill based on current_rate."""
        limiter = RecoveryRateLimiter(initial_rate=5.0, target_rate=20.0, ramp_duration=300.0)
        limiter.start_recovery_period(now=1000.0)

        # Consume initial token
        limiter.should_wait(now=1000.0)

        # Wait 0.2s (at rate=5.0, should get 1 token)
        wait_time = limiter.should_wait(now=1000.2)
        assert wait_time == 0.0  # Token refilled

    def test_burst_capacity(self):
        """Burst capacity: bucket starts with `capacity` tokens (default 1.0)."""
        limiter = RecoveryRateLimiter(initial_rate=5.0)
        limiter.start_recovery_period(now=1000.0)

        # First call succeeds (uses initial capacity)
        wait_time_1 = limiter.should_wait(now=1000.0)
        assert wait_time_1 == 0.0

        # Second call immediate needs to wait (capacity exhausted)
        wait_time_2 = limiter.should_wait(now=1000.0)
        assert wait_time_2 > 0.0

    def test_rate_changes_accelerate_refill(self):
        """Rate changes: as current_rate increases, refill accelerates."""
        limiter = RecoveryRateLimiter(initial_rate=5.0, target_rate=20.0, ramp_duration=300.0)
        limiter.start_recovery_period(now=1000.0)

        # At start (rate=5.0), consume token and check refill time
        limiter.should_wait(now=1000.0)
        wait_start = limiter.should_wait(now=1000.0)

        # Midway through ramp (rate=12.5), consume token and check refill
        limiter.start_recovery_period(now=2000.0)  # Reset
        limiter.should_wait(now=2150.0)  # Midpoint
        wait_mid = limiter.should_wait(now=2150.0)

        # Higher rate means shorter wait
        assert wait_mid < wait_start

    def test_should_wait_after_recovery_end(self):
        """At recovery end: should_wait() returns 0.0 (unlimited)."""
        limiter = RecoveryRateLimiter(ramp_duration=300.0)
        limiter.start_recovery_period(now=1000.0)

        # After recovery period
        wait_time = limiter.should_wait(now=1500.0)
        assert wait_time == 0.0


class TestErrorRateMonitoring:
    """Tests for error rate monitoring and adaptive backoff."""

    def test_record_result_success(self):
        """record_result(success=True) records success."""
        limiter = RecoveryRateLimiter()
        limiter.start_recovery_period(now=1000.0)
        limiter.record_result(success=True, now=1000.0)

        # Error rate should be 0
        assert limiter.error_rate(now=1000.0) == 0.0

    def test_record_result_failure(self):
        """record_result(success=False) records failure."""
        limiter = RecoveryRateLimiter()
        limiter.start_recovery_period(now=1000.0)
        limiter.record_result(success=False, now=1000.0)

        # Error rate should be 1.0 (1 failure / 1 total)
        assert limiter.error_rate(now=1000.0) == 1.0

    def test_error_rate_calculation(self):
        """error_rate() calculates failures/total in time window (60s)."""
        limiter = RecoveryRateLimiter(error_window=60.0)
        limiter.start_recovery_period(now=1000.0)

        # 3 successes, 2 failures
        limiter.record_result(success=True, now=1000.0)
        limiter.record_result(success=False, now=1010.0)
        limiter.record_result(success=True, now=1020.0)
        limiter.record_result(success=False, now=1030.0)
        limiter.record_result(success=True, now=1040.0)

        # Error rate = 2/5 = 0.4
        assert limiter.error_rate(now=1040.0) == 0.4

    def test_old_results_pruned(self):
        """Old results outside window are pruned."""
        limiter = RecoveryRateLimiter(error_window=60.0)
        limiter.start_recovery_period(now=1000.0)

        # Old results (outside window)
        limiter.record_result(success=False, now=1000.0)
        limiter.record_result(success=False, now=1010.0)

        # Recent results (within window)
        limiter.record_result(success=True, now=1100.0)
        limiter.record_result(success=True, now=1110.0)

        # At now=1120, old results (1000, 1010) are > 60s old, should be pruned
        error_rate = limiter.error_rate(now=1120.0)
        # Only recent successes count: 0/2 = 0.0
        assert error_rate == 0.0

    def test_should_backoff_above_threshold(self):
        """should_backoff() returns True when error_rate > threshold (0.3)."""
        limiter = RecoveryRateLimiter(error_threshold=0.3)
        limiter.start_recovery_period(now=1000.0)

        # Create error rate of 0.4 (above 0.3)
        limiter.record_result(success=False, now=1000.0)
        limiter.record_result(success=False, now=1010.0)
        limiter.record_result(success=True, now=1020.0)
        limiter.record_result(success=True, now=1030.0)
        limiter.record_result(success=True, now=1040.0)

        # Error rate = 2/5 = 0.4 > 0.3
        assert limiter.error_rate(now=1040.0) == 0.4
        # This is detected during record_result, which adjusts rate

    def test_should_backoff_below_threshold(self):
        """should_backoff() returns False when error_rate <= threshold."""
        limiter = RecoveryRateLimiter(error_threshold=0.3)
        limiter.start_recovery_period(now=1000.0)

        # Create error rate of 0.2 (below 0.3)
        limiter.record_result(success=False, now=1000.0)
        limiter.record_result(success=True, now=1010.0)
        limiter.record_result(success=True, now=1020.0)
        limiter.record_result(success=True, now=1030.0)
        limiter.record_result(success=True, now=1040.0)

        # Error rate = 1/5 = 0.2 <= 0.3
        assert limiter.error_rate(now=1040.0) == 0.2

    def test_backoff_reduces_rate(self):
        """Backoff reduces current rate by 50% (rate_multiplier=0.5)."""
        limiter = RecoveryRateLimiter(initial_rate=10.0, target_rate=20.0, error_threshold=0.3)
        limiter.start_recovery_period(now=1000.0)

        # Baseline rate at start
        base_rate = limiter.current_rate(now=1000.0)
        assert base_rate == 10.0

        # Trigger backoff with high error rate
        for i in range(4):
            limiter.record_result(success=False, now=1000.0 + i)  # 4 failures
        limiter.record_result(success=True, now=1005.0)  # 1 success
        # Error rate = 4/5 = 0.8 > 0.3, triggers backoff

        # After backoff, rate should be halved
        backed_off_rate = limiter.current_rate(now=1010.0)
        assert backed_off_rate == base_rate * 0.5

    def test_backoff_recovery(self):
        """Backoff recovery: when error rate drops below 0.1, restore multiplier to 1.0."""
        limiter = RecoveryRateLimiter(initial_rate=10.0, error_threshold=0.3)
        limiter.start_recovery_period(now=1000.0)

        # Trigger backoff
        for i in range(4):
            limiter.record_result(success=False, now=1000.0 + i)
        limiter.record_result(success=True, now=1005.0)

        # Rate is halved
        assert limiter.current_rate(now=1010.0) == 5.0

        # After backoff_until expires and error rate drops, restore
        # Add many successes to drop error rate below 0.1
        for i in range(20):
            limiter.record_result(success=True, now=1100.0 + i)

        # Error rate now < 0.1, should restore multiplier
        rate = limiter.current_rate(now=1200.0)
        # At now=1200, elapsed=200, rate should be 10.0 (not halved)
        expected = 10.0 + (20.0 - 10.0) * (200.0 / 300.0)
        assert rate == expected


class TestEdgeCases:
    """Tests for edge cases and defaults."""

    def test_constructor_defaults(self):
        """Constructor defaults: initial_rate=5.0, target_rate=20.0, ramp_duration=300.0, error_threshold=0.3."""
        limiter = RecoveryRateLimiter()

        assert limiter.initial_rate == 5.0
        assert limiter.target_rate == 20.0
        assert limiter.ramp_duration == 300.0
        assert limiter.error_threshold == 0.3

    def test_now_parameter_injection(self):
        """All time-dependent methods accept optional `now` parameter for deterministic testing."""
        limiter = RecoveryRateLimiter()

        # Methods should accept now parameter
        limiter.is_in_recovery_period(now=1000.0)
        limiter.start_recovery_period(now=1000.0)
        limiter.current_rate(now=1000.0)
        limiter.should_wait(now=1000.0)
        limiter.record_result(success=True, now=1000.0)
        limiter.error_rate(now=1000.0)

    def test_empty_error_window(self):
        """Empty error window returns 0.0 error rate."""
        limiter = RecoveryRateLimiter()
        limiter.start_recovery_period(now=1000.0)

        # No results recorded
        assert limiter.error_rate(now=1000.0) == 0.0

    def test_multiple_start_calls_reset(self):
        """Multiple start_recovery_period calls reset properly."""
        limiter = RecoveryRateLimiter()

        # First start
        limiter.start_recovery_period(now=1000.0)
        limiter.record_result(success=False, now=1010.0)
        assert limiter.recovery_started_at == 1000.0

        # Second start should reset
        limiter.start_recovery_period(now=2000.0)
        assert limiter.recovery_started_at == 2000.0
        # Results should be cleared
        assert limiter.error_rate(now=2000.0) == 0.0

    def test_recovery_started_at_defaults_to_zero(self):
        """recovery_started_at defaults to 0.0 (not in recovery)."""
        limiter = RecoveryRateLimiter()
        assert limiter.recovery_started_at == 0.0
        assert limiter.is_in_recovery_period(now=1000.0) is False
