"""
Gap detection engine orchestrator for Stash-to-Plex reconciliation.

Integrates GapDetector with infrastructure (Stash GQL, Plex matcher, persistent queue)
to orchestrate end-to-end gap detection: fetch scenes, match against Plex, run detectors,
and enqueue discovered gaps.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import os
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any, Optional, TYPE_CHECKING

from reconciliation.detector import GapDetector, GapResult, has_meaningful_metadata

if TYPE_CHECKING:
    from stashapi.stashapp import StashInterface
    from config.config import Stash2PlexConfig

from shared.log import create_logger
_, log_debug, log_info, log_warn, log_error = create_logger("Gap Engine")


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
        skipped_no_metadata: Number of gaps skipped due to quality gate (no meaningful metadata)
        scenes_checked: Total number of scenes checked
        errors: List of non-fatal error messages during detection
    """
    empty_metadata_count: int = 0
    stale_sync_count: int = 0
    missing_count: int = 0
    total_gaps: int = 0
    enqueued_count: int = 0
    skipped_already_queued: int = 0
    skipped_no_metadata: int = 0
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
        queue_manager=None
    ):
        self.stash = stash
        self.config = config
        self.data_dir = data_dir
        self.queue_manager = queue_manager
        self.detector = GapDetector()

    def run(self, scope: str = "all") -> GapDetectionResult:
        """Run gap detection and optionally enqueue discovered gaps.

        Args:
            scope: Scope of scenes to check:
                - "all": All scenes in library
                - "recent": Scenes added in last 24 hours (by created_at)
                - "recent_7days": Scenes added in last 7 days (by created_at)
                - "missing_metadata": Empty-metadata gaps only (all scenes)

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

            # Optional Plex unmatched pre-filter for missing-metadata scope.
            # Uses Plex API unmatched=1 to avoid scanning the full Stash set.
            if scope == "missing_metadata":
                use_unmatched = os.getenv("STASH2PLEX_RECONCILE_USE_PLEX_UNMATCHED", "1").lower() not in ("0", "false", "no")
                if use_unmatched:
                    try:
                        unmatched_paths = self._fetch_plex_unmatched_paths()
                        if unmatched_paths:
                            before = len(scenes)
                            scenes = [
                                s for s in scenes
                                if (s.get('files') and s['files'][0].get('path') in unmatched_paths)
                            ]
                            log_info(
                                f"Scope 'missing_metadata': filtered by Plex unmatched paths "
                                f"{before} -> {len(scenes)}"
                            )
                    except Exception as e:
                        log_warn(f"Plex unmatched pre-filter failed, continuing full set: {e}")

                # Optional cap after pre-filter (0 disables cap).
                cap = int(os.getenv("STASH2PLEX_RECONCILE_MAX_SCENES", "0") or "0")
                if cap > 0 and len(scenes) > cap:
                    log_info(f"Scope 'missing_metadata': limiting to newest {cap} scenes (of {len(scenes)})")
                    scenes = scenes[:cap]

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

        plex_items_metadata: dict[str, dict[str, Any]] = {}

        # Special path: missing_metadata mode is now driven directly by Plex
        # unmatched list (source of truth), not matcher/cache confidence.
        if scope == "missing_metadata":
            try:
                unmatched_paths = self._fetch_plex_unmatched_paths()
            except Exception as e:
                result.errors.append(f"Failed to fetch Plex unmatched paths: {e}")
                log_error(f"Failed to fetch Plex unmatched paths: {e}")
                return result

            filtered_scenes = [
                s for s in scenes
                if (s.get('files') and s['files'][0].get('path') in unmatched_paths)
            ]
            log_info(
                f"Scope 'missing_metadata': unmatched-driven candidate set "
                f"{len(scenes)} -> {len(filtered_scenes)}"
            )

            # Build gap list directly from unmatched candidates that have
            # meaningful Stash metadata to push.
            empty_gaps = []
            for scene in filtered_scenes:
                if not has_meaningful_metadata(scene):
                    continue
                try:
                    sid = int(scene.get('id'))
                except (TypeError, ValueError):
                    continue
                empty_gaps.append(GapResult(
                    scene_id=sid,
                    gap_type='empty_metadata',
                    scene_data=scene,
                    reason='Plex reports item as unmatched; Stash has meaningful metadata',
                ))

            stale_gaps = []
            missing_gaps = []
            scenes = filtered_scenes
        else:
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
            if getattr(self.config, 'reconcile_missing', True):
                missing_gaps = self.detector.detect_missing(scenes, sync_timestamps, matched_paths)
            else:
                missing_gaps = []
                log_debug("Skipping 'missing from Plex' detection (reconcile_missing=false)")

        result.empty_metadata_count = len(empty_gaps)
        result.stale_sync_count = len(stale_gaps)
        result.missing_count = len(missing_gaps)
        result.total_gaps = result.empty_metadata_count + result.stale_sync_count + result.missing_count

        if scope == "missing_metadata":
            self._log_missing_metadata_diagnostics(scenes, plex_items_metadata, empty_gaps)

        log_info(f"Gaps detected: {result.empty_metadata_count} empty metadata, "
                 f"{result.stale_sync_count} stale, {result.missing_count} missing")

        # Step 6: Enqueue gaps (if queue_manager provided)
        if self.queue_manager is not None:
            try:
                enqueued, skipped, skipped_no_metadata = self._enqueue_gaps(empty_gaps, stale_gaps, missing_gaps)
                result.enqueued_count = enqueued
                result.skipped_already_queued = skipped
                result.skipped_no_metadata = skipped_no_metadata
                msg = f"Enqueued {enqueued} gaps ({skipped} already queued)"
                if skipped_no_metadata > 0:
                    msg += f", {skipped_no_metadata} skipped (no Stash metadata yet — add studio/performers/tags/date to sync)"
                log_info(msg)
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
            created_at
            rating100
            updated_at
            files { path }
            studio { name }
            performers { name }
            tags { name }
            paths { screenshot preview }
        """

        if scope == "recent":
            # Last 24 hours by date added (created_at), not metadata update date
            yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
            log_debug(f"Fetching scenes added since {yesterday}")
            scenes = self.stash.find_scenes(
                f={"created_at": {"value": yesterday, "modifier": "GREATER_THAN"}},
                fragment=fragment
            )
        elif scope == "recent_7days":
            week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
            log_debug(f"Fetching scenes added since {week_ago}")
            scenes = self.stash.find_scenes(
                f={"created_at": {"value": week_ago, "modifier": "GREATER_THAN"}},
                fragment=fragment
            )
        else:  # "all"
            log_debug("Fetching all scenes")
            scenes = self.stash.find_scenes(fragment=fragment)

        scenes = scenes or []

        # Newest-first processing so reconciliation prioritizes recently added files.
        # Primary key: created_at (date added to Stash). Fallback: metadata date.
        def _scene_sort_key(scene: dict[str, Any]) -> tuple[int, str, str]:
            created = scene.get("created_at") or ""
            date_val = scene.get("date") or ""
            scene_id = str(scene.get("id") or "")
            return (1 if created else 0, created, date_val or scene_id)

        scenes.sort(key=_scene_sort_key, reverse=True)
        return scenes

    def _connect_to_plex(self):
        """Connect to Plex server with error translation.

        Returns:
            Connected PlexServer instance.

        Raises:
            PlexServerDown: If Plex server is unreachable.
        """
        from plex.client import PlexClient
        from plex.exceptions import PlexServerDown, translate_plex_exception

        try:
            client = PlexClient(
                url=self.config.plex_url,
                token=self.config.plex_token
            )
            plex = client.server
            log_debug(f"Connected to Plex server: {plex.friendlyName}")
            return plex
        except Exception as e:
            translated = translate_plex_exception(e)
            if isinstance(translated, PlexServerDown):
                log_error("Plex server is down, aborting gap detection")
                raise PlexServerDown("Plex server unreachable") from e
            raise

    def _init_caches(self):
        """Initialize library and match caches.

        Returns:
            Tuple of (library_cache, match_cache), either may be None on failure.
        """
        from plex.cache import PlexCache, MatchCache

        try:
            return PlexCache(self.data_dir), MatchCache(self.data_dir)
        except Exception as e:
            log_warn(f"Failed to initialize caches, continuing without: {e}")
            return None, None

    def _get_library_sections(self, plex) -> dict[str, Any]:
        """Resolve configured library names to Plex LibrarySection objects.

        Args:
            plex: Connected PlexServer instance.

        Returns:
            Dict of library_name -> LibrarySection.

        Raises:
            Exception: If no libraries could be resolved.
        """
        # plex_libraries is a @property that returns list[str] (empty if plex_library is None)
        libraries = self.config.plex_libraries
        sections = {}
        for lib_name in libraries:
            try:
                sections[lib_name] = plex.library.section(lib_name)
            except Exception as e:
                log_warn(f"Failed to get library '{lib_name}': {e}")

        if not sections:
            raise Exception("No Plex libraries available")
        return sections

    def _parse_unmatched_path_mappings(self) -> list[tuple[str, str]]:
        """Parse plex_unmatched_path_map config into prefix pairs.

        Format: '/plex/prefix=>/stash/prefix; /plex2=>/stash2'
        """
        raw = (getattr(self.config, 'plex_unmatched_path_map', None) or '').strip()
        if not raw:
            return []

        pairs: list[tuple[str, str]] = []
        for item in [x.strip() for x in raw.split(';') if x.strip()]:
            if '=>' not in item:
                log_warn(f"Invalid plex_unmatched_path_map entry (missing '=>'): {item}")
                continue
            src, dst = item.split('=>', 1)
            src = src.strip().rstrip('/')
            dst = dst.strip().rstrip('/')
            if not src or not dst:
                continue
            pairs.append((src, dst))
        return pairs

    def _map_unmatched_path_to_stash(self, plex_path: str, mappings: list[tuple[str, str]]) -> str:
        """Apply configured prefix mapping from Plex path to Stash path."""
        normalized = plex_path.replace('\\\\', '/')
        for src, dst in mappings:
            if normalized.startswith(src + '/') or normalized == src:
                return dst + normalized[len(src):]
        return normalized

    def _fetch_plex_unmatched_paths(self) -> set[str]:
        """Fetch file paths from Plex sections where unmatched=1.

        Returns:
            Set of (optionally mapped) file paths for Stash-side comparison.
        """
        plex = self._connect_to_plex()
        sections = self._get_library_sections(plex)
        mappings = self._parse_unmatched_path_mappings()

        out: set[str] = set()
        for _, section in sections.items():
            section_key = getattr(section, 'key', None)
            if not section_key:
                continue

            params = {
                'unmatched': '1',
                'X-Plex-Token': self.config.plex_token,
            }
            url = f"{self.config.plex_url.rstrip('/')}/library/sections/{section_key}/all?{urllib.parse.urlencode(params)}"
            with urllib.request.urlopen(url, timeout=30) as resp:
                xml_data = resp.read()

            root = ET.fromstring(xml_data)
            for part in root.findall('.//Part'):
                p = part.attrib.get('file')
                if p:
                    out.add(self._map_unmatched_path_to_stash(p, mappings))

        log_info(f"Plex unmatched pre-filter discovered {len(out)} file path(s)")
        if mappings:
            log_info(f"Applied {len(mappings)} unmatched path mapping rule(s)")
        return out

    def _build_plex_data(
        self,
        scenes: list[dict[str, Any]],
        sync_timestamps: dict[int, float]
    ) -> tuple[dict[str, dict[str, Any]], set[str]]:
        """Build Plex metadata dict and matched_paths set.

        Orchestrates: connect to Plex, init caches, resolve libraries,
        then process scenes in batches for memory efficiency.

        Args:
            scenes: Stash scenes to check
            sync_timestamps: Scene ID to timestamp mapping

        Returns:
            Tuple of (plex_items_metadata dict, matched_paths set)

        Raises:
            PlexServerDown: If Plex server is unreachable.
        """
        plex_items_metadata = {}
        matched_paths = set()

        plex = self._connect_to_plex()
        library_cache, match_cache = self._init_caches()
        library_sections = self._get_library_sections(plex)

        # Use configurable batch size (default 100 if not set or invalid)
        try:
            batch_size = int(self.config.reconcile_batch_size)
        except (AttributeError, ValueError, TypeError):
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

            # If scene has sync timestamp, it's already matched to a Plex item.
            # Still need to fetch Plex metadata for empty-metadata detection —
            # a scene may have been synced before metadata was available (e.g.,
            # synced during scan before Auto Tag added performers/studios/tags).
            if int(scene_id) in sync_timestamps:
                matched_paths.add(file_path)
                # Fall through to matcher below to also get Plex metadata

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
        - rating100: userRating on 0-100 scale

        Note: rating100 is extracted for completeness but NOT used by
        has_meaningful_metadata() quality gate (see detector.py for rationale).

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

        # Rating (Plex userRating is 0.0-10.0, convert to 0-100)
        user_rating = getattr(plex_item, 'userRating', None)
        if user_rating is not None:
            try:
                metadata['rating100'] = int(float(user_rating) * 10)
            except (ValueError, TypeError):
                # Skip if userRating is not a valid number
                pass

        return metadata

    def _log_missing_metadata_diagnostics(
        self,
        scenes: list[dict[str, Any]],
        plex_items_metadata: dict[str, dict[str, Any]],
        empty_gaps: list,
    ) -> None:
        """Emit evidence for why scenes were/weren't classified as empty metadata gaps."""
        try:
            gap_ids = {g.scene_id for g in empty_gaps}
            stats = {
                'total_scenes': len(scenes),
                'with_plex_match': 0,
                'stash_has_meaningful': 0,
                'plex_has_core_fields': 0,
                'classified_empty_gap': len(empty_gaps),
            }
            examples = []

            for scene in scenes:
                files = scene.get('files') or []
                if not files:
                    continue
                file_path = files[0].get('path')
                if not file_path:
                    continue

                plex_meta = plex_items_metadata.get(file_path)
                if not plex_meta:
                    continue

                stats['with_plex_match'] += 1
                stash_meaningful = has_meaningful_metadata(scene)
                if stash_meaningful:
                    stats['stash_has_meaningful'] += 1

                plex_has_core = any([
                    bool(plex_meta.get('studio')),
                    bool(plex_meta.get('performers')),
                    bool(plex_meta.get('tags')),
                    bool(plex_meta.get('details')),
                ])
                if plex_has_core:
                    stats['plex_has_core_fields'] += 1

                try:
                    sid = int(scene.get('id'))
                except Exception:
                    sid = None

                if len(examples) < 20:
                    examples.append({
                        'scene_id': sid,
                        'in_empty_gap': bool(sid in gap_ids) if sid is not None else False,
                        'stash_meaningful': stash_meaningful,
                        'plex_flags': {
                            'studio': bool(plex_meta.get('studio')),
                            'performers': bool(plex_meta.get('performers')),
                            'tags': bool(plex_meta.get('tags')),
                            'details': bool(plex_meta.get('details')),
                            'date': bool(plex_meta.get('date')),
                        },
                    })

            log_info(f"Missing-metadata diagnostics: {stats}")
            for ex in examples:
                log_info(f"Missing-metadata sample: {ex}")
        except Exception as e:
            log_warn(f"Missing-metadata diagnostics failed: {e}")

    def _enqueue_gaps(
        self,
        empty_gaps: list,
        stale_gaps: list,
        missing_gaps: list
    ) -> tuple[int, int, int]:
        """Enqueue discovered gaps as sync jobs.

        Deduplicates:
        - Against scenes already in queue (via get_queued_scene_ids)
        - Against scenes already synced (via sync_timestamps — persistent guard not
          bounded by queue row age, preventing re-enqueue after 24h+ sessions)
        - Across gap types (same scene may appear in multiple lists)

        Args:
            empty_gaps: List of GapResult from detect_empty_metadata
            stale_gaps: List of GapResult from detect_stale_syncs
            missing_gaps: List of GapResult from detect_missing

        Returns:
            Tuple of (enqueued_count, skipped_already_queued, skipped_no_metadata)
        """
        from sync_queue.operations import load_sync_timestamps
        from datetime import datetime

        # Load sync timestamps for persistent already-synced guard.
        # This is the primary defence against infinite requeue: if a scene has a
        # sync_timestamp >= its Stash updated_at, it was already synced with current
        # data and must not be re-enqueued regardless of how old its queue row is.
        sync_timestamps = load_sync_timestamps(self.data_dir)

        enqueued_count = 0
        skipped_count = 0
        skipped_no_metadata_count = 0

        # Combine all gaps
        all_gaps = list(empty_gaps) + list(stale_gaps) + list(missing_gaps)

        for gap in all_gaps:
            scene_id = gap.scene_id
            scene_data = gap.scene_data

            # Persistent already-synced guard: skip if sync_timestamp >= updated_at.
            # This prevents re-enqueue of scenes processed in sessions older than the
            # queue completed_window — the root cause of the infinite requeue loop.
            # detect_stale_syncs and detect_missing already filter by sync_timestamps
            # before producing gaps, but detect_empty_metadata does not — it re-detects
            # based on current Plex state, which may be empty due to Plex processing lag.
            if scene_id in sync_timestamps:
                updated_at_str = scene_data.get('updated_at')
                if updated_at_str:
                    try:
                        updated_at_epoch = datetime.fromisoformat(
                            updated_at_str.replace('Z', '+00:00')
                        ).timestamp()
                        if sync_timestamps[scene_id] >= updated_at_epoch:
                            log_debug(
                                f"Scene {scene_id} already synced (sync={sync_timestamps[scene_id]:.0f} "
                                f">= updated_at={updated_at_epoch:.0f}), skipping re-enqueue"
                            )
                            skipped_count += 1
                            continue
                    except (ValueError, AttributeError):
                        pass  # Can't parse updated_at — allow enqueue as safe fallback

            # Build job data
            job_data = self._build_job_data(scene_data)
            if job_data is None:
                # Scene has no files, skip
                skipped_count += 1
                continue

            # Quality gate: don't enqueue scenes with no meaningful metadata.
            # Same guard as hooks/handlers.py — prevents syncing empty metadata
            # which would clear existing Plex values.
            if not has_meaningful_metadata(job_data):
                log_debug(f"Scene {scene_id} has no meaningful metadata, skipping enqueue")
                skipped_no_metadata_count += 1
                continue

            # Enqueue via queue_manager — handles both in-memory and cross-session dedup.
            # The in-memory _pending_scene_ids set provides cross-gap-type dedup within
            # this run (same scene can appear in empty, stale, and missing lists).
            result = self.queue_manager.try_enqueue(scene_id, "metadata", job_data)
            if result.enqueued:
                enqueued_count += 1
            else:
                skipped_count += 1

        return enqueued_count, skipped_count, skipped_no_metadata_count

    def _build_job_data(self, scene: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Build job data dict from Stash scene.

        Args:
            scene: Stash scene dict from GQL

        Returns:
            Job data dict, or None if scene has no files
        """
        from validation.scene_extractor import extract_scene_metadata, get_scene_file_path

        file_path = get_scene_file_path(scene)
        if not file_path:
            return None

        job_data = extract_scene_metadata(scene)
        job_data['path'] = file_path
        return job_data
