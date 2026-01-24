"""
Centralized error classification for retry/DLQ routing.

Provides consistent classification of errors to determine whether they should
be retried (transient) or moved to DLQ (permanent). This ensures all components
use the same logic for error handling decisions.
"""

import logging
from typing import Type

from worker.processor import TransientError, PermanentError


# HTTP status codes that indicate transient (retry-able) errors
# 429: Rate limited - retry after backoff
# 5xx: Server errors - usually temporary
TRANSIENT_CODES = frozenset({429, 500, 502, 503, 504})

# HTTP status codes that indicate permanent (non-retry-able) errors
# 400: Bad request - data issue
# 401: Unauthorized - auth config issue
# 403: Forbidden - permission issue
# 404: Not found - item doesn't exist
# 405: Method not allowed - API misuse
# 410: Gone - item permanently removed
# 422: Unprocessable entity - validation failure
PERMANENT_CODES = frozenset({400, 401, 403, 404, 405, 410, 422})

# Module logger
logger = logging.getLogger(__name__)


def classify_http_error(status_code: int) -> Type[Exception]:
    """
    Classify an HTTP status code as transient or permanent error.

    Args:
        status_code: HTTP response status code

    Returns:
        TransientError class for retry-able errors
        PermanentError class for non-retry-able errors
    """
    if status_code in TRANSIENT_CODES:
        logger.debug(f"HTTP {status_code} classified as transient")
        return TransientError

    if status_code in PERMANENT_CODES:
        logger.debug(f"HTTP {status_code} classified as permanent")
        return PermanentError

    # Default classification by status code range
    if 400 <= status_code < 500:
        # Unknown 4xx = permanent (client error, unlikely to change)
        logger.debug(f"HTTP {status_code} (unknown 4xx) classified as permanent")
        return PermanentError

    if status_code >= 500:
        # Unknown 5xx = transient (server error, may recover)
        logger.debug(f"HTTP {status_code} (unknown 5xx) classified as transient")
        return TransientError

    # Unknown codes (1xx, 2xx, 3xx shouldn't reach here) = transient (safer)
    logger.debug(f"HTTP {status_code} (unexpected) classified as transient")
    return TransientError


def classify_exception(exc: Exception) -> Type[Exception]:
    """
    Classify an exception as transient or permanent error.

    Handles various exception types:
    - HTTP responses (from requests/httpx): Extract status code
    - Network errors: Transient (ConnectionError, TimeoutError, OSError)
    - Validation errors: Permanent (ValueError, TypeError, KeyError, AttributeError)
    - Already classified: Return same type
    - Unknown: Transient (safer, allows retry)

    Args:
        exc: The exception to classify

    Returns:
        TransientError class for retry-able errors
        PermanentError class for non-retry-able errors
    """
    # Check if already classified
    if isinstance(exc, TransientError):
        logger.debug(f"Exception already TransientError: {exc}")
        return TransientError

    if isinstance(exc, PermanentError):
        logger.debug(f"Exception already PermanentError: {exc}")
        return PermanentError

    # Check for HTTP response (requests, httpx, urllib, etc.)
    if hasattr(exc, 'response') and exc.response is not None:
        response = exc.response
        status_code = getattr(response, 'status_code', None)
        if status_code is not None:
            logger.debug(f"Exception has HTTP response with status {status_code}")
            return classify_http_error(status_code)

    # Network errors are transient (connectivity, timeout)
    if isinstance(exc, (ConnectionError, TimeoutError, OSError)):
        logger.debug(f"Network error classified as transient: {type(exc).__name__}")
        return TransientError

    # Validation/data errors are permanent (won't fix with retry)
    if isinstance(exc, (ValueError, TypeError, KeyError, AttributeError)):
        logger.debug(f"Validation error classified as permanent: {type(exc).__name__}")
        return PermanentError

    # Unknown errors default to transient (safer, allows retry)
    logger.debug(f"Unknown exception classified as transient: {type(exc).__name__}")
    return TransientError
