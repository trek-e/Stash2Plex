# PlexSync Improvements

## What This Is

Improvements to the PlexSync plugin for Stash, which syncs metadata from Stash to Plex. The current version has timing and reliability issues — syncs fail when Plex is unavailable, late Stash metadata updates don't propagate, and matching sometimes fails even when a match exists.

## Core Value

Reliable sync: when metadata changes in Stash, it eventually reaches Plex — even if Plex was temporarily unavailable or Stash hadn't finished indexing yet.

## Requirements

### Validated (v1.0)

- [x] Retry logic when Plex is unavailable (exponential backoff with jitter, circuit breaker)
- [x] Late update handling — push metadata to Plex when Stash updates after initial sync
- [x] Input sanitization — validate/clean data before sending to Plex API
- [x] Improved matching logic — confidence scoring, reduced false negatives

### Active

(None — v1.0 complete, ready for next milestone)

### Out of Scope

- Plex → Stash sync — Stash remains the primary metadata source
- New features unrelated to reliability/security — focus is fixing existing functionality

## Context

**Current state:** PlexSync v1.0 complete. Queue-based architecture with SQLite persistence, exponential backoff, circuit breaker, confidence-scored matching, and late update detection.

**Source:** https://github.com/stashapp/CommunityScripts/tree/main/plugins/PlexSync

## Constraints

- **Compatibility**: Must work with existing Stash plugin architecture
- **Dependencies**: Should minimize new dependencies beyond what's already in requirements.txt (stashapi, unidecode, requests)

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Fork locally for development | Need to test changes against real Stash/Plex setup | — Pending |
| persist-queue for SQLite queue | Built-in crash recovery vs custom SQLite queue | v1.0 |
| Job metadata for sync state | Simpler than separate SQLite table | v1.0 |
| JSON file for timestamps | sync_timestamps.json with atomic writes | v1.0 |
| In-memory dedup | Resets on restart but meets <100ms hook requirement | v1.0 |
| Confidence scoring | HIGH/LOW based on match uniqueness | v1.0 |
| PlexNotFound as transient | Items may appear after library scan | v1.0 |

## Milestones

| Version | Status | Date | Notes |
|---------|--------|------|-------|
| v1.0 | Complete | 2026-02-03 | 5 phases, 16 plans, 76 commits |

---
*Last updated: 2026-02-03 after v1.0 completion*
