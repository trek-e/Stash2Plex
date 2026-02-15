"""
Recovery scheduler for automatic Plex outage recovery detection.

Since Stash plugins are invoked per-event (not long-running), the scheduler
uses a check-on-invocation pattern: each plugin run checks if a health probe
is due based on persisted state in recovery_state.json.

When health checks succeed during HALF_OPEN state, the scheduler orchestrates
circuit breaker transitions to close the circuit and allow queue drain.
"""

import json
import os
import time
from dataclasses import dataclass, asdict
from typing import Optional

from shared.log import create_logger
from worker.circuit_breaker import CircuitBreaker, CircuitState

_, log_debug, log_info, _, _ = create_logger("Recovery")


@dataclass
class RecoveryState:
    """Persisted state for recovery detection scheduling."""
    last_check_time: float = 0.0           # time.time() of last health check
    consecutive_successes: int = 0         # consecutive successful checks
    consecutive_failures: int = 0          # consecutive failed checks
    last_recovery_time: float = 0.0        # when circuit last closed after outage
    recovery_count: int = 0                # total recoveries detected
    recovery_started_at: float = 0.0       # when recovery period began (0.0 = not in recovery)


class RecoveryScheduler:
    """Manages recovery detection scheduling via persisted state.

    NOT a timer/thread. On each plugin invocation, call should_check_recovery()
    to check if a health probe is due based on circuit state and last check time.
    """

    STATE_FILE = 'recovery_state.json'

    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self.state_path = os.path.join(data_dir, self.STATE_FILE)

    def load_state(self) -> RecoveryState:
        """Load recovery state from disk."""
        try:
            if os.path.exists(self.state_path):
                with open(self.state_path, 'r') as f:
                    data = json.load(f)
                return RecoveryState(**data)
        except (json.JSONDecodeError, TypeError, KeyError) as e:
            log_debug(f"Failed to load recovery state, using defaults: {e}")
        return RecoveryState()

    def save_state(self, state: RecoveryState) -> None:
        """Save recovery state to disk atomically."""
        tmp_path = self.state_path + '.tmp'
        try:
            with open(tmp_path, 'w') as f:
                json.dump(asdict(state), f, indent=2)
            os.replace(tmp_path, self.state_path)
        except OSError as e:
            log_debug(f"Failed to save recovery state: {e}")

    def should_check_recovery(self, circuit_state: CircuitState, now: Optional[float] = None) -> bool:
        """Check if recovery health probe is due.

        Args:
            circuit_state: Current circuit breaker state
            now: Current time (default: time.time()). For testing.

        Returns:
            True if health probe should run now.
        """
        # No recovery needed when circuit is closed
        if circuit_state == CircuitState.CLOSED:
            return False

        # Recovery detection runs during OPEN or HALF_OPEN states
        if now is None:
            now = time.time()

        state = self.load_state()
        elapsed = now - state.last_check_time

        # Check every 5 seconds during outage
        return elapsed >= 5.0

    def record_health_check(self, success: bool, latency_ms: float, circuit_breaker: CircuitBreaker) -> None:
        """Record a health check result and update circuit breaker state.

        Args:
            success: Whether health check succeeded
            latency_ms: Health check latency in milliseconds
            circuit_breaker: CircuitBreaker instance to update
        """
        state = self.load_state()
        state.last_check_time = time.time()

        if success:
            # Update consecutive counters
            state.consecutive_successes += 1
            state.consecutive_failures = 0

            # If circuit is HALF_OPEN, attempt recovery
            if circuit_breaker.state == CircuitState.HALF_OPEN:
                circuit_breaker.record_success()

                # Check if circuit transitioned to CLOSED (recovery complete)
                if circuit_breaker.state == CircuitState.CLOSED:
                    state.recovery_count += 1
                    state.last_recovery_time = time.time()
                    state.recovery_started_at = time.time()
                    state.consecutive_successes = 0
                    log_info(f"Recovery detected: Plex is back online (recovery #{state.recovery_count})")
            elif circuit_breaker.state == CircuitState.OPEN:
                # Health check passed but circuit hasn't transitioned to HALF_OPEN yet
                log_debug("Health check passed but circuit still OPEN (awaiting recovery_timeout)")

        else:
            # Update consecutive counters
            state.consecutive_failures += 1
            state.consecutive_successes = 0

            # If circuit is HALF_OPEN, failed recovery attempt
            if circuit_breaker.state == CircuitState.HALF_OPEN:
                circuit_breaker.record_failure()

            # Log at debug level (expected during outage)
            log_debug(f"Health check failed during {circuit_breaker.state.value} state")

        self.save_state(state)

    def clear_recovery_period(self) -> None:
        """Clear recovery period state.

        Called when graduated rate limiting ramp completes.
        Sets recovery_started_at to 0.0 and persists state.
        """
        state = self.load_state()
        state.recovery_started_at = 0.0
        self.save_state(state)


__all__ = ['RecoveryScheduler', 'RecoveryState']
