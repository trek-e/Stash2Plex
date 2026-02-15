# Requirements: PlexSync v1.5 Outage Resilience

**Defined:** 2026-02-15
**Core Value:** Reliable sync — when metadata changes in Stash, it eventually reaches Plex — even if Plex was temporarily unavailable

## v1.5 Requirements

Requirements for outage resilience milestone. Each maps to roadmap phases.

### Recovery

- [ ] **RECV-01**: Plugin automatically drains pending queue jobs when Plex recovers from outage without user interaction
- [ ] **RECV-02**: Active health check probes Plex during circuit OPEN state to detect recovery
- [ ] **RECV-03**: Plugin logs recovery notification when circuit transitions from OPEN back to CLOSED
- [ ] **RECV-04**: Queue draining after recovery uses graduated rate limiting to avoid overwhelming Plex

### Health Monitoring

- [ ] **HLTH-01**: Plex health check using lightweight endpoint validates server connectivity
- [ ] **HLTH-02**: Passive health checks (job success/failure) combined with active probes for hybrid monitoring
- [ ] **HLTH-03**: Health check interval uses exponential backoff during extended outages (5s → 60s cap)

### State Persistence

- [ ] **STAT-01**: Circuit breaker state persists to JSON file and survives plugin restarts
- [ ] **STAT-02**: Recovery scheduler tracks check timing via persisted state file

### Outage Visibility

- [ ] **VISB-01**: Queue status UI shows circuit breaker state and recovery timing
- [ ] **VISB-02**: All circuit breaker state transitions logged with descriptive messages
- [ ] **VISB-03**: Outage history tracks start/end times, duration, and jobs affected (last 30 outages)
- [ ] **VISB-04**: Outage summary report available as Stash UI task

### DLQ Management

- [ ] **DLQM-01**: "Recover Outage Jobs" task re-queues DLQ entries with transient errors from outage windows
- [ ] **DLQM-02**: DLQ recovery supports per-error-type filtering (PlexServerDown, Timeout, etc.)

## Future Requirements

### Advanced Recovery

- **RECV-05**: Outage-triggered reconciliation detects metadata gaps from hook events missed during extended outages
- **RECV-06**: Configurable recovery strategies per error type (aggressive/conservative)

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Real-time push notifications | Stash plugins not daemons; external monitoring tools (Uptime Kuma) solve this |
| Automatic full reconciliation on recovery | Too expensive for large libraries (10K+ items); user-triggered with scope filter safer |
| Multi-tiered circuit breakers | Over-engineering; PlexServerDown already gets special handling (999 retries) |
| External health check endpoint | Plugin can't serve HTTP; Plex has native health endpoints |
| Automatic failover to backup server | Complex; manual failover via config change is safer |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| RECV-01 | — | Pending |
| RECV-02 | — | Pending |
| RECV-03 | — | Pending |
| RECV-04 | — | Pending |
| HLTH-01 | — | Pending |
| HLTH-02 | — | Pending |
| HLTH-03 | — | Pending |
| STAT-01 | — | Pending |
| STAT-02 | — | Pending |
| VISB-01 | — | Pending |
| VISB-02 | — | Pending |
| VISB-03 | — | Pending |
| VISB-04 | — | Pending |
| DLQM-01 | — | Pending |
| DLQM-02 | — | Pending |

**Coverage:**
- v1.5 requirements: 15 total
- Mapped to phases: 0
- Unmapped: 15 ⚠️

---
*Requirements defined: 2026-02-15*
*Last updated: 2026-02-15 after initial definition*
