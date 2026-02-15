"""
Integration tests for circuit breaker behavior.

Tests verify circuit breaker state machine:
- CLOSED: Normal operation, executes all requests
- OPEN: After failure_threshold failures, blocks all requests
- HALF_OPEN: After recovery_timeout, allows one test request
- Transitions based on success/failure

Uses freezegun for time control to test timeout-based transitions
without waiting for real time to elapse.
"""

import pytest
import time
from unittest.mock import Mock, MagicMock, patch
from freezegun import freeze_time


@pytest.mark.integration
class TestCircuitBreakerStateTransitions:
    """Tests for circuit breaker state machine transitions."""

    def test_initial_state_is_closed(self, fresh_circuit_breaker):
        """Circuit breaker starts in CLOSED state."""
        from worker.circuit_breaker import CircuitState

        assert fresh_circuit_breaker.state == CircuitState.CLOSED
        assert fresh_circuit_breaker.can_execute() is True

    def test_opens_after_failure_threshold(self, fresh_circuit_breaker):
        """Circuit opens after 5 consecutive failures."""
        from worker.circuit_breaker import CircuitState

        # Record 4 failures - still closed
        for _ in range(4):
            fresh_circuit_breaker.record_failure()
        assert fresh_circuit_breaker.state == CircuitState.CLOSED

        # 5th failure opens circuit
        fresh_circuit_breaker.record_failure()
        assert fresh_circuit_breaker.state == CircuitState.OPEN
        assert fresh_circuit_breaker.can_execute() is False

    def test_success_resets_failure_count(self, fresh_circuit_breaker):
        """Success in CLOSED state resets failure count."""
        from worker.circuit_breaker import CircuitState

        # Build up failures
        fresh_circuit_breaker.record_failure()
        fresh_circuit_breaker.record_failure()
        fresh_circuit_breaker.record_failure()

        # Success resets
        fresh_circuit_breaker.record_success()

        # Need full threshold again
        fresh_circuit_breaker.record_failure()
        fresh_circuit_breaker.record_failure()
        fresh_circuit_breaker.record_failure()
        fresh_circuit_breaker.record_failure()
        assert fresh_circuit_breaker.state == CircuitState.CLOSED

        # 5th (cumulative) opens
        fresh_circuit_breaker.record_failure()
        assert fresh_circuit_breaker.state == CircuitState.OPEN


@pytest.mark.integration
class TestCircuitBreakerRecoveryWithTimeControl:
    """Tests for circuit breaker recovery using freezegun."""

    @freeze_time("2026-01-01 12:00:00")
    def test_stays_open_before_timeout(self, fresh_circuit_breaker):
        """Circuit stays OPEN before recovery timeout."""
        from worker.circuit_breaker import CircuitState

        # Open the circuit
        for _ in range(5):
            fresh_circuit_breaker.record_failure()

        assert fresh_circuit_breaker.state == CircuitState.OPEN

        # Advance time 30 seconds (less than 60s timeout)
        with freeze_time("2026-01-01 12:00:30"):
            # Still OPEN
            assert fresh_circuit_breaker.state == CircuitState.OPEN
            assert fresh_circuit_breaker.can_execute() is False

    @freeze_time("2026-01-01 12:00:00")
    def test_transitions_to_half_open_after_timeout(self, fresh_circuit_breaker):
        """Circuit transitions to HALF_OPEN after 60s recovery timeout."""
        from worker.circuit_breaker import CircuitState

        # Open the circuit
        for _ in range(5):
            fresh_circuit_breaker.record_failure()

        assert fresh_circuit_breaker.state == CircuitState.OPEN

        # Advance time past 60s timeout
        with freeze_time("2026-01-01 12:01:01"):
            # Should now be HALF_OPEN
            assert fresh_circuit_breaker.state == CircuitState.HALF_OPEN
            assert fresh_circuit_breaker.can_execute() is True

    @freeze_time("2026-01-01 12:00:00")
    def test_success_in_half_open_closes_circuit(self, fresh_circuit_breaker):
        """Success in HALF_OPEN state closes the circuit."""
        from worker.circuit_breaker import CircuitState

        # Open the circuit
        for _ in range(5):
            fresh_circuit_breaker.record_failure()

        # Advance past timeout
        with freeze_time("2026-01-01 12:01:01"):
            assert fresh_circuit_breaker.state == CircuitState.HALF_OPEN

            # Record success
            fresh_circuit_breaker.record_success()

            # Circuit should close
            assert fresh_circuit_breaker.state == CircuitState.CLOSED
            assert fresh_circuit_breaker.can_execute() is True

    @freeze_time("2026-01-01 12:00:00")
    def test_failure_in_half_open_reopens_circuit(self, fresh_circuit_breaker):
        """Failure in HALF_OPEN state reopens the circuit."""
        from worker.circuit_breaker import CircuitState

        # Open the circuit
        for _ in range(5):
            fresh_circuit_breaker.record_failure()

        # Advance past timeout to HALF_OPEN
        with freeze_time("2026-01-01 12:01:01"):
            assert fresh_circuit_breaker.state == CircuitState.HALF_OPEN

            # Record failure
            fresh_circuit_breaker.record_failure()

            # Circuit should reopen
            assert fresh_circuit_breaker.state == CircuitState.OPEN
            assert fresh_circuit_breaker.can_execute() is False


@pytest.mark.integration
class TestCircuitBreakerWithWorker:
    """Tests for circuit breaker integrated with SyncWorker."""

    def test_worker_has_circuit_breaker(self, mock_queue, mock_dlq, mock_config, tmp_path):
        """SyncWorker initializes with circuit breaker."""
        from worker.processor import SyncWorker
        from worker.circuit_breaker import CircuitBreaker

        worker = SyncWorker(
            queue=mock_queue,
            dlq=mock_dlq,
            config=mock_config,
            data_dir=str(tmp_path),
        )

        assert hasattr(worker, 'circuit_breaker')
        assert isinstance(worker.circuit_breaker, CircuitBreaker)

    def test_worker_circuit_opens_after_failures(self, mock_queue, mock_dlq, mock_config, tmp_path):
        """Worker's circuit breaker opens after 5 failures."""
        from worker.processor import SyncWorker
        from worker.circuit_breaker import CircuitState

        worker = SyncWorker(
            queue=mock_queue,
            dlq=mock_dlq,
            config=mock_config,
            data_dir=str(tmp_path),
        )

        # Simulate 5 job failures
        for _ in range(5):
            worker.circuit_breaker.record_failure()

        assert worker.circuit_breaker.state == CircuitState.OPEN

    def test_worker_blocks_when_circuit_open(self, mock_queue, mock_dlq, mock_config, tmp_path):
        """Worker cannot execute when circuit is OPEN."""
        from worker.processor import SyncWorker
        from worker.circuit_breaker import CircuitState

        worker = SyncWorker(
            queue=mock_queue,
            dlq=mock_dlq,
            config=mock_config,
            data_dir=str(tmp_path),
        )

        # Open the circuit
        for _ in range(5):
            worker.circuit_breaker.record_failure()

        # Worker should check can_execute before processing
        assert worker.circuit_breaker.can_execute() is False

    @freeze_time("2026-01-01 12:00:00")
    def test_worker_resumes_after_recovery_timeout(self, mock_queue, mock_dlq, mock_config, tmp_path):
        """Worker can execute after circuit recovers."""
        from worker.processor import SyncWorker
        from worker.circuit_breaker import CircuitState

        worker = SyncWorker(
            queue=mock_queue,
            dlq=mock_dlq,
            config=mock_config,
            data_dir=str(tmp_path),
        )

        # Open the circuit
        for _ in range(5):
            worker.circuit_breaker.record_failure()

        assert worker.circuit_breaker.can_execute() is False

        # Advance past recovery timeout
        with freeze_time("2026-01-01 12:01:01"):
            # Worker can execute again (HALF_OPEN)
            assert worker.circuit_breaker.can_execute() is True


@pytest.mark.integration
class TestCircuitBreakerReset:
    """Tests for manual circuit breaker reset."""

    def test_reset_closes_open_circuit(self, fresh_circuit_breaker):
        """reset() closes an OPEN circuit."""
        from worker.circuit_breaker import CircuitState

        # Open circuit
        for _ in range(5):
            fresh_circuit_breaker.record_failure()

        assert fresh_circuit_breaker.state == CircuitState.OPEN

        # Reset
        fresh_circuit_breaker.reset()

        assert fresh_circuit_breaker.state == CircuitState.CLOSED
        assert fresh_circuit_breaker.can_execute() is True

    def test_reset_clears_failure_count(self, fresh_circuit_breaker):
        """reset() clears accumulated failure count."""
        from worker.circuit_breaker import CircuitState

        # Build up failures (not enough to open)
        fresh_circuit_breaker.record_failure()
        fresh_circuit_breaker.record_failure()
        fresh_circuit_breaker.record_failure()

        # Reset
        fresh_circuit_breaker.reset()

        # Need full threshold again
        fresh_circuit_breaker.record_failure()
        fresh_circuit_breaker.record_failure()
        fresh_circuit_breaker.record_failure()
        fresh_circuit_breaker.record_failure()

        # Still closed (only 4 since reset)
        assert fresh_circuit_breaker.state == CircuitState.CLOSED


@pytest.mark.integration
class TestBackoffDelayWithTimeControl:
    """Tests for exponential backoff delay calculation."""

    def test_delay_increases_with_retry_count(self):
        """Delay range increases exponentially with retry count."""
        from worker.backoff import calculate_delay

        # Get max possible delay for each retry level
        # Using seed to get deterministic results
        delay_0 = calculate_delay(retry_count=0, base=5.0, cap=80.0, jitter_seed=42)
        delay_2 = calculate_delay(retry_count=2, base=5.0, cap=80.0, jitter_seed=42)

        # Max for retry 0: 5 * 2^0 = 5
        # Max for retry 2: 5 * 2^2 = 20
        assert delay_0 <= 5.0
        assert delay_2 <= 20.0

    def test_delay_respects_cap(self):
        """Delay never exceeds cap regardless of retry count."""
        from worker.backoff import calculate_delay

        # Very high retry count
        delay = calculate_delay(retry_count=100, base=5.0, cap=80.0, jitter_seed=42)

        assert delay <= 80.0

    @freeze_time("2026-01-01 12:00:00")
    def test_next_retry_at_calculation(self, mock_queue, mock_dlq, mock_config, tmp_path):
        """next_retry_at is calculated as current time + delay."""
        from worker.processor import SyncWorker, TransientError

        worker = SyncWorker(
            queue=mock_queue,
            dlq=mock_dlq,
            config=mock_config,
            data_dir=str(tmp_path),
        )

        job = {'scene_id': 123, 'data': {'path': '/test.mp4'}}
        error = TransientError("test")

        updated_job = worker._prepare_for_retry(job, error)

        # next_retry_at should be in the future
        current_time = time.time()
        assert updated_job['next_retry_at'] >= current_time


@pytest.mark.integration
class TestCircuitBreakerFullCycle:
    """Test complete circuit breaker lifecycle with time control."""

    @freeze_time("2026-01-01 12:00:00")
    def test_full_cycle_closed_open_half_open_closed(self, fresh_circuit_breaker):
        """Test complete state cycle: CLOSED -> OPEN -> HALF_OPEN -> CLOSED."""
        from worker.circuit_breaker import CircuitState

        # Start CLOSED
        assert fresh_circuit_breaker.state == CircuitState.CLOSED
        assert fresh_circuit_breaker.can_execute() is True

        # 5 failures -> OPEN
        for _ in range(5):
            fresh_circuit_breaker.record_failure()
        assert fresh_circuit_breaker.state == CircuitState.OPEN
        assert fresh_circuit_breaker.can_execute() is False

        # Wait 61s -> HALF_OPEN
        with freeze_time("2026-01-01 12:01:01"):
            assert fresh_circuit_breaker.state == CircuitState.HALF_OPEN
            assert fresh_circuit_breaker.can_execute() is True

            # Success in HALF_OPEN -> CLOSED
            fresh_circuit_breaker.record_success()
            assert fresh_circuit_breaker.state == CircuitState.CLOSED
            assert fresh_circuit_breaker.can_execute() is True

    @freeze_time("2026-01-01 12:00:00")
    def test_full_cycle_closed_open_half_open_open(self, fresh_circuit_breaker):
        """Test failure recovery cycle: CLOSED -> OPEN -> HALF_OPEN -> OPEN."""
        from worker.circuit_breaker import CircuitState

        # Start CLOSED
        assert fresh_circuit_breaker.state == CircuitState.CLOSED

        # 5 failures -> OPEN
        for _ in range(5):
            fresh_circuit_breaker.record_failure()
        assert fresh_circuit_breaker.state == CircuitState.OPEN

        # Wait 61s -> HALF_OPEN
        with freeze_time("2026-01-01 12:01:01"):
            assert fresh_circuit_breaker.state == CircuitState.HALF_OPEN

            # Failure in HALF_OPEN -> OPEN (immediately)
            fresh_circuit_breaker.record_failure()
            assert fresh_circuit_breaker.state == CircuitState.OPEN
            assert fresh_circuit_breaker.can_execute() is False


@pytest.mark.integration
class TestCircuitBreakerWithWorkerFullWorkflow:
    """Test circuit breaker integrated with worker in full workflow scenarios."""

    def test_worker_circuit_breaker_affects_job_processing_decision(self, mock_queue, mock_dlq, mock_config, tmp_path):
        """Worker checks circuit breaker state before processing."""
        from worker.processor import SyncWorker
        from worker.circuit_breaker import CircuitState

        worker = SyncWorker(
            queue=mock_queue,
            dlq=mock_dlq,
            config=mock_config,
            data_dir=str(tmp_path),
        )

        # Initially can process
        assert worker.circuit_breaker.can_execute() is True
        assert worker.circuit_breaker.state == CircuitState.CLOSED

        # Simulate 5 consecutive failures from Plex
        for _ in range(5):
            worker.circuit_breaker.record_failure()

        # Now should block processing
        assert worker.circuit_breaker.can_execute() is False
        assert worker.circuit_breaker.state == CircuitState.OPEN

    @freeze_time("2026-01-01 12:00:00")
    def test_worker_can_recover_after_timeout(self, mock_queue, mock_dlq, mock_config, tmp_path):
        """Worker's circuit breaker recovers after timeout."""
        from worker.processor import SyncWorker
        from worker.circuit_breaker import CircuitState

        worker = SyncWorker(
            queue=mock_queue,
            dlq=mock_dlq,
            config=mock_config,
            data_dir=str(tmp_path),
        )

        # Open the circuit
        for _ in range(5):
            worker.circuit_breaker.record_failure()
        assert worker.circuit_breaker.state == CircuitState.OPEN

        # After 61 seconds, should be HALF_OPEN
        with freeze_time("2026-01-01 12:01:01"):
            assert worker.circuit_breaker.can_execute() is True
            assert worker.circuit_breaker.state == CircuitState.HALF_OPEN

            # Successful job closes circuit
            worker.circuit_breaker.record_success()
            assert worker.circuit_breaker.state == CircuitState.CLOSED
            assert worker.circuit_breaker.can_execute() is True


@pytest.mark.integration
class TestCircuitBreakerPersistenceIntegration:
    """Tests for circuit breaker state persistence across worker instances."""

    def test_state_persists_across_worker_instances(self, mock_queue, mock_dlq, mock_config, tmp_path):
        """Circuit breaker OPEN state survives creating a new worker (simulates plugin restart)."""
        from worker.processor import SyncWorker
        from worker.circuit_breaker import CircuitState

        # First worker instance: open circuit via 5 failures
        worker1 = SyncWorker(
            queue=mock_queue,
            dlq=mock_dlq,
            config=mock_config,
            data_dir=str(tmp_path),
        )
        for _ in range(5):
            worker1.circuit_breaker.record_failure()
        assert worker1.circuit_breaker.state == CircuitState.OPEN

        # Verify state file created
        state_file = tmp_path / "circuit_breaker.json"
        assert state_file.exists()

        # Second worker instance (simulates plugin restart): loads OPEN state
        worker2 = SyncWorker(
            queue=mock_queue,
            dlq=mock_dlq,
            config=mock_config,
            data_dir=str(tmp_path),
        )
        assert worker2.circuit_breaker.state == CircuitState.OPEN
        assert worker2.circuit_breaker.can_execute() is False

    def test_closed_state_persists_after_recovery(self, mock_queue, mock_dlq, mock_config, tmp_path):
        """After recovery (HALF_OPEN -> CLOSED), new worker sees CLOSED state."""
        from worker.processor import SyncWorker
        from worker.circuit_breaker import CircuitState

        # First worker: open circuit
        worker1 = SyncWorker(
            queue=mock_queue,
            dlq=mock_dlq,
            config=mock_config,
            data_dir=str(tmp_path),
        )
        for _ in range(5):
            worker1.circuit_breaker.record_failure()
        assert worker1.circuit_breaker.state == CircuitState.OPEN

        # Force HALF_OPEN and recover
        worker1.circuit_breaker._state = CircuitState.HALF_OPEN
        worker1.circuit_breaker.record_success()
        assert worker1.circuit_breaker.state == CircuitState.CLOSED

        # New worker: should be CLOSED
        worker2 = SyncWorker(
            queue=mock_queue,
            dlq=mock_dlq,
            config=mock_config,
            data_dir=str(tmp_path),
        )
        assert worker2.circuit_breaker.state == CircuitState.CLOSED
        assert worker2.circuit_breaker.can_execute() is True

    def test_no_state_file_without_data_dir(self, mock_queue, mock_dlq, mock_config):
        """Worker without data_dir creates circuit breaker without persistence."""
        from worker.processor import SyncWorker

        worker = SyncWorker(
            queue=mock_queue,
            dlq=mock_dlq,
            config=mock_config,
            data_dir=None,
        )
        assert worker.circuit_breaker._state_file is None

    @freeze_time("2026-01-01 12:00:00")
    def test_half_open_state_persists_across_restart(self, mock_queue, mock_dlq, mock_config, tmp_path):
        """HALF_OPEN state persists, allowing recovery test on restart."""
        from worker.processor import SyncWorker
        from worker.circuit_breaker import CircuitState

        # First worker: open circuit
        worker1 = SyncWorker(
            queue=mock_queue,
            dlq=mock_dlq,
            config=mock_config,
            data_dir=str(tmp_path),
        )
        for _ in range(5):
            worker1.circuit_breaker.record_failure()

        # Advance time past recovery timeout to trigger HALF_OPEN
        with freeze_time("2026-01-01 12:01:01"):
            assert worker1.circuit_breaker.state == CircuitState.HALF_OPEN

            # New worker should load HALF_OPEN state
            worker2 = SyncWorker(
                queue=mock_queue,
                dlq=mock_dlq,
                config=mock_config,
                data_dir=str(tmp_path),
            )
            assert worker2.circuit_breaker.state == CircuitState.HALF_OPEN
            assert worker2.circuit_breaker.can_execute() is True

    def test_state_file_location(self, mock_queue, mock_dlq, mock_config, tmp_path):
        """State file is stored in data_dir as circuit_breaker.json."""
        from worker.processor import SyncWorker

        worker = SyncWorker(
            queue=mock_queue,
            dlq=mock_dlq,
            config=mock_config,
            data_dir=str(tmp_path),
        )

        expected_path = str(tmp_path / "circuit_breaker.json")
        assert worker.circuit_breaker._state_file == expected_path
