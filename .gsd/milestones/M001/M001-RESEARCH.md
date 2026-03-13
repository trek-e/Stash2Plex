# Project Research Summary

**Project:** Stash2Plex v2.0 — Plex Custom Metadata Provider
**Domain:** HTTP metadata provider service + Stash GraphQL integration (monorepo)
**Researched:** 2026-02-23
**Confidence:** MEDIUM (Plex provider API is beta as of PMS 1.43.0; core contract documented and verified)

## Executive Summary

Stash2Plex v2.0 adds a pull-model Plex Custom Metadata Provider alongside the existing push-model Stash plugin. The provider is a long-running FastAPI HTTP service deployed as a Docker container that responds to Plex Media Server scan events, queries Stash GraphQL for scene metadata, and returns formatted Plex MediaContainer responses. The two models are complementary: the existing plugin handles real-time Stash hook events (push), while the new provider handles Plex-initiated scan-time lookups (pull). Neither replaces the other.

The recommended approach is Python/FastAPI in a Docker container sharing code with the existing plugin via a new `shared_lib/` package. Language consistency with the existing 29K-line Python codebase is the primary driver — shared path mapping logic, Stash GraphQL client, and Pydantic models can be imported directly rather than duplicated or RPC'd. The Plex provider API is in beta (PMS 1.43.0+), but the core three-endpoint contract (registration, match, metadata) is documented and confirmed via Plex's official reference implementation.

The two highest risks are both addressable at project setup time: (1) Docker networking configuration — the provider URL registered in Plex must be reachable from Plex's network context, not localhost, and `host.docker.internal` requires an extra_hosts entry on Linux; (2) the regex path mapping engine is the architectural lynchpin — Plex sends relative paths while Stash stores absolute paths, and bidirectional mapping must be validated via roundtrip tests at startup before any metadata logic runs. Both risks are well-understood and have clear prevention strategies.

## Key Findings

### Recommended Stack

Python/FastAPI wins decisively over Go or Rust for shared-code reasons, not performance. The provider's hot path is I/O-bound (Plex request → Stash GraphQL → response), and FastAPI on a single uvicorn worker handles 1,000–5,000 req/s — far above what Plex scan traffic demands. Critically, `shared_lib/` holds path mapping, Stash query logic, and Pydantic models that both the plugin and provider import directly. A second language would require duplicating or RPC-ing this code.

**Core technologies:**
- **FastAPI 0.115.14**: HTTP framework — async-first, Pydantic v2 native, auto-generates OpenAPI spec. Single uvicorn worker (avoids APScheduler running N times).
- **httpx 0.28.1**: Async HTTP client for Stash GraphQL calls — replaces stashapi in the provider's async context.
- **pydantic v2 (existing)**: Response model validation and provider config via BaseSettings — already in requirements.txt, zero new dep.
- **APScheduler 3.11.x**: Scheduled gap detection — AsyncIOScheduler integrates with FastAPI lifespan; appropriate for a long-running container (unlike the short-lived plugin where it was previously rejected).
- **diskcache 5.6.0 (existing)**: Cache Stash GraphQL results per request session — prevents Stash overload during large library scans.
- **Docker + docker-compose**: Container deployment; build context must be repo root (not `provider/`) to include `shared_lib/`.

**What not to use:** Flask (sync, blocks under concurrent scan load), Celery (overkill for one scheduled job), XML responses (JSON supported, Pydantic serializes it cleanly), gunicorn multi-worker (causes APScheduler to run N times).

### Expected Features

**Must have (table stakes — provider non-functional without these):**
- HTTP provider server: registration (`GET /`), match (`POST /library/metadata/matches`), metadata (`GET /library/metadata/{id}`)
- Match by Stash scene ID from `guid` field — stable re-match on subsequent Plex refreshes
- Regex path mapping engine — bidirectional, user-configurable named rules, first-match-wins
- Match by filename via mapped path → Stash `findScenesByPathRegex`
- Filename-only fallback when path mapping not configured or misses
- Full metadata response: title, date, studio, performers as Role[], tags as Genre[], details, duration, screenshot as thumb
- Empty match response (valid MediaContainer with empty array, never 404) for unmatched files
- Docker container with docker-compose.yml and environment variable configuration
- Stable ratingKey — use Stash integer scene ID; never embed file paths

**Should have (competitive differentiators):**
- Manual match (`manual=1`) returning multiple candidates ranked by confidence
- Gap detection: Plex files not in Stash (scan-time observation + scheduled)
- Gap detection: Stash scenes not in Plex (scheduled full comparison)
- Gap report surface accessible from Stash plugin UI (shared Docker volume JSON file)
- Real-time gap event logging during scans (free — match endpoint already knows "no match")

**Defer to v2.x+:**
- Batch metadata pre-warming at startup (defer until 90s timeout is a real production problem)
- Genre array bug workaround (monitor Plex for fix; single-tag workaround only if bug persists)
- Provider preferences UI in Plex (Plex has not shipped this feature as of February 2026)
- Title + date token tertiary fallback (low value; path + filename fallbacks cover most cases)

**Anti-features (do not build):**
- Plex → Stash metadata write-back (creates sync loops; Stash is the source of truth)
- Provider-managed retry queue (v1.x plugin already owns this; returning empty match is sufficient)
- Music library support (Plex provider API does not support music type)
- NFO / sidecar file generation (incompatible with the new provider API model)

### Architecture Approach

The architecture is a two-service monorepo: the existing short-lived plugin and a new long-running `provider/` Docker service sharing code through `shared_lib/`. The provider is a passive HTTP responder — Plex initiates all requests; the provider never calls Plex. All Stash access is read-only GraphQL queries via an async httpx client. The plugin's push model continues unchanged. The two gap detection perspectives (provider: scan-time misses; plugin reconciler: scheduled full comparison) complement each other without coupling.

**Major components:**
1. `shared_lib/path_mapper.py` — bidirectional regex path mapping engine; foundation everything else depends on
2. `shared_lib/stash_client.py` — async httpx GraphQL client (find_scene_by_path, find_scene_by_id, paginated enumeration)
3. `shared_lib/models.py` — shared Pydantic models (StashScene, path rules)
4. `provider/routes/discovery.py` — static MediaProvider registration response
5. `provider/routes/match.py` — primary integration point: path map → Stash lookup → confidence-ranked response
6. `provider/routes/metadata.py` + `provider/mappers/plex_response.py` — full scene metadata serve
7. `provider/gap/tracker.py` — scan-time gap observation; optional `/gaps` endpoint for plugin polling
8. `provider/config.py` — Pydantic BaseSettings from environment variables

**Build order dictated by dependencies:** shared_lib foundation first → provider HTTP skeleton (enables Plex registration testing with stubs) → match route → metadata route → gap tracker → plugin config extension.

### Critical Pitfalls

1. **GUID/ratingKey must never contain forward slashes** — use Stash integer scene ID only (`scene-123`). Embedding file paths in the ratingKey breaks Plex URL routing silently; items match but metadata fetch fails with no obvious error. Establish the ratingKey format in Phase 1 before any matching logic.

2. **Plex sends relative paths in the filename hint, not absolute paths** — the `filename` field in the Match request is relative to the Plex library root, not a full disk path. Path mapping must account for this; title/year should be primary match signals with path as a confidence booster, not the sole lookup key.

3. **`host.docker.internal` fails on Linux without extra_hosts config** — Docker Desktop (Mac/Windows) injects this DNS name automatically; Linux Docker does not. Add `extra_hosts: ["host.docker.internal:host-gateway"]` to docker-compose.yml from day one. Test on Linux before publishing the compose file.

4. **Provider URL registered in Plex must be reachable from Plex's network context** — `localhost` registered in Plex settings resolves to Plex's own container in Docker bridge mode (common on NAS deployments), not the host. Register using the host LAN IP or Docker service name depending on network topology.

5. **Regex path mapping silent wrong-direction failures** — bidirectional mapping uses two regex sets; a mistake in capture groups produces a syntactically valid but semantically wrong path, logged as "scene not in Stash" (a false gap). Implement startup roundtrip validation: apply forward mapping to sample Stash paths, then reverse mapping back, and fail startup if results don't match originals.

6. **90-second Plex timeout under concurrent scan load** — during a large library rescan, Plex fires many concurrent Match requests. Without a short Stash GraphQL timeout (≤10s) and result caching, slow Stash responses compound and trigger Plex timeouts. Items become permanently unmatched for that scan cycle.

7. **Gap detection timestamp comparison is wrong if using Plex's `updatedAt`** — Plex's `updatedAt` measures when Plex last wrote metadata, not when Stash was updated. Compare `stash.updated_at` against `sync_timestamps.json[scene_id].last_synced_at` (the existing plugin's reference), not against any Plex field.

## Implications for Roadmap

Based on research, the dependency graph is clear: `shared_lib/` must exist before any provider routes; the provider skeleton must work (registration + Plex reachability) before match logic is useful; match must work before metadata serving is meaningful; both must be stable before gap detection adds value.

### Phase 1: Foundation — Monorepo Restructure + shared_lib

**Rationale:** Every subsequent phase depends on `shared_lib/`. Establishing the Docker build context pattern and shared package structure now prevents the monorepo Docker COPY context failure from derailing later phases. This is also when the ratingKey format gets locked in (no forward slashes).
**Delivers:** `shared_lib/` package with path mapper, Stash client, and shared models; Docker build from repo root confirmed working; ratingKey format established as integer scene ID.
**Addresses:** Provider registration (table stakes), Docker container deployment (table stakes)
**Avoids:** GUID slash pitfall, Docker build context pitfall, host.docker.internal on Linux

### Phase 2: Provider HTTP Skeleton + Registration

**Rationale:** Unblocks manual testing against real Plex immediately. Getting PMS to successfully register the provider with stub data validates network topology before any business logic exists. Network issues surface here when the fix cost is low.
**Delivers:** FastAPI app that starts, registers with Plex, and returns well-formed discovery response. Docker container publishable. Plex shows "Stash2Plex" in its agent list.
**Uses:** FastAPI 0.115.14, uvicorn, pydantic BaseSettings, docker-compose with correct build context
**Implements:** `provider/routes/discovery.py`, `provider/main.py`, `provider/config.py`, `provider/Dockerfile`
**Avoids:** Provider URL reachability pitfall, host.docker.internal Linux config

### Phase 3: Match Endpoint + Path Mapping Engine

**Rationale:** This is the core value proposition. Match is the primary integration point; without it nothing else matters. The path mapping engine is the architectural lynchpin — it must be built and validated here, including startup roundtrip validation.
**Delivers:** Plex can scan files and receive Stash scene IDs back. Path mapping roundtrip validation runs at startup. Filename fallback covers unconfigured mapping. Manual match returns ranked candidates.
**Uses:** `shared_lib/path_mapper.py`, `shared_lib/stash_client.py` (find_scene_by_path, find_scene_by_filename)
**Implements:** `provider/routes/match.py`, path rule config loading from env vars
**Avoids:** Relative path misunderstanding, wrong-direction mapping, 90s timeout (add caching and short Stash timeout here)

### Phase 4: Metadata Serve Route

**Rationale:** Depends on match working — PMS only calls metadata after a successful match. Can only be meaningfully integration-tested with real match results.
**Delivers:** Plex displays full scene metadata: title, date, studio, performers, tags, summary, poster image.
**Uses:** `shared_lib/stash_client.py` (find_scene_by_id), pydantic response models
**Implements:** `provider/routes/metadata.py`, `provider/mappers/plex_response.py`, `provider/routes/images.py`
**Avoids:** Anti-pattern of serving images directly through provider (return Stash URL, let Plex fetch directly)

### Phase 5: Gap Detection

**Rationale:** Enhancement on top of a working core. Real-time gap detection is free (match endpoint already knows "no match"). Scheduled full comparison needs stable match flow to validate results.
**Delivers:** Scan-time gap events logged; scheduled full bi-directional comparison; gap report JSON on shared volume for Stash UI.
**Uses:** APScheduler 3.11.x AsyncIOScheduler, plexapi (existing), `shared_lib/stash_client.py` paginated enumeration
**Implements:** `provider/gap/tracker.py`, APScheduler job in FastAPI lifespan
**Avoids:** Wrong timestamp source (use `sync_timestamps.json` not Plex `updatedAt`), per-item Stash queries during scan (batch or rate-limit)

### Phase 6: Plugin Config Extension

**Rationale:** The existing plugin's reconciliation engine can use the same path mapping rules once `shared_lib/path_mapper.py` exists. Deferred because provider features are the primary v2.0 goal.
**Delivers:** Plugin and provider share path mapping configuration; plugin reconciler uses consistent mapping rules.
**Uses:** `shared_lib/path_mapper.py` (direct import)
**Implements:** Extension to `validation/config.py`, update to `Stash2Plex.yml` plugin manifest

### Phase Ordering Rationale

- `shared_lib/` first because it has zero dependencies and everything else depends on it — changes to shared models after routes are written cascade expensively.
- Provider skeleton before match logic because Plex registration and network reachability must be validated on real infrastructure, not mocked. Network pitfalls caught here are low-cost; caught after match logic exists they require partial rework.
- Match before metadata because PMS only calls metadata after a successful match; metadata cannot be integration-tested without working match.
- Gap detection after core metadata because it builds on the match flow's "no match" signal and requires stable IDs.
- Plugin extension last because the provider is the primary v2.0 deliverable; plugin changes are additive and independent.

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 3 (Match + Path Mapping):** The exact payload Plex sends to the Match endpoint — particularly whether `filename` is always present and what its format is in different Plex library configurations (symlinked paths, UNC paths, mapped drives) — should be verified against a live Plex instance before implementing. Research confidence on the filename hint is MEDIUM.
- **Phase 5 (Gap Detection):** The full bi-directional gap detection has scale concerns (O(n) Stash enumeration, O(m) Plex enumeration). The batch vs. real-time split and token-bucket rate limiting need detailed design before implementation. Stash GraphQL pagination behavior under load is not fully characterized.

Phases with standard patterns (can skip deeper research):
- **Phase 1 (shared_lib foundation):** Pure Python package structure — well-documented, no unknowns.
- **Phase 2 (HTTP skeleton):** FastAPI + Docker deployment is a well-trodden pattern with official documentation.
- **Phase 4 (Metadata serve):** Stash field → Plex field mapping is fully documented in research; straightforward transformation layer.
- **Phase 6 (Plugin extension):** Adding a config field to an existing Pydantic model follows the established pattern in `validation/config.py`.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | FastAPI + Docker is a settled decision; library versions verified against current releases. Performance headroom confirmed adequate for home server scan traffic. |
| Features | MEDIUM-HIGH | Core three-endpoint contract (registration, match, metadata) verified via Plex official docs and reference implementation. Gap detection design is sound. One known active bug: only first Genre array element imported by Plex (unresolved as of February 2026). |
| Architecture | MEDIUM | Plex provider API is beta (PMS 1.43.0+). Core patterns verified via official tmdb-example-provider. Exact Match payload format (especially filename field behavior across library types) has MEDIUM confidence — needs live Plex validation. |
| Pitfalls | HIGH | Nine critical pitfalls identified with specific prevention strategies and phase assignments. Docker networking and GUID format pitfalls are well-documented in community and official sources. |

**Overall confidence:** MEDIUM-HIGH

### Gaps to Address

- **Exact Match endpoint payload format:** The `filename` field in the Match request body — whether it is always present, always relative, and what it looks like across different Plex library types (symlinked paths, UNC paths, mapped drives) — needs validation against a live Plex instance in Phase 3. Design path mapping to degrade gracefully when filename is absent or absolute.
- **Stash GraphQL field names for scene paths:** `files { path }` vs `paths { ... }` field naming needs verification against the local Stash instance's GraphQL playground before implementing the Stash client. Research notes this uncertainty explicitly.
- **Genre array bug:** Active Plex bug where only the first Genre tag is imported. Monitor for fix. If not resolved before Phase 4 ships, implement concatenated single-tag workaround.
- **Image URL accessibility from Plex:** Stash image URLs may require authentication (ApiKey header). Whether Plex can fetch images directly from Stash without auth — or whether the provider must proxy or redirect with auth — needs testing in Phase 4.

## Sources

### Primary (HIGH confidence)
- [plexinc/tmdb-example-provider (GitHub)](https://github.com/plexinc/tmdb-example-provider) — official Plex reference implementation; confirmed endpoint structure, response shapes, GUID format
- [Plex Custom Metadata Provider Announcement](https://forums.plex.tv/t/announcement-custom-metadata-providers/934384/) — official Plex team; confirmed PMS 1.43.0+ requirement, beta status
- [Stash scene.graphql schema](https://github.com/stashapp/stash/blob/develop/graphql/schema/types/scene.graphql) — authoritative Stash scene field definitions
- [Stash ApiKey PR #1241](https://github.com/stashapp/stash/pull/1241) — confirmed ApiKey header authentication
- [FastAPI Docker Deployment Guide](https://fastapi.tiangolo.com/deployment/docker/) — confirmed uvicorn + slim base image production pattern
- [APScheduler 3.x Documentation](https://apscheduler.readthedocs.io/en/3.x/userguide.html) — AsyncIOScheduler + FastAPI lifespan integration

### Secondary (MEDIUM confidence)
- [Plex Developer API Docs](https://developer.plex.tv/pms/) — official but beta; provider spec may change
- [Plex forum page 2 community discussion](https://forums.plex.tv/t/announcement-custom-metadata-providers/934384?page=2) — 90s timeout, relative filename hint, no auth: developer community observations
- [Drewpeifer/plex-meta-tvdb (GitHub)](https://github.com/Drewpeifer/plex-meta-tvdb) — community provider showing real MediaContainer response structure
- [Genre array bug report](https://forums.plex.tv/t/only-first-genre-is-imported-when-matching-or-metadata-requested-from-a-custom-metadata-providers/936554) — active February 2026, unresolved
- [stashapp-tools PyPI](https://pypi.org/project/stashapp-tools/) — version 0.2.59 current (Sep 2025)
- [Docker host.docker.internal Linux behavior](https://wikitwist.com/docker-host-networking-explained-differences-on-linux-macos-and-windows/) — confirmed platform-specific behavior

### Tertiary (LOW confidence / needs validation)
- Stash GraphQL `findScenesByPathRegex` query — confirmed via community documentation but exact field names need verification against local Stash instance
- Go vs FastAPI performance benchmarks — consistent direction but I/O-bound workload narrows gap significantly

---
*Research completed: 2026-02-23*
*Ready for roadmap: yes*

# Architecture Research: Plex Metadata Provider Integration

**Domain:** HTTP metadata provider service + Stash plugin monorepo (v2.0)
**Researched:** 2026-02-23
**Confidence:** MEDIUM — Plex provider API is beta (PMS 1.43.0+); core patterns verified via official example repos and forum announcements

---

## System Overview

v2.0 adds a long-running HTTP service (`provider/`) alongside the existing short-lived plugin (`Stash2Plex.py`). They share code through a `shared/` package that lives in the plugin root.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          USER ENVIRONMENT                                │
│                                                                          │
│   ┌────────────────────────┐        ┌────────────────────────────┐      │
│   │   Stash Application    │        │   Plex Media Server        │      │
│   │   (existing)           │        │   (PMS 1.43.0+)            │      │
│   │                        │        │                            │      │
│   │  Stash2Plex Plugin     │        │  Settings → Agents →       │      │
│   │  (event-driven, short- │        │  Add Custom Provider       │      │
│   │   lived per invocation)│        │  URL: http://provider:8080 │      │
│   └────────────┬───────────┘        └────────────┬───────────────┘      │
│                │                                  │                      │
│                │  GraphQL (pull)                  │  HTTP (provider API) │
│                ▼                                  ▼                      │
│   ┌────────────────────────────────────────────────────────────────┐    │
│   │              provider/ (Docker container, long-running)        │    │
│   │                                                                │    │
│   │  FastAPI HTTP server                                           │    │
│   │  ├── GET /                    MediaProvider discovery          │    │
│   │  ├── POST /library/metadata/matches   Match → Stash lookup     │    │
│   │  ├── GET /library/metadata/{id}       Full metadata serve      │    │
│   │  └── GET /library/metadata/{id}/images  Image proxy           │    │
│   │                                                                │    │
│   │  ┌─────────────────┐  ┌──────────────────┐  ┌─────────────┐  │    │
│   │  │  path_mapper.py │  │  stash_client.py  │  │ gap_tracker │  │    │
│   │  │  (regex engine) │  │  (GraphQL client) │  │ .py         │  │    │
│   │  └─────────────────┘  └──────────────────┘  └─────────────┘  │    │
│   └────────────────────────────────────────────────────────────────┘    │
│                │                                                         │
│                │  GraphQL + HTTP                                         │
│                ▼                                                         │
│   ┌────────────────────────┐                                             │
│   │   Stash Server         │                                             │
│   │   :9999/graphql        │                                             │
│   └────────────────────────┘                                             │
└─────────────────────────────────────────────────────────────────────────┘
```

### Coexistence: Push + Pull Models

The v1.x plugin (push) and v2.0 provider (pull) are **complementary, not competing**:

| Trigger | Component | Flow |
|---------|-----------|------|
| Scene updated in Stash | Plugin (push) | Hook → enqueue → worker → Plex API write |
| Plex library scan | Provider (pull) | PMS → HTTP match → Stash GraphQL → serve metadata |
| Gap detected | Either | Plugin: existing reconciler enqueues; Provider: real-time during scan |

---

## How Plex Discovers and Calls the Provider

**Registration** (MEDIUM confidence — verified via Plex forum announcement and tmdb-example-provider):

1. User opens PMS → Settings → Agents → Add Custom Provider
2. Enters the provider base URL (e.g., `http://192.168.1.100:8080`)
3. PMS performs a GET to the base URL to fetch the `MediaProvider` definition
4. PMS stores the provider and calls it during library scans

**Provider discovery response** — what the root endpoint must return:

```json
{
  "MediaContainer": {
    "MediaProvider": [{
      "identifier": "tv.plex.agents.custom.stash2plex",
      "title": "Stash2Plex",
      "version": "2.0.0",
      "Types": {
        "MediaType": [{
          "type": "1",
          "title": "Movie",
          "Scheme": [{"key": "stash2plex"}],
          "Feature": [
            {"type": "match", "key": "/library/metadata/matches"},
            {"type": "metadata", "key": "/library/metadata"},
            {"type": "images", "key": "/library/metadata/{id}/images"}
          ]
        }]
      }
    }]
  }
}
```

**Match flow** (what PMS sends to provider during scan):

```
PMS scans file: /media/Adult/Studio/2024-01-01_scene_title.mp4
    ↓
POST /library/metadata/matches
Body: {
  "type": 1,
  "title": "scene_title",
  "year": 2024,
  "filename": "2024-01-01_scene_title.mp4",
  "manual": 0
}
    ↓
Provider: apply regex path map to reconstruct Stash path
Provider: query Stash GraphQL findScenes(path: ...)
Provider: return candidate match with ratingKey = stash_scene_id
    ↓
PMS stores ratingKey, calls GET /library/metadata/{stash_scene_id}
Provider: query Stash for full scene, return formatted metadata
```

**Authentication:** Currently unauthenticated (beta limitation confirmed by Plex team). Providers hosted locally on Docker do not need auth for now. Future versions will add auth.

**Timeout:** PMS has a 90-second timeout for provider requests. Match + Stash GraphQL roundtrip must complete within this budget.

**File path information passed:** PMS passes the filename (not full path) and relative path to library root. This is why the **regex path mapper** must reconstruct the full Stash path from PMS library base + relative path.

---

## Recommended Monorepo Structure

```
Stash2Plex/                          # repo root (existing plugin)
├── Stash2Plex.py                    # existing entry point (unchanged)
├── Stash2Plex.yml                   # existing plugin manifest
├── requirements.txt                 # existing plugin deps
│
├── plex/                            # existing — plex API wrappers
├── worker/                          # existing — queue worker
├── sync_queue/                      # existing — queue ops
├── reconciliation/                  # existing — gap detection (plugin side)
├── validation/                      # existing — Pydantic config + validators
├── hooks/                           # existing — Stash hook handlers
├── shared/                          # existing shared utilities (log.py)
│   └── log.py
│
├── shared_lib/                      # NEW — code shared between plugin + provider
│   ├── __init__.py
│   ├── path_mapper.py               # Bidirectional regex path mapping engine
│   ├── stash_client.py              # Stash GraphQL client (http + ApiKey)
│   └── models.py                    # Shared data models (StashScene, etc.)
│
└── provider/                        # NEW — Plex metadata provider service
    ├── Dockerfile
    ├── docker-compose.yml
    ├── requirements.txt             # FastAPI, httpx, pydantic — no plugin deps
    ├── pyproject.toml
    ├── main.py                      # FastAPI app entry point
    ├── config.py                    # Provider config (env vars via Pydantic)
    ├── routes/
    │   ├── __init__.py
    │   ├── discovery.py             # GET / → MediaProvider response
    │   ├── match.py                 # POST /library/metadata/matches
    │   ├── metadata.py              # GET /library/metadata/{id}
    │   └── images.py                # GET /library/metadata/{id}/images
    ├── mappers/
    │   ├── __init__.py
    │   └── plex_response.py         # Stash scene → Plex MediaContainer format
    ├── gap/
    │   ├── __init__.py
    │   └── tracker.py               # Gap tracking (scan-time + scheduled)
    └── tests/
        ├── test_discovery.py
        ├── test_match.py
        ├── test_metadata.py
        └── test_path_mapper.py
```

### Structure Rationale

- **`shared_lib/`** (not `shared/`): The existing `shared/` module is plugin-specific. A clearly named `shared_lib/` avoids confusion and maps to `pip install -e ../shared_lib` in the provider Dockerfile.
- **`provider/requirements.txt`** separate from plugin `requirements.txt`: Provider uses FastAPI and httpx; plugin uses plexapi and persist-queue. No overlap. Don't mix.
- **`provider/` as self-contained service**: Has its own `Dockerfile`, config, and can be deployed independently. The only shared dependency is `shared_lib/` installed via path.
- **`provider/routes/`**: One file per endpoint group. FastAPI routers make this clean to compose.
- **`provider/mappers/`**: Transformation layer — keeps routes thin and testable independently.
- **`provider/gap/`**: Gap detection logic for the provider side (scan-time observation of what Plex couldn't match, separate from the plugin's reconciler).

---

## Component Responsibilities

### New Components

| Component | Responsibility | Communicates With |
|-----------|---------------|-------------------|
| `provider/main.py` | FastAPI app init, router assembly, lifespan | All routes |
| `provider/config.py` | Env var config (Pydantic BaseSettings) | All provider components |
| `provider/routes/discovery.py` | Serve MediaProvider definition to PMS | None (static) |
| `provider/routes/match.py` | Handle PMS match requests → Stash lookup | `shared_lib/path_mapper`, `shared_lib/stash_client` |
| `provider/routes/metadata.py` | Serve full scene metadata by ID | `shared_lib/stash_client`, `provider/mappers` |
| `provider/routes/images.py` | Proxy image URLs from Stash | `shared_lib/stash_client` |
| `provider/mappers/plex_response.py` | Transform StashScene → Plex MediaContainer | `shared_lib/models` |
| `provider/gap/tracker.py` | Track unmatched items, schedule full comparison | `shared_lib/stash_client` |
| `shared_lib/path_mapper.py` | Bidirectional regex path mapping | None |
| `shared_lib/stash_client.py` | GraphQL client for Stash API | Stash :9999/graphql |
| `shared_lib/models.py` | Shared data models | Both plugin and provider |

### Existing Components: Reused vs. Unchanged

| Component | v2.0 Status | Notes |
|-----------|-------------|-------|
| `plex/client.py` | Unchanged | Plugin push model only |
| `plex/matcher.py` | Unchanged | Plugin push model only |
| `worker/processor.py` | Unchanged | Push model only |
| `reconciliation/engine.py` | Unchanged | Plugin-side gap detection |
| `validation/config.py` | Extend | Add `path_mappings` config field |
| `shared/log.py` | Plugin-only | Provider uses standard logging |
| Stash GraphQL usage | Extracted | Move from inline calls in engine.py to `shared_lib/stash_client.py` |

The reconciliation engine already queries Stash GraphQL inline via `stashapi`. The `shared_lib/stash_client.py` is a clean reimplementation for the provider using `httpx` (async-capable, no stashapi dependency), with the plugin continuing to use `stashapi` via its existing pattern.

---

## Architectural Patterns

### Pattern 1: MediaProvider Discovery Endpoint

**What:** Plex calls the base URL to get a static JSON description of the provider's capabilities. This is the handshake.

**When to use:** Always — this is required for PMS to know what endpoints to call.

**Implementation:**

```python
# provider/routes/discovery.py
from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()

MEDIA_PROVIDER = {
    "MediaContainer": {
        "MediaProvider": [{
            "identifier": "tv.plex.agents.custom.stash2plex",
            "title": "Stash2Plex",
            "version": "2.0.0",
            "Types": {
                "MediaType": [{
                    "type": "1",
                    "title": "Movie",
                    "Scheme": [{"key": "stash2plex"}],
                    "Feature": [
                        {"type": "match", "key": "/library/metadata/matches"},
                        {"type": "metadata", "key": "/library/metadata"},
                        {"type": "images", "key": "/library/metadata/{id}/images"},
                    ]
                }]
            }
        }]
    }
}

@router.get("/")
async def discovery():
    return JSONResponse(content=MEDIA_PROVIDER)
```

**Trade-offs:** Static response — no auth complexity. Plex caches this, so changes require PMS to re-fetch (remove and re-add the provider URL).

---

### Pattern 2: Regex Path Mapping Engine

**What:** A bidirectional regex engine that transforms paths from PMS path space to Stash path space and vice versa. This is the core of the match feature.

**Why it's needed:** PMS and Stash see different paths to the same file. PMS might see `/media/Adult/scene.mp4` while Stash sees `/nas/content/Adult/scene.mp4`. A simple prefix swap is insufficient when path structures differ.

**Design:** A list of ordered rules, each with a `from_pattern` (regex) and `to_pattern` (replacement). Applied in order, first match wins. Bidirectional: PMS→Stash and Stash→PMS rules.

**Implementation:**

```python
# shared_lib/path_mapper.py
import re
from dataclasses import dataclass
from typing import Optional

@dataclass
class PathRule:
    """Single bidirectional path mapping rule."""
    from_pattern: str      # regex applied to source path
    to_pattern: str        # replacement string (supports \1, \2 groups)
    direction: str         # "plex_to_stash" | "stash_to_plex" | "both"

class PathMapper:
    def __init__(self, rules: list[PathRule]):
        self._rules = rules
        self._compiled = [
            (re.compile(r.from_pattern), r.to_pattern, r.direction)
            for r in rules
        ]

    def plex_to_stash(self, plex_path: str) -> Optional[str]:
        """Map a PMS-visible path to Stash path space."""
        for pattern, replacement, direction in self._compiled:
            if direction in ("plex_to_stash", "both"):
                if pattern.search(plex_path):
                    return pattern.sub(replacement, plex_path)
        return None  # No mapping found — fallback to filename search

    def stash_to_plex(self, stash_path: str) -> Optional[str]:
        """Map a Stash path to PMS path space (for gap detection)."""
        for pattern, replacement, direction in self._compiled:
            if direction in ("stash_to_plex", "both"):
                if pattern.search(stash_path):
                    return pattern.sub(replacement, stash_path)
        return None
```

**Configuration** (in `provider/.env` / docker env):

```
PATH_MAPPINGS='[
  {"from_pattern": "^/media/", "to_pattern": "/nas/content/", "direction": "plex_to_stash"},
  {"from_pattern": "^/nas/content/Adult/(.+)", "to_pattern": "/media/Adult/\1", "direction": "stash_to_plex"}
]'
```

**Trade-offs:**
- Pro: Handles complex multi-segment remaps that prefix swap cannot
- Pro: First-match-wins is predictable and debuggable
- Con: User-configured regex is a footgun — needs clear error messages when no rule matches
- Con: Must be tested against actual path pairs during setup

---

### Pattern 3: Stash GraphQL Client (httpx, async)

**What:** Thin async GraphQL client for Stash's `/graphql` endpoint using `httpx`.

**Why not stashapi:** The `stashapp-tools` package (`stashapi`) is designed for the plugin environment (auto-installs via pip, not suitable for Docker service). The provider needs a clean dependency. `httpx` is the natural async HTTP client for FastAPI services.

**Authentication:** Stash uses `ApiKey` header (JWT). Verified via Stash pull request #1241 and community documentation.

**Implementation:**

```python
# shared_lib/stash_client.py
import httpx
from typing import Any, Optional

FIND_SCENE_BY_PATH = """
query FindSceneByPath($path: String!) {
  findScenes(
    scene_filter: { path: { value: $path, modifier: EQUALS } }
    filter: { per_page: 1 }
  ) {
    scenes {
      id
      title
      date
      details
      studio { name }
      performers { name }
      tags { name }
      files { path }
      paths { screenshot }
      stash_ids { stash_id endpoint }
    }
  }
}
"""

FIND_SCENE_BY_ID = """
query FindScene($id: ID!) {
  findScene(id: $id) {
    id
    title
    date
    details
    studio { name }
    performers { name }
    tags { name }
    files { path }
    paths { screenshot }
    stash_ids { stash_id endpoint }
  }
}
"""

class StashClient:
    def __init__(self, stash_url: str, api_key: Optional[str] = None):
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["ApiKey"] = api_key
        self._client = httpx.AsyncClient(
            base_url=stash_url,
            headers=headers,
            timeout=30.0,
        )

    async def find_scene_by_path(self, path: str) -> Optional[dict]:
        result = await self._graphql(FIND_SCENE_BY_PATH, {"path": path})
        scenes = result.get("findScenes", {}).get("scenes", [])
        return scenes[0] if scenes else None

    async def find_scene_by_id(self, scene_id: str) -> Optional[dict]:
        result = await self._graphql(FIND_SCENE_BY_ID, {"id": scene_id})
        return result.get("findScene")

    async def _graphql(self, query: str, variables: dict) -> dict[str, Any]:
        response = await self._client.post(
            "/graphql",
            json={"query": query, "variables": variables}
        )
        response.raise_for_status()
        data = response.json()
        if "errors" in data:
            raise RuntimeError(f"Stash GraphQL error: {data['errors']}")
        return data.get("data", {})

    async def close(self):
        await self._client.aclose()
```

**Trade-offs:**
- Pro: No stashapi dependency in provider service
- Pro: Async — plays well with FastAPI's event loop
- Con: Manual GraphQL query strings — must track if Stash schema changes
- Mitigation: Keep queries in constants, add schema version check on startup

---

### Pattern 4: Match Route — Path Mapping + Stash Lookup

**What:** The POST /library/metadata/matches handler. This is the primary integration point where PMS asks "what is this file?"

**Two-stage lookup:**
1. Regex path map PMS path → Stash path, query by path (HIGH confidence match)
2. If no path match → query by filename/title (LOW confidence match, manual review)

```python
# provider/routes/match.py
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()

@router.post("/library/metadata/matches")
async def match(request: Request):
    body = await request.json()
    filename = body.get("filename", "")
    title = body.get("title", "")
    year = body.get("year")

    path_mapper: PathMapper = request.app.state.path_mapper
    stash: StashClient = request.app.state.stash_client

    # Stage 1: Path-based match (reconstruct Stash path from PMS hints)
    # PMS passes filename; we need the library base path from config
    stash_path = path_mapper.plex_to_stash(filename)
    scene = None
    if stash_path:
        scene = await stash.find_scene_by_path(stash_path)

    # Stage 2: Filename/title fallback
    if not scene:
        scene = await stash.find_scene_by_filename(filename)

    if not scene:
        return JSONResponse(content={"MediaContainer": {"size": 0, "Metadata": []}})

    return JSONResponse(content={
        "MediaContainer": {
            "size": 1,
            "Metadata": [{
                "ratingKey": str(scene["id"]),
                "guid": f"stash2plex://{scene['id']}",
                "type": "movie",
                "title": scene.get("title") or filename,
                "year": int(scene["date"][:4]) if scene.get("date") else None,
            }]
        }
    })
```

**Trade-offs:**
- Pro: Path-based match is deterministic, no false positives
- Pro: Filename fallback ensures coverage when path mapping misconfigured
- Con: PMS passes filename only (not full path) — provider must know library base paths to reconstruct full path
- Mitigation: Configure `PLEX_LIBRARY_PATHS` env var in Docker; provider prepends when mapping

---

### Pattern 5: Stash Scene → Plex Metadata Mapping

**What:** Transform Stash's scene data model into the Plex MediaContainer format.

**Key mappings:**

| Stash Field | Plex Field | Notes |
|-------------|-----------|-------|
| `id` | `ratingKey` | String — PMS uses this as the identifier |
| `title` | `title` | Direct |
| `date` | `originallyAvailableAt` | Format: YYYY-MM-DD |
| `details` | `summary` | Direct |
| `studio.name` | `studio` | String |
| `performers[].name` | `Role[].tag` | Cast members |
| `tags[].name` | `Genre[].tag` | Genre tags |
| `paths.screenshot` | `thumb` | Poster image URL |
| `rating100` | `rating` | Divide by 10 for 0-10 scale |

```python
# provider/mappers/plex_response.py

def scene_to_metadata(scene: dict, stash_base_url: str) -> dict:
    """Transform Stash scene dict into Plex Metadata object."""
    metadata = {
        "ratingKey": str(scene["id"]),
        "key": f"/library/metadata/{scene['id']}",
        "guid": f"stash2plex://{scene['id']}",
        "type": "movie",
        "title": scene.get("title") or "Untitled",
        "summary": scene.get("details") or "",
    }

    if scene.get("date"):
        metadata["originallyAvailableAt"] = scene["date"]
        metadata["year"] = int(scene["date"][:4])

    if scene.get("studio"):
        metadata["studio"] = scene["studio"]["name"]

    if scene.get("performers"):
        metadata["Role"] = [
            {"tag": p["name"]} for p in scene["performers"]
        ]

    if scene.get("tags"):
        metadata["Genre"] = [
            {"tag": t["name"]} for t in scene["tags"]
        ]

    if scene.get("paths", {}).get("screenshot"):
        # Proxy through provider or serve direct Stash URL
        metadata["thumb"] = f"{stash_base_url}{scene['paths']['screenshot']}"

    return metadata
```

---

### Pattern 6: Provider Config (Pydantic BaseSettings + env vars)

**What:** All provider configuration via environment variables — no config file parsing, no YAML. Docker Compose sets env vars.

```python
# provider/config.py
from pydantic_settings import BaseSettings
from typing import Optional
import json

class ProviderConfig(BaseSettings):
    # Stash connection
    stash_url: str                    # e.g., http://stash:9999
    stash_api_key: Optional[str] = None

    # Provider identity
    provider_id: str = "tv.plex.agents.custom.stash2plex"
    provider_title: str = "Stash2Plex"
    provider_version: str = "2.0.0"

    # Path mapping (JSON array of rules)
    path_mappings_json: str = "[]"

    # Gap detection
    gap_check_interval_hours: int = 24

    # Logging
    log_level: str = "INFO"

    @property
    def path_mappings(self) -> list[dict]:
        return json.loads(self.path_mappings_json)

    class Config:
        env_file = ".env"
```

---

### Pattern 7: Docker Compose Setup

**What:** Provider runs as a Docker service alongside Stash. Single `docker-compose.yml` in `provider/`.

```yaml
# provider/docker-compose.yml
services:
  stash2plex-provider:
    build: .
    ports:
      - "8080:8080"
    environment:
      - STASH_URL=http://host.docker.internal:9999
      - STASH_API_KEY=${STASH_API_KEY}
      - PATH_MAPPINGS_JSON=${PATH_MAPPINGS_JSON}
      - LOG_LEVEL=INFO
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/"]
      interval: 30s
      timeout: 10s
      retries: 3
```

```dockerfile
# provider/Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install shared_lib from parent directory
COPY ../shared_lib /app/shared_lib
RUN pip install -e /app/shared_lib

# Install provider dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
```

**Trade-offs:**
- Pro: Standard, well-understood deployment pattern
- Pro: `host.docker.internal` resolves to host — works for Stash on same machine
- Con: Docker build context must include `shared_lib/` from parent — `COPY ../shared_lib` requires running `docker build` from repo root, not `provider/`
- Mitigation: `docker-compose.yml` sets `build.context: ..` and `dockerfile: provider/Dockerfile`

---

## Data Flows

### Match Request Flow (Scan Time)

```
[PMS scans /media/Adult/2024-01-01_title.mp4]
    ↓
POST /library/metadata/matches
{filename: "2024-01-01_title.mp4", title: "title", year: 2024}
    ↓
[PathMapper.plex_to_stash("2024-01-01_title.mp4")]
    │
    ├── Rule match found → reconstructed_path = "/nas/content/Adult/2024-01-01_title.mp4"
    │   └── StashClient.find_scene_by_path(reconstructed_path)
    │           └── GraphQL: findScenes(path == reconstructed_path)
    │               ├── Found → return {ratingKey: "42", title: "...", ...}
    │               └── Not found → fall through to filename search
    │
    └── No rule match → StashClient.find_scene_by_filename("2024-01-01_title.mp4")
            └── GraphQL: findScenes(path contains filename)
                ├── Found (1 result) → return match
                └── Found (>1 result) → return all as candidates (manual selection)
                └── Not found → return empty MediaContainer
    ↓
[PMS stores ratingKey for matched item]
[gap/tracker.py records unmatched items]
```

### Metadata Serve Flow (After Match)

```
[PMS requests full metadata]
    ↓
GET /library/metadata/42
    ↓
[StashClient.find_scene_by_id("42")]
    └── GraphQL: findScene(id: "42")
        └── Returns full scene with performers, tags, studio, date, paths
    ↓
[plex_response.scene_to_metadata(scene, stash_base_url)]
    └── Transform → Plex MediaContainer format
    ↓
[Return JSON to PMS]
[PMS writes metadata to library]
```

### Gap Detection Flow (Provider Side)

The provider observes matches in real-time. Items that return empty match results are candidates for gaps:

```
[During scan — match request returns empty]
    ↓
[gap/tracker.py.record_unmatched(filename, plex_library_path)]
    └── Stored in-memory (small footprint during scan)
    ↓
[Scan complete — PMS stops sending match requests]
    ↓
[gap/tracker.py periodic job (every gap_check_interval_hours)]
    └── For each unmatched item:
        └── Does Stash have a scene with this filename? (GraphQL)
            ├── YES → Stash has it, Plex couldn't match → real gap
            │   └── Log + expose via /gaps endpoint (for plugin to query)
            └── NO → Stash doesn't have it either → not a gap
```

**Integration with plugin gap detection:**
- Plugin's `reconciliation/engine.py` continues its scheduled gap detection independently
- Provider gap tracker focuses on scan-time misses (different perspective)
- Together they give comprehensive gap visibility

---

## Build Order (Dependency-Based)

### Phase 1: `shared_lib/` Foundation

**Goal:** Extractable, testable code that both plugin and provider use.

**Components:**
1. `shared_lib/stash_client.py` — async httpx GraphQL client
2. `shared_lib/path_mapper.py` — bidirectional regex engine
3. `shared_lib/models.py` — shared data models

**Dependencies:** None (pure Python, no Plex or Stash dependency)
**Why first:** Both plugin changes and provider depend on this. Testable in isolation.

---

### Phase 2: Provider HTTP Skeleton

**Goal:** FastAPI app that starts, responds to discovery, and returns well-formed Plex responses — even with stub data.

**Components:**
1. `provider/main.py` — FastAPI app, router assembly, lifespan (StashClient init/close)
2. `provider/config.py` — Pydantic BaseSettings from env
3. `provider/routes/discovery.py` — static MediaProvider response
4. `provider/Dockerfile` + `docker-compose.yml`

**Dependencies:** Phase 1 (config uses shared_lib models)
**Why second:** Unblocks manual testing against real PMS immediately. Can point PMS at stub provider to verify registration works before match logic exists.

---

### Phase 3: Match Route + Path Mapper Integration

**Goal:** PMS can send a match request and get back a Stash scene ID.

**Components:**
1. `provider/routes/match.py` — POST handler with path mapper + Stash lookup
2. Path mapper config loading from env
3. `shared_lib/stash_client.py` — `find_scene_by_path` + `find_scene_by_filename`

**Dependencies:** Phase 1 (stash_client, path_mapper), Phase 2 (app state)
**Why third:** This is the core value — match is required before metadata serving is useful.

---

### Phase 4: Metadata Serve Route

**Goal:** PMS can fetch full scene metadata after a successful match.

**Components:**
1. `provider/routes/metadata.py` — GET /library/metadata/{id}
2. `provider/mappers/plex_response.py` — Stash scene → Plex format
3. `provider/routes/images.py` — image proxy/redirect

**Dependencies:** Phase 3 (needs match working to know what IDs PMS will request)
**Why fourth:** Can only meaningfully test with real matches working.

---

### Phase 5: Gap Tracker

**Goal:** Provider observes scan-time misses and exposes gap data.

**Components:**
1. `provider/gap/tracker.py` — in-memory + periodic persistence
2. Optional: expose `/gaps` endpoint for plugin to query

**Dependencies:** Phase 4 (needs full match + metadata flow working to distinguish "no match" from "error")
**Why fifth:** Gap detection is enhancement functionality — core metadata serving must work first.

---

### Phase 6: Plugin Integration (Path Mapping Config)

**Goal:** Plugin's `validation/config.py` understands path mapping config so the plugin's existing reconciler can use the same mapping rules.

**Components:**
1. Add `path_mappings` to `Stash2PlexConfig` (list of mapping rules)
2. Plugin's reconciler uses `PathMapper` for Stash→Plex path reconstruction
3. Update `Stash2Plex.yml` with path_mappings setting

**Dependencies:** Phase 1 (shared_lib/path_mapper)
**Why last:** Plugin changes can be done independently; provider features are the primary goal of v2.0.

---

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| Plex Media Server | HTTP (PMS calls provider) | Provider is passive responder; no Plex API calls from provider |
| Stash GraphQL | httpx POST to /graphql | `ApiKey` header auth; async |
| Docker networking | `host.docker.internal` | Stash on host, provider in container |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| Plugin ↔ shared_lib | Direct Python import | `shared_lib/` installed as editable package in plugin .venv |
| Provider ↔ shared_lib | Direct Python import | Installed via Docker build COPY + pip -e |
| Provider ↔ PMS | HTTP/JSON | PMS initiates all requests; provider never calls PMS |
| Provider gap ↔ Plugin reconciler | No direct coupling | Independent gap detection perspectives; future: provider exposes `/gaps` API |

---

## Scaling Considerations

This is a single-user home server setup. Scale means: "handles concurrent PMS scan requests without blocking."

| Concern | At 1 user (home server) | Notes |
|---------|------------------------|-------|
| Concurrent match requests | FastAPI async handles naturally | PMS sends multiple concurrent match requests during scan |
| Stash GraphQL rate limits | None documented | Stash has no rate limits; home server OK |
| Match latency | Target < 5s (within 90s PMS timeout) | Path map + 1 GraphQL call is typically < 500ms |
| Image serving | Proxy redirect to Stash URL is sufficient | Don't buffer images in provider |

---

## Anti-Patterns

### Anti-Pattern 1: Importing `plexapi` or `stashapi` in Provider

**What people might do:** Reuse the plugin's `plexapi` wrapper or `stashapi` client in the provider service.

**Why it's wrong:**
- `plexapi` is for Plex API writes (the push model) — the provider never writes to Plex
- `stashapi` auto-installs packages and uses plugin-specific patterns; not suitable for a Docker service
- Creates unnecessary coupling between provider and plugin dependency trees

**Do this instead:** `shared_lib/stash_client.py` using `httpx` — minimal, async, Docker-friendly.

---

### Anti-Pattern 2: Serving Images Directly from Provider

**What people might do:** Fetch scene images from Stash and stream them through the provider to PMS.

**Why it's wrong:**
- Large binary data in the request path blocks FastAPI workers
- Stash already has authenticated image endpoints — proxy adds zero value
- Provider could OOM on large libraries during scan

**Do this instead:** Return Stash image URLs directly in the Plex metadata response. If Stash requires auth, configure PMS to access images via Stash's session token, or expose images via a redirect endpoint.

---

### Anti-Pattern 3: Writing Plex Metadata from Provider

**What people might do:** Have the provider also write metadata back to Plex (e.g., via plexapi) when serving metadata.

**Why it's wrong:**
- Provider is a read-only responder — PMS reads from it; PMS writes to its own database
- Creates a two-writer conflict with the v1.x push plugin
- Violates the out-of-scope constraint: no Plex → Stash write-back

**Do this instead:** Provider only responds to PMS HTTP requests. All Plex metadata writes come from PMS consuming provider responses, or from the plugin's push model. Never both simultaneously.

---

### Anti-Pattern 4: Monolithic Path Mapper (One Mega-Regex)

**What people might do:** Build a single complex regex to handle all path transformations at once.

**Why it's wrong:**
- Path mappings differ per Plex library (Adult library vs. regular movies may have different roots)
- One mega-regex is undebuggable when it fails
- Config becomes impenetrable for users

**Do this instead:** Ordered list of simple rules, first-match-wins. Each rule is independently testable. Users can add, remove, or reorder rules without understanding the others.

---

### Anti-Pattern 5: Sharing State Between Plugin and Provider via Filesystem

**What people might do:** Have the provider read/write the plugin's SQLite queue or JSON state files.

**Why it's wrong:**
- Plugin runs on host; provider runs in Docker — filesystem not shared without explicit volume mounts
- Race conditions if both write to same files concurrently
- Tight coupling: breaking change in one breaks the other

**Do this instead:** Provider has independent state. Gap data is exposed via an HTTP endpoint that the plugin optionally queries. Loose coupling, explicit interface.

---

## Sources

**Plex Provider API:**
- [Plex Custom Metadata Provider Announcement](https://forums.plex.tv/t/announcement-custom-metadata-providers/934384/) — MEDIUM confidence: official Plex team announcement, beta API
- [Plex Developer API Docs](https://developer.plex.tv/pms/) — MEDIUM confidence: official docs, but provider spec is beta
- [plexinc/tmdb-example-provider](https://github.com/plexinc/tmdb-example-provider) — HIGH confidence: official Plex-authored reference implementation
- [Drewpeifer/plex-meta-tvdb](https://github.com/Drewpeifer/plex-meta-tvdb) — MEDIUM confidence: community implementation showing real endpoint structure

**Stash GraphQL API:**
- [Stash scene.graphql schema](https://github.com/stashapp/stash/blob/develop/graphql/schema/types/scene.graphql) — HIGH confidence: authoritative source
- [Stash API Wiki](https://github.com/stashapp/stash/wiki/API) — HIGH confidence: official auth documentation
- [Stash ApiKey PR #1241](https://github.com/stashapp/stash/pull/1241) — HIGH confidence: ApiKey header authentication implementation

**FastAPI + Docker:**
- [FastAPI Docker docs](https://fastapi.tiangolo.com/deployment/docker/) — HIGH confidence: official FastAPI documentation
- [Python monorepo patterns](https://dev.to/ctrix/mastering-python-monorepos-a-practical-guide-2b4) — MEDIUM confidence: community patterns, multiple sources agree

**Plex Provider Technical Details:**
- Plex forum page 2 discussion — 90s timeout, filename in match body, caching behavior — MEDIUM confidence: Plex team responses in forum thread

---

*Architecture research for: Plex Metadata Provider v2.0 integration*
*Researched: 2026-02-23*
*Key insight: Plex's provider API is REST + JSON; any HTTP server qualifies. The complexity is in the path mapping engine (Plex sees different paths than Stash) and keeping the provider stateless enough to restart cleanly. The plugin and provider share code via `shared_lib/` but have independent deployment and dependency trees.*

# Stack Research: Plex Metadata Provider Service (v2.0)

**Domain:** Plex Custom Metadata Provider HTTP Service + Stash GraphQL Integration
**Researched:** 2026-02-23
**Confidence:** HIGH (framework comparison), MEDIUM (Plex provider API specifics — PMS 1.43 still beta)

---

## Framework Decision: Python (FastAPI) — Recommended

Three languages were evaluated: Python/FastAPI, Go, and Rust. The recommendation is **Python with FastAPI**. Rationale follows.

### Why Not Go

Go would give ~5x more raw throughput and ~100ms lower p99 latency than FastAPI. That performance headroom is irrelevant here: the bottleneck is the round-trip to the Stash GraphQL API and the Plex → provider network hop, not the provider's own compute. The real cost is operational: Go introduces a second language into a codebase with 29,348 lines of Python, 910+ tests, and deeply Python-specific patterns (pydantic models, plexapi, diskcache). The shared code problem is unsolvable cleanly — path mapping rules, config validation, and Stash query logic would need to be duplicated or RPC'd across languages.

### Why Not Rust

Same ops argument, worse DX. Rust compile times (~30–60s clean builds) slow iteration on the provider's XML/JSON response marshaling, which needs to track Plex API changes. Async Rust is powerful but fighting the borrow checker for metadata transformation code is cost without benefit. Rust makes sense for a dedicated, stable, compute-bound service. This isn't that.

### Why Python/FastAPI

- **Shared code is real**: `shared/` directory holds path mapping, Stash GraphQL client, and config validation. All of it is Python. The provider can import it directly — no RPC, no duplication.
- **FastAPI's async model fits the workload**: the provider's hot path is `POST /match` → `await stash_graphql_query()` → return JSON. Pure async I/O. FastAPI + uvicorn handles this well.
- **Pydantic v2 already in requirements.txt**: Plex MediaContainer/Metadata response models get type-safe serialization for free with the library already present.
- **Performance is adequate**: FastAPI handles 1,000–5,000 req/s on a single worker. Plex calls the provider once per file during a library scan — not a hot path. A library of 10,000 items scanned in one batch is ~10,000 requests spread over minutes.
- **Docker isolates the new service**: the provider runs in its own container. Python's startup overhead and GIL are non-issues inside a long-running container.

---

## Recommended Stack

### Core Technologies (NEW — provider service)

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| FastAPI | >=0.115.14 | HTTP framework for Plex provider endpoints | Async-first, Pydantic v2 native, auto-generates OpenAPI spec for the Plex provider interface. Supports both JSON and XML responses. 0.115.14 is latest stable (Jul 2025). |
| uvicorn | >=0.34.0 | ASGI server | FastAPI's recommended production server. Single-worker sufficient; Plex scan traffic is bursty, not sustained high-concurrency. |
| pydantic v2 | >=2.0.0 | Response model validation + serialization | Already in requirements.txt. Models Plex MediaContainer, Metadata, Match response shapes. Type-safe construction prevents malformed responses. |
| httpx | >=0.28.1 | Async HTTP client for Stash GraphQL calls | Replaces requests for async context inside FastAPI. Supports HTTP/1.1 and HTTP/2, connection pooling, timeout control. Used via `AsyncClient` singleton. |
| APScheduler | >=3.11.0 | Scheduled gap detection (full comparison sweep) | AsyncIOScheduler integrates with FastAPI lifespan. Runs bi-directional gap detection on configurable interval (hourly/daily). Thread-safe, persistence optional. |

### Core Technologies (REUSE — existing plugin)

| Technology | Version | Purpose | Why Reuse |
|------------|---------|---------|-----------|
| stashapi | >=0.2.59 | Stash GraphQL client | Already in requirements.txt (stashapp-tools). Provides `findScenes`, `findScene`, title/performer/tag query methods. Use as the provider's Stash query layer. |
| pydantic v2 | >=2.0.0 | Config validation for provider settings | Same config validation pattern as existing plugin. Provider config (provider port, stash URL, path mappings) uses same Pydantic model approach. |
| plexapi | >=4.17.0 | Gap detection — compare Plex items against Stash | Already in requirements.txt. Bi-directional gap detection needs to enumerate Plex library items; plexapi handles this. |
| diskcache | >=5.6.0 | Cache Stash query results in provider | Already in requirements.txt. Cache `findScene` results keyed by path or hash to avoid hammering Stash GraphQL on repeated Plex lookups. 5-minute TTL sufficient. |
| tenacity | >=9.0.0 | Retry Stash GraphQL calls | Already in requirements.txt. Stash GraphQL endpoint can be temporarily unavailable during plugin restarts. Same retry pattern as Plex API calls. |
| re (stdlib) | stdlib | Regex path mapping engine | Python stdlib regex engine. No external dependency. Path mapping rules are user-configured regex patterns with named groups. |

### Supporting Libraries (NEW — provider service)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| python-multipart | >=0.0.20 | Form data parsing (if Plex sends form-encoded match hints) | Only if Plex sends `application/x-www-form-urlencoded` match requests. The Plex API docs show JSON body for match, but older PMS versions may differ. |
| pytest-asyncio | >=0.24.0 | Async test support for provider endpoints | Already in dev requirements or add now. Required for testing async FastAPI routes and async Stash GraphQL client. |
| pytest-httpx | >=0.35.0 | Mock httpx requests in tests | Replaces responses/requests-mock for testing async Stash GraphQL calls inside the provider. Pairs with httpx. |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| Docker + docker-compose | Container build and local dev | Provider runs as separate container alongside Stash. `docker-compose.yml` at repo root wires provider + (optionally) Stash. Multi-stage build: `python:3.11-slim-bookworm` base, ~150MB final image. |
| uv | Python package manager inside Docker | Faster than pip for Docker builds. Optional but recommended if dev team adopts it. Otherwise pip with `--no-cache-dir`. |
| FastAPI built-in `/docs` (Swagger UI) | Provider API documentation | FastAPI auto-generates OpenAPI spec. Useful for verifying Plex provider conformance during development without Plex pointing at the service. |

---

## Plex Provider API Requirements (verified from official docs)

The provider must implement three HTTP endpoints. PMS 1.43.0+ required, API version 1.2.0.

| Endpoint | Method | Purpose | Notes |
|----------|--------|---------|-------|
| `GET /` | GET | Provider registration — returns MediaProvider definition | Returns identifier, title, supported Types, Feature list. Plex fetches this to register the provider. |
| `POST /library/metadata/matches` | POST | Match feature — find Stash scene matching Plex hints | Body: `{type, title, year, filename, guid, ...}`. Returns MediaContainer with Metadata[] ordered by confidence. |
| `GET /library/metadata/{ratingKey}` | GET | Metadata feature — full metadata for a ratingKey | ratingKey must encode enough to reconstruct Stash scene ID (e.g., scene UUID or path hash). Returns MediaContainer with single Metadata object. |
| `GET /library/metadata/{ratingKey}/images` | GET | Image assets (recommended, not required) | Returns poster/backdrop URLs pointing to Stash screenshot/preview endpoints. |

**Response format:** JSON (provider returns `Content-Type: application/json`; Plex requests JSON via `Accept: application/json`). MediaContainer wraps Metadata[].

**Authentication:** PMS sends `X-Plex-Token` header but current spec says "only unauthenticated requests are currently supported" — do NOT validate the token (it belongs to the user's Plex account, not a service account). Accept all requests.

**Supported headers to read:**
- `X-Plex-Language` (IETF tag, e.g. `en-US`) — return localized metadata if available
- `X-Plex-Country` (ISO 3166 country code)
- `X-Plex-Container-Size` / `X-Plex-Container-Start` — pagination (required for `/children`)

**Provider identifier format:** `tv.plex.agents.custom.stash2plex` (alphanumeric + periods only).

---

## Path Mapping Engine

The regex path mapping engine translates Plex file paths (as Plex sees them on the filesystem or via network share) to Stash file paths (as Stash indexes them). This is the critical matching component.

**Recommendation: Python `re` stdlib — no external library needed.**

Pattern: user configures a list of `(pattern, replacement)` tuples in the provider config. The engine applies them in order, stopping on first match.

```python
import re
from typing import Optional

MAPPING_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r'^/mnt/plex/(?P<rest>.+)'), r'/data/stash/\g<rest>'),
    (re.compile(r'^//nas/media/(?P<rest>.+)'), r'/mnt/stash/\g<rest>'),
]

def plex_to_stash_path(plex_path: str) -> Optional[str]:
    for pattern, replacement in MAPPING_RULES:
        if m := pattern.match(plex_path):
            return m.expand(replacement)
    return None  # No mapping found — fall back to filename/hash matching
```

Named groups allow non-trivial remappings (not just prefix swaps). Bidirectional: add separate `stash_to_plex_path()` using inverse rules for gap detection.

**Why not `pathlib` substitution or simple `str.replace`:** regex handles drive-letter normalization, UNC paths, case-insensitive matching on Windows-hosted Plex, and partial path segment replacement. The complexity is justified by real user setups (SMB mounts, Docker volume remaps, NAS paths).

---

## Stash GraphQL Client (in provider)

**Use `stashapi` (stashapp-tools 0.2.59) — do not write a raw GraphQL client.**

stashapp-tools is the official community Python client for Stash's GraphQL API. It provides `find_scene()`, `find_scenes()`, and scene metadata access. Version 0.2.59 (Sep 2025) is current.

For the provider's async context (FastAPI/httpx), wrap stashapi calls in `asyncio.to_thread()` if stashapi is synchronous, or use httpx directly for the two specific queries needed:

```python
# Two queries needed for the provider's match flow:
# 1. Find scene by file path → GET scene metadata
FIND_SCENE_BY_PATH = """
query FindSceneByPath($path: String!) {
  findScenes(scene_filter: { path: { value: $path, modifier: EQUALS } }) {
    scenes {
      id title date details
      performers { name }
      tags { name }
      studio { name }
      files { path }
    }
  }
}
"""

# 2. Find scene by ID (for /library/metadata/{ratingKey} endpoint)
FIND_SCENE_BY_ID = """
query FindSceneById($id: ID!) {
  findScene(id: $id) {
    id title date details rating100
    performers { name }
    tags { name }
    studio { name }
    files { path }
    urls
  }
}
"""
```

**If stashapi's sync client conflicts with async:** use `httpx.AsyncClient` directly with the two GraphQL queries above. This is 50 lines, no dependency on stashapi sync internals.

---

## Docker Setup

**Base image:** `python:3.11-slim-bookworm` — current recommended slim for production FastAPI (confirmed Feb 2026 community consensus).

**Multi-stage build pattern:**

```dockerfile
# Stage 1: dependency install
FROM python:3.11-slim-bookworm AS deps
WORKDIR /app
COPY provider/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Stage 2: runtime
FROM python:3.11-slim-bookworm AS runtime
WORKDIR /app
COPY --from=deps /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY provider/ ./provider/
COPY shared/ ./shared/
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["uvicorn", "provider.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
```

**Why single worker:** Plex scan traffic is bursty in short bursts, not sustained high-concurrency. uvicorn's async event loop handles concurrent requests without multiple workers. Multiple workers complicate APScheduler (gap detection would run N times). Single worker + async is cleaner.

**docker-compose.yml** (monorepo root):

```yaml
services:
  stash2plex-provider:
    build:
      context: .
      dockerfile: provider/Dockerfile
    ports:
      - "8080:8080"
    environment:
      - STASH_URL=http://stash:9999
      - STASH_API_KEY=${STASH_API_KEY}
      - PROVIDER_PORT=8080
    volumes:
      - ./provider/config.yml:/app/config.yml:ro
    restart: unless-stopped
```

The Plex server needs network access to the provider container. In practice: either Plex is also in Docker (same network) or the provider port is published to the host and Plex accesses it via `http://host:8080`.

---

## Monorepo Structure

```
Stash2Plex/                    # existing repo root
├── Stash2Plex.py              # existing plugin (unchanged)
├── worker/                    # existing
├── plex/                      # existing
├── shared/                    # NEW — shared between plugin and provider
│   ├── path_mapping.py        # Regex bidirectional path mapper
│   ├── stash_client.py        # Stash GraphQL query helpers
│   └── models.py              # Shared pydantic models (scene, config)
└── provider/                  # NEW — Plex metadata provider service
    ├── Dockerfile
    ├── requirements.txt
    ├── main.py                # FastAPI app, lifespan, route wiring
    ├── routes/
    │   ├── registration.py    # GET / — MediaProvider definition
    │   ├── match.py           # POST /library/metadata/matches
    │   └── metadata.py        # GET /library/metadata/{ratingKey}
    ├── services/
    │   ├── match_service.py   # Match logic: path map → Stash query → confidence
    │   └── metadata_service.py # Metadata fetch and Plex response assembly
    ├── scheduler.py           # APScheduler gap detection jobs
    └── config.py              # Provider-specific Pydantic config model
```

**Shared code strategy:** `shared/` is a Python package (with `__init__.py`) importable by both the Stash plugin and the provider. The plugin imports it as a sibling package (already in sys.path via Stash plugin loader). The provider Docker image COPYs the `shared/` directory.

---

## Scheduling: Gap Detection

**Use APScheduler 3.x AsyncIOScheduler integrated with FastAPI lifespan.**

APScheduler is already evaluated for v1.5 but rejected because the Stash plugin is not a long-running daemon. The provider service IS a long-running Docker container — the original objection no longer applies.

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from contextlib import asynccontextmanager
from fastapi import FastAPI

scheduler = AsyncIOScheduler()

@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.add_job(
        run_gap_detection,
        trigger="interval",
        hours=config.gap_detection_interval_hours,
        id="gap_detection",
        replace_existing=True,
    )
    scheduler.start()
    yield
    scheduler.shutdown()

app = FastAPI(lifespan=lifespan)
```

**Why APScheduler over `schedule` library:** APScheduler supports asyncio natively (AsyncIOScheduler runs jobs in the same event loop as FastAPI), supports cron/interval/date triggers, and is production-grade. The `schedule` library is synchronous-only and would require a thread, complicating the async architecture. APScheduler 3.11.x is stable and actively maintained (latest: 3.11.2.post1).

**Gap detection architecture:** the scheduled job uses plexapi to enumerate all items in configured Plex libraries, maps each Plex file path to a Stash path via the regex engine, and queries Stash for each scene. Gaps are logged and optionally enqueued into the existing v1.x plugin queue for push-model sync.

---

## Installation

```bash
# provider/requirements.txt (new file)
fastapi>=0.115.14
uvicorn[standard]>=0.34.0
httpx>=0.28.1
APScheduler>=3.11.0
pydantic>=2.0.0
stashapi>=0.2.59
plexapi>=4.17.0
diskcache>=5.6.0
tenacity>=9.0.0

# provider/requirements-dev.txt (new file)
pytest>=8.0.0
pytest-asyncio>=0.24.0
pytest-httpx>=0.35.0
httpx>=0.28.1  # required by pytest-httpx
```

**Existing plugin requirements.txt: unchanged.** The provider runs in a separate Docker container with its own dependency set. No new packages are added to the Stash plugin.

---

## Alternatives Considered

| Category | Recommended | Alternative | When to Use Alternative |
|----------|-------------|-------------|-------------------------|
| HTTP framework | FastAPI | Flask + Blueprints | Never for this project. Flask lacks async-native support; sync Flask with Plex API calls would block during Stash GraphQL lookups. FastAPI's async is not optional here. |
| HTTP framework | FastAPI | Go net/http or Gin | If the team decides to fully decouple the provider from the Python codebase and accept no shared code. Would require duplicating path mapping, config models, and Stash query logic in Go. Not recommended. |
| HTTP framework | FastAPI | Rust Axum | If extreme performance is required (>50,000 req/s). Not justified for Plex scan traffic (hundreds of requests per scan). |
| ASGI server | uvicorn | gunicorn + uvicorn workers | If multiple workers needed (sustained high-concurrency). Single uvicorn worker is preferred to avoid APScheduler running N times per interval. Add gunicorn only if worker count needs to scale. |
| GraphQL client | stashapi (stashapp-tools) | gql 4.0.0 + HTTPXAsyncTransport | If stashapi's sync model is a blocking problem in async context. gql with HTTPXAsyncTransport is a clean async-native GraphQL client. Use if `asyncio.to_thread(stashapi_call)` adds unacceptable latency. |
| GraphQL client | stashapi (stashapp-tools) | Raw httpx POST | For the two specific queries needed (find by path, find by ID). Raw httpx is 50 lines, no extra dep. Recommended if stashapi pulls in unnecessary transitive deps in the provider container. |
| Scheduler | APScheduler | Celery + Redis | Never for this project. Celery requires Redis/RabbitMQ broker. Massively overkill for a single recurring gap-detection job in a single-container service. |
| Scheduler | APScheduler | cron (system) | If provider runs outside Docker (bare metal). System cron is simpler but can't access the FastAPI app context (shared Stash client, config). APScheduler inside the process has direct access. |
| Path mapping | re (stdlib) | pathlib + string ops | For simple prefix-only mappings. Use `pathlib` if all user mappings are guaranteed to be prefix swaps. In practice, SMB/UNC/Docker volume paths need regex. Default to regex. |

---

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| Flask | Synchronous by default. The match endpoint awaits a Stash GraphQL call; Flask would block the entire process during each Plex request. | FastAPI with async def route handlers. |
| Django | 10x more framework than needed. No ORM needed (Stash is the data source). Startup overhead in a lightweight container. | FastAPI. |
| Go (separate service) | Requires duplicating path mapping logic, Stash GraphQL queries, and config parsing in a second language. Shared code via RPC is more complex than the shared Python package approach. | FastAPI + `shared/` Python package. |
| Celery | Requires Redis or RabbitMQ broker. Gap detection is one job on a cron interval — APScheduler handles this with zero infrastructure overhead. | APScheduler AsyncIOScheduler. |
| gql library (as default) | gql 4.0.0 adds a dependency for something stashapi (already required) already provides. Only add gql if stashapi's sync model causes actual problems in async. | stashapi (stashapp-tools), or raw httpx if stashapi sync causes issues. |
| XML response generation | Plex supports JSON (`Accept: application/json`). XML is default but new providers should use JSON. Generating XML in Python requires lxml or ElementTree and is error-prone compared to Pydantic JSON serialization. | FastAPI JSONResponse with Pydantic models. Set `Content-Type: application/json`. |
| gunicorn multi-worker (default) | Multiple uvicorn workers cause APScheduler gap detection to run once per worker per interval. Requires sticky sessions or external state to coordinate. | Single uvicorn worker (`--workers 1`). Scale via multiple container replicas only if scan traffic justifies it (unlikely). |
| SQLite in provider | No persistent state needed in the provider itself. Match results cache → diskcache. Gap detection results → logged + optionally forwarded to plugin queue. No new SQLite tables. | diskcache for response caching, in-memory for transient state. |

---

## Stack Patterns by Variant

**If Stash and Plex are on the same Docker network:**
- Provider container joins same network, accesses Stash via service name (`http://stash:9999`)
- No port exposure needed for Stash → provider calls
- Plex accesses provider via container name or published port

**If Stash is on bare metal (not Docker):**
- Provider container accesses Stash via host IP + port (`http://host.docker.internal:9999` on Mac/Windows, `http://172.17.0.1:9999` on Linux)
- Set `STASH_URL` env var accordingly in docker-compose

**If stashapi sync is a problem in async context:**
- Replace stashapi calls with `await asyncio.to_thread(stashapi.find_scene, scene_id)` first
- If still blocking, replace stashapi with raw `httpx.AsyncClient` POST to Stash GraphQL endpoint
- The two required queries are simple enough to inline (50 lines each)

**If gap detection interval needs to be dynamic:**
- Store APScheduler job ID and use `scheduler.reschedule_job()` on config reload
- Config reload triggered by `POST /admin/reload-config` endpoint (optional, not in MVP)

---

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| FastAPI 0.115.14 | pydantic>=2.0.0 | FastAPI 0.115.x requires pydantic v2. Already in requirements.txt. |
| FastAPI 0.115.14 | uvicorn>=0.34.0 | FastAPI 0.115.x compatible with uvicorn 0.34.x. |
| APScheduler 3.11.x | Python 3.9+ | AsyncIOScheduler requires Python 3.7+. Plugin already requires 3.9+. |
| httpx 0.28.1 | Python 3.8+ | Full async support. Compatible with Python 3.9+ (plugin baseline). |
| pytest-asyncio 0.24.x | pytest 8.x | Requires pytest 8.x. If currently on older pytest, upgrade. |
| pytest-httpx 0.35.x | httpx 0.28.x | Version-matched: pytest-httpx minor version must match httpx minor version. |
| stashapi 0.2.59 | Python 3.9+ | Developed on Python 3.11, maintains 3.9+ compatibility. |

---

## Sources

- [Plex Developer Documentation — Metadata Providers](https://developer.plex.tv/pms/index.html#section/API-Info/Metadata-Providers) — HIGH confidence: official API spec, endpoints, response format verified
- [Plex Custom Metadata Providers Forum Announcement](https://forums.plex.tv/t/announcement-custom-metadata-providers/934384/) — MEDIUM confidence: community confirmation, PMS 1.43.0+ requirement, beta status confirmed
- [plexinc/tmdb-example-provider (GitHub)](https://github.com/plexinc/tmdb-example-provider) — HIGH confidence: official Plex reference implementation (TypeScript/Express), confirms endpoint structure and response shapes
- [Drewpeifer/plex-meta-tvdb (GitHub)](https://github.com/Drewpeifer/plex-meta-tvdb) — MEDIUM confidence: community implementation confirming MediaContainer JSON response format
- [FastAPI Release Notes](https://fastapi.tiangolo.com/release-notes/) — HIGH confidence: 0.115.14 current stable confirmed
- [FastAPI Docker Deployment Guide](https://fastapi.tiangolo.com/deployment/docker/) — HIGH confidence: official uvicorn + slim base image pattern
- [APScheduler 3.x Documentation](https://apscheduler.readthedocs.io/en/3.x/userguide.html) — HIGH confidence: AsyncIOScheduler + FastAPI lifespan integration pattern
- [stashapp-tools PyPI](https://pypi.org/project/stashapp-tools/) — HIGH confidence: version 0.2.59 current (Sep 2025)
- [Stash GraphQL scene.graphql schema (GitHub)](https://github.com/stashapp/stash/blob/develop/graphql/schema/types/scene.graphql) — HIGH confidence: verified scene fields (title, date, performers, tags, studio, files, details)
- [httpx PyPI](https://www.python-httpx.org/) — HIGH confidence: 0.28.1 current, async client confirmed
- [gql 4.0.0 documentation](https://gql.readthedocs.io/en/stable/) — MEDIUM confidence: async alternative if stashapi sync model blocks
- Go vs FastAPI performance benchmarks (multiple sources, 2024–2025) — MEDIUM confidence: consistent 5–12x Go throughput advantage; I/O-bound workload narrows gap significantly

---

*Stack research for: Plex Metadata Provider Service (v2.0)*
*Researched: 2026-02-23*
*Key Recommendation: Python FastAPI (not Go, not Rust) — shared code with existing plugin justifies language consistency over performance headroom. Provider runs in Docker; separation of concerns achieved at container boundary, not language boundary.*

# Feature Research

**Domain:** Plex Custom Metadata Provider + Bi-Directional Gap Detection (v2.0)
**Researched:** 2026-02-23
**Confidence:** MEDIUM-HIGH (API is beta as of PMS 1.43.0; core contract is documented; community edge cases confirmed)

---

## Plex Provider API Contract (Critical Reference)

These are implementation constraints that drive every feature decision.

### Provider Registration

Plex discovers the provider via a single URL in Settings -> Metadata Agents -> Add Provider. The provider responds at its root path (`GET /`) with a `MediaProvider` JSON object:

```json
{
  "MediaProvider": {
    "identifier": "tv.plex.agents.custom.stash2plex",
    "title": "Stash2Plex",
    "version": "1.0.0",
    "Types": [{ "type": "movie", "name": "Movie" }],
    "Feature": [
      { "key": "/match", "type": "match" },
      { "key": "/metadata", "type": "metadata" }
    ]
  }
}
```

Identifier must use prefix `tv.plex.agents.custom.` followed by ASCII letters, numbers, and periods. For Stash scene content, use type 1 (movie) only. No authentication mechanism exists in the provider spec as of February 2026.

Source: Official Plex developer docs + Plex announcement forum thread. Confidence: HIGH.

### Match Endpoint

Plex calls `POST /match` when it needs to resolve a newly scanned file to a metadata record.

**What Plex sends:**

```json
{
  "type": 1,
  "title": "Scene Title",
  "year": 2024,
  "guid": "tv.plex.agents.custom.stash2plex://scene-123",
  "filename": "Videos/Studio/2024-01-15 Scene Title.mp4",
  "manual": 0,
  "includeAdult": 1
}
```

Key fields and their reliability for Stash matching:

| Field | Description | Reliability for Stash |
|-------|-------------|----------------------|
| `type` | Always 1 for movie libraries | Always present |
| `filename` | Relative path from Plex library root | Most reliable — Stash scenes are files |
| `guid` | Present on re-match; format `{identifier}://{ratingKey}` | Reliable when present; absent on first scan |
| `title` | Plex-extracted title from filename — may be dirty | Unreliable; quality suffixes, dates mixed in |
| `year` | Parsed by Plex from filename | Unreliable for adult content with date-naming |
| `manual` | 1 = user-initiated "Fix Match" | When 1, return multiple ranked candidates |
| `includeAdult` | 1 for adult-configured libraries | Present; use as filter signal |

**What provider must return:**

```json
{
  "MediaContainer": {
    "offset": 0,
    "totalSize": 1,
    "identifier": "tv.plex.agents.custom.stash2plex",
    "size": 1,
    "Metadata": [
      {
        "type": "movie",
        "ratingKey": "scene-123",
        "guid": "tv.plex.agents.custom.stash2plex://scene-123",
        "title": "Scene Title",
        "year": 2024,
        "thumb": "https://stash-host/scene/123/screenshot",
        "summary": "Scene description"
      }
    ]
  }
}
```

- `ratingKey` must match `[a-zA-Z0-9_-]+` — valid in URL path, no forward slashes
- Empty `Metadata` array = no match found; Plex leaves item unmatched (not an error)
- 404 or 500 from provider causes Plex errors; always return valid JSON
- `manual=1` responses must return multiple candidates ordered by confidence
- Plex enforces a **90-second timeout** on all provider requests

Source: Official docs + Plex forum community thread. Confidence: HIGH (timeout, ratingKey format, empty response behavior).

### Metadata Endpoint

Plex calls `GET /metadata/{ratingKey}` after a successful match and on subsequent refreshes. This is a GET, not a POST.

**What Plex sends:** Simple GET with ratingKey in URL path. Optional headers: `X-Plex-Language`, `X-Plex-Country`.

**What provider must return:**

```json
{
  "MediaContainer": {
    "size": 1,
    "identifier": "tv.plex.agents.custom.stash2plex",
    "Metadata": [
      {
        "type": "movie",
        "ratingKey": "scene-123",
        "guid": "tv.plex.agents.custom.stash2plex://scene-123",
        "title": "Scene Title",
        "originallyAvailableAt": "2024-01-15",
        "year": 2024,
        "summary": "Scene description from Stash",
        "studio": "Studio Name",
        "contentRating": "X",
        "duration": 3600000,
        "thumb": "https://stash-host/scene/123/screenshot",
        "art": "https://stash-host/scene/123/screenshot",
        "Genre": [{"tag": "tag1"}, {"tag": "tag2"}],
        "Role": [{"tag": "Performer Name", "role": "Actor"}]
      }
    ]
  }
}
```

Required: `ratingKey`, `key`, `guid`, `type`, `title`, `originallyAvailableAt`.

**Known active bug (February 2026, unresolved):** Only the first element of the `Genre` array is imported by Plex. Other array fields (`Role`, `Director`) appear unaffected. Needs a workaround or monitoring for fix.

**Refresh optimization:** After initial match, Plex calls Metadata directly using the stored guid. No re-match occurs on refresh. Caching metadata by ratingKey is correct and efficient.

Source: Official docs + Plex forum genre bug report. Confidence: MEDIUM (bug is unresolved; behavior may change).

---

## Feature Landscape

### Table Stakes (Users Expect These)

Features users assume exist. Missing these = provider feels broken or incomplete.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| HTTP provider server (root, /match, /metadata) | The entire feature is HTTP-based; without this nothing works | MEDIUM | FastAPI or Flask; must respond within 90s; stateless per-request |
| Provider registration endpoint (`GET /`) | Plex discovers capabilities here; without it provider is invisible to Plex | LOW | Static JSON response; rarely changes |
| Match by Stash scene ID from guid | Re-match and manual fix must be stable and fast | LOW | Parse `stash2plex://scene-{id}` from guid; direct Stash GraphQL `findScene(id)` lookup |
| Match by filename via path mapping | Primary match signal; Stash scenes are files, filename is the canonical identity | HIGH | Requires regex path mapper to translate Plex-relative path to Stash absolute path, then `findScenesByPathRegex` query |
| Full metadata response for Plex display | Plex shows nothing until full metadata is returned | MEDIUM | Map Stash fields: title, date->originallyAvailableAt, studio, performers->Role[], tags->Genre[], details->summary, duration (ms) |
| Empty match response for unknown files | Missing match = no Plex display; wrong response = Plex error | LOW | Return `{"MediaContainer": {"size": 0, "Metadata": []}}` when no Stash match; never return 404 for match requests |
| Stable ratingKey across container restarts | Plex stores ratingKey and calls Metadata with it later; if key changes, Plex loses the item | LOW | Use Stash scene ID as ratingKey (e.g., `scene-123`); Stash IDs are stable integers |
| Stash GraphQL client | All data comes from Stash; every match and metadata request queries Stash GraphQL | MEDIUM | Reuse patterns from v1.x; add `findScenesByPathRegex` and `findScene(id)` queries |
| Docker container with environment variable config | Users expect "add URL, done" setup; no Python installs or Stash plugin changes | MEDIUM | Dockerfile + docker-compose.yml; env vars for Stash URL, Stash API key, path mapping rules |

### Differentiators (Competitive Advantage)

Features that set this provider apart from generic alternatives.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Regex path mapping engine | Stash and Plex virtually never share the same path scheme; without this, Match by filename fails for most users | HIGH | User configures named regex pairs: `(plex_pattern, stash_replacement)`; bidirectional (forward for match, reverse for gap detection); first-match-wins ordering |
| Filename-only fallback matching | When path mapping fails or is unconfigured, filename alone is often unique enough to match | MEDIUM | Strip quality suffixes from Plex `filename` field; query Stash `findScenesByPathRegex` on filename component only; mirrors v1.x matcher heuristic |
| Title + date token fallback | Many Stash scene names embed date and title parseable from Plex's extracted `title` | MEDIUM | Extract ISO date and title tokens from Plex `title` field as tertiary strategy when path and filename fallbacks both fail |
| Gap detection: Plex files not in Stash | Surfaces files Plex has scanned that Stash does not know about | HIGH | Enumerate Plex library items; apply reverse path mapping; query Stash for each path; build "not found in Stash" list |
| Gap detection: Stash scenes not in Plex | Surfaces Stash scenes that never got into Plex's library | HIGH | Enumerate all Stash scenes via paginated `findScenes`; apply forward path mapping; check Plex library for each; build "not in Plex" list |
| Real-time gap events during scans | Gaps caught at scan time rather than discovered in a later audit | LOW | When Match returns empty (no Stash match), log/emit a gap event; zero cost, happens in the existing Match flow |
| Scheduled full gap comparison | Periodic full audit catches files added outside of Plex scan events | MEDIUM | Scheduler in Docker container (APScheduler or cron); runs both gap directions on configurable interval |
| Gap report readable by v1.x Stash plugin UI | Users see gaps in the familiar Stash UI without learning a new tool | MEDIUM | Provider writes gap results to a JSON file on a shared Docker volume; v1.x plugin reads and renders in Stash UI tasks |
| Manual match candidates ranked by confidence | User-initiated "Fix Match" shows best options; user picks the right one | MEDIUM | `manual=1` response returns multiple Stash scenes ordered by match quality: guid match > path match > filename match > title match |
| Coexistence with v1.x push model | Provider handles Plex-pull at scan time; v1.x handles Stash-push on hook events; no interference | LOW | Provider is read-only from Stash perspective; it never writes to Stash, never touches v1.x queue or worker |

### Anti-Features (Commonly Requested, Often Problematic)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| Plex to Stash metadata write-back | Plex edits propagating back to Stash seems like full bi-directionality | Stash is the source of truth; write-back creates sync loops, conflicts with stash-box identification, and contradicts the v1.x data flow contract | Keep Stash authoritative; provider reads only |
| Provider replaces v1.x push model | Simpler single system | Provider is pull-only triggered by Plex scans; v1.x push handles real-time hook-driven updates which the provider cannot initiate | Keep both; they cover different event types |
| Provider-managed retry queue | Seems needed for transient Stash failures | Adds operational complexity to Docker container; v1.x plugin already owns the queue and retry logic | Let provider return empty match on Stash timeout; Plex will retry on next scan or refresh |
| Per-user Plex authentication | Restrict provider access per Plex user | Plex provider spec has no authentication mechanism as of February 2026 | Run provider on local network only; no public exposure needed for home media server use |
| Music library support | Complete metadata ecosystem | Plex provider API does not support music type yet (confirmed February 2026); Stash does not manage music files | Explicitly out of scope; document the limitation clearly |
| Real-time Plex scan triggering from Stash | Fully automated push-to-scan | Provider cannot initiate Plex scans; it only responds to them | v1.x push model updates metadata after scan completes; teach users the flow order |
| NFO / sidecar file generation | Some users prefer file-based metadata storage | Plex provider spec does not integrate NFO for matching; NFO is a legacy metadata agent concept incompatible with the new provider API | Stick to HTTP provider contract; NFO approach is not supported |
| Provider-specific preferences UI in Plex | Configure API keys through Plex settings | Plex has not shipped provider preferences yet (confirmed limitation February 2026) | Use environment variables in Docker container for all configuration |

---

## Feature Dependencies

```
[HTTP Provider Server]
    required by -> [Provider Registration Endpoint]
    required by -> [Match Endpoint]
    required by -> [Metadata Endpoint]

[Stash GraphQL Client]
    required by -> [Match by filename/path]
    required by -> [Match by Stash scene ID]
    required by -> [Full metadata response]
    required by -> [Gap detection: Stash scenes not in Plex]

[Regex Path Mapping Engine]
    required by -> [Match by filename/path] (forward translation: Plex path -> Stash path)
    required by -> [Gap detection: Plex files not in Stash] (reverse translation: Plex path -> Stash path to verify)
    required by -> [Gap detection: Stash scenes not in Plex] (forward translation: Stash path -> Plex path to check)
    enhances   -> [Filename fallback matching] (path map first; fallback to filename when path map misses)

[Match by Stash scene ID]
    enables -> [Stable ratingKey behavior]
    enables -> [Fast re-match on metadata refresh]

[Match by filename/path]
    depends on -> [Regex Path Mapping Engine] (primary)
    falls back to -> [Filename fallback matching] (secondary)
    falls back to -> [Title + date token fallback] (tertiary)
    enables -> [Real-time gap events during scans] (no match = gap event; zero additional cost)

[Gap detection: Plex files not in Stash]
    depends on -> [Plex API client] (enumerate Plex library items)
    depends on -> [Regex Path Mapping Engine] (reverse-translate Plex paths to Stash paths)
    depends on -> [Stash GraphQL Client] (verify scene existence in Stash)

[Gap detection: Stash scenes not in Plex]
    depends on -> [Stash GraphQL Client] (paginated enumeration of all Stash scenes)
    depends on -> [Regex Path Mapping Engine] (forward-translate Stash paths to expected Plex paths)
    depends on -> [Plex API client] (verify item existence in Plex)

[Scheduled full gap comparison]
    depends on -> [Gap detection: Plex files not in Stash]
    depends on -> [Gap detection: Stash scenes not in Plex]

[Gap report in Stash plugin UI]
    depends on -> [Gap detection: any direction] (needs data to display)
    depends on -> [v1.x Stash plugin] (renders UI; already exists; reads from shared volume)

[Docker container deployment]
    wraps -> [HTTP Provider Server]
    wraps -> [Scheduled full gap comparison]
    provides -> environment variable configuration
    provides -> shared volume for gap report JSON
```

### Dependency Notes

- **Regex Path Mapping is the architectural lynchpin.** Plex sends filename as a path relative to the Plex library root (e.g., `Movies/Studio/filename.mp4`). Stash stores absolute paths (e.g., `/mnt/nas/Movies/Studio/filename.mp4`). Docker mounts add a third layer. The mapper must handle prepend-root, case sensitivity, and volume mount differences. Both forward (Stash->Plex) and reverse (Plex->Stash) translations must work. Design as ordered list of named regex rules: `(plex_pattern, stash_replacement)` for forward, invert capture groups for reverse.

- **Match by filename/path requires Stash `findScenesByPathRegex`.** Stash GraphQL supports path-based queries via `findScenesByPathRegex`. The provider constructs a regex from the mapped path or just the filename to query Stash. The existing v1.x `matcher.py` has equivalent logic that can be ported.

- **Gap detection full sweep is expensive at scale.** Enumerating all Plex items and all Stash scenes then comparing is O(n) per system with O(1) set lookups — use a set-based approach: collect all Stash normalized paths into a Python set, then check each Plex item's translated path against the set. Paginate the Stash GraphQL query (100 scenes per page recommended).

- **Real-time gap events are free.** The Match endpoint already decides "found in Stash" or "not found in Stash." Logging a structured gap event when Match returns empty costs nothing and captures scan-time gaps without a separate mechanism.

- **Gap report in Stash plugin UI needs a communication channel.** Provider runs in Docker; v1.x plugin runs inside Stash. Options: shared Docker volume with a JSON file (recommended — simple, no port needed), or provider exposes a `/gaps` REST endpoint the Stash plugin polls.

---

## MVP Definition

MVP = enough for Plex to successfully match and display Stash metadata via the provider.

### Launch With (v2.0 MVP)

- [ ] HTTP provider server with root registration, `/match` POST, `/metadata/{ratingKey}` GET
- [ ] Match by Stash scene ID from guid field — stable re-match, no path mapping needed
- [ ] Regex path mapping engine — user-configurable named rules, bidirectional
- [ ] Match by filename via mapped path -> Stash `findScenesByPathRegex`
- [ ] Filename-only fallback when path mapping not configured or misses
- [ ] Full metadata response: title, date, studio, performers as Role[], tags as Genre[], details as summary, duration, screenshot as thumb
- [ ] Empty match response (valid MediaContainer, not 404) for files not found in Stash
- [ ] Manual match (`manual=1`) returns multiple candidates ranked by match quality
- [ ] Docker container with docker-compose.yml and environment variable config for Stash URL, Stash API key, and path mapping rules

### Add After Validation (v2.x)

- [ ] Gap detection: Plex files not in Stash — trigger when users report "Plex has files Stash doesn't know about"
- [ ] Gap detection: Stash scenes not in Plex — trigger when users want full library coverage audit
- [ ] Scheduled full gap comparison — trigger after individual gap directions are validated
- [ ] Gap report readable in Stash plugin UI — trigger after gap detection data is useful
- [ ] Real-time gap event logging during scans — trigger: gap detection patterns are established; low cost to add

### Future Consideration (v2.x+)

- [ ] Batch metadata pre-warming at startup — pre-cache Stash scenes to reduce per-request latency; defer until 90s timeout is a real problem in production
- [ ] Genre array bug workaround — monitor Plex for fix; implement concatenation workaround only if bug persists past v2.0
- [ ] Provider preferences UI in Plex — deferred; Plex has not shipped this feature; environment variables are the current workaround

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| HTTP provider server + registration | HIGH | LOW | P1 |
| Match by Stash scene ID (guid) | HIGH | LOW | P1 |
| Regex path mapping engine | HIGH | HIGH | P1 |
| Match by filename via path mapping | HIGH | MEDIUM | P1 |
| Full metadata response | HIGH | MEDIUM | P1 |
| Docker container + docker-compose.yml | HIGH | LOW | P1 |
| Empty match response (no error on miss) | HIGH | LOW | P1 |
| Filename-only fallback matching | HIGH | MEDIUM | P1 |
| Manual match ranked candidates | MEDIUM | MEDIUM | P2 |
| Gap detection: Plex not in Stash | MEDIUM | HIGH | P2 |
| Gap detection: Stash not in Plex | MEDIUM | HIGH | P2 |
| Scheduled full gap comparison | MEDIUM | MEDIUM | P2 |
| Gap report in Stash plugin UI | MEDIUM | MEDIUM | P2 |
| Real-time gap event logging | LOW | LOW | P2 |
| Title + date token fallback | LOW | MEDIUM | P3 |
| Match confidence scoring detail | LOW | MEDIUM | P3 |
| Batch metadata pre-warming | LOW | HIGH | P3 |

**Priority key:**
- P1: Must have for v2.0 launch — provider non-functional without these
- P2: Should have — gap detection, manual match improvements
- P3: Nice to have — polish, optimization, edge case handling

---

## Competitor Feature Analysis

No direct competitor exists (Stash-to-Plex custom providers are a niche). Comparable providers in the ecosystem:

| Feature | tmdb-example-provider (Plex official) | plex-meta-tvdb (community) | Stash2Plex Provider (our approach) |
|---------|---------------------------------------|---------------------------|-------------------------------------|
| Match strategy | Title + year via TMDB title search | Title + year via TVDB search | Filename path mapping + Stash GraphQL; guid fallback on re-match |
| Filename / path use | Not used — TMDB is authoritative | Not used — TVDB is authoritative | Primary signal — Stash path is the canonical identity |
| External ID format | `tmdb://12345` | `tvdb://12345` | `stash2plex://scene-{id}` using Stash scene integer ID |
| Path translation | Not needed (external API is authoritative) | Not needed | Required — Plex relative path never matches Stash absolute path |
| Gap detection | None | None | Bi-directional gap detection (differentiator unique to this provider) |
| Deployment | TypeScript server, no Docker specified | TypeScript server, no Docker specified | Python Docker container (explicit requirement) |
| Authentication | None (spec limitation) | None (spec limitation) | None (spec limitation; same constraint) |
| Data source | TMDB API (external, internet-required) | TVDB API (external, internet-required) | Stash local instance (no internet required) |

---

## Stash GraphQL Queries Needed

These are the GraphQL queries the provider must issue against the Stash instance. Field names should be verified against the local Stash GraphQL playground (`http://stash-host/playground`) before implementation.

**Primary match query (path or filename):**

```graphql
query FindScenesByPath($path_regex: String!) {
  findScenesByPathRegex(path_regex: $path_regex) {
    id
    title
    date
    details
    duration
    studio { name }
    performers { name }
    tags { name }
    files { path }
    paths { screenshot }
  }
}
```

**Direct ID lookup (for guid-based re-match and Metadata endpoint):**

```graphql
query FindScene($id: ID!) {
  findScene(id: $id) {
    id
    title
    date
    details
    duration
    studio { name }
    performers { name }
    tags { name }
    files { path }
    paths { screenshot }
  }
}
```

**Full scene enumeration (for gap detection, paginated):**

```graphql
query AllScenes($page: Int!, $per_page: Int!) {
  findScenes(filter: { page: $page, per_page: $per_page }) {
    count
    scenes {
      id
      title
      files { path }
    }
  }
}
```

Confidence: MEDIUM — `findScenesByPathRegex` confirmed via Stash community documentation; exact field names (`files { path }` vs `paths`) should be verified against local Stash instance before implementing.

---

## Path Mapping Design Notes

The regex path mapping engine is the most architecturally critical unique feature. User-facing design:

**The problem in concrete terms:**
- Plex sends: `filename: "Movies/Studio Name/2024-01-15 Title.mp4"` (relative to Plex library root)
- Stash stores: `/volume/media/Movies/Studio Name/2024-01-15 Title.mp4` (absolute)
- Docker mounts may differ between the Plex container and the Stash container

**Configuration model (user-facing, in docker-compose environment vars or YAML):**

```yaml
path_mappings:
  - name: "Main library"
    plex_pattern: "^Movies/(.*)"
    stash_replacement: "/volume/media/Movies/\\1"
  - name: "Archive"
    plex_pattern: "^Archive/(.*)"
    stash_replacement: "/mnt/old/\\1"
```

Rules are tried in order; first match wins. Bidirectional: forward uses `(plex_pattern, stash_replacement)`, reverse derives the inverse by swapping pattern and replacement with capture groups.

**Filename-only fallback (when no path rule matches):** Extract just the filename from Plex's relative path, construct a regex that matches that filename anywhere in a Stash path, query via `findScenesByPathRegex`. Degrades gracefully when path mapping is unconfigured — most filenames are unique enough.

---

## Known Constraints and Edge Cases

| Constraint | Impact | Mitigation |
|------------|--------|------------|
| 90-second PMS timeout | Stash queries + path mapping must complete in under 90s | Cache Stash responses; avoid full library scans per request; use `findScenesByPathRegex` not `findScenes` with scan |
| No provider authentication in spec | Provider URL accessible to anyone on the network | Deploy on local network only; document this; add optional IP allowlist in provider |
| Genre array bug (only first imported) | Tags from Stash lose all but the first | Monitor Plex for fix; workaround: concatenate tags into single string as tag if bug persists |
| ratingKey must be URL-safe | Cannot use file paths or special characters as ratingKey | Use Stash integer scene ID as ratingKey: `scene-123` |
| Provider-specific preferences not implemented in Plex | Cannot configure provider via Plex UI | Use environment variables in Docker container |
| Music libraries unsupported | Cannot extend to audio | Explicitly out of scope; document |
| Filename field is relative to library root | Must know Plex library root to reconstruct absolute path | Path mapping engine handles this; library root is one of the mapping inputs |
| Re-match uses stored guid, not re-scanning | Once matched, Plex does not re-discover; uses stored guid | Stable ratingKey is critical; never change the ID scheme |

---

## Sources

- Plex Metadata Provider API documentation: https://developer.plex.tv/pms/index.html#section/API-Info/Metadata-Providers (MEDIUM confidence — fetched February 2026; API is beta)
- Plex official TMDB example provider: https://github.com/plexinc/tmdb-example-provider (HIGH confidence — official Plex reference implementation)
- Plex custom provider announcement forum: https://forums.plex.tv/t/announcement-custom-metadata-providers/934384/ (HIGH confidence — official Plex announcement)
- Plex provider announcement page 2 (community edge cases): https://forums.plex.tv/t/announcement-custom-metadata-providers/934384?page=2 (MEDIUM confidence — developer community observations; 90s timeout, filename field, no auth)
- Genre array bug report: https://forums.plex.tv/t/only-first-genre-is-imported-when-matching-or-metadata-requested-from-a-custom-metadata-providers/936554 (MEDIUM confidence — active February 2026, unresolved)
- Community TVDB provider reference: https://github.com/Drewpeifer/plex-meta-tvdb (MEDIUM confidence — community implementation showing Match response structure)
- Stash GraphQL API reference: https://deepwiki.com/stashapp/stash/4.1-graphql-api (MEDIUM confidence — third-party Stash documentation)
- Stash scene GraphQL schema: https://github.com/stashapp/stash/blob/develop/graphql/schema/types/scene.graphql (HIGH confidence — official Stash source)
- Existing v1.x matcher: /Users/trekkie/projects/Stash2Plex/plex/matcher.py (HIGH confidence — production code showing filename-based matching heuristics)

---

*Feature research for: Plex Metadata Provider + Bi-Directional Gap Detection (v2.0)*
*Researched: 2026-02-23*

# Pitfalls Research: Plex Metadata Provider Service

**Domain:** Adding Custom Plex Metadata Provider + Docker service to existing Stash-to-Plex sync plugin
**Researched:** 2026-02-23
**Confidence:** HIGH (Plex API, Docker networking), MEDIUM (monorepo integration, gap detection edge cases)

**Context:** PlexSync v2.0 adds a Plex-side metadata provider service deployed as a Docker container. The provider queries Stash GraphQL API during Plex scans to resolve metadata. Regex-based bidirectional path mapping connects the two filesystems. Bi-directional gap detection (real-time during scans + scheduled) identifies items out of sync. The provider coexists with the v1.x push model.

---

## Critical Pitfalls

Mistakes that cause rewrites, broken Plex scanning, or silent data corruption.

### Pitfall 1: GUID and ratingKey Cannot Contain Forward Slashes

**What goes wrong:**
The provider generates a GUID or ratingKey that contains a forward slash — for example, encoding a Stash scene path like `/data/videos/Studio/Scene Title.mp4` into the identifier. Plex treats the ratingKey as a URL path component and the forward slash breaks URL routing. The metadata endpoint becomes unreachable (`/library/metadata/data/videos/...` parses as nested paths), and Plex silently fails to fetch metadata, leaving items unmatched.

**Why it happens:**
Developers naturally want to use the Stash scene path or a combination of IDs in the ratingKey for easy lookup. Paths contain slashes. The Plex API documentation specifies that ratingKeys cannot contain forward slashes, but this constraint is easy to overlook when designing the identifier scheme for a file-path-based provider.

**How to avoid:**
Use Stash's numeric scene ID as the ratingKey — it is guaranteed slash-free. The GUID format must be:

```
tv.plex.agents.custom.stash2plex://scene/{stash_scene_id}
```

Where `stash_scene_id` is an integer. Never embed file paths, hashes, or any string that could contain slashes in the ratingKey. The provider identifier prefix (`tv.plex.agents.custom.stash2plex`) must use only ASCII letters, numbers, and periods — verified against regex `[a-zA-Z0-9.]+`.

**Warning signs:**
- HTTP 404s when Plex fetches metadata from the provider (check provider access logs)
- Items match successfully but metadata fetch silently fails
- GUID in Plex database shows truncated or malformed paths

**Phase to address:**
Phase 1 (Provider skeleton + GUID design) — establish ratingKey format before any matching logic is written.

---

### Pitfall 2: Plex Sends Relative Paths, Not Absolute Paths, to the Match Endpoint

**What goes wrong:**
The Match endpoint receives a `filename` hint that is a relative path from the Plex library root, not the full absolute path on disk. Code that tries to apply regex path mapping (Stash-side path → Plex-side path) to reconstruct the full path fails because there is no library root prefix in the hint. The provider falls back to title-only matching for every item, defeating the purpose of regex path mapping.

**Why it happens:**
The Plex documentation states `filename` is "the relative path for the underlying media file" — but developers assume it will be the same full path that Plex stores internally for the file (as seen in `plexapi` `part.file`). They are different: `part.file` is the full absolute path inside Plex's container/mount, while the Match hint `filename` is relative to the library section root.

**How to avoid:**
Design the Match endpoint to work in two layers:
1. **Primary match:** Stash GraphQL query using title/year hints (always present). Use `filename` only as a confidence tiebreaker.
2. **Path-assisted match:** Apply regex mapping to `filename` to derive a Stash-comparable relative path, then query Stash for scenes matching that relative path segment. Do not reconstruct absolute paths from the filename hint alone.

Configure at least one fallback (Stash scene hash, if available via `guid` hint from a prior agent pass).

**Warning signs:**
- All Match responses return zero results when using path-based lookup
- Provider logs show "filename hint" present but path reconstruction returns no match
- 100% of matches fall through to title-only fallback

**Phase to address:**
Phase 2 (Match endpoint implementation) — verify Match hint payload format against the live Plex instance before implementing path logic.

---

### Pitfall 3: Regex Path Mapping Silently Matches the Wrong Direction

**What goes wrong:**
Bidirectional path mapping uses one set of regex patterns for Stash→Plex and the reverse for Plex→Stash. A pattern like `^/data/(.+)` applied in the wrong direction matches a path it should not, translates it silently, and the translated path does not exist on the target system. The match returns None (scene not found), which is logged as "item not in Stash" — misidentifying the failure as a gap rather than a mapping error.

**Why it happens:**
Bidirectional mapping requires two distinct regex sets. Developers write the forward mapping, copy it for the reverse, and make a mistake in the capture group or substitution. Because both patterns are valid regex, there is no parse-time error. The failure mode is silent: the mapped path is syntactically valid but semantically wrong.

**How to avoid:**
- Implement an explicit validation step at startup: pick five known-good Stash scene paths, apply forward mapping, verify the result exists in the Plex library structure, apply reverse mapping to the result, verify you get the original path back. Fail startup if round-trip fails.
- Store forward and reverse patterns as separate named configs (`stash_to_plex_patterns`, `plex_to_stash_patterns`) — never derive one from the other algorithmically.
- Log every path translation at DEBUG level: `"Stash /data/foo.mp4 → Plex /media/foo.mp4"`. Silent mappings are undebuggable.

```python
def validate_path_mapping_roundtrip(mapper, sample_stash_paths):
    for stash_path in sample_stash_paths:
        plex_path = mapper.stash_to_plex(stash_path)
        if plex_path is None:
            raise ConfigError(f"Forward mapping failed for: {stash_path}")
        recovered = mapper.plex_to_stash(plex_path)
        if recovered != stash_path:
            raise ConfigError(
                f"Roundtrip mapping failed: {stash_path} → {plex_path} → {recovered}"
            )
```

**Warning signs:**
- Gap detection reports many scenes as "not in Plex" despite them being there
- Match success rate suddenly drops after path mapping config change
- Provider logs show path translations producing paths with double slashes or wrong roots

**Phase to address:**
Phase 3 (Regex path mapping engine) — roundtrip validation must be a required startup check, not an optional debug flag.

---

### Pitfall 4: Provider Registration URL Must Be Reachable from Plex's Network Context

**What goes wrong:**
The provider is registered in Plex using `http://localhost:8008` or `http://127.0.0.1:8008`. This works when Plex and the provider are on the same host with host networking. But if Plex runs in Docker with bridge networking (common for Unraid, Synology, and NAS setups), `localhost` inside the Plex container resolves to the container itself — not the host. Plex cannot reach the provider. All metadata requests fail silently; Plex falls back to built-in agents.

**Why it happens:**
During development the provider is tested from a browser or curl on the host machine, where `localhost:8008` works fine. The developer registers the URL from the host's perspective. But Plex makes HTTP requests to the registered URL from within its own network context, where `localhost` has a different meaning.

**How to avoid:**
- For Docker bridge mode (most NAS deployments): register the provider using the Docker bridge gateway IP (`172.17.0.1`) or the host's LAN IP (e.g., `192.168.1.x:8008`).
- For Docker host mode: `localhost` works from Plex's perspective because Plex shares the host network stack.
- For both containers on a shared Docker network: use the service name (`http://stash2plex-provider:8008`).

Document all three cases explicitly in the deployment guide. Provide a startup check where the provider logs its own URL and network mode on startup.

**Warning signs:**
- Provider is running (accessible from browser on host) but Plex shows no metadata from the custom provider
- Plex Media Server logs show connection refused or timeout to the provider URL
- Provider access logs show no requests from Plex at all

**Phase to address:**
Phase 1 (Provider skeleton + Docker setup) — test with Plex in bridge mode before writing any metadata logic.

---

### Pitfall 5: host.docker.internal Does Not Work on Linux Without Extra Config

**What goes wrong:**
The provider uses `host.docker.internal` to reach the Stash instance running on the host (e.g., `http://host.docker.internal:9999/graphql`). This works on Docker Desktop for Mac and Windows, where Docker Desktop injects this DNS entry automatically. On Linux (the dominant NAS/server platform where users actually run Stash), `host.docker.internal` is not defined by default. The provider fails to connect to Stash GraphQL with a DNS resolution error at startup. The container crashes or runs in a permanently degraded state.

**Why it happens:**
Developers test on Mac with Docker Desktop, where `host.docker.internal` is pre-configured. They assume it is a universal Docker feature. It is not — on Linux Docker (not Docker Desktop), it requires an explicit `extra_hosts` entry in `docker-compose.yml`:

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

**How to avoid:**
- In `docker-compose.yml`, always include `extra_hosts: ["host.docker.internal:host-gateway"]` for Linux compatibility.
- Alternatively, use the `--add-host=host.docker.internal:host-gateway` flag.
- Document that the Stash URL config should use `host.docker.internal` for host-based Stash instances, and explain the Linux requirement.
- Add a startup connectivity check that attempts to reach the configured Stash URL and logs a clear error if unreachable: `"Cannot reach Stash at {url} — check host.docker.internal config on Linux"`.

**Warning signs:**
- Provider logs show "Name or service not known: host.docker.internal" at startup
- Provider works on developer's Mac but fails for users running on Linux NAS
- Stash GraphQL connection errors despite Stash being accessible from the host browser

**Phase to address:**
Phase 1 (Docker setup) — test on Linux Docker, not just Docker Desktop, before publishing the docker-compose.yml.

---

### Pitfall 6: 90-Second Plex Timeout Kills Stash GraphQL Queries During Large Library Operations

**What goes wrong:**
During a Plex library scan of a large library (1,000+ scenes), the provider handles many concurrent Match requests. Each Match request queries Stash GraphQL. If Stash is under load (background scan, tag update, etc.), GraphQL responses slow to 5-10 seconds. Plex enforces a hard 90-second timeout on all provider requests. Under concurrent load, request queuing causes latency to compound. Requests start timing out. Plex marks items as unmatched and stops retrying them for the current scan cycle.

**Why it happens:**
The provider was tested with a small library where Stash responds in <100ms. Under concurrent scan load, the simple `requests.get(stash_graphql_url, ...)` call blocks without a short timeout, and 20 simultaneous slow GraphQL queries back up the provider's HTTP server.

**How to avoid:**
- Set an explicit timeout on all Stash GraphQL requests: `requests.post(url, timeout=10)` — short enough to fail fast before the 90-second Plex timeout.
- Implement a local request cache: identical Match queries (same title + year) return cached results for 5 minutes, reducing Stash load during bulk scans.
- Use async request handling in the provider HTTP server (FastAPI with async routes, not Flask with synchronous handlers) to prevent one slow Stash query from blocking other concurrent requests.
- Add a Stash circuit breaker in the provider: if Stash responds slowly >3 times in 60 seconds, return empty Match results for 30 seconds rather than queueing more slow queries.

**Warning signs:**
- Provider logs show requests completing in 8-15 seconds during scans (Stash load indicator)
- Plex scan logs show provider timeout errors for specific items
- Items that were previously matched become unmatched after a full library rescan

**Phase to address:**
Phase 2 (Match endpoint) — implement caching and short timeouts from day one; do not defer as an optimization.

---

### Pitfall 7: Monorepo Docker Build Context Cannot Access Parent Directory

**What goes wrong:**
The monorepo structure has `shared/` at the repo root, used by both the existing Stash plugin and the new `provider/` service. The provider's `Dockerfile` sits in `provider/` and tries to `COPY ../shared/ ./shared/` to include the shared code. Docker refuses this: build context cannot reference files outside the build context directory. The build fails with `COPY failed: forbidden path outside the build context`.

**Why it happens:**
This is a fundamental Docker constraint: the build context is the directory passed to `docker build` (typically the Dockerfile's directory). Any `COPY` or `ADD` instruction must reference paths within that context. When the Dockerfile is in a subdirectory but needs sibling or parent files, the natural `../` reference is forbidden.

**How to avoid:**
Set the build context to the repository root, not the `provider/` directory. Use a `docker-compose.yml` at the repo root:

```yaml
services:
  stash2plex-provider:
    build:
      context: .              # Repo root is build context
      dockerfile: provider/Dockerfile
```

In the Dockerfile, reference paths from the repo root:

```dockerfile
COPY shared/ /app/shared/
COPY provider/ /app/provider/
WORKDIR /app/provider
```

Alternatively, install `shared/` as a local package via `pip install -e ../shared` using a `pyproject.toml`, but this requires the shared package to be properly structured as an installable Python package.

**Warning signs:**
- `docker build` fails with `forbidden path outside the build context`
- Developer works around it by copying `shared/` into `provider/` manually — this creates a diverging copy
- Tests pass locally (using relative imports) but Docker image has import errors at runtime

**Phase to address:**
Phase 1 (Monorepo restructure + Docker setup) — establish the build context pattern before writing any provider code.

---

### Pitfall 8: Gap Detection Timestamps Between Stash and Plex Are Not Comparable

**What goes wrong:**
The gap detection logic compares Stash's `updated_at` timestamp against Plex's `updatedAt` field to determine if a scene is "stale in Plex." Stash stores timestamps in UTC ISO 8601. Plex's `updatedAt` field represents when Plex last refreshed its internal metadata record — not when Stash was updated. These measure different events: Stash update time vs. Plex metadata write time. They are not comparable. Gap detection either misses all gaps (Plex's `updatedAt` is always newer because Plex refreshes periodically) or flags everything as stale (Stash's update time is always newer).

**Why it happens:**
The naive assumption is: "if Stash was updated after Plex last saw this item, the item needs re-sync." But Plex's `updatedAt` is modified by ANY Plex metadata operation — including thumbnail generation, sort order updates, or agent re-runs unrelated to Stash. The two clocks measure different things.

**How to avoid:**
Use the existing `sync_timestamps.json` (already tracking "when did Stash2Plex last sync this scene?") as the reference point for gap detection. The correct comparison is:

```
Gap if: stash.updated_at > sync_timestamps[scene_id].last_synced_at
```

Not:
```
Gap if: stash.updated_at > plex.updatedAt  # Wrong — different clocks
```

For items with no sync timestamp at all (never synced), flag as a gap regardless of timestamps.

**Warning signs:**
- Gap detection reports 0 gaps even when known-stale scenes exist
- Gap detection reports all scenes as stale after any Plex library maintenance
- Periodic gap detection consistently flags the same scenes as gaps even after re-sync

**Phase to address:**
Phase 4 (Bi-directional gap detection) — design the comparison logic using `sync_timestamps.json` as the authority before writing any gap detection queries.

---

### Pitfall 9: Real-Time Gap Detection During Plex Scan Overwhelms Stash GraphQL

**What goes wrong:**
The provider intercepts Plex scan events and runs a Stash GraphQL lookup for every scene Plex scans. During a full library rescan (1,000+ items), the provider fires 1,000 simultaneous GraphQL queries against Stash. Stash's embedded HTTP server is not built for high concurrent load — it processes requests sequentially or with minimal concurrency. Response times climb from 50ms to 30+ seconds. The provider's 90-second Plex timeout window fills up. Plex scan stalls. Stash becomes unresponsive for the duration of the scan.

**Why it happens:**
The real-time gap detection design pattern assumes the provider can query Stash for every Plex scan event. Under normal per-scene hook usage this is fine. During a full rescan, Plex fires scan events for every item in rapid succession, with no rate limiting from Plex's side.

**How to avoid:**
- **Batch gap detection:** Do not query Stash per-item during real-time scan. Instead, record which scenes Plex scanned (write to a local SQLite log) and then run a batch comparison against Stash after the scan completes (detect via scan completion hook or polling).
- **Rate limit real-time queries:** If per-item queries are needed, use a token bucket (max 10 queries/second to Stash) and queue excess requests.
- **Scheduled gap detection for bulk:** For full library comparisons, use the scheduled gap detection (already planned) rather than real-time interception. Reserve real-time detection for individual scene-level events only.

**Warning signs:**
- Stash UI becomes unresponsive during Plex library rescans
- Provider logs show Stash GraphQL requests queuing up with increasing latency
- Plex scan takes much longer than usual (provider is a bottleneck)

**Phase to address:**
Phase 4 (Bi-directional gap detection) — design the real-time vs. scheduled detection split upfront; do not build real-time detection that relies on per-item GraphQL queries.

---

## Technical Debt Patterns

Shortcuts that seem reasonable but create long-term problems.

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Use Flask instead of FastAPI for provider | Simpler, familiar, no async complexity | Synchronous handler blocks under concurrent Plex scan load; hits 90s timeout at scale | Only for prototype/single-user; never for library rescans |
| Hardcode Stash URL as localhost in provider | Works on developer machine | Breaks for every Docker deployment on a different host | Never (always make configurable) |
| Skip roundtrip validation of regex path mapping | Faster startup, simpler code | Silent mapping failures appear as "scene not in Stash" gaps | Never — validation catches config errors before they corrupt gap state |
| Store GUIDs with file paths embedded | Easy human debugging | Forward slashes in paths break Plex URL routing | Never |
| Single docker-compose.yml per-service | Simpler per-service builds | Cannot share parent directory code; leads to duplicated `shared/` copies | Never (sets up divergence) |
| Query Stash without per-request timeout | Simpler requests code | One slow Stash query blocks all concurrent provider requests; cascading timeout | Never (always set timeout <= 10s) |
| Compare Plex updatedAt to Stash updated_at for gaps | Straightforward, matches field names | Measures different events; produces incorrect gap detection in both directions | Never |
| Use sync_timestamps.json from plugin directory in provider | No new state file, shared truth | Provider must know plugin data dir path; creates coupling and Docker volume dependency | Acceptable if volume path is configurable |

---

## Integration Gotchas

Common mistakes when connecting to external services.

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| Plex Provider API (Match) | Assume `filename` hint is absolute path | Treat as relative-to-library path; use title/year as primary match signals |
| Plex Provider API (registration) | Register with `localhost` URL | Register with host LAN IP or Docker service name, depending on network topology |
| Plex Provider API (GUID) | Embed file paths in ratingKey | Use integer Stash scene ID only; no slashes permitted |
| Plex Provider API (90s timeout) | No timeout on upstream Stash calls | Set 10s timeout on all GraphQL calls; cache repeat queries for 5 min |
| Plex Provider API (images) | Assume images URL is private/internal | Image URLs must be publicly accessible (or accessible to Plex's network); provider must serve them |
| Stash GraphQL (from Docker) | Use `host.docker.internal` without Linux config | Add `extra_hosts: ["host.docker.internal:host-gateway"]` in docker-compose for Linux |
| Stash GraphQL (concurrent scan) | Fire one query per Plex scan event | Batch queries; rate-limit to max 10/sec; cache results per scan session |
| Regex path mapping (bidirectional) | Derive reverse pattern from forward | Write forward and reverse as separate explicit configs; validate roundtrip on startup |
| sync_timestamps.json (gap detection) | Compare Plex `updatedAt` to Stash `updated_at` | Compare Stash `updated_at` to `sync_timestamps.json[scene_id].last_synced_at` |
| Docker build (monorepo) | `COPY ../shared/` from service Dockerfile | Set build context to repo root; reference `shared/` from root in Dockerfile |

---

## Performance Traps

Patterns that work at small scale but fail as usage grows.

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Synchronous Flask handler for Match endpoint | One slow Stash query blocks all concurrent Plex scan requests | Use FastAPI with async handlers; set short Stash query timeout | Libraries > 50 items (Plex scans concurrent) |
| No cache on Match endpoint | Stash gets 1,000 identical title queries during rescan | Cache Match results by (title, year, type) for 5 minutes | Libraries > 100 items in single scan |
| Full Stash library dump for gap detection | Gap scan takes 10+ minutes for 5,000-scene library | Paginate Stash GraphQL queries; use cursor-based pagination | Libraries > 500 scenes |
| Per-item Stash query during real-time scan interception | Stash becomes unresponsive during Plex rescan | Batch or rate-limit real-time scan queries | Libraries > 20 items scanned simultaneously |
| Storing full file paths in GUID/ratingKey | Hits Plex URL routing limit on deeply nested paths | Use integer scene IDs as ratingKeys | Any library with paths > ~100 chars |
| Docker bridge networking without ADVERTISE_IP | Plex reports wrong URL, remote access breaks | Set ADVERTISE_IP in docker-compose or use host networking | Any remote access scenario |

---

## Security Mistakes

Domain-specific security issues for a metadata provider serving local network.

| Mistake | Risk | Prevention |
|---------|------|------------|
| Provider accepts all requests without auth token validation | Any process on local network can inject false metadata into Plex | Validate Plex-provided request headers (X-Plex-Token) or use a shared secret in config; at minimum bind to 127.0.0.1 if single-host |
| Stash API key logged at DEBUG level | API key visible in log files shared for debugging | Redact credentials in all log output; use same obfuscation pattern as existing plugin |
| Provider serves Stash image URLs with auth token in URL | Token exposed in Plex's request logs and metadata store | Proxy images through provider (strip token from external URL), or use short-lived signed URLs |
| Regex path mapping patterns exposed in provider /info endpoint | Reveals internal filesystem layout | Return only provider identifier and capabilities from /info; never expose config in API responses |

---

## UX Pitfalls

Configuration and operational experience issues.

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| Provider requires manual Plex URL for registration | Users must find their server's internal URL, prone to copy errors | Auto-detect Plex URL from docker-compose network; provide registration CLI command |
| Silent match failure (no provider logs exposed) | Users cannot tell why scenes don't get metadata | Provider must log every Match request outcome (matched / no match / error) at INFO level |
| Path mapping regex errors fail at scan time | Users get "no metadata" with no explanation | Validate regex patterns at provider startup; refuse to start with invalid or non-roundtripping patterns |
| Gap detection reports same gaps repeatedly | Users re-sync scenes that keep appearing as gaps | Implement "suppressed gap" tracking: mark gap as resolved after sync; only re-flag if Stash is updated again |
| docker-compose.yml requires separate management from Stash setup | Users must manage two compose files | Provide a single `docker-compose.yml` at repo root that includes both Stash (if applicable) and provider |

---

## "Looks Done But Isn't" Checklist

Things that appear complete but are missing critical pieces.

- [ ] **Provider registers with Plex:** URL is set in Plex UI and shows green status — but verify Plex can actually make HTTP requests TO the provider (check provider access logs for incoming requests from Plex's IP)
- [ ] **Match endpoint returns results:** Returns results in development — but verify with `filename` hint as a relative path, not absolute (Plex sends relative, not absolute)
- [ ] **GUID format is correct:** GUIDs parse as valid URLs — but verify no forward slashes in the ratingKey portion (common mistake: encoding a path in the ID)
- [ ] **Path mapping works:** Forward mapping translates correctly — but verify reverse mapping too (roundtrip test) and verify with paths that have spaces, special characters, and Unicode
- [ ] **host.docker.internal resolves:** Works on Mac during development — but verify on Linux with `extra_hosts` config (Linux Docker does not inject this by default)
- [ ] **Gap detection finds gaps:** Detects gaps in a test run — but verify it is comparing against `sync_timestamps.json` (not Plex `updatedAt`) as the reference timestamp
- [ ] **Docker build succeeds:** `docker build` passes — but verify `shared/` is correctly included via root build context, not copied into the service directory (which creates a diverging duplicate)
- [ ] **Plex scan completes with provider active:** Small library scan works — but verify with a full rescan (1,000+ items) to confirm no timeout cascades or Stash overload

---

## Recovery Strategies

When pitfalls occur despite prevention, how to recover.

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| GUID format has slashes; items unmatched | HIGH | 1. Change ratingKey format 2. Force Plex to "Fix Match" on all affected items (plexapi script) 3. Re-register provider with correct GUID scheme |
| Provider URL unreachable from Plex | LOW | 1. Check provider access logs for zero requests from Plex 2. Re-register with correct host IP 3. Verify firewall/Docker network allows connection |
| host.docker.internal DNS failure on Linux | LOW | 1. Add `extra_hosts: ["host.docker.internal:host-gateway"]` to docker-compose.yml 2. Restart provider container |
| Regex path mapping misconfigured | MEDIUM | 1. Enable DEBUG logging for path translation 2. Fix patterns 3. Restart provider 4. Trigger Plex rescan to re-match previously failed items |
| Gap detection false positives (wrong timestamp source) | MEDIUM | 1. Clear gap detection state 2. Fix comparison to use sync_timestamps.json 3. Re-run gap detection |
| Docker build COPY context failure | LOW | 1. Move docker-compose.yml build context to repo root 2. Update Dockerfile COPY paths |
| Stash overwhelmed by concurrent Match queries | MEDIUM | 1. Add rate limiting (token bucket) to provider 2. Add result cache 3. Restart both services 4. Trigger Plex rescan |
| Sync timestamps not accessible from provider | MEDIUM | 1. Mount plugin data directory as Docker volume 2. Configure provider with correct path to sync_timestamps.json |

---

## Pitfall-to-Phase Mapping

How roadmap phases should address these pitfalls.

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| GUID/ratingKey contains slashes | Phase 1 (Provider skeleton) | Verify GUID regex matches `[a-zA-Z0-9.]+://[^/]+/[0-9]+` pattern only |
| Relative path filename hint misunderstood | Phase 2 (Match endpoint) | Test Match endpoint with actual Plex scan request payload (not mocked) |
| Regex path mapping wrong direction | Phase 3 (Path mapping engine) | Run roundtrip validation on 10 sample paths at startup; test fails fast |
| Provider URL unreachable from Plex bridge mode | Phase 1 (Docker setup) | Test registration and metadata fetch from Plex running in bridge-mode Docker |
| host.docker.internal fails on Linux | Phase 1 (Docker setup) | Test docker-compose.yml on Linux host, not just Docker Desktop for Mac |
| 90s Plex timeout under concurrent load | Phase 2 (Match endpoint) | Load test with 100 concurrent Match requests; all complete in <5s |
| Monorepo Docker COPY context failure | Phase 1 (Monorepo restructure) | Verify `docker build` from repo root includes shared/ without manual copying |
| Gap detection uses wrong timestamp | Phase 4 (Gap detection) | Unit test: scene with stash.updated_at > last_synced_at flags as gap; scene with stash.updated_at < last_synced_at does not |
| Real-time scan overwhelms Stash | Phase 4 (Gap detection) | Simulate 500-item Plex rescan; verify Stash response time stays under 500ms throughout |

---

## Sources

### Plex Custom Metadata Provider API
- [Announcement: Custom Metadata Providers - Plex Forum](https://forums.plex.tv/t/announcement-custom-metadata-providers/934384/) — Primary source for provider pitfalls from early adopters
- [Announcement: Custom Metadata Providers - Page 2](https://forums.plex.tv/t/announcement-custom-metadata-providers/934384?page=2) — Developer complaints: 90s timeout, relative path hints, image URL requirements
- [Plex Media Server Developer Documentation](https://developer.plex.tv/pms/) — Authoritative API spec: GUID format, Match endpoint, required fields
- [TMDB Example Provider - GitHub](https://github.com/plexinc/tmdb-example-provider) — Official reference implementation showing GUID construction, route structure
- [Preferences for new custom metadata providers](https://forums.plex.tv/t/preferences-for-new-custom-metadata-providers/936354) — Confirmed: provider preferences not yet implemented

### Docker Networking
- [Docker Host Networking: Linux vs. Mac differences](https://wikitwist.com/docker-host-networking-explained-differences-on-linux-macos-and-windows/) — host.docker.internal platform-specific behavior
- [Plex Docker Networking Options - DeepWiki](https://deepwiki.com/plexinc/pms-docker/2.3-networking-options) — Bridge vs. host mode, ADVERTISE_IP requirements
- [Docker Compose depends_on with health checks](https://oneuptime.com/blog/post/2026-01-16-docker-compose-depends-on-healthcheck/view) — Startup ordering for multi-service compose

### Monorepo / Docker Build Context
- [Python Monorepo: Shared Code and Docker](https://lightrun.com/answers/auxilincom-docker-compose-starter-how-do-you-handle-code-sharing-between-different-services-in-the-same-monorepo/) — COPY context limitation and root-context solution

### Bidirectional Sync / Gap Detection
- [The Engineering Challenges of Bi-Directional Sync](https://www.stacksync.com/blog/the-engineering-challenges-of-bi-directional-sync-why-two-one-way-pipelines-fail) — Two-pipeline approach fundamental flaws
- [Distributed Systems: Unreliable Clocks](https://medium.com/@franciscofrez/the-problems-of-distributed-systems-part-3-unreliable-clocks-a10c0fba0de4) — Timestamp comparison pitfalls across systems

### File Timestamp Handling
- [Stop using utcnow and utcfromtimestamp - Paul Ganssle](https://blog.ganssle.io/articles/2019/11/utcnow.html) — Python datetime timezone-aware comparison

---

*Pitfalls research for: PlexSync v2.0 — Plex Metadata Provider Service milestone*
*Researched: 2026-02-23*
*Focus: Custom Plex metadata provider API gotchas, Docker networking for multi-service setup, regex path mapping edge cases, bi-directional gap detection timestamp pitfalls, monorepo Docker build context*