---
phase: 03-plex-api-client
plan: 03
subsystem: worker
tags: [plex, integration, worker, processor]
dependency-graph:
  requires: [03-01, 03-02]
  provides: [worker-plex-integration]
  affects: [04-plugin-wiring]
tech-stack:
  patterns: [lazy-initialization, dependency-injection]
key-files:
  modified: [worker/processor.py]
  created: [tests/__init__.py, tests/test_plex_integration.py]
decisions:
  - id: mock-at-method-level
    choice: "Mock _get_plex_client method in tests instead of patching plexapi"
    reason: "Avoids queue module shadowing issue with plexapi->urllib3->queue import chain"
metrics:
  duration: 4min
  completed: 2026-01-24
---

# Phase 3 Plan 3: Worker Plex Integration Summary

Worker processor now uses PlexClient and find_plex_item_by_path for real Plex metadata sync operations.

## What Was Built

### Task 1: Wire PlexClient into SyncWorker (20e4b5f)

Updated `worker/processor.py` to replace the Phase 1 stub with real Plex integration:

1. **Config injection**: SyncWorker.__init__ now accepts `config: PlexSyncConfig` parameter
2. **Lazy PlexClient**: Added `_get_plex_client()` method for lazy initialization
3. **Real _process_job**: Replaced stub with implementation that:
   - Validates job has file path (raises PermanentError if missing)
   - Gets PlexClient lazily
   - Searches all library sections using `find_plex_item_by_path`
   - Raises PlexNotFound if item not found
   - Updates metadata via `_update_metadata` helper
   - Translates unknown exceptions via `translate_plex_exception`

4. **Metadata updates**: Added `_update_metadata()` helper supporting:
   - title.value
   - studio.value
   - summary.value
   - tagline.value

### Task 2: Integration Tests (7613fba)

Created `tests/test_plex_integration.py` with 17 tests across 5 test classes:

| Class | Tests | Focus |
|-------|-------|-------|
| TestMatcher | 5 | find_plex_item_by_path strategies |
| TestExceptionHierarchy | 3 | Exception subclass relationships |
| TestExceptionTranslation | 3 | translate_plex_exception behavior |
| TestSyncWorkerIntegration | 4 | _process_job with mocked client |
| TestPlexClientStructure | 2 | PlexClient attributes/properties |

Tests carefully avoid triggering the queue module shadowing issue by mocking at method level rather than patching plexapi imports.

## Integration Points

```
worker/processor.py
    |
    +-- imports from plex.client.PlexClient (lazy, in _get_plex_client)
    +-- imports from plex.matcher.find_plex_item_by_path (lazy, in _process_job)
    +-- imports from plex.exceptions.* (lazy, in _process_job)
    +-- receives validation.config.PlexSyncConfig via constructor
```

## Key Code Paths

**Job processing flow:**
```
_process_job(job)
    -> validate file_path present
    -> _get_plex_client() (lazy init)
    -> for section in client.server.library.sections():
    ->     find_plex_item_by_path(section, file_path)
    -> if not found: raise PlexNotFound
    -> _update_metadata(plex_item, data)
    -> plex_item.edit(**edits)
    -> plex_item.reload()
```

**Exception handling:**
```
_process_job catches:
    - PlexTemporaryError, PlexPermanentError, PlexNotFound -> re-raise
    - Exception -> translate_plex_exception(e) -> raise
```

## Decisions Made

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Mock at method level | Mock `_get_plex_client` instead of patching `plexapi` module | Avoids queue module shadowing issue; plexapi->requests->urllib3 imports stdlib queue |
| Lazy imports in _process_job | Import plex.exceptions inside method | Avoids circular import at module load time |
| Search all sections | Iterate `client.server.library.sections()` | Works without knowing library name; can be optimized later |

## Verification Results

All must-haves verified:

- [x] Worker uses PlexClient to connect to Plex
- [x] Worker uses find_plex_item_by_path to locate items
- [x] Plex errors translated to TransientError/PermanentError hierarchy
- [x] _process_job is no longer a stub
- [x] worker/processor.py has real Plex integration (258 lines)
- [x] Key links verified: client, matcher, exceptions

All 17 integration tests pass.

## Deviations from Plan

None - plan executed exactly as written.

## Files Changed

| File | Change | Lines |
|------|--------|-------|
| worker/processor.py | Modified | +112/-15 |
| tests/__init__.py | Created | 0 |
| tests/test_plex_integration.py | Created | 359 |

## Next Phase Readiness

Phase 3 complete. All Plex API client components are ready:

- [x] 03-01: Exception hierarchy and translate_plex_exception
- [x] 03-02: PlexClient wrapper with timeouts and retry
- [x] 03-03: Worker integration with PlexClient and matcher

Ready for Phase 4: Plugin Wiring - connecting all components in the Stash plugin entry point.
