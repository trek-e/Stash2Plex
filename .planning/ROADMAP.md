# v1.1 Roadmap: Foundation Hardening

## Overview

Focus: Comprehensive testing, thorough documentation, then performance/observability/reliability improvements. No new features — solidify the foundation before expanding.

## Phases

### Phase 1: Testing Infrastructure ✓
**Goal:** pytest setup with fixtures for mocking Plex/Stash APIs
**Plans:** 2 plans (complete)
**Completed:** 2026-02-03

- pytest configuration (pytest.ini, conftest.py)
- Mock fixtures for PlexServer, StashInterface
- Test directory structure mirroring source
- Coverage reporting setup (pytest-cov)

**Success:** `pytest` runs with mock infrastructure ready ✓

Plans:
- [x] 01-01-PLAN.md — pytest.ini and requirements-dev.txt configuration
- [x] 01-02-PLAN.md — conftest.py fixtures and test directory structure

---

### Phase 2: Core Unit Tests ✓
**Goal:** Unit test coverage for all core modules
**Plans:** 4 plans (complete)
**Completed:** 2026-02-03

- `sync_queue/` - QueueManager, operations, DLQ (88.8% coverage)
- `validation/` - metadata validation, config validation (94.2% coverage)
- `plex/` - matching logic, API client (94.4% coverage)
- `hooks/` - handler logic (96.9% coverage)

**Success:** >80% coverage on core modules ✓ (445 tests, all >80%)

Plans:
- [x] 02-01-PLAN.md — sync_queue tests (QueueManager, operations, DLQ)
- [x] 02-02-PLAN.md — validation tests (SyncMetadata, PlexSyncConfig, sanitizers)
- [x] 02-03-PLAN.md — plex tests (matcher, client, exceptions)
- [x] 02-04-PLAN.md — hooks tests (handlers)

---

### Phase 2.1: Fix Plex Device Registration (Bugfix) ✓
**Goal:** Persistent device identity to avoid "new device" notifications on each sync
**Plans:** 1 plan (complete)
**Completed:** 2026-02-03

- Create plex/device_identity.py with UUID persistence
- Integrate into PlexSync.py initialization (before PlexClient creation)
- Add unit tests for device identity module

**Success:** Plex no longer shows "new device" notifications on each sync ✓

**Priority:** HIGH (bugfix)

Plans:
- [x] 02.1-01-PLAN.md — Implement persistent device identity

---

### Phase 3: Integration Tests ✓
**Goal:** End-to-end tests with mocked external services
**Plans:** 4 plans (complete)
**Completed:** 2026-02-03

- Full sync workflow with mocked Plex/Stash
- Error scenarios (Plex down, Stash timeout, etc.)
- Queue persistence and recovery tests
- Circuit breaker behavior tests

**Success:** 62 integration tests covering critical paths ✓

Plans:
- [x] 03-01-PLAN.md — Test infrastructure (freezegun, integration fixtures)
- [x] 03-02-PLAN.md — Sync workflow tests (happy path metadata sync)
- [x] 03-03-PLAN.md — Queue persistence and circuit breaker tests
- [x] 03-04-PLAN.md — Error scenario tests (Plex down, not found, permanent errors)

---

### Phase 4: User Documentation ✓
**Goal:** Complete user-facing documentation
**Plans:** 4 plans (complete)
**Completed:** 2026-02-03

- Installation guide (Stash plugin setup)
- Configuration reference (all settings explained)
- Troubleshooting guide (common issues, log interpretation)
- Quick start tutorial

**Success:** New user can install and configure without external help ✓

Plans:
- [x] 04-01-PLAN.md — README.md with overview and quick start
- [x] 04-02-PLAN.md — docs/install.md installation guide
- [x] 04-03-PLAN.md — docs/config.md configuration reference
- [x] 04-04-PLAN.md — docs/troubleshoot.md troubleshooting guide

---

### Phase 5: Architecture Documentation ✓
**Goal:** Developer/maintainer documentation
**Plans:** 2 plans (complete)
**Completed:** 2026-02-03

- Component diagram (queue, worker, hooks, plex client)
- Data flow documentation (event → queue → sync → Plex)
- Design decisions and rationale
- Contributing guide

**Success:** New contributor can understand architecture quickly ✓

Plans:
- [x] 05-01-PLAN.md — docs/ARCHITECTURE.md with system diagram, module overview, data flow, design decisions
- [x] 05-02-PLAN.md — CONTRIBUTING.md with dev setup, PR guidelines, testing expectations

---

### Phase 6: API Documentation
**Goal:** Auto-generated API reference
**Plans:** 1 plan

- MkDocs + mkdocstrings setup
- API reference pages for all modules
- Docstring audit and examples
- Integration with architecture docs

**Success:** All public APIs documented with examples

Plans:
- [ ] 06-01-PLAN.md — MkDocs configuration, API reference pages, docstring examples

---

### Phase 7: Performance Optimization
**Goal:** Reduce API calls, improve matching speed

- Plex library caching (avoid repeated scans)
- Match result caching
- Batch API calls where possible
- Profile and optimize hot paths

**Success:** Measurable reduction in Plex API calls per sync

---

### Phase 8: Observability Improvements
**Goal:** Better visibility into sync operations

- Structured logging (JSON format option)
- Sync statistics tracking (success/fail counts)
- Match confidence histograms
- Error categorization and reporting

**Success:** Can diagnose sync issues from logs alone

---

### Phase 9: Reliability Hardening
**Goal:** Handle edge cases gracefully

- Unicode/special character handling in titles
- Very long title/description truncation
- Malformed API response handling
- Partial failure recovery

**Success:** No crashes from malformed input data

---

### Phase 10: Metadata Sync Toggles
**Goal:** Add toggles for enabling/disabling each metadata category sync

- Configuration options for each metadata field (title, studio, performers, tags, etc.)
- Allow users to selectively enable/disable sync for specific fields
- Update worker to respect toggle settings
- Documentation for new settings

**Success:** Users can configure which metadata fields sync to Plex

**Depends on:** Phase 9

Plans:
- [ ] TBD (run /gsd:plan-phase 10 to break down)

---

### Phase 11: Queue Management UI
**Goal:** Add button to delete queue in plugin menu to clear out dead items

- Add task in plugin menu to clear/delete queue items
- Allow users to purge dead letter queue entries
- Confirmation dialog before destructive operations
- Status feedback after queue operations

**Success:** Users can clear stuck/dead queue items from Stash UI

**Depends on:** Phase 10

Plans:
- [ ] TBD (run /gsd:plan-phase 11 to break down)

---

### Phase 12: Process Queue Button
**Goal:** Add process queue button to handle stalled queues due to time limits

- Add task in plugin menu to manually trigger queue processing
- Handle long queues that stall due to Stash plugin timeout
- Allow resume/continue processing for large backlogs
- Progress feedback during manual processing

**Success:** Users can manually process stuck queues that timeout

**Depends on:** Phase 11

Plans:
- [ ] TBD (run /gsd:plan-phase 12 to break down)

---

### Phase 13: Dynamic Queue Timeout
**Goal:** Make queue processing timeout dynamic based on item count and average processing time

- Track average time to process each queue item
- Calculate required timeout based on: items_in_queue × avg_time_per_item
- Request appropriate timeout from Stash plugin system
- Handle cases where calculated timeout exceeds Stash limits
- Fallback behavior when timeout cannot be extended

**Success:** Queue processing timeout adapts to workload size, reducing timeouts for large queues

**Depends on:** Phase 12

Plans:
- [ ] TBD (run /gsd:plan-phase 13 to break down)

---

## Phase Dependencies

```
Phase 1 (Test Infra)
    |
Phase 2 (Unit Tests) --> Phase 3 (Integration Tests)
                              |
              +---------------+---------------+
              |                               |
Phase 4 (User Docs)                Phase 5 (Arch Docs)
              |                               |
              +---------------+---------------+
                              |
                    Phase 6 (API Docs)
                              |
              +---------------+---------------+
              |               |               |
      Phase 7          Phase 8          Phase 9
    (Performance)   (Observability)  (Reliability)
              |               |               |
              +---------------+---------------+
                              |
                    Phase 10 (Toggles)
                              |
                    Phase 11 (Queue UI)
                              |
                    Phase 12 (Process Queue)
                              |
                    Phase 13 (Dynamic Timeout)
```

Note: Phase 2.1 (Bugfix) can run in parallel with Phase 3 - it's independent.

## Estimated Effort

| Phase | Complexity | Plans |
|-------|------------|-------|
| 1. Test Infrastructure | Medium | 2 |
| 2. Core Unit Tests | High | 4 |
| 2.1. Plex Device Registration | Low | 1 |
| 3. Integration Tests | High | 4 |
| 4. User Documentation | Medium | 4 |
| 5. Architecture Docs | Medium | 2 |
| 6. API Documentation | Low | 1 |
| 7. Performance | Medium | 2-3 |
| 8. Observability | Medium | 2-3 |
| 9. Reliability | Medium | 2-3 |
| 10. Metadata Sync Toggles | Medium | 2-3 |
| 11. Queue Management UI | Low | 1-2 |
| 12. Process Queue Button | Low | 1-2 |
| 13. Dynamic Queue Timeout | Medium | 1-2 |

**Total:** ~27-40 plans across 14 phases

---
*Created: 2026-02-03*
