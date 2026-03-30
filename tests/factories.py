"""
Reusable test object builders for Stash2Plex.

Builder functions accept keyword overrides so tests can customize
only the fields they care about, avoiding rigid fixtures.
"""

from unittest.mock import Mock, MagicMock


def make_plex_item(
    title="Test Scene",
    studio="Test Studio",
    summary="Test description for the scene.",
    rating_key=12345,
    guid="plex://movie/abc123",
    actors=("Performer One", "Performer Two"),
    genres=("Genre One",),
    collections=("Collection One",),
    file_path="/media/videos/test_scene.mp4",
    tagline=None,
    originally_available_at=None,
):
    """Build a mock Plex item with customizable attributes."""
    item = MagicMock()
    item.title = title
    item.studio = studio
    item.summary = summary
    item.ratingKey = rating_key
    item.key = f"/library/metadata/{rating_key}"
    item.guid = guid
    item.tagline = tagline
    item.originallyAvailableAt = originally_available_at

    # Actors
    item.actors = []
    for name in (actors or []):
        actor = MagicMock()
        actor.tag = name
        item.actors.append(actor)

    # Genres
    item.genres = []
    for name in (genres or []):
        genre = MagicMock()
        genre.tag = name
        item.genres.append(genre)

    # Collections
    item.collections = []
    for name in (collections or []):
        coll = MagicMock()
        coll.tag = name
        item.collections.append(coll)

    # File path through media hierarchy
    part = MagicMock()
    part.file = file_path
    media = MagicMock()
    media.parts = [part]
    item.media = [media]

    # Edit/reload methods
    item.edit.return_value = None
    item.reload.return_value = None

    return item


def make_config(
    plex_url="http://localhost:32400",
    plex_token="test-token-abc123",
    plex_library="Movies",
    plex_libraries=None,
    stash_url="http://localhost:9999",
    stash_api_key="stash-api-key-xyz",
    poll_interval=5,
    max_retries=5,
    initial_backoff=1.0,
    max_backoff=300.0,
    circuit_breaker_threshold=5,
    circuit_breaker_timeout=60,
    debug_logging=False,
    obfuscate_paths=False,
    max_tags=100,
    plex_connect_timeout=10.0,
    plex_read_timeout=30.0,
    preserve_plex_edits=False,
    strict_matching=False,
    dlq_retention_days=30,
    sync_master=True,
    sync_performers=True,
    sync_poster=True,
    sync_background=True,
    sync_tags=True,
    sync_collection=True,
    sync_studio=True,
    sync_summary=True,
    sync_tagline=True,
    sync_date=True,
    stash_session_cookie=None,
):
    """Build a mock config with customizable attributes."""
    config = Mock()
    config.plex_url = plex_url
    config.plex_token = plex_token
    config.plex_library = plex_library
    config.plex_libraries = plex_libraries or [plex_library]
    config.stash_url = stash_url
    config.stash_api_key = stash_api_key
    config.poll_interval = poll_interval
    config.max_retries = max_retries
    config.initial_backoff = initial_backoff
    config.max_backoff = max_backoff
    config.circuit_breaker_threshold = circuit_breaker_threshold
    config.circuit_breaker_timeout = circuit_breaker_timeout
    config.debug_logging = debug_logging
    config.obfuscate_paths = obfuscate_paths
    config.max_tags = max_tags
    config.plex_connect_timeout = plex_connect_timeout
    config.plex_read_timeout = plex_read_timeout
    config.preserve_plex_edits = preserve_plex_edits
    config.strict_matching = strict_matching
    config.dlq_retention_days = dlq_retention_days
    config.sync_master = sync_master
    config.sync_performers = sync_performers
    config.sync_poster = sync_poster
    config.sync_background = sync_background
    config.sync_tags = sync_tags
    config.sync_collection = sync_collection
    config.sync_studio = sync_studio
    config.sync_summary = sync_summary
    config.sync_tagline = sync_tagline
    config.sync_date = sync_date
    config.stash_session_cookie = stash_session_cookie
    return config


def make_job(
    scene_id=123,
    update_type="metadata",
    path="/media/videos/test_scene.mp4",
    title="Test Scene Title",
    studio="Test Studio",
    details="A test scene description.",
    performers=None,
    tags=None,
    enqueued_at=1700000000.0,
    extra_data=None,
):
    """Build a sample sync job dict."""
    data = {"path": path, "title": title}
    if studio is not None:
        data["studio"] = studio
    if details is not None:
        data["details"] = details
    if performers is not None:
        data["performers"] = performers
    if tags is not None:
        data["tags"] = tags
    if extra_data:
        data.update(extra_data)

    return {
        "scene_id": scene_id,
        "update_type": update_type,
        "data": data,
        "enqueued_at": enqueued_at,
        "job_key": f"scene_{scene_id}",
    }


def make_stash_scene(
    id="789",
    title="Stash Scene Title",
    details="Scene details from Stash.",
    date="2024-02-20",
    rating100=75,
    studio_name="Stash Studio",
    performers=("Performer A", "Performer B"),
    tags=("Tag A", "Tag B"),
    file_path="/stash/media/scene_789.mp4",
):
    """Build a sample Stash scene data dict."""
    return {
        "id": id,
        "title": title,
        "details": details,
        "date": date,
        "rating100": rating100,
        "studio": {"name": studio_name},
        "performers": [{"name": p} for p in (performers or [])],
        "tags": [{"name": t} for t in (tags or [])],
        "files": [{"path": file_path}],
    }
