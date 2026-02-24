"""
shared_lib.stash_client — Async Stash GraphQL client.

Design notes:
- Async-only: all public methods are coroutines. Plugin code calls via asyncio.run().
- Uses httpx.AsyncClient for async HTTP. Caller must call close() when done.
- Returns typed Pydantic models (StashScene, StashFile) so callers get IDE support
  and validation without coupling to raw GraphQL dict shapes.
- Phase 25 live validation need: the findScenes path filter (EQUALS modifier) needs
  verification against a real Stash instance — the exact GraphQL field names and
  modifier syntax may differ. See STATE.md concerns.

Exports:
    StashClient          -- async GraphQL client
    StashScene           -- typed Pydantic model for a Stash scene
    StashFile            -- typed Pydantic model for a scene file
    StashConnectionError -- Stash server unreachable or timed out
    StashQueryError      -- GraphQL response contained errors
    StashSceneNotFound   -- findScene returned null (scene ID not found)
"""

from __future__ import annotations

import logging
from typing import Optional

import httpx
from pydantic import BaseModel

log = logging.getLogger("shared_lib.stash_client")


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class StashConnectionError(Exception):
    """
    Stash server is unreachable or the request timed out.

    Covers both connection failures (ConnectError) and timeouts
    (TimeoutException) — both represent an unavailable server from
    the caller's perspective.
    """


class StashQueryError(Exception):
    """
    GraphQL response contained an errors array.

    Raised when Stash returns HTTP 200 but the response body has
    ``{"errors": [...]}`` — indicating a bad query or server-side error.
    """


class StashSceneNotFound(Exception):
    """
    findScene returned null — the scene ID does not exist in Stash.
    """


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class StashFile(BaseModel):
    """A single file associated with a Stash scene."""

    path: str


class StashScene(BaseModel):
    """
    Typed Stash scene model with flattened nested fields.

    Nested GraphQL structures (studio, performers, tags, paths) are
    flattened into scalar/list fields for ergonomic access.
    """

    id: str
    title: Optional[str] = None
    details: Optional[str] = None  # Maps to Plex summary / description
    date: Optional[str] = None
    rating100: Optional[int] = None
    files: list[StashFile] = []

    # Flattened from nested GraphQL objects
    studio_name: Optional[str] = None          # from studio.name
    performer_names: list[str] = []            # from performers[].name
    tag_names: list[str] = []                  # from tags[].name
    screenshot_url: Optional[str] = None       # from paths.screenshot
    preview_url: Optional[str] = None          # from paths.preview


# ---------------------------------------------------------------------------
# GraphQL query strings
# ---------------------------------------------------------------------------

_FIND_SCENE_BY_ID = """
query FindScene($id: ID!) {
    findScene(id: $id) {
        id
        title
        details
        date
        rating100
        files {
            path
        }
        studio {
            name
        }
        performers {
            name
        }
        tags {
            name
        }
        paths {
            screenshot
            preview
        }
    }
}
"""

_FIND_SCENES_BY_PATH = """
query FindScenesByPath($path: String!) {
    findScenes(
        scene_filter: {
            path: { value: $path, modifier: EQUALS }
        }
    ) {
        scenes {
            id
            title
            details
            date
            rating100
            files {
                path
            }
            studio {
                name
            }
            performers {
                name
            }
            tags {
                name
            }
            paths {
                screenshot
                preview
            }
        }
    }
}
"""
# NOTE: Path filter needs live validation against a Stash instance in Phase 25.
# The EQUALS modifier and exact field name may differ from live API behaviour.
# See STATE.md concerns: "Stash GraphQL field names for scene paths need verification".


# ---------------------------------------------------------------------------
# Parse helper
# ---------------------------------------------------------------------------


def _parse_scene(raw: dict) -> StashScene:
    """
    Flatten a raw GraphQL scene dict into a typed StashScene model.

    Args:
        raw: Raw scene dict from GraphQL response (findScene or findScenes.scenes[0]).

    Returns:
        StashScene with all nested fields flattened.
    """
    studio_node = raw.get("studio")
    studio_name = studio_node.get("name") if studio_node else None

    performer_names = [p["name"] for p in (raw.get("performers") or [])]
    tag_names = [t["name"] for t in (raw.get("tags") or [])]

    paths_node = raw.get("paths") or {}
    screenshot_url = paths_node.get("screenshot")
    preview_url = paths_node.get("preview")

    files = [StashFile(path=f["path"]) for f in (raw.get("files") or [])]

    return StashScene(
        id=raw["id"],
        title=raw.get("title"),
        details=raw.get("details"),
        date=raw.get("date"),
        rating100=raw.get("rating100"),
        files=files,
        studio_name=studio_name,
        performer_names=performer_names,
        tag_names=tag_names,
        screenshot_url=screenshot_url,
        preview_url=preview_url,
    )


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class StashClient:
    """
    Async GraphQL client for querying the Stash server.

    Usage (plugin, synchronous context)::

        import asyncio
        from shared_lib.stash_client import StashClient

        client = StashClient("http://localhost:9999", api_key="my-key")
        scene = asyncio.run(client.find_scene_by_id(42))
        asyncio.run(client.close())

    Usage (async context)::

        async with contextlib.asynccontextmanager ...:
            client = StashClient(url)
            try:
                scene = await client.find_scene_by_id(42)
            finally:
                await client.close()
    """

    def __init__(
        self,
        stash_url: str,
        api_key: Optional[str] = None,
        timeout: float = 10.0,
    ) -> None:
        """
        Create the async Stash GraphQL client.

        Args:
            stash_url:  Base URL of the Stash server, e.g. ``http://localhost:9999``.
                        Trailing slashes are stripped automatically.
            api_key:    Optional Stash API key. Sent as ``ApiKey`` header when provided.
            timeout:    Total request timeout in seconds (default 10). Connect
                        timeout is fixed at 5 seconds.
        """
        self._url = stash_url.rstrip("/") + "/graphql"

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if api_key:
            headers["ApiKey"] = api_key

        self._client = httpx.AsyncClient(
            headers=headers,
            timeout=httpx.Timeout(timeout, connect=5.0),
        )
        log.debug("StashClient initialised — url=%s api_key=%s", self._url, bool(api_key))

    async def close(self) -> None:
        """Close the underlying httpx client and release connections."""
        await self._client.aclose()

    async def _gql(self, query: str, variables: dict) -> dict:
        """
        Execute a GraphQL query against Stash.

        Args:
            query:     GraphQL query string.
            variables: Variable dict to pass alongside the query.

        Returns:
            The ``data`` dict from the GraphQL response.

        Raises:
            StashConnectionError: Server unreachable or request timed out.
            StashQueryError:      Response contained a GraphQL ``errors`` array.
        """
        try:
            resp = await self._client.post(
                self._url,
                json={"query": query, "variables": variables},
            )
        except httpx.ConnectError as exc:
            raise StashConnectionError(f"Cannot connect to Stash: {exc}") from exc
        except httpx.TimeoutException as exc:
            raise StashConnectionError(f"Stash request timed out: {exc}") from exc

        resp.raise_for_status()

        body = resp.json()
        if "errors" in body:
            messages = "; ".join(e.get("message", str(e)) for e in body["errors"])
            raise StashQueryError(f"GraphQL errors: {messages}")

        return body.get("data", {})

    async def find_scene_by_id(self, scene_id: str | int) -> StashScene:
        """
        Fetch a Stash scene by its ID.

        Args:
            scene_id: Scene ID as string or int. Converted to string before
                      being sent in GraphQL variables.

        Returns:
            StashScene with typed, flattened fields.

        Raises:
            StashSceneNotFound:   findScene returned null (scene does not exist).
            StashConnectionError: Server unreachable or timed out.
            StashQueryError:      GraphQL response contained errors.
        """
        data = await self._gql(_FIND_SCENE_BY_ID, {"id": str(scene_id)})
        raw = data.get("findScene")
        if raw is None:
            raise StashSceneNotFound(f"Scene {scene_id} not found in Stash")
        return _parse_scene(raw)

    async def find_scene_by_path(self, path: str) -> Optional[StashScene]:
        """
        Fetch the first Stash scene whose file path exactly matches *path*.

        NOTE: The path filter (EQUALS modifier) needs live validation against a
        Stash instance in Phase 25. The exact GraphQL field names and modifier
        syntax may differ from the live API. See STATE.md concerns.

        Args:
            path: Absolute file path to search for.

        Returns:
            StashScene if a matching scene is found, None otherwise.

        Raises:
            StashConnectionError: Server unreachable or timed out.
            StashQueryError:      GraphQL response contained errors.
        """
        data = await self._gql(_FIND_SCENES_BY_PATH, {"path": path})
        scenes = data.get("findScenes", {}).get("scenes", [])
        if not scenes:
            return None
        return _parse_scene(scenes[0])
