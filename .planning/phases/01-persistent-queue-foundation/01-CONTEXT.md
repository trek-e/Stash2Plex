# Phase 1: Persistent Queue Foundation - Context

**Gathered:** 2025-01-24
**Status:** Ready for planning

<domain>
## Phase Boundary

SQLite-backed queue infrastructure that stores sync jobs durably and survives process restarts, Plex outages, and crashes. This phase builds the queue foundation — validation, retry logic, and Plex integration are separate phases.

</domain>

<decisions>
## Implementation Decisions

### Queue Storage
- Store SQLite database in Stash plugin data directory
- Queue tied to Stash lifecycle — reset Stash = reset queue (simpler, no orphan state)

### Job Lifecycle
- Create jobs only for relevant metadata-changing updates (filter out non-sync events)
- Retries get priority over new jobs in queue processing order

### Observability
- Standard logging verbosity: job created, completed, failed events
- Use Stash's integrated logging system (stashapi.log)

### Claude's Discretion
- Completed job retention period (reasonable default)
- Full stack traces vs summary for failed jobs (appropriate debugging detail)
- Job deduplication strategy for rapid updates
- Maximum queue size (if limits needed)
- DLQ notification method (log warning vs Stash notification)
- DLQ retry mechanism design
- DLQ retention period
- DLQ data storage (full snapshot vs reference)
- Queue status check mechanism
- Log detail level for scene identifiers

</decisions>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches. User trusts Claude to make reasonable infrastructure decisions for most areas.

Key constraints:
- Must integrate with Stash plugin architecture
- Must survive plugin restarts gracefully
- Failed jobs should be reviewable for debugging

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 01-persistent-queue-foundation*
*Context gathered: 2025-01-24*
