# Phase 24: Provider HTTP Skeleton - Research

**Researched:** 2026-02-25
**Domain:** Plex Custom Metadata Provider API, FastAPI, Docker, pydantic-settings
**Confidence:** HIGH (Plex API protocol verified against official example repos and community implementations; FastAPI/Docker patterns from official docs and Context7)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Docker deployment model**
- Own docker-compose.yml at repo root (not inside provider/)
- Build context is repo root so shared_lib/ is COPY-able
- Bridge networking with extra_hosts for host.docker.internal on Linux
- Default port: 9090
- Local build only (no registry publishing for Phase 24)
- python:3.12-slim base image, single-stage Dockerfile
- restart: unless-stopped
- Target topology: same machine (Plex, Stash, provider all on one box)

**Configuration approach**
- Environment variables with S2P_ prefix (S2P_STASH_URL, S2P_STASH_API_KEY, S2P_PLEX_URL, S2P_PLEX_TOKEN, S2P_LOG_LEVEL)
- Optional YAML config file mounted at /config/provider.yml — env vars override config file values
- Required to start: S2P_STASH_URL + S2P_STASH_API_KEY (fail fast with clear error if missing)
- Optional with defaults: PLEX_URL (http://host.docker.internal:32400), PLEX_TOKEN (empty — skip registration), PROVIDER_PORT (9090), LOG_LEVEL (info)
- Path mapping rules defined in the YAML config file as a list
- Validate Stash connectivity at startup — warn if unreachable but start anyway

**Plex agent registration**
- Manual setup: user adds provider URL in Plex agent settings
- Agent identifier: tv.plex.agents.stash2plex
- Declare both Match + Metadata features from Phase 24 (endpoints stub until Phases 25-26)
- Stub /match returns 200 with empty matches array
- Stub /metadata returns 200 with null metadata

**Logging & health**
- Structured JSON log format ({"ts":..., "level":..., "msg":..., ...})
- Default log level: info
- Log all incoming Plex requests at info level (path, timing)
- /health endpoint returns: status, version, stash reachability, plex registration state, uptime
- Startup banner showing version, port, connectivity status, path rule count
- Docker healthcheck in docker-compose.yml (curl /health, 30s interval)
- Version included in /health response (no separate endpoint)

### Claude's Discretion
- Media types to declare in manifest (likely Movie only based on Stash content model)
- Exact YAML config file schema structure
- FastAPI project structure within provider/
- Startup connectivity check implementation (timeout, retry)
- Exact JSON log field names and structure

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| PROV-01 | Plex metadata provider registers as tv.plex.agents.custom.stash2plex with Match + Metadata features | Plex MediaProvider manifest protocol documented; exact JSON format verified from plexinc/tmdb-example-provider and malvinarum/Plex-Media-Server-Custom-Metadata |
| PROV-05 | Provider deployed as Docker container with configurable Stash/Plex connection settings | FastAPI + uvicorn Docker pattern verified from official FastAPI docs; pydantic-settings YAML+env precedence verified from Context7 |
| INFR-03 | Docker container handles Linux host networking (host.docker.internal workaround) | extra_hosts: host.docker.internal:host-gateway confirmed to work on both Linux (Docker 20.10+) and macOS |
| INFR-04 | Provider configuration via environment variables and/or config file | pydantic-settings YamlConfigSettingsSource + env_settings with settings_customise_sources verified from Context7 |
</phase_requirements>

---

## Summary

Phase 24 builds a FastAPI service in a `provider/` directory that implements the Plex Custom Metadata Provider HTTP protocol and packages it as a Docker container. The Plex protocol is HTTP-REST with a specific JSON shape — verified from the official `plexinc/tmdb-example-provider` TypeScript reference and the `malvinarum/Plex-Media-Server-Custom-Metadata` Cloudflare Worker implementation. All route patterns, type codes, and response envelopes are now confirmed.

The configuration stack is pydantic-settings v2 with `YamlConfigSettingsSource` for the optional YAML file and `EnvSettingsSource` first in the tuple so env vars beat file values. The container wiring is a single-stage `python:3.12-slim` Dockerfile with `uvicorn` (not gunicorn — consistent with the existing project decision in STATE.md). The `extra_hosts: host.docker.internal:host-gateway` entry in docker-compose.yml is the cross-platform fix for Linux (macOS gets it for free from Docker Desktop).

The Plex agent manifest endpoint is a plain GET at the provider's root URL (i.e., `GET /`). Plex POSTs match requests and GETs metadata by ratingKey. For Phase 24 the match and metadata routes return stub-valid empty responses. Stash content is adult video, which Plex models as movies (MetadataType = 1), so the manifest declares `Types: [{ type: 1, Scheme: [...] }]`.

**Primary recommendation:** Build `provider/` as a standard FastAPI package, wire `GET /` as the manifest, `POST /library/metadata/matches` as the stub match, and `GET /library/metadata/{ratingKey}` as the stub metadata. Ship one docker-compose.yml at repo root. Use pydantic-settings with env-first, YAML-file-second precedence.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| fastapi | >=0.115 | HTTP framework + route declarations | Standard async Python API framework; already used in project decision log |
| uvicorn | >=0.30 | ASGI server (single worker) | Locked choice in STATE.md — APScheduler runs N times with gunicorn multi-worker |
| pydantic-settings | >=2.0 | Settings from env vars + YAML file | Pydantic v2 family; YamlConfigSettingsSource covers YAML config |
| python-json-logger | >=3.0 | Structured JSON log output | Mature, maintained (updated Oct 2025); standard approach for FastAPI JSON logs |
| httpx | >=0.27 | Async HTTP for Stash startup health check | Already in requirements-dev.txt from Phase 23; same client as StashClient |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| PyYAML | >=6.0 | Required by pydantic-settings for YamlConfigSettingsSource | Automatically needed when using YAML config source |
| python-multipart | any | FastAPI form handling | Only if POST bodies become multipart; not needed in Phase 24 |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| python-json-logger | structlog | structlog is more powerful but adds complexity; python-json-logger drops into Python's standard logging without structural changes |
| pydantic-settings YAML | manual PyYAML + env.get() | Hand-rolling loses validation, defaults, and type coercion |
| uvicorn direct | fastapi CLI (`fastapi run`) | fastapi CLI wraps uvicorn; either works, but `uvicorn app.main:app` is explicit and debuggable |

**Installation:**
```bash
pip install fastapi uvicorn pydantic-settings python-json-logger PyYAML httpx
```

---

## Architecture Patterns

### Recommended Project Structure

```
provider/
├── __init__.py
├── main.py          # FastAPI app factory + lifespan, mounts routers
├── config.py        # pydantic-settings Settings class (env + YAML)
├── logging_config.py  # JSON formatter setup, called once at startup
├── routes/
│   ├── __init__.py
│   ├── manifest.py   # GET /  → MediaProvider response
│   ├── match.py      # POST /library/metadata/matches → stub
│   ├── metadata.py   # GET /library/metadata/{ratingKey} → stub
│   └── health.py     # GET /health → status JSON
└── models.py        # Pydantic response models (MediaProvider, MediaContainer, etc.)
```

At repo root:
```
docker-compose.yml    # Builds provider/, default port 9090
Dockerfile            # single-stage python:3.12-slim
.dockerignore         # excludes __pycache__, .venv, tests/, *.pyc
```

### Pattern 1: Plex MediaProvider Manifest

**What:** The provider's root endpoint returns a `MediaProvider` JSON object that Plex reads during registration to discover the provider's identifier, supported types, and feature endpoints.

**When to use:** Always — this is the registration contract.

**Verified endpoint shapes (from `plexinc/tmdb-example-provider` and `malvinarum/Plex-Media-Server-Custom-Metadata`):**

```python
# Source: plexinc/tmdb-example-provider, malvinarum/Plex-Media-Server-Custom-Metadata

AGENT_ID = "tv.plex.agents.stash2plex"

# GET /  →  manifest response
{
    "MediaProvider": {
        "identifier": AGENT_ID,
        "title": "Stash2Plex",
        "version": "1.0.0",
        "Types": [
            {
                "type": 1,              # 1 = Movie (Stash scenes = adult videos = movies)
                "Scheme": [{"scheme": AGENT_ID}]
            }
        ],
        "Feature": [
            {
                "type": "match",
                "key": "/library/metadata/matches"
            },
            {
                "type": "metadata",
                "key": "/library/metadata"
            }
        ]
    }
}
```

**Key insight:** `Feature.key` is the URL path Plex will use for that feature's requests. The `key` for `metadata` is the base path; Plex appends `/{ratingKey}` automatically.

### Pattern 2: Plex Match Endpoint (Stub)

**What:** Plex POSTs a JSON body describing a file scan hit to `POST /library/metadata/matches`. The provider returns match candidates. Phase 24 returns an empty candidates array.

```python
# Source: plexinc/tmdb-example-provider tvRoutes.ts, malvinarum worker.js

# POST /library/metadata/matches
# Request body (from Plex):
# { "type": 1, "title": "...", "year": 2021, "filename": "scene-name.mp4" }

# Phase 24 stub response:
{
    "MediaContainer": {
        "offset": 0,
        "totalSize": 0,
        "identifier": "tv.plex.agents.stash2plex",
        "size": 0,
        "Metadata": []
    }
}
```

### Pattern 3: Plex Metadata Endpoint (Stub)

**What:** Plex GETs metadata by ratingKey after a successful match. Phase 24 stubs this with null/empty.

```python
# Source: malvinarum worker.js

# GET /library/metadata/{ratingKey}

# Phase 24 stub response — null metadata signals "no metadata yet"
{
    "MediaContainer": {
        "size": 0,
        "identifier": "tv.plex.agents.stash2plex",
        "Metadata": []
    }
}
```

**ratingKey format constraint (from STATE.md decision log):** Integer scene ID only — `str(scene_id)`. Never embed file paths. Plex URL routing silently breaks on forward slashes in ratingKey. For Phase 24 stub, the ratingKey path parameter is accepted but ignored.

### Pattern 4: FastAPI Lifespan for Startup Work

**What:** Use `@asynccontextmanager` lifespan for startup banner, Stash connectivity check, and config validation. Replaces deprecated `on_startup`.

```python
# Source: FastAPI official docs (fastapi.tiangolo.com/advanced/events/)
from contextlib import asynccontextmanager
from fastapi import FastAPI

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup — runs before accepting requests
    _print_startup_banner()
    await _check_stash_connectivity()
    yield
    # Shutdown — runs after last request
    await stash_client.close()

app = FastAPI(lifespan=lifespan)
```

### Pattern 5: pydantic-settings with YAML + Env Precedence

**What:** env vars beat YAML file beats defaults. Implemented by returning `(env_settings, YamlConfigSettingsSource(cls))` from `settings_customise_sources`.

```python
# Source: Context7 /pydantic/pydantic-settings
from pydantic_settings import (
    BaseSettings,
    YamlConfigSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

class ProviderSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="S2P_",
        yaml_file="/config/provider.yml",
        yaml_file_encoding="utf-8",
    )

    stash_url: str                                  # Required — no default
    stash_api_key: str                              # Required — no default
    plex_url: str = "http://host.docker.internal:32400"
    plex_token: str = ""                            # Empty = skip registration
    provider_port: int = 9090
    log_level: str = "info"
    # Path rules loaded from YAML config file (not env-settable)
    path_rules: list[dict] = []

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            env_settings,                          # Highest priority
            YamlConfigSettingsSource(settings_cls), # File config
            init_settings,                          # Code defaults
        )
```

**Validation note:** Required fields (`stash_url`, `stash_api_key`) with no defaults will raise `pydantic.ValidationError` on startup if missing — fail-fast behavior is built in. Catch this at startup and emit a clear error naming the missing variables before exiting.

### Pattern 6: docker-compose.yml with host.docker.internal on Linux + macOS

```yaml
# Source: Docker docs, Baeldung ops
services:
  provider:
    build:
      context: .          # Repo root — shared_lib/ is COPY-able
      dockerfile: Dockerfile
    ports:
      - "${PROVIDER_PORT:-9090}:9090"
    extra_hosts:
      - "host.docker.internal:host-gateway"   # Linux: maps to host IP; macOS: no-op (already available)
    environment:
      - S2P_STASH_URL=${S2P_STASH_URL}
      - S2P_STASH_API_KEY=${S2P_STASH_API_KEY}
      - S2P_PLEX_URL=${S2P_PLEX_URL:-http://host.docker.internal:32400}
      - S2P_PLEX_TOKEN=${S2P_PLEX_TOKEN:-}
      - S2P_LOG_LEVEL=${S2P_LOG_LEVEL:-info}
    volumes:
      - ./provider_config:/config     # Optional: mount provider.yml here
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9090/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 15s
    restart: unless-stopped
```

**Linux host-gateway requirement:** Docker Engine >= 20.10 is required for `host-gateway` to be resolved. On older engines, use the host IP directly (172.17.0.1). This is acceptable since Docker 20.10 was released in December 2020.

### Pattern 7: Dockerfile (single-stage, python:3.12-slim)

```dockerfile
# Source: FastAPI official Docker docs, betterstack.com/community/guides
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Copy shared_lib first (from repo root build context)
COPY shared_lib/ /app/shared_lib/

# Install dependencies with cache busting
COPY provider/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy provider application code
COPY provider/ /app/provider/

EXPOSE 9090

CMD ["uvicorn", "provider.main:app", "--host", "0.0.0.0", "--port", "9090"]
```

**Note on exec form CMD:** Use JSON array form `["uvicorn", ...]`, not shell form `uvicorn ...`. Exec form is required for graceful shutdown (SIGTERM reaches uvicorn, not a shell wrapper) and for lifespan shutdown events to fire.

### Pattern 8: Structured JSON Logging with python-json-logger

```python
# Source: python-json-logger PyPI, sheshbabu.com/posts/fastapi-structured-json-logging
import logging
from pythonjsonlogger import json as jsonlogger   # python-json-logger >= 3.x

def configure_logging(log_level: str) -> None:
    handler = logging.StreamHandler()
    formatter = jsonlogger.JsonFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        rename_fields={"asctime": "ts", "levelname": "level", "message": "msg"},
    )
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(log_level.upper())
```

**Note on import path:** `python-json-logger` >= 3.0 uses `pythonjsonlogger.json.JsonFormatter`. Pre-3.0 used `pythonjsonlogger.jsonlogger.JsonFormatter`. Pin `python-json-logger>=3.0.0` and use the new import.

### Anti-Patterns to Avoid

- **Shell-form CMD in Dockerfile:** `CMD uvicorn ...` prevents SIGTERM from reaching uvicorn, causing ungraceful shutdown and lost in-flight requests.
- **Hardcoding `172.17.0.1`:** Fragile on non-default Docker networks; use `host-gateway` instead.
- **Forward slashes in ratingKey:** Plex URL routing silently breaks. Always use integer scene ID as a plain string (e.g., `"12345"` not `"/path/to/file"`).
- **`on_startup`/`on_shutdown` events:** Deprecated since FastAPI 0.93. Use `lifespan` context manager.
- **Mounting provider.yml as required:** Must be optional — container must start even if /config/provider.yml doesn't exist. YamlConfigSettingsSource silently skips missing files.
- **Running gunicorn with multiple workers:** APScheduler (used in later phases) runs N times with multi-worker — locked decision from STATE.md.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Settings from env + YAML | Custom os.environ parsing + PyYAML load | pydantic-settings YamlConfigSettingsSource | Type coercion, validation, defaults, precedence all handled |
| JSON log output | Custom logging.Formatter | python-json-logger JsonFormatter | Handles exception serialization, nested fields, field renaming |
| Startup/shutdown hooks | Global state flags + threading.Event | FastAPI lifespan context manager | Clean async resource management, proper shutdown order |
| Config validation with clear errors | try/except os.environ.get | pydantic ValidationError on Settings() | Auto-names missing fields in error message |

**Key insight:** The pydantic-settings ValidationError when required fields are absent already names the missing variables — the only custom work needed is catching it and printing a user-friendly message before `sys.exit(1)`.

---

## Common Pitfalls

### Pitfall 1: Plex Can't Reach Provider URL

**What goes wrong:** Plex running on the host machine (not in Docker) tries to reach the provider via the URL configured in Plex settings. If user configures `http://localhost:9090` on a Linux machine where Plex is on host, the container's port 9090 maps to host's 9090 — this works. But if Plex itself is in Docker (different network), it can't reach `localhost:9090` on the host.

**Why it happens:** Docker port mapping is transparent from host→container but not container→container on different networks. The Phase 24 target topology (same machine, all services on host) means Plex is on the host and the provider is in Docker — host→container port mapping works correctly.

**How to avoid:** Document that the provider URL to register in Plex is `http://localhost:9090` (or `http://host.docker.internal:9090` if Plex is also containerized). The `ports` mapping in docker-compose.yml makes the container's 9090 available on host's 9090.

**Warning signs:** Plex shows "Connection refused" when adding provider URL. Check that `docker-compose ps` shows the container running and `curl http://localhost:9090/health` returns 200 from the host.

### Pitfall 2: MediaProvider manifest served at wrong path

**What goes wrong:** Plex expects the manifest at the root URL the user registers. If the registered URL is `http://localhost:9090/provider`, the manifest must be at `GET http://localhost:9090/provider` (or `GET http://localhost:9090/provider/`). If Feature keys are relative paths like `/library/metadata/matches`, Plex constructs the full URL as `http://localhost:9090/library/metadata/matches` — which bypasses any `/provider` prefix.

**Why it happens:** Plex resolves Feature.key values as absolute paths from the host, not relative to the registered URL.

**How to avoid:** Register the provider URL as bare `http://localhost:9090` (no trailing path). Serve the manifest at `GET /`. Feature keys like `/library/metadata/matches` resolve correctly from the root.

**Warning signs:** Plex shows the provider in the list but match/metadata calls return 404.

### Pitfall 3: ratingKey Contains Forward Slashes

**What goes wrong:** If a ratingKey like `stash/scene/42` is returned from the match endpoint, Plex constructs `GET /library/metadata/stash/scene/42` which the FastAPI router interprets as a nested path, not a ratingKey parameter.

**Why it happens:** HTTP path segments are delimited by `/`. FastAPI `{ratingKey}` path parameters only match up to the next `/`.

**How to avoid:** ratingKey must be `[a-zA-Z0-9_-]+`. For Stash scenes, use integer scene ID as string: `"42"`. Decision is locked in STATE.md.

### Pitfall 4: YamlConfigSettingsSource fails when file absent

**What goes wrong:** If `/config/provider.yml` doesn't exist and pydantic-settings is configured to load it, older versions raise FileNotFoundError. The container fails to start even though the YAML file is optional.

**Why it happens:** pydantic-settings < 2.3 raised on missing YAML file.

**How to avoid:** Use pydantic-settings >= 2.3 (which silently skips missing YAML files). Also handle the case defensively at container startup by checking if the file exists before loading. MEDIUM confidence — verify this behavior in the version being installed.

**Warning signs:** Container exits immediately with FileNotFoundError on startup even when S2P_STASH_URL and S2P_STASH_API_KEY are set.

### Pitfall 5: python-json-logger import changed in v3.x

**What goes wrong:** Code using the old import `from pythonjsonlogger import jsonlogger` fails at startup with ImportError when python-json-logger >= 3.0 is installed.

**Why it happens:** v3.0 renamed the module from `pythonjsonlogger.jsonlogger` to `pythonjsonlogger.json`.

**How to avoid:** Pin `python-json-logger>=3.0.0` and use `from pythonjsonlogger import json as jsonlogger`. Consistent import style avoids silent drift.

### Pitfall 6: host-gateway not available on Docker < 20.10

**What goes wrong:** `extra_hosts: - "host.docker.internal:host-gateway"` fails with "invalid IP address in add-host: host-gateway" on Docker Engine < 20.10.

**Why it happens:** `host-gateway` as a symbolic value was added in Docker 20.10 (December 2020).

**How to avoid:** Document minimum Docker version (20.10+) in README/setup docs. For users on older engines, the fallback is to hardcode `172.17.0.1` (default Docker bridge IP on Linux).

---

## Code Examples

### Minimal FastAPI Provider (verified structure)

```python
# provider/main.py
# Source: FastAPI official docs + Plex protocol from plexinc/tmdb-example-provider

from contextlib import asynccontextmanager
from fastapi import FastAPI
from provider.config import get_settings
from provider.logging_config import configure_logging
from provider.routes import manifest, match, metadata, health

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    _print_startup_banner(settings)
    await _check_stash(settings)
    yield

app = FastAPI(lifespan=lifespan)
app.include_router(manifest.router)
app.include_router(match.router)
app.include_router(metadata.router)
app.include_router(health.router)
```

### Manifest Route (verified Plex protocol)

```python
# provider/routes/manifest.py
# Source: plexinc/tmdb-example-provider TVProvider.ts + malvinarum worker.js

from fastapi import APIRouter
from fastapi.responses import JSONResponse

AGENT_ID = "tv.plex.agents.stash2plex"
router = APIRouter()

@router.get("/")
async def manifest():
    return JSONResponse({
        "MediaProvider": {
            "identifier": AGENT_ID,
            "title": "Stash2Plex",
            "version": "1.0.0",
            "Types": [
                {"type": 1, "Scheme": [{"scheme": AGENT_ID}]}   # 1 = Movie
            ],
            "Feature": [
                {"type": "match",    "key": "/library/metadata/matches"},
                {"type": "metadata", "key": "/library/metadata"},
            ]
        }
    })
```

### Stub Match Route (Phase 24 placeholder)

```python
# provider/routes/match.py
# Source: Plex protocol spec; empty Metadata array = no candidates

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

AGENT_ID = "tv.plex.agents.stash2plex"
router = APIRouter()

@router.post("/library/metadata/matches")
async def match(request: Request):
    body = await request.json()
    return JSONResponse({
        "MediaContainer": {
            "offset": 0,
            "totalSize": 0,
            "identifier": AGENT_ID,
            "size": 0,
            "Metadata": []
        }
    })
```

### Stub Metadata Route (Phase 24 placeholder)

```python
# provider/routes/metadata.py

from fastapi import APIRouter
from fastapi.responses import JSONResponse

AGENT_ID = "tv.plex.agents.stash2plex"
router = APIRouter()

@router.get("/library/metadata/{ratingKey}")
async def metadata(ratingKey: str):
    return JSONResponse({
        "MediaContainer": {
            "size": 0,
            "identifier": AGENT_ID,
            "Metadata": []
        }
    })
```

### Health Endpoint

```python
# provider/routes/health.py

import time
from fastapi import APIRouter
from fastapi.responses import JSONResponse

START_TIME = time.time()
router = APIRouter()

@router.get("/health")
async def health():
    return JSONResponse({
        "status": "ok",
        "version": "1.0.0",
        "uptime_seconds": int(time.time() - START_TIME),
        "stash_reachable": True,   # Set by lifespan startup check
        "plex_registered": False,  # Phase 24: manual registration
    })
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Plex legacy `.bundle` Python 2 agents | HTTP REST Custom Metadata Provider API | ~2024-2025 (announced, beta as of PMS 1.43.0) | No language restriction; any HTTP server works |
| FastAPI `on_startup` / `on_shutdown` events | `lifespan` context manager | FastAPI 0.93 (deprecated), 0.95+ (lifespan preferred) | Cleaner resource management; deprecated path still works |
| `tiangolo/uvicorn-gunicorn-fastapi` Docker image | Official `python:3.X-slim` + `uvicorn` or `fastapi run` | ~2022 (official FastAPI docs updated) | Simpler, no outdated base image lag |
| `pythonjsonlogger.jsonlogger.JsonFormatter` | `pythonjsonlogger.json.JsonFormatter` | python-json-logger 3.0 (Oct 2025) | Breaking rename — must use new import path |

**Deprecated/outdated:**
- `tiangolo/uvicorn-gunicorn-fastapi`: FastAPI docs explicitly say to build from `python:3.X` scratch
- `on_startup` / `on_shutdown` on `FastAPI()`: Use `lifespan` parameter instead

---

## Open Questions

1. **Does Plex send the manifest GET request once or repeatedly?**
   - What we know: Plex discovers the manifest when the user adds the provider URL. Subsequent re-reads are unclear.
   - What's unclear: Whether Plex polls `/` periodically or reads it only once at registration time.
   - Recommendation: Serve the manifest statically from a constant — no database or dynamic generation needed for Phase 24.

2. **Does pydantic-settings >= 2.3 truly silently skip missing YAML files?**
   - What we know: MEDIUM confidence claim from search results; exact version behavior not verified in Context7.
   - What's unclear: The exact pydantic-settings release that introduced silent-skip behavior.
   - Recommendation: Wrap Settings() instantiation in a try/except and check for FileNotFoundError explicitly; log a warning and fall back gracefully if YAML is missing.

3. **Exact Plex PMS version required for Custom Metadata Provider support**
   - What we know: Beta announced ~late 2025, PMS 1.43.0 mentioned. The feature is in beta.
   - What's unclear: Whether beta-channel enrollment is needed or if it's generally available.
   - Recommendation: Document in setup notes that the user needs PMS 1.43.0+ (beta channel may be required). The provider will still run and be reachable; Plex just may not show the "Add Provider" UI on older PMS versions.

4. **Does declaring both Match + Metadata features in the Phase 24 stub cause Plex to error when stubs return empty?**
   - What we know: The community implementations return empty `Metadata: []` from stubs without reported errors.
   - What's unclear: Whether Plex logs a warning or degrades gracefully on empty match results.
   - Recommendation: Stub responses with `Metadata: []` are valid per the protocol (no candidates found). Proceed with stubs. Plex treats 0 candidates as "no match" — a known, handled state.

---

## Sources

### Primary (HIGH confidence)
- `plexinc/tmdb-example-provider` (GitHub) — Official Plex example; MediaProvider.ts type definitions, TVProvider.ts manifest shape, tvRoutes.ts route patterns
- `malvinarum/Plex-Media-Server-Custom-Metadata` (GitHub) — Working Cloudflare Worker implementation; confirmed movie type=1 manifest, match + metadata response shapes
- Context7 `/pydantic/pydantic-settings` — YamlConfigSettingsSource usage, settings_customise_sources precedence, env_prefix
- Context7 `/websites/fastapi_tiangolo` — lifespan context manager, uvicorn single-worker guidance
- FastAPI official docs (fastapi.tiangolo.com/deployment/docker/) — Single-stage Dockerfile, exec-form CMD, python:3.12-slim
- Plex forums announcement (forums.plex.tv/t/announcement-custom-metadata-providers/934384) — Protocol overview, feature types, supported library types
- Baeldung ops / Docker docs — `extra_hosts: host.docker.internal:host-gateway` Linux/macOS cross-platform pattern

### Secondary (MEDIUM confidence)
- betterstack.com FastAPI Docker guide — Non-root user, .dockerignore, docker-compose healthcheck patterns (consistent with official docs)
- python-json-logger PyPI page (nhairs.github.io/python-json-logger/latest/) — v3.x import path change confirmed

### Tertiary (LOW confidence)
- pydantic-settings silent-skip of missing YAML files (exact version boundary) — Needs validation in implementation

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries verified from Context7 official docs or official FastAPI docs
- Plex protocol: HIGH — verified from official Plex example repo + two independent working implementations
- Architecture: HIGH — follows FastAPI idiomatic patterns verified from official docs
- Docker / networking: HIGH — `host-gateway` confirmed from Docker docs via multiple sources
- Pitfalls: MEDIUM-HIGH — most from official docs; YAML silent-skip is MEDIUM (not directly verified)

**Research date:** 2026-02-25
**Valid until:** 2026-05-25 (Plex Custom Provider API is beta — check forums for breaking changes before Phase 25+)
