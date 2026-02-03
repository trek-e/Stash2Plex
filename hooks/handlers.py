"""
Hook handlers for fast event capture.

Implements <100ms event handlers that enqueue jobs for background processing.
Includes metadata validation before enqueueing.
"""

import time
from typing import Optional

try:
    from queue.operations import enqueue, load_sync_timestamps
except ImportError:
    enqueue = None
    load_sync_timestamps = None

try:
    from validation.metadata import validate_metadata
except ImportError:
    validate_metadata = None


# In-memory tracking of pending scene IDs for deduplication
# Resets on restart - acceptable tradeoff for <100ms hook handler requirement
_pending_scene_ids: set[int] = set()


def mark_scene_pending(scene_id: int) -> None:
    """Mark scene as having a pending job in queue."""
    _pending_scene_ids.add(scene_id)


def unmark_scene_pending(scene_id: int) -> None:
    """Remove scene from pending set (called after job completes)."""
    _pending_scene_ids.discard(scene_id)


def is_scene_pending(scene_id: int) -> bool:
    """Check if scene already has a pending job."""
    return scene_id in _pending_scene_ids


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


def on_scene_update(
    scene_id: int,
    update_data: dict,
    queue,
    data_dir: Optional[str] = None,
    sync_timestamps: Optional[dict[int, float]] = None
) -> bool:
    """
    Handle scene update event with fast enqueue.

    Target: <100ms execution time. Validates metadata before enqueueing
    to ensure clean data enters the queue.

    Args:
        scene_id: Stash scene ID
        update_data: Scene update data from hook
        queue: Queue instance for job storage
        data_dir: Plugin data directory for sync timestamps
        sync_timestamps: Dict mapping scene_id to last sync timestamp

    Returns:
        True if job was enqueued, False if filtered out or validation failed
    """
    start = time.time()

    # Filter non-sync events before enqueueing
    if not requires_plex_sync(update_data):
        print(f"[PlexSync] Scene {scene_id} update filtered (no metadata changes)")
        return False

    # Filter: Timestamp comparison for late update detection
    if sync_timestamps is not None:
        # Try to get updated_at from Stash hook data
        # Fallback to current time if field missing (Stash may not always provide it)
        stash_updated_at = update_data.get('updated_at')
        if stash_updated_at is None:
            # Stash didn't provide updated_at - use current time as proxy
            # This means we'll re-sync, which is safe (idempotent)
            stash_updated_at = time.time()

        last_synced = sync_timestamps.get(scene_id)
        if last_synced and stash_updated_at <= last_synced:
            print(f"[PlexSync] Scene {scene_id} already synced (Stash: {stash_updated_at} <= Last: {last_synced})")
            return False

    # Filter: Queue deduplication using in-memory tracking
    if is_scene_pending(scene_id):
        print(f"[PlexSync] Scene {scene_id} already in queue, skipping duplicate")
        return False

    # Enqueue job for background processing
    if enqueue is None:
        print(f"[PlexSync] ERROR: queue.operations not available")
        return False

    # Build validation data from update_data
    # Title is required - if missing from update, we need to get it
    # For now, if title is missing, we skip validation
    title = update_data.get('title')

    if title and validate_metadata is not None:
        # Build validation dict with available fields
        validation_data = {
            'scene_id': scene_id,
            'title': title,
        }

        # Add optional fields if present
        for field in ['details', 'rating100', 'date', 'studio', 'performers', 'tags']:
            if field in update_data and update_data[field] is not None:
                validation_data[field] = update_data[field]

        # Validate and sanitize
        validated, error = validate_metadata(validation_data)

        if error:
            # Check if it's a missing title error (critical)
            if 'title' in error.lower() and ('required' in error.lower() or 'empty' in error.lower()):
                print(f"[PlexSync] Scene {scene_id} validation failed: {error}")
                return False
            # For other validation errors, log warning but continue with sanitized data
            print(f"[PlexSync] WARNING: Scene {scene_id} validation issue: {error}")

        if validated:
            # Use validated/sanitized data for job
            sanitized_data = {
                'title': validated.title,
            }
            # Add optional fields from validated model
            if validated.details is not None:
                sanitized_data['details'] = validated.details
            if validated.rating100 is not None:
                sanitized_data['rating100'] = validated.rating100
            if validated.date is not None:
                sanitized_data['date'] = validated.date
            if validated.studio is not None:
                sanitized_data['studio'] = validated.studio
            if validated.performers is not None:
                sanitized_data['performers'] = validated.performers
            if validated.tags is not None:
                sanitized_data['tags'] = validated.tags

            # Preserve any extra fields from original update_data that we don't validate
            for key in ['studio_id', 'performer_ids', 'tag_ids', 'rating']:
                if key in update_data:
                    sanitized_data[key] = update_data[key]

            enqueue(queue, scene_id, "metadata", sanitized_data)
        else:
            # Validation failed critically (title issues), already logged above
            return False
    else:
        # No title in update or validation not available, enqueue as-is
        # (title might be in Stash already, worker can lookup)
        enqueue(queue, scene_id, "metadata", update_data)

    # Mark scene as pending to prevent duplicate enqueues
    mark_scene_pending(scene_id)

    # Calculate elapsed time and warn if over target
    elapsed_ms = (time.time() - start) * 1000
    print(f"[PlexSync] Enqueued sync job for scene {scene_id} in {elapsed_ms:.1f}ms")

    if elapsed_ms > 100:
        print(f"[PlexSync] WARNING: Hook handler exceeded 100ms target ({elapsed_ms:.1f}ms)")

    return True
