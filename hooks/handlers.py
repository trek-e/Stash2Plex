"""
Hook handlers for fast event capture.

Implements <100ms event handlers that enqueue jobs for background processing.
"""

import time
from typing import Optional

try:
    from queue.operations import enqueue
except ImportError:
    enqueue = None


def requires_plex_sync(update_data: dict) -> bool:
    """
    Check if update contains sync-worthy changes.

    Filters out non-metadata updates like play counts, view history,
    and file system only changes.

    Args:
        update_data: Scene update data from Stash hook

    Returns:
        True if update contains metadata fields that should sync to Plex
    """
    # Metadata fields that trigger Plex sync
    sync_fields = [
        'title',
        'details',
        'studio_id',
        'performer_ids',
        'tag_ids',
        'rating100',
        'date',
        'rating',
        'studio',
        'performers',
        'tags'
    ]

    # Check if any sync-worthy field is present in the update
    for field in sync_fields:
        if field in update_data:
            return True

    return False


def on_scene_update(scene_id: int, update_data: dict, queue) -> bool:
    """
    Handle scene update event with fast enqueue.

    Target: <100ms execution time. No Plex API calls, no validation,
    just filter and enqueue.

    Args:
        scene_id: Stash scene ID
        update_data: Scene update data from hook
        queue: Queue instance for job storage

    Returns:
        True if job was enqueued, False if filtered out
    """
    start = time.time()

    # Filter non-sync events before enqueueing
    if not requires_plex_sync(update_data):
        print(f"[PlexSync] Scene {scene_id} update filtered (no metadata changes)")
        return False

    # Enqueue job for background processing
    if enqueue is None:
        print(f"[PlexSync] ERROR: queue.operations not available")
        return False

    enqueue(queue, scene_id, "metadata", update_data)

    # Calculate elapsed time and warn if over target
    elapsed_ms = (time.time() - start) * 1000
    print(f"[PlexSync] Enqueued sync job for scene {scene_id} in {elapsed_ms:.1f}ms")

    if elapsed_ms > 100:
        print(f"[PlexSync] WARNING: Hook handler exceeded 100ms target ({elapsed_ms:.1f}ms)")

    return True
