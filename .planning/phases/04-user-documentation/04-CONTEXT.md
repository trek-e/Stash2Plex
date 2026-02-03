# Phase 4: User Documentation - Context

**Gathered:** 2026-02-03
**Status:** Ready for planning

<domain>
## Phase Boundary

Complete user-facing documentation so new users can install and configure PlexSync without external help. Covers installation, configuration reference, troubleshooting, and quick start tutorial.

</domain>

<decisions>
## Implementation Decisions

### Document Structure
- README.md contains overview + quick start + links to detailed docs
- docs/ folder organized by task: install.md, config.md, troubleshoot.md
- README links directly to doc files in docs/

### Content Depth
- Minimal screenshots — only where essential (1-2 key steps)
- Every setting documented with: name, type, default, example values, when to change
- Multiple example PlexSync.yml configurations for different scenarios (basic, preserve Plex edits, strict matching)

### Audience Assumptions
- Assumes user knows Stash basics (has it running, understands scenes/performers)
- Assumes user knows Plex basics (has server running, understands libraries and metadata)
- Cover both Docker and bare metal deployments with path mapping notes
- Assumes comfort with terminal (can run commands, read logs, edit config files)

### Troubleshooting Scope
- Focus on common issues (top 5-10) plus log interpretation guide
- Include actual log output examples with annotations explaining each part
- Briefly explain queue/retry/DLQ system so users understand why things might be delayed
- Include "how to report issues" section with template for GitHub issues

### Claude's Discretion
- Whether docs/ needs its own README.md as index (depends on file count)
- Which settings need "why" explanations vs just "how"
- Exact log examples to include

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

*Phase: 04-user-documentation*
*Context gathered: 2026-02-03*
