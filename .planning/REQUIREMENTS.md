# Requirements: PlexSync Improvements

**Defined:** 2025-01-24
**Core Value:** Reliable sync — when metadata changes in Stash, it eventually reaches Plex

## v1 Requirements

### Retry & Reliability

- [ ] **RTRY-01**: Failed Plex API calls retry with exponential backoff and jitter
- [x] **RTRY-02**: Transient errors (network, 5xx, timeout) trigger retry; permanent errors (4xx except 429) do not
- [ ] **RTRY-03**: Permanently failed operations go to dead letter queue for manual review
- [ ] **RTRY-04**: All Plex API calls have explicit connect and read timeouts

### Queue & Persistence

- [x] **QUEUE-01**: Sync jobs persist to SQLite-backed queue (survives process restart)
- [x] **QUEUE-02**: Hook handler captures events quickly (<100ms) and enqueues for background processing
- [x] **QUEUE-03**: Background worker processes queue with retry orchestration

### Input Validation

- [x] **VALID-01**: Metadata validated against schema before sending to Plex
- [x] **VALID-02**: Special characters sanitized to prevent API errors
- [x] **VALID-03**: Plugin configuration validated against schema on load

### Matching & Late Updates

- [ ] **MATCH-01**: Improved matching logic reduces false negatives when finding Plex items
- [ ] **MATCH-02**: Late metadata updates in Stash trigger re-sync to Plex
- [ ] **MATCH-03**: Matches scored with confidence; low-confidence matches logged for review

## v2 Requirements

### Advanced Reliability

- **ADV-01**: Circuit breaker prevents cascading failures during extended Plex outages
- **ADV-02**: Adaptive retry strategies based on failure patterns
- **ADV-03**: Rate limiting to prevent overwhelming Plex API

### Observability

- **OBS-01**: Structured logging with correlation IDs
- **OBS-02**: Sync health dashboard showing queue depth, success rate
- **OBS-03**: Periodic reconciliation scans to catch missed syncs

## Out of Scope

| Feature | Reason |
|---------|--------|
| Plex → Stash sync | Stash remains primary metadata source; bidirectional adds complexity |
| Real-time webhooks from Plex | Would require Plex-side configuration; hook approach is simpler |
| Web UI for queue management | CLI/log-based initially; UI adds significant complexity |
| Multi-Plex server support | Focus on single server reliability first |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| QUEUE-01 | Phase 1 | Complete |
| QUEUE-02 | Phase 1 | Complete |
| QUEUE-03 | Phase 1 | Complete |
| VALID-01 | Phase 2 | Complete |
| VALID-02 | Phase 2 | Complete |
| VALID-03 | Phase 2 | Complete |
| RTRY-02 | Phase 2 | Complete |
| MATCH-01 | Phase 3 | Pending |
| RTRY-04 | Phase 3 | Pending |
| RTRY-01 | Phase 4 | Pending |
| RTRY-03 | Phase 4 | Pending |
| MATCH-02 | Phase 5 | Pending |
| MATCH-03 | Phase 5 | Pending |

**Coverage:**
- v1 requirements: 13 total
- Mapped to phases: 13
- Unmapped: 0 ✓

---
*Requirements defined: 2025-01-24*
*Last updated: 2026-01-24 after Phase 2 completion*
