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
