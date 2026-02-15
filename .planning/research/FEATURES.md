# Feature Research: Outage Resilience for Queue Systems

**Domain:** Outage resilience in sync/queue systems (metadata sync plugin context)
**Researched:** 2026-02-15
**Confidence:** HIGH

## Context

PlexSync already has:
- Persistent SQLite queue with crash recovery
- Exponential backoff with jitter (PlexServerDown = 999 retries, never DLQ'd)
- Circuit breaker (5 failures → OPEN → 60s → HALF_OPEN)
- Check-on-invocation scheduling (not a daemon)
- Manual "Process Queue" button
- Queue status display

**Gap:** When Plex recovers from outage, nothing triggers automatic queue drain. User must manually hit "Process Queue" or wait for coincidental hook event.

**Research focus:** What features do users expect for automatic recovery, health monitoring, and outage reporting?

---

## Table Stakes

Features users expect. Missing these = product feels incomplete.

| Feature | Why Expected | Complexity | Dependencies |
|---------|--------------|------------|--------------|
| **Automatic queue drain on recovery** | Industry standard: queues resume automatically when downstream recovers | MEDIUM | Requires recovery detection mechanism |
| **Health monitoring with retry** | All production queue systems probe downstream to detect recovery | LOW | Active health check with configurable interval |
| **Outage visibility in status UI** | Users need to know *why* queue stopped and *when* it will resume | LOW | Extend existing queue status task |
| **Circuit breaker state logging** | State transitions (CLOSED → OPEN → HALF_OPEN) must be observable | LOW | Already exists, just needs better logging |
| **Recovery notification** | Users need confirmation when system returns to normal | LOW | Log when circuit closes after outage |

---

## Differentiators

Features that set product apart. Not expected, but valuable.

| Feature | Value Proposition | Complexity | Dependencies |
|---------|-------------------|------------|--------------|
| **Passive + active health checks** | Passive (monitor actual jobs) detects failure faster; active (periodic probe) detects recovery faster | MEDIUM | Circuit breaker already does passive; add active probe |
| **Circuit breaker state persistence** | Survives plugin restarts during outages (doesn't reset to CLOSED and hammer Plex) | LOW | JSON state file like reconciliation scheduler |
| **Outage-triggered reconciliation** | When Plex recovers after hours down, auto-reconcile to find gaps from events during outage | MEDIUM | Requires reconciliation engine (Phase 1) + outage detection |
| **DLQ recovery for outage jobs** | Jobs DLQ'd during outage (timeout, rate limit) can be re-queued when service recovers | MEDIUM | DLQ already tracks error types; add "recover by type" command |
| **Health check backoff** | Space out recovery probes to avoid hammering recovering service (1s → 2s → 4s → cap at 60s) | LOW | Apply existing backoff logic to health checks |
| **Outage history tracking** | Log outage start/end times, duration, jobs affected for post-mortem analysis | LOW | Extend reconciliation state file pattern |

---

## Anti-Features

Features to explicitly NOT build.

| Anti-Feature | Why Requested | Why Avoid | What to Do Instead |
|--------------|---------------|-----------|-------------------|
| **Real-time push notifications** | "Alert me immediately when Plex is down" | Stash plugins run per-event, no daemon for push notifications; external monitoring (Uptime Kuma, Healthchecks.io) solves this better | Log outage clearly, extend queue status to show "Circuit OPEN since [time]" |
| **Automatic full reconciliation on recovery** | "Sync everything that changed during outage" | Expensive: 10K+ items after 8hr backup outage; may re-queue already-queued jobs | User-triggered reconciliation with "since last outage" scope filter |
| **Multi-tiered circuit breakers** | "Different thresholds for temporary vs permanent failures" | Over-engineering: PlexServerDown already gets special handling (999 retries); circuit breaker handles burst failures | Single circuit breaker with error-specific retry limits (existing) |
| **External health check endpoint** | "I want to monitor Plex through this plugin" | Plugin can't serve HTTP; Plex has native health endpoints (`/identity`, `/servers`); dedicated monitoring tools exist | Document how to monitor Plex directly + queue status task shows derived health |
| **Automatic failover to backup Plex server** | "Switch to secondary server during outage" | Complex: config management, metadata sync conflicts, race conditions on recovery | Manual failover via config change is safer; most users have single Plex |

---

## Feature Dependencies

```
[Automatic Queue Drain]
    └──requires──> [Recovery Detection] (health monitoring)
    └──requires──> [Event-Driven Trigger] (mechanism to resume processing)

[Recovery Detection]
    ├──uses──> [Active Health Check] (periodic probe during OPEN state)
    ├──uses──> [Circuit Breaker HALF_OPEN] (existing test-on-timeout)
    └──enhances──> [Passive Health Check] (existing: job success/failure)

[Event-Driven Trigger]
    ├──option1──> [Hook-Based Resume] (emit fake hook event to trigger processing)
    ├──option2──> [Scheduler Integration] (check-on-invocation: "is circuit closed + queue not empty?")
    └──option3──> [Direct Worker Call] (worker.process_next() after health check succeeds)

[Circuit Breaker State Persistence]
    └──pattern──> [ReconciliationScheduler] (existing JSON state file pattern)
    └──data──> {state: "open"|"closed"|"half_open", opened_at: timestamp, ...}

[Outage-Triggered Reconciliation]
    └──requires──> [Reconciliation Engine] (Phase 1)
    └──requires──> [Outage History] (track outage windows)
    └──enhances──> [Automatic Recovery] (reconcile after drain completes)

[DLQ Recovery]
    └──requires──> [Error Type Classification] (existing: PlexServerDown, Timeout, etc.)
    └──enhances──> [DLQ Management] (existing: clear, purge tasks)
    └──new task──> "Recover Outage Jobs" (re-queue DLQ entries with transient errors)

[Health Check Backoff]
    └──uses──> [Exponential Backoff Logic] (existing: worker/backoff.py)
    └──applies to──> [Active Health Check Interval]

[Outage History]
    └──pattern──> [ReconciliationScheduler State] (existing JSON persistence)
    └──data──> [{start: timestamp, end: timestamp, duration_secs: N, jobs_affected: N}, ...]
```

---

## MVP Definition (Outage Resilience Phase)

### Phase 1: Automatic Recovery Core

**Goal:** Queue drains automatically when Plex recovers.

**Launch With:**

- [ ] **Active Health Check During OPEN State**
  - When circuit opens, start periodic health probe (every 60s)
  - Probe: lightweight Plex API call (`/identity` endpoint check)
  - Success → transition to HALF_OPEN (existing logic) → test job → CLOSED
  - Failure → stay OPEN, retry after backoff interval
  - Complexity: LOW (reuse existing circuit breaker state machine)

- [ ] **Automatic Queue Processing on Recovery**
  - When circuit transitions CLOSED (after HALF_OPEN success), trigger queue drain
  - Mechanism: Call `worker.process_next()` in loop until queue empty or circuit reopens
  - Rate limiting: Respect existing worker throttling (avoid hammering just-recovered Plex)
  - Complexity: LOW (worker already has process loop)

- [ ] **Enhanced Logging for State Transitions**
  - CLOSED → OPEN: "Circuit breaker opened after 5 consecutive failures. Queue processing paused."
  - OPEN → HALF_OPEN: "Testing recovery after 60s timeout..."
  - HALF_OPEN → CLOSED: "Plex recovered! Resuming queue processing. [N] jobs pending."
  - HALF_OPEN → OPEN: "Recovery test failed. Circuit re-opened."
  - Complexity: LOW (add log statements to existing circuit breaker)

- [ ] **Outage Status in Queue UI**
  - Extend `handle_queue_status()` task to show circuit state
  - Display: "Circuit: OPEN (since [time], recovery test in [seconds])" when not CLOSED
  - Display: "Circuit: CLOSED" when healthy (normal operation)
  - Complexity: LOW (read circuit breaker state property)

**Defer to Phase 2:**

- Circuit breaker state persistence (survives restarts)
- Health check interval backoff
- Outage history tracking
- DLQ recovery for outage-related failures

### Phase 2: State Persistence & Advanced Health

**Goal:** Outage resilience survives plugin restarts. Smarter recovery probing.

**Add After Phase 1 Proven:**

- [ ] **Circuit Breaker State Persistence**
  - Save state to `circuit_breaker_state.json` on every transition
  - Load on plugin init: restore OPEN state if plugin restarted during outage
  - Prevents: Reset to CLOSED after Stash restart → hammering still-down Plex
  - Complexity: LOW (pattern already exists in ReconciliationScheduler)

- [ ] **Health Check Backoff**
  - Initial probe: 5s after opening
  - Exponential backoff: 5s → 10s → 20s → 40s → cap at 60s
  - Prevents: Constant 60s probes during long outages (e.g., 8hr Plex backup)
  - Complexity: LOW (reuse worker/backoff.py logic)

- [ ] **Passive + Active Health Check Hybrid**
  - Passive (existing): Job failures update circuit breaker immediately
  - Active (new): Periodic probes detect recovery when queue is idle
  - Benefit: Fast failure detection + fast recovery detection
  - Complexity: MEDIUM (coordinate active probe timer with worker loop)

- [ ] **Outage History Tracking**
  - Log each outage: start time, end time, duration, jobs affected
  - Store in `outage_history.json` (last 30 outages, ring buffer)
  - Display in queue status: "Last outage: [date], [duration], [jobs affected]"
  - Complexity: LOW (extend state persistence pattern)

**Defer to Phase 3:**

- Outage-triggered reconciliation
- DLQ recovery for outage jobs
- Outage summary reports

### Phase 3: Advanced Outage Management

**Goal:** Auto-heal metadata gaps from outage windows. Recover DLQ'd jobs.

**Future Considerations:**

- [ ] **Outage-Triggered Reconciliation** (Depends on Phase 1 reconciliation engine)
  - When circuit closes after extended outage (>1hr), trigger reconciliation
  - Scope: "scenes updated during outage window [outage_start to outage_end]"
  - Rationale: Hook events missed during outage → queue never populated
  - Complexity: MEDIUM (requires outage history + reconciliation engine)

- [ ] **DLQ Recovery for Outage Jobs**
  - Task: "Recover Outage Jobs" re-queues DLQ entries with transient errors
  - Filter: Jobs failed with PlexServerDown, Timeout, 503 during last outage window
  - Safety: Dry-run mode shows what would be recovered before re-queuing
  - Complexity: MEDIUM (DLQ query + error type classification)

- [ ] **Per-Error-Type DLQ Recovery**
  - Granular recovery: "Re-queue all PlexServerDown jobs" vs "Re-queue all Timeout jobs"
  - Use case: Network blip caused timeouts; safe to retry after stability confirmed
  - Complexity: LOW (extend DLQ query filtering)

- [ ] **Outage Summary Report**
  - Task: "View Outage History" shows last 30 outages with stats
  - Metrics: duration, jobs affected, recovery time, jobs succeeded after recovery
  - Helps: Post-mortem analysis, identify recurring issues
  - Complexity: LOW (format existing outage history data)

---

## Feature Prioritization Matrix

| Feature | User Value | Complexity | Phase | Notes |
|---------|------------|------------|-------|-------|
| Active health check (OPEN state) | HIGH | LOW | P1 | Core automatic recovery |
| Auto queue drain on recovery | HIGH | LOW | P1 | Core automatic recovery |
| Enhanced state transition logging | HIGH | LOW | P1 | Observability is table stakes |
| Outage status in queue UI | HIGH | LOW | P1 | Users need to see *why* queue paused |
| Circuit breaker state persistence | MEDIUM | LOW | P2 | Prevents restart issues during outages |
| Health check backoff | MEDIUM | LOW | P2 | Reduces load on recovering service |
| Passive + active health hybrid | MEDIUM | MEDIUM | P2 | Optimization, not critical path |
| Outage history tracking | MEDIUM | LOW | P2 | Nice for post-mortem, not urgent |
| Outage-triggered reconciliation | MEDIUM | MEDIUM | P3 | Depends on reconciliation engine first |
| DLQ recovery for outage jobs | LOW | MEDIUM | P3 | Niche use case (most jobs retry anyway) |
| Per-error-type DLQ recovery | LOW | LOW | P3 | Enhancement, not core need |
| Outage summary report | LOW | LOW | P3 | Analytics, not operational |

**Priority Key:**
- **P1 (Phase 1):** Must have for automatic recovery MVP
- **P2 (Phase 2):** Should have for production resilience
- **P3 (Phase 3):** Nice to have, advanced management

---

## Implementation Patterns (Non-Daemon Context)

### Challenge: Stash Plugins Are Not Daemons

Stash plugins are invoked per-event (hook, task, startup), then exit. No long-running process for timers/polling.

**Implications for health checks:**

| Pattern | Feasibility | Notes |
|---------|-------------|-------|
| **Continuous polling loop** | NO | Plugin exits after hook/task completes. Can't run background poller. |
| **Threading.Timer (daemon thread)** | YES | Worker already uses daemon thread. Can add health check timer to worker thread. |
| **Check-on-invocation** | YES | On each hook/task, check "is circuit OPEN + time for health check?" |
| **Task-triggered health check** | YES | User clicks "Test Plex Connection" task, runs health check immediately. |

**Recommended Approach (Phase 1):**

1. **Health check in worker thread loop** (when circuit is OPEN)
   - Worker already runs in daemon thread
   - When circuit opens, worker pauses job processing
   - Add: Every 60s while OPEN, run health probe
   - If probe succeeds → transition to HALF_OPEN → test real job → CLOSED

2. **Manual health check task** (for user verification)
   - Task: "Test Plex Connection"
   - Runs health probe, logs result
   - Does NOT change circuit state (read-only test)
   - Useful: "Is Plex up? Should I Process Queue?"

**Alternative Approach (Phase 2):**

- **Check-on-invocation health check**
  - On every hook/task invocation, check: "circuit OPEN + >60s since last probe?"
  - If yes, run health check
  - Pro: No timer needed
  - Con: If no events occur during outage, no recovery detection until user action
  - Verdict: Supplement worker-based checks, don't replace

### Event-Driven Queue Drain Pattern

**Goal:** When Plex recovers, trigger queue processing without user intervention.

**Options:**

| Option | How It Works | Pros | Cons | Verdict |
|--------|-------------|------|------|---------|
| **Direct worker call** | Health check → circuit closes → `worker.process_next()` loop | Simple, direct | Tightly couples health check to worker | **RECOMMENDED** |
| **Emit fake hook event** | Health check → circuit closes → synthesize Scene.Update.Post hook | Reuses existing hook handler | Hacky, needs valid scene ID | Not recommended |
| **Scheduler trigger** | Check-on-invocation: "circuit closed + queue not empty? → process" | Leverages existing pattern | Requires every hook to check queue state | Overcomplicated |
| **Worker auto-resume** | Worker loop: "if circuit closed and queue not empty, keep processing" | Self-healing | Worker already does this when running | **ALREADY EXISTS** |

**Implementation (Phase 1):**

Worker already has processing loop. When circuit closes:

```python
# In worker._worker_loop() or health check callback
if self.circuit_breaker.state == CircuitState.CLOSED:
    # Circuit just closed, resume processing
    while self.queue.qsize() > 0 and self.circuit_breaker.can_execute():
        self._process_next()
```

No special triggering needed. Worker naturally resumes when circuit closes.

### Health Check Implementation

**Lightweight Plex probe:**

```python
def _health_check(self) -> bool:
    """Check if Plex server is reachable. Returns True if healthy."""
    try:
        # Lightweight endpoint: /identity (no auth required, fast)
        response = requests.get(
            f"{self.config.plex_url}/identity",
            timeout=5.0
        )
        return response.status_code == 200
    except (requests.RequestException, ConnectionError, TimeoutError):
        return False
```

**Active check interval (Phase 1: fixed, Phase 2: backoff):**

```python
# Phase 1: Fixed 60s interval when OPEN
if self.circuit_breaker.state == CircuitState.OPEN:
    if time.time() - self._last_health_check > 60.0:
        if self._health_check():
            # Trigger HALF_OPEN transition
            self.circuit_breaker.record_success()  # Test with real job next
```

**Passive check (already exists via circuit breaker):**

- Job success → `circuit_breaker.record_success()`
- Job failure → `circuit_breaker.record_failure()`
- 5 consecutive failures → OPEN
- Already implemented, no changes needed

---

## Comparison: PlexSync vs Industry Patterns

| Feature | AWS SQS + Lambda | RabbitMQ | Kafka | PlexSync Approach |
|---------|------------------|----------|-------|-------------------|
| **Automatic recovery** | Built-in: messages retry automatically | DLQ + shovel plugin for replay | Consumer offset management | Worker loop + circuit breaker auto-resume |
| **Health monitoring** | CloudWatch alarms on DLQ depth | Management UI health checks | JMX metrics + consumer lag | Active probe during OPEN + passive job monitoring |
| **Circuit breaker** | Not built-in (app-level) | Not built-in | Not applicable (pull model) | **YES** - core resilience feature |
| **State persistence** | DLQ is persistent | Messages persist to disk | Log-based persistence | Queue + DLQ persistent, circuit state ephemeral (Phase 2: persist) |
| **Outage visibility** | CloudWatch dashboards | Management UI | Kafka UI, Burrow | Queue status task + log messages |
| **Recovery automation** | Auto-retry with backoff | Dead-letter queue + shovel | Consumer resume on rebalance | **Phase 1 focus** - health check + auto-drain |

**Key Differentiator:** PlexSync's circuit breaker is more sophisticated than typical queue systems. Most rely on consumer-side retry logic. PlexSync has producer-side pause (circuit OPEN = stop processing queue) + automatic recovery detection.

**Industry Standard We Match:**

- Persistent queue with DLQ (AWS SQS, RabbitMQ, Kafka all have this)
- Exponential backoff with jitter (AWS SDK default, RabbitMQ plugin)
- Health monitoring (all production systems)

**Industry Standard We Lack (Phase 1 adds):**

- Automatic resume after outage (AWS Lambda auto-retries, Kafka consumers resume)
- Active health checks during outage (most monitoring systems probe periodically)

---

## Sources

### Queue System Recovery Patterns

- [Outage recovery scenarios in Amazon SQS](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/designing-for-outage-recovery-scenarios.html) — HIGH confidence: AWS best practices for failover, message handling during outages
- [Avoiding insurmountable queue backlogs](https://aws.amazon.com/builders-library/avoiding-insurmountable-queue-backlogs/) — HIGH confidence: AWS Builders Library on backpressure, retry strategies
- [Reliability Guide | RabbitMQ](https://www.rabbitmq.com/docs/reliability) — HIGH confidence: Durability, acknowledgment, recovery patterns

### Circuit Breaker Patterns

- [How to Configure Circuit Breaker Patterns](https://oneuptime.com/blog/post/2026-02-02-circuit-breaker-patterns/view) — MEDIUM confidence: Recent (Feb 2026) guide on three-state pattern
- [Circuit Breaker Pattern in Microservices](https://www.geeksforgeeks.org/system-design/what-is-circuit-breaker-pattern-in-microservices/) — MEDIUM confidence: CLOSED/OPEN/HALF_OPEN state behavior
- [Building Resilient Systems: Circuit Breakers and Retry Patterns](https://dasroot.net/posts/2026/01/building-resilient-systems-circuit-breakers-retry-patterns/) — MEDIUM confidence: Integration with retry logic
- [Why Circuit Breaker Recovery Needs Coordination](https://blog.bolshakov.dev/2025/12/06/why-circuit-breaker-recovery-needs-coordination.html) — HIGH confidence: Concurrent recovery challenges, state race conditions

### Health Check Patterns

- [Mastering APISIX Health Checks: Active and Passive Monitoring Strategies](https://api7.ai/blog/health-check-ensures-high-availability) — HIGH confidence: Active vs passive tradeoffs, hybrid approach
- [Active or Passive Health Checks: Which Is Right for You?](https://www.f5.com/company/blog/nginx/active-or-passive-health-checks-which-is-right-for-you) — HIGH confidence: When to use each, resource implications
- [10 Essential Best Practices for API Gateway Health Checks](https://api7.ai/blog/10-best-practices-of-api-gateway-health-checks) — MEDIUM confidence: Probe frequency, timeout configuration
- [Health Monitoring | Distributed Application Architecture Patterns](https://jurf.github.io/daap/resilience-and-reliability-patterns/health-monitoring/) — MEDIUM confidence: Patterns for dependency health tracking

### Dead Letter Queue Recovery

- [How to Implement Dead Letter Queue Patterns for Failed Message Handling](https://oneuptime.com/blog/post/2026-02-09-dead-letter-queue-patterns/view) — HIGH confidence: Recent (Feb 2026), recovery strategies, retry workflows
- [Strategies for Successful Dead Letter Queue Event Handling](https://rashadansari.medium.com/strategies-for-successful-dead-letter-queue-event-handling-e354f7dfbb3e) — MEDIUM confidence: Manual review, automated reprocessing
- [Apache Kafka Dead Letter Queue: A Comprehensive Guide](https://www.confluent.io/learn/kafka-dead-letter-queue/) — HIGH confidence: Official Confluent resource, when to DLQ vs retry
- [Dead Letter Queue - Karafka framework documentation](https://karafka.io/docs/Dead-Letter-Queue/) — MEDIUM confidence: Multiple DLQ tiers, error classification

### Event-Driven Processing (Non-Daemon)

- [8 Event-Driven Architectures With Webhooks, Queues, and n8n](https://medium.com/@Nexumo_/8-event-driven-architectures-with-webhooks-queues-and-n8n-34f08e3a8a43) — MEDIUM confidence: Webhook + queue patterns, async processing
- [How to Choose a Solution for Queuing Your Webhooks](https://hookdeck.com/webhooks/guides/how-to-choose-a-solution-for-queuing-your-webhooks) — MEDIUM confidence: Event-driven queue processing without daemon
- [Building a Webhooks System with Event Driven Architecture](https://codeopinion.com/building-a-webhooks-system-with-event-driven-architecture/) — MEDIUM confidence: Decouple producers/consumers, idempotent processing

### Outage Monitoring & Alerting

- [How to Monitor SQS Queue Depth](https://oneuptime.com/blog/post/2026-01-27-sqs-queue-depth-monitoring/view) — MEDIUM confidence: Key metrics (queue depth = most important), alerting strategies
- [IT Monitoring Trends 2026: From Multi-Cloud Chaos to Unified Visibility](https://blog.paessler.com/it-monitoring-trends-2026-from-multi-cloud-chaos-to-unified-visibility) — LOW confidence: General trends, AI-powered anomaly detection
- [Cloud outages expected to be the new normal in 2026](https://www.techtarget.com/searchCloudComputing/feature/Cloud-outages-expected-to-be-the-new-normal-in-2026) — MEDIUM confidence: Context for why outage resilience matters (264 global outages in one week Feb 2026)

---

**Research Summary:**

Automatic recovery is **table stakes** — every production queue system (AWS SQS, RabbitMQ, Kafka) has mechanisms to resume after downstream recovers. PlexSync's gap is the event-driven trigger: worker runs in daemon thread but doesn't actively probe during outages.

**Phase 1 (MVP) is straightforward:**
1. Add active health check to worker loop (when circuit OPEN, probe every 60s)
2. When probe succeeds → circuit transitions to HALF_OPEN (existing logic) → test real job → CLOSED
3. When circuit closes → worker automatically resumes queue processing (loop already exists)
4. Log all state transitions clearly
5. Show circuit state in queue status UI

**Phase 2 (production hardening) adds persistence:**
- Circuit state survives Stash restarts (prevents reset-to-CLOSED during outage)
- Health check backoff (5s → 60s cap) reduces load on recovering Plex
- Outage history for post-mortem analysis

**Phase 3 (advanced) integrates with reconciliation:**
- After extended outage, auto-trigger reconciliation for missed events
- Re-queue DLQ jobs that failed due to outage (not permanent errors)

All patterns align with industry best practices for resilient queue systems. No novel approaches needed — apply proven patterns to PlexSync's non-daemon constraint.

---

*Feature research for: PlexSync outage resilience milestone*
*Researched: 2026-02-15*
*Confidence: HIGH (circuit breaker patterns, health checks, DLQ recovery all verified with current 2026 sources)*
