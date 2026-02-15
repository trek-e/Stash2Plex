"""
Deep Plex health check using /identity endpoint.

The /identity endpoint requires database access, preventing false positives
during Plex's multi-stage startup sequence:
  1. Port open (TCP listening)
  2. HTTP responding (web server started)
  3. Database loading (SQLite initialization)
  4. API ready (/identity works)

A simple TCP or HTTP check would pass during stage 2-3, but actual API
operations would fail. The /identity endpoint only succeeds when Plex is
fully operational.

This module provides a health check function used by:
- Manual health check task (troubleshooting)
- Worker loop integration (circuit breaker state management)
"""

import time
from typing import Tuple, TYPE_CHECKING

from shared.log import create_logger

if TYPE_CHECKING:
    from plex.client import PlexClient

log_trace, log_debug, log_info, log_warn, log_error = create_logger("Health")

__all__ = ["check_plex_health"]


def check_plex_health(plex_client: "PlexClient", timeout: float = 5.0) -> Tuple[bool, float]:
    """
    Check Plex server health via /identity endpoint.

    Uses server.query('/identity') which requires database access. This ensures
    we only report healthy when Plex is fully operational, not just when the
    HTTP server is responding.

    Args:
        plex_client: PlexClient instance to check
        timeout: Request timeout in seconds (default: 5.0, shorter than normal 30s)

    Returns:
        Tuple of (is_healthy, latency_ms):
        - (True, latency_ms) if server responded successfully
        - (False, 0.0) if server is unreachable or returned error

    Examples:
        >>> from plex.client import PlexClient
        >>> from plex.health import check_plex_health
        >>> client = PlexClient(url="http://plex:32400", token="token")
        >>> healthy, latency = check_plex_health(client)
        >>> if healthy:
        ...     print(f"Plex is healthy (latency: {latency:.1f}ms)")
        ... else:
        ...     print("Plex is down or database loading")
    """
    try:
        start = time.perf_counter()
        plex_client.server.query('/identity', timeout=timeout)
        end = time.perf_counter()

        latency_ms = (end - start) * 1000.0
        log_debug(f"Health check passed (latency: {latency_ms:.1f}ms)")
        return (True, latency_ms)

    except Exception as exc:
        # Any exception means "not healthy" - could be:
        # - ConnectionError (server down)
        # - TimeoutError (server too slow / hung)
        # - 503 (database loading)
        # - Any other API error
        #
        # Log at debug level since failures during outages are expected
        # and would be noisy at info level. Caller logs at appropriate level.
        log_debug(f"Health check failed: {type(exc).__name__}: {exc}")
        return (False, 0.0)
