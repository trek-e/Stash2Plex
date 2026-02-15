"""
Tests for circuit breaker state machine.

Tests verify the 3-state machine (CLOSED, OPEN, HALF_OPEN)
transitions correctly based on success/failure/timeout.
"""

import pytest
import json
import fcntl
from pathlib import Path
from unittest.mock import patch, mock_open

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


class TestCircuitBreakerStatePersistence:
    """Test state persistence across CircuitBreaker instances."""

    def test_state_persisted_on_open(self, tmp_path):
        """State is persisted when circuit opens and can be reloaded."""
        state_file = str(tmp_path / "cb.json")

        # Create breaker and open it
        breaker = CircuitBreaker(failure_threshold=5, state_file=state_file)
        for _ in range(5):
            breaker.record_failure()

        assert breaker.state == CircuitState.OPEN
        assert Path(state_file).exists()

        # Create new breaker from same file
        breaker2 = CircuitBreaker(state_file=state_file)
        assert breaker2.state == CircuitState.OPEN
        assert breaker2._opened_at is not None

    def test_state_persisted_on_close(self, tmp_path):
        """State is persisted when circuit closes."""
        state_file = str(tmp_path / "cb.json")

        # Open circuit
        breaker = CircuitBreaker(failure_threshold=2, state_file=state_file)
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

        # Force HALF_OPEN and record success to close
        breaker._state = CircuitState.HALF_OPEN
        breaker.record_success()

        # Create new breaker from same file
        breaker2 = CircuitBreaker(state_file=state_file)
        assert breaker2.state == CircuitState.CLOSED

    def test_state_persisted_on_half_open(self, tmp_path):
        """HALF_OPEN state is persisted correctly."""
        state_file = str(tmp_path / "cb.json")

        # Open circuit
        breaker = CircuitBreaker(failure_threshold=2, recovery_timeout=60.0, state_file=state_file)
        breaker.record_failure()
        breaker.record_failure()

        # Force HALF_OPEN via time mock
        with patch('worker.circuit_breaker.time') as mock_time:
            breaker._opened_at = 30.0
            mock_time.time.return_value = 100.0  # 70 seconds elapsed
            _ = breaker.state  # Triggers transition to HALF_OPEN

        # Create new breaker from same file
        breaker2 = CircuitBreaker(state_file=state_file)
        assert breaker2.state == CircuitState.HALF_OPEN

    def test_no_persistence_without_state_file(self, tmp_path):
        """CircuitBreaker without state_file doesn't create any files."""
        # Create breaker without state_file
        breaker = CircuitBreaker(failure_threshold=2)

        # Trigger transitions
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

        # Force HALF_OPEN
        breaker._state = CircuitState.HALF_OPEN
        breaker.record_success()
        assert breaker.state == CircuitState.CLOSED

        # Verify no files created in tmp_path
        assert len(list(tmp_path.iterdir())) == 0

    def test_failure_count_persisted(self, tmp_path):
        """Failure count persists across instances."""
        state_file = str(tmp_path / "cb.json")

        # Record 3 failures (below threshold of 5)
        breaker = CircuitBreaker(failure_threshold=5, state_file=state_file)
        for _ in range(3):
            breaker.record_failure()
        assert breaker.state == CircuitState.CLOSED

        # Create new breaker and record 2 more failures
        breaker2 = CircuitBreaker(failure_threshold=5, state_file=state_file)
        breaker2.record_failure()
        breaker2.record_failure()

        # Should be OPEN now (3+2=5)
        assert breaker2.state == CircuitState.OPEN

    def test_success_count_persisted_in_half_open(self, tmp_path):
        """Success count in HALF_OPEN state persists across instances."""
        state_file = str(tmp_path / "cb.json")

        # Open circuit and force HALF_OPEN
        breaker = CircuitBreaker(failure_threshold=2, success_threshold=3, state_file=state_file)
        breaker.record_failure()
        breaker.record_failure()
        breaker._state = CircuitState.HALF_OPEN

        # Record 1 success
        breaker.record_success()
        assert breaker.state == CircuitState.HALF_OPEN

        # Create new breaker and record 2 more successes
        breaker2 = CircuitBreaker(failure_threshold=2, success_threshold=3, state_file=state_file)
        breaker2.record_success()
        breaker2.record_success()

        # Should be CLOSED now (1+2=3)
        assert breaker2.state == CircuitState.CLOSED


class TestCircuitBreakerStateCorruption:
    """Test graceful degradation when state file is corrupted."""

    def test_corrupted_json_defaults_to_closed(self, tmp_path):
        """Corrupted JSON file defaults to CLOSED state."""
        state_file = str(tmp_path / "cb.json")

        # Write garbage to state file
        with open(state_file, 'w') as f:
            f.write("this is not json {{{")

        # Create breaker - should not raise exception
        breaker = CircuitBreaker(state_file=state_file)
        assert breaker.state == CircuitState.CLOSED

    def test_missing_keys_defaults_to_closed(self, tmp_path):
        """State file missing required keys defaults to CLOSED."""
        state_file = str(tmp_path / "cb.json")

        # Write incomplete JSON
        with open(state_file, 'w') as f:
            json.dump({"state": "open"}, f)

        breaker = CircuitBreaker(state_file=state_file)
        assert breaker.state == CircuitState.CLOSED

    def test_invalid_state_value_defaults_to_closed(self, tmp_path):
        """Invalid state value defaults to CLOSED."""
        state_file = str(tmp_path / "cb.json")

        # Write invalid state
        with open(state_file, 'w') as f:
            json.dump({
                "state": "invalid",
                "failure_count": 0,
                "success_count": 0,
                "opened_at": None
            }, f)

        breaker = CircuitBreaker(state_file=state_file)
        assert breaker.state == CircuitState.CLOSED

    def test_nonexistent_file_defaults_to_closed(self, tmp_path):
        """Nonexistent state file defaults to CLOSED."""
        state_file = str(tmp_path / "nonexistent.json")

        breaker = CircuitBreaker(state_file=state_file)
        assert breaker.state == CircuitState.CLOSED

    def test_save_failure_nonfatal(self, tmp_path):
        """Save failure doesn't raise exception, breaker continues to work."""
        state_file = str(tmp_path / "cb.json")

        breaker = CircuitBreaker(failure_threshold=2, state_file=state_file)

        # Mock open to raise OSError during save
        with patch('builtins.open', side_effect=OSError("Disk full")):
            # Should not raise exception
            breaker.record_failure()
            breaker.record_failure()

        # Breaker should still transition in-memory
        assert breaker.state == CircuitState.OPEN


class TestCircuitBreakerTransitionLogging:
    """Test logging of state transitions (VISB-02 requirement)."""

    def test_log_on_open(self):
        """Opening circuit logs appropriate message."""
        breaker = CircuitBreaker(failure_threshold=3)

        with patch('worker.circuit_breaker.log_info') as mock_log:
            # Trigger OPEN transition
            for _ in range(3):
                breaker.record_failure()

            # Should have logged OPEN transition
            mock_log.assert_called_once()
            call_args = mock_log.call_args[0][0]
            assert "OPENED" in call_args or "opened" in call_args.lower()
            assert "consecutive failures" in call_args.lower() or "failures" in call_args.lower()

    def test_log_on_close(self):
        """Closing circuit logs appropriate message."""
        breaker = CircuitBreaker(failure_threshold=2)

        # Open circuit
        breaker.record_failure()
        breaker.record_failure()

        # Force HALF_OPEN
        breaker._state = CircuitState.HALF_OPEN

        with patch('worker.circuit_breaker.log_info') as mock_log:
            # Record success to close
            breaker.record_success()

            # Should have logged CLOSED transition
            mock_log.assert_called_once()
            call_args = mock_log.call_args[0][0]
            assert "CLOSED" in call_args or "closed" in call_args.lower()
            assert "recovery" in call_args.lower() or "success" in call_args.lower()

    def test_log_on_half_open(self):
        """Transition to HALF_OPEN logs appropriate message."""
        breaker = CircuitBreaker(failure_threshold=2, recovery_timeout=60.0)

        # Open circuit
        breaker.record_failure()
        breaker.record_failure()

        with patch('worker.circuit_breaker.log_info') as mock_log:
            with patch('worker.circuit_breaker.time') as mock_time:
                breaker._opened_at = 30.0
                mock_time.time.return_value = 100.0

                # Trigger HALF_OPEN transition
                _ = breaker.state

                # Should have logged HALF_OPEN transition
                mock_log.assert_called_once()
                call_args = mock_log.call_args[0][0]
                assert "HALF" in call_args or "half" in call_args.lower()
                assert "timeout" in call_args.lower() or "recovery" in call_args.lower()

    def test_log_on_reopen_from_half_open(self):
        """Reopening from HALF_OPEN logs appropriate message."""
        breaker = CircuitBreaker(failure_threshold=2)

        # Force HALF_OPEN
        breaker._state = CircuitState.HALF_OPEN

        with patch('worker.circuit_breaker.log_info') as mock_log:
            # Record failure to reopen
            breaker.record_failure()

            # Should have logged reopening
            mock_log.assert_called_once()
            call_args = mock_log.call_args[0][0]
            assert "OPENED" in call_args or "opened" in call_args.lower() or "reopen" in call_args.lower()

    def test_no_log_on_failure_below_threshold(self):
        """Failures below threshold don't trigger logging."""
        breaker = CircuitBreaker(failure_threshold=5)

        with patch('worker.circuit_breaker.log_info') as mock_log:
            # Record 1 failure (below threshold)
            breaker.record_failure()

            # Should NOT have logged (no state change)
            mock_log.assert_not_called()


class TestCircuitBreakerFileLocking:
    """Test file locking prevents concurrent state modifications."""

    def test_lock_file_created_on_save(self, tmp_path):
        """Lock file is created when saving state."""
        state_file = str(tmp_path / "cb.json")

        breaker = CircuitBreaker(failure_threshold=2, state_file=state_file)

        # Trigger transition
        breaker.record_failure()
        breaker.record_failure()

        # Lock file should exist
        lock_file = Path(state_file + '.lock')
        assert lock_file.exists()

    def test_concurrent_save_skipped_when_locked(self, tmp_path):
        """Save is skipped gracefully when lock is held."""
        state_file = str(tmp_path / "cb.json")
        lock_file = state_file + '.lock'

        # Acquire exclusive lock manually
        with open(lock_file, 'w') as lf:
            fcntl.flock(lf.fileno(), fcntl.LOCK_EX)

            # Create breaker and trigger transition while lock is held
            breaker = CircuitBreaker(failure_threshold=2, state_file=state_file)

            # Should not raise exception
            breaker.record_failure()
            breaker.record_failure()

            # Breaker should still work in-memory
            assert breaker.state == CircuitState.OPEN

            # fcntl.flock releases on file close

    def test_save_works_after_lock_released(self, tmp_path):
        """Save works correctly after lock is released."""
        state_file = str(tmp_path / "cb.json")
        lock_file = state_file + '.lock'

        # Acquire and release lock
        with open(lock_file, 'w') as lf:
            fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        # Lock released here

        # Create breaker and trigger transition
        breaker = CircuitBreaker(failure_threshold=2, state_file=state_file)
        breaker.record_failure()
        breaker.record_failure()

        # State should be saved
        assert Path(state_file).exists()

        # Verify state can be loaded
        breaker2 = CircuitBreaker(state_file=state_file)
        assert breaker2.state == CircuitState.OPEN
