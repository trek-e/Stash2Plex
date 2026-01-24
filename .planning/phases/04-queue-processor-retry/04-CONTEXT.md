# Phase 4: Queue Processor with Retry - Context

**Gathered:** 2026-01-24
**Status:** Ready for planning

<domain>
## Phase Boundary

Background worker with exponential backoff retry orchestration. Failed Plex API calls retry with increasing delays before moving to dead letter queue. Permanent errors go directly to DLQ. Worker polls queue at configurable intervals and survives Plex outages by persisting retry state.

</domain>

<decisions>
## Implementation Decisions

### Backoff Timing
- Claude's discretion: base retry interval (roadmap suggests 5s -> 10s -> 20s -> 40s -> 80s)
- Claude's discretion: maximum delay cap
- Claude's discretion: jitter percentage for retry delays
- Claude's discretion: whether PlexNotFound uses different (longer) retry timing

### Retry Limits
- Max retries configurable via existing PlexSyncConfig.max_retries field
- PlexNotFound gets separate (higher) retry limit since library scanning can take hours
- Claude's discretion: retry count tracking mechanism (job data vs in-memory)
- Claude's discretion: permanent error handling (immediate DLQ vs one retry)

### DLQ Review
- Claude's discretion: how users review DLQ (log output vs CLI command)
- Claude's discretion: whether users can retry jobs from DLQ
- Claude's discretion: what information stored for debugging
- DLQ retention period configurable (add to PlexSyncConfig, default 30 days)

### Worker Behavior
- Poll interval configurable via existing PlexSyncConfig.poll_interval field
- Claude's discretion: batch processing (one at a time vs all pending)
- Claude's discretion: periodic status logging during outages
- Circuit breaker: pause processing after many consecutive failures (user requested)

### Claude's Discretion
- Exact backoff timing and jitter
- PlexNotFound retry timing (longer delays, higher limit)
- DLQ review mechanism
- Retry count persistence
- Batch vs single job processing
- Status logging frequency
- Circuit breaker thresholds

</decisions>

<specifics>
## Specific Ideas

- Circuit breaker should pause processing when Plex seems completely down, not just slow
- PlexNotFound is special — library scanning can take hours, so needs longer retry windows
- Existing max_retries and poll_interval fields in PlexSyncConfig should be used (don't add duplicates)
- DLQ already exists from Phase 1 — this phase adds the retry orchestration that routes to it

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 04-queue-processor-retry*
*Context gathered: 2026-01-24*
