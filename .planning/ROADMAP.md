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

### Phase 2: Core Unit Tests
**Goal:** Unit test coverage for all core modules

- `sync_queue/` - QueueManager, operations, DLQ
- `validation/` - metadata validation, config validation
- `plex/` - matching logic, API client
- `hooks/` - handler logic (without external calls)

**Success:** >80% coverage on core modules

---

### Phase 3: Integration Tests
**Goal:** End-to-end tests with mocked external services

- Full sync workflow with mocked Plex/Stash
- Error scenarios (Plex down, Stash timeout, etc.)
- Queue persistence and recovery tests
- Circuit breaker behavior tests

**Success:** Integration tests cover critical paths

---

### Phase 4: User Documentation
**Goal:** Complete user-facing documentation

- Installation guide (Stash plugin setup)
- Configuration reference (all settings explained)
- Troubleshooting guide (common issues, log interpretation)
- Quick start tutorial

**Success:** New user can install and configure without external help

---

### Phase 5: Architecture Documentation
**Goal:** Developer/maintainer documentation

- Component diagram (queue, worker, hooks, plex client)
- Data flow documentation (event → queue → sync → Plex)
- Design decisions and rationale
- Contributing guide

**Success:** New contributor can understand architecture quickly

---

### Phase 6: API Documentation
**Goal:** Auto-generated API reference

- Docstring audit and improvements
- Sphinx or mkdocs setup
- Generated API reference
- Integration with architecture docs

**Success:** All public APIs documented with examples

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
```

## Estimated Effort

| Phase | Complexity | Plans |
|-------|------------|-------|
| 1. Test Infrastructure | Medium | 2 |
| 2. Core Unit Tests | High | 4-5 |
| 3. Integration Tests | High | 3-4 |
| 4. User Documentation | Medium | 2-3 |
| 5. Architecture Docs | Medium | 2-3 |
| 6. API Documentation | Low | 1-2 |
| 7. Performance | Medium | 2-3 |
| 8. Observability | Medium | 2-3 |
| 9. Reliability | Medium | 2-3 |
| 10. Metadata Sync Toggles | Medium | 2-3 |

**Total:** ~22-32 plans across 10 phases

---
*Created: 2026-02-03*
