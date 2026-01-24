"""
Background worker for processing sync jobs.

Exports SyncWorker class that processes jobs from the queue
with proper acknowledgment and error handling.
"""

from worker.processor import SyncWorker, TransientError, PermanentError

__all__ = ['SyncWorker', 'TransientError', 'PermanentError']
