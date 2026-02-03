# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2025-01-24)

**Core value:** Reliable sync — when metadata changes in Stash, it eventually reaches Plex
**Current focus:** Phase 4 COMPLETE, ready for Phase 5

## Current Position

Phase: 5 of 5 (Late Update Detection) - IN PROGRESS
Plan: 2 of 3 in current phase
Status: Plan 05-02 complete
Last activity: 2026-02-03 — Completed 05-02-PLAN.md

Progress: [██████████████░] 95% (15/~16 plans)

## Performance Metrics

**Velocity:**
- Total plans completed: 15
- Average duration: 2.4 min
- Total execution time: 0.61 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 1. Persistent Queue Foundation | 3 | 9 min | 3 min |
| 2. Validation & Error Classification | 3 | 7 min | 2.3 min |
| 3. Plex API Client | 3 | 9 min | 3 min |
| 4. Queue Processor with Retry | 4 | 9 min | 2.25 min |
| 5. Late Update Detection | 2 | 4.5 min | 2.25 min |

**Recent Trend:**
- Last 5 plans: 04-03 (3min), 04-04 (2min), 05-01 (2.5min), 05-02 (2min)
- Trend: Stable

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

**From 05-02 (Deduplication and Confidence Scoring):**
- In-memory set for dedup (resets on restart - acceptable tradeoff for <100ms hook requirement)
- Binary confidence scoring: HIGH for single match, LOW for multiple candidates
- PlexNotFound raised when no matches (enables existing retry logic)
- Candidate deduplication uses ratingKey to avoid false LOW confidence

**From 05-01 (Sync Timestamp Infrastructure):**
- Sync timestamps stored in JSON file alongside queue database (sync_timestamps.json)
- Atomic writes via temp file + os.replace for crash safety
- strict_matching defaults to True (safer - skip low-confidence matches)
- preserve_plex_edits defaults to False (Stash is source of truth)

**From 04-04 (DLQ Monitoring):**
- Log DLQ status every 10 jobs (not time-based) for predictable monitoring
- DLQ cleanup runs before status logging on startup (see clean state)
- Cleanup uses config.dlq_retention_days with 30-day default fallback

**From 04-03 (Retry Orchestration):**
- Re-enqueue pattern: ack + put instead of nack for metadata updates
- Small 0.1s delay after nack to avoid tight loop on not-ready jobs
- Permanent errors don't count against circuit breaker
- Job metadata pattern: retry_count, next_retry_at, last_error_type in job dict

**From 04-02 (Circuit Breaker & DLQ Config):**
- Default failure_threshold=5 before circuit opens
- Default recovery_timeout=60s before half-open transition
- DLQ retention range 1-365 days with 30-day default

**From 04-01 (Exponential Backoff):**
- Use seeded random.Random for deterministic testing
- PlexNotFound gets 30s base, 600s cap, 12 retries (~2hr window)
- Standard errors get 5s base, 80s cap, 5 retries
- Lazy import of PlexNotFound to avoid circular dependencies

**From 03-03 (Worker Plex Integration):**
- Mock _get_plex_client method in tests to avoid queue module shadowing issue
- Lazy imports in _process_job to avoid circular imports
- Search all library sections to find items (can optimize later)

**From 03-02 (PlexClient Wrapper):**
- Lazy imports for plexapi/requests to avoid queue module shadowing stdlib
- Retry decorator applied inside method for lazy exception loading
- Return None on ambiguous filename matches instead of guessing
- Use read_timeout as PlexServer timeout (PlexAPI uses single timeout, not tuple)

**From 03-01 (Plex Exception Hierarchy):**
- PlexNotFound subclasses TransientError - items may appear after library scan
- Lazy imports for plexapi/requests in translate_plex_exception
- Unknown errors default to PlexTemporaryError (safer, allows retry)
- Timeout ranges constrained: connect 1-30s, read 5-120s

**From 02-03 (Config Validation):**
- Token masking shows first/last 4 chars for debugging while protecting secret
- Env var fallback (PLEX_URL, PLEX_TOKEN) enables local dev without Stash
- Multiple Stash config locations supported for version compatibility
- Tunables have constrained ranges: max_retries 1-20, poll_interval 0.1-60s

**From 02-02 (Metadata Validation):**
- Separate validators per field type (title required vs optional fields)
- validate_metadata returns tuple (model, error) not exception
- Skip validation when no title present (worker can lookup)
- Pydantic field_validator mode='before' for sanitization

**From 02-01 (Validation Utilities):**
- Use unicodedata stdlib for sanitization (no external dependencies)
- Word boundary truncation at 80% of max_length threshold
- Unknown errors default to transient (safer, allows retry)
- Error classification returns exception class, not instance

**From 01-03 (Hook Handler & Background Worker):**
- Hook handler completes in <100ms by filtering and enqueueing only
- Worker runs in daemon thread with 10-second timeout on get_pending
- Worker tracks retry counts per pqid for max_retries enforcement
- Unknown errors treated as transient (nack for retry)
- Process job stubbed for Phase 3 Plex API implementation
- Plugin initializes on first stdin input, not on import

**From 01-02 (Dead Letter Queue):**
- Separate DLQ database (dlq.db) from main queue for long retention
- Store full job_data as pickled BLOB for complete error context
- 30-day default retention period for DLQ cleanup

**From 01-01 (Queue Infrastructure):**
- Used persist-queue SQLiteAckQueue for built-in crash recovery (vs custom SQLite queue)
- Queue stored in $STASH_PLUGIN_DATA or ~/.stash/plugins/PlexSync/data
- Dict-compatible SyncJob structure for safe pickle serialization
- Stateless operations pattern - functions receive queue instance

**Prior decisions:**
- Fork locally for development (Pending) — Need to test changes against real Stash/Plex setup

### Pending Todos

None.

### Blockers/Concerns

None.

## Session Continuity

Last session: 2026-02-03T05:15:24Z
Stopped at: Completed 05-02-PLAN.md
Resume file: None

## Completed Phases

### Phase 5: Late Update Detection (IN PROGRESS - Started 2026-02-03)
**Plans completed:** 2/3
**Commits:** 01a2e61 → 848b708 (4 commits total, 2 in 05-01, 2 in 05-02)
**Completed plans:**
- 05-01: Sync timestamp infrastructure (sync_timestamps.json) and config flags (strict_matching, preserve_plex_edits)
- 05-02: In-memory deduplication tracking and confidence-scored matching (MatchConfidence enum, find_plex_items_with_confidence)

### Phase 4: Queue Processor with Retry (Complete 2026-01-24)
**Verification:** PASSED (all must-haves)
**Commits:** e1e9adc → 517fa83 (2 commits in 04-04, 8 total in phase)
**Key deliverables:**
- Exponential backoff with jitter (5s base, 80s cap for standard; 30s base, 600s cap for PlexNotFound)
- Circuit breaker with CLOSED/OPEN/HALF_OPEN states
- Retry orchestration with crash-safe job metadata
- DLQ monitoring: status logging on startup and every 10 jobs
- Automatic DLQ cleanup using config retention days
- 46 tests for retry components

### Phase 3: Plex API Client (Complete 2026-01-24)
**Verification:** PASSED (all must-haves)
**Commits:** 20e4b5f → 7613fba (6 commits total in phase)
**Key deliverables:**
- PlexTemporaryError, PlexPermanentError, PlexNotFound exception hierarchy
- translate_plex_exception for error classification
- PlexClient wrapper with lazy init, timeouts, and retry
- find_plex_item_by_path with 3 fallback strategies
- Worker integration: _process_job now does real Plex sync
- 17 integration tests

### Phase 2: Validation & Error Classification (Complete 2026-01-24)
**Verification:** PASSED (all must-haves)
**Commits:** 41f14b2 → 7a715c6 (8 commits)
**Key deliverables:**
- Text sanitization with Unicode normalization and smart truncation
- Error classification for retry/DLQ routing
- SyncMetadata pydantic model for metadata validation
- PlexSyncConfig model with fail-fast config validation
- Masked token logging for security
- Config extraction from Stash input with env var fallback

### Phase 1: Persistent Queue Foundation (Complete 2026-01-24)
**Verification:** PASSED (6/6 must-haves)
**Commits:** 9ae922a → 6922352 (12 commits)
**Key deliverables:**
- SQLiteAckQueue with crash recovery (auto_resume=True)
- Dead letter queue for permanently failed jobs
- Hook handler with <100ms enqueue
- Background worker with ack/nack/fail workflow
- Plugin entry point (PlexSync.py)
