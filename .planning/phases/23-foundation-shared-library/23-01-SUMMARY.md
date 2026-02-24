---
phase: 23-foundation-shared-library
plan: 01
subsystem: infra
tags: [shared_lib, pydantic, regex, path-mapping, tdd, httpx, pytest-asyncio, respx]

# Dependency graph
requires: []
provides:
  - shared_lib Python package at repo root (importable by plugin and provider)
  - PathRule Pydantic model: name, plex_pattern, stash_pattern, case_insensitive
  - PathMapper class with bidirectional plex_to_stash / stash_to_plex translation
  - from_env classmethod parses PATH_RULES JSON env var into validated rules
  - _template_to_match_pattern: derives stash match regex from replacement template
  - _pattern_to_repl_template: derives replacement template from plex match regex
  - httpx, pytest-asyncio, respx installed in venv (ready for Phase 23-02)
affects:
  - 23-02 (stash client uses shared_lib package; httpx/respx already installed)
  - 24-provider (Docker COPY shared_lib/ into provider image; path mapper used by provider)
  - 25-matching (path mapper translates scene paths for exact-match endpoint)

# Tech tracking
tech-stack:
  added: [httpx>=0.27.0, pytest-asyncio>=0.25.0, respx>=0.22.0]
  patterns:
    - PathRule as Pydantic BaseModel for validated rule config
    - Pre-compile regexes at PathMapper.__init__ to avoid per-call recompilation
    - Derive stash match regex from replacement template via _template_to_match_pattern
    - Derive plex replacement template from regex via _pattern_to_repl_template
    - asyncio_mode = strict in pytest.ini (explicit @pytest.mark.asyncio required)

key-files:
  created:
    - shared_lib/__init__.py
    - shared_lib/path_mapper.py
    - tests/shared_lib/__init__.py
    - tests/shared_lib/test_path_mapper.py
  modified:
    - requirements-dev.txt
    - pytest.ini

key-decisions:
  - "stash_pattern is a re.sub replacement template (\\1, \\2), not a match regex — _template_to_match_pattern derives the stash match regex from it at init time"
  - "plex_pattern is a match regex (^/plex/(.*)}) — _pattern_to_repl_template derives the stash-to-plex replacement template from it at init time"
  - "asyncio_mode = strict chosen over auto to avoid side effects on 22+ existing sync tests"
  - "count=1 in re.sub() prevents multiple substitutions on paths with repeated segments (Pitfall 2 from research)"

patterns-established:
  - "Pattern: bidirectional mapping via template/pattern derivation — one rule, two directions, no duplicate config"
  - "Pattern: pre-compile-at-init for regex engines — PathMapper.__init__ compiles all regex patterns once"
  - "Pattern: _normalize() method strips backslashes before matching — all path comparison in forward-slash space"

requirements-completed: [PATH-01, PATH-02, INFR-01]

# Metrics
duration: 5min
completed: 2026-02-24
---

# Phase 23 Plan 01: Foundation + Shared Library — Path Mapper Summary

**Bidirectional regex path mapper (PathRule + PathMapper) with 13-test TDD suite; httpx/respx/pytest-asyncio installed for Phase 23-02**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-02-24T05:12:22Z
- **Completed:** 2026-02-24T05:17:15Z
- **Tasks:** 2 (plus RED/GREEN/REFACTOR sub-phases)
- **Files modified:** 6

## Accomplishments

- Created `shared_lib/` package at repo root — importable by plugin via sys.path and provider via Docker COPY
- Implemented `PathMapper` with fully bidirectional path translation: `plex_to_stash` and `stash_to_plex`
- Solved the bidirectional derivation problem: `stash_pattern` is a replacement template, match regex is derived via `_template_to_match_pattern`; plex replacement template derived via `_pattern_to_repl_template`
- 13 TDD tests covering: simple prefix swap, nested paths, no-match returns None, multi-rule first-match-wins, priority order, backslash normalization, case_insensitive flag, from_env JSON parsing, invalid JSON raises, bidirectional round-trip
- Installed httpx, pytest-asyncio, respx for Phase 23-02 (stash_client tests)

## Task Commits

Each task was committed atomically:

1. **Task 1: Create shared_lib package and install dev dependencies** - `3489aee` (chore)
2. **Task 2 RED: Add failing tests for bidirectional path mapper** - `398f475` (test)
3. **Task 2 GREEN: Implement bidirectional path mapper** - `ee4ecab` (feat)

_Note: TDD task has three commits (chore setup → test RED → feat GREEN). Refactor skipped — implementation was clean._

**Plan metadata:** (docs commit — see below)

## Files Created/Modified

- `shared_lib/__init__.py` — Package marker with docstring distinguishing from existing `shared/` package
- `shared_lib/path_mapper.py` — PathRule Pydantic model + PathMapper class with bidirectional translation helpers
- `tests/shared_lib/__init__.py` — Empty test package marker
- `tests/shared_lib/test_path_mapper.py` — 13 TDD tests covering all spec behaviors
- `requirements-dev.txt` — Added httpx>=0.27.0, pytest-asyncio>=0.25.0, respx>=0.22.0
- `pytest.ini` — Added --cov=shared_lib and asyncio_mode = strict

## Decisions Made

- `stash_pattern` field is treated as a `re.sub` replacement template (`\1`, `\2`), not as a match regex. The match regex for stash paths is derived at init time via `_template_to_match_pattern`, which replaces `\N` backreferences with `(.*?)` capture groups and escapes literal portions.
- `plex_pattern` is a standard match regex (`^/plex/media/(.*)`). For stash→plex substitution, a replacement template is derived via `_pattern_to_repl_template`, which strips anchors and replaces capturing groups with numbered backreferences.
- `asyncio_mode = strict` chosen (not `auto`) to avoid unintended effects on 22+ existing sync tests.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Stash_pattern field used as regex caused PatternError**

- **Found during:** Task 2 GREEN (first implementation attempt)
- **Issue:** Initial implementation tried to compile `stash_pattern` (e.g., `/stash/media/\1`) as a regex pattern via `re.compile()`. Python raised `re.PatternError: invalid group reference 1 at position 14` because `\1` references a non-existent capture group in a match pattern context.
- **Fix:** Implemented `_template_to_match_pattern()` helper to derive a proper match regex from the stash_pattern replacement template, and `_pattern_to_repl_template()` to derive a replacement template from the plex_pattern regex. These are computed once at `__init__` time.
- **Files modified:** `shared_lib/path_mapper.py`
- **Verification:** All 13 tests pass including `test_stash_to_plex_simple_prefix_swap` and `test_bidirectional_roundtrip`
- **Committed in:** `ee4ecab` (GREEN phase feat commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - Bug)
**Impact on plan:** The fix resolved an architectural gap in the research example code where stash_pattern was described as both a replacement template and a match regex simultaneously — contradictory requirements. The derivation approach makes the rule design simpler for users (write one template, not two patterns) while maintaining full bidirectionality.

## Issues Encountered

- Coverage threshold failure (80%) is pre-existing — running only shared_lib tests gives 3% total because plex/worker/validation have 0% in this isolated run. The plan's verify command (`pytest tests/shared_lib/`) correctly shows 13/13 pass. Not a new issue.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- `shared_lib/` package is importable. `from shared_lib.path_mapper import PathMapper, PathRule` works from repo root.
- httpx, respx, pytest-asyncio installed — Phase 23-02 (stash_client.py) can proceed immediately.
- `asyncio_mode = strict` configured — async tests require `@pytest.mark.asyncio` decorator.
- Path mapper is the complete PATH-01, PATH-02, INFR-01 implementation. No blockers for Phase 23-02.

## Self-Check: PASSED

Files verified:
- FOUND: shared_lib/__init__.py
- FOUND: shared_lib/path_mapper.py
- FOUND: tests/shared_lib/__init__.py
- FOUND: tests/shared_lib/test_path_mapper.py
- FOUND: .planning/phases/23-foundation-shared-library/23-01-SUMMARY.md

Commits verified:
- FOUND: 3489aee (chore: create shared_lib package and install dev dependencies)
- FOUND: 398f475 (test: add failing tests for bidirectional path mapper)
- FOUND: ee4ecab (feat: implement bidirectional path mapper)

---
*Phase: 23-foundation-shared-library*
*Completed: 2026-02-24*
