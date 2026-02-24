"""
Tests for shared_lib.stash_client — async Stash GraphQL client.

Uses respx to mock httpx requests so no live Stash instance is required.
All tests require @pytest.mark.asyncio (asyncio_mode = strict in pytest.ini).
"""

import pytest
import httpx
import respx

from shared_lib.stash_client import (
    StashClient,
    StashScene,
    StashFile,
    StashConnectionError,
    StashQueryError,
    StashSceneNotFound,
)

# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

STASH_URL = "http://stash:9999"
GRAPHQL_URL = "http://stash:9999/graphql"

FULL_SCENE_RESPONSE = {
    "data": {
        "findScene": {
            "id": "123",
            "title": "Test Scene",
            "details": "A test scene description",
            "date": "2024-01-15",
            "rating100": 85,
            "files": [{"path": "/media/stash/video.mp4"}],
            "studio": {"name": "Test Studio"},
            "performers": [
                {"name": "Alice"},
                {"name": "Bob"},
            ],
            "tags": [
                {"name": "action"},
                {"name": "drama"},
            ],
            "paths": {
                "screenshot": "http://stash:9999/scene/123/screenshot",
                "preview": "http://stash:9999/scene/123/preview",
            },
        }
    }
}

FIND_SCENES_RESPONSE = {
    "data": {
        "findScenes": {
            "scenes": [
                {
                    "id": "456",
                    "title": "Path Scene",
                    "details": "Found by path",
                    "date": "2024-03-20",
                    "rating100": 70,
                    "files": [{"path": "/media/stash/other.mp4"}],
                    "studio": {"name": "Another Studio"},
                    "performers": [{"name": "Carol"}],
                    "tags": [{"name": "comedy"}],
                    "paths": {
                        "screenshot": "http://stash:9999/scene/456/screenshot",
                        "preview": "http://stash:9999/scene/456/preview",
                    },
                }
            ]
        }
    }
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_find_scene_by_id_success():
    """find_scene_by_id returns a typed StashScene with correct flattened fields."""
    with respx.mock:
        respx.post(GRAPHQL_URL).mock(
            return_value=httpx.Response(200, json=FULL_SCENE_RESPONSE)
        )
        client = StashClient(STASH_URL)
        try:
            scene = await client.find_scene_by_id("123")
        finally:
            await client.close()

    assert isinstance(scene, StashScene)
    assert scene.id == "123"
    assert scene.title == "Test Scene"
    assert scene.details == "A test scene description"
    assert scene.date == "2024-01-15"
    assert scene.rating100 == 85
    assert len(scene.files) == 1
    assert isinstance(scene.files[0], StashFile)
    assert scene.files[0].path == "/media/stash/video.mp4"
    # Flattened fields
    assert scene.studio_name == "Test Studio"
    assert scene.performer_names == ["Alice", "Bob"]
    assert scene.tag_names == ["action", "drama"]
    assert scene.screenshot_url == "http://stash:9999/scene/123/screenshot"
    assert scene.preview_url == "http://stash:9999/scene/123/preview"


@pytest.mark.asyncio
async def test_find_scene_by_id_not_found():
    """find_scene_by_id raises StashSceneNotFound when findScene returns null."""
    with respx.mock:
        respx.post(GRAPHQL_URL).mock(
            return_value=httpx.Response(200, json={"data": {"findScene": None}})
        )
        client = StashClient(STASH_URL)
        try:
            with pytest.raises(StashSceneNotFound):
                await client.find_scene_by_id("999")
        finally:
            await client.close()


@pytest.mark.asyncio
async def test_find_scene_by_id_accepts_int():
    """find_scene_by_id accepts an int scene_id and sends it as a string in the GraphQL variables."""
    with respx.mock:
        route = respx.post(GRAPHQL_URL).mock(
            return_value=httpx.Response(200, json=FULL_SCENE_RESPONSE)
        )
        client = StashClient(STASH_URL)
        try:
            await client.find_scene_by_id(42)
        finally:
            await client.close()

    # Verify the request body sent "id": "42" (str, not int)
    import json
    request_body = json.loads(route.calls[0].request.content)
    assert request_body["variables"]["id"] == "42"


@pytest.mark.asyncio
async def test_find_scene_by_path_found():
    """find_scene_by_path returns a StashScene when the path matches."""
    with respx.mock:
        respx.post(GRAPHQL_URL).mock(
            return_value=httpx.Response(200, json=FIND_SCENES_RESPONSE)
        )
        client = StashClient(STASH_URL)
        try:
            scene = await client.find_scene_by_path("/media/stash/other.mp4")
        finally:
            await client.close()

    assert isinstance(scene, StashScene)
    assert scene.id == "456"
    assert scene.title == "Path Scene"
    assert scene.studio_name == "Another Studio"
    assert scene.performer_names == ["Carol"]
    assert scene.tag_names == ["comedy"]


@pytest.mark.asyncio
async def test_find_scene_by_path_not_found():
    """find_scene_by_path returns None (does not raise) when no scene matches."""
    with respx.mock:
        respx.post(GRAPHQL_URL).mock(
            return_value=httpx.Response(
                200, json={"data": {"findScenes": {"scenes": []}}}
            )
        )
        client = StashClient(STASH_URL)
        try:
            result = await client.find_scene_by_path("/no/match/here.mp4")
        finally:
            await client.close()

    assert result is None


@pytest.mark.asyncio
async def test_connection_error():
    """find_scene_by_id raises StashConnectionError when the server is unreachable."""
    with respx.mock:
        respx.post(GRAPHQL_URL).mock(
            side_effect=httpx.ConnectError("Connection refused")
        )
        client = StashClient(STASH_URL)
        try:
            with pytest.raises(StashConnectionError):
                await client.find_scene_by_id("1")
        finally:
            await client.close()


@pytest.mark.asyncio
async def test_timeout_error():
    """find_scene_by_id raises StashConnectionError on timeout (timeout is a connection-class error)."""
    with respx.mock:
        respx.post(GRAPHQL_URL).mock(
            side_effect=httpx.TimeoutException("timed out")
        )
        client = StashClient(STASH_URL)
        try:
            with pytest.raises(StashConnectionError):
                await client.find_scene_by_id("1")
        finally:
            await client.close()


@pytest.mark.asyncio
async def test_graphql_errors_response():
    """find_scene_by_id raises StashQueryError when GraphQL response contains an errors array."""
    with respx.mock:
        respx.post(GRAPHQL_URL).mock(
            return_value=httpx.Response(
                200, json={"errors": [{"message": "bad query"}]}
            )
        )
        client = StashClient(STASH_URL)
        try:
            with pytest.raises(StashQueryError):
                await client.find_scene_by_id("1")
        finally:
            await client.close()


@pytest.mark.asyncio
async def test_api_key_header_sent():
    """StashClient sends ApiKey header when api_key is provided."""
    with respx.mock:
        route = respx.post(GRAPHQL_URL).mock(
            return_value=httpx.Response(200, json=FULL_SCENE_RESPONSE)
        )
        client = StashClient(STASH_URL, api_key="secret123")
        try:
            await client.find_scene_by_id("123")
        finally:
            await client.close()

    assert route.calls[0].request.headers.get("ApiKey") == "secret123"


@pytest.mark.asyncio
async def test_scene_with_missing_optional_fields():
    """StashScene gracefully handles null studio, empty performers/tags, no screenshot."""
    minimal_response = {
        "data": {
            "findScene": {
                "id": "1",
                "title": "Minimal Scene",
                "details": None,
                "date": None,
                "rating100": None,
                "files": [],
                "studio": None,
                "performers": [],
                "tags": [],
                "paths": {"screenshot": None, "preview": None},
            }
        }
    }
    with respx.mock:
        respx.post(GRAPHQL_URL).mock(
            return_value=httpx.Response(200, json=minimal_response)
        )
        client = StashClient(STASH_URL)
        try:
            scene = await client.find_scene_by_id("1")
        finally:
            await client.close()

    assert scene.studio_name is None
    assert scene.performer_names == []
    assert scene.tag_names == []
    assert scene.screenshot_url is None
    assert scene.preview_url is None


@pytest.mark.asyncio
async def test_close_calls_aclose():
    """client.close() can be called without raising an error."""
    client = StashClient(STASH_URL)
    # Should not raise
    await client.close()


@pytest.mark.asyncio
async def test_graphql_url_construction():
    """StashClient strips trailing slashes and appends /graphql correctly."""
    with respx.mock:
        route = respx.post(GRAPHQL_URL).mock(
            return_value=httpx.Response(200, json=FULL_SCENE_RESPONSE)
        )

        # Without trailing slash
        client1 = StashClient("http://stash:9999")
        try:
            await client1.find_scene_by_id("123")
        finally:
            await client1.close()

        # With trailing slash — should also POST to the same URL
        client2 = StashClient("http://stash:9999/")
        try:
            await client2.find_scene_by_id("123")
        finally:
            await client2.close()

    # Both calls should hit the same mocked URL
    assert len(route.calls) == 2
    for call in route.calls:
        assert str(call.request.url) == GRAPHQL_URL
