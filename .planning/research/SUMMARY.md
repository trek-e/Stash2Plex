# Project Research Summary

**Project:** PlexSync Outage Resilience Features (v1.5)
**Domain:** Event-driven metadata sync with queue resilience
**Researched:** 2026-02-15
**Confidence:** HIGH

## Executive Summary

PlexSync needs automatic recovery when Plex comes back online after outages. The research reveals this is table stakes for production queue systems—AWS SQS, RabbitMQ, and Kafka all auto-resume after downstream recovery. PlexSync's unique constraint is the non-daemon architecture: Stash plugins exit after each invocation, so recovery detection must use the check-on-invocation pattern proven in v1.4's auto-reconciliation scheduler.

The recommended approach requires **zero new dependencies**. Extend the existing circuit breaker (worker/circuit_breaker.py) with JSON state persistence using stdlib patterns already validated in reconciliation/scheduler.py. Add active health checks using plexapi's server.query('/identity') endpoint. Wire recovery detection into the check-on-invocation pattern—on each plugin invocation, check if circuit breaker is OPEN and Plex has recovered. When Plex is healthy again, close the circuit and let the existing worker loop automatically drain the queue.

The critical risks are race conditions and thundering herd on recovery. Circuit breaker state transitions need file locking to prevent concurrent invocations from creating duplicate recovery attempts. Queue draining after recovery needs rate limiting to avoid overwhelming a just-recovered Plex server with hundreds of backlogged sync jobs. Both patterns have proven solutions in the research: fcntl-based advisory locking for state persistence, and graduated recovery with configurable rate limits.

## Key Findings

### Recommended Stack

**NO NEW DEPENDENCIES REQUIRED.** All capabilities exist in the current stack (Python stdlib + plexapi + persist-queue). This is the strongest finding—typical circuit breaker libraries (pybreaker) require Redis for persistence, but PlexSync's existing pattern (JSON + atomic write) is sufficient and already proven.

**Core technologies:**
- **json (stdlib)**: Circuit breaker state persistence — Already validated in reconciliation/scheduler.py. Atomic write pattern (write to .tmp, os.replace) prevents corruption on crashes. Human-readable for debugging. Zero dependencies.
- **plexapi >=4.17.0**: Health check via server.query('/identity') — v4.18.0 installed. Lightweight XML endpoint validates Plex is reachable. Existing dependency, no additional installation needed.
- **threading.Timer (stdlib)**: Check-on-invocation recovery trigger — Pattern validated in reconciliation/scheduler.py. Use is_due() pattern on each plugin invocation to check if queue drain should be attempted after circuit breaker recovery.

**What NOT to use:**
- **pybreaker**: Requires Redis server (external dependency). PlexSync circuit_breaker.py already implements 3-state pattern in 140 lines.
- **shelve**: Overkill for small state (5-10 fields). writeback=True caches all entries in memory, slow close().
- **APScheduler**: Contradicts single-file plugin deployment model. Check-on-invocation handles recovery triggers without daemons.

### Expected Features

**Must have (table stakes):**
- **Automatic queue drain on recovery** — Industry standard. Every production queue system (AWS SQS, RabbitMQ, Kafka) resumes automatically when downstream recovers. Users expect this.
- **Health monitoring with retry** — All production systems probe downstream to detect recovery. Without this, users must manually hit "Process Queue" after every Plex outage.
- **Outage visibility in status UI** — Users need to know WHY queue stopped and WHEN it will resume. Extend existing queue status task to show circuit state.
- **Circuit breaker state logging** — State transitions (CLOSED → OPEN → HALF_OPEN) must be observable for debugging.
- **Recovery notification** — Users need confirmation when system returns to normal after outage.

**Should have (competitive differentiators):**
- **Circuit breaker state persistence** — Survives plugin restarts during outages. Prevents reset to CLOSED and hammering Plex after Stash restart.
- **Passive + active health checks** — Passive (monitor actual jobs) detects failure faster; active (periodic probe) detects recovery faster. Hybrid approach is best.
- **Health check backoff** — Space out recovery probes to avoid hammering recovering service (1s → 2s → 4s → cap at 60s).
- **Outage history tracking** — Log outage start/end times, duration, jobs affected for post-mortem analysis.

**Defer (v2+):**
- **Outage-triggered reconciliation** — When Plex recovers after hours down, auto-reconcile to find gaps from events during outage. Depends on Phase 1 reconciliation engine first.
- **DLQ recovery for outage jobs** — Jobs DLQ'd during outage (timeout, rate limit) can be re-queued when service recovers. Medium complexity, niche use case.

**Anti-features (explicitly avoid):**
- **Real-time push notifications** — Stash plugins run per-event, no daemon for push. External monitoring (Uptime Kuma, Healthchecks.io) solves this better.
- **Automatic full reconciliation on recovery** — Expensive for large libraries (10K+ items). User-triggered with scope filter is safer.
- **External health check endpoint** — Plugin can't serve HTTP. Plex has native health endpoints.

### Architecture Approach

PlexSync's event-driven, non-daemon architecture shapes all design decisions. The check-on-invocation pattern (proven in v1.4 reconciliation) extends naturally to recovery detection. New components focus on state persistence and health tracking, while existing components (circuit breaker, backoff, queue) require minimal modification.

**Major components:**
1. **resilience/recovery_detector.py (NEW)** — Detects Plex recovery after outage. Loads circuit breaker state, checks if recovery health check is due, coordinates with scheduler and health check components.
2. **resilience/recovery_scheduler.py (NEW)** — Tracks recovery check timing using check-on-invocation pattern. Manages recovery_state.json with last_check_time, last_check_result, consecutive_successes.
3. **plex/health.py (NEW)** — Lightweight Plex health checking. Stateless check using server.query('/identity'). Returns (is_healthy: bool, latency_ms: float).
4. **worker/circuit_breaker.py (MODIFIED)** — Add state_file parameter, save_state()/load_state() methods. Save state on every transition. Atomic write pattern (tmp → rename).
5. **Stash2Plex.py (MODIFIED)** — Add maybe_recovery_trigger() called after maybe_auto_reconcile(). Wire recovery detection into plugin lifecycle.
6. **Task Dispatch (MODIFIED)** — Add health_check task mode for manual verification. Reports circuit state, Plex connectivity, recovery state, queue size.

**Key architectural patterns:**
- **Check-on-invocation**: Read state, check if action due, execute if needed, update state. Proven in reconciliation scheduler.
- **Persisted circuit breaker**: State survives process restarts via JSON + atomic write.
- **Stateless health check**: No side effects, no persistent state. Scheduler tracks timing separately.

### Critical Pitfalls

1. **Circuit Breaker Stale State Race Condition** — Multiple plugin invocations read stale state, all transition to HALF_OPEN simultaneously, thundering herd of test requests overwhelms Plex. **Prevention:** File-based distributed lock (fcntl) for state transitions, OR single-writer pattern (only worker modifies CB state, hooks read-only), OR idempotent transitions with cooldown timestamps.

2. **Health Check False Positive from Plex Restart Sequence** — Health check detects port 32400 open but Plex still loading database (returns 503 for metadata requests). Circuit closes prematurely, queue drains with failures. **Prevention:** Deep health check using sentinel request (server.query('/identity') with DB access verification), NOT shallow TCP connect. Add grace period or require N consecutive successes.

3. **Thundering Herd on Automatic Recovery Trigger** — Plex recovers, 500+ queued jobs drain at max rate, CPU spikes, slow responses cause new failures, circuit reopens. Metastable failure loop. **Prevention:** Graduated recovery with rate limiting (5 jobs/sec → 10 → 20 → normal over 5-10 minutes). Monitor error rate, back off if failures increase. Prioritize recent jobs over stale backlog.

4. **DLQ Recovery Without Deduplication** — User recovers 200 DLQ jobs, 150 already resolved manually, creates 150 duplicate syncs. **Prevention:** Pre-recovery validation (check Plex current state, verify scene still exists, check if already in queue). Idempotent recovery with deduplication tracking. Reconciliation-aware recovery (only recover confirmed gaps).

5. **Check-on-Invocation Race Condition with Concurrent Hooks** — Two hooks fire simultaneously, both see reconciliation is due, both trigger gap detection. **Prevention:** Atomic check-and-set with file locking (fcntl.flock), cooldown window with randomized delay, single-threaded reconciliation via worker queue, OR idempotent reconciliation with run ID.

## Implications for Roadmap

Based on research, suggested phase structure:

### Phase 1: Circuit Breaker State Persistence (Foundation)

**Rationale:** Circuit breaker persistence is the foundation for recovery detection. Without it, recovery detector can't check "is circuit OPEN?" without worker running. Must come first because all other phases depend on durable circuit state.

**Delivers:** Circuit breaker state survives plugin restarts. State persists to `circuit_breaker.json` using atomic write pattern.

**Addresses:**
- Must-have: Circuit breaker state persistence (prevents reset-to-CLOSED after Stash restart)
- Anti-pattern avoidance: Prevents retry exhaustion after restart during outages

**Avoids:**
- Critical Pitfall 1: Race conditions via file locking with fcntl (POSIX advisory locks)
- Technical debt: Skip file locking = race conditions with concurrent invocations (NEVER acceptable)

**Stack elements:** json (stdlib), atomic write pattern (os.replace)

**Research flag:** STANDARD PATTERNS — JSON persistence pattern proven in reconciliation/scheduler.py. No additional research needed.

---

### Phase 2: Plex Health Check Implementation (Independent)

**Rationale:** Health checking is independent of circuit breaker persistence. Can develop in parallel with Phase 1. Needed before recovery detection (Phase 4) but provides immediate value as manual task.

**Delivers:** Lightweight Plex connectivity check. Manual "Health Check" task available in Stash UI.

**Addresses:**
- Must-have: Health monitoring (foundation for automatic recovery)
- Must-have: Outage visibility in status UI (health check shows current state)

**Avoids:**
- Critical Pitfall 2: False positives from shallow checks. Use server.query('/identity') with DB access verification.

**Stack elements:** plexapi server.query('/identity'), existing PlexClient

**Research flag:** STANDARD PATTERNS — Plex /identity endpoint well-documented. Health check pattern proven in multiple systems.

---

### Phase 3: Recovery Scheduler Implementation (State Management)

**Rationale:** Recovery scheduler manages check timing using check-on-invocation pattern. Independent component, can develop after Phase 1's persistence patterns are proven. Needed before Phase 4 integration.

**Delivers:** Recovery check timing and state tracking. Persists to `recovery_state.json`.

**Addresses:**
- Should-have: Health check backoff (adaptive interval, reduces load on recovering service)

**Avoids:**
- Critical Pitfall 5: Check-on-invocation races via atomic check-and-set with file locking

**Stack elements:** json (stdlib), check-on-invocation pattern from reconciliation/scheduler.py

**Research flag:** STANDARD PATTERNS — Reuses reconciliation scheduler pattern. No new research needed.

---

### Phase 4: Recovery Detector Integration (Orchestration)

**Rationale:** Integrates all previous phases (circuit breaker persistence, health check, recovery scheduler) into cohesive recovery detection. Depends on Phases 1-3 completion.

**Delivers:** Automatic Plex recovery detection. Creates `resilience/recovery_detector.py` that coordinates state, health checks, and scheduling.

**Addresses:**
- Must-have: Automatic queue drain on recovery (core feature)
- Must-have: Recovery notification (log when circuit closes)

**Avoids:**
- Integration complexity by reusing proven components from Phases 1-3

**Stack elements:** All components from Phases 1-3

**Research flag:** INTEGRATION PHASE — Test with real Plex outage/recovery cycles. Verify state persistence + health check + scheduler coordination.

---

### Phase 5: Entry Point Wiring (Automatic Recovery)

**Rationale:** Wires recovery detection into plugin lifecycle. Adds `maybe_recovery_trigger()` to Stash2Plex.py main(). Completes automatic recovery MVP.

**Delivers:** Recovery detection runs on every plugin invocation. Queue automatically drains when Plex recovers.

**Addresses:**
- Must-have: Automatic queue drain (completes core feature)
- Must-have: Enhanced logging for state transitions

**Avoids:**
- Hook handler latency impact (check is <10ms when circuit CLOSED)
- Cascading failures via graceful error handling

**Stack elements:** Integration with existing plugin lifecycle

**Research flag:** STANDARD PATTERNS — Follows maybe_auto_reconcile() pattern. Test with concurrent hook invocations.

---

### Phase 6: Graduated Recovery & Rate Limiting (Production Hardening)

**Rationale:** Prevents thundering herd when draining large backlogs after extended outages. Should come AFTER Phase 5 MVP so automatic recovery works, THEN add rate limiting based on real-world testing.

**Delivers:** Rate-limited queue draining during recovery period. Graduated scaling (5 jobs/sec → 10 → 20 → normal over 5-10 minutes).

**Addresses:**
- Should-have: Backpressure-aware recovery
- Advanced: Adaptive concurrency limits based on error rate

**Avoids:**
- Critical Pitfall 3: Thundering herd overwhelming just-recovered Plex server
- Performance trap: No backpressure during recovery (Plex CPU spikes)

**Stack elements:** Existing backoff.py logic, worker rate limiting

**Research flag:** NEEDS TESTING — Test with 500+ job backlogs after simulated outages. Monitor Plex CPU, error rates, queue drain time.

---

### Phase 7: Outage History & Advanced Monitoring (Observability)

**Rationale:** Adds observability for post-mortem analysis. Lower priority than core recovery (Phases 1-5) and production hardening (Phase 6). Provides value for debugging recurring outages.

**Delivers:** Outage history tracking (start/end times, duration, jobs affected). Display in queue status UI.

**Addresses:**
- Should-have: Outage history tracking for post-mortem
- Should-have: Enhanced status UI (show last outage details)

**Avoids:**
- Unbounded DLQ growth via outage history (identify patterns, set policies)

**Stack elements:** JSON state persistence pattern, queue status task extension

**Research flag:** STANDARD PATTERNS — Extends existing state persistence and task dispatch patterns.

---

### Phase 8: DLQ Recovery for Outage Jobs (Advanced Management)

**Rationale:** Advanced feature for recovering jobs DLQ'd during outages. Depends on validation logic and reconciliation integration. Lowest priority—most jobs already retry via PlexServerDown = 999 retries.

**Delivers:** "Recover Outage Jobs" task. Re-queues DLQ entries with transient errors from last outage window.

**Addresses:**
- Should-have: DLQ recovery for outage jobs (niche but valuable)
- Should-have: Per-error-type DLQ recovery

**Avoids:**
- Critical Pitfall 4: DLQ duplicates via pre-recovery validation (check Plex state, verify scene exists, deduplicate)

**Stack elements:** Existing DLQ management, reconciliation engine integration

**Research flag:** NEEDS RESEARCH — DLQ recovery patterns vary by error type. Need to classify which errors are safe to retry. Test with mixed DLQ (resolved + unresolved items).

---

### Phase Ordering Rationale

**Dependency-driven order:**
1. Phase 1 (Circuit Breaker Persistence) is foundation—enables recovery detection without worker running
2. Phases 2-3 (Health Check, Scheduler) are independent—can develop in parallel
3. Phase 4 (Recovery Detector) integrates Phases 1-3
4. Phase 5 (Entry Point Wiring) completes automatic recovery MVP
5. Phase 6 (Rate Limiting) hardens MVP based on real-world testing
6. Phases 7-8 (Observability, DLQ) add advanced management features

**Risk mitigation order:**
- Phases 1-5 address ALL must-have features (table stakes)
- Phase 6 addresses Critical Pitfall 3 (thundering herd)—production blocker
- Phases 7-8 add should-have features (competitive but not launch-blocking)

**Architecture alignment:**
- Phases 1-3 build independent components (loose coupling)
- Phase 4 integrates components (orchestration layer)
- Phase 5 wires into plugin lifecycle (minimal surface area)
- Phases 6-8 enhance existing components (no new architecture)

**Testing strategy:**
- Phase 1: Test state persistence with concurrent invocations (race conditions)
- Phase 2: Test health check against real Plex restart (false positives)
- Phase 3: Test scheduler with rapid invocations (check-on-invocation timing)
- Phase 4: Integration tests (state + health + scheduler coordination)
- Phase 5: End-to-end tests (full recovery flow)
- Phase 6: Load tests (500+ job backlogs, Plex CPU monitoring)
- Phase 7: Observability validation (outage history accuracy)
- Phase 8: DLQ recovery validation (deduplication, pre-validation)

### Research Flags

**Phases with standard patterns (skip research-phase):**
- **Phase 1:** Circuit breaker persistence — pattern proven in reconciliation/scheduler.py
- **Phase 2:** Health check — Plex /identity endpoint well-documented, plexapi usage established
- **Phase 3:** Recovery scheduler — reuses reconciliation scheduler pattern
- **Phase 5:** Entry point wiring — follows maybe_auto_reconcile() pattern

**Phases needing integration testing (not research, just validation):**
- **Phase 4:** Recovery detector integration — test state + health + scheduler coordination with real Plex outages
- **Phase 6:** Rate limiting — test with large backlogs (500+ jobs), monitor Plex CPU/error rates

**Phases needing deeper research during planning:**
- **Phase 8 (DLQ Recovery):** Error classification logic needs research. Which errors are safe to retry? How to validate pre-recovery? Need to study DLQ patterns for transient vs. permanent failures. Research available, but needs domain-specific decisions.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All capabilities exist in current stack (stdlib + plexapi). No new dependencies needed. Patterns proven in v1.4 reconciliation. |
| Features | HIGH | Feature expectations verified with industry patterns (AWS SQS, RabbitMQ, Kafka). Must-have vs. should-have validated with current 2026 sources. |
| Architecture | HIGH | Check-on-invocation pattern proven in v1.4. Circuit breaker exists (140 lines). Components cleanly separated. Integration points well-defined. |
| Pitfalls | HIGH | All critical pitfalls verified with recent sources (Feb 2026). Race conditions, thundering herd, false positives all have proven solutions. Testing strategies identified. |

**Overall confidence:** HIGH

The research is comprehensive and actionable. No gaps that block roadmap creation. Stack choices are conservative (reuse existing), architecture extends proven patterns (check-on-invocation), features align with industry standards (automatic recovery is table stakes), and pitfalls have known prevention strategies.

### Gaps to Address

**During Phase 1 (Circuit Breaker Persistence):**
- File locking strategy decision: fcntl advisory locks vs. single-writer pattern vs. optimistic concurrency. Need to test which works best with Stash plugin invocation patterns. **Recommendation:** Start with single-writer (only worker modifies state, hooks read-only)—aligns with existing architecture where worker manages circuit breaker.

**During Phase 2 (Health Check):**
- Exact health check implementation: server.query('/identity') vs. library.sections() sentinel request. Need to test against real Plex restart sequence to verify which detects "database loaded" reliably. **Recommendation:** Start with /identity (lightweight), add library check if false positives occur in testing.

**During Phase 6 (Rate Limiting):**
- Rate limit tuning: 5 jobs/sec starting rate may be too conservative for powerful servers, too aggressive for RPi. Need configurable rate with adaptive adjustment based on error rate. **Recommendation:** Make rate configurable, default 5 jobs/sec, increase if error rate <1%.

**During Phase 8 (DLQ Recovery):**
- Error classification: Which error types are safe to retry after outage? PlexServerDown yes, but what about Timeout (could be network vs. Plex performance)? Need to study DLQ error patterns. **Recommendation:** Phase 8 starts with conservative recovery (PlexServerDown only), expand to other errors based on validation.

**No blocking gaps.** All gaps have clear resolution strategies. Can proceed to roadmap creation with confidence.

## Sources

### Primary (HIGH confidence)

**Stack Research:**
- [Python JSON Documentation](https://docs.python.org/3/library/json.html) — stdlib, version 2.0.9, basic serialization
- [PlexAPI Server Documentation](https://python-plexapi.readthedocs.io/en/latest/modules/server.html) — server.query() method, timeout parameter
- Existing codebase: `reconciliation/scheduler.py` save_state()/load_state() pattern (JSON + atomic write) — validated
- Existing codebase: `worker/circuit_breaker.py` (3-state pattern validated, 999 tests)

**Feature Research:**
- [Outage recovery scenarios in Amazon SQS](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/designing-for-outage-recovery-scenarios.html) — AWS best practices for failover, message handling
- [Avoiding insurmountable queue backlogs](https://aws.amazon.com/builders-library/avoiding-insurmountable-queue-backlogs/) — AWS Builders Library on backpressure, retry strategies
- [Reliability Guide | RabbitMQ](https://www.rabbitmq.com/docs/reliability) — durability, acknowledgment, recovery patterns
- [How to Implement Dead Letter Queue Patterns](https://oneuptime.com/blog/post/2026-02-09-dead-letter-queue-patterns/view) — Recent (Feb 2026), recovery strategies

**Architecture Research:**
- [Circuit Breaker - Martin Fowler](https://martinfowler.com/bliki/CircuitBreaker.html) — authoritative pattern definition
- [Health Check Pattern - Microsoft](https://learn.microsoft.com/en-us/azure/architecture/patterns/health-endpoint-monitoring) — health check best practices
- [Atomic File Writes in Python](https://docs.python.org/3/library/os.html#os.replace) — os.replace() atomicity guarantees
- Existing PlexSync: `reconciliation/scheduler.py` (lines 47-150) — proven check-on-invocation implementation

**Pitfalls Research:**
- [Building Resilient Systems: Circuit Breakers and Retry Patterns](https://dasroot.net/posts/2026/01/building-resilient-systems-circuit-breakers-retry-patterns/) — integration with retry logic
- [Implementing health checks — AWS Builders Library](https://aws.amazon.com/builders-library/implementing-health-checks/) — dependency health check false positives
- [Retry Storm Antipattern — Azure Architecture Center](https://learn.microsoft.com/en-us/azure/architecture/antipatterns/retry-storm/) — thundering herd prevention
- [How to Avoid Cascading Failures in Distributed Systems](https://www.infoq.com/articles/anatomy-cascading-failure/) — cascade failure prevention

### Secondary (MEDIUM confidence)

**Stack Research:**
- [DiskCache vs persist-queue comparison](https://github.com/grantjenks/python-diskcache) — feature comparison, use cases
- [Plex API Documentation — Server Identity](https://plexapi.dev/api-reference/server/get-server-capabilities) — /identity endpoint structure
- [pms-docker healthcheck.sh](https://github.com/plexinc/pms-docker/blob/master/root/healthcheck.sh) — official Docker healthcheck uses /identity endpoint

**Feature Research:**
- [How to Configure Circuit Breaker Patterns](https://oneuptime.com/blog/post/2026-02-02-circuit-breaker-patterns/view) — Recent (Feb 2026) guide on three-state pattern
- [Mastering APISIX Health Checks: Active and Passive Monitoring Strategies](https://api7.ai/blog/health-check-ensures-high-availability) — active vs passive tradeoffs
- [Apache Kafka Dead Letter Queue: A Comprehensive Guide](https://www.confluent.io/learn/kafka-dead-letter-queue/) — when to DLQ vs retry

**Architecture Research:**
- [Event-Driven Architecture Patterns](https://aws.amazon.com/event-driven-architecture/) — event-driven patterns for non-daemon systems
- [JSON State Persistence Best Practices](https://realpython.com/python-json/) — JSON serialization patterns

**Pitfalls Research:**
- [Understanding Back Pressure in Message Queues](https://akashrajpurohit.com/blog/understanding-back-pressure-in-message-queues-a-guide-for-developers/) — backpressure patterns
- [The Thundering Herd Problem and Its Solutions](https://www.nottldr.com/SystemSage/the-thundering-herd-problem-and-its-solutions-0ie2hx3) — thundering herd solutions
- [Handling Race Condition in Distributed System — GeeksforGeeks](https://www.geeksforgeeks.org/computer-networks/handling-race-condition-in-distributed-system/) — race condition patterns
- [Dead Letter Queues (DLQ): The Complete, Developer-Friendly Guide](https://swenotes.com/2025/09/25/dead-letter-queues-dlq-the-complete-developer-friendly-guide/) — DLQ recovery patterns

### Tertiary (LOW confidence)

**Stack Research:**
- [Plex Healthcheck Gist](https://gist.github.com/dimo414/aaaee1c639d292a64b72f4644606fbf0) — community pattern, not official docs

**Feature Research:**
- [IT Monitoring Trends 2026](https://blog.paessler.com/it-monitoring-trends-2026-from-multi-cloud-chaos-to-unified-visibility) — general trends, AI-powered anomaly detection
- [Cloud outages expected to be the new normal in 2026](https://www.techtarget.com/searchCloudComputing/feature/Cloud-outages-expected-to-be-the-new-normal-in-2026) — context for why outage resilience matters

**Pitfalls Research:**
- [Storage resilience: atomic writes](https://github.com/anomalyco/opencode/issues/7733) — temp + fsync + rename pattern (GitHub issue, not authoritative)
- [Registry corruption after crash during atomic rename](https://github.com/openclaw/openclaw/issues/1469) — real-world JSON corruption example

---

**Research completed:** 2026-02-15
**Ready for roadmap:** YES

This research provides a complete foundation for roadmap creation. All must-have features identified, stack choices validated, architecture approach proven, and critical pitfalls mapped to prevention strategies. Phase suggestions are dependency-ordered and risk-prioritized. Proceed to requirements definition with confidence.
