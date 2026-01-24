# Phase 5: Late Update Detection - Context

**Gathered:** 2026-01-24
**Status:** Ready for planning

<domain>
## Phase Boundary

Late metadata updates in Stash trigger re-sync to Plex with confidence-based matching. When Stash metadata changes after initial sync (successful or not), the change propagates to Plex. Matches are scored for confidence; low-confidence matches are logged for user review.

</domain>

<decisions>
## Implementation Decisions

### Late Update Triggering
- Any metadata change in Stash triggers re-sync consideration (not just failed syncs)
- Use timestamp comparison: Stash `last_updated` vs our `last_synced_at`
- Check on every Scene.Update hook (no separate periodic scan)
- Store sync tracking state in job metadata (piggyback on existing queue job structure)

### Confidence Scoring
- Binary confidence levels: HIGH (auto-sync) or LOW (needs review)
- Primary factor: match uniqueness (single match = high, multiple candidates = low)
- Single unique match (any strategy) = high confidence, auto-sync
- Multiple matches or ambiguous = low confidence, needs review
- No match found = treat as PlexNotFound (use existing retry logic with 12 retries over ~2 hours)

### Low-Confidence Handling
- Log output only (no separate review queue in this phase)
- Log includes: scene ID, Stash path, list of Plex candidates found (basic info)
- Configurable behavior: add `strict_matching` config option
  - `strict_matching: true` → skip sync on low confidence (safer)
  - `strict_matching: false` → sync anyway with warning logged
- Claude's discretion: whether to add manual re-enqueue capability

### Re-sync Behavior
- Overwrite all metadata fields (Stash is source of truth by default)
- Configurable conflict resolution: add config option for Plex edit handling
  - Default: Stash always wins (overwrite Plex edits)
  - Option to preserve Plex edits (only update empty/default fields)
- Re-syncs use same queue as initial syncs (same retry logic applies)
- Deduplicate: if scene_id already in queue, skip adding duplicate job

### Claude's Discretion
- Manual trigger mechanism for low-confidence matches
- Exact deduplication implementation (check queue before enqueue)
- Config field names for strict_matching and conflict resolution

</decisions>

<specifics>
## Specific Ideas

- Timestamp comparison is preferred for simplicity (vs content hashing)
- Log format should be scannable — user needs to quickly see which scenes need attention
- Deduplication prevents queue flooding during bulk Stash updates

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 05-late-update-detection*
*Context gathered: 2026-01-24*
