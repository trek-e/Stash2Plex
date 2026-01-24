---
phase: 02-validation-error-classification
plan: 01
subsystem: validation
tags: [sanitization, error-handling, unicode, http-status-codes]

# Dependency graph
requires:
  - phase: 01-persistent-queue-foundation
    provides: TransientError, PermanentError exception classes
provides:
  - sanitize_for_plex function for text sanitization
  - classify_exception for error routing
  - classify_http_error for HTTP status classification
  - TRANSIENT_CODES and PERMANENT_CODES sets
affects: [02-02-metadata-validation, 03-plex-api]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Error classification pattern for retry/DLQ routing"
    - "Unicode normalization with NFC"

key-files:
  created:
    - validation/__init__.py
    - validation/sanitizers.py
    - validation/errors.py
  modified: []

key-decisions:
  - "Use unicodedata stdlib for sanitization (no external deps)"
  - "Truncate at word boundary when >80% of max_length"
  - "Unknown errors default to transient (safer, allows retry)"

patterns-established:
  - "Error classification returns exception class, not instance"
  - "QUOTE_MAP str.maketrans for character substitution"

# Metrics
duration: 2min
completed: 2026-01-24
---

# Phase 2 Plan 1: Validation Utilities Summary

**Text sanitization with Unicode normalization and centralized error classification for HTTP/network/validation errors**

## Performance

- **Duration:** 2 min
- **Started:** 2026-01-24T15:41:57Z
- **Completed:** 2026-01-24T15:43:43Z
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments
- Created validation module with sanitize_for_plex function
- Implemented error classification for retry/DLQ routing
- Exported clean public API through module __init__

## Task Commits

Each task was committed atomically:

1. **Task 1: Create validation module with sanitizers** - `41f14b2` (feat)
2. **Task 2: Create error classification module** - `54cb1a5` (feat)
3. **Task 3: Update validation module exports** - `8b933fc` (feat)

## Files Created/Modified
- `validation/__init__.py` - Module init with exports
- `validation/sanitizers.py` - sanitize_for_plex function, QUOTE_MAP
- `validation/errors.py` - classify_exception, classify_http_error, TRANSIENT_CODES, PERMANENT_CODES

## Decisions Made
- Used unicodedata stdlib for Unicode normalization (no external dependencies)
- Word boundary truncation threshold set at 80% of max_length
- Unknown errors classified as transient to allow retry (safer default)
- Classification returns exception class (not instance) for raising with context

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- validation module ready for use in metadata validation (02-02)
- Error classification ready for use in Plex API client (Phase 3)
- All verification tests pass

---
*Phase: 02-validation-error-classification*
*Completed: 2026-01-24*
