# Phase 3: Plex API Client - Context

**Gathered:** 2026-01-24
**Status:** Ready for planning

<domain>
## Phase Boundary

Reliable Plex communication with explicit timeouts and improved scene matching. All Plex API calls must have timeouts (no infinite hangs), matching logic finds Plex items by file path, errors are classified for retry/DLQ routing, and immediate retries handle network blips.

</domain>

<decisions>
## Implementation Decisions

### Timeout Configuration
- Timeouts configurable in PlexSyncConfig (not hardcoded)
- Claude's discretion: default connect timeout value (likely 5-10s)
- Claude's discretion: default read timeout value (likely 30-60s)
- Claude's discretion: global session vs per-request (based on PlexAPI capabilities)

### Error Handling
- Authentication failures (401, invalid token) → Permanent error to DLQ
- Plex item not found (scene not in library) → Transient with long retry (Plex may still be scanning)
- Server overload (503, rate limiting) → Apply existing Phase 2 error classification
- Create Plex-specific exception classes: PlexTemporaryError, PlexPermanentError, PlexNotFound
- Subclass from existing TransientError/PermanentError for compatibility

### Retry Behavior
- Use tenacity library for immediate retries
- Add jitter to retry delays (avoid thundering herd)
- Connection errors only trigger immediate retry (timeouts, refused connections)
- HTTP errors (including 5xx) return job to queue for later retry
- Claude's discretion: retry count and backoff timing (likely 3 retries, 100-400ms)

### File Path Matching
- Claude's discretion: path matching strategy (flexible approach handling common cases)
- Claude's discretion: path prefix mapping (config option vs filename-only)
- Claude's discretion: fallback strategy if exact path fails
- Claude's discretion: case sensitivity (cross-platform compatibility)

### Claude's Discretion
- Default timeout values
- Timeout scope (global vs per-request)
- Specific retry count and timing
- Path matching implementation details
- Case sensitivity handling

</decisions>

<specifics>
## Specific Ideas

- PlexNotFound should be distinct from other transient errors — it may need different retry timing since Plex library scanning can take a while
- Tenacity is already a common Python library, so adding it shouldn't be controversial
- Keep compatibility with existing error classification from Phase 2

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 03-plex-api-client*
*Context gathered: 2026-01-24*
