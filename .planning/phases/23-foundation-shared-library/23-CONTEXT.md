# Phase 23: Foundation + Shared Library - Context

**Gathered:** 2026-02-23
**Status:** Ready for planning

<domain>
## Phase Boundary

Create the monorepo shared code layer (`shared_lib/`) with a bidirectional regex path mapping engine and async Stash GraphQL client. Both the existing Stash plugin and the new provider service must be able to import it. Docker build context must include shared_lib for the provider container.

</domain>

<decisions>
## Implementation Decisions

### Path Mapping Config Format
- Rules defined via **provider environment variables only** (docker-compose.yml)
- Single env var as **JSON array**: `PATH_RULES='[{"name":"nas","plex_pattern":"...","stash_pattern":"..."}]'`
- Each rule has three fields: `name` (human-readable), `plex_pattern` (regex with capture groups), `stash_pattern` (regex with capture groups)
- **Regex only** — no prefix shorthand mode. Simple prefix swaps are just simple regexes. One engine, no ambiguity.

### Monorepo Directory Layout
- `shared_lib/` at **repo root** — sibling to `provider/`
- Plugin imports via **sys.path manipulation** at startup (Stash2Plex.py adds repo root to sys.path)
- Provider's `requirements.txt` includes all shared dependencies — shared_lib has no separate requirements.txt
- Provider internal directory structure at Claude's discretion

### Stash GraphQL Client Design
- **Async-only** using httpx (provider is async/FastAPI; plugin uses asyncio.run() when needed)
- **Pydantic models** for return types (StashScene, StashFile, etc.) — consistent with existing config.py pattern
- **Exceptions** for error handling: StashConnectionError, StashQueryError, StashSceneNotFound — matches existing plugin exception pattern (PlexServerDown, PlexNotFound)
- **Direct httpx + raw GraphQL queries** — no stashapp-tools dependency. Write the 3-4 queries needed directly for full control and async-native behavior.

### Path Mapping Behavior
- **Return None** when no rule matches — caller decides fallback behavior (provider: filename lookup, plugin: log warning)
- **Case-sensitive by default**, with optional `case_insensitive` flag per rule for Windows/SMB paths
- **Normalize backslashes to forward slashes** on input before matching — users write rules with forward slashes only
- **Logging:** Debug-level for all mapping attempts (input → output), info-level for misses — aligns with existing debug_logging toggle pattern

### Claude's Discretion
- Provider internal directory structure (flat routes/ + mappers/ + gap/, or deeper nesting)
- Exact Pydantic model field definitions for StashScene/StashFile
- GraphQL query structure and field selection

</decisions>

<specifics>
## Specific Ideas

- Path mapping rules follow "first match wins" priority ordering — evaluated in array order
- Bidirectional by design: plex_pattern captures groups that stash_pattern uses, and vice versa
- The ratingKey format must be established here as integer scene ID (no forward slashes — research pitfall #1)

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 23-foundation-shared-library*
*Context gathered: 2026-02-23*
