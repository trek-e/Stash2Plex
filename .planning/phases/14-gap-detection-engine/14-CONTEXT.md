# Phase 14: Gap Detection Engine - Context

**Gathered:** 2026-02-14
**Status:** Ready for planning

<domain>
## Phase Boundary

Core logic to compare Stash scene metadata against Plex metadata and identify three types of discrepancies: empty fields, stale timestamps, and missing items. Discovered gaps are enqueued through the existing persistent queue. No UI, no scheduling — just the detection engine and queue integration.

</domain>

<decisions>
## Implementation Decisions

### Comparison strategy
- Use the existing "meaningful metadata" quality gate for empty detection — a Plex item is a gap if it lacks ALL of studio/performers/tags/details/date while Stash has at least one
- Do NOT compare field-by-field; reuse the same gate logic from handlers.py
- Stale detection uses Stash scene `updated_at` vs `sync_timestamps.json` — no need to fetch Plex timestamps
- Engine checks ALL Stash scenes against Plex, not just previously-synced ones — this catches scenes added before PlexSync was installed

### Missing item behavior
- When a Stash scene has no Plex match, enqueue a normal sync job — the existing worker/retry/DLQ pipeline handles it
- Report all missing scenes including those where the file doesn't exist in any Plex library — the user may need to add the library or fix paths
- Use a lighter pre-check before running the full matcher: check sync_timestamps.json for known matches first, only invoke the two-phase matcher for scenes with no recorded match
- Enqueued jobs are standard sync jobs — no special "gap" or "missing" tagging needed

### Claude's Discretion
- Whether to trigger a Plex library scan when scenes are missing (or just rely on existing PlexNotFound-as-transient retry pattern)
- How to handle the "Stash-has-but-Plex-doesn't after recent sync" edge case — given the LOCKED "missing fields clear Plex values" rule, Claude should determine correct semantics (likely: if sync timestamp is newer than Stash updated_at, skip — the empty value was intentional)
- Batch size and iteration strategy for processing large Stash libraries efficiently
- Detection thresholds (what counts as "empty" for each field type)

</decisions>

<specifics>
## Specific Ideas

- Reuse existing infrastructure heavily: Stash GQL client, Plex matcher (with caching), sync_timestamps.json, persistent queue
- The "lighter pre-check" for matching means: sync_timestamps.json lookup → cache lookup → full two-phase matcher (only as last resort)
- Gap types map to existing enqueue patterns: empty and stale gaps are regular sync jobs, missing items are also regular sync jobs (PlexNotFound retry handles discovery)

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 14-gap-detection-engine*
*Context gathered: 2026-02-14*
