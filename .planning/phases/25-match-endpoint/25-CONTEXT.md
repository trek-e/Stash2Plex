# Phase 25: Match Endpoint - Context

**Gathered:** 2026-03-04
**Status:** Ready for planning

<domain>
## Phase Boundary

Implement the Plex match endpoint so library scans return Stash scene IDs via path mapping with filename fallback. Includes startup roundtrip validation of mapping rules and 90-second timeout compliance under concurrent scan load. Requirements: PROV-02, PROV-04, PATH-03, PATH-04.

</domain>

<decisions>
## Implementation Decisions

### Plex filename handling
- Each path mapping rule includes a `plex_library_root` field (absolute path, e.g., `/plex/media/`)
- Provider prepends `plex_library_root` to Plex's relative filename to reconstruct absolute Plex path before running PathMapper
- If no rule's library root matches, skip path mapping entirely and fall through to filename fallback
- Match endpoint uses `filename` field only from the request body — title, year, and other fields are logged but not used for lookup

### Fallback strategy
- When path mapping returns None, extract the basename from the relative filename and search Stash via substring/contains match
- New `find_scenes_by_filename(filename)` method on StashClient with a dedicated GraphQL query using INCLUDES modifier on path
- If multiple Stash scenes match the same filename, return all as candidates in the MediaContainer response (let Plex/user pick)
- Log whether each match came from path mapping or filename fallback (for debugging), but response format is identical

### Startup validation
- Each rule optionally includes `test_plex_path` and `test_stash_path` fields for roundtrip validation
- At startup, validate: test_plex_path -> PathMapper -> stash result == test_stash_path, and reverse roundtrip back to original
- Failed rules are disabled (excluded from active rules) with a warning in the startup banner — provider continues with remaining valid rules
- If ALL rules fail or no rules are configured, provider still starts with a prominent warning — filename fallback remains functional
- Non-blocking Stash connectivity check at startup — warn if unreachable but start anyway (consistent with Phase 24 decision)

### Match response shape
- Each Metadata entry includes minimal fields: ratingKey (integer scene ID), title, and date — full metadata comes from Phase 26's metadata endpoint
- Score differentiation: path-mapped matches get a high score (100), filename fallback matches get a lower score — influences Plex auto-match behavior
- When Stash is unreachable during a match request, return valid empty MediaContainer (graceful degradation) and log the error
- Asyncio semaphore limits concurrent Stash GraphQL calls (e.g., max 10) to prevent overwhelming Stash during full library rescans and ensure 90-second timeout compliance

### Claude's Discretion
- Exact semaphore concurrency limit value
- Score values for path-mapped vs fallback matches
- GraphQL query structure for filename search (INCLUDES modifier specifics)
- Request body parsing and field extraction details
- Startup banner formatting for rule validation results

</decisions>

<specifics>
## Specific Ideas

- The `plex_library_root` and test path fields extend the existing PathRule model in shared_lib — keep config shape consistent
- Startup validation results should be visible in the startup banner (checkmarks/X per rule, like Phase 24's connectivity status)
- Filename fallback is a safety net, not the primary strategy — path mapping should handle the vast majority of matches in a well-configured deployment

</specifics>

<code_context>
## Existing Code Insights

### Reusable Assets
- `shared_lib/path_mapper.py`: PathMapper + PathRule — needs `plex_library_root`, `test_plex_path`, `test_stash_path` fields added to PathRule
- `shared_lib/stash_client.py`: StashClient — needs new `find_scenes_by_filename()` method; existing `find_scene_by_path()` used for path-mapped lookups
- `provider/routes/match.py`: Stub endpoint already parses `filename` from request body and returns MediaContainer
- `provider/models.py`: MediaContainerResponse — Metadata list needs typed match entry model (ratingKey, title, date, score)
- `provider/config.py`: ProviderSettings.path_rules already accepts list[dict] — validation logic builds PathMapper from these at startup

### Established Patterns
- Plex protocol envelope: all responses wrapped in `{"MediaContainer": {...}}` dict
- StashClient exceptions: StashConnectionError for unreachable, StashQueryError for GraphQL errors — match endpoint catches these for graceful degradation
- PathMapper returns None on no match — established pattern for fallback triggering
- lru_cache(maxsize=1) for settings — startup builds PathMapper once from validated rules

### Integration Points
- `provider/main.py` lifespan: startup validation runs here (rule roundtrip + Stash connectivity check), sets `app.state` with validated PathMapper and StashClient
- `provider/routes/match.py`: main implementation target — reads PathMapper and StashClient from `request.app.state`
- PathRule model in shared_lib: extended with new optional fields (plex_library_root, test paths)

</code_context>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 25-match-endpoint*
*Context gathered: 2026-03-04*
