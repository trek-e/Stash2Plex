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
