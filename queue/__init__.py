"""
Persistent Queue Module

Provides durable job queue infrastructure for PlexSync using SQLite-backed
persistence. Jobs survive process restarts, crashes, and Plex outages.
"""

from queue.manager import QueueManager
from queue.models import SyncJob
from queue.operations import enqueue, get_pending, ack_job, nack_job, fail_job, get_stats

__all__ = [
    'QueueManager',
    'SyncJob',
    'enqueue',
    'get_pending',
    'ack_job',
    'nack_job',
    'fail_job',
    'get_stats',
]
