# S10: Foundation Shared Library

**Goal:** Create the shared_lib package with a bidirectional regex path mapping engine and comprehensive tests using TDD.
**Demo:** Create the shared_lib package with a bidirectional regex path mapping engine and comprehensive tests using TDD.

## Must-Haves


## Tasks

- [x] **T01: 23-foundation-shared-library 01** `est:5min`
  - Create the shared_lib package with a bidirectional regex path mapping engine and comprehensive tests using TDD.

Purpose: PATH-01 and PATH-02 require a regex-based bidirectional path mapper that supports multiple named rules in priority order. This is the core translation layer between Plex file paths and Stash scene paths. INFR-01 requires the shared_lib package to exist as an importable Python package.

Output: Working `shared_lib/path_mapper.py` with PathRule Pydantic model, PathMapper class, and full test suite proving bidirectional translation, multi-rule priority, edge cases.
- [x] **T02: 23-foundation-shared-library 02** `est:3min`
  - Create the async Stash GraphQL client in shared_lib with comprehensive tests using TDD.

Purpose: INFR-02 requires an async GraphQL client that queries Stash scenes by path and by ID, returning typed Pydantic models. This client will be used by the provider service (Phase 25) for match requests and by the plugin in future phases. Completing this plan also finalizes INFR-01 — both shared_lib modules exist and the package is fully importable.

Output: Working `shared_lib/stash_client.py` with StashClient class, Pydantic models (StashScene, StashFile), custom exceptions, and full async test suite using respx mocks.

## Files Likely Touched

- `shared_lib/__init__.py`
- `shared_lib/path_mapper.py`
- `tests/shared_lib/__init__.py`
- `tests/shared_lib/test_path_mapper.py`
- `requirements-dev.txt`
- `pytest.ini`
- `shared_lib/stash_client.py`
- `tests/shared_lib/test_stash_client.py`
