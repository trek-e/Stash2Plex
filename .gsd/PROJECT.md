# PlexSync Improvements

## What This Is

Stash-to-Plex metadata sync ecosystem: a Stash plugin that pushes metadata on changes (v1.x), plus a Plex metadata provider service that lets Plex pull metadata from Stash during scans (v2.0). Together they ensure metadata flows reliably in both directions — push for real-time updates, pull for scan-time resolution — with regex-based path mapping and bi-directional gap detection.

## Core Value

Reliable sync: when metadata changes in Stash, it eventually reaches Plex — even if Plex was temporarily unavailable or Stash hadn't finished indexing yet.

## Current State (v1.5)

**Shipped:** 2026-02-24

PlexSync v1.5 adds outage resilience — automatic recovery when Plex comes back online:
- Circuit breaker state persists to JSON across plugin restarts (advisory file locking)
- Deep Plex health checks via /identity endpoint with exponential backoff (5s → 60s cap)
- Automatic recovery detection on plugin invocation — queue drains without user interaction
- Graduated rate limiting with token bucket prevents overwhelming Plex post-recovery
- Outage history tracking (last 30 outages) with MTBF/MTTR metrics in Stash UI
- DLQ recovery task re-queues outage-related failures with per-error-type filtering
- 29,348 LOC Python

Built on v1.0-v1.4 foundation:
- SQLite-backed persistent queue with crash recovery and circuit breaker (v1.0)
- 910+ tests, complete documentation, disk-backed caching (v1.1)
- Queue management UI with Process Queue button (v1.2)
- Production stability: multi-library, debug logging, batch backpressure (v1.3)
- Metadata reconciliation: gap detection, auto-reconciliation, enhanced status (v1.4)

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

### Validated (v1.3)

- [x] Multi-library support — search only configured Plex libraries
- [x] Debug logging mode — verbose step-by-step logging for troubleshooting
- [x] Path obfuscation — privacy-safe log sharing
- [x] Batch backpressure — throttled processing prevents Plex API overload
- [x] Configurable max_tags — user-tunable tag limit (10-500)
- [x] Identification sync pipeline — stash-box identification triggers metadata sync correctly
- [x] Queue stability — O(n²) reprocessing, doubling, stuck items all resolved
- [x] PEP 668 compatibility — containerized Python environments supported

### Validated (v1.4)

- [x] Reconciliation: detect Plex items with empty metadata that Stash has data for
- [x] Reconciliation: detect Stash scenes updated more recently than last sync
- [x] Reconciliation: detect Stash scenes with no matching Plex item
- [x] Manual reconciliation tasks in Stash UI (All / Recent / Last 7 Days)
- [x] Auto-reconciliation on Stash startup (recent scope, >1hr since last run)
- [x] Configurable periodic reconciliation interval (never/hourly/daily/weekly)
- [x] Configurable reconciliation scope (all/24h/7days)
- [x] Discovered gaps enqueued through existing queue (backpressure/retry/circuit breaker)
- [x] Enhanced "View Queue Status" with reconciliation history and gap counts by type

### Validated (v1.5)

- [x] Automatic queue drain when Plex recovers from outage — v1.5
- [x] Circuit breaker state persistence across Stash process restarts — v1.5
- [x] Plex health monitoring and recovery detection — v1.5
- [x] Graduated rate limiting during recovery period — v1.5
- [x] Outage history tracking with MTBF/MTTR metrics — v1.5
- [x] DLQ recovery for outage-related failures — v1.5
- [x] Enhanced outage visibility in queue status — v1.5

### Active

## Current Milestone: v2.0 Plex Metadata Provider

**Goal:** Add a Plex-side metadata provider service that Plex queries during scans to resolve metadata from Stash, with regex path mapping and bi-directional gap detection between libraries.

**Target features:**
- Custom Plex metadata provider (tv.plex.agents.custom.stash2plex) deployed as Docker container
- Match flow: regex path mapping → Stash GraphQL lookup, filename/hash fallback
- Full metadata serving on Plex Metadata requests
- Regex-based bidirectional path mapping engine (complex remapping, not just prefix swaps)
- Bi-directional gap detection: real-time during scans + scheduled full comparison
- Monorepo structure: provider/ alongside existing Stash plugin, shared code
- Coexists with v1.x push model (complementary, not replacement)

### Out of Scope

- Plex → Stash metadata write-back — Stash remains the primary metadata source; provider reads from Stash only
- Mobile/web UI — Stash plugin UI + Docker logs sufficient for provider
- Provider replaces push model — v1.x plugin continues for real-time hook-driven sync

## Context

**Source:** https://github.com/stashapp/CommunityScripts/tree/main/plugins/PlexSync
**Plex Provider API:** https://developer.plex.tv/pms/index.html#section/API-Info/Metadata-Providers
**Plex Provider API version:** 1.2.0, requires PMS 1.43.0+

## Constraints

- **Compatibility**: Must work with existing Stash plugin architecture (v1.x push model preserved)
- **Plex Provider API**: Must conform to PMS metadata provider spec (Match + Metadata features)
- **Deployment**: Provider service runs as Docker container, needs access to Stash GraphQL API and Plex API
- **Dependencies**: Minimize new dependencies in Stash plugin; provider service can use appropriate framework

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
| Debug logs as log_info with prefix | Stash filters out log_debug entirely | v1.3 |
| Batch backpressure 0.15s | Prevents circuit breaker trips at ~160 items | v1.3 |
| max_tags default 100 | 50 was too low for real-world tag counts (50-89 common) | v1.3 |
| is_identification flag passthrough | Scan gate must not block identification sync | v1.3 |
| Check-on-invocation scheduling | Stash plugins aren't daemons; check JSON state each invocation | v1.4 |
| Lighter pre-check for gap detection | sync_timestamps lookup before expensive matcher call | v1.4 |
| Meaningful metadata gate for gaps | Reuse handlers.py quality gate (studio/performers/tags/details/date) | v1.4 |
| Standard sync jobs for gaps | Enqueue as normal jobs, no special gap tagging | v1.4 |
| state_file=None default | 100% backward compatibility with existing configs | v1.5 |
| Non-blocking advisory locking | LOCK_NB makes save skippable, not blocking | v1.5 |
| Corrupted state defaults to CLOSED | Safe default, not stuck-open | v1.5 |
| Health checks don't modify circuit breaker | Avoids race conditions between health checks and worker | v1.5 |
| Health check timeout 5s | Short timeout avoids blocking worker thread | v1.5 |
| Recovery detection on invocation only | Reuses check-on-invocation pattern from v1.4 | v1.5 |
| Token bucket capacity 1.0 | Minimal burst, single job ahead for conservative recovery | v1.5 |
| Circular buffer maxlen=30 | Automatic oldest-record eviction for outage history | v1.5 |
| Conservative DLQ recovery default | PlexServerDown only; other types opt-in | v1.5 |

## Milestones

| Version | Status | Date | Notes |
|---------|--------|------|-------|
| v1.0 | Complete | 2026-02-03 | 5 phases, 16 plans, 76 commits |
| v1.1 | Complete | 2026-02-03 | 11 phases, 27 plans, 136 commits |
| v1.2 | Complete | 2026-02-04 | 3 phases, 3 plans, 15 commits |
| v1.3 | Complete | 2026-02-09 | Ad-hoc, 28 commits, production-driven |
| v1.4 | Complete | 2026-02-14 | 3 phases, 5 plans, metadata reconciliation |
| v1.5 | Complete | 2026-02-24 | Outage resilience — 6 phases, 12 plans |
| v2.0 | Active | 2026-02-23 | Plex metadata provider + bi-directional gap detection |

---
*Last updated: 2026-02-23 after v2.0 milestone start*
