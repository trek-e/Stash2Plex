# Roadmap: PlexSync Improvements

## Overview

This roadmap transforms PlexSync from synchronous, fragile metadata sync to a reliable, queue-based architecture. We build from the ground up: persistent queue infrastructure, non-blocking event capture, comprehensive validation, Plex integration with intelligent retry, and finally late update detection. Each phase delivers verifiable reliability improvements that compound toward the goal of "metadata eventually reaches Plex, even when things go wrong."

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Persistent Queue Foundation** - SQLite-backed queue with dead letter queue for durable sync job storage
- [ ] **Phase 2: Validation & Error Classification** - Input validation and error handling before retry logic
- [ ] **Phase 3: Plex API Client** - Plex integration with timeouts and improved matching
- [ ] **Phase 4: Queue Processor with Retry** - Background worker with exponential backoff orchestration
- [ ] **Phase 5: Late Update Detection** - Confidence-based matching and late metadata sync

## Phase Details

### Phase 1: Persistent Queue Foundation
**Goal**: Sync jobs persist to disk and survive process restarts, Plex outages, and crashes
**Depends on**: Nothing (first phase)
**Requirements**: QUEUE-01, QUEUE-02, QUEUE-03
**Success Criteria** (what must be TRUE):
  1. Sync jobs enqueued to SQLite database survive Stash plugin restart
  2. Jobs remain queryable by status (pending, in_progress, completed, failed)
  3. Dead letter queue table stores permanently failed jobs for manual review
  4. Queue operations (enqueue, get_pending, update_status, move_to_dlq) work reliably
**Plans**: 3 plans

Plans:
- [x] 01-01-PLAN.md - Queue infrastructure (manager, models, operations)
- [x] 01-02-PLAN.md - Dead letter queue implementation
- [x] 01-03-PLAN.md - Hook handler, worker, and plugin entry point

### Phase 2: Validation & Error Classification
**Goal**: Invalid data blocked before entering queue; errors classified before retry attempts
**Depends on**: Phase 1
**Requirements**: VALID-01, VALID-02, VALID-03, RTRY-02
**Success Criteria** (what must be TRUE):
  1. Metadata validated against schema before enqueue (pydantic models reject malformed data)
  2. Special characters sanitized to prevent Plex API errors (character limits enforced)
  3. Plugin configuration validated on load (required fields checked, types enforced)
  4. Errors classified as transient (retry) or permanent (DLQ) based on HTTP status and error type
  5. Hook handler completes in <100ms (non-blocking enqueue)
**Plans**: 3 plans

Plans:
- [ ] 02-01-PLAN.md - Sanitizers and error classification utilities
- [ ] 02-02-PLAN.md - Metadata validation model and hook integration
- [ ] 02-03-PLAN.md - Config validation and plugin init integration

### Phase 3: Plex API Client
**Goal**: Reliable Plex communication with timeouts and improved scene matching
**Depends on**: Phase 2
**Requirements**: MATCH-01, RTRY-04
**Success Criteria** (what must be TRUE):
  1. All Plex API calls have explicit connect and read timeouts (no infinite hangs)
  2. Matching logic finds Plex items by file path with reduced false negatives
  3. Plex API errors return classified exceptions (PlexTemporaryError vs PlexPermanentError)
  4. Immediate retries (tenacity) handle network blips (100ms, 200ms, 400ms backoff)
**Plans**: TBD

Plans:
- [ ] 03-01: TBD

### Phase 4: Queue Processor with Retry
**Goal**: Background worker processes queue with exponential backoff and dead letter queue
**Depends on**: Phase 3
**Requirements**: RTRY-01, RTRY-03
**Success Criteria** (what must be TRUE):
  1. Failed Plex API calls retry with exponential backoff and jitter (5s -> 10s -> 20s -> 40s -> 80s)
  2. Permanently failed operations (max 5 retries or permanent errors) move to dead letter queue
  3. Background worker polls queue every 30s for pending jobs
  4. Sync operations complete even when Plex temporarily unavailable (queued work survives outage)
  5. User can review dead letter queue for failed operations requiring manual intervention
**Plans**: TBD

Plans:
- [ ] 04-01: TBD

### Phase 5: Late Update Detection
**Goal**: Stash metadata updates after initial sync propagate to Plex; matching confidence tracked
**Depends on**: Phase 4
**Requirements**: MATCH-02, MATCH-03
**Success Criteria** (what must be TRUE):
  1. Late metadata updates in Stash (after initial incomplete sync) trigger re-sync to Plex
  2. Matches scored with confidence level (high confidence auto-sync, low confidence log for review)
  3. User can review low-confidence matches in logs before manual sync
**Plans**: TBD

Plans:
- [ ] 05-01: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2 -> 3 -> 4 -> 5

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Persistent Queue Foundation | 3/3 | Complete | 2026-01-24 |
| 2. Validation & Error Classification | 0/3 | In Progress | - |
| 3. Plex API Client | 0/? | Not started | - |
| 4. Queue Processor with Retry | 0/? | Not started | - |
| 5. Late Update Detection | 0/? | Not started | - |
