"""
Base error classes for worker job classification.

Extracted from processor.py to break the circular import with plex.exceptions,
which subclasses these for proper retry/DLQ routing.
"""


class TransientError(Exception):
    """Retry-able errors (network, timeout, 5xx)"""
    pass


class PermanentError(Exception):
    """Non-retry-able errors (4xx except 429, validation)"""
    pass
