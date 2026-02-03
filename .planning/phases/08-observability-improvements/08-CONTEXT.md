# Phase 8: Observability Improvements - Context

**Gathered:** 2026-02-03
**Status:** Ready for planning

<domain>
## Phase Boundary

Better visibility into sync operations — enabling diagnosis of sync issues from logs alone without needing to reproduce or debug live. Covers logging format, statistics tracking, and error reporting.

</domain>

<decisions>
## Implementation Decisions

### Logging Format
- Keep Stash-only logging (stderr via Stash plugin format) — no separate file logging
- Default log level: INFO (show sync results, errors, cache stats — skip per-file trace)
- JSON format support: Claude's discretion based on typical observability patterns
- Batch summary logging: Claude's discretion

### Statistics Tracking
- What metrics to track: Claude's discretion (counts, timing, or both)
- Where stats are visible: Claude's discretion (logs only, file, or both)
- Match confidence tracking: Claude's discretion
- Stats persistence: Claude's discretion (session only vs cumulative)

### Error Reporting
- Error categorization approach: Claude's discretion (by cause, by action, or both)
- Actionable hints in error messages: Claude's discretion
- DLQ summary logging: Yes — periodically log summary of DLQ contents
- Error deduplication: Claude's discretion

### Claude's Discretion
- JSON logging format decision
- Batch summary line format and frequency
- Metrics to track (success/failure counts, timing stats, match confidence)
- Stats storage location and persistence
- Error categorization scheme
- Whether to include actionable hints
- Error deduplication approach

</decisions>

<specifics>
## Specific Ideas

- DLQ summary should show breakdown by error type (e.g., "5 items in DLQ: 3 not-found, 2 permanent errors")
- Goal is to diagnose sync issues from logs alone — logs should tell the full story
- Current cache stats logging (every 10 jobs) is a good pattern to follow

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 08-observability-improvements*
*Context gathered: 2026-02-03*
