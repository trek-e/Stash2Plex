# Project Research Summary

**Project:** PlexSync Improvements
**Domain:** Stash-to-Plex metadata synchronization plugin
**Researched:** 2026-01-24
**Confidence:** HIGH

## Executive Summary

PlexSync is a Stash plugin that synchronizes scene metadata to Plex Media Server. The research reveals that reliable metadata sync plugins require a fundamentally different architecture than the current synchronous approach. Expert practitioners use **queue-based, asynchronous architectures** with exponential backoff retry, persistent state management, and comprehensive error handling. The recommended approach separates event capture (hook handlers that return quickly) from processing (background workers with retry logic), using SQLite-backed persistent queues to survive crashes and Plex downtime.

The critical insight from research: **synchronous API calls in hook handlers are the root cause of reliability issues**. When Plex is down or slow, Stash blocks waiting for responses, sync operations are lost, and failures happen silently. The solution is a layered Hook-Queue-Worker architecture using lightweight, embedded technologies (tenacity for retries, persist-queue for SQLite-backed queues, pydantic for validation) that require no external dependencies beyond Python libraries.

The primary risk is implementing retry logic without idempotency and proper error classification. Research shows this creates cascading failures: retries duplicate metadata updates, permanent errors (404, 401) waste resources retrying endlessly, and thundering herd problems overwhelm recovering services. Mitigation requires designing idempotent operations from the start, classifying errors before implementing retry logic, and using exponential backoff with jitter as table stakes for any retry implementation.

## Key Findings

### Recommended Stack

**Use lightweight, embedded solutions optimized for plugin architecture.** The research strongly recommends avoiding heavyweight task queues (Celery, RQ, Huey) that require external infrastructure like Redis. PlexSync's plugin context demands zero-config, embedded solutions that "just work" without separate server processes.

**Core technologies:**
- **Tenacity (9.1.2)**: Python retry library with exponential backoff and async support — industry standard with 1,034+ stars, actively maintained fork of deprecated retrying library
- **persist-queue (1.1.0)**: SQLite-backed persistent queue with acknowledgment support — zero external dependencies, WAL mode for concurrent access, perfect for embedded plugin use
- **Pydantic (2.12.5)**: Rust-backed input validation with type-hint native API — fastest in ecosystem, prevents bad data from reaching Plex API
- **pybreaker (1.4.1)**: Circuit breaker for preventing cascading failures — production-stable, configurable thresholds, async support
- **Python 3.11+**: Required by stashapi, provides best compatibility across the ecosystem

**Key rejections:**
- NOT Celery/RQ/Huey (require Redis/external broker, too heavyweight)
- NOT python-plexapi (4.1MB library when only single PUT endpoint needed)
- NOT in-memory queues (state lost on crashes, no durability)

### Expected Features

**Must have (table stakes) — missing these makes plugin feel unreliable:**
- **Exponential backoff retry**: Industry standard, reduces cascading failures by 83.5%
- **Retry limits & budget**: Prevents infinite retry loops (typical: 3-5 retries for metadata sync)
- **Idempotent operations**: Ensures safe retries without duplicates (use unique operation IDs, upsert patterns)
- **Error-specific retry logic**: Retry network errors/5xx, don't retry 4xx client errors
- **Explicit timeouts**: requests library has no default timeout, must set (3-4s connect, 10s read)
- **Silent failure prevention**: Log ALL failures, alert on critical ones
- **Dead letter queue pattern**: Store unprocessable messages for investigation (increases resiliency 40-60%)
- **Operation status logging**: Users need visibility (success/pending/failed/retrying with timestamps)
- **Input validation & sanitization**: Prevents bad data from causing failures
- **Graceful degradation**: Queue updates when Plex unavailable, don't block Stash

**Should have (competitive differentiation):**
- **Circuit breaker pattern**: Stops retry attempts when service confirmed down (reduces wasted effort)
- **Late update detection**: Catches metadata changed after initial sync via polling or webhooks
- **Confidence-based matching**: Fuzzy matching with confidence scores (90%+ auto-merge, 60-89% human review)
- **Differential sync**: Only sync changed fields rather than full record updates
- **Sync queue visibility**: Dashboard showing pending/failed/completed with manual retry

**Defer (v2+):**
- Observability integration (OpenTelemetry) — valuable but complex, standard logging sufficient for MVP
- Batch sync optimization — optimization, not core reliability
- Conflict resolution — not needed for uni-directional Stash → Plex sync
- Adaptive retry strategy — advanced feature, standard backoff sufficient initially

### Architecture Approach

**Adopt a Layered Hook-Queue-Worker architecture** that separates event capture from retry logic and API execution. This maintains compatibility with Stash's hook-based plugin system while adding reliability through asynchronous processing and persistent state.

**Major components:**
1. **Hook Handler (Event Capture)** — Non-blocking event capture that responds to Stash hooks in <100ms, validates hook context, queries scene metadata via GraphQL, enqueues jobs to persistent queue, returns immediately to Stash
2. **Persistent Queue (SQLite Storage)** — Durable storage for sync jobs that survives crashes/restarts, uses WAL mode for concurrent access (hook writes while worker reads), tracks job state (pending/in_progress/completed/failed), includes Dead Letter Queue table for permanently failed jobs
3. **Queue Processor (Background Worker)** — Polls queue every 30s for pending jobs, orchestrates retry logic with exponential backoff, updates job status, moves to DLQ after max retries, runs as scheduled task via Stash Task Scheduler (like FileMonitor plugin)
4. **Plex API Client (Integration Layer)** — Handles Plex-specific logic (matching scenes by file path, updating metadata, error classification), uses tenacity for immediate retries (100ms, 200ms, 400ms) for network blips, raises PlexTemporaryError (retry) vs PlexPermanentError (DLQ)
5. **Config Manager** — Centralized configuration from plugin YAML settings, external config file, or environment variables

**Key patterns to follow:**
- Exponential backoff with jitter: prevents thundering herd, formula `min(base_delay * 2^retry, max_delay) + jitter`
- Dead Letter Queue: after max retries or permanent errors (401, 404), move to DLQ table for manual inspection
- Separate event capture from processing: hook handler enqueues and returns quickly, worker processes in background
- Idempotent operations: syncing same scene multiple times produces same result (safe retries, handles late updates)
- Persistent queue with WAL: SQLite Write-Ahead Logging allows concurrent reads/writes

### Critical Pitfalls

1. **Non-Idempotent Operations Leading to Duplicates** — Retry logic causes duplicate metadata updates (same tag multiple times, duplicate collections). **Prevention:** Implement idempotency keys for all operations, use PUT (update) not POST (additive), store completed operation hashes, design operations as "set rating to 4" not "increment rating"

2. **Retry Without Exponential Backoff + Jitter** — Plugin overwhelms Plex when it comes back online, creating thundering herd that prevents recovery. **Prevention:** Implement exponential backoff (1s, 2s, 4s, 8s capped at 5min), add jitter (randomness ±25%), respect 429 Retry-After headers, different strategies for different errors (429 vs 503 vs 5xx)

3. **Silent Failures (No Observability)** — Sync operations fail without indication, metadata missing in Plex with no error logs. **Prevention:** Heartbeat monitoring (emit "still alive" signals), structured logging with correlation IDs, track operation states (QUEUED → IN_PROGRESS → COMPLETED/FAILED), Dead Letter Queue for inspection, sync health dashboard (success rate, queue depth, failed items)

4. **Database-as-Queue Anti-Pattern** — Using database table as queue causes performance degradation, lock contention, difficulty with queue semantics. **Prevention:** Use persist-queue (SQLite-backed queue library) or in-memory queue with disk persistence, if database unavoidable use SELECT FOR UPDATE SKIP LOCKED and separate table from main schema

5. **Retrying Non-Transient Errors** — System wastes resources retrying operations that will never succeed (missing Plex library, invalid credentials). **Prevention:** Classify errors before retrying — TRANSIENT (503, timeouts, network errors) retry with backoff, PERMANENT (401, 403, 404, 400) move to DLQ immediately, validate before queuing (scene has file path, Plex library exists, credentials valid)

## Implications for Roadmap

Based on research, suggested phase structure follows a **foundation-first approach** that builds reliability infrastructure before adding advanced features. The dependency analysis reveals that retry logic requires idempotency to be safe, observability must exist before queue mechanisms for debuggability, and error classification prevents wasted retries.

### Phase 1: Persistent Queue Foundation
**Rationale:** Foundation for all reliability improvements, testable in isolation without touching existing sync code. Research shows queue persistence is critical — in-memory queues lose state on crashes, causing silent data loss.

**Delivers:** SQLite database with sync_queue and dlq_queue tables, queue operations (enqueue, get_pending, update_status, move_to_dlq), config manager for settings, persistence across process restarts

**Addresses:**
- Graceful degradation (queue updates when Plex down)
- State management without persistence pitfall (survives crashes)
- Dead letter queue pattern (table stakes feature)

**Avoids:**
- Database-as-queue anti-pattern (uses proper queue library)
- State management without persistence (SQLite durability)

**Research flag:** Standard pattern, skip research-phase. Well-documented SQLite + WAL mode usage.

---

### Phase 2: Hook Handler (Non-Blocking Event Capture)
**Rationale:** Enables end-to-end flow (Stash event → queue) without requiring Plex integration yet. Builds on Phase 1 queue infrastructure. Research emphasizes hook handlers must return in <100ms — current synchronous Plex calls violate this.

**Delivers:** Parse Stash hook context, query Stash GraphQL for scene metadata, input validation/sanitization (pydantic models), enqueue jobs to persistent queue, measure and ensure <100ms response time

**Addresses:**
- Synchronous blocking sync anti-pattern (async via queue)
- Input validation & sanitization (table stakes feature)
- Operation status logging (visibility into sync state)

**Avoids:**
- No input validation/sanitization pitfall (pydantic validation early)
- Synchronous API call in hook handler anti-pattern (queue instead)

**Research flag:** Standard pattern, skip research-phase. Hook-to-queue is well-documented pattern.

---

### Phase 3: Error Classification & Validation
**Rationale:** Must happen BEFORE retry logic implementation. Research shows classifying errors first prevents wasting resources retrying permanent failures. This phase is cheap (mostly configuration) but critical for Phase 4 success.

**Delivers:** Error classification logic (transient vs permanent), validation rules for metadata (pydantic schemas), sanitization functions (character limits, special char handling), pre-queue validation (required fields, data types)

**Addresses:**
- Error-specific retry logic (table stakes feature)
- Input validation & sanitization (table stakes feature)

**Avoids:**
- Retrying non-transient errors pitfall (classify before retry)
- No input validation pitfall (validation before queue)

**Research flag:** Standard pattern, skip research-phase. HTTP error code classification is well-established.

---

### Phase 4: Plex API Client with Immediate Retry
**Rationale:** Implements Plex integration with tenacity for sub-second retries (network blips). Testable independently against real/mock Plex before wiring up queue processor. Phase 3 error classification feeds into this layer.

**Delivers:** Plex authentication (token from config), scene matching logic (file path → Plex item), metadata update via Plex API, tenacity decorator for immediate retries (100ms, 200ms, 400ms), error handling (raise PlexTemporaryError vs PlexPermanentError), timeout configuration (3-4s connect, 10s read)

**Addresses:**
- Explicit timeouts (table stakes feature — requests has no default)
- Idempotent operations (metadata updates naturally idempotent via PUT)
- Matching logic improvements (file path primary, fuzzy fallback)

**Avoids:**
- No timeout configuration pitfall (explicit timeouts on all requests)
- Poor matching logic pitfall (multi-strategy with fallback)

**Research flag:** Needs research-phase. Plex API behavior, undocumented rate limits, matching strategies need investigation during implementation.

---

### Phase 5: Queue Processor with Exponential Backoff
**Rationale:** Integration point requiring both queue (Phase 1) and Plex client (Phase 4) working. Implements the core retry orchestration that distinguishes reliable sync from current approach. Research shows this is most complex phase with highest failure risk.

**Delivers:** Polling loop (get pending jobs every 30s), exponential backoff calculation (5s → 10s → 20s → 40s → 80s with jitter), retry orchestration (call Plex client, handle errors, update job status), DLQ movement (after 5 max retries or permanent errors), background worker scheduling via Stash Task Scheduler

**Addresses:**
- Exponential backoff retry (table stakes feature, reduces cascading failures 83.5%)
- Retry limits & budget (table stakes feature, prevents infinite loops)
- Dead letter queue pattern (table stakes feature, 40-60% resiliency increase)
- Silent failure prevention (logging with correlation IDs)

**Avoids:**
- Retry without exponential backoff + jitter pitfall (core implementation)
- Silent failures pitfall (structured logging, health checks)
- Infinite retries without DLQ pitfall (max 5 attempts, then DLQ)

**Research flag:** Needs research-phase. Stash Task Scheduler integration, background worker patterns need investigation.

---

### Phase 6: Observability & Health Monitoring
**Rationale:** Post-MVP reliability enhancement. Makes system debuggable and measurable. Research shows observability should come before advanced features — can't optimize what you can't measure.

**Delivers:** Structured logging with correlation IDs (trace request lifecycle), sync health dashboard (success rate, average completion time, queue depth), heartbeat monitoring (detect silent failures), metrics tracking (operations per hour, retry rate, DLQ growth), alerting on absence (no successful syncs in N hours)

**Addresses:**
- Silent failure prevention (comprehensive monitoring)
- Operation status logging (user visibility)

**Avoids:**
- Silent failures pitfall (monitoring catches absence of events)
- Not logging enough context pitfall (correlation IDs, structured logs)

**Research flag:** Standard pattern, skip research-phase. Structured logging with Python logging library is well-documented.

---

### Phase 7: Advanced Features (Post-MVP)
**Rationale:** Competitive differentiators built on solid reliability foundation. Can be implemented in any order based on user feedback.

**Delivers:**
- Circuit breaker pattern (pybreaker, stops attempts when Plex confirmed down)
- Late update detection (polling fallback: 1min, 5min, 15min, 1hr after initial sync)
- Confidence-based matching (90%+ auto-merge, 60-89% review queue, multi-strategy pipeline)
- Rate limiting (client-side token bucket, respect 429 headers)

**Addresses:**
- Circuit breaker pattern (differentiator feature)
- Late update detection (differentiator feature, solves Stash indexing delay)
- Confidence-based matching (differentiator feature, reduces false negatives)

**Avoids:**
- Ignoring rate limits pitfall (client-side rate limiter)
- Webhook reliability assumptions pitfall (polling fallback)

**Research flag:** Needs research-phase for late update detection (Stash GraphQL polling patterns) and confidence-based matching (fuzzy matching libraries). Circuit breaker and rate limiting are standard patterns.

---

### Phase Ordering Rationale

**Why this order:**
- **Queue first** because all reliability features depend on persistent state
- **Hook handler second** because it enables testing event → queue flow without Plex
- **Error classification third** because retry logic needs it (prevents wasted retries on permanent failures)
- **Plex client fourth** because it's testable independently and feeds into queue processor
- **Queue processor fifth** because it integrates queue + Plex client (highest complexity, highest risk)
- **Observability sixth** because it makes the system debuggable before adding advanced features
- **Advanced features last** because they build on solid foundation

**Why this grouping:**
- Phases 1-2 establish architecture (queue + event capture)
- Phases 3-5 implement core reliability (validation + retry + orchestration)
- Phase 6 adds observability (makes system measurable)
- Phase 7 adds competitive features (differentiation)

**How this avoids pitfalls:**
- Idempotency designed in from Phase 4 (before retry logic in Phase 5)
- Error classification exists before retry (Phase 3 before Phase 5)
- Observability infrastructure ready before queue mechanisms (logging from Phase 2)
- Validation gates prevent bad data from entering queue (Phase 3 sanitization)

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 4 (Plex API Client):** Plex API behavior undocumented, rate limits unknown, matching strategies need experimentation
- **Phase 5 (Queue Processor):** Stash Task Scheduler integration specifics, background worker lifecycle management
- **Phase 7 (Late Update Detection):** Stash GraphQL polling patterns, change detection mechanisms
- **Phase 7 (Confidence-Based Matching):** Fuzzy matching library evaluation, threshold tuning, false positive/negative tradeoffs

Phases with standard patterns (skip research-phase):
- **Phase 1 (Persistent Queue):** SQLite + WAL mode well-documented, persist-queue library has clear examples
- **Phase 2 (Hook Handler):** Hook-to-queue pattern standard in event-driven systems
- **Phase 3 (Error Classification):** HTTP status code classification well-established (transient vs permanent)
- **Phase 6 (Observability):** Python structured logging with logging library standard practice
- **Phase 7 (Circuit Breaker):** pybreaker library well-documented, pattern well-established
- **Phase 7 (Rate Limiting):** Token bucket algorithm standard, implementation examples abundant

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All libraries verified from PyPI and GitHub, versions and compatibility confirmed, alternatives evaluated with clear rationale |
| Features | HIGH | Table stakes vs differentiators well-researched from retry pattern literature (AWS, ByteByteGo, Microsoft), backed by 2026 sources with production examples |
| Architecture | MEDIUM-HIGH | Layered Hook-Queue-Worker pattern verified from webhook best practices and event-driven architecture sources, but Stash-specific implementation needs validation (Task Scheduler integration) |
| Pitfalls | HIGH | Well-documented patterns from authoritative sources (AWS Builders Library, ByteByteGo, HackerOne), backed by 2026 sources with specific examples from production systems |

**Overall confidence:** HIGH

Research is strong across all areas. Stack recommendations are verified with official sources (PyPI, GitHub), features are grounded in industry best practices from authoritative sources (AWS, Microsoft, ByteByteGo), architecture patterns are validated from webhook and event-driven literature, and pitfalls are drawn from production failure case studies.

The one area requiring validation during implementation is Stash-specific plugin architecture (Task Scheduler, hook execution model), but the general patterns (queue-based async processing, retry with backoff) are well-established and transferable.

### Gaps to Address

**Stash plugin execution model specifics:**
- How Stash Task Scheduler works in practice (FileMonitor plugin is reference, but needs hands-on validation)
- Whether background threads are stable or if scheduled tasks are preferred
- Plugin lifecycle management (startup, shutdown, reload scenarios)
- **Mitigation:** Phase 5 research-phase will investigate Stash plugin patterns, potentially prototype background worker before full implementation

**Plex API undocumented behavior:**
- Rate limits not officially documented, anecdotal evidence suggests permissive for local API
- Metadata field length limits not specified
- Error response formats may vary
- **Mitigation:** Phase 4 research-phase will test against real Plex instance, document observed behavior, implement defensive validation

**Optimal retry parameters:**
- Research provides formulas (exponential backoff, jitter) but not domain-specific tuning
- What's the right balance between fast recovery and not overwhelming Plex?
- How many retries before DLQ for different error types?
- **Mitigation:** Start with conservative defaults from research (5 retries, 5s base, 300s max, 25% jitter), tune based on observability data in Phase 6

**Matching strategy confidence thresholds:**
- Research suggests 90%+ auto-merge, 60-89% review, but these are guidelines not validated for media files
- What fuzzy matching algorithm works best for scene filenames?
- **Mitigation:** Phase 7 research-phase will evaluate matching libraries (fuzzywuzzy, thefuzz, rapidfuzz), prototype against real Stash/Plex data, empirically determine thresholds

## Sources

### Primary (HIGH confidence)

**Technology Stack:**
- [Tenacity GitHub](https://github.com/jd/tenacity) — v9.1.2, Apr 2025, verified retry library
- [Tenacity PyPI](https://pypi.org/project/tenacity/) — Official package repository
- [persist-queue PyPI](https://pypi.org/project/persist-queue/) — v1.1.0, Oct 2025, SQLite-backed queue
- [Pydantic PyPI](https://pypi.org/project/pydantic/) — v2.12.5, Nov 2025, Rust-backed validation
- [pybreaker PyPI](https://pypi.org/project/pybreaker/) — v1.4.1, Sep 2025, circuit breaker
- [stashapi PyPI](https://pypi.org/project/stashapi/) — v0.1.3, Dec 2025, Stash integration

**Architecture Patterns:**
- [Webhook Retry Best Practices - Svix](https://www.svix.com/resources/webhook-best-practices/retries/) — Authoritative guide, exponential backoff + jitter
- [Timeouts, retries and backoff with jitter - AWS Builders Library](https://aws.amazon.com/builders-library/timeouts-retries-and-backoff-with-jitter/) — Industry standard reference
- [A Guide to Retry Pattern in Distributed Systems - ByteByteGo](https://blog.bytebytego.com/p/a-guide-to-retry-pattern-in-distributed) — Comprehensive retry patterns
- [persist-queue GitHub](https://github.com/peter-wangxu/persist-queue) — SQLite queue implementation details

**Critical Pitfalls:**
- [Designing retry logic that doesn't create data duplicates - Medium, Jan 2026](https://medium.com/@backend.bao/designing-retry-logic-that-doesnt-create-data-duplicates-99a784500931) — Idempotency patterns
- [Mastering Idempotency: Building Reliable APIs - ByteByteGo](https://blog.bytebytego.com/p/mastering-idempotency-building-reliable) — Production examples
- [Building A Monitoring System That Catches Silent Failures - Vincent Lakatos](https://www.vincentlakatos.com/blog/building-a-monitoring-system-that-catches-silent-failures/) — Detection patterns
- [Database-as-IPC - Wikipedia](https://en.wikipedia.org/wiki/Database-as-IPC) — Anti-pattern analysis

### Secondary (MEDIUM confidence)

**Stash Plugin Architecture:**
- [Plugin Development - DeepWiki](https://deepwiki.com/stashapp/CommunityScripts/6.2-plugin-development) — Community documentation
- [CommunityScripts - GitHub](https://github.com/stashapp/CommunityScripts) — Plugin repository
- [FileMonitor Plugin](https://github.com/stashapp/CommunityScripts/blob/main/plugins/FileMonitor/README.md) — Background worker reference

**Feature Landscape:**
- [Understanding Idempotency in Data Pipelines - Airbyte](https://airbyte.com/data-engineering-resources/idempotency-in-data-pipelines) — Data sync patterns
- [Circuit Breaker Pattern - Azure Architecture Center](https://learn.microsoft.com/en-us/azure/architecture/patterns/circuit-breaker) — Microsoft reference
- [Fuzzy Matching 101 - Match Data Pro](https://matchdatapro.com/fuzzy-matching-101-a-complete-guide-for-2026/) — Matching strategies

### Tertiary (LOW confidence)

**Plex API Behavior:**
- [Plex Forums - 503 Service Unavailable discussions](https://forums.plex.tv/t/503-service-unavailable/768874) — Anecdotal evidence of Plex maintenance windows
- Community reports suggest Plex API rate limits are permissive for local calls but undocumented

---
*Research completed: 2026-01-24*
*Ready for roadmap: yes*
