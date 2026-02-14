---
status: resolved
trigger: "Investigate issue: plexclient-connect-error"
created: 2026-02-14T00:00:00Z
updated: 2026-02-14T00:05:00Z
---

## Current Focus

hypothesis: PlexClient is being called with .connect() method that doesn't exist, likely a reconciliation-specific code path using wrong API
test: Search for .connect() calls and PlexClient usage patterns
expecting: Find where reconciliation differs from working hook-triggered sync
next_action: Search codebase for PlexClient.connect() calls

## Symptoms

expected: Manual reconciliation task (triggered from Stash UI) should detect gaps between Stash and Plex metadata and enqueue sync jobs
actual: Error during reconciliation: Failed to build Plex data: 'PlexClient' object has no attribute 'connect'
errors: 'PlexClient' object has no attribute 'connect'
reproduction: Trigger any manual reconciliation task from Stash UI (Reconcile Library)
started: First time ever testing reconciliation - never worked before. All other sync features (hook-triggered sync) presumably work fine.

## Eliminated

## Evidence

- timestamp: 2026-02-14T00:01:00Z
  checked: reconciliation/engine.py line 223
  found: Code calls `plex = client.connect()` on PlexClient instance
  implication: PlexClient does not have a .connect() method

- timestamp: 2026-02-14T00:02:00Z
  checked: plex/client.py full implementation
  found: PlexClient has .server property (lazy initialization), .get_library(), and .scan_library() methods, but NO .connect() method
  implication: reconciliation/engine.py is using wrong API

- timestamp: 2026-02-14T00:03:00Z
  checked: worker/processor.py lines 458-466
  found: Worker correctly uses PlexClient - creates instance, then accesses .server property
  implication: Correct pattern is `client = PlexClient(...); server = client.server`

- timestamp: 2026-02-14T00:04:00Z
  checked: PlexClient class design (plex/client.py lines 160-174)
  found: `.server` is a @property that lazily initializes PlexServer connection via `_get_server()` method
  implication: The API is `client.server`, not `client.connect()`

## Resolution

root_cause: reconciliation/engine.py line 223 calls nonexistent method `client.connect()`. PlexClient API uses `.server` property for lazy connection, not `.connect()` method. This was first-time code (reconciliation never worked before) so wrong API was used from start.
fix: Changed reconciliation/engine.py line 223 from `plex = client.connect()` to `plex = client.server`. Also updated test file tests/reconciliation/test_engine.py to mock .server property instead of .connect() method.
verification: All 90 reconciliation tests pass, including test_run_handles_plex_server_down which now correctly mocks the .server property with PropertyMock.
files_changed: ["reconciliation/engine.py", "tests/reconciliation/test_engine.py"]
