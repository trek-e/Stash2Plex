"""
Tests for circuit breaker state machine.

Tests verify the 3-state machine (CLOSED, OPEN, HALF_OPEN)
transitions correctly based on success/failure/timeout.
"""

import pytest
from unittest.mock import patch

from worker.circuit_breaker import CircuitBreaker, CircuitState


class TestCircuitBreakerInitialState:
    """Test initial state and basic properties."""

    def test_initial_state_closed(self):
        """Circuit starts in CLOSED state."""
        breaker = CircuitBreaker()
        assert breaker.state == CircuitState.CLOSED

    def test_can_execute_when_closed(self):
        """Can execute when circuit is CLOSED."""
        breaker = CircuitBreaker()
        assert breaker.can_execute() is True


class TestCircuitBreakerOpenTransition:
    """Test CLOSED -> OPEN transition."""

    def test_opens_after_threshold_failures(self):
        """Circuit opens after failure_threshold consecutive failures."""
        breaker = CircuitBreaker(failure_threshold=3)

        # Record 2 failures - should stay closed
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.state == CircuitState.CLOSED

        # 3rd failure opens circuit
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

    def test_blocks_when_open(self):
        """Cannot execute when circuit is OPEN."""
        breaker = CircuitBreaker(failure_threshold=2)

        breaker.record_failure()
        breaker.record_failure()

        assert breaker.state == CircuitState.OPEN
        assert breaker.can_execute() is False

    def test_success_resets_failure_count(self):
        """Success resets failure count in CLOSED state."""
        breaker = CircuitBreaker(failure_threshold=3)

        # 2 failures
        breaker.record_failure()
        breaker.record_failure()

        # Success resets count
        breaker.record_success()

        # 2 more failures should not open (count reset)
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.state == CircuitState.CLOSED

        # 3rd failure now opens
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN


class TestCircuitBreakerHalfOpen:
    """Test OPEN -> HALF_OPEN transition."""

    def test_half_open_after_recovery_timeout(self):
        """Circuit transitions to HALF_OPEN after recovery timeout."""
        breaker = CircuitBreaker(failure_threshold=2, recovery_timeout=60.0)

        # Open the circuit
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

        # Mock time to simulate timeout elapsed
        with patch('worker.circuit_breaker.time') as mock_time:
            # First call is when we opened, second is now (61 seconds later)
            mock_time.time.return_value = 100.0  # Any value > opened_at + timeout
            # Force internal opened_at to a known value
            breaker._opened_at = 30.0  # 100 - 30 = 70 > 60 (timeout)

            assert breaker.state == CircuitState.HALF_OPEN
            assert breaker.can_execute() is True

    def test_not_half_open_before_timeout(self):
        """Circuit stays OPEN before recovery timeout."""
        breaker = CircuitBreaker(failure_threshold=2, recovery_timeout=60.0)

        # Open the circuit
        breaker.record_failure()
        breaker.record_failure()

        with patch('worker.circuit_breaker.time') as mock_time:
            # Simulate only 30 seconds elapsed (less than 60s timeout)
            breaker._opened_at = 70.0
            mock_time.time.return_value = 100.0  # 100 - 70 = 30 < 60

            assert breaker.state == CircuitState.OPEN
            assert breaker.can_execute() is False


class TestCircuitBreakerRecovery:
    """Test HALF_OPEN -> CLOSED and HALF_OPEN -> OPEN transitions."""

    def test_success_closes_circuit(self):
        """Success in HALF_OPEN state closes the circuit."""
        breaker = CircuitBreaker(failure_threshold=2, success_threshold=1)

        # Open the circuit
        breaker.record_failure()
        breaker.record_failure()

        # Force HALF_OPEN state
        breaker._state = CircuitState.HALF_OPEN

        # Record success
        breaker.record_success()

        assert breaker.state == CircuitState.CLOSED
        assert breaker.can_execute() is True

    def test_failure_in_half_open_reopens(self):
        """Failure in HALF_OPEN state reopens the circuit."""
        breaker = CircuitBreaker(failure_threshold=2)

        # Open the circuit
        breaker.record_failure()
        breaker.record_failure()

        # Force HALF_OPEN state
        breaker._state = CircuitState.HALF_OPEN

        # Record failure
        breaker.record_failure()

        assert breaker.state == CircuitState.OPEN
        assert breaker.can_execute() is False

    def test_multiple_successes_required(self):
        """Circuit requires success_threshold successes to close from HALF_OPEN."""
        breaker = CircuitBreaker(failure_threshold=2, success_threshold=3)

        # Force HALF_OPEN state
        breaker._state = CircuitState.HALF_OPEN

        # 2 successes - still HALF_OPEN
        breaker.record_success()
        breaker.record_success()
        assert breaker.state == CircuitState.HALF_OPEN

        # 3rd success closes
        breaker.record_success()
        assert breaker.state == CircuitState.CLOSED


class TestCircuitBreakerReset:
    """Test manual reset functionality."""

    def test_reset_closes_circuit(self):
        """Reset forces circuit to CLOSED state."""
        breaker = CircuitBreaker(failure_threshold=2)

        # Open the circuit
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

        # Reset
        breaker.reset()

        assert breaker.state == CircuitState.CLOSED
        assert breaker.can_execute() is True

    def test_reset_clears_counters(self):
        """Reset clears failure and success counters."""
        breaker = CircuitBreaker(failure_threshold=3)

        # Build up failures
        breaker.record_failure()
        breaker.record_failure()

        # Reset
        breaker.reset()

        # Should need full threshold again
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.state == CircuitState.CLOSED

        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN
