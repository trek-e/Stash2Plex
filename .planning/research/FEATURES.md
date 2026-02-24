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
