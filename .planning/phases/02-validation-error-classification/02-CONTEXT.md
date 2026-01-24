# Phase 2: Validation & Error Classification - Context

**Gathered:** 2026-01-24
**Status:** Ready for planning

<domain>
## Phase Boundary

Block invalid data before it enters the queue; classify errors to determine retry vs DLQ handling. Validation happens early (hook handler), sanitization preserves meaning, and error classification is centralized for consistent retry behavior.

</domain>

<decisions>
## Implementation Decisions

### Metadata Validation
- Validate required fields only: scene_id and title (others optional)
- Use pydantic models for validation (type-safe, auto-coercion, clear errors)
- On validation failure: sanitize and attempt sync (don't reject)
- Log sanitizations at WARN level so user sees when data is modified
- Validate in hook handler before enqueue (bad data never hits queue)

### Character Sanitization
- Handle: control characters, unicode/encoding issues, special symbols (&, quotes, angle brackets)
- Preserve meaning when sanitizing (& → "and", smart quotes → regular quotes)
- Research Plex API field length limits during planning
- Truncation approach: Claude's discretion

### Error Classification
- HTTP 5xx (500, 502, 503, 504): Always transient → retry
- HTTP 4xx: Mostly permanent (400, 401, 403, 404 → DLQ); 429 → transient (rate limited)
- Centralized classifier function that categorizes all errors
- Use existing TransientError/PermanentError exception classes from Phase 1

### Plugin Configuration
- Use pydantic config model (consistent with metadata validation)
- Required fields: Claude determines from existing PlexSync code
- Failure behavior on bad config: Claude's discretion
- Support optional tunables with sensible defaults (max_retries, poll_interval, etc.)

### Claude's Discretion
- Strict mode toggle (config option for reject vs sanitize)
- ID validation depth (type-check vs positive int check)
- Performance trade-offs if validation approaches 100ms limit
- Network error classification (DNS vs connection vs timeout)
- Truncation approach (word boundary vs hard cut)
- Config validation failure mode (fail loudly vs use defaults)
- Which config fields are truly required

</decisions>

<specifics>
## Specific Ideas

- User currently experiencing issues with control characters, unicode, and special symbols
- Plex API has caused errors due to character issues - need research on actual limits
- Warn-level logging ensures user visibility without being intrusive
- Hook handler must stay under 100ms - keep validation lightweight

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 02-validation-error-classification*
*Context gathered: 2026-01-24*
