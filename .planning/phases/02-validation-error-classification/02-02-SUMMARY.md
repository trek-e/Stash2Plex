---
phase: 02-validation-error-classification
plan: 02
subsystem: validation
tags: [pydantic, validation, metadata, sanitization]

# Dependency graph
requires:
  - phase: 02-01
    provides: sanitize_for_plex function for text cleaning
provides:
  - SyncMetadata pydantic model with field validation
  - validate_metadata helper for try/catch-free validation
  - Hook handler integration with pre-enqueue validation
affects: [03-plex-api, worker-processing]

# Tech tracking
tech-stack:
  added: [pydantic v2]
  patterns: [field_validator mode='before' for sanitization]

key-files:
  created: [validation/metadata.py]
  modified: [hooks/handlers.py, validation/__init__.py]

key-decisions:
  - "Separate validators per field type (title/details/studio vs list fields)"
  - "validate_metadata returns tuple not exception for graceful error handling"
  - "Hook handler skips validation if no title present (worker can lookup)"

patterns-established:
  - "Pydantic field_validator mode='before' for sanitization before type checking"
  - "Tuple return (result, error) pattern for validation helpers"

# Metrics
duration: 2min
completed: 2026-01-24
---

# Phase 02 Plan 02: Metadata Validation Summary

**Pydantic SyncMetadata model with field sanitization and hook handler integration for pre-enqueue validation**

## Performance

- **Duration:** 2 min
- **Started:** 2026-01-24T15:47:16Z
- **Completed:** 2026-01-24T15:49:21Z
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments
- SyncMetadata pydantic model enforces scene_id > 0 and non-empty title
- Field validators sanitize text using sanitize_for_plex before type checking
- Hook handler validates metadata before enqueueing, maintaining <100ms performance
- Clean module exports for SyncMetadata and validate_metadata

## Task Commits

Each task was committed atomically:

1. **Task 1: Create SyncMetadata pydantic model** - `d998284` (feat)
2. **Task 2: Integrate validation into hook handler** - `2313316` (feat)
3. **Task 3: Update validation module exports** - `7a715c6` (chore)

## Files Created/Modified
- `validation/metadata.py` - SyncMetadata model with field validators and validate_metadata helper
- `hooks/handlers.py` - Added validation import and pre-enqueue validation logic
- `validation/__init__.py` - Added SyncMetadata and validate_metadata exports

## Decisions Made
- **Separate validators per field type:** Title has its own validator that raises on empty (required field), while details/studio return None if empty. List fields have a combined validator.
- **Tuple return pattern:** validate_metadata returns (model, None) or (None, error_string) instead of raising exceptions. This allows callers to decide how to handle errors without try/catch boilerplate.
- **Skip validation when no title:** If update_data lacks a title, hook handler enqueues as-is. The worker can look up the title from Stash later. This avoids blocking metadata-only updates (like rating changes).

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Validation foundation complete for queue processing
- SyncMetadata can be extended with additional fields as needed
- Error classification from 02-01 combines with validation for complete input handling
- Ready for 02-03: Rate limit configuration and queue processing integration

---
*Phase: 02-validation-error-classification*
*Completed: 2026-01-24*
