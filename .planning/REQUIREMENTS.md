# Requirements: PlexSync v2.0 Plex Metadata Provider

**Defined:** 2026-02-23
**Core Value:** Reliable sync — when metadata changes in Stash, it eventually reaches Plex — even if Plex was temporarily unavailable

## v2.0 Requirements

Requirements for Plex metadata provider milestone. Each maps to roadmap phases.

### Provider Core

- [x] **PROV-01**: Plex metadata provider registers as tv.plex.agents.custom.stash2plex with Match + Metadata features
- [ ] **PROV-02**: Match endpoint accepts Plex scan request and returns match candidates from Stash via path mapping + fallback
- [ ] **PROV-03**: Metadata endpoint returns full scene metadata (title, summary, date, performers, tags, studio, artwork) for a matched scene
- [ ] **PROV-04**: Provider responds within Plex's 90-second timeout under concurrent scan load
- [ ] **PROV-05**: Provider deployed as Docker container with configurable Stash/Plex connection settings

### Path Mapping

- [x] **PATH-01**: Regex-based bidirectional path mapping translates Plex library paths to Stash scene paths and vice versa
- [x] **PATH-02**: Path mapping supports multiple named rules applied in order
- [ ] **PATH-03**: Startup roundtrip validation confirms each mapping rule correctly translates in both directions
- [ ] **PATH-04**: Path mapping handles Plex's relative-to-library-root filename format

### Gap Detection

- [ ] **GAPD-01**: Real-time gap detection flags files in Plex that Stash doesn't know about during Match requests
- [ ] **GAPD-02**: Scheduled comparison identifies gaps in both directions (Plex→Stash and Stash→Plex)
- [ ] **GAPD-03**: Gap detection results available as a report (API endpoint or log output)
- [ ] **GAPD-04**: Configurable comparison schedule (hourly/daily/weekly/manual)

### Infrastructure

- [x] **INFR-01**: Monorepo structure with shared_lib/ package importable by both plugin and provider
- [x] **INFR-02**: Stash GraphQL client in shared_lib/ queries scenes by path and by ID
- [ ] **INFR-03**: Docker container handles Linux host networking (host.docker.internal workaround)
- [x] **INFR-04**: Provider configuration via environment variables and/or config file

## Future Requirements

### Advanced Provider

- **PROV-06**: Provider serves artwork (poster, background) proxied from Stash with auth token
- **PROV-07**: Provider supports Plex's includeChildren for TV-show-like content hierarchies
- **PROV-08**: Match endpoint supports hash-based matching (phash/oshash) as tertiary fallback

### Advanced Gap Detection

- **GAPD-05**: Gap detection auto-enqueues discovered gaps into the v1.x sync queue for resolution
- **GAPD-06**: Gap detection web dashboard with filterable results

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Plex → Stash metadata write-back | Stash remains primary metadata source; provider reads only |
| Replace v1.x push model | Push model handles real-time hook-driven sync; provider is complementary |
| Provider serves video streams | Out of scope; Plex handles media serving |
| Mobile/web UI for provider | Docker logs + API endpoints sufficient for v2.0 |
| Non-Docker deployment | Docker is the deployment model; bare-metal not supported |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| PROV-01 | Phase 24 | Complete |
| PROV-02 | Phase 25 | Pending |
| PROV-03 | Phase 26 | Pending |
| PROV-04 | Phase 25 | Pending |
| PROV-05 | Phase 24 | Pending |
| PATH-01 | Phase 23 | Complete |
| PATH-02 | Phase 23 | Complete |
| PATH-03 | Phase 25 | Pending |
| PATH-04 | Phase 25 | Pending |
| GAPD-01 | Phase 27 | Pending |
| GAPD-02 | Phase 27 | Pending |
| GAPD-03 | Phase 27 | Pending |
| GAPD-04 | Phase 27 | Pending |
| INFR-01 | Phase 23 | Complete |
| INFR-02 | Phase 23 | Complete |
| INFR-03 | Phase 24 | Pending |
| INFR-04 | Phase 24 | Complete |

**Coverage:**
- v2.0 requirements: 17 total
- Mapped to phases: 17
- Unmapped: 0 ✓

---
*Requirements defined: 2026-02-23*
*Last updated: 2026-02-23 after roadmap creation (traceability complete)*
