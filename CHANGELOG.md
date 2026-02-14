# Changelog

All notable changes to Stash2Plex will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.4.2] - 2026-02-14

### Added

- **Configurable Missing Detection**: New `reconcile_missing` setting (default: true) to enable/disable "missing from Plex" detection during reconciliation. Disable when your Stash library is a superset of Plex to prevent noise from scenes that intentionally have no Plex match.

### Configuration

- `reconcile_missing` - Include "missing from Plex" detection in reconciliation (default: true)

## [1.4.1] - 2026-02-14

### Changed

- **Shared Logging Module**: Extracted duplicated Stash log functions from 6 files into `shared/log.py` with `create_logger()` factory.
- **Shared Scene Extractor**: Consolidated duplicated scene-to-job-data transformation from 3 files into `validation/scene_extractor.py`.
- **Refactored Gap Detection Engine**: Broke `_build_plex_data()` into focused setup methods (`_connect_to_plex()`, `_init_caches()`, `_get_library_sections()`).
- **Refactored Task Dispatch**: Replaced 157-line `handle_task()` with dispatch table and separate `handle_bulk_sync()` function.
- **Refactored Metadata Sync**: Broke 347-line `_update_metadata()` into focused field sync methods (`_build_core_edits()`, `_sync_performers()`, `_upload_image()`, `_sync_tags()`, `_sync_collection()`).

## [1.4.0] - 2026-02-14

### Added

- **Gap Detection Engine**: Detects three types of metadata gaps between Stash and Plex — empty metadata (Plex has no data but Stash does), stale syncs (Stash updated since last sync), and missing items (Stash scenes with no Plex match). Uses batch processing and deduplication for large libraries.
- **Manual Reconciliation Tasks**: Three new Stash UI tasks — "Reconcile Library (All)", "Reconcile Library (Recent)", and "Reconcile Library (Last 7 Days)" — to detect and queue metadata gaps on demand. Logs progress summary with gap counts by type.
- **Auto-Reconciliation Scheduler**: Automatic gap detection using check-on-invocation pattern (no threads/timers needed). Triggers on Stash startup (if >1 hour since last run, recent scope) and at configurable intervals.
- **Enhanced Queue Status**: "View Queue Status" now displays reconciliation history — last run time, scope, scenes checked, gaps found by type (empty/stale/missing), and enqueued count.
- **Configurable Reconciliation Settings**: `reconcile_interval` (never/hourly/daily/weekly, default: never) and `reconcile_scope` (all/24h/7days, default: 24h) settings in Stash plugin UI.

### Configuration

- `reconcile_interval` - Auto-reconciliation interval (never/hourly/daily/weekly, default: never)
- `reconcile_scope` - Default scope for auto-reconciliation (all/24h/7days, default: 24h)

## [1.3.4] - 2026-02-09

### Fixed

- **Identification Events Blocked by Scan Gate**: Fixed metadata sync never firing after stash-box identification. The entry point correctly bypassed the scan-running gate for identification events, but `on_scene_update()` had its own scan-running check without the same bypass — causing the identify job (still in Stash's job queue) to block the very metadata sync it should trigger. Now passes `is_identification` flag through to skip the redundant gate.
- **Redundant Plex Scan on Identification**: Removed duplicate `trigger_plex_scan_for_scene()` call during identification events. `Scene.Create.Post` already triggers the Plex scan when the file is first discovered; the identification path no longer triggers a second scan.

## [1.3.3] - 2026-02-08

### Fixed

- **Batch Processor Backpressure**: Added 0.15s pause between jobs in the batch processor (`Process Queue` task) to prevent overwhelming Plex with rapid API calls. Previously had no throttle, causing circuit breaker trips around item 160+ during large batch syncs.
- **Debug Logging Visibility**: Debug-gated log messages (`debug_logging=true`) now appear in Stash UI. Previously used `log_debug()` which Stash filters out, making the debug logging feature effectively broken. All 19 instances across processor and matcher promoted to `log_info()` with `[DEBUG]` prefix.
- **Silent Batch Errors**: TransientError in batch processor now logs at WARN level with error details. Previously logged at DEBUG level, making circuit breaker failures invisible.
- **Circuit Breaker Cause**: Circuit breaker OPEN message now includes the last error type and message (e.g., "Circuit breaker OPEN — Plex may be unavailable (last error: ReadTimeout: read timed out)").

### Added

- **Configurable Max Tags**: New `max_tags` setting (default: 100, range: 10-500) replaces the hardcoded limit of 50 tags per Plex item. Scenes with many tags (50-89 was common) no longer trigger excessive truncation warnings.

### Configuration

- `max_tags` - Maximum number of tags/genres to sync per Plex item (default: 100)

## [1.3.2] - 2026-02-08

### Added

- **Debug Logging Mode**: New `debug_logging` setting enables verbose step-by-step logging for troubleshooting. Logs detailed information about queue polling, circuit breaker state, matching decisions, metadata comparisons, and API calls.
- **Path Obfuscation**: New `obfuscate_paths` setting replaces file paths in logs with deterministic word substitutions for privacy when sharing logs.

### Fixed

- **Background Image Sync**: Fixed background/fanart images not syncing to Plex.
- **Poster Upload Reliability**: Improved image fetching from Stash with proper authentication headers.

### Configuration

- `debug_logging` - Enable verbose debug logging (default: false)
- `obfuscate_paths` - Obfuscate file paths in logs for privacy (default: false)

## [1.3.1] - 2026-02-07

### Fixed

- **Identification Events Blocked**: Fixed `Scene.Update.Post` events from stash-box identification being blocked by the scan-running gate. Identification events now pass through correctly even during library scans.

## [1.3.0] - 2026-02-07

### Added

- **Multi-Library Support**: New comma-separated `plex_library` format (e.g., `"Adult, Movies, TV Shows"`). Stash2Plex searches only configured libraries instead of all.

### Fixed

- **O(n²) Reprocessing**: Fixed queue items being reprocessed exponentially due to nack-without-ack cycle. Items now properly acknowledge before requeue.
- **Queue Doubling**: Fixed duplicate jobs created when items were nacked and re-enqueued simultaneously.
- **Stuck Queue Items**: Fixed items stuck in "active" state after worker restart, blocking queue processing.
- **Server-Down Handling**: Clean handling when Plex is unreachable — no DLQ entries, no traceback spam. Transient connection errors now retry gracefully.
- **Queue Empty Exception**: Fixed catching wrong `Empty` exception (`queue.Empty` vs `persistqueue.exceptions.Empty`).
- **Clear Queue Errors**: Fixed clear queue task causing worker errors and stale processing loop.

### Configuration

- `plex_library` now accepts comma-separated values for multiple libraries

## [1.2.7] - 2026-02-06

### Fixed

- **PEP 668 Externally Managed Environment**: pip fallback now passes `--break-system-packages` to handle Python 3.12+ on Alpine/Debian/Ubuntu containers that block system-wide pip installs. Also updated the actionable error message to include the flag so manual installs work on first try.

## [1.2.6] - 2026-02-05

### Fixed

- **Exponentially Inflated Stats**: Fixed `save_to_file` double-counting cumulative stats on every save. Stats were merged with existing file values even though the in-memory stats already contained the loaded totals, causing counts to grow exponentially (reaching 10^32 after enough save cycles). Now uses simple overwrite since `load_from_file` already provides the cumulative base.

## [1.2.5] - 2026-02-05

### Fixed

- **Plex Read Timeouts During Bulk Sync**: Consolidated up to 6 `plex_item.reload()` calls per job into a single deferred reload, reducing HTTP roundtrips by ~5 per scene. Added `requests.Session` for connection pooling/keep-alive and a 150ms inter-job pause to prevent overwhelming Plex with rapid-fire requests.
- **Job ID Logging**: Fixed `Job None completed` in worker logs. Jobs now get monotonically increasing IDs for log correlation.
- **Redundant Metadata Updates**: Core metadata fields (title, studio, summary, tagline, date) are now compared against current Plex values before writing. Skips the Plex API call entirely when nothing changed.

## [1.2.4] - 2026-02-05

### Improved

- **Bulk Sync Skips Already-Synced Scenes**: "Sync Recent Scenes" and "Sync All Scenes" now use sync timestamps to skip scenes that haven't changed since their last successful sync. Dramatically speeds up repeated bulk syncs by only processing scenes that actually need updating.

## [1.2.3] - 2026-02-05

### Fixed

- **Stash-box Identification Race Condition**: Prevented empty metadata from being synced to Plex when `Scene.Update.Post` fires before stash-box identification completes. A metadata quality gate now defers sync when no meaningful metadata (studio, performers, tags, details, date) is present, allowing the post-identification update to carry the real data.

## [1.2.2] - 2026-02-05

### Fixed

- **Robust Dependency Installation**: Replaced fragile dependency loading with three-step approach: PythonDepManager → pip fallback → actionable error message. Fixes `ModuleNotFoundError` when PythonDepManager fails or dependencies are installed to the wrong Python.
- **requirements.txt as Source of Truth**: Dependencies are now parsed from `requirements.txt` instead of being hardcoded in three separate places. Adding a dependency only requires updating `requirements.txt`.
- **Broader Exception Handling**: `ensure_import()` errors (network failures, permission issues) are now caught properly instead of only catching `ImportError`.
- **Actionable Error Messages**: When dependencies can't be installed, the error now shows the exact Python path Stash is using and the exact `pip install` command to run.

## [1.2.1] - 2026-02-04

### Fixed

- **Docker Dependency Installation**: Fixed dependencies not auto-installing in Docker environments. PythonDepManager requires explicit `ensure_import()` calls rather than reading `requirements.txt`. Plugin now properly calls `ensure_import()` at startup to install pydantic, plexapi, tenacity, persist-queue, diskcache, and stashapi.

## [1.2.0] - 2026-02-04

### Added

- **Queue Status Task**: View pending queue count, DLQ count, and error summary directly from Stash UI
- **Clear Queue Task**: Delete all pending queue items with confirmation dialog
- **Clear DLQ Task**: Remove all dead letter queue entries with confirmation
- **Purge DLQ Task**: Remove DLQ entries older than 7 days
- **Process Queue Task**: Manually trigger foreground queue processing that runs until empty (no timeout limits)
- **Progress Feedback**: Processing shows progress every 5 items or 10 seconds during manual queue processing
- **Smart Timeout Calculation**: Dynamic timeout based on measured average processing time per item
- **Cold Start Handling**: Conservative 2.0s/item estimate when no history available, gradually trusting measured data

### Changed

- **Timeout Guidance**: When queue processing times out, message now guides users to use "Process Queue" task to continue
- **Timeout Clamping**: Calculated timeout clamped to 30-600 second range for safety

### Configuration

- 5 new tasks available in Stash plugin menu:
  - View Queue Status
  - Clear Pending Queue
  - Clear Dead Letter Queue
  - Purge Old DLQ Entries
  - Process Queue

## [1.1.6] - 2026-02-03

### Fixed

- **Scene.Create.Post During Scans**: Fixed `trigger_plex_scan` not working because Scene.Create.Post hooks were being skipped during active Stash scans. Now allows Scene.Create.Post through to trigger Plex scan for new files.

## [1.1.5] - 2026-02-03

### Added

- **Plex Library Scan Trigger**: New `trigger_plex_scan` setting that triggers a Plex library scan when Stash identifies a new scene. This ensures Plex discovers files added via Stash before metadata sync occurs.
- **Scene.Create.Post Hook**: Plugin now listens for new scene creation events to trigger Plex scans immediately when files are discovered.

### Configuration

- `trigger_plex_scan` - Enable automatic Plex library scans when Stash identifies scenes (default: false)

## [1.1.4] - 2026-02-03

### Changed

- **Batch Scene Fetching**: Instead of making individual GraphQL calls per scene, all scene data is now fetched in a single batch query. This prevents Stash from killing the plugin due to timeout when processing large queues.

## [1.1.3] - 2026-02-03

### Added

- **Dynamic Queue Timeout**: Processing timeout now scales based on queue size (~2s per item, min 30s, max 600s)
- **Progress Logging**: Queue processing logs progress every 10 items

### Changed

- **Timeout Recovery**: Better timeout error message with recovery instructions

## [1.1.2] - 2026-02-03

### Fixed

- **Log Noise**: Sanitization messages (for cleaning invisible characters) now log at debug level instead of warning, reducing false error noise in Stash logs

## [1.1.1] - 2026-02-03

### Fixed

- **Job Validation**: Path, poster_url, and background_url fields are now correctly included in sanitized job data, fixing "missing file path" errors

## [1.1.0] - 2026-02-03

### Added

- **Metadata Sync Toggles**: Selectively enable/disable syncing for each field type (studio, summary, tagline, date, performers, tags, poster, background, collection)
- **Master Sync Toggle**: Single setting to disable all field syncing while keeping the plugin active
- **Performance Caching**: Disk-backed caching for Plex library data (1-hour TTL) and match results, reducing API calls significantly
- **Sync Statistics**: Track success/failure counts, timing metrics, and match confidence with batch summary logging every 10 jobs
- **Stats Persistence**: Statistics saved to `stats.json` for cross-session tracking
- **Partial Failure Recovery**: Per-field error handling so one field failure doesn't fail the entire sync
- **Response Validation**: Detect silent Plex API failures by validating responses
- **Field Limits**: Enforce Plex field length limits with automatic truncation
- **Emoji Sanitization**: Optional stripping of emojis from metadata (configurable)
- **Persistent Device Identity**: Stash2Plex now appears as a consistent device in Plex, eliminating "new device" notifications
- **Comprehensive Test Suite**: 500+ tests with >80% code coverage
- **Documentation**: Complete user guide, architecture documentation, and API reference (MkDocs)

### Changed

- **Missing Fields Behavior**: When a field is present in Stash data but empty/null, it now clears the existing Plex value (previously preserved)
- **Improved Logging**: Structured batch summaries with JSON output for log aggregation tools

### Fixed

- **"New Device" Spam**: Plex no longer shows new device notifications on each sync operation

## [1.0.0] - 2026-02-03

### Added

- **Persistent Queue**: SQLite-backed queue that survives Stash restarts
- **Automatic Retry**: Failed syncs retry with exponential backoff and jitter
- **Circuit Breaker**: Protects Plex from being hammered when it's unavailable
- **Dead Letter Queue**: Permanently failed jobs stored for manual review
- **Crash Recovery**: In-progress jobs automatically resume after restart
- **Confidence Scoring**: HIGH/LOW confidence matching to avoid false positives
- **Late Update Detection**: Catches metadata changes after initial sync
- **Hook Handler**: Fast (<100ms) event capture that doesn't block Stash
- **Input Validation**: Pydantic-based validation prevents bad data from reaching Plex API

### Configuration

- `plex_url` - Plex server URL (required)
- `plex_token` - Plex authentication token (required)
- `plex_library` - Plex library name (recommended)
- `enabled` - Enable/disable the plugin
- `max_retries` - Maximum retry attempts before DLQ
- `poll_interval` - Seconds between queue polls
- `strict_matching` - Skip sync when multiple matches found
- `preserve_plex_edits` - Don't overwrite existing Plex values
- `connect_timeout` - Plex connection timeout
- `read_timeout` - Plex read timeout

[1.3.3]: https://github.com/trek-e/Stash2Plex/compare/v1.3.2...v1.3.3
[1.3.2]: https://github.com/trek-e/Stash2Plex/compare/v1.3.1...v1.3.2
[1.3.1]: https://github.com/trek-e/Stash2Plex/compare/v1.3.0...v1.3.1
[1.3.0]: https://github.com/trek-e/Stash2Plex/compare/v1.2.7...v1.3.0
[1.2.7]: https://github.com/trek-e/Stash2Plex/compare/v1.2.6...v1.2.7
[1.2.6]: https://github.com/trek-e/Stash2Plex/compare/v1.2.5...v1.2.6
[1.2.5]: https://github.com/trek-e/Stash2Plex/compare/v1.2.4...v1.2.5
[1.2.4]: https://github.com/trek-e/Stash2Plex/compare/v1.2.3...v1.2.4
[1.2.3]: https://github.com/trek-e/Stash2Plex/compare/v1.2.2...v1.2.3
[1.2.2]: https://github.com/trek-e/Stash2Plex/compare/v1.2.1...v1.2.2
[1.2.1]: https://github.com/trek-e/Stash2Plex/compare/v1.2.0...v1.2.1
[1.2.0]: https://github.com/trek-e/Stash2Plex/compare/v1.1.6...v1.2.0
[1.1.6]: https://github.com/trek-e/Stash2Plex/compare/v1.1.5...v1.1.6
[1.1.5]: https://github.com/trek-e/Stash2Plex/compare/v1.1.4...v1.1.5
[1.1.4]: https://github.com/trek-e/Stash2Plex/compare/v1.1.3...v1.1.4
[1.1.3]: https://github.com/trek-e/Stash2Plex/compare/v1.1.2...v1.1.3
[1.1.2]: https://github.com/trek-e/Stash2Plex/compare/v1.1.1...v1.1.2
[1.1.1]: https://github.com/trek-e/Stash2Plex/compare/v1.1.0...v1.1.1
[1.1.0]: https://github.com/trek-e/Stash2Plex/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/trek-e/Stash2Plex/releases/tag/v1.0.0
