"""Gap detection engine for identifying metadata discrepancies between Stash and Plex."""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass
class GapResult:
    """Result of a gap detection operation.

    Attributes:
        scene_id: The Stash scene ID
        gap_type: Type of gap detected ('empty_metadata', 'stale_sync', 'missing')
        scene_data: The complete Stash scene dict (needed for enqueue)
        reason: Human-readable explanation of the gap
    """
    scene_id: int
    gap_type: str
    scene_data: dict[str, Any]
    reason: str


def has_meaningful_metadata(data: dict[str, Any]) -> bool:
    """Check if data dict has any meaningful metadata fields.

    This reuses the same quality gate logic from handlers.py (lines 266-272).
    A scene has meaningful metadata if it has any of:
    - studio
    - performers
    - tags
    - details
    - date

    NOTE: rating100 is intentionally EXCLUDED. A rating alone is not considered
    "meaningful metadata" because:
    1. Ratings are often auto-assigned defaults (not user-curated)
    2. A scene with ONLY a rating shouldn't trigger sync (would clear other Plex fields)
    3. Per LOCKED architecture decision: empty/null fields clear Plex values

    Args:
        data: Dictionary to check for metadata fields

    Returns:
        True if data has at least one meaningful metadata field, False otherwise
    """
    return any([
        data.get('studio'),
        data.get('performers'),
        data.get('tags'),
        data.get('details'),
        data.get('date'),
    ])


class GapDetector:
    """Detects metadata gaps between Stash and Plex.

    The detector operates on pre-fetched data (no API calls) and identifies
    three types of gaps:
    1. Empty metadata - Plex has no meaningful metadata but Stash does
    2. Stale syncs - Stash updated_at is newer than sync timestamp
    3. Missing items - No sync history and no known Plex match
    """

    def detect_empty_metadata(
        self,
        stash_scenes: list[dict[str, Any]],
        plex_items_metadata: dict[str, dict[str, Any]]
    ) -> list[GapResult]:
        """Detect scenes where Plex has no meaningful metadata but Stash does.

        A scene is an "empty metadata gap" when:
        - The Plex item exists (matched by file path) AND
        - The Plex item lacks ALL of: studio, performers, tags, details, date AND
        - The Stash scene has at least one of those fields populated

        Args:
            stash_scenes: List of Stash scene dicts (from GQL)
            plex_items_metadata: Dict mapping file_path -> plex metadata dict

        Returns:
            List of GapResult objects for scenes with empty metadata in Plex
        """
        gaps = []

        for scene in stash_scenes:
            scene_id = scene.get('id')
            files = scene.get('files', [])

            # Skip scenes without files
            if not files:
                continue

            # Get the file path (assume first file for now)
            file_path = files[0].get('path')
            if not file_path:
                continue

            # Skip if no Plex match
            if file_path not in plex_items_metadata:
                continue

            plex_metadata = plex_items_metadata[file_path]

            # Check if Stash has meaningful metadata
            if not has_meaningful_metadata(scene):
                continue

            # Convert scene_id to int
            try:
                scene_id_int = int(scene_id)
            except (ValueError, TypeError):
                continue

            # Check if Plex lacks meaningful metadata
            if not has_meaningful_metadata(plex_metadata):
                gaps.append(GapResult(
                    scene_id=scene_id_int,
                    gap_type='empty_metadata',
                    scene_data=scene,
                    reason=f'Scene {scene_id} has meaningful metadata in Stash but Plex has no meaningful metadata'
                ))

        return gaps

    def detect_stale_syncs(
        self,
        stash_scenes: list[dict[str, Any]],
        sync_timestamps: dict[int, float]
    ) -> list[GapResult]:
        """Detect scenes where Stash updated_at is newer than sync timestamp.

        A scene is a "stale sync gap" when:
        - The scene has a sync timestamp entry AND
        - The Stash scene's updated_at (converted to epoch) is newer than the sync timestamp

        Edge case: If sync timestamp is newer than updated_at, SKIP -- the sync already
        happened with current data. If the Stash fields are now empty, that was intentional
        (per LOCKED "missing fields clear Plex values" decision).

        Args:
            stash_scenes: List of Stash scene dicts (with updated_at field)
            sync_timestamps: Dict mapping scene_id -> epoch timestamp

        Returns:
            List of GapResult objects for scenes with stale syncs
        """
        gaps = []

        for scene in stash_scenes:
            scene_id = scene.get('id')
            updated_at_str = scene.get('updated_at')

            # Skip if no updated_at field or it's None
            if not updated_at_str:
                continue

            # Convert scene_id to int for sync_timestamps lookup
            try:
                scene_id_int = int(scene_id)
            except (ValueError, TypeError):
                continue

            # Skip if scene has no sync timestamp (handled by detect_missing)
            if scene_id_int not in sync_timestamps:
                continue

            # Parse Stash updated_at to epoch timestamp
            # Stash returns ISO format like "2026-02-10T12:00:00Z"
            # Replace Z with +00:00 for fromisoformat (matching pattern from Stash2Plex.py line 871)
            try:
                updated_at_str_normalized = updated_at_str.replace('Z', '+00:00')
                updated_at = datetime.fromisoformat(updated_at_str_normalized)
                updated_at_epoch = updated_at.timestamp()
            except (ValueError, AttributeError):
                # Skip if can't parse datetime
                continue

            sync_timestamp = sync_timestamps[scene_id_int]

            # Only detect gap if Stash is newer than sync
            # If sync is newer, skip (intentional empty per LOCKED decision)
            if updated_at_epoch > sync_timestamp:
                gaps.append(GapResult(
                    scene_id=scene_id_int,
                    gap_type='stale_sync',
                    scene_data=scene,
                    reason=f'Scene {scene_id} was updated in Stash after last sync (stale)'
                ))

        return gaps

    def detect_missing(
        self,
        stash_scenes: list[dict[str, Any]],
        sync_timestamps: dict[int, float],
        matched_paths: set[str]
    ) -> list[GapResult]:
        """Detect scenes with no sync history and no known Plex match.

        A scene is "missing" when:
        - It has NO entry in sync_timestamps (never successfully synced) AND
        - Its file path is NOT in matched_paths set (no known Plex match)

        Args:
            stash_scenes: List of Stash scene dicts
            sync_timestamps: Dict mapping scene_id -> epoch timestamp
            matched_paths: Set of file paths that have known Plex matches

        Returns:
            List of GapResult objects for missing scenes
        """
        gaps = []

        for scene in stash_scenes:
            scene_id = scene.get('id')
            files = scene.get('files', [])

            # Skip scenes without files
            if not files:
                continue

            # Get the file path (assume first file for now)
            file_path = files[0].get('path')
            if not file_path:
                continue

            # Convert scene_id to int for sync_timestamps lookup
            try:
                scene_id_int = int(scene_id)
            except (ValueError, TypeError):
                continue

            # Skip if scene has a sync timestamp (was synced before)
            if scene_id_int in sync_timestamps:
                continue

            # Skip if file path has a known Plex match
            if file_path in matched_paths:
                continue

            # This is a missing scene
            gaps.append(GapResult(
                scene_id=scene_id_int,
                gap_type='missing',
                scene_data=scene,
                reason=f'Scene {scene_id} has no sync history and no known Plex match (missing)'
            ))

        return gaps
