# T01: 23-foundation-shared-library 01

**Slice:** S10 — **Milestone:** M001

## Description

Create the shared_lib package with a bidirectional regex path mapping engine and comprehensive tests using TDD.

Purpose: PATH-01 and PATH-02 require a regex-based bidirectional path mapper that supports multiple named rules in priority order. This is the core translation layer between Plex file paths and Stash scene paths. INFR-01 requires the shared_lib package to exist as an importable Python package.

Output: Working `shared_lib/path_mapper.py` with PathRule Pydantic model, PathMapper class, and full test suite proving bidirectional translation, multi-rule priority, edge cases.

## Must-Haves

- [ ] "PathMapper.plex_to_stash() translates a Plex path to a Stash path using regex capture groups"
- [ ] "PathMapper.stash_to_plex() translates a Stash path to a Plex path using regex capture groups"
- [ ] "Multiple named rules are evaluated in array order — first match wins"
- [ ] "Returns None when no rule matches a given path"
- [ ] "PathMapper.from_env() parses a JSON string into validated PathRule models"
- [ ] "Backslash paths are normalized to forward slashes before matching"
- [ ] "shared_lib package is importable from the repo root"

## Files

- `shared_lib/__init__.py`
- `shared_lib/path_mapper.py`
- `tests/shared_lib/__init__.py`
- `tests/shared_lib/test_path_mapper.py`
- `requirements-dev.txt`
- `pytest.ini`
