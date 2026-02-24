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
