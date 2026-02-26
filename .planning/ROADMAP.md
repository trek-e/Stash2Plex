# Roadmap: PlexSync

## Milestones

- ✅ **v1.0 MVP** — Phases 1-5 (shipped 2026-02-03) → [archived](milestones/v1.0-ROADMAP.md)
- ✅ **v1.1 Testing & Documentation** — Phases 1-10 + 2.1 (shipped 2026-02-03) → [archived](milestones/v1.1-ROADMAP.md)
- ✅ **v1.2 Queue Management UI** — Phases 11-13 (shipped 2026-02-04) → [archived](milestones/v1.2-ROADMAP.md)
- ✅ **v1.3 Production Stability** — Ad-hoc (shipped 2026-02-09)
- ✅ **v1.4 Metadata Reconciliation** — Phases 14-16 (shipped 2026-02-14) → [archived](milestones/v1.4-ROADMAP.md)
- ✅ **v1.5 Outage Resilience** — Phases 17-22 (shipped 2026-02-24) → [archived](milestones/v1.5-ROADMAP.md)
- 🚧 **v2.0 Plex Metadata Provider** — Phases 23-27 (in progress)

## Phases

<details>
<summary>✅ v1.4 Metadata Reconciliation (Phases 14-16) — SHIPPED 2026-02-14</summary>

- [x] Phase 14: Gap Detection Engine (2/2 plans) — completed 2026-02-14
- [x] Phase 15: Manual Reconciliation (1/1 plans) — completed 2026-02-14
- [x] Phase 16: Automated Reconciliation & Reporting (2/2 plans) — completed 2026-02-14

</details>

<details>
<summary>✅ v1.5 Outage Resilience (Phases 17-22) — SHIPPED 2026-02-24</summary>

- [x] Phase 17: Circuit Breaker Persistence (2/2 plans) — completed 2026-02-15
- [x] Phase 18: Health Check Infrastructure (2/2 plans) — completed 2026-02-15
- [x] Phase 19: Recovery Detection & Automation (2/2 plans) — completed 2026-02-15
- [x] Phase 20: Graduated Recovery & Rate Limiting (2/2 plans) — completed 2026-02-15
- [x] Phase 21: Outage Visibility & History (2/2 plans) — completed 2026-02-15
- [x] Phase 22: DLQ Recovery for Outage Jobs (2/2 plans) — completed 2026-02-15

</details>

### 🚧 v2.0 Plex Metadata Provider (In Progress)

**Milestone Goal:** Add a Plex Custom Metadata Provider service that Plex queries during library scans to resolve and serve Stash scene metadata, with regex-based bidirectional path mapping and bi-directional gap detection between libraries.

- [x] **Phase 23: Foundation + Shared Library** — Monorepo structure, shared_lib package, bidirectional path mapping engine, async Stash GraphQL client (1/2 plans done)
- [x] **Phase 24: Provider HTTP Skeleton** — FastAPI provider registers with Plex, Docker container deployed, Plex shows Stash2Plex in agent list (completed 2026-02-26)
- [ ] **Phase 25: Match Endpoint** — Plex scan requests return Stash scene IDs via path mapping + fallback; startup roundtrip validation; 90s timeout compliance
- [ ] **Phase 26: Metadata Serve Route** — Plex displays full scene metadata (title, date, studio, performers, tags, summary, artwork) after a successful match
- [ ] **Phase 27: Gap Detection** — Scan-time gaps logged in real time; scheduled bi-directional comparison runs; gap report accessible via API endpoint

## Phase Details

### Phase 23: Foundation + Shared Library
**Goal**: The monorepo shared code layer exists and both the plugin and provider can import it
**Depends on**: Nothing (first v2.0 phase)
**Requirements**: INFR-01, INFR-02, PATH-01, PATH-02
**Success Criteria** (what must be TRUE):
  1. `shared_lib/` package is importable from both `provider/` and the existing Stash plugin without import errors
  2. `shared_lib/path_mapper.py` translates a Plex path to a Stash path and back again using a user-defined regex rule
  3. Path mapping supports multiple named rules evaluated in priority order — first matching rule wins
  4. `shared_lib/stash_client.py` queries Stash GraphQL to find a scene by file path and by scene ID and returns a typed result
  5. Docker build context is set to repo root so `shared_lib/` is available inside the provider container at build time
**Plans:** 2/2 plans complete
Plans:
- [x] 23-01-PLAN.md — Infrastructure + bidirectional path mapper (TDD) — complete 2026-02-24
- [ ] 23-02-PLAN.md — Async Stash GraphQL client + import verification (TDD)

### Phase 24: Provider HTTP Skeleton
**Goal**: A running Docker container that Plex can reach and register as a metadata provider
**Depends on**: Phase 23
**Requirements**: PROV-01, PROV-05, INFR-03, INFR-04
**Success Criteria** (what must be TRUE):
  1. Plex Media Server shows "Stash2Plex" in its list of available metadata agents after configuring the provider URL
  2. The provider container starts with Stash and Plex connection details supplied as environment variables (no hardcoded values)
  3. `docker-compose up` brings the provider online; `docker-compose down` stops it cleanly
  4. The provider URL registered in Plex is reachable from Plex's network context on both Linux and macOS Docker deployments
**Plans:** 2/2 plans complete
Plans:
- [ ] 24-01-PLAN.md — FastAPI provider application (config, logging, routes, models)
- [ ] 24-02-PLAN.md — Docker infrastructure (Dockerfile, docker-compose.yml, build + verify)

### Phase 25: Match Endpoint
**Goal**: Plex library scans successfully match files to Stash scenes via the provider
**Depends on**: Phase 24
**Requirements**: PROV-02, PROV-04, PATH-03, PATH-04
**Success Criteria** (what must be TRUE):
  1. A Plex scan of a configured library returns Stash scene IDs for files whose paths satisfy a configured path mapping rule
  2. Files with no path mapping match fall back to filename-only Stash lookup and still return a candidate when the file exists in Stash
  3. Startup validation confirms each configured mapping rule correctly round-trips (Plex path → Stash path → Plex path) before the provider accepts traffic; misconfigured rules are reported and rejected at startup
  4. The provider correctly handles Plex's relative-to-library-root filename format and reconstructs absolute Stash paths
  5. The provider responds to all match requests within Plex's 90-second timeout even during a full library rescan with concurrent requests
**Plans**: TBD

### Phase 26: Metadata Serve Route
**Goal**: Plex displays full scene metadata sourced from Stash after matching
**Depends on**: Phase 25
**Requirements**: PROV-03
**Success Criteria** (what must be TRUE):
  1. After a successful match, Plex displays the scene's title, release date, studio, summary, and duration from Stash
  2. Performers appear in Plex's cast list with their Stash names
  3. Stash tags appear as Plex genres
  4. A scene thumbnail (screenshot) from Stash appears as the Plex poster image
**Plans**: TBD

### Phase 27: Gap Detection
**Goal**: Missing files and scenes are identified and surfaced for review without manual investigation
**Depends on**: Phase 25
**Requirements**: GAPD-01, GAPD-02, GAPD-03, GAPD-04
**Success Criteria** (what must be TRUE):
  1. During a Plex scan, any file that the provider cannot match to a Stash scene is recorded as a gap in real time (visible in logs immediately)
  2. A scheduled job runs bidirectional comparison — files in Plex with no Stash scene AND Stash scenes with no Plex file — on a user-configured schedule (hourly/daily/weekly/manual)
  3. Gap report results are accessible via an API endpoint so the Stash plugin UI or an HTTP client can retrieve them
  4. The comparison schedule is configurable via environment variable; manual trigger is always available regardless of schedule
**Plans**: TBD

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 14. Gap Detection Engine | v1.4 | 2/2 | Complete | 2026-02-14 |
| 15. Manual Reconciliation | v1.4 | 1/1 | Complete | 2026-02-14 |
| 16. Automated Reconciliation & Reporting | v1.4 | 2/2 | Complete | 2026-02-14 |
| 17. Circuit Breaker Persistence | v1.5 | 2/2 | Complete | 2026-02-15 |
| 18. Health Check Infrastructure | v1.5 | 2/2 | Complete | 2026-02-15 |
| 19. Recovery Detection & Automation | v1.5 | 2/2 | Complete | 2026-02-15 |
| 20. Graduated Recovery & Rate Limiting | v1.5 | 2/2 | Complete | 2026-02-15 |
| 21. Outage Visibility & History | v1.5 | 2/2 | Complete | 2026-02-15 |
| 22. DLQ Recovery for Outage Jobs | v1.5 | 2/2 | Complete | 2026-02-15 |
| 23. Foundation + Shared Library | 2/2 | Complete    | 2026-02-24 | - |
| 24. Provider HTTP Skeleton | 2/2 | Complete   | 2026-02-26 | - |
| 25. Match Endpoint | v2.0 | 0/? | Not started | - |
| 26. Metadata Serve Route | v2.0 | 0/? | Not started | - |
| 27. Gap Detection | v2.0 | 0/? | Not started | - |

---
*Last updated: 2026-02-24 after 23-01 completion*
