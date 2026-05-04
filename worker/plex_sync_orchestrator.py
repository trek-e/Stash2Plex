"""
Plex sync orchestration module.

Deep seam for match + confidence policy + metadata apply + confirmed cache write.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from shared.log import create_logger

log_trace, log_debug, log_info, log_warn, log_error = create_logger("PlexSync")


class SyncOutcomeKind(str, Enum):
    SYNCED = "synced"
    SKIPPED_LOW_CONFIDENCE = "skipped_low_confidence"
    RETRYABLE_FAILURE = "retryable_failure"
    PERMANENT_FAILURE = "permanent_failure"


@dataclass(frozen=True)
class SyncOutcome:
    kind: SyncOutcomeKind
    confidence: Optional[str] = None
    warnings: list[str] = field(default_factory=list)
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    retry_hint_seconds: Optional[float] = None


class DefaultMatcherAdapter:
    """Adapter over plex.matcher.find_plex_items_with_confidence."""

    def match(self, *, section: Any, file_path: str, library_cache: Any, match_cache: Any, debug: bool):
        from plex.matcher import find_plex_items_with_confidence  # lazy: imports plexapi

        return find_plex_items_with_confidence(
            section,
            file_path,
            library_cache=library_cache,
            match_cache=match_cache,
            debug_logging=debug,
        )


class DefaultMetadataAdapter:
    """Adapter over worker.metadata_updater.MetadataUpdater."""

    def __init__(self, metadata_updater):
        self.metadata_updater = metadata_updater

    def apply(self, *, plex_item: Any, scene_data: dict):
        return self.metadata_updater.update(plex_item, scene_data)


class DefaultCacheAdapter:
    """Adapter for confirmed match cache writes after successful metadata apply."""

    def __init__(self, match_cache: Any):
        self.match_cache = match_cache

    def record_confirmed_match(self, *, section_title: str, file_path: str, item: Any) -> None:
        if self.match_cache is None:
            return
        item_key = getattr(item, 'key', None) or str(getattr(item, 'ratingKey', None))
        if item_key:
            self.match_cache.set_match(section_title, file_path, item_key)


class PlexSyncOrchestrator:
    """Coordinates candidate matching and metadata update for one scene sync."""

    def __init__(self, *, matcher_adapter: Any, metadata_adapter: Any, cache_adapter: Optional[Any], config: Any):
        self.matcher = matcher_adapter
        self.metadata = metadata_adapter
        self.cache = cache_adapter
        self.config = config

    def sync_scene_to_plex(
        self,
        *,
        scene_id: int,
        scene_data: dict,
        file_path: str,
        sections: list[Any],
        library_cache: Any = None,
        match_cache: Any = None,
        debug: bool = False,
    ) -> SyncOutcome:
        from plex.exceptions import PlexNotFound  # lazy: circular import guard
        from validation.obfuscation import obfuscate_path  # lazy

        all_candidates = []
        section_by_candidate_key: dict[str, str] = {}

        for section in sections:
            try:
                _, _, candidates = self.matcher.match(
                    section=section,
                    file_path=file_path,
                    library_cache=library_cache,
                    match_cache=match_cache,
                    debug=debug,
                )
                all_candidates.extend(candidates)
                for candidate in candidates:
                    section_by_candidate_key[candidate.key] = section.title
                if debug:
                    log_info(f"[DEBUG] Section '{section.title}': {len(candidates)} candidate(s)")
            except PlexNotFound:
                if debug:
                    log_info(f"[DEBUG] Section '{section.title}': no match")
                continue

        seen_keys = set()
        unique_candidates = []
        for candidate in all_candidates:
            if candidate.key not in seen_keys:
                seen_keys.add(candidate.key)
                unique_candidates.append(candidate)

        if debug:
            log_info(
                f"[DEBUG] Dedup: {len(all_candidates)} total -> {len(unique_candidates)} unique candidate(s)"
            )

        if len(unique_candidates) == 0:
            raise PlexNotFound(f"Could not find Plex item for path: {obfuscate_path(file_path)}")

        if len(unique_candidates) == 1:
            plex_item = unique_candidates[0]
            if debug:
                log_info(f"[DEBUG] HIGH confidence match: {plex_item.title}")
            apply_result = self.metadata.apply(plex_item=plex_item, scene_data=scene_data)
            if self.cache is not None:
                section_title = section_by_candidate_key.get(plex_item.key)
                if section_title:
                    self.cache.record_confirmed_match(
                        section_title=section_title,
                        file_path=file_path,
                        item=plex_item,
                    )

            warnings = []
            if apply_result is not None and getattr(apply_result, 'has_warnings', False):
                warnings.append(getattr(apply_result, 'warning_summary', 'partial_sync'))
            return SyncOutcome(kind=SyncOutcomeKind.SYNCED, confidence='high', warnings=warnings)

        paths = [
            c.media[0].parts[0].file if c.media and c.media[0].parts else c.key
            for c in unique_candidates
        ]
        obfuscated_paths = [obfuscate_path(p) for p in paths]
        if self.config.strict_matching:
            log_warn(
                f"LOW CONFIDENCE SKIPPED: scene {scene_id} "
                f"Stash path: {obfuscate_path(file_path)} "
                f"Plex candidates ({len(unique_candidates)}): {obfuscated_paths}"
            )
            return SyncOutcome(
                kind=SyncOutcomeKind.SKIPPED_LOW_CONFIDENCE,
                confidence='low',
                error_type='LowConfidence',
                error_message='Low confidence match skipped (strict_matching=true)',
            )

        plex_item = unique_candidates[0]
        log_warn(
            f"LOW CONFIDENCE SYNCED: scene {scene_id} "
            f"Chosen: {obfuscated_paths[0]} "
            f"Other candidates: {obfuscated_paths[1:]}"
        )
        apply_result = self.metadata.apply(plex_item=plex_item, scene_data=scene_data)
        warnings = []
        if apply_result is not None and getattr(apply_result, 'has_warnings', False):
            warnings.append(getattr(apply_result, 'warning_summary', 'partial_sync'))
        return SyncOutcome(kind=SyncOutcomeKind.SYNCED, confidence='low', warnings=warnings)
