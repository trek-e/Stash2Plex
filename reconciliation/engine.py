"""
Gap detection engine orchestrator for Stash-to-Plex reconciliation.

Integrates GapDetector with infrastructure (Stash GQL, Plex matcher, persistent queue)
to orchestrate end-to-end gap detection: fetch scenes, match against Plex, run detectors,
and enqueue discovered gaps.
"""

import logging
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, TYPE_CHECKING

from reconciliation.detector import GapDetector, has_meaningful_metadata

if TYPE_CHECKING:
    from stashapi.stashapp import StashInterface
    from config.config import Stash2PlexConfig
    from persistqueue import SQLiteAckQueue

logger = logging.getLogger('Stash2Plex.reconciliation.engine')

# Stash plugin log levels
def log_debug(msg): print(f"\x01d\x02[Stash2Plex Gap Engine] {msg}", file=sys.stderr)
def log_info(msg): print(f"\x01i\x02[Stash2Plex Gap Engine] {msg}", file=sys.stderr)
def log_warn(msg): print(f"\x01w\x02[Stash2Plex Gap Engine] {msg}", file=sys.stderr)
def log_error(msg): print(f"\x01e\x02[Stash2Plex Gap Engine] {msg}", file=sys.stderr)


@dataclass
class GapDetectionResult:
    """Result summary from gap detection run.

    Attributes:
        empty_metadata_count: Number of scenes with empty metadata in Plex
        stale_sync_count: Number of scenes with stale sync timestamps
        missing_count: Number of scenes with no Plex match
        total_gaps: Total number of gaps detected (sum of above)
        enqueued_count: Number of gaps actually enqueued (after dedup)
        skipped_already_queued: Number of gaps skipped (already in queue)
        scenes_checked: Total number of scenes checked
        errors: List of non-fatal error messages during detection
    """
    empty_metadata_count: int = 0
    stale_sync_count: int = 0
    missing_count: int = 0
    total_gaps: int = 0
    enqueued_count: int = 0
    skipped_already_queued: int = 0
    scenes_checked: int = 0
    errors: list[str] = field(default_factory=list)


class GapDetectionEngine:
    """Orchestrates gap detection and enqueue operations.

    Connects the pure GapDetector logic to real infrastructure:
    - Stash GQL queries for scene data
    - Plex matcher for file-to-item matching
    - Persistent queue for enqueue operations
    - Match cache for performance optimization

    Args:
        stash: StashInterface instance for GQL queries
        config: Stash2PlexConfig with Plex connection details
        data_dir: Plugin data directory (for sync_timestamps.json, queue, cache)
        queue: Optional SQLiteAckQueue (if provided, gaps are enqueued; if None, detection-only)
    """

    def __init__(
        self,
        stash: "StashInterface",
        config: "Stash2PlexConfig",
        data_dir: str,
        queue: Optional["SQLiteAckQueue"] = None
    ):
        self.stash = stash
        self.config = config
        self.data_dir = data_dir
        self.queue = queue
        self.detector = GapDetector()

    def run(self, scope: str = "all") -> GapDetectionResult:
        """Run gap detection and optionally enqueue discovered gaps.

        Args:
            scope: "all" (all scenes) or "recent" (last 24 hours)

        Returns:
            GapDetectionResult with counts and any errors encountered

        Execution steps:
            1. Fetch Stash scenes via GQL (with scope filtering)
            2. Load sync_timestamps from disk
            3. Build Plex item metadata dict for empty detection
            4. Build matched_paths set for missing detection (lighter pre-check)
            5. Run three detection methods
            6. Enqueue gaps (if queue provided), with deduplication
            7. Return summary
        """
        result = GapDetectionResult()

        # Step 1: Fetch Stash scenes
        try:
            scenes = self._fetch_stash_scenes(scope)
            result.scenes_checked = len(scenes)
            if not scenes:
                log_info("No scenes found to check")
                return result
            log_info(f"Checking {len(scenes)} scenes for gaps")
        except Exception as e:
            result.errors.append(f"Failed to fetch Stash scenes: {e}")
            log_error(f"Failed to fetch scenes: {e}")
            return result

        # Step 2: Load sync timestamps
        from sync_queue.operations import load_sync_timestamps
        sync_timestamps = load_sync_timestamps(self.data_dir)
        log_debug(f"Loaded {len(sync_timestamps)} sync timestamps")

        # Step 3 & 4: Build Plex metadata and matched paths
        try:
            plex_items_metadata, matched_paths = self._build_plex_data(scenes, sync_timestamps)
            log_debug(f"Built metadata for {len(plex_items_metadata)} Plex items, {len(matched_paths)} matched paths")
        except Exception as e:
            # PlexServerDown or other critical errors
            result.errors.append(f"Failed to build Plex data: {e}")
            log_error(f"Failed to build Plex data: {e}")
            return result

        # Step 5: Run detectors
        empty_gaps = self.detector.detect_empty_metadata(scenes, plex_items_metadata)
        stale_gaps = self.detector.detect_stale_syncs(scenes, sync_timestamps)
        missing_gaps = self.detector.detect_missing(scenes, sync_timestamps, matched_paths)

        result.empty_metadata_count = len(empty_gaps)
        result.stale_sync_count = len(stale_gaps)
        result.missing_count = len(missing_gaps)
        result.total_gaps = result.empty_metadata_count + result.stale_sync_count + result.missing_count

        log_info(f"Gaps detected: {result.empty_metadata_count} empty metadata, "
                 f"{result.stale_sync_count} stale, {result.missing_count} missing")

        # Step 6: Enqueue gaps (if queue provided)
        if self.queue is not None:
            try:
                enqueued, skipped = self._enqueue_gaps(empty_gaps, stale_gaps, missing_gaps)
                result.enqueued_count = enqueued
                result.skipped_already_queued = skipped
                log_info(f"Enqueued {enqueued} gaps ({skipped} already queued)")
            except Exception as e:
                result.errors.append(f"Failed to enqueue gaps: {e}")
                log_error(f"Failed to enqueue gaps: {e}")
        else:
            log_info("Detection-only mode (no queue provided)")

        return result

    def _fetch_stash_scenes(self, scope: str) -> list[dict[str, Any]]:
        """Fetch Stash scenes via GQL with scope filtering.

        Args:
            scope: "all" or "recent" (last 24 hours)

        Returns:
            List of scene dicts with all needed fields
        """
        # Batch query fragment - matches Stash2Plex.py lines 799-811
        fragment = """
            id
            title
            details
            date
            rating100
            updated_at
            files { path }
            studio { name }
            performers { name }
            tags { name }
            paths { screenshot preview }
        """

        if scope == "recent":
            # Last 24 hours - matches Stash2Plex.py lines 818-824
            yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
            log_debug(f"Fetching scenes updated since {yesterday}")
            scenes = self.stash.find_scenes(
                f={"updated_at": {"value": yesterday, "modifier": "GREATER_THAN"}},
                fragment=fragment
            )
        else:  # "all"
            log_debug("Fetching all scenes")
            scenes = self.stash.find_scenes(fragment=fragment)

        return scenes or []

    def _build_plex_data(
        self,
        scenes: list[dict[str, Any]],
        sync_timestamps: dict[int, float]
    ) -> tuple[dict[str, dict[str, Any]], set[str]]:
        """Build Plex metadata dict and matched_paths set.

        This does the heavy lifting:
        - Connects to Plex
        - For each scene, determines if it has a Plex match
        - Extracts Plex metadata for empty detection
        - Builds matched_paths set for missing detection

        Uses lighter pre-check strategy:
        - Check sync_timestamps first (known matches)
        - Check match_cache for path-to-key mappings
        - Fall back to full matcher for unknowns

        Args:
            scenes: Stash scenes to check
            sync_timestamps: Scene ID to timestamp mapping

        Returns:
            Tuple of (plex_items_metadata dict, matched_paths set)
            - plex_items_metadata: file_path -> {studio, performers, tags, details, date}
            - matched_paths: set of file paths with known Plex matches

        Raises:
            Exception if Plex server is unreachable (PlexServerDown)
        """
        from plex.exceptions import PlexServerDown, PlexNotFound

        plex_items_metadata = {}
        matched_paths = set()

        # Connect to Plex
        try:
            # Lazy import to avoid module-level plexapi dependency
            from plex.client import PlexClient
            from plex.cache import PlexCache, MatchCache

            client = PlexClient(
                url=self.config.plex_url,
                token=self.config.plex_token
            )
            plex = client.connect()
            log_debug(f"Connected to Plex server: {plex.friendlyName}")
        except Exception as e:
            # Check if this is PlexServerDown
            from plex.exceptions import translate_plex_exception
            translated = translate_plex_exception(e)
            if isinstance(translated, PlexServerDown):
                log_error("Plex server is down, aborting gap detection")
                raise PlexServerDown("Plex server unreachable") from e
            raise

        # Initialize caches
        try:
            library_cache = PlexCache(self.data_dir)
            match_cache = MatchCache(self.data_dir)
        except Exception as e:
            log_warn(f"Failed to initialize caches, continuing without: {e}")
            library_cache = None
            match_cache = None

        # Get library sections
        libraries = self.config.plex_libraries if hasattr(self.config, 'plex_libraries') else [self.config.plex_library]
        library_sections = {}
        for lib_name in libraries:
            try:
                library_sections[lib_name] = plex.library.section(lib_name)
            except Exception as e:
                log_warn(f"Failed to get library '{lib_name}': {e}")

        if not library_sections:
            raise Exception("No Plex libraries available")

        # Process scenes in batches for memory efficiency
        batch_size = 100
        for i in range(0, len(scenes), batch_size):
            batch = scenes[i:i + batch_size]
            self._process_scene_batch(
                batch,
                sync_timestamps,
                library_sections,
                library_cache,
                match_cache,
                plex_items_metadata,
                matched_paths
            )

            # Log progress
            if (i + batch_size) % 50 == 0 or (i + batch_size) >= len(scenes):
                log_debug(f"Processed {min(i + batch_size, len(scenes))}/{len(scenes)} scenes")

        return plex_items_metadata, matched_paths

    def _process_scene_batch(
        self,
        scenes: list[dict[str, Any]],
        sync_timestamps: dict[int, float],
        library_sections: dict[str, Any],
        library_cache: Optional[Any],
        match_cache: Optional[Any],
        plex_items_metadata: dict[str, dict[str, Any]],
        matched_paths: set[str]
    ):
        """Process a batch of scenes to build Plex metadata and matched paths.

        This implements the lighter pre-check strategy:
        1. If scene in sync_timestamps, mark as matched (skip matcher)
        2. If scene NOT in sync_timestamps, try matcher

        Args:
            scenes: Batch of scenes to process
            sync_timestamps: Scene ID to timestamp mapping
            library_sections: Dict of library name to section object
            library_cache: Optional PlexCache instance
            match_cache: Optional MatchCache instance
            plex_items_metadata: Output dict to populate with Plex metadata
            matched_paths: Output set to populate with matched file paths
        """
        from plex.matcher import find_plex_items_with_confidence, MatchConfidence
        from plex.exceptions import PlexNotFound

        for scene in scenes:
            scene_id = scene.get('id')
            files = scene.get('files', [])
            if not files:
                continue

            file_path = files[0].get('path')
            if not file_path:
                continue

            # Lighter pre-check: if scene has sync timestamp, it's already matched
            if int(scene_id) in sync_timestamps:
                matched_paths.add(file_path)
                # Note: We don't have Plex metadata for this item without fetching it,
                # but that's OK - empty detection only needs metadata for NEW matches
                # (items already synced once won't have empty metadata)
                continue

            # Scene not in sync_timestamps - try matcher
            plex_item = None
            for lib_name, library in library_sections.items():
                try:
                    confidence, item, candidates = find_plex_items_with_confidence(
                        library,
                        file_path,
                        library_cache=library_cache,
                        match_cache=match_cache,
                        debug_logging=self.config.debug_logging if hasattr(self.config, 'debug_logging') else False
                    )
                    if confidence == MatchConfidence.HIGH and item is not None:
                        plex_item = item
                        matched_paths.add(file_path)
                        break
                except PlexNotFound:
                    # Expected for missing items - not an error
                    continue
                except Exception as e:
                    # Non-fatal matcher errors - log and continue
                    log_debug(f"Matcher error for scene {scene_id}: {e}")
                    continue

            # Extract metadata if we found a match
            if plex_item is not None:
                try:
                    metadata = self._extract_plex_metadata(plex_item)
                    plex_items_metadata[file_path] = metadata
                except Exception as e:
                    log_debug(f"Failed to extract metadata for {file_path}: {e}")

    def _extract_plex_metadata(self, plex_item: Any) -> dict[str, Any]:
        """Extract metadata from a Plex item for gap detection.

        Converts Plex's data format to the shape used by has_meaningful_metadata:
        - studio: studio name string or None
        - performers: list of actor names
        - tags: list of genre names
        - details: summary text
        - date: year or originallyAvailableAt

        Args:
            plex_item: plexapi Video object

        Returns:
            Dict with metadata fields (may be empty/None)
        """
        metadata = {}

        # Studio
        studio = getattr(plex_item, 'studio', None)
        if studio:
            metadata['studio'] = studio

        # Performers (Plex calls them 'actors')
        actors = getattr(plex_item, 'actors', None) or []
        if actors:
            metadata['performers'] = [a.tag for a in actors if hasattr(a, 'tag')]

        # Tags (Plex calls them 'genres')
        genres = getattr(plex_item, 'genres', None) or []
        if genres:
            metadata['tags'] = [g.tag for g in genres if hasattr(g, 'tag')]

        # Details (Plex calls it 'summary')
        summary = getattr(plex_item, 'summary', None)
        if summary:
            metadata['details'] = summary

        # Date (try year first, then originallyAvailableAt)
        year = getattr(plex_item, 'year', None)
        if year:
            metadata['date'] = str(year)
        else:
            orig_date = getattr(plex_item, 'originallyAvailableAt', None)
            if orig_date:
                metadata['date'] = str(orig_date)

        return metadata

    def _enqueue_gaps(
        self,
        empty_gaps: list,
        stale_gaps: list,
        missing_gaps: list
    ) -> tuple[int, int]:
        """Enqueue discovered gaps as sync jobs.

        Deduplicates:
        - Against scenes already in queue (via get_queued_scene_ids)
        - Across gap types (same scene may appear in multiple lists)

        Args:
            empty_gaps: List of GapResult from detect_empty_metadata
            stale_gaps: List of GapResult from detect_stale_syncs
            missing_gaps: List of GapResult from detect_missing

        Returns:
            Tuple of (enqueued_count, skipped_already_queued)
        """
        from sync_queue.operations import enqueue, get_queued_scene_ids
        import os

        # Load existing queue scene IDs for deduplication
        queue_path = os.path.join(self.data_dir, 'queue')
        existing_in_queue = get_queued_scene_ids(queue_path)

        # Track scenes we've already enqueued in this run (cross-gap-type dedup)
        enqueued_this_run = set()
        enqueued_count = 0
        skipped_count = 0

        # Combine all gaps
        all_gaps = list(empty_gaps) + list(stale_gaps) + list(missing_gaps)

        for gap in all_gaps:
            scene_id = gap.scene_id
            scene_data = gap.scene_data

            # Skip if already in queue
            if scene_id in existing_in_queue:
                skipped_count += 1
                continue

            # Skip if already enqueued this run
            if scene_id in enqueued_this_run:
                skipped_count += 1
                continue

            # Build job data
            job_data = self._build_job_data(scene_data)
            if job_data is None:
                # Scene has no files, skip
                skipped_count += 1
                continue

            # Enqueue
            try:
                enqueue(self.queue, scene_id, "metadata", job_data)
                enqueued_this_run.add(scene_id)
                enqueued_count += 1
            except Exception as e:
                log_warn(f"Failed to enqueue scene {scene_id}: {e}")
                skipped_count += 1

        return enqueued_count, skipped_count

    def _build_job_data(self, scene: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Build job data dict from Stash scene.

        Matches the extraction logic from Stash2Plex.py handle_task (lines 885-911).

        Args:
            scene: Stash scene dict from GQL

        Returns:
            Job data dict, or None if scene has no files
        """
        # Extract file path
        files = scene.get('files', [])
        if not files:
            return None
        file_path = files[0].get('path')
        if not file_path:
            return None

        # Build base job data
        job_data = {
            'path': file_path,
            'title': scene.get('title'),
            'details': scene.get('details'),
            'date': scene.get('date'),
            'rating100': scene.get('rating100'),
        }

        # Extract nested fields
        studio = scene.get('studio')
        if studio:
            job_data['studio'] = studio.get('name')

        performers = scene.get('performers', [])
        if performers:
            job_data['performers'] = [p.get('name') for p in performers if p.get('name')]

        tags = scene.get('tags', [])
        if tags:
            job_data['tags'] = [t.get('name') for t in tags if t.get('name')]

        paths = scene.get('paths', {})
        if paths:
            if paths.get('screenshot'):
                job_data['poster_url'] = paths['screenshot']
            if paths.get('preview'):
                job_data['background_url'] = paths['preview']

        return job_data
