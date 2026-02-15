"""
Recovery rate limiter for graduated queue drain after Plex outage recovery.

Uses token bucket algorithm with graduated rate scaling to prevent
overwhelming a just-recovered Plex server. Error rate monitoring
triggers adaptive backoff if failures spike during recovery.
"""

import time
from typing import Optional

from shared.log import create_logger

_, log_debug, log_info, log_warn, _ = create_logger("RateLimiter")


class RecoveryRateLimiter:
    """
    Graduated rate limiter for post-recovery queue drain.

    Implements token bucket algorithm with linear rate scaling from initial_rate
    to target_rate over ramp_duration. Monitors error rate and applies adaptive
    backoff if failures exceed threshold.

    Example:
        >>> limiter = RecoveryRateLimiter(initial_rate=5.0, target_rate=20.0, ramp_duration=300.0)
        >>> limiter.start_recovery_period()
        >>> wait_time = limiter.should_wait()
        >>> if wait_time > 0:
        ...     time.sleep(wait_time)
        >>> # Process job
        >>> limiter.record_result(success=True)
    """

    def __init__(
        self,
        initial_rate: float = 5.0,
        target_rate: float = 20.0,
        ramp_duration: float = 300.0,
        error_threshold: float = 0.3,
        error_window: float = 60.0,
    ):
        """
        Initialize recovery rate limiter.

        Args:
            initial_rate: Starting rate in jobs/second (default 5.0)
            target_rate: Full rate in jobs/second (default 20.0)
            ramp_duration: Seconds to reach full rate (default 300.0 = 5 minutes)
            error_threshold: Error rate triggering backoff (default 0.3 = 30%)
            error_window: Time window for error rate calculation in seconds (default 60.0)
        """
        self.initial_rate = initial_rate
        self.target_rate = target_rate
        self.ramp_duration = ramp_duration
        self.error_threshold = error_threshold
        self.error_window = error_window

        # Recovery period state
        self.recovery_started_at: float = 0.0  # 0.0 means not in recovery

        # Token bucket state
        self.tokens: float = 1.0  # Current token bucket level
        self.capacity: float = 1.0  # Max tokens (allows 1 job burst)
        self.last_update: float = 0.0  # Last token refill time

        # Backoff state
        self.rate_multiplier: float = 1.0  # Backoff multiplier (0.5 during backoff, 1.0 normal)
        self.backoff_until: float = 0.0  # Time when backoff expires

        # Error tracking
        self.results: list = []  # List of (timestamp, success_bool)

    def is_in_recovery_period(self, now: Optional[float] = None) -> bool:
        """
        Check if currently in recovery period.

        Args:
            now: Current time (default: time.time())

        Returns:
            True if recovery_started_at > 0 and elapsed < ramp_duration
        """
        if self.recovery_started_at == 0.0:
            return False

        if now is None:
            now = time.time()

        elapsed = now - self.recovery_started_at
        return elapsed < self.ramp_duration

    def start_recovery_period(self, now: Optional[float] = None):
        """
        Start recovery period.

        Sets recovery_started_at, resets tokens/last_update, clears error results
        and backoff state.

        Args:
            now: Current time (default: time.time())
        """
        if now is None:
            now = time.time()

        self.recovery_started_at = now
        self.tokens = self.capacity
        self.last_update = now
        self.rate_multiplier = 1.0
        self.backoff_until = 0.0
        self.results = []

        log_info(f"Recovery period started at {now}, rate will ramp from "
                 f"{self.initial_rate} to {self.target_rate} jobs/sec over "
                 f"{self.ramp_duration}s")

    def end_recovery_period(self):
        """
        End recovery period.

        Clears recovery_started_at (sets to 0.0) and resets state.
        """
        log_info(f"Recovery period ended, returning to unlimited rate")
        self.recovery_started_at = 0.0
        self.tokens = self.capacity
        self.last_update = 0.0
        self.rate_multiplier = 1.0
        self.backoff_until = 0.0
        self.results = []

    def current_rate(self, now: Optional[float] = None) -> float:
        """
        Calculate current rate based on elapsed time in recovery period.

        Uses linear interpolation: rate = initial_rate + (target_rate - initial_rate) * (elapsed / ramp_duration)

        Args:
            now: Current time (default: time.time())

        Returns:
            Current rate in jobs/second, with rate_multiplier applied
        """
        if not self.is_in_recovery_period(now):
            return self.target_rate

        if now is None:
            now = time.time()

        elapsed = now - self.recovery_started_at
        if elapsed >= self.ramp_duration:
            return self.target_rate * self.rate_multiplier

        # Linear interpolation
        progress = elapsed / self.ramp_duration
        rate = self.initial_rate + (self.target_rate - self.initial_rate) * progress

        return rate * self.rate_multiplier

    def should_wait(self, now: Optional[float] = None) -> float:
        """
        Check if job should wait, based on token bucket.

        Refills tokens based on elapsed time and current rate, then tries to
        consume 1 token. If token available, returns 0.0. If not, returns
        wait time in seconds until next token is available.

        Args:
            now: Current time (default: time.time())

        Returns:
            Wait time in seconds (0.0 if can proceed immediately)
        """
        if not self.is_in_recovery_period(now):
            return 0.0

        if now is None:
            now = time.time()

        # Refill tokens based on elapsed time
        if self.last_update > 0:
            elapsed = now - self.last_update
            rate = self.current_rate(now)
            tokens_to_add = elapsed * rate
            self.tokens = min(self.capacity, self.tokens + tokens_to_add)

        self.last_update = now

        # Try to consume 1 token
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return 0.0

        # Not enough tokens, calculate wait time
        shortage = 1.0 - self.tokens
        rate = self.current_rate(now)
        wait_time = shortage / rate if rate > 0 else 0.0

        return wait_time

    def record_result(self, success: bool, now: Optional[float] = None):
        """
        Record job result for error rate monitoring.

        Appends to results list with timestamp, prunes old results outside
        error_window, and adjusts rate if needed.

        Args:
            success: True if job succeeded, False if failed
            now: Current time (default: time.time())
        """
        if now is None:
            now = time.time()

        # Record result
        self.results.append((now, success))

        # Prune old results outside window
        cutoff = now - self.error_window
        self.results = [(ts, s) for ts, s in self.results if ts >= cutoff]

        # Check if rate adjustment needed
        self._maybe_adjust_rate(now)

    def _maybe_adjust_rate(self, now: Optional[float] = None):
        """
        Adjust rate based on error rate.

        If error rate > threshold and not already backed off: halve rate (multiplier=0.5).
        If error rate < 0.1 and backoff expired: restore rate (multiplier=1.0).

        Args:
            now: Current time (default: time.time())
        """
        if not self.is_in_recovery_period(now):
            return

        if now is None:
            now = time.time()

        err_rate = self.error_rate(now)

        # Trigger backoff if error rate too high
        if err_rate > self.error_threshold and self.rate_multiplier == 1.0:
            self.rate_multiplier = 0.5
            self.backoff_until = now + 60.0
            log_warn(f"Error rate {err_rate:.2%} exceeds threshold {self.error_threshold:.2%}, "
                     f"reducing rate by 50% for 60s")

        # Restore rate if error rate drops and backoff period expired
        elif err_rate < 0.1 and self.rate_multiplier < 1.0 and now >= self.backoff_until:
            self.rate_multiplier = 1.0
            log_info(f"Error rate {err_rate:.2%} recovered, restoring full rate")

    def error_rate(self, now: Optional[float] = None) -> float:
        """
        Calculate error rate in current time window.

        Args:
            now: Current time (default: time.time())

        Returns:
            Error rate as failures/total (0.0 if no results)
        """
        if now is None:
            now = time.time()

        # Prune old results
        cutoff = now - self.error_window
        recent_results = [(ts, s) for ts, s in self.results if ts >= cutoff]

        if not recent_results:
            return 0.0

        failures = sum(1 for _, success in recent_results if not success)
        total = len(recent_results)

        return failures / total if total > 0 else 0.0
