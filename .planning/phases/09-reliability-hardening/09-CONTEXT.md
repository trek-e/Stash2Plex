# Phase 9: Reliability Hardening - Context

**Gathered:** 2026-02-03
**Status:** Ready for planning

<domain>
## Phase Boundary

Handle edge cases gracefully — prevent crashes from malformed input data. Covers Unicode/special character handling, truncation of long fields, malformed API response handling, and partial failure recovery.

</domain>

<decisions>
## Implementation Decisions

### Unicode Handling
- Emoji/symbol handling: Claude's discretion based on Plex support
- Control characters: Claude's discretion (strip silently or log)
- RTL/mixed-direction text: Claude's discretion
- Empty-after-sanitization: Claude's discretion for fallback behavior

### Truncation Strategy
- How to truncate: Claude's discretion (word boundary, ellipsis, etc.)
- Logging truncation: Claude's discretion for verbosity
- Which fields can truncate: Claude's discretion
- List limits (performers/tags): Claude's discretion based on Plex API behavior

### Malformed Data Behavior
- Data integrity vs sync-what-we-can: Claude's discretion based on field
- Missing optional fields: **LOCKED** — Clear existing Plex value (don't preserve)
- Unexpected API responses: Claude's discretion for error classification
- Warning aggregation: Claude's discretion

### Partial Failure Recovery
- Job outcome on partial success: Claude's discretion
- Stats categorization: Claude's discretion
- Rollback on disconnect: Claude's discretion
- Field-level retry count: Claude's discretion

### Claude's Discretion
- Nearly all implementation details are delegated to Claude
- One locked decision: Missing optional fields should CLEAR existing Plex values (not preserve them)

</decisions>

<specifics>
## Specific Ideas

- The goal is "no crashes from malformed input data" — defensive coding
- Build on existing validation infrastructure (validation/ module has sanitizers)
- Stash metadata can contain user-generated content with arbitrary Unicode
- Plex API behavior should be researched, not assumed

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 09-reliability-hardening*
*Context gathered: 2026-02-03*
