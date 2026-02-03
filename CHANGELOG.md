# Changelog

All notable changes to Stash2Plex will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

[1.1.0]: https://github.com/trek-e/Stash2Plex/compare/v1.0...v1.1
[1.0.0]: https://github.com/trek-e/Stash2Plex/releases/tag/v1.0
