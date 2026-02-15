"""
Circuit breaker pattern for resilient Plex API calls.

Prevents retry exhaustion during Plex outages by pausing
job processing when consecutive failures occur.

States:
- CLOSED: Normal operation, count failures
- OPEN: Block all requests until recovery timeout
- HALF_OPEN: Allow one test request to check recovery
"""

import time
import json
import os
import fcntl
from enum import Enum
from typing import Optional
from shared.log import create_logger

log_trace, log_debug, log_info, log_warn, log_error = create_logger("CircuitBreaker")


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """
    Circuit breaker state machine.

    Tracks consecutive failures and blocks execution when
    a failure threshold is reached. Allows recovery testing
    after a timeout period.

    Args:
        failure_threshold: Consecutive failures before opening (default: 5)
        recovery_timeout: Seconds before transitioning to HALF_OPEN (default: 60.0)
        success_threshold: Successes in HALF_OPEN to close (default: 1)
        state_file: Optional path to persist state (default: None for no persistence)

    Usage:
        breaker = CircuitBreaker()

        if breaker.can_execute():
            try:
                result = call_plex_api()
                breaker.record_success()
            except Exception:
                breaker.record_failure()
        else:
            # Circuit is open, skip execution
            pass
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        success_threshold: int = 1,
        state_file: Optional[str] = None,
        outage_history: Optional['OutageHistory'] = None
    ):
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._success_threshold = success_threshold
        self._state_file = state_file
        self._outage_history = outage_history

        # Internal state
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._opened_at: float | None = None

        # Load persisted state if available
        if self._state_file:
            self._load_state()

    def _load_state(self) -> None:
        """Load circuit breaker state from disk."""
        if self._state_file is None:
            return

        if not os.path.exists(self._state_file):
            return

        try:
            with open(self._state_file, 'r') as f:
                data = json.load(f)

            # Validate all required keys exist before loading
            required_keys = ['state', 'failure_count', 'success_count', 'opened_at']
            for key in required_keys:
                if key not in data:
                    raise KeyError(f"Missing required key: {key}")

            self._state = CircuitState(data['state'])
            self._failure_count = data['failure_count']
            self._success_count = data['success_count']
            self._opened_at = data['opened_at']

            log_debug(f"Circuit breaker state loaded: {self._state.value}")

        except (json.JSONDecodeError, TypeError, KeyError, ValueError) as e:
            log_warn(f"Circuit breaker state corrupted, using defaults: {e}")
            # Reset to defaults on any error
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            self._opened_at = None

    def _save_state(self) -> None:
        """Save circuit breaker state to disk atomically."""
        if self._state_file is None:
            return

        state_data = {
            'state': self._state.value,
            'failure_count': self._failure_count,
            'success_count': self._success_count,
            'opened_at': self._opened_at
        }

        tmp_path = self._state_file + '.tmp'
        try:
            with open(tmp_path, 'w') as f:
                json.dump(state_data, f, indent=2)
            os.replace(tmp_path, self._state_file)
        except OSError as e:
            log_debug(f"Failed to save circuit breaker state: {e}")

    def _save_state_locked(self) -> None:
        """Save circuit breaker state with file locking."""
        if self._state_file is None:
            return

        lock_path = self._state_file + '.lock'

        try:
            # Open lock file and acquire exclusive lock
            with open(lock_path, 'w') as lock_file:
                try:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    self._save_state()
                except BlockingIOError:
                    log_trace("Circuit breaker state save skipped (locked)")
                finally:
                    try:
                        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                    except OSError:
                        pass
        except OSError as e:
            log_debug(f"Failed to acquire lock for circuit breaker state: {e}")

    @property
    def state(self) -> CircuitState:
        """Current circuit state (may transition to HALF_OPEN if timeout elapsed)."""
        if self._state == CircuitState.OPEN and self._opened_at is not None:
            if time.time() - self._opened_at >= self._recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                self._success_count = 0
                log_info(f"Circuit breaker entering HALF_OPEN state after {self._recovery_timeout}s timeout")
                self._save_state_locked()
        return self._state

    def can_execute(self) -> bool:
        """
        Check if execution is allowed.

        Returns:
            True if circuit is CLOSED or HALF_OPEN, False if OPEN
        """
        current_state = self.state  # Property call handles OPEN -> HALF_OPEN transition
        return current_state != CircuitState.OPEN

    def record_success(self) -> None:
        """
        Record a successful execution.

        In CLOSED state: resets failure count.
        In HALF_OPEN state: increments success count, closes if threshold reached.
        """
        if self._state == CircuitState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self._success_threshold:
                self._close()
            else:
                # Success recorded but threshold not yet reached
                self._save_state_locked()
        else:
            # CLOSED state - just reset failure count
            self._failure_count = 0
            self._save_state_locked()

    def record_failure(self) -> None:
        """
        Record a failed execution.

        In CLOSED state: increments failure count, opens if threshold reached.
        In HALF_OPEN state: immediately reopens the circuit.
        """
        if self._state == CircuitState.HALF_OPEN:
            # HALF_OPEN failure -> reopen immediately
            self._open()
        else:
            # CLOSED state - count failures
            self._failure_count += 1
            if self._failure_count >= self._failure_threshold:
                self._open()
            else:
                # Failure recorded but threshold not yet reached
                self._save_state_locked()

    def reset(self) -> None:
        """
        Force reset to CLOSED state.

        Useful for testing or manual recovery.
        """
        log_info("Circuit breaker manually reset to CLOSED")
        self._close()

    def _open(self) -> None:
        """Transition to OPEN state."""
        self._state = CircuitState.OPEN
        self._opened_at = time.time()
        self._failure_count = 0
        self._success_count = 0
        log_info(f"Circuit breaker OPENED after {self._failure_threshold} consecutive failures")
        self._save_state_locked()

        # Record outage start
        if self._outage_history is not None:
            self._outage_history.record_outage_start(self._opened_at)

    def _close(self) -> None:
        """Transition to CLOSED state."""
        self._state = CircuitState.CLOSED
        self._opened_at = None
        self._failure_count = 0
        self._success_count = 0
        log_info("Circuit breaker CLOSED after successful recovery")
        self._save_state_locked()


__all__ = ['CircuitBreaker', 'CircuitState']
