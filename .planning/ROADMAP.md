# Roadmap: PlexSync

## Milestones

- ✅ **v1.0 MVP** - Phases 1-5 (shipped 2026-02-03) → [archived](milestones/v1.0-ROADMAP.md)
- ✅ **v1.1 Testing & Documentation** - Phases 1-10 + 2.1 (shipped 2026-02-03) → [archived](milestones/v1.1-ROADMAP.md)
- ✅ **v1.2 Queue Management UI** - Phases 11-13 (shipped 2026-02-04) → [archived](milestones/v1.2-ROADMAP.md)
- ✅ **v1.3 Production Stability** - Ad-hoc (shipped 2026-02-09)
- ✅ **v1.4 Metadata Reconciliation** - Phases 14-16 (shipped 2026-02-14) → [archived](milestones/v1.4-ROADMAP.md)
- 🚧 **v1.5 Outage Resilience** - Phases 17-22 (in progress)

## Phases

<details>
<summary>✅ v1.4 Metadata Reconciliation (Phases 14-16) — SHIPPED 2026-02-14</summary>

- [x] Phase 14: Gap Detection Engine (2/2 plans) — completed 2026-02-14
- [x] Phase 15: Manual Reconciliation (1/1 plans) — completed 2026-02-14
- [x] Phase 16: Automated Reconciliation & Reporting (2/2 plans) — completed 2026-02-14

</details>

### 🚧 v1.5 Outage Resilience (In Progress)

**Milestone Goal:** Automatic recovery when Plex comes back online after downtime — queue drains without user interaction, circuit breaker state persists across restarts, and health monitoring provides visibility into outage/recovery status.

- [x] **Phase 17: Circuit Breaker Persistence** - Circuit breaker state survives plugin restarts — completed 2026-02-15
- [x] **Phase 18: Health Check Infrastructure** - Lightweight Plex connectivity validation — completed 2026-02-15
- [x] **Phase 19: Recovery Detection & Automation** - Automatic Plex recovery detection with queue drain — completed 2026-02-15
- [x] **Phase 20: Graduated Recovery & Rate Limiting** - Rate-limited queue draining prevents overwhelming recovered Plex — completed 2026-02-15
- [ ] **Phase 21: Outage Visibility & History** - Enhanced status UI with outage tracking and history
- [ ] **Phase 22: DLQ Recovery for Outage Jobs** - Re-queue DLQ entries from outage windows

## Phase Details

### Phase 17: Circuit Breaker Persistence
**Goal**: Circuit breaker state persists across plugin restarts, preventing reset-to-CLOSED during outages
**Depends on**: Phase 16 (v1.4 complete)
**Requirements**: STAT-01, VISB-02
**Success Criteria** (what must be TRUE):
  1. Circuit breaker state (CLOSED/OPEN/HALF_OPEN) persists to circuit_breaker.json
  2. Plugin restart during Plex outage preserves OPEN state (no retry exhaustion after restart)
  3. State transitions (CLOSED → OPEN → HALF_OPEN) are logged with descriptive messages
  4. File locking prevents race conditions when concurrent invocations modify circuit breaker state
**Plans**: 2 plans

Plans:
- [ ] 17-01-PLAN.md --- TDD: Circuit breaker persistence, transition logging, and file locking
- [ ] 17-02-PLAN.md --- Wire state_file into SyncWorker and add integration tests

### Phase 18: Health Check Infrastructure
**Goal**: Lightweight Plex connectivity check validates server is reachable and responsive
**Depends on**: Phase 17
**Requirements**: HLTH-01, HLTH-02, HLTH-03
**Success Criteria** (what must be TRUE):
  1. Health check uses server.query('/identity') endpoint (lightweight, validates DB access)
  2. Manual "Health Check" task available in Stash UI shows Plex connectivity status
  3. Hybrid health monitoring combines passive checks (job results) with active probes
  4. Health check interval uses exponential backoff during extended outages (5s → 10s → 20s → 60s cap)
  5. Deep health check prevents false positives from Plex restart sequence (port open but DB loading)
**Plans**: 2 plans

Plans:
- [x] 18-01-PLAN.md --- TDD: Deep health check function using server.query('/identity')
- [x] 18-02-PLAN.md --- Manual health check task + active health probes in worker loop

### Phase 19: Recovery Detection & Automation
**Goal**: Plugin automatically detects when Plex recovers from outage and drains pending queue without user interaction
**Depends on**: Phase 18
**Requirements**: RECV-01, RECV-02, RECV-03, STAT-02
**Success Criteria** (what must be TRUE):
  1. Recovery detection runs on every plugin invocation using check-on-invocation pattern
  2. When circuit is OPEN and Plex health check succeeds, circuit transitions back to CLOSED
  3. Queue automatically drains when Plex recovers (no manual "Process Queue" needed)
  4. Recovery notification logged when circuit closes after outage
  5. Recovery scheduler state (last check time, consecutive successes) persists to recovery_state.json
**Plans**: 2 plans

Plans:
- [x] 19-01-PLAN.md --- TDD: RecoveryScheduler with check-on-invocation pattern and state persistence
- [x] 19-02-PLAN.md --- Wire maybe_check_recovery() into main loop with integration tests

### Phase 20: Graduated Recovery & Rate Limiting
**Goal**: Queue draining after recovery uses graduated rate limiting to avoid overwhelming just-recovered Plex server
**Depends on**: Phase 19
**Requirements**: RECV-04
**Success Criteria** (what must be TRUE):
  1. Recovery period (first 5-10 minutes after circuit closes) enforces rate limiting on queue drain
  2. Graduated scaling increases drain rate over time (5 jobs/sec → 10 → 20 → normal)
  3. Error rate monitoring backs off if failures increase during recovery period
  4. Configurable recovery rate with safe defaults prevents thundering herd on large backlogs
**Plans**: 2 plans

Plans:
- [x] 20-01-PLAN.md --- TDD: RecoveryRateLimiter with token bucket, graduated scaling, and error monitoring
- [x] 20-02-PLAN.md --- Wire rate limiter into worker loop with integration tests

### Phase 21: Outage Visibility & History
**Goal**: Queue status UI shows circuit state, recovery timing, and outage history for debugging
**Depends on**: Phase 20
**Requirements**: VISB-01, VISB-03, VISB-04
**Success Criteria** (what must be TRUE):
  1. "View Queue Status" task displays circuit breaker state (CLOSED/OPEN/HALF_OPEN) and recovery timing
  2. Outage history tracks last 30 outages with start/end times, duration, and jobs affected
  3. "Outage Summary Report" task available in Stash UI shows detailed outage statistics
  4. Enhanced status display shows time since last health check and next scheduled check
**Plans**: TBD

Plans:
- [ ] 21-01: TBD

### Phase 22: DLQ Recovery for Outage Jobs
**Goal**: Re-queue DLQ entries with transient errors from outage windows, enabling recovery of jobs that failed during Plex downtime
**Depends on**: Phase 21
**Requirements**: DLQM-01, DLQM-02
**Success Criteria** (what must be TRUE):
  1. "Recover Outage Jobs" task available in Stash UI identifies DLQ entries from last outage window
  2. Per-error-type filtering allows recovery of specific error classes (PlexServerDown, Timeout, etc.)
  3. Pre-recovery validation checks Plex current state and verifies scene still exists (prevents duplicates)
  4. Recovery operation is idempotent with deduplication tracking (safe to run multiple times)
  5. Conservative recovery defaults to PlexServerDown errors only (safe set), expandable to other types
**Plans**: TBD

Plans:
- [ ] 22-01: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 17 → 18 → 19 → 20 → 21 → 22

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 14. Gap Detection Engine | v1.4 | 2/2 | ✓ Complete | 2026-02-14 |
| 15. Manual Reconciliation | v1.4 | 1/1 | ✓ Complete | 2026-02-14 |
| 16. Automated Reconciliation & Reporting | v1.4 | 2/2 | ✓ Complete | 2026-02-14 |
| 17. Circuit Breaker Persistence | v1.5 | 2/2 | ✓ Complete | 2026-02-15 |
| 18. Health Check Infrastructure | v1.5 | 2/2 | ✓ Complete | 2026-02-15 |
| 19. Recovery Detection & Automation | v1.5 | 2/2 | ✓ Complete | 2026-02-15 |
| 20. Graduated Recovery & Rate Limiting | v1.5 | 2/2 | ✓ Complete | 2026-02-15 |
| 21. Outage Visibility & History | v1.5 | 0/TBD | Not started | - |
| 22. DLQ Recovery for Outage Jobs | v1.5 | 0/TBD | Not started | - |

---
*Last updated: 2026-02-15 after Phase 20 completion*
