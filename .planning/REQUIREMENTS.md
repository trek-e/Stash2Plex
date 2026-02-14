# Requirements: PlexSync v1.4 Metadata Reconciliation

**Defined:** 2026-02-14
**Core Value:** Reliable sync — when metadata changes in Stash, it eventually reaches Plex

## v1.4 Requirements

Requirements for v1.4 release. Each maps to roadmap phases.

### Gap Detection

- [ ] **GAP-01**: Plugin can detect Plex items with empty metadata fields (studio/performers/tags) where Stash has data
- [ ] **GAP-02**: Plugin can detect Stash scenes updated more recently than their last successful sync to Plex
- [ ] **GAP-03**: Plugin can detect Stash scenes that have no matching item in Plex
- [ ] **GAP-04**: Discovered gaps are enqueued through existing persistent queue (reusing retry/backpressure/circuit breaker/DLQ)
- [ ] **GAP-05**: User can scope reconciliation to all scenes or recent scenes (last 24 hours)

### Manual Reconciliation

- [ ] **RECON-01**: User can trigger "Reconcile Library" task from Stash UI
- [ ] **RECON-02**: Reconciliation logs progress summary showing gap counts by type (empty/stale/missing)

### Automated Reconciliation

- [ ] **AUTO-01**: Plugin can run periodic reconciliation at a configurable interval (never/hourly/daily/weekly)
- [ ] **AUTO-02**: Plugin can auto-trigger reconciliation on Stash startup (recent scenes only)
- [ ] **AUTO-03**: User can configure reconciliation scope with date range options (all/24h/7days/custom)

### Reporting

- [ ] **RPT-01**: "View Queue Status" task shows last reconciliation run time, gaps found, and gaps queued by type

## Future Requirements

Deferred to future release. Tracked but not in current roadmap.

### Advanced Reconciliation

- **ADV-01**: Dry-run mode — preview gaps without queuing syncs
- **ADV-02**: Confidence scoring — "definitely empty" vs "possibly stale" gap classification
- **ADV-03**: Per-library reconciliation — reconcile specific Plex library instead of all
- **ADV-04**: Field-level gap detection — show which specific fields are empty/stale

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Bidirectional sync | Stash remains the authoritative metadata source |
| Real-time continuous reconciliation | Hammers APIs; scheduled intervals are industry standard |
| Reconcile on every Plex edit | Requires Plex polling/webhooks infrastructure that doesn't exist |
| Auto-fix without review | Dangerous: may overwrite intentional edits or flood queue |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| GAP-01 | Phase 14 | Pending |
| GAP-02 | Phase 14 | Pending |
| GAP-03 | Phase 14 | Pending |
| GAP-04 | Phase 14 | Pending |
| GAP-05 | Phase 15 | Pending |
| RECON-01 | Phase 15 | Pending |
| RECON-02 | Phase 15 | Pending |
| AUTO-01 | Phase 16 | Pending |
| AUTO-02 | Phase 16 | Pending |
| AUTO-03 | Phase 16 | Pending |
| RPT-01 | Phase 16 | Pending |

**Coverage:**
- v1.4 requirements: 11 total
- Mapped to phases: 11
- Unmapped: 0

✓ 100% requirement coverage achieved

---
*Requirements defined: 2026-02-14*
*Last updated: 2026-02-14 after roadmap creation*
