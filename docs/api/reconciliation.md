# reconciliation

Gap detection and automatic reconciliation between Stash and Plex.

## GapDetectionEngine

Orchestrates end-to-end gap detection: fetch scenes from Stash, match against Plex, run detectors, and enqueue discovered gaps.

::: reconciliation.engine.GapDetectionEngine

### Key Methods

- `detect_gaps(scope)` - Run full detection pipeline for a scope (`all`, `recent`, `recent_7days`)
- `_connect_to_plex()` - Connect with error translation (raises `PlexServerDown`)
- `_build_plex_data(scenes, sync_timestamps)` - Orchestrate Plex matching in batches
- `_process_scene_batch(...)` - Match individual scenes using lighter pre-check strategy

### GapDetectionResult

::: reconciliation.engine.GapDetectionResult

Dataclass summarizing detection results: `empty_metadata_count`, `stale_sync_count`, `missing_count`, `total_gaps`, `enqueued_count`, `scenes_checked`, `errors`.

---

## GapDetector

Pure detection logic with no infrastructure dependencies.

::: reconciliation.detector.GapDetector

### Detection Methods

- `detect_empty_metadata(scenes, plex_metadata)` - Scenes where Plex has no metadata but Stash does
- `detect_stale_syncs(scenes, sync_timestamps)` - Scenes updated in Stash since last sync
- `detect_missing(scenes, sync_timestamps, matched_paths)` - Scenes with no Plex match

### has_meaningful_metadata

::: reconciliation.detector.has_meaningful_metadata

Returns `True` if a scene has at least one non-empty metadata field (studio, performers, tags, details, date). Used by the metadata quality gate to prevent syncing empty scenes.

---

## ReconciliationScheduler

Manages auto-reconciliation timing using a check-on-invocation pattern.

::: reconciliation.scheduler.ReconciliationScheduler

### Key Methods

- `is_due(config)` - Check if scheduled reconciliation is due (based on `reconcile_interval`)
- `is_startup_due()` - Check if startup reconciliation is due (>1 hour since last run)
- `record_run(scope, result)` - Record a completed reconciliation run
- `load_state()` / `save_state()` - Persist state to `reconciliation_state.json`

### ReconciliationState

::: reconciliation.scheduler.ReconciliationState

Dataclass with persisted fields: `last_run_time`, `last_scope`, `last_scenes_checked`, `last_gaps_found`, `last_enqueued`.
