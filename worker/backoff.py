"""
Exponential backoff with full jitter for retry delay calculation.

Provides crash-safe delay calculation for retry orchestration.
Full jitter prevents thundering herd when multiple jobs retry
simultaneously after Plex outage.

Functions:
    calculate_delay: Calculate retry delay with full jitter
    get_retry_params: Get backoff parameters based on error type
"""

import random
from typing import Optional, Tuple

# PlexNotFound: number of "core" attempts using the original exponential
# schedule (30s base, capped at 10 min) before the long tail kicks in.
_PLEX_NOT_FOUND_CORE_RETRIES = 12

# PlexNotFound: fixed delay caps for the long-tail attempts beyond
# _PLEX_NOT_FOUND_CORE_RETRIES, so a job survives roughly until Plex's next
# scheduled library scan (which can be ~24h away) instead of being written
# off after ~1.4h. See get_retry_params() for the full rationale.
_PLEX_NOT_FOUND_TAIL_CAPS_SECONDS: Tuple[float, ...] = (
    6 * 3600.0,   # ~6h
    12 * 3600.0,  # ~12h
    24 * 3600.0,  # ~24h
)

_PLEX_NOT_FOUND_MAX_RETRIES = _PLEX_NOT_FOUND_CORE_RETRIES + len(_PLEX_NOT_FOUND_TAIL_CAPS_SECONDS)


def calculate_delay(
    retry_count: int,
    base: float,
    cap: float,
    jitter_seed: Optional[int] = None
) -> float:
    """
    Calculate retry delay using exponential backoff with full jitter.

    Full jitter formula: random.uniform(0, min(cap, base * 2^retry_count))

    This distributes retries randomly within the delay window,
    preventing thundering herd when multiple jobs retry after an outage.

    Args:
        retry_count: Number of previous retry attempts (0 for first retry)
        base: Base delay in seconds (e.g., 5.0)
        cap: Maximum delay cap in seconds (e.g., 80.0)
        jitter_seed: Optional seed for deterministic testing

    Returns:
        Delay in seconds, in range [0, min(cap, base * 2^retry_count)]

    Example:
        >>> from worker.backoff import calculate_delay
        >>> delay = calculate_delay(retry_count=3, base=1.0, cap=60.0,
        ...                         jitter_seed=42)
        >>> 0 <= delay <= 8.0  # 2^3 = 8, with jitter
        True
    """
    # Create seeded random generator for deterministic testing
    rng = random.Random(jitter_seed)

    # Calculate exponential delay: base * 2^retry_count
    exponential_delay = base * (2 ** retry_count)

    # Apply cap
    max_delay = min(cap, exponential_delay)

    # Full jitter: random value in [0, max_delay]
    return rng.uniform(0, max_delay)


def get_retry_params(error: Exception, retry_count: int = 0) -> Tuple[float, float, int]:
    """
    Get backoff parameters based on error type.

    PlexNotFound errors use longer delays and more retries because
    Plex library scanning can take minutes to hours.

    Args:
        error: The exception that triggered the retry
        retry_count: Number of previous retry attempts (0 for the first
            retry). Only affects PlexNotFound's cap — see below.

    Returns:
        Tuple of (base_delay, max_delay, max_retries)
        - PlexNotFound: (30.0, cap, 15) — see below for `cap`.
        - Other errors: (5.0, 80.0, 5) for standard backoff

    PlexNotFound schedule:
        Attempts 1-12 (retry_count 0-11) use the original exponential
        schedule: 30s base -> 60 -> 120 -> 240 -> 480 -> capped at 600s
        (10 min). Worst-case (unjittered) total across these 12 attempts is
        5130s (~1.43h); with full jitter the average is ~43 minutes — far
        short of a scheduled Plex library scan, which can be up to ~24h
        away. Attempts 13-15 (retry_count 12-14) add a long tail at fixed
        caps of ~6h, ~12h, ~24h so a job survives roughly until the next
        scan instead of being written off first.
    """
    # Import lazily to avoid circular imports
    from plex.exceptions import PlexNotFound, PlexServerDown

    if isinstance(error, PlexServerDown):
        # Server is down: circuit breaker handles pausing, not retries
        # Large max_retries so jobs are never DLQ'd for being unreachable
        return (30.0, 300.0, 999)
    elif isinstance(error, PlexNotFound):
        base = 30.0
        if retry_count < _PLEX_NOT_FOUND_CORE_RETRIES:
            cap = 600.0
        else:
            tail_index = min(
                retry_count - _PLEX_NOT_FOUND_CORE_RETRIES,
                len(_PLEX_NOT_FOUND_TAIL_CAPS_SECONDS) - 1,
            )
            cap = _PLEX_NOT_FOUND_TAIL_CAPS_SECONDS[tail_index]
        return (base, cap, _PLEX_NOT_FOUND_MAX_RETRIES)
    else:
        # Standard transient errors: normal backoff
        # 5s base -> 10 -> 20 -> 40 -> 80 (capped)
        return (5.0, 80.0, 5)
