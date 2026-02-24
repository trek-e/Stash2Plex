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
