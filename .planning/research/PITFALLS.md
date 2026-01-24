# Domain Pitfalls: Sync/Integration Plugins

**Domain:** Metadata Sync Plugins (Stash to Plex)
**Researched:** 2026-01-24
**Focus:** Retry logic, queue mechanisms, and reliability improvements

## Critical Pitfalls

Mistakes that cause rewrites or major issues.

### Pitfall 1: Non-Idempotent Operations Leading to Duplicates
**What goes wrong:** Retry logic causes duplicate metadata updates - for example, applying the same tag multiple times, creating duplicate collections, or incrementing view counts repeatedly when the same request is retried after network timeouts.

**Why it happens:** Developers design retry logic without constraints, assuming failure is binary (succeeded/failed). The system retries requests without tracking which operations actually completed, leading to duplicate side effects on the target system (Plex).

**Consequences:**
- Plex metadata becomes corrupted with duplicate entries
- Collections contain the same item multiple times
- View counts and watch history become inaccurate
- Manual cleanup required in Plex
- User trust in sync reliability erodes

**Prevention:**
- Implement idempotency keys for all sync operations - include a unique identifier (e.g., `stash_scene_id + operation_type + timestamp`) in requests
- Before applying metadata changes, check current Plex state to detect if operation already completed
- Use Plex's update operations (PUT) rather than additive operations (POST) where possible
- Store completed operation hashes to prevent re-application of identical changes
- Design operations to be naturally idempotent: "set rating to 4" not "increment rating"

**Detection:**
- Monitor for duplicate tags/collections appearing in Plex
- Log requests with correlation IDs to trace retry chains
- Alert when same scene_id appears in sync queue multiple times within short timeframe
- Track operation counts per scene and flag anomalies (e.g., 5+ sync attempts)

**Sources:**
- [Designing retry logic that doesn't create data duplicates (Medium, 2026)](https://medium.com/@backend.bao/designing-retry-logic-that-doesnt-create-data-duplicates-99a784500931)
- [Preventing Duplicate Operations in APIs with Idempotent Keys (Medium)](https://medium.com/@anas.mdhat/preventing-duplicate-operations-in-apis-with-idempotent-keys-f67c3bf6117a)
- [Mastering Idempotency: Building Reliable APIs (ByteByteGo)](https://blog.bytebytego.com/p/mastering-idempotency-building-reliable)

---

### Pitfall 2: Retry Without Exponential Backoff + Jitter
**What goes wrong:** When Plex becomes unavailable (during backup, restart, or under load), the plugin retries immediately and repeatedly, overwhelming Plex when it comes back online and potentially triggering cascading failures.

**Why it happens:** Developers implement simple retry logic with fixed delays or immediate retries. When multiple sync operations fail simultaneously (e.g., Plex goes down), they all retry at the same time, creating a "thundering herd" that prevents Plex from recovering.

**Consequences:**
- Plex server remains overloaded even after recovery
- Retry storms prevent successful operations from completing
- Other Plex clients experience degraded performance
- Sync operations continue failing despite Plex being "up"
- Plugin banned/rate-limited by Plex

**Prevention:**
- Implement exponential backoff: 1s, 2s, 4s, 8s, 16s (capped at reasonable maximum like 5 minutes)
- Add jitter (randomness) to backoff intervals: `backoff_time = base_delay * (2^attempt) + random(0, 1000ms)`
- Set maximum retry attempts (e.g., 5-7 attempts) before marking operation as permanently failed
- Different error types require different strategies:
  - 429 (rate limit): Use `Retry-After` header value if provided, otherwise exponential backoff
  - 503 (service unavailable): Exponential backoff with jitter
  - 4xx errors (except 429): Don't retry - these are client errors
  - 5xx errors: Retry with backoff
- Implement circuit breaker pattern: after N consecutive failures, stop attempting for a cooldown period

**Detection:**
- Log retry attempt counts and intervals
- Monitor request timestamps to detect synchronized retry patterns
- Alert when retry intervals are suspiciously uniform (indicates missing jitter)
- Track 429 responses from Plex API

**Sources:**
- [Retrying and Exponential Backoff: Smart Strategies for Robust Software (HackerOne)](https://www.hackerone.com/blog/retrying-and-exponential-backoff-smart-strategies-robust-software)
- [Timeouts, retries and backoff with jitter (AWS Builders Library)](https://aws.amazon.com/builders-library/timeouts-retries-and-backoff-with-jitter/)
- [A Guide to Retry Pattern in Distributed Systems (ByteByteGo)](https://blog.bytebytego.com/p/a-guide-to-retry-pattern-in-distributed)

---

### Pitfall 3: Silent Failures (No Observability)
**What goes wrong:** Sync operations fail without any indication to the user or administrator. Metadata changes in Stash never reach Plex, but there's no error message, no log entry, no alert - just absence of expected updates.

**Why it happens:** The system tracks what happened (successful operations) but not what should have happened (expected operations). A missed sync isn't logged as an event because it's the absence of an event. Additionally, alerts may be configured but fail silently due to delivery chain issues.

**Consequences:**
- Users discover sync failures weeks later when metadata is missing
- No data to debug why syncs failed
- Cannot distinguish between "never attempted" and "attempted but failed"
- Cannot measure sync reliability metrics
- Trust in sync system completely eroded

**Prevention:**
- **Heartbeat monitoring:** Emit "still alive" signals at regular intervals; alert if heartbeat stops
- **Expected event tracking:** Log when sync should have been triggered (e.g., on Stash scene.update event), then track completion
- **Structured logging with correlation IDs:** Every sync operation gets a unique ID that flows through the entire pipeline:
  ```python
  correlation_id = f"{scene_id}_{operation}_{timestamp}"
  log.info(f"[{correlation_id}] Sync initiated", extra={"scene_id": scene_id})
  log.info(f"[{correlation_id}] Plex API called", extra={"api_endpoint": "/library/sections"})
  log.error(f"[{correlation_id}] Sync failed", extra={"error": str(e)})
  ```
- **Operation state tracking:** Maintain states: QUEUED → IN_PROGRESS → COMPLETED/FAILED/PERMANENTLY_FAILED
- **Sync health dashboard:** Track metrics like:
  - Success rate (last hour, last day)
  - Average time to completion
  - Queue depth
  - Permanently failed items count
- **Dead letter queue (DLQ):** Items that exceed max retries go to DLQ for manual inspection
- **Alert on absence:** If no successful syncs in last N hours, send alert (assumes at least some Stash activity)

**Detection:**
- User reports missing metadata
- Sync queue grows without shrinking
- No log entries for sync operations
- Success rate drops to 0%
- Correlation IDs stop appearing in logs

**Sources:**
- [Building A Monitoring System That Catches Silent Failures (Vincent Lakatos)](https://www.vincentlakatos.com/blog/building-a-monitoring-system-that-catches-silent-failures/)
- [Agentforce Studio's New Health Monitoring Tool Aims to Catch 'Silent Failures' (Salesforce Blog, 2026)](https://www.salesforce.com/blog/agent-monitoring/?bc=OTH)
- [The Silent Failure: When Monitoring Doesn't Wake the Right People (OnPage)](https://www.onpage.com/the-silent-failure-when-monitoring-doesnt-wake-the-right-people/)

---

### Pitfall 4: Database-as-Queue Anti-Pattern
**What goes wrong:** Using Stash's database (or a separate SQLite/Postgres table) as a queue for retry operations leads to performance degradation, lock contention, and difficulty implementing proper queue semantics (FIFO, priority, etc.).

**Why it happens:** Databases are familiar and already available, so it seems convenient to add a `sync_queue` table with columns like `status`, `retry_count`, `next_retry_at`. But databases aren't designed for high-frequency queue operations - they're designed for ACID transactions on structured data.

**Consequences:**
- Polling the database for "ready to retry" items causes constant load
- Row-level locks during updates create contention between workers
- Cannot easily implement backpressure or flow control
- Difficult to prioritize certain operations (e.g., new scenes vs updates)
- Database size grows with queue depth
- Cannot easily implement distributed workers

**Prevention:**
- **For lightweight needs (single-instance plugin):** In-memory queue with persistent backup:
  - Python's `queue.PriorityQueue` for active items
  - Pickle to disk periodically for crash recovery
  - Suitable when: single process, moderate volume (<1000 queued items)
- **For production/multi-instance needs:** Dedicated queue system:
  - Redis with sorted sets (can persist to disk): `ZADD sync_queue {timestamp} {scene_id}`
  - RabbitMQ or similar message broker for complex workflows
  - AWS SQS for cloud deployments
- **If database is unavoidable:**
  - Use `SELECT ... FOR UPDATE SKIP LOCKED` to prevent lock contention (Postgres)
  - Index on `(status, next_retry_at)` for efficient queries
  - Separate table from main Stash schema to avoid locking core tables
  - Archive completed items regularly
- **Hybrid approach:** Fast path (in-memory) for first retry, slow path (persistent storage) for extended retries

**Detection:**
- Database CPU spikes correlating with queue polling
- Lock wait times increasing
- Sync operations taking longer as queue depth grows
- Workers spending time waiting for locks rather than processing

**Sources:**
- [Microservice Antipatterns: The Queue Explosion (Charlie Pitman)](https://cpitman.github.io/microservices/2018/03/25/microservice-antipattern-queue-explosion.html)
- [Database-as-IPC (Wikipedia)](https://en.wikipedia.org/wiki/Database-as-IPC)
- [Using a database as a queue is a well known anti pattern (Hacker News)](https://news.ycombinator.com/item?id=18774559)

---

### Pitfall 5: Retrying Non-Transient Errors
**What goes wrong:** The system retries operations that will never succeed - like attempting to sync a scene when the corresponding Plex library doesn't exist, or when required metadata fields are missing from Stash. This wastes resources and delays detection of real problems.

**Why it happens:** Retry logic treats all failures the same, without distinguishing between transient errors (Plex temporarily unavailable) and permanent errors (invalid API key, missing required field).

**Consequences:**
- Queue fills with items that will never succeed
- Resources wasted on pointless retries
- Real transient failures get delayed waiting for permanent failures to exhaust retries
- Difficult to identify which failures need code fixes vs operational intervention

**Prevention:**
- **Classify errors before retrying:**
  - **TRANSIENT (retry):** Network timeouts, 503 Service Unavailable, 429 Rate Limited, connection refused
  - **PERMANENT (don't retry):** 401 Unauthorized, 403 Forbidden, 404 Not Found (library), 400 Bad Request (malformed data)
  - **AMBIGUOUS (retry cautiously):** 500 Internal Server Error (could be transient or permanent)
- **Implement error classification:**
  ```python
  TRANSIENT_ERRORS = {503, 429, 502, 504}
  PERMANENT_ERRORS = {400, 401, 403, 404, 422}

  if response.status_code in PERMANENT_ERRORS:
      mark_as_permanently_failed(item)
      send_alert(f"Permanent failure: {error}")
      return  # Don't retry
  elif response.status_code in TRANSIENT_ERRORS:
      schedule_retry_with_backoff(item)
  ```
- **Validate before queuing:** Check that required data exists before adding to queue:
  - Scene has file path
  - Target Plex library exists
  - API credentials valid
- **Max retry with inspection:** Even transient failures shouldn't retry forever - after max attempts, move to DLQ for human review

**Detection:**
- Same items appearing in queue repeatedly with same error
- Queue depth growing despite active processing
- Error logs showing repeated 4xx errors
- DLQ filling with items that have validation errors

**Sources:**
- [Retrying and Exponential Backoff: Smart Strategies (HackerOne)](https://www.hackerone.com/blog/retrying-and-exponential-backoff-smart-strategies-robust-software)
- [A Guide to Retry Pattern in Distributed Systems (ByteByteGo)](https://blog.bytebytego.com/p/a-guide-to-retry-pattern-in-distributed)

---

## Moderate Pitfalls

Mistakes that cause delays or technical debt.

### Pitfall 6: No Input Validation/Sanitization
**What goes wrong:** Stash metadata contains special characters, extremely long strings, or malformed data that causes Plex API errors or corrupts Plex's database when synced without sanitization.

**Prevention:**
- Validate all data before sending to Plex:
  - **Length limits:** Tag names, titles, descriptions (Plex has undocumented limits)
  - **Character encoding:** Remove or escape special characters that break Plex's XML/JSON parsing
  - **Required fields:** Ensure non-empty values for mandatory fields
  - **Data types:** Ratings are floats 0-10, dates are ISO8601, etc.
- Use allowlist approach where possible: known-good patterns rather than blocklist
- Sanitize file paths: Remove characters invalid in filesystem paths
- Escape special characters for API calls: HTML entities, URL encoding
- Example validation:
  ```python
  def sanitize_tag(tag: str) -> str:
      # Plex tags have ~255 char limit
      tag = tag[:255]
      # Remove problematic characters
      tag = re.sub(r'[<>&"]', '', tag)
      # Ensure not empty after sanitization
      return tag.strip() or "untagged"
  ```

**Detection:**
- Plex API returns 400 Bad Request with validation errors
- Plex UI shows garbled text or missing metadata
- Sync succeeds but data appears corrupted in Plex

**Sources:**
- [Input Validation - OWASP Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Input_Validation_Cheat_Sheet.html)
- [Input Validation and Sanitization: Ensuring API Security (Software Patterns Lexicon)](https://softwarepatternslexicon.com/cloud-computing/api-management-and-integration-services/input-validation-and-sanitization/)
- [API Security Risks and Trends for 2026 (CybelAngel)](https://cybelangel.com/blog/api-security-risks/)

---

### Pitfall 7: Poor Matching Logic (False Negatives)
**What goes wrong:** Sync fails to find the correct Plex item for a Stash scene, even when it exists in Plex, requiring manual intervention. This happens due to filename mismatches, path differences, or overly strict matching criteria.

**Prevention:**
- **Multi-strategy matching with fallback:**
  1. Exact file path match (fastest, most reliable)
  2. Filename match (handle different mount points: `/mnt/media` vs `D:\media`)
  3. Fuzzy filename match (handle encoding differences, extra spaces)
  4. Metadata match (duration + file size within tolerance)
  5. Manual match table (user-provided scene_id → plex_id mappings)
- **Normalize before comparing:**
  - Convert to lowercase
  - Remove special characters/punctuation
  - Normalize Unicode (NFD vs NFC)
  - Trim whitespace
- **Handle common path translation issues:**
  - Stash sees `/mnt/media/video.mp4`
  - Plex sees `D:\media\video.mp4` (Windows vs Linux mount points)
  - Solution: Allow configurable path prefix mappings
- **Tolerate minor differences:**
  - File duration within 2 seconds (encoding differences)
  - File size within 1% (metadata differences)
  - Fuzzy string matching with 95% similarity threshold
- **Log match confidence:** Track which strategy succeeded, alert on low confidence
- **Balance precision vs recall:**
  - High precision (strict matching): Fewer false positives, more false negatives (manual work)
  - High recall (loose matching): More false positives (wrong matches), fewer false negatives
  - For sync plugins, false negatives are usually acceptable (scene just doesn't sync); false positives corrupt data
  - **Recommendation:** Prefer precision, provide UI for manual matching on failures

**Detection:**
- User reports metadata not syncing despite scene existing in both systems
- Logs show "Plex item not found" for scenes that should match
- Manual match table grows rapidly

**Sources:**
- [The Myth of Perfect Metadata Matching (Crossref)](https://www.crossref.org/blog/the-myth-of-perfect-metadata-matching/)
- [Fuzzy Matching 101: Accurate Data Matching (Data Ladder)](https://dataladder.com/fuzzy-matching-101/)
- [How Good Is Your Matching? (ROR)](https://ror.org/blog/2024-11-06-how-good-is-your-matching/)

---

### Pitfall 8: Ignoring Rate Limits
**What goes wrong:** Plugin makes too many API requests to Plex too quickly, gets rate limited (429 responses), and either fails to handle this gracefully or enters a retry loop that makes the problem worse.

**Prevention:**
- **Respect Plex's rate limits:**
  - Undocumented but generally permissive for local API calls
  - More strict for Plex.tv authentication endpoints
  - Can be triggered by rapid-fire requests (hundreds per second)
- **Implement client-side rate limiting:**
  - Token bucket algorithm: Start with N tokens, consume 1 per request, refill at fixed rate
  - Sliding window counter: Track requests in last N seconds
  - Example with token bucket:
    ```python
    from threading import Lock
    import time

    class RateLimiter:
        def __init__(self, max_requests, window_seconds):
            self.max_requests = max_requests
            self.window = window_seconds
            self.tokens = max_requests
            self.last_refill = time.time()
            self.lock = Lock()

        def acquire(self):
            with self.lock:
                self._refill()
                if self.tokens >= 1:
                    self.tokens -= 1
                    return True
                return False

        def _refill(self):
            now = time.time()
            elapsed = now - self.last_refill
            new_tokens = elapsed * (self.max_requests / self.window)
            self.tokens = min(self.max_requests, self.tokens + new_tokens)
            self.last_refill = now
    ```
- **Handle 429 responses:**
  - Check for `Retry-After` header (seconds or HTTP date)
  - If present, wait that duration before retrying
  - If absent, use exponential backoff
  - Don't count 429 against max retry attempts (it's expected)
- **Batch operations:** Instead of updating each tag individually, batch multiple changes into single API call
- **Prioritize operations:** New scene sync is higher priority than metadata update

**Detection:**
- 429 responses in logs
- Plex returns errors about too many requests
- Sync latency spikes during bulk operations

**Sources:**
- [API Rate Limiting: Understanding Request Throttling (Postman)](https://blog.postman.com/what-is-api-rate-limiting/)
- [10 Best Practices for API Rate Limiting and Throttling (Knit)](https://www.getknit.dev/blog/10-best-practices-for-api-rate-limiting-and-throttling)
- [Rate Limiting Best Practices (Cloudflare)](https://developers.cloudflare.com/waf/rate-limiting-rules/best-practices/)

---

### Pitfall 9: No Timeout Configuration
**What goes wrong:** Requests to Plex API hang indefinitely when Plex is unresponsive (but not completely down), blocking the sync worker thread and preventing other operations from processing.

**Prevention:**
- **Set timeouts on all HTTP requests:**
  ```python
  # Bad: can hang forever
  response = requests.get(plex_url)

  # Good: fails fast
  response = requests.get(plex_url, timeout=(5, 30))  # (connect, read) timeouts
  ```
- **Appropriate timeout values:**
  - Connect timeout: 3-5 seconds (establishing connection)
  - Read timeout: 15-30 seconds (waiting for response)
  - Longer for operations known to be slow (searching large libraries)
- **Timeout hierarchy:**
  - HTTP request timeout < Operation timeout < Worker timeout
  - Example: Request timeout 30s, operation timeout 60s, worker timeout 120s
- **Handle timeout errors as transient:** Retry with backoff, don't mark as permanent failure

**Detection:**
- Sync operations never complete
- Worker threads stuck waiting
- No error logs, just absence of completion

**Sources:**
- [Timeouts, retries and backoff with jitter (AWS)](https://aws.amazon.com/builders-library/timeouts-retries-and-backoff-with-jitter/)
- Common pattern across all API integration best practices guides

---

### Pitfall 10: State Management Without Persistence
**What goes wrong:** Plugin crashes or restarts, losing all in-memory queue state. Pending sync operations disappear, and there's no way to recover which scenes needed syncing.

**Prevention:**
- **Persist queue state:**
  - Option 1: Save to disk on every queue change (slow but safe)
  - Option 2: Save periodically (every 30s or 100 ops) + on graceful shutdown
  - Option 3: Use persistent queue (Redis, database) from start
- **Track operation state in durable storage:**
  - Maintain `last_sync_attempt` timestamp per scene
  - Track `sync_status`: pending/in_progress/completed/failed
  - Store `retry_count` and `next_retry_at`
- **Crash recovery on startup:**
  - Load persisted queue state
  - Find operations in "in_progress" state (crashed while processing)
  - Reset them to "pending" for retry
  - Resume from last checkpoint
- **Graceful shutdown handling:**
  ```python
  import signal
  import sys

  def graceful_shutdown(signum, frame):
      logger.info("Shutdown signal received, saving state...")
      queue.persist_to_disk()
      sys.exit(0)

  signal.signal(signal.SIGTERM, graceful_shutdown)
  signal.signal(signal.SIGINT, graceful_shutdown)
  ```

**Detection:**
- Operations disappear after plugin restart
- Users report syncs not completing after Stash restart
- Queue depth resets to 0 on restart

---

## Minor Pitfalls

Mistakes that cause annoyance but are fixable.

### Pitfall 11: Logging Sensitive Data
**What goes wrong:** Logs contain Plex API tokens, authentication credentials, or user file paths, creating security risks when logs are shared for debugging.

**Prevention:**
- Redact sensitive data before logging:
  - API tokens: Show first/last 4 chars only (`sk_abc...xyz`)
  - Passwords: Never log, even hashed
  - File paths: Consider privacy - may reveal user's library organization
  - User IDs: Hash or pseudonymize
- Example:
  ```python
  def redact_token(token: str) -> str:
      if len(token) < 12:
          return "***"
      return f"{token[:4]}...{token[-4:]}"

  log.info(f"Calling Plex API with token {redact_token(api_token)}")
  ```
- Use structured logging to separate sensitive fields:
  ```python
  log.info("API call successful", extra={
      "endpoint": "/library/sections",
      "token": redact_token(token),  # Redacted in logs
      "duration_ms": elapsed
  })
  ```

**Detection:**
- Security audit finds tokens in log files
- User shares debug logs containing credentials

---

### Pitfall 12: Not Logging Enough Context
**What goes wrong:** Error logs say "Sync failed" without indicating which scene, what operation, or why it failed, making debugging impossible.

**Prevention:**
- Include context in every log message:
  - Scene ID, file path, operation type
  - Correlation ID for tracing
  - Error details (status code, error message)
  - Timing information
- Example:
  ```python
  log.error(
      f"[{correlation_id}] Sync failed for scene {scene_id}",
      extra={
          "scene_id": scene_id,
          "scene_path": scene.path,
          "operation": "update_tags",
          "plex_library_id": library_id,
          "error_type": type(e).__name__,
          "error_message": str(e),
          "duration_ms": elapsed,
          "retry_count": retry_count
      }
  )
  ```
- Log successful operations too (at INFO level):
  - Confirms system is working
  - Helps measure performance
  - Useful for audit trail

**Detection:**
- Developers unable to debug issues from logs
- "Need more information" responses on bug reports

---

### Pitfall 13: Webhook Reliability Assumptions
**What goes wrong:** Assuming Stash's plugin hooks fire reliably for every scene update. Webhooks can be missed, duplicated, or delayed, leading to missed syncs or duplicate syncs.

**Prevention:**
- **Don't rely solely on webhooks:** Supplement with periodic full scans
  - Webhook handles 99% of cases (immediate sync)
  - Hourly/daily scan catches missed updates
- **Handle duplicate webhook events:** Use idempotency to prevent duplicate syncs
- **Handle delayed webhooks:** If webhook arrives 10 minutes late, check if sync already happened
- **Implement webhook validation:** Verify webhook authenticity if Stash provides signatures

**Detection:**
- Scenes updated in Stash don't sync to Plex
- Same scene syncs multiple times from single update

**Sources:**
- [SaaS Integration Best Practices: Webhooks (Skyvia)](https://blog.skyvia.com/saas-integration-best-practices/)
- [11 Common Integration Challenges (BindBee)](https://www.bindbee.dev/blog/overcome-integration-challenges)

---

## Phase-Specific Warnings

Based on the PlexSync improvement roadmap, here are pitfalls mapped to likely implementation phases:

| Phase Topic | Likely Pitfall | Mitigation |
|-------------|---------------|------------|
| Retry Logic Implementation | Pitfall 2: Missing exponential backoff + jitter | Start with exponential backoff library (e.g., `tenacity` for Python) rather than rolling your own |
| Queue Mechanism | Pitfall 4: Database-as-queue anti-pattern | Use in-memory queue with disk persistence for simplicity, or Redis for production |
| Late Update Detection | Pitfall 13: Webhook reliability assumptions | Implement both webhook listeners AND periodic reconciliation scans |
| Input Sanitization | Pitfall 6: No validation leading to corrupted Plex data | Create validation functions early, before implementing sync logic |
| Idempotency Implementation | Pitfall 1: Duplicates from retries | Design operations to be idempotent from start, not as afterthought |
| Observability/Logging | Pitfall 3: Silent failures with no monitoring | Implement structured logging and health checks before deploying retry logic |
| Error Classification | Pitfall 5: Retrying permanent errors | Create error classification logic before implementing retry - saves debugging time |
| Rate Limiting | Pitfall 8: Overwhelming Plex API | Add client-side rate limiter wrapper around Plex API client early |

## Research Confidence

| Area | Confidence | Notes |
|------|------------|-------|
| Retry patterns | HIGH | Well-documented patterns from AWS, ByteByteGo, Microsoft, backed by 2026 sources |
| Queue anti-patterns | HIGH | Multiple authoritative sources (Temporal, industry blogs) with specific examples |
| Idempotency | HIGH | Recent 2026 sources from payment/fintech domains with production examples |
| Observability | MEDIUM | Good 2026 sources but less specific to sync plugins vs general distributed systems |
| Metadata matching | MEDIUM | Good academic/industry sources but focused on scholarly metadata vs media files |
| Rate limiting | HIGH | Authoritative sources from API gateway providers (Cloudflare, AWS, Atlassian) |
| Plex API specifics | LOW | No official Plex API documentation found; recommendations based on general API best practices |

## Key Takeaways

**Don't underestimate:**
1. **Silent failures** - Absence of events is harder to detect than presence of errors
2. **Idempotency** - Easier to design in from start than bolt on after problems arise
3. **Error classification** - Not all failures should retry; distinguish transient vs permanent early

**Do prioritize:**
1. **Exponential backoff + jitter** - Non-negotiable for production retry logic
2. **Structured logging** - Invest early, debugging will be 10x easier
3. **Health checks** - Monitor both success (operations completing) and absence (operations missing)

**Sequence matters:**
1. Implement idempotency BEFORE retry logic (prevents duplicates from retries)
2. Implement logging/observability BEFORE queue mechanism (makes debugging queue issues possible)
3. Implement error classification BEFORE exponential backoff (prevents wasted retries)

## Sources

### Retry & Resilience Patterns
- [Designing retry logic that doesn't create data duplicates (Medium, Jan 2026)](https://medium.com/@backend.bao/designing-retry-logic-that-doesnt-create-data-duplicates-99a784500931)
- [Retrying and Exponential Backoff: Smart Strategies for Robust Software (HackerOne)](https://www.hackerone.com/blog/retrying-and-exponential-backoff-smart-strategies-robust-software)
- [Timeouts, retries and backoff with jitter (AWS Builders Library)](https://aws.amazon.com/builders-library/timeouts-retries-and-backoff-with-jitter/)
- [A Guide to Retry Pattern in Distributed Systems (ByteByteGo)](https://blog.bytebytego.com/p/a-guide-to-retry-pattern-in-distributed)
- [Better Retries with Exponential Backoff and Jitter (Baeldung)](https://www.baeldung.com/resilience4j-backoff-jitter)

### Idempotency & Duplicate Prevention
- [Preventing Duplicate Operations in APIs with Idempotent Keys (Medium)](https://medium.com/@anas.mdhat/preventing-duplicate-operations-in-apis-with-idempotent-keys-f67c3bf6117a)
- [Mastering Idempotency: Building Reliable APIs (ByteByteGo)](https://blog.bytebytego.com/p/mastering-idempotency-building-reliable)
- [Implementing Idempotency Keys in REST APIs (Zuplo)](https://zuplo.com/learning-center/implementing-idempotency-keys-in-rest-apis-a-complete-guide)
- [Understanding Idempotency in Data Pipelines (Airbyte)](https://airbyte.com/data-engineering-resources/idempotency-in-data-pipelines)

### Queue Systems & Anti-patterns
- [Microservice Antipatterns: The Queue Explosion (Charlie Pitman)](https://cpitman.github.io/microservices/2018/03/25/microservice-antipattern-queue-explosion.html)
- [Database-as-IPC (Wikipedia)](https://en.wikipedia.org/wiki/Database-as-IPC)
- [Queue-Based Exponential Backoff: Resilient Retry Pattern (DEV Community)](https://dev.to/andreparis/queue-based-exponential-backoff-a-resilient-retry-pattern-for-distributed-systems-37f3)

### Observability & Silent Failures
- [Building A Monitoring System That Catches Silent Failures (Vincent Lakatos)](https://www.vincentlakatos.com/blog/building-a-monitoring-system-that-catches-silent-failures/)
- [Agentforce Studio's New Health Monitoring Tool Aims to Catch 'Silent Failures' (Salesforce, 2026)](https://www.salesforce.com/blog/agent-monitoring/?bc=OTH)
- [We Caught 92% of Outages Before Users Noticed: Synthetic Monitoring (Medium, Jan 2026)](https://medium.com/@yashbatra11111/we-caught-92-of-outages-before-users-noticed-why-synthetic-monitoring-beats-reactive-alerting-1f4cfeb0d770)
- [Effective Logging Strategies for Better Observability and Debugging (Medium)](https://juliofalbo.medium.com/effective-logging-strategies-for-better-observability-and-debugging-4b90decefdf1)

### Integration Best Practices
- [SaaS Integration Best Practices: A Comprehensive Guide (Skyvia, 2026)](https://blog.skyvia.com/saas-integration-best-practices/)
- [Common Integration Style Pitfalls and Design Best Practices (Oracle)](https://docs.oracle.com/en/cloud/paas/integration-cloud/integrations-user/common-integration-style-pitfalls-and-design-best-practices.html)
- [11 Common Integration Challenges And How to Overcome Them (BindBee)](https://www.bindbee.dev/blog/overcome-integration-challenges)

### API Security & Validation
- [Input Validation - OWASP Cheat Sheet Series](https://cheatsheetseries.owasp.org/cheatsheets/Input_Validation_Cheat_Sheet.html)
- [Input Validation and Sanitization: Ensuring API Security (Software Patterns Lexicon)](https://softwarepatternslexicon.com/cloud-computing/api-management-and-integration-services/input-validation-and-sanitization/)
- [API Security Risks and Trends for 2026 (CybelAngel)](https://cybelangel.com/blog/api-security-risks/)

### Rate Limiting & Throttling
- [API Rate Limiting: Understanding Request Throttling (Postman)](https://blog.postman.com/what-is-api-rate-limiting/)
- [10 Best Practices for API Rate Limiting and Throttling (Knit)](https://www.getknit.dev/blog/10-best-practices-for-api-rate-limiting-and-throttling)
- [Rate Limiting Best Practices (Cloudflare)](https://developers.cloudflare.com/waf/rate-limiting-rules/best-practices/)

### Metadata Matching
- [The Myth of Perfect Metadata Matching (Crossref)](https://www.crossref.org/blog/the-myth-of-perfect-metadata-matching/)
- [Fuzzy Matching 101: Accurate Data Matching (Data Ladder)](https://dataladder.com/fuzzy-matching-101/)
- [How Good Is Your Matching? (ROR, Nov 2024)](https://ror.org/blog/2024-11-06-how-good-is-your-matching/)
