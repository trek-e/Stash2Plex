# Phase 5: Architecture Documentation - Context

**Gathered:** 2026-02-03
**Status:** Ready for planning

<domain>
## Phase Boundary

Developer/maintainer documentation so new contributors can understand the PlexSync architecture quickly. Covers component diagram, data flow, design decisions, and contributing guide.

</domain>

<decisions>
## Implementation Decisions

### Diagram Format
- Use Mermaid diagrams (text-based, renders in GitHub, easy to update)
- One comprehensive diagram showing full system
- Module boundaries only (hooks/ → sync_queue/ → worker/ → plex/)
- Include external systems (Stash → PlexSync → Plex) for full context

### Content Depth
- High-level overview — explain what each module does, not how
- No code examples — concepts only, reference source files for implementation details
- Design rationale inline with component descriptions (brief, not a dedicated section)
- Brief mentions of data models — reference that Pydantic models exist, don't detail schemas

### Target Audience
- Assume advanced Python experience — skip Python basics, focus on architecture
- Brief context for Stash plugin system — quick intro to hooks, tasks, plugin structure
- Brief context for Plex API — quick intro to libraries, items, metadata concepts
- Link to external resources — Stash and Plex docs for readers who need deeper context

### Contributing Guide Scope
- Brief dev setup — reference requirements-dev.txt, run pytest, not full walkthrough
- Basic PR guidance — fork, branch, PR (standard GitHub flow)
- Reference existing tools for code style — mention black/ruff if configured
- Tests encouraged but not required

### Claude's Discretion
- Exact Mermaid diagram structure and node naming
- Order of module descriptions
- Which external links to include

</decisions>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 05-architecture-documentation*
*Context gathered: 2026-02-03*
