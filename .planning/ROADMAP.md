# Roadmap: PlexSync v1.4 Metadata Reconciliation

## Milestones

- ✅ **v1.0 MVP** - Phases 1-5 (shipped 2026-02-03) → [archived](milestones/v1.0-ROADMAP.md)
- ✅ **v1.1 Testing & Documentation** - Phases 1-10 + 2.1 (shipped 2026-02-03) → [archived](milestones/v1.1-ROADMAP.md)
- ✅ **v1.2 Queue Management UI** - Phases 11-13 (shipped 2026-02-04) → [archived](milestones/v1.2-ROADMAP.md)
- ✅ **v1.3 Production Stability** - Ad-hoc (shipped 2026-02-09)
- ✅ **v1.4 Metadata Reconciliation** - Phases 14-16 (shipped 2026-02-14)

## Overview

v1.4 adds metadata reconciliation to detect and repair gaps between Stash and Plex. The three-phase journey builds a gap detection engine (empty fields, stale timestamps, missing items), adds manual reconciliation control, then automates with scheduling and enhanced reporting. All gaps flow through the existing queue infrastructure, reusing retry, backpressure, circuit breaker, and DLQ mechanisms.

## Phases

**Phase Numbering:**
- Integer phases (14, 15, 16): Planned milestone work
- Decimal phases (14.1, 14.2): Urgent insertions (marked with INSERTED)

### ✅ v1.4 Metadata Reconciliation (Complete)

**Milestone Goal:** Detect and repair metadata gaps between Stash and Plex — covering items with empty Plex fields, stale syncs, and scenes missing from Plex entirely.

- [x] **Phase 14: Gap Detection Engine** - Core logic to detect empty metadata, stale syncs, and missing Plex items ✓ 2026-02-14
- [x] **Phase 15: Manual Reconciliation** - User-triggered reconciliation task with scope control ✓ 2026-02-14
- [x] **Phase 16: Automated Reconciliation & Reporting** - Periodic scheduling, startup trigger, and enhanced status reporting ✓ 2026-02-14

## Phase Details

### Phase 14: Gap Detection Engine
**Goal**: Plugin can detect three types of metadata gaps and enqueue them for sync
**Depends on**: Nothing (uses existing infrastructure)
**Requirements**: GAP-01, GAP-02, GAP-03, GAP-04
**Success Criteria** (what must be TRUE):
  1. Plugin can identify Plex items with empty studio/performers/tags fields where Stash has populated data
  2. Plugin can identify Stash scenes with updated_at timestamps newer than their last successful sync timestamp
  3. Plugin can identify Stash scenes that have no matching Plex item (by querying Plex libraries)
  4. Detected gaps are enqueued as sync jobs through the existing persistent queue infrastructure
  5. Gap detection reuses existing Stash GQL client, Plex matcher, and sync timestamp tracking
**Plans:** 2 plans

Plans:
- [x] 14-01-PLAN.md — GapDetector core: TDD for three gap detection methods (empty metadata, stale sync, missing items)
- [x] 14-02-PLAN.md — GapDetectionEngine: orchestration layer wiring detector to Stash GQL, Plex matcher, and queue

### Phase 15: Manual Reconciliation
**Goal**: User can trigger reconciliation on-demand with configurable scope
**Depends on**: Phase 14 (gap detection engine)
**Requirements**: GAP-05, RECON-01, RECON-02
**Success Criteria** (what must be TRUE):
  1. User can trigger "Reconcile Library" task from Stash plugin task menu
  2. User can choose reconciliation scope: all scenes or recent scenes (last 24 hours)
  3. Reconciliation logs progress summary showing gap counts by type (empty metadata: X, stale sync: Y, missing from Plex: Z)
  4. Reconciliation completes without overwhelming the queue (gaps are enqueued, not processed inline)
**Plans:** 1 plan

Plans:
- [x] 15-01-PLAN.md — Wire GapDetectionEngine into Stash plugin task system with scope control and progress logging

### Phase 16: Automated Reconciliation & Reporting
**Goal**: Plugin automatically reconciles on schedule and reports reconciliation history in UI
**Depends on**: Phase 15 (manual reconciliation)
**Requirements**: AUTO-01, AUTO-02, AUTO-03, RPT-01
**Success Criteria** (what must be TRUE):
  1. Plugin runs periodic reconciliation at configured interval (never/hourly/daily/weekly) without user action
  2. Plugin auto-triggers reconciliation on Stash startup, scoped to recent scenes only (last 24 hours)
  3. User can configure reconciliation scope with date range options (all/24h/7days/custom range)
  4. "View Queue Status" task displays last reconciliation run time, total gaps found, and gaps queued by type
**Plans:** 2 plans

Plans:
- [x] 16-01-PLAN.md — Config, scheduler state persistence, auto-reconciliation wiring, enhanced queue status
- [x] 16-02-PLAN.md — Comprehensive tests for scheduler, auto-reconciliation, and enhanced status

## Progress

**Execution Order:**
Phases execute in numeric order: 14 → 15 → 16

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 14. Gap Detection Engine | 2/2 | ✓ Complete | 2026-02-14 |
| 15. Manual Reconciliation | 1/1 | ✓ Complete | 2026-02-14 |
| 16. Automated Reconciliation & Reporting | 2/2 | ✓ Complete | 2026-02-14 |

---
*Roadmap created: 2026-02-14*
*Last updated: 2026-02-14 after phase 16 completion*
