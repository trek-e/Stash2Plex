# T02: 23-foundation-shared-library 02

**Slice:** S10 — **Milestone:** M001

## Description

Create the async Stash GraphQL client in shared_lib with comprehensive tests using TDD.

Purpose: INFR-02 requires an async GraphQL client that queries Stash scenes by path and by ID, returning typed Pydantic models. This client will be used by the provider service (Phase 25) for match requests and by the plugin in future phases. Completing this plan also finalizes INFR-01 — both shared_lib modules exist and the package is fully importable.

Output: Working `shared_lib/stash_client.py` with StashClient class, Pydantic models (StashScene, StashFile), custom exceptions, and full async test suite using respx mocks.

## Must-Haves

- [ ] "StashClient.find_scene_by_id() returns a typed StashScene for a valid scene ID"
- [ ] "StashClient.find_scene_by_id() raises StashSceneNotFound when scene does not exist"
- [ ] "StashClient.find_scene_by_path() returns a typed StashScene when path matches"
- [ ] "StashClient.find_scene_by_path() returns None when no scene matches the path"
- [ ] "StashClient raises StashConnectionError when Stash server is unreachable"
- [ ] "StashClient raises StashQueryError when GraphQL returns errors"
- [ ] "StashScene model contains flattened fields (studio_name, performer_names, tag_names)"
- [ ] "shared_lib is importable with both path_mapper and stash_client modules"

## Files

- `shared_lib/stash_client.py`
- `tests/shared_lib/test_stash_client.py`
