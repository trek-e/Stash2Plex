# PlexSync Improvements

## What This Is

Improvements to the PlexSync plugin for Stash, which syncs metadata from Stash to Plex. The plugin provides reliable, queue-based synchronization with comprehensive test coverage, caching for performance, and granular control over which fields sync.

## Core Value

Reliable sync: when metadata changes in Stash, it eventually reaches Plex — even if Plex was temporarily unavailable or Stash hadn't finished indexing yet.

## Current State (v1.2)

**Shipped:** 2026-02-04

PlexSync v1.2 adds user-facing queue management:
- Queue status viewing and clearing from Stash UI
- Dead letter queue management (clear, purge old entries)
- Process Queue button for foreground processing without timeout limits
- Dynamic timeout based on measured processing times
- 5 new plugin tasks (7 total)
- ~370 lines added

Built on v1.1 foundation:
- 500+ tests with >80% coverage across all modules
- Complete documentation (user guide, architecture, API reference)
- Disk-backed caching reducing Plex API calls
- SyncStats with batch summary logging
- Partial failure recovery with per-field tracking
- Metadata sync toggles for selective field syncing

**Tech stack:** Python 3.9+, SQLite (persist-queue), plexapi, pydantic, diskcache, MkDocs

## Requirements

### Validated (v1.0)

- [x] Retry logic when Plex is unavailable (exponential backoff with jitter, circuit breaker)
- [x] Late update handling — push metadata to Plex when Stash updates after initial sync
- [x] Input sanitization — validate/clean data before sending to Plex API
- [x] Improved matching logic — confidence scoring, reduced false negatives

### Validated (v1.1)

- [x] pytest infrastructure with fixtures for Plex/Stash mocking
- [x] Unit tests for all core modules (queue, worker, matching, validation) — 500+ tests
- [x] Integration tests with mocked Plex/Stash APIs — 62 integration tests
- [x] Coverage reporting and CI integration — >80% enforced
- [x] User guide: installation, configuration, troubleshooting
- [x] Architecture docs: component diagrams, data flow, design decisions
- [x] API reference: auto-generated from docstrings (MkDocs)
- [x] Plex library caching to reduce API calls (diskcache, 1-hour TTL)
- [x] Optimized matching with match result caching
- [x] Structured logging with batch summary every 10 jobs
- [x] Sync statistics and metrics (SyncStats, JSON output)
- [x] Edge case handling (unicode, special characters, long titles, field limits)
- [x] Partial failure recovery with per-field error tracking
- [x] Metadata sync toggles (enable/disable each field category)

### Validated (v1.2)

- [x] Queue Management UI — view status, clear queue, clear/purge DLQ from Stash UI
- [x] Process Queue Button — foreground processing until queue empty
- [x] Dynamic Queue Timeout — timeout based on item count × avg processing time

### Out of Scope

- Plex → Stash sync — Stash remains the primary metadata source
- Bi-directional sync — complexity outweighs benefit for current use case
- Mobile/web UI — Stash plugin UI is sufficient

## Context

**Source:** https://github.com/stashapp/CommunityScripts/tree/main/plugins/PlexSync

## Constraints

- **Compatibility**: Must work with existing Stash plugin architecture
- **Dependencies**: Minimize new dependencies (added diskcache for v1.1 caching)

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| persist-queue for SQLite queue | Built-in crash recovery vs custom SQLite queue | v1.0 |
| Job metadata for sync state | Simpler than separate SQLite table | v1.0 |
| JSON file for timestamps | sync_timestamps.json with atomic writes | v1.0 |
| Confidence scoring | HIGH/LOW based on match uniqueness | v1.0 |
| PlexNotFound as transient | Items may appear after library scan | v1.0 |
| 80% coverage threshold | Enforced via --cov-fail-under | v1.1 |
| unittest.mock over pytest-mock | Avoid external dependencies in conftest.py | v1.1 |
| 1-hour TTL for library cache | Balances freshness vs API call reduction | v1.1 |
| No TTL for match cache | File paths stable, invalidate on failure | v1.1 |
| LOCKED: Missing fields clear Plex | None/empty in data clears existing Plex value | v1.1 |
| All sync toggles default True | Backward compatible with existing configs | v1.1 |

## Milestones

| Version | Status | Date | Notes |
|---------|--------|------|-------|
| v1.0 | Complete | 2026-02-03 | 5 phases, 16 plans, 76 commits |
| v1.1 | Complete | 2026-02-03 | 11 phases, 27 plans, 136 commits |
| v1.2 | Complete | 2026-02-04 | 3 phases, 3 plans, 15 commits |

---
*Last updated: 2026-02-04 after v1.2 milestone*
