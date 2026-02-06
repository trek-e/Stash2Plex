# Changelog

All notable changes to Stash2Plex will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
