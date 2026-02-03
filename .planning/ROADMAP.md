# v1.2 Roadmap: Queue UI Improvements

## Overview

Focus: User-facing queue management improvements. Allow users to manage stuck/dead queues directly from Stash UI and handle timeout issues for large backlogs.

## Milestones

- [x] **v1.0 MVP** — Phases 1-5 (shipped 2026-02-03) → [archived](milestones/v1.0-ROADMAP.md)
- [x] **v1.1 Foundation Hardening** — Phases 1-10 + 2.1 (shipped 2026-02-03) → [archived](milestones/v1.1-ROADMAP.md)
- [ ] **v1.2 Queue UI** — Phases 11-13 (in progress)

## Phases

### Phase 11: Queue Management UI
**Goal:** Add button to delete queue in plugin menu to clear out dead items

- Add task in plugin menu to clear/delete queue items
- Allow users to purge dead letter queue entries
- Confirmation dialog before destructive operations
- Status feedback after queue operations

**Success:** Users can clear stuck/dead queue items from Stash UI

**Depends on:** Phase 10

Plans:
- [ ] TBD (run /gsd:plan-phase 11 to break down)

---

### Phase 12: Process Queue Button
**Goal:** Add process queue button to handle stalled queues due to time limits

- Add task in plugin menu to manually trigger queue processing
- Handle long queues that stall due to Stash plugin timeout
- Allow resume/continue processing for large backlogs
- Progress feedback during manual processing

**Success:** Users can manually process stuck queues that timeout

**Depends on:** Phase 11

Plans:
- [ ] TBD (run /gsd:plan-phase 12 to break down)

---

### Phase 13: Dynamic Queue Timeout
**Goal:** Make queue processing timeout dynamic based on item count and average processing time

- Track average time to process each queue item
- Calculate required timeout based on: items_in_queue × avg_time_per_item
- Request appropriate timeout from Stash plugin system
- Handle cases where calculated timeout exceeds Stash limits
- Fallback behavior when timeout cannot be extended

**Success:** Queue processing timeout adapts to workload size, reducing timeouts for large queues

**Depends on:** Phase 12

Plans:
- [ ] TBD (run /gsd:plan-phase 13 to break down)

---

## Phase Dependencies

```
Phase 11 (Queue UI)
    |
Phase 12 (Process Queue)
    |
Phase 13 (Dynamic Timeout)
```

## Estimated Effort

| Phase | Complexity | Plans |
|-------|------------|-------|
| 11. Queue Management UI | Low | 1-2 |
| 12. Process Queue Button | Low | 1-2 |
| 13. Dynamic Queue Timeout | Medium | 1-2 |

**Total:** ~3-6 plans across 3 phases

---
*Created: 2026-02-03*
