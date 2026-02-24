# Phase 23: Foundation + Shared Library - Research

**Researched:** 2026-02-23
**Domain:** Python monorepo layout, regex path translation, async GraphQL HTTP client, Pydantic v2 typed models
**Confidence:** HIGH

## Summary

Phase 23 creates the `shared_lib/` package at the repo root and populates it with two modules: a bidirectional regex path mapper (`path_mapper.py`) and an async Stash GraphQL client (`stash_client.py`). All user decisions are locked — the only discretion areas are provider internal directory structure, exact Pydantic model field set, and GraphQL query field selection. Research focuses on confirming the right implementation patterns for those locked choices.

The existing codebase provides strong prior art. The Stash GraphQL query shape is already proven in `hooks/handlers.py` (the `SCENE_QUERY` constant). Pydantic v2 (`2.12.5`) is already installed in the venv. httpx is **not** installed and must be added to `requirements-dev.txt` and eventually the provider's `requirements.txt`. The existing `shared/` package (logging utilities) must not be confused or merged with the new `shared_lib/` package — they are different directories with different purposes.

The critical naming decision is that `shared_lib/` must NOT be named `shared/` — that directory already exists and contains the Stash binary logging protocol (`shared/log.py`). Both packages will coexist and serve separate concerns.

**Primary recommendation:** Create `shared_lib/` at repo root as a standard Python package (`__init__.py`), implement `path_mapper.py` with pure `re` (no third-party regex library), and implement `stash_client.py` using `httpx.AsyncClient` with raw GraphQL POST requests and Pydantic v2 typed return models.

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Path Mapping Config Format**
- Rules defined via **provider environment variables only** (docker-compose.yml)
- Single env var as **JSON array**: `PATH_RULES='[{"name":"nas","plex_pattern":"...","stash_pattern":"..."}]'`
- Each rule has three fields: `name` (human-readable), `plex_pattern` (regex with capture groups), `stash_pattern` (regex with capture groups)
- **Regex only** — no prefix shorthand mode. Simple prefix swaps are just simple regexes. One engine, no ambiguity.

**Monorepo Directory Layout**
- `shared_lib/` at **repo root** — sibling to `provider/`
- Plugin imports via **sys.path manipulation** at startup (Stash2Plex.py adds repo root to sys.path)
- Provider's `requirements.txt` includes all shared dependencies — shared_lib has no separate requirements.txt
- Provider internal directory structure at Claude's discretion

**Stash GraphQL Client Design**
- **Async-only** using httpx (provider is async/FastAPI; plugin uses asyncio.run() when needed)
- **Pydantic models** for return types (StashScene, StashFile, etc.) — consistent with existing config.py pattern
- **Exceptions** for error handling: StashConnectionError, StashQueryError, StashSceneNotFound — matches existing plugin exception pattern (PlexServerDown, PlexNotFound)
- **Direct httpx + raw GraphQL queries** — no stashapp-tools dependency. Write the 3-4 queries needed directly for full control and async-native behavior.

**Path Mapping Behavior**
- **Return None** when no rule matches — caller decides fallback behavior (provider: filename lookup, plugin: log warning)
- **Case-sensitive by default**, with optional `case_insensitive` flag per rule for Windows/SMB paths
- **Normalize backslashes to forward slashes** on input before matching — users write rules with forward slashes only
- **Logging:** Debug-level for all mapping attempts (input → output), info-level for misses — aligns with existing debug_logging toggle pattern

### Claude's Discretion
- Provider internal directory structure (flat routes/ + mappers/ + gap/, or deeper nesting)
- Exact Pydantic model field definitions for StashScene/StashFile
- GraphQL query structure and field selection

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| INFR-01 | Monorepo structure with shared_lib/ package importable by both plugin and provider | Standard Python package layout with `__init__.py`; sys.path injection in Stash2Plex.py; Docker COPY from repo root context |
| INFR-02 | Stash GraphQL client in shared_lib/ queries scenes by path and by ID | Proven GraphQL query shape already in hooks/handlers.py SCENE_QUERY; httpx.AsyncClient POST with json payload; Pydantic v2 typed returns |
| PATH-01 | Regex-based bidirectional path mapping translates Plex library paths to Stash scene paths and vice versa | Python stdlib `re` module; capture groups enable bidirectional substitution via re.sub() with group references |
| PATH-02 | Path mapping supports multiple named rules applied in order | List of rule dicts evaluated in array order; first re.match() that succeeds wins; return None on exhaustion |
</phase_requirements>

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python `re` | stdlib | Regex path matching and substitution | No dependency, zero risk, sufficient for all path pattern needs |
| `pydantic` | 2.12.5 (already installed) | Typed models for StashScene, StashFile, PathRule | Already in project; v2 already used for Stash2PlexConfig; consistent pattern |
| `httpx` | latest stable (~0.28.x) | Async HTTP client for Stash GraphQL | Async-native (asyncio compatible); superior to requests for async contexts; officially recommended for FastAPI async services |
| Python `json` | stdlib | Parsing PATH_RULES env var | No dependency needed |
| Python `logging` | stdlib | Debug/info logging per locked decision | Already the project standard |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `pytest-asyncio` | latest (~0.25.x) | Test async functions without asyncio.run() boilerplate | Required to test stash_client.py functions as async tests |
| `respx` | latest (~0.22.x) | Mock httpx AsyncClient in tests | The standard companion library for mocking httpx; same author ecosystem |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `httpx` | `aiohttp` | aiohttp is older, larger API surface, less FastAPI-idiomatic; httpx is the correct pairing for FastAPI |
| `httpx` | `requests` + `asyncio.run()` | requests is synchronous-only; would require thread executors in async provider code |
| Raw `re` | `regex` (PyPI) | `regex` adds Unicode features not needed here; stdlib `re` is sufficient and zero-dependency |

**Installation (to add to requirements-dev.txt):**
```bash
pip install httpx pytest-asyncio respx
```

**Provider requirements.txt will include:**
```
httpx>=0.27.0
pydantic>=2.0.0
fastapi
uvicorn
```

---

## Architecture Patterns

### Recommended Project Structure

```
shared_lib/               # New package — repo root sibling to provider/
├── __init__.py           # Empty or minimal; marks as package
├── path_mapper.py        # PathRule model + PathMapper class
└── stash_client.py       # StashClient class + StashScene/StashFile models

provider/                 # Created in Phase 24 (not this phase)
└── requirements.txt      # Will list httpx, pydantic, fastapi, uvicorn

shared/                   # EXISTING — do not modify
├── __init__.py
└── log.py                # Stash binary logging protocol (keep separate)

Stash2Plex.py             # Add sys.path injection for repo root
tests/
└── shared_lib/           # New test directory for Phase 23 tests
    ├── __init__.py
    ├── test_path_mapper.py
    └── test_stash_client.py
```

### Pattern 1: Python Package — sys.path Injection (Plugin Side)

**What:** The Stash plugin process adds the repo root to `sys.path` at startup so `import shared_lib` resolves.
**When to use:** Plugin side only. Provider gets `shared_lib/` via Docker COPY (build context = repo root).

```python
# In Stash2Plex.py — add after PLUGIN_DIR is set
REPO_ROOT = os.path.dirname(PLUGIN_DIR)  # parent of plugin dir
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
# Now: from shared_lib.path_mapper import PathMapper  # works
```

**Codebase note:** `PLUGIN_DIR` is already computed as `os.path.dirname(os.path.abspath(__file__))`. Since `Stash2Plex.py` lives at the repo root (same level as `shared_lib/`), `PLUGIN_DIR` IS the repo root. So the injection is simply `sys.path.insert(0, PLUGIN_DIR)` — which already happens. No change needed: `from shared_lib.path_mapper import PathMapper` will already work once `shared_lib/` exists.

### Pattern 2: PathRule Pydantic Model + PathMapper Class

**What:** Pydantic model validates each rule dict; PathMapper holds an ordered list of rules and exposes `plex_to_stash()` and `stash_to_plex()` methods.
**When to use:** This is the locked design.

```python
# Source: derived from existing validation/config.py pattern + Python re stdlib
from pydantic import BaseModel
from typing import Optional
import re
import logging

log = logging.getLogger("shared_lib.path_mapper")

class PathRule(BaseModel):
    name: str
    plex_pattern: str       # regex with capture groups
    stash_pattern: str      # regex with capture groups
    case_insensitive: bool = False

class PathMapper:
    def __init__(self, rules: list[PathRule]):
        self._rules = rules
        # Pre-compile regexes at init time for performance
        self._plex_compiled = [
            re.compile(r.plex_pattern, re.IGNORECASE if r.case_insensitive else 0)
            for r in rules
        ]
        self._stash_compiled = [
            re.compile(r.stash_pattern, re.IGNORECASE if r.case_insensitive else 0)
            for r in rules
        ]

    def _normalize(self, path: str) -> str:
        """Normalize backslashes to forward slashes."""
        return path.replace("\\", "/")

    def plex_to_stash(self, plex_path: str) -> Optional[str]:
        """Translate Plex path to Stash path. Returns None if no rule matches."""
        path = self._normalize(plex_path)
        for rule, plex_re, stash_re in zip(self._rules, self._plex_compiled, self._stash_compiled):
            match = plex_re.match(path)
            if match:
                # Use stash_pattern as replacement template with captured groups
                result = plex_re.sub(rule.stash_pattern, path)
                log.debug(f"path_mapper: plex→stash via rule '{rule.name}': {path!r} → {result!r}")
                return result
        log.info(f"path_mapper: no rule matched plex path {path!r}")
        return None

    def stash_to_plex(self, stash_path: str) -> Optional[str]:
        """Translate Stash path to Plex path. Returns None if no rule matches."""
        path = self._normalize(stash_path)
        for rule, plex_re, stash_re in zip(self._rules, self._plex_compiled, self._stash_compiled):
            match = stash_re.match(path)
            if match:
                result = stash_re.sub(rule.plex_pattern, path)
                log.debug(f"path_mapper: stash→plex via rule '{rule.name}': {path!r} → {result!r}")
                return result
        log.info(f"path_mapper: no rule matched stash path {path!r}")
        return None

    @classmethod
    def from_env(cls, env_value: str) -> "PathMapper":
        """Parse PATH_RULES JSON env var into a PathMapper."""
        import json
        raw = json.loads(env_value)
        rules = [PathRule(**r) for r in raw]
        return cls(rules)
```

### Pattern 3: Async Stash GraphQL Client

**What:** `httpx.AsyncClient` sends raw GraphQL POST requests. Returns typed Pydantic models.
**When to use:** This is the locked design. Plugin calls via `asyncio.run()`.

```python
# Source: httpx official docs (Context7 /encode/httpx) + existing SCENE_QUERY in hooks/handlers.py
import httpx
from pydantic import BaseModel
from typing import Optional
import logging

log = logging.getLogger("shared_lib.stash_client")

# ── Exceptions (mirrors PlexServerDown / PlexNotFound pattern) ─────────────
class StashConnectionError(Exception):
    """Stash server unreachable."""

class StashQueryError(Exception):
    """GraphQL query returned an errors field."""

class StashSceneNotFound(Exception):
    """Scene not found (findScene returned null)."""

# ── Typed return models ────────────────────────────────────────────────────
class StashFile(BaseModel):
    path: str

class StashScene(BaseModel):
    id: str
    title: Optional[str] = None
    details: Optional[str] = None
    date: Optional[str] = None
    rating100: Optional[int] = None
    files: list[StashFile] = []
    studio_name: Optional[str] = None   # flattened from studio.name
    performer_names: list[str] = []     # flattened from performers[].name
    tag_names: list[str] = []           # flattened from tags[].name
    screenshot_url: Optional[str] = None  # from paths.screenshot
    preview_url: Optional[str] = None    # from paths.preview

# ── GraphQL queries (proven shape from hooks/handlers.py SCENE_QUERY) ──────
_FIND_SCENE_BY_ID = """
query FindScene($id: ID!) {
    findScene(id: $id) {
        id title details date rating100
        files { path }
        studio { name }
        performers { name }
        tags { name }
        paths { screenshot preview }
    }
}
"""

_FIND_SCENES_BY_PATH = """
query FindScenesByPath($path: String!) {
    findScenes(scene_filter: { path: { value: $path, modifier: EQUALS } }) {
        scenes {
            id title details date rating100
            files { path }
            studio { name }
            performers { name }
            tags { name }
            paths { screenshot preview }
        }
    }
}
"""

class StashClient:
    def __init__(self, stash_url: str, api_key: Optional[str] = None, timeout: float = 10.0):
        self._url = stash_url.rstrip("/") + "/graphql"
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["ApiKey"] = api_key
        self._client = httpx.AsyncClient(
            headers=headers,
            timeout=httpx.Timeout(timeout, connect=5.0)
        )

    async def close(self):
        await self._client.aclose()

    async def _gql(self, query: str, variables: dict) -> dict:
        try:
            resp = await self._client.post(self._url, json={"query": query, "variables": variables})
            resp.raise_for_status()
        except httpx.ConnectError as e:
            raise StashConnectionError(f"Cannot reach Stash at {self._url}: {e}") from e
        except httpx.TimeoutException as e:
            raise StashConnectionError(f"Stash request timed out: {e}") from e
        data = resp.json()
        if "errors" in data:
            raise StashQueryError(f"Stash GraphQL errors: {data['errors']}")
        return data.get("data", {})

    async def find_scene_by_id(self, scene_id: str | int) -> StashScene:
        data = await self._gql(_FIND_SCENE_BY_ID, {"id": str(scene_id)})
        raw = data.get("findScene")
        if not raw:
            raise StashSceneNotFound(f"No scene with id={scene_id}")
        return _parse_scene(raw)

    async def find_scene_by_path(self, path: str) -> Optional[StashScene]:
        data = await self._gql(_FIND_SCENES_BY_PATH, {"path": path})
        scenes = data.get("findScenes", {}).get("scenes", [])
        return _parse_scene(scenes[0]) if scenes else None

def _parse_scene(raw: dict) -> StashScene:
    return StashScene(
        id=raw["id"],
        title=raw.get("title"),
        details=raw.get("details"),
        date=raw.get("date"),
        rating100=raw.get("rating100"),
        files=[StashFile(path=f["path"]) for f in raw.get("files", [])],
        studio_name=raw.get("studio", {}).get("name") if raw.get("studio") else None,
        performer_names=[p["name"] for p in raw.get("performers", []) if p.get("name")],
        tag_names=[t["name"] for t in raw.get("tags", []) if t.get("name")],
        screenshot_url=raw.get("paths", {}).get("screenshot"),
        preview_url=raw.get("paths", {}).get("preview"),
    )
```

### Pattern 4: Docker Build Context — Repo Root

**What:** `docker-compose.yml` sets `context: .` (repo root) and uses `COPY shared_lib/ /app/shared_lib/` in the Dockerfile.
**When to use:** This is the locked design. Required so the provider container can import `shared_lib`.

```yaml
# docker-compose.yml (scaffold — full file in Phase 24)
services:
  provider:
    build:
      context: .           # repo root — shared_lib/ is available here
      dockerfile: provider/Dockerfile
```

```dockerfile
# provider/Dockerfile (scaffold — full file in Phase 24)
COPY shared_lib/ /app/shared_lib/
COPY provider/ /app/
WORKDIR /app
RUN pip install -r requirements.txt
```

### Anti-Patterns to Avoid

- **Naming `shared_lib/` as `shared/`:** The `shared/` directory already exists at repo root with `log.py`. Creating a new `shared/` would shadow or collide with it and break all existing imports of `shared.log`.
- **Using `re.fullmatch()` for path matching:** Rules should use `re.sub()` (not `re.fullmatch` + manual group reconstruction) because sub() supports backreference replacement syntax (`\1`, `\2`) natively and handles the full path transformation in one call.
- **Bidirectional using a single pattern per rule:** The design uses both `plex_pattern` and `stash_pattern` as both match and replacement templates. When going plex→stash: match with `plex_pattern`, substitute using `stash_pattern` as the repl string. When going stash→plex: match with `stash_pattern`, substitute using `plex_pattern` as the repl string. This is the bidirectional engine design.
- **Creating a separate `requirements.txt` inside `shared_lib/`:** Locked decision: provider's `requirements.txt` lists all shared dependencies. No separate file for `shared_lib/`.
- **Using stashapp-tools in shared_lib:** Locked decision: raw httpx queries only. stashapp-tools uses synchronous requests under the hood and is not async-native.
- **Making StashClient a module-level singleton:** Provider is long-running and must be able to close the httpx client cleanly. Use dependency injection (FastAPI `Depends`) in Phase 24, not a module-level global.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| HTTP async POST to GraphQL | Custom socket/urllib async wrapper | `httpx.AsyncClient` | Handles connection pooling, timeouts, TLS, redirects correctly |
| JSON env var parsing | Manual string splitting | `json.loads()` + Pydantic model validation | stdlib + Pydantic catches malformed rules with clear error messages |
| Regex compilation caching | dict-based compile cache | Pre-compile at `PathMapper.__init__` time | Eliminates re-compilation cost per request; correct place for one-time work |
| Mock httpx in tests | Custom `AsyncMock` with response attributes | `respx` library | respx is purpose-built for mocking httpx, handles async context managers correctly |

**Key insight:** The path mapping engine is 50 lines of pure Python. The complexity is in the regex semantics (bidirectional substitution), not infrastructure — don't over-engineer.

---

## Common Pitfalls

### Pitfall 1: `re.sub()` Replacement String Backreference Syntax

**What goes wrong:** User writes a stash_pattern like `/stash/media/\1` expecting Python to substitute group 1. But `re.sub(plex_pattern, stash_pattern, path)` uses the _replacement string_ as a Python regex replacement where `\1` works — but only if using raw strings `r"\1"`. When read from JSON, the string arrives as a plain string with a literal backslash-1.

**Why it happens:** JSON `"stash_pattern": "/stash/\\1"` arrives in Python as the string `/stash/\1`. Python's `re.sub` replacement string uses `\1` to mean group 1. This actually works correctly — JSON double-escaping `\\1` in the file becomes the Python string `\1` which re.sub interprets as group 1. Users must write `\\1` in JSON.

**How to avoid:** Document clearly in user-facing config examples that capture group references in JSON must be written as `\\1`, `\\2`, etc. Add a validator test that checks round-trip with a known rule.

**Warning signs:** Path mapper returns the literal string `/stash/\1` instead of the substituted path value.

### Pitfall 2: `re.match()` Only Matches at String Start

**What goes wrong:** `re.match(pattern, path)` anchors to the start of the string. If the user omits `^` from their pattern, it still anchors. But if they also omit `$` or `(.*)` at the end, the match succeeds on a prefix — and `re.sub()` will substitute only the matched prefix, leaving the tail of the path.

**Why it happens:** `re.match` matches from the start but not necessarily the full string. `re.sub` replaces _all_ occurrences of the pattern in the string, not just the first.

**How to avoid:** Use `re.sub(pattern, repl, path, count=1)` to replace only the first occurrence. Validate in tests that a rule matching `/plex/media/` doesn't corrupt `/plex/media/dir/file.mkv`. The correct pattern for a prefix swap is `^/plex/media/(.*)` → `/stash/media/\1`.

**Warning signs:** Path output is correct for simple single-segment paths but wrong for nested paths.

### Pitfall 3: `shared/` vs `shared_lib/` Import Confusion

**What goes wrong:** Developers (or Claude in future sessions) attempt `from shared.path_mapper import ...` because `shared/` already exists.

**Why it happens:** The existing `shared/` package is a thin logging utility that predates v2.0. The new `shared_lib/` package contains the cross-service infrastructure.

**How to avoid:** The `__init__.py` of `shared_lib/` should have a clear docstring stating its purpose. Never add v2.0 modules to the existing `shared/` directory.

### Pitfall 4: asyncio.run() in Plugin Context

**What goes wrong:** The Stash plugin is synchronous (stdin JSON protocol, short-lived process). Calling `asyncio.run(stash_client.find_scene_by_id(123))` works in isolation but will raise `RuntimeError: This event loop is already running` if there's already an event loop active in the Stash process.

**Why it happens:** Some Stash plugin helper methods internally use asyncio. If the plugin already has a running loop, `asyncio.run()` cannot nest.

**How to avoid:** For Phase 23, `stash_client.py` is async-only by design. The plugin (Phase 23 scope is just import verification) does not need to call StashClient at all yet. When the plugin does call StashClient in a later phase, use `asyncio.get_event_loop().run_until_complete()` or check for a running loop first. Document this constraint in stash_client.py's module docstring.

**Warning signs:** `RuntimeError: This event loop is already running` in plugin logs.

### Pitfall 5: Stash GraphQL Field Names — Path Query

**What goes wrong:** The `findScenes` query with a path filter may use different filter argument names depending on the Stash version.

**Why it happens:** STATE.md explicitly flags: "Stash GraphQL field names for scene paths (`files { path }` vs `paths { ... }`) need verification against local instance before implementing stash_client." The `files { path }` field is used in the existing `SCENE_QUERY` in `hooks/handlers.py` and is confirmed working. The path-filter argument for `findScenes` is less certain.

**How to avoid:** The existing `hooks/handlers.py` SCENE_QUERY already confirms `files { path }` and `paths { screenshot preview }` work. Use those exact field names. For the path filter on `findScenes`, use `scene_filter: { path: { value: $path, modifier: EQUALS } }` — this is the filter shape used by stashapp-tools internally. Flag in stash_client.py docstring that this query needs live validation in Phase 25.

**Warning signs:** GraphQL `errors` array in the response containing "Unknown argument" or "Cannot query field".

---

## Code Examples

### Path Mapper — ENV Parse and Use

```python
# Source: locked design from CONTEXT.md + stdlib json
import os, json
from shared_lib.path_mapper import PathMapper, PathRule

rules_json = os.environ.get("PATH_RULES", "[]")
mapper = PathMapper.from_env(rules_json)

# Forward: Plex path → Stash path
stash_path = mapper.plex_to_stash("/plex/media/video.mkv")
# Returns None if no rule matches

# Reverse: Stash path → Plex path
plex_path = mapper.stash_to_plex("/stash/media/video.mkv")
```

### Stash Client — Async Usage

```python
# Source: httpx official docs (Context7 /encode/httpx) + locked design
import asyncio
from shared_lib.stash_client import StashClient, StashSceneNotFound

async def example():
    client = StashClient("http://localhost:9999", api_key="abc123")
    try:
        scene = await client.find_scene_by_id(42)
        print(scene.title, scene.files[0].path)
    except StashSceneNotFound:
        print("not found")
    finally:
        await client.close()

# Plugin sync usage:
asyncio.run(example())
```

### httpx AsyncClient — Confirmed Pattern

```python
# Source: Context7 /encode/httpx async docs
import httpx

async with httpx.AsyncClient(
    base_url='http://stash:9999',
    headers={'ApiKey': 'token123'},
    timeout=httpx.Timeout(10.0, connect=5.0)
) as client:
    response = await client.post('/graphql', json={
        "query": "query { findScene(id: \"1\") { id title } }",
        "variables": {}
    })
    response.raise_for_status()
    data = response.json()
```

### pytest-asyncio — Async Test Pattern

```python
# Pattern for testing stash_client.py
import pytest
import respx
import httpx
from shared_lib.stash_client import StashClient, StashSceneNotFound

@pytest.mark.asyncio
async def test_find_scene_by_id_found():
    with respx.mock:
        respx.post("http://stash:9999/graphql").mock(
            return_value=httpx.Response(200, json={
                "data": {"findScene": {"id": "42", "title": "Test Scene", "files": [], ...}}
            })
        )
        client = StashClient("http://stash:9999")
        scene = await client.find_scene_by_id(42)
        assert scene.title == "Test Scene"
        await client.close()
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| stashapp-tools for all Stash queries (synchronous) | Direct httpx + raw GraphQL (async-native) | v2.0 design decision | Provider can handle concurrent Plex scan requests without thread pool overhead |
| Single monolithic plugin script | Shared library layer importable by plugin + provider | Phase 23 | Code sharing without duplication across services |
| Pydantic v1 style validators | Pydantic v2 `@field_validator`, `model_config` | v2 already in project | Type-safe models with fast validation core (pydantic-core Rust) |

**Deprecated/outdated:**
- `stashapp-tools` dependency for shared_lib: was used by existing plugin for synchronous queries; explicitly excluded from shared_lib by locked decision

---

## Open Questions

1. **Stash path filter query exact syntax**
   - What we know: `files { path }` confirmed working from hooks/handlers.py SCENE_QUERY. `findScenes` with `scene_filter` is the standard Stash filter pattern used by stashapp-tools.
   - What's unclear: The exact modifier syntax (`EQUALS` vs `INCLUDES`) for path filter is not verified against a live Stash instance. STATE.md flags this as a known concern for Phase 25.
   - Recommendation: Implement with `EQUALS` modifier (most specific). Document in stash_client.py that Phase 25 must validate against a live Stash instance before relying on `find_scene_by_path()`.

2. **httpx version pinning**
   - What we know: httpx is not in the current venv. Provider requirements.txt doesn't exist yet (Phase 24 creates it).
   - What's unclear: Whether the provider will use a locked version or a range.
   - Recommendation: Add `httpx>=0.27.0` to requirements-dev.txt now (for testing shared_lib). Provider requirements.txt is Phase 24 scope.

3. **pytest-asyncio configuration mode**
   - What we know: pytest-asyncio requires either `asyncio_mode = "auto"` in pytest.ini or `@pytest.mark.asyncio` on each test. The existing pytest.ini does not have asyncio_mode set.
   - What's unclear: Whether to add `asyncio_mode = "auto"` (affects all tests) or use per-test markers.
   - Recommendation: Use `@pytest.mark.asyncio` per test in the new `tests/shared_lib/` directory to avoid interfering with existing synchronous tests. Add `asyncio_mode = "strict"` under `[pytest]` or leave default (markers required). Do NOT set `asyncio_mode = "auto"` — it would affect all 22+ existing tests.

---

## Sources

### Primary (HIGH confidence)
- Context7 `/encode/httpx` — async client, POST JSON, timeout configuration, AsyncClient patterns
- Context7 `/websites/pydantic_dev_2_12` — BaseModel, Optional fields, field validators (v2.12)
- `/Users/trekkie/projects/Stash2Plex/hooks/handlers.py` — confirmed Stash GraphQL query shape (SCENE_QUERY), field names `files { path }`, `paths { screenshot preview }`, `studio { name }`, `performers { name }`, `tags { name }`
- `/Users/trekkie/projects/Stash2Plex/validation/config.py` — established Pydantic v2 model pattern for this project
- `/Users/trekkie/projects/Stash2Plex/plex/exceptions.py` — established exception hierarchy pattern (PlexServerDown, PlexNotFound) that StashClient exceptions mirror

### Secondary (MEDIUM confidence)
- `.planning/STATE.md` — locked architectural decisions (ratingKey as integer, Docker build context = repo root, host.docker.internal Linux concern)
- `.planning/phases/23-foundation-shared-library/23-CONTEXT.md` — all locked user decisions
- Existing `shared/` directory inspection — confirms `shared_lib/` is the correct new name (avoids collision)

### Tertiary (LOW confidence)
- `findScenes` path filter modifier `EQUALS` — inferred from stashapp-tools usage patterns; needs live Stash validation (flagged in STATE.md as Phase 25 concern)

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — httpx is well-documented, pydantic v2 already confirmed in venv, re is stdlib
- Architecture: HIGH — existing codebase provides proven patterns; directory layout decisions are locked
- Pitfalls: HIGH — re.sub() backreference semantics and shared/ collision verified by direct inspection; asyncio nesting is a known Python constraint
- GraphQL field names: MEDIUM — `files { path }` and `paths { screenshot }` confirmed in existing code; `findScenes` path filter needs live validation

**Research date:** 2026-02-23
**Valid until:** 2026-03-23 (stable domain; httpx and pydantic APIs are stable)
