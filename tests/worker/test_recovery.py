"""
Tests for RecoveryScheduler - TDD implementation.

RecoveryScheduler manages recovery detection scheduling for Plex outages
using check-on-invocation pattern with persisted state.
"""

import json
import os
import time
import tempfile
import pytest
from unittest.mock import Mock, MagicMock

from worker.recovery import RecoveryScheduler, RecoveryState
from worker.circuit_breaker import CircuitBreaker, CircuitState


@pytest.fixture
def temp_dir():
    """Create temporary directory for test data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def scheduler(temp_dir):
    """Create RecoveryScheduler instance for testing."""
    return RecoveryScheduler(temp_dir)


@pytest.fixture
def mock_circuit_breaker():
    """Create mock circuit breaker."""
    breaker = Mock(spec=CircuitBreaker)
    breaker.state = CircuitState.CLOSED
    return breaker


class TestRecoveryState:
    """Test RecoveryState dataclass."""

    def test_default_values(self):
        """RecoveryState has correct default values."""
        state = RecoveryState()
        assert state.last_check_time == 0.0
        assert state.consecutive_successes == 0
        assert state.consecutive_failures == 0
        assert state.last_recovery_time == 0.0
        assert state.recovery_count == 0

    def test_custom_values(self):
        """RecoveryState accepts custom values."""
        state = RecoveryState(
            last_check_time=1234567890.0,
            consecutive_successes=3,
            consecutive_failures=2,
            last_recovery_time=1234567800.0,
            recovery_count=5
        )
        assert state.last_check_time == 1234567890.0
        assert state.consecutive_successes == 3
        assert state.consecutive_failures == 2
        assert state.last_recovery_time == 1234567800.0
        assert state.recovery_count == 5


class TestRecoverySchedulerInit:
    """Test RecoveryScheduler initialization."""

    def test_init_sets_paths(self, temp_dir):
        """__init__ sets data_dir and state_path correctly."""
        scheduler = RecoveryScheduler(temp_dir)
        assert scheduler.data_dir == temp_dir
        expected_path = os.path.join(temp_dir, 'recovery_state.json')
        assert scheduler.state_path == expected_path

    def test_state_file_constant(self):
        """STATE_FILE class constant is correct."""
        assert RecoveryScheduler.STATE_FILE == 'recovery_state.json'


class TestLoadState:
    """Test load_state functionality."""

    def test_load_state_missing_file(self, scheduler):
        """load_state returns default RecoveryState when file missing."""
        state = scheduler.load_state()
        assert isinstance(state, RecoveryState)
        assert state.last_check_time == 0.0
        assert state.recovery_count == 0

    def test_load_state_valid_json(self, scheduler, temp_dir):
        """load_state loads valid JSON correctly."""
        state_data = {
            'last_check_time': 1234567890.0,
            'consecutive_successes': 2,
            'consecutive_failures': 1,
            'last_recovery_time': 1234567800.0,
            'recovery_count': 3
        }
        state_path = os.path.join(temp_dir, 'recovery_state.json')
        with open(state_path, 'w') as f:
            json.dump(state_data, f)

        state = scheduler.load_state()
        assert state.last_check_time == 1234567890.0
        assert state.consecutive_successes == 2
        assert state.consecutive_failures == 1
        assert state.last_recovery_time == 1234567800.0
        assert state.recovery_count == 3

    def test_load_state_corrupted_json(self, scheduler, temp_dir):
        """load_state returns defaults when JSON corrupted."""
        state_path = os.path.join(temp_dir, 'recovery_state.json')
        with open(state_path, 'w') as f:
            f.write("{corrupted json")

        state = scheduler.load_state()
        assert isinstance(state, RecoveryState)
        assert state.last_check_time == 0.0

    def test_load_state_invalid_type(self, scheduler, temp_dir):
        """load_state returns defaults when JSON has wrong type."""
        state_path = os.path.join(temp_dir, 'recovery_state.json')
        with open(state_path, 'w') as f:
            json.dump(["not", "a", "dict"], f)

        state = scheduler.load_state()
        assert isinstance(state, RecoveryState)
        assert state.last_check_time == 0.0

    def test_load_state_missing_fields(self, scheduler, temp_dir):
        """load_state uses defaults for missing fields (dataclass behavior)."""
        state_path = os.path.join(temp_dir, 'recovery_state.json')
        with open(state_path, 'w') as f:
            json.dump({'last_check_time': 123.0}, f)  # Missing other fields

        state = scheduler.load_state()
        assert isinstance(state, RecoveryState)
        assert state.last_check_time == 123.0  # Provided field
        assert state.consecutive_successes == 0  # Default for missing field
        assert state.recovery_count == 0  # Default for missing field


class TestSaveState:
    """Test save_state functionality."""

    def test_save_state_creates_file(self, scheduler, temp_dir):
        """save_state creates recovery_state.json."""
        state = RecoveryState(
            last_check_time=1234567890.0,
            consecutive_successes=2,
            recovery_count=5
        )
        scheduler.save_state(state)

        state_path = os.path.join(temp_dir, 'recovery_state.json')
        assert os.path.exists(state_path)

    def test_save_state_atomic_write(self, scheduler, temp_dir):
        """save_state uses atomic write with os.replace."""
        state = RecoveryState(last_check_time=1234567890.0)
        scheduler.save_state(state)

        # Verify tmp file doesn't exist after save
        tmp_path = os.path.join(temp_dir, 'recovery_state.json.tmp')
        assert not os.path.exists(tmp_path)

        # Verify final file exists
        state_path = os.path.join(temp_dir, 'recovery_state.json')
        assert os.path.exists(state_path)

    def test_save_state_roundtrip(self, scheduler):
        """save_state then load_state preserves data."""
        original = RecoveryState(
            last_check_time=1234567890.0,
            consecutive_successes=3,
            consecutive_failures=1,
            last_recovery_time=1234567800.0,
            recovery_count=7
        )
        scheduler.save_state(original)

        loaded = scheduler.load_state()
        assert loaded.last_check_time == original.last_check_time
        assert loaded.consecutive_successes == original.consecutive_successes
        assert loaded.consecutive_failures == original.consecutive_failures
        assert loaded.last_recovery_time == original.last_recovery_time
        assert loaded.recovery_count == original.recovery_count

    def test_save_state_handles_os_error(self, scheduler, temp_dir):
        """save_state handles OSError gracefully."""
        # Make directory read-only to trigger OSError
        os.chmod(temp_dir, 0o444)

        try:
            state = RecoveryState(last_check_time=123.0)
            # Should not raise exception
            scheduler.save_state(state)
        finally:
            # Restore permissions
            os.chmod(temp_dir, 0o755)


class TestShouldCheckRecovery:
    """Test should_check_recovery logic."""

    def test_should_check_closed_circuit(self, scheduler, mock_circuit_breaker):
        """should_check_recovery returns False when circuit is CLOSED."""
        mock_circuit_breaker.state = CircuitState.CLOSED
        assert scheduler.should_check_recovery(CircuitState.CLOSED) is False

    def test_should_check_open_too_soon(self, scheduler, temp_dir):
        """should_check_recovery returns False when OPEN but interval not elapsed."""
        # Save state with recent check
        state = RecoveryState(last_check_time=1000.0)
        scheduler.save_state(state)

        # Check at 1003.0 (only 3 seconds later)
        result = scheduler.should_check_recovery(CircuitState.OPEN, now=1003.0)
        assert result is False

    def test_should_check_open_interval_elapsed(self, scheduler, temp_dir):
        """should_check_recovery returns True when OPEN and 5s elapsed."""
        # Save state with old check
        state = RecoveryState(last_check_time=1000.0)
        scheduler.save_state(state)

        # Check at 1005.0 (exactly 5 seconds later)
        result = scheduler.should_check_recovery(CircuitState.OPEN, now=1005.0)
        assert result is True

    def test_should_check_open_first_time(self, scheduler):
        """should_check_recovery returns True when OPEN and never checked."""
        # No state file exists, last_check_time defaults to 0.0
        result = scheduler.should_check_recovery(CircuitState.OPEN, now=1000.0)
        assert result is True

    def test_should_check_half_open_interval_elapsed(self, scheduler, temp_dir):
        """should_check_recovery returns True when HALF_OPEN and 5s elapsed."""
        state = RecoveryState(last_check_time=1000.0)
        scheduler.save_state(state)

        result = scheduler.should_check_recovery(CircuitState.HALF_OPEN, now=1005.0)
        assert result is True

    def test_should_check_half_open_too_soon(self, scheduler, temp_dir):
        """should_check_recovery returns False when HALF_OPEN but too soon."""
        state = RecoveryState(last_check_time=1000.0)
        scheduler.save_state(state)

        result = scheduler.should_check_recovery(CircuitState.HALF_OPEN, now=1003.0)
        assert result is False

    def test_should_check_uses_time_time_by_default(self, scheduler):
        """should_check_recovery uses time.time() when now not provided."""
        # Create old state
        state = RecoveryState(last_check_time=time.time() - 10.0)
        scheduler.save_state(state)

        # Should return True since 10 seconds elapsed
        result = scheduler.should_check_recovery(CircuitState.OPEN)
        assert result is True


class TestRecordHealthCheck:
    """Test record_health_check functionality."""

    def test_record_success_updates_last_check_time(self, scheduler, temp_dir, mock_circuit_breaker):
        """record_health_check updates last_check_time on success."""
        mock_circuit_breaker.state = CircuitState.OPEN

        scheduler.record_health_check(success=True, latency_ms=50.0, circuit_breaker=mock_circuit_breaker)

        state = scheduler.load_state()
        assert state.last_check_time > 0.0

    def test_record_success_increments_consecutive_successes(self, scheduler, temp_dir, mock_circuit_breaker):
        """record_health_check increments consecutive_successes on success."""
        mock_circuit_breaker.state = CircuitState.OPEN

        scheduler.record_health_check(success=True, latency_ms=50.0, circuit_breaker=mock_circuit_breaker)
        state = scheduler.load_state()
        assert state.consecutive_successes == 1

        scheduler.record_health_check(success=True, latency_ms=50.0, circuit_breaker=mock_circuit_breaker)
        state = scheduler.load_state()
        assert state.consecutive_successes == 2

    def test_record_success_resets_consecutive_failures(self, scheduler, temp_dir, mock_circuit_breaker):
        """record_health_check resets consecutive_failures on success."""
        # Set up state with failures
        state = RecoveryState(consecutive_failures=3)
        scheduler.save_state(state)

        mock_circuit_breaker.state = CircuitState.OPEN
        scheduler.record_health_check(success=True, latency_ms=50.0, circuit_breaker=mock_circuit_breaker)

        state = scheduler.load_state()
        assert state.consecutive_failures == 0

    def test_record_success_half_open_calls_record_success(self, scheduler, temp_dir, mock_circuit_breaker):
        """record_health_check calls circuit_breaker.record_success() in HALF_OPEN."""
        mock_circuit_breaker.state = CircuitState.HALF_OPEN

        scheduler.record_health_check(success=True, latency_ms=50.0, circuit_breaker=mock_circuit_breaker)

        mock_circuit_breaker.record_success.assert_called_once()

    def test_record_success_open_no_record_success_call(self, scheduler, temp_dir, mock_circuit_breaker):
        """record_health_check does NOT call record_success() when circuit is OPEN."""
        mock_circuit_breaker.state = CircuitState.OPEN

        scheduler.record_health_check(success=True, latency_ms=50.0, circuit_breaker=mock_circuit_breaker)

        mock_circuit_breaker.record_success.assert_not_called()

    def test_record_success_circuit_closes_logs_recovery(self, scheduler, temp_dir, mock_circuit_breaker):
        """record_health_check logs recovery when circuit transitions to CLOSED."""
        # Circuit starts HALF_OPEN, transitions to CLOSED after record_success
        mock_circuit_breaker.state = CircuitState.HALF_OPEN

        # After record_success is called, circuit transitions to CLOSED
        def transition_to_closed():
            mock_circuit_breaker.state = CircuitState.CLOSED

        mock_circuit_breaker.record_success.side_effect = transition_to_closed

        scheduler.record_health_check(success=True, latency_ms=50.0, circuit_breaker=mock_circuit_breaker)

        state = scheduler.load_state()
        assert state.recovery_count == 1
        assert state.last_recovery_time > 0.0
        assert state.consecutive_successes == 0  # Reset after recovery

    def test_record_success_multiple_recoveries(self, scheduler, temp_dir, mock_circuit_breaker):
        """record_health_check increments recovery_count on each recovery."""
        # Simulate first recovery
        mock_circuit_breaker.state = CircuitState.HALF_OPEN
        def transition_to_closed():
            mock_circuit_breaker.state = CircuitState.CLOSED
        mock_circuit_breaker.record_success.side_effect = transition_to_closed

        scheduler.record_health_check(success=True, latency_ms=50.0, circuit_breaker=mock_circuit_breaker)
        state = scheduler.load_state()
        assert state.recovery_count == 1

        # Simulate second outage and recovery
        mock_circuit_breaker.state = CircuitState.HALF_OPEN
        mock_circuit_breaker.record_success.side_effect = transition_to_closed

        scheduler.record_health_check(success=True, latency_ms=50.0, circuit_breaker=mock_circuit_breaker)
        state = scheduler.load_state()
        assert state.recovery_count == 2

    def test_record_failure_increments_consecutive_failures(self, scheduler, temp_dir, mock_circuit_breaker):
        """record_health_check increments consecutive_failures on failure."""
        mock_circuit_breaker.state = CircuitState.OPEN

        scheduler.record_health_check(success=False, latency_ms=0.0, circuit_breaker=mock_circuit_breaker)
        state = scheduler.load_state()
        assert state.consecutive_failures == 1

        scheduler.record_health_check(success=False, latency_ms=0.0, circuit_breaker=mock_circuit_breaker)
        state = scheduler.load_state()
        assert state.consecutive_failures == 2

    def test_record_failure_resets_consecutive_successes(self, scheduler, temp_dir, mock_circuit_breaker):
        """record_health_check resets consecutive_successes on failure."""
        # Set up state with successes
        state = RecoveryState(consecutive_successes=3)
        scheduler.save_state(state)

        mock_circuit_breaker.state = CircuitState.OPEN
        scheduler.record_health_check(success=False, latency_ms=0.0, circuit_breaker=mock_circuit_breaker)

        state = scheduler.load_state()
        assert state.consecutive_successes == 0

    def test_record_failure_half_open_calls_record_failure(self, scheduler, temp_dir, mock_circuit_breaker):
        """record_health_check calls circuit_breaker.record_failure() in HALF_OPEN."""
        mock_circuit_breaker.state = CircuitState.HALF_OPEN

        scheduler.record_health_check(success=False, latency_ms=0.0, circuit_breaker=mock_circuit_breaker)

        mock_circuit_breaker.record_failure.assert_called_once()

    def test_record_failure_open_no_record_failure_call(self, scheduler, temp_dir, mock_circuit_breaker):
        """record_health_check does NOT call record_failure() when circuit is OPEN."""
        mock_circuit_breaker.state = CircuitState.OPEN

        scheduler.record_health_check(success=False, latency_ms=0.0, circuit_breaker=mock_circuit_breaker)

        mock_circuit_breaker.record_failure.assert_not_called()

    def test_record_failure_updates_last_check_time(self, scheduler, temp_dir, mock_circuit_breaker):
        """record_health_check updates last_check_time on failure."""
        mock_circuit_breaker.state = CircuitState.OPEN

        scheduler.record_health_check(success=False, latency_ms=0.0, circuit_breaker=mock_circuit_breaker)

        state = scheduler.load_state()
        assert state.last_check_time > 0.0

    def test_record_health_check_saves_state(self, scheduler, temp_dir, mock_circuit_breaker):
        """record_health_check persists state to disk."""
        mock_circuit_breaker.state = CircuitState.OPEN

        scheduler.record_health_check(success=True, latency_ms=50.0, circuit_breaker=mock_circuit_breaker)

        # Create new scheduler instance to verify persistence
        new_scheduler = RecoveryScheduler(temp_dir)
        state = new_scheduler.load_state()
        assert state.consecutive_successes == 1


class TestEdgeCases:
    """Test edge cases and integration scenarios."""

    def test_consecutive_counters_alternate(self, scheduler, temp_dir, mock_circuit_breaker):
        """Consecutive counters alternate correctly between success/failure."""
        mock_circuit_breaker.state = CircuitState.OPEN

        # Success -> Failure -> Success
        scheduler.record_health_check(success=True, latency_ms=50.0, circuit_breaker=mock_circuit_breaker)
        state = scheduler.load_state()
        assert state.consecutive_successes == 1
        assert state.consecutive_failures == 0

        scheduler.record_health_check(success=False, latency_ms=0.0, circuit_breaker=mock_circuit_breaker)
        state = scheduler.load_state()
        assert state.consecutive_successes == 0
        assert state.consecutive_failures == 1

        scheduler.record_health_check(success=True, latency_ms=50.0, circuit_breaker=mock_circuit_breaker)
        state = scheduler.load_state()
        assert state.consecutive_successes == 1
        assert state.consecutive_failures == 0

    def test_recovery_only_counted_on_transition_to_closed(self, scheduler, temp_dir, mock_circuit_breaker):
        """Recovery is only counted when circuit actually transitions to CLOSED."""
        # Multiple successes in HALF_OPEN don't count as multiple recoveries
        mock_circuit_breaker.state = CircuitState.HALF_OPEN

        # First success doesn't close circuit
        scheduler.record_health_check(success=True, latency_ms=50.0, circuit_breaker=mock_circuit_breaker)
        state = scheduler.load_state()
        assert state.recovery_count == 0

        # Second success closes circuit
        def transition_to_closed():
            mock_circuit_breaker.state = CircuitState.CLOSED
        mock_circuit_breaker.record_success.side_effect = transition_to_closed

        scheduler.record_health_check(success=True, latency_ms=50.0, circuit_breaker=mock_circuit_breaker)
        state = scheduler.load_state()
        assert state.recovery_count == 1

    def test_check_interval_boundary(self, scheduler, temp_dir):
        """should_check_recovery respects exact 5.0s boundary."""
        state = RecoveryState(last_check_time=1000.0)
        scheduler.save_state(state)

        # Exactly at boundary
        assert scheduler.should_check_recovery(CircuitState.OPEN, now=1005.0) is True

        # Just before boundary
        assert scheduler.should_check_recovery(CircuitState.OPEN, now=1004.999) is False

        # Just after boundary
        assert scheduler.should_check_recovery(CircuitState.OPEN, now=1005.001) is True


class TestRecoveryOutageHistory:
    """Test outage history integration with recovery scheduler."""

    def test_recovery_records_outage_end(self, temp_dir, mock_circuit_breaker):
        """record_health_check calls outage_history.record_outage_end on recovery."""
        from unittest.mock import Mock

        mock_history = Mock()
        scheduler = RecoveryScheduler(temp_dir, outage_history=mock_history)

        # Simulate successful recovery (HALF_OPEN -> CLOSED transition)
        mock_circuit_breaker.state = CircuitState.HALF_OPEN

        def transition_to_closed():
            mock_circuit_breaker.state = CircuitState.CLOSED
        mock_circuit_breaker.record_success.side_effect = transition_to_closed

        scheduler.record_health_check(success=True, latency_ms=50.0, circuit_breaker=mock_circuit_breaker)

        # Should have called record_outage_end
        mock_history.record_outage_end.assert_called_once()
        call_args = mock_history.record_outage_end.call_args[0]
        assert len(call_args) == 1

        # Verify it was called with last_recovery_time
        state = scheduler.load_state()
        assert call_args[0] == state.last_recovery_time

    def test_recovery_without_outage_history(self, temp_dir, mock_circuit_breaker):
        """Recovery without outage_history doesn't raise error."""
        scheduler = RecoveryScheduler(temp_dir, outage_history=None)

        mock_circuit_breaker.state = CircuitState.HALF_OPEN

        def transition_to_closed():
            mock_circuit_breaker.state = CircuitState.CLOSED
        mock_circuit_breaker.record_success.side_effect = transition_to_closed

        # Should not raise exception
        scheduler.record_health_check(success=True, latency_ms=50.0, circuit_breaker=mock_circuit_breaker)

    def test_no_outage_end_when_circuit_stays_open(self, temp_dir, mock_circuit_breaker):
        """record_health_check doesn't call record_outage_end when circuit stays OPEN."""
        from unittest.mock import Mock

        mock_history = Mock()
        scheduler = RecoveryScheduler(temp_dir, outage_history=mock_history)

        mock_circuit_breaker.state = CircuitState.OPEN

        scheduler.record_health_check(success=False, latency_ms=0.0, circuit_breaker=mock_circuit_breaker)

        # Should NOT have called record_outage_end
        mock_history.record_outage_end.assert_not_called()

    def test_no_outage_end_when_circuit_stays_half_open(self, temp_dir, mock_circuit_breaker):
        """record_health_check doesn't call record_outage_end when circuit stays HALF_OPEN."""
        from unittest.mock import Mock

        mock_history = Mock()
        scheduler = RecoveryScheduler(temp_dir, outage_history=mock_history)

        # Circuit is HALF_OPEN but doesn't transition to CLOSED
        mock_circuit_breaker.state = CircuitState.HALF_OPEN

        # No side effect - circuit stays HALF_OPEN
        scheduler.record_health_check(success=True, latency_ms=50.0, circuit_breaker=mock_circuit_breaker)

        # Should NOT have called record_outage_end (circuit didn't close)
        mock_history.record_outage_end.assert_not_called()
