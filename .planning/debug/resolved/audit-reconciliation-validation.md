---
status: resolved
trigger: "Comprehensive code audit: Reconciliation and Validation modules"
created: 2026-02-15T00:00:00Z
updated: 2026-02-15T02:00:00Z
---

## Current Focus

hypothesis: Analysis complete, issues identified and categorized
test: Verified each issue with code execution where possible
expecting: Fixes for BUG/INCONSISTENCY items, documentation for IMPROVEMENT items
next_action: Create fixes for identified issues

## Symptoms

expected: All code paths are correct, consistent, and fully leveraged
actual: Unknown — comprehensive audit needed
errors: None reported — proactive audit
reproduction: Read and trace every code path
started: Current codebase as of v1.5.4

## Eliminated

## Evidence

- timestamp: 2026-02-15T00:10:00Z
  checked: Read all 10 target files (engine.py, detector.py, scheduler.py, __init__.py, config.py, metadata.py, errors.py, sanitizers.py, obfuscation.py, scene_extractor.py)
  found: All files read successfully, total ~2000 lines of code
  implication: Ready for systematic analysis

- timestamp: 2026-02-15T00:15:00Z
  checked: reconciliation/detector.py has_meaningful_metadata() function
  found: Function checks for studio, performers, tags, details, date (lines 40-46)
  implication: Consistent with handlers.py quality gate (lines 266-272)

- timestamp: 2026-02-15T00:20:00Z
  checked: reconciliation/engine.py _enqueue_gaps() quality gate
  found: Line 501 calls has_meaningful_metadata() before enqueue
  implication: Correctly prevents enqueueing scenes with no metadata

- timestamp: 2026-02-15T00:25:00Z
  checked: reconciliation/detector.py detect_empty_metadata() logic
  found: INCONSISTENCY - Uses has_meaningful_metadata() to filter Stash scenes (line 100) but doesn't check rating100
  implication: has_meaningful_metadata() excludes rating100, but it's a valid metadata field that could be meaningful

- timestamp: 2026-02-15T00:30:00Z
  checked: validation/metadata.py SyncMetadata model field validation
  found: All fields have sanitizers via field_validator decorators (lines 61-119)
  implication: Good - metadata is always sanitized before use

- timestamp: 2026-02-15T00:35:00Z
  checked: validation/scene_extractor.py extract_scene_metadata()
  found: Extracts title, details, date, rating100, studio, performers, tags, poster_url, background_url
  implication: Complete extraction - matches GQL fragment in engine.py

- timestamp: 2026-02-15T00:40:00Z
  checked: reconciliation/engine.py _extract_plex_metadata()
  found: Extracts studio, performers (actors), tags (genres), details (summary), date (year/originallyAvailableAt)
  implication: Does NOT extract rating - cannot compare rating between Stash/Plex

- timestamp: 2026-02-15T00:45:00Z
  checked: reconciliation/scheduler.py state persistence
  found: Uses atomic write (tmp file + os.replace) at lines 72-79
  implication: Good - prevents corrupt state on crash

- timestamp: 2026-02-15T00:50:00Z
  checked: reconciliation/scheduler.py file locking
  found: NO FILE LOCKING - concurrent access could cause race conditions
  implication: POTENTIAL BUG if multiple plugin invocations run simultaneously

- timestamp: 2026-02-15T00:55:00Z
  checked: validation/config.py plex_libraries property
  found: Lines 56-67 parse comma-separated library names
  implication: Good - handles single/multiple libraries correctly

- timestamp: 2026-02-15T01:00:00Z
  checked: reconciliation/engine.py _get_library_sections() fallback
  found: Lines 259-269 - tries hasattr for plex_libraries, falls back to plex_library
  implication: DEAD CODE - plex_libraries is a @property, hasattr will always return True even if plex_library is None

- timestamp: 2026-02-15T01:05:00Z
  checked: validation/errors.py classify_http_error() coverage
  found: Handles 429, 5xx (transient), 400, 401, 403, 404, 405, 410, 422 (permanent)
  implication: Complete coverage for common HTTP errors

- timestamp: 2026-02-15T01:10:00Z
  checked: validation/obfuscation.py collision handling
  found: Lines 64-69 add numeric suffix if word already used
  implication: Good - prevents different paths from mapping to same obfuscated value

- timestamp: 2026-02-15T01:15:00Z
  checked: reconciliation/engine.py _fetch_stash_scenes() scope handling
  found: Lines 193-199 support "recent_7days" scope not documented in run() docstring
  implication: INCONSISTENCY - scope parameter supports undocumented value

- timestamp: 2026-02-15T01:20:00Z
  checked: reconciliation/detector.py detect_stale_syncs() edge case handling
  found: Lines 175-177 correctly skip if sync is newer than updated_at (intentional empty per LOCKED decision)
  implication: Good - respects "missing fields clear Plex values" architecture decision

- timestamp: 2026-02-15T01:25:00Z
  checked: validation/config.py field sync toggles
  found: Lines 82-122 define 11 sync toggles with sync_master override
  implication: UNDERUTILIZED - these toggles exist but worker/processor.py may not honor all of them

- timestamp: 2026-02-15T01:30:00Z
  checked: validation/sanitizers.py emoji handling
  found: strip_emoji parameter exists (line 67) but defaults to False
  implication: UNDERUTILIZED - emoji stripping available but not used anywhere

- timestamp: 2026-02-15T01:35:00Z
  checked: reconciliation/engine.py _process_scene_batch() lighter pre-check
  found: Lines 354-360 skip matcher if scene in sync_timestamps (optimization)
  implication: Good - avoids expensive Plex matching for already-synced scenes

- timestamp: 2026-02-15T01:40:00Z
  checked: reconciliation/engine.py batch size hardcoded
  found: Line 298 batch_size = 100 hardcoded
  implication: IMPROVEMENT - could be configurable for memory-constrained systems

- timestamp: 2026-02-15T01:45:00Z
  checked: validation/metadata.py rating100 validation
  found: Lines 56, rating100 validated as ge=0, le=100
  implication: Good - enforces valid range

- timestamp: 2026-02-15T01:50:00Z
  checked: reconciliation/scheduler.py SCOPE_MAP
  found: Lines 27-31 map '24h' -> 'recent', '7days' -> 'recent_7days'
  implication: Good - scheduler correctly translates config values to engine values

## Resolution

root_cause: |
  Comprehensive audit revealed 5 categories of issues across reconciliation/ and validation/ modules:

  BUGS (must fix):
  1. reconciliation/engine.py line 259 - Dead code: hasattr(config, 'plex_libraries') always True
  2. reconciliation/scheduler.py - Missing file locking for concurrent access protection

  INCONSISTENCIES (should fix):
  3. reconciliation/engine.py _fetch_stash_scenes() supports undocumented "recent_7days" scope
  4. reconciliation/engine.py _extract_plex_metadata() does not extract rating, cannot compare ratings

  UNDERUTILIZED (document/enhance):
  5. validation/sanitizers.py strip_emoji parameter exists but never used
  6. validation/config.py field sync toggles may not be honored by worker/processor.py

  IMPROVEMENTS (nice to have):
  7. reconciliation/engine.py batch_size hardcoded at 100, could be configurable
  8. has_meaningful_metadata() excludes rating100 (intentional, but undocumented)

fix: |
  1. Remove dead hasattr check, use config.plex_libraries directly
  2. Add file locking to scheduler state persistence
  3. Document "recent_7days" scope in run() docstring
  4. Add rating extraction to _extract_plex_metadata() (or document why excluded)
  5. Either use strip_emoji or remove the parameter
  6. Verify worker honors all sync toggles (separate audit)
  7. Make batch_size configurable via config
  8. Document has_meaningful_metadata() logic in docstring

verification: |
  ✓ All 91 reconciliation tests pass
  ✓ Dead code removed (hasattr check)
  ✓ File locking added (fcntl.flock for shared/exclusive locks)
  ✓ Scope documentation updated (recent_7days now documented)
  ✓ Rating extraction added with error handling
  ✓ has_meaningful_metadata() logic documented (rating100 exclusion rationale)
  ✓ Batch size now configurable (reconcile_batch_size config field, 10-1000 range)
  ✓ strip_emoji documented as intentionally unused (preserved for future use)

files_changed:
  - reconciliation/engine.py (6 fixes)
  - reconciliation/detector.py (1 documentation)
  - reconciliation/scheduler.py (2 file locking additions)
  - validation/sanitizers.py (1 documentation)
  - validation/config.py (1 new field)
