# Python Quality Refactoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor worker, validation, and test code for quality — extract duplicated field sync logic, decompose the 1293-line processor.py, consolidate scattered imports, DRY Pydantic validators, and modernize test patterns.

**Architecture:** Extract `MetadataUpdater` class and generic `sync_field()` function from `SyncWorker`. Pure-function imports move to module-level; heavy/test-sensitive imports stay lazy with documented reasons. Test builders replace rigid fixtures.

**Tech Stack:** Python 3.14, Pydantic v2, pytest, unittest.mock

---

### Task 1: Test Factories (`tests/factories.py`)

**Files:**
- Create: `tests/factories.py`

This task creates builder functions used by all subsequent tasks. No existing code changes.

- [ ] **Step 1: Create `tests/factories.py` with all builders**

```python
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
```

- [ ] **Step 2: Verify factories import cleanly**

Run: `python -c "from tests.factories import make_plex_item, make_config, make_job, make_stash_scene; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add tests/factories.py
git commit -m "refactor: add test builder factories for flexible test data creation"
```

---

### Task 2: Generic Field Syncer (`worker/field_sync.py`)

**Files:**
- Create: `worker/field_sync.py`
- Create: `tests/worker/test_field_sync.py`

- [ ] **Step 1: Write the failing tests in `tests/worker/test_field_sync.py`**

```python
"""
Tests for worker/field_sync.py - generic field sync logic.

Tests verify:
- Adding new items to a field (performers, tags, collection)
- Clearing field when value is None/empty (LOCKED decision)
- No-op when all items already exist
- Truncation at max count with warning
- Error handling wraps exceptions as warnings
"""

import pytest
from unittest.mock import MagicMock

from tests.factories import make_plex_item
from worker.field_sync import (
    FieldSyncSpec,
    sync_field,
    PERFORMERS_SPEC,
    TAGS_SPEC,
    COLLECTION_SPEC,
)
from validation.errors import PartialSyncResult


@pytest.fixture
def result():
    return PartialSyncResult()


# ─── Spec definitions are correct ─────────────────────────────────

class TestSpecDefinitions:
    def test_performers_spec_attributes(self):
        assert PERFORMERS_SPEC.name == 'performers'
        assert PERFORMERS_SPEC.plex_attr == 'actors'
        assert PERFORMERS_SPEC.edit_prefix == 'actor'
        assert PERFORMERS_SPEC.clear_on_empty is True
        assert PERFORMERS_SPEC.sanitize_items is True

    def test_tags_spec_attributes(self):
        assert TAGS_SPEC.name == 'tags'
        assert TAGS_SPEC.plex_attr == 'genres'
        assert TAGS_SPEC.edit_prefix == 'genre'
        assert TAGS_SPEC.clear_on_empty is True
        assert TAGS_SPEC.sanitize_items is True

    def test_collection_spec_attributes(self):
        assert COLLECTION_SPEC.name == 'collection'
        assert COLLECTION_SPEC.plex_attr == 'collections'
        assert COLLECTION_SPEC.edit_prefix == 'collection'
        assert COLLECTION_SPEC.clear_on_empty is False
        assert COLLECTION_SPEC.sanitize_items is False


# ─── Adding new items ─────────────────────────────────────────────

class TestSyncFieldAddsNew:
    @pytest.mark.parametrize("spec,values,plex_attr_items", [
        (PERFORMERS_SPEC, ["Actor A", "Actor B"], []),
        (TAGS_SPEC, ["Genre A", "Genre B"], []),
        (COLLECTION_SPEC, ["Studio X"], []),
    ])
    def test_adds_new_items(self, spec, values, plex_attr_items, result):
        item = make_plex_item(actors=(), genres=(), collections=())
        setattr(item, spec.plex_attr, [MagicMock(tag=t) for t in plex_attr_items])

        needs_reload = sync_field(spec, item, values, result, debug=False)

        assert needs_reload is True
        item.edit.assert_called_once()
        edit_kwargs = item.edit.call_args[1]
        for i, name in enumerate(values):
            assert edit_kwargs[f'{spec.edit_prefix}[{i}].tag.tag'] == name
        assert spec.name in result.fields_updated

    @pytest.mark.parametrize("spec,existing,incoming", [
        (PERFORMERS_SPEC, ["Actor A"], ["Actor A", "Actor B"]),
        (TAGS_SPEC, ["Genre A"], ["Genre A", "Genre B"]),
    ])
    def test_merges_with_existing(self, spec, existing, incoming, result):
        item = make_plex_item(actors=(), genres=(), collections=())
        setattr(item, spec.plex_attr, [MagicMock(tag=t) for t in existing])

        needs_reload = sync_field(spec, item, incoming, result, debug=False)

        assert needs_reload is True
        edit_kwargs = item.edit.call_args[1]
        # Existing items come first, then new ones
        assert edit_kwargs[f'{spec.edit_prefix}[0].tag.tag'] == existing[0]
        new_item = [v for v in incoming if v not in existing][0]
        assert edit_kwargs[f'{spec.edit_prefix}[1].tag.tag'] == new_item


# ─── Clearing (LOCKED decision) ──────────────────────────────────

class TestSyncFieldClears:
    @pytest.mark.parametrize("spec", [PERFORMERS_SPEC, TAGS_SPEC])
    @pytest.mark.parametrize("empty_value", [None, []])
    def test_clears_on_empty(self, spec, empty_value, result):
        item = make_plex_item()

        needs_reload = sync_field(spec, item, empty_value, result, debug=False)

        assert needs_reload is True
        item.edit.assert_called_once_with(**{spec.lock_edit_key: 1})
        assert spec.name in result.fields_updated

    def test_collection_does_not_clear_on_empty(self, result):
        item = make_plex_item()

        needs_reload = sync_field(COLLECTION_SPEC, item, None, result, debug=False)

        assert needs_reload is False
        item.edit.assert_not_called()


# ─── No-op when unchanged ────────────────────────────────────────

class TestSyncFieldNoop:
    @pytest.mark.parametrize("spec,values,existing", [
        (PERFORMERS_SPEC, ["Actor A"], ["Actor A"]),
        (TAGS_SPEC, ["Genre A"], ["Genre A"]),
        (COLLECTION_SPEC, ["Studio X"], ["Studio X"]),
    ])
    def test_noop_when_all_exist(self, spec, values, existing, result):
        item = make_plex_item(actors=(), genres=(), collections=())
        setattr(item, spec.plex_attr, [MagicMock(tag=t) for t in existing])

        needs_reload = sync_field(spec, item, values, result, debug=False)

        assert needs_reload is False
        item.edit.assert_not_called()
        assert spec.name in result.fields_updated


# ─── Truncation ───────────────────────────────────────────────────

class TestSyncFieldTruncation:
    @pytest.mark.parametrize("spec", [PERFORMERS_SPEC, TAGS_SPEC])
    def test_truncates_at_max_count(self, spec, result, capsys):
        item = make_plex_item(actors=(), genres=(), collections=())
        setattr(item, spec.plex_attr, [])

        values = [f"Item {i}" for i in range(spec.max_count + 10)]
        sync_field(spec, item, values, result, debug=False)

        edit_kwargs = item.edit.call_args[1]
        assert len(edit_kwargs) == spec.max_count
        captured = capsys.readouterr()
        assert "Truncating" in captured.err


# ─── Error handling ───────────────────────────────────────────────

class TestSyncFieldErrors:
    @pytest.mark.parametrize("spec", [PERFORMERS_SPEC, TAGS_SPEC, COLLECTION_SPEC])
    def test_edit_exception_becomes_warning(self, spec, result):
        item = make_plex_item(actors=(), genres=(), collections=())
        setattr(item, spec.plex_attr, [])
        item.edit.side_effect = Exception("Plex API error")

        needs_reload = sync_field(spec, item, ["New Item"], result, debug=False)

        assert needs_reload is False
        assert result.has_warnings
        assert result.warnings[0].field_name == spec.name

    @pytest.mark.parametrize("spec", [PERFORMERS_SPEC, TAGS_SPEC])
    def test_clear_exception_becomes_warning(self, spec, result):
        item = make_plex_item()
        item.edit.side_effect = Exception("Plex API error")

        needs_reload = sync_field(spec, item, None, result, debug=False)

        assert needs_reload is False
        assert result.has_warnings
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/worker/test_field_sync.py -v 2>&1 | head -20`
Expected: FAIL — `ModuleNotFoundError: No module named 'worker.field_sync'`

- [ ] **Step 3: Write `worker/field_sync.py` implementation**

```python
"""
Generic field sync for Plex list fields (performers, tags, collections).

Provides a single sync_field() function that handles:
- Clearing field when value is None/empty (LOCKED decision)
- Sanitizing incoming values
- Diffing current vs. new items
- Building indexed Plex edit dicts
- Truncation at max count with logging

Each field type is defined as a FieldSyncSpec dataclass.
"""

from dataclasses import dataclass

from validation.limits import (
    MAX_PERFORMER_NAME_LENGTH, MAX_PERFORMERS,
    MAX_TAG_NAME_LENGTH, MAX_TAGS,
    MAX_COLLECTIONS,
)
from validation.sanitizers import sanitize_for_plex
from shared.log import create_logger

log_trace, log_debug, log_info, log_warn, log_error = create_logger("FieldSync")


@dataclass(frozen=True)
class FieldSyncSpec:
    """Specification for syncing a Plex list field."""
    name: str              # Human name: 'performers', 'tags', 'collection'
    plex_attr: str         # Plex item attribute: 'actors', 'genres', 'collections'
    edit_prefix: str       # Plex edit key prefix: 'actor', 'genre', 'collection'
    max_count: int         # Maximum items allowed
    max_name_length: int   # Per-item name sanitization limit
    lock_edit_key: str     # Key for locking/clearing: 'actor.locked', etc.
    clear_on_empty: bool = True     # Whether None/[] clears the field
    sanitize_items: bool = True     # Whether to sanitize individual item names


PERFORMERS_SPEC = FieldSyncSpec(
    name='performers',
    plex_attr='actors',
    edit_prefix='actor',
    max_count=MAX_PERFORMERS,
    max_name_length=MAX_PERFORMER_NAME_LENGTH,
    lock_edit_key='actor.locked',
)

TAGS_SPEC = FieldSyncSpec(
    name='tags',
    plex_attr='genres',
    edit_prefix='genre',
    max_count=MAX_TAGS,
    max_name_length=MAX_TAG_NAME_LENGTH,
    lock_edit_key='genre.locked',
)

COLLECTION_SPEC = FieldSyncSpec(
    name='collection',
    plex_attr='collections',
    edit_prefix='collection',
    max_count=MAX_COLLECTIONS,
    max_name_length=255,
    lock_edit_key='collection.locked',
    clear_on_empty=False,
    sanitize_items=False,
)


def sync_field(
    spec: FieldSyncSpec,
    plex_item,
    values,
    result,
    debug: bool,
    max_count_override: int | None = None,
) -> bool:
    """
    Sync a list field to Plex. Returns True if reload needed.

    Args:
        spec: Field specification (which Plex attribute, edit prefix, limits)
        plex_item: Plex Video item to update
        values: List of string values to sync, or None/[] to clear
        result: PartialSyncResult to record outcome
        debug: Whether to log debug details
        max_count_override: Override spec.max_count (used for config.max_tags)

    Returns:
        True if plex_item.edit() was called (reload needed), False otherwise
    """
    max_count = max_count_override if max_count_override is not None else spec.max_count

    # Handle clear case
    if values is None or values == []:
        if not spec.clear_on_empty:
            return False
        try:
            plex_item.edit(**{spec.lock_edit_key: 1})
            log_debug(f"Clearing {spec.name} (Stash value is empty)")
            result.add_success(spec.name)
            return True
        except Exception as e:
            log_warn(f" Failed to clear {spec.name}: {e}")
            result.add_warning(spec.name, e)
            return False

    if not values:
        return False

    try:
        # Sanitize if needed
        if spec.sanitize_items:
            sanitized = [sanitize_for_plex(v, max_length=spec.max_name_length) for v in values]
        else:
            sanitized = list(values)

        # Truncate input list
        if len(sanitized) > max_count:
            log_warn(f"Truncating {spec.name} list from {len(sanitized)} to {max_count}")
            sanitized = sanitized[:max_count]

        # Get current items
        current = [item.tag for item in getattr(plex_item, spec.plex_attr, [])]

        if debug:
            log_info(f"[DEBUG] {spec.name}: current={current}, incoming={sanitized}")

        # Find new items not already present
        new_items = [v for v in sanitized if v not in current]

        if new_items:
            all_items = current + new_items
            if len(all_items) > max_count:
                log_warn(f"Truncating combined {spec.name} list from {len(all_items)} to {max_count}")
                all_items = all_items[:max_count]

            edits = {f'{spec.edit_prefix}[{i}].tag.tag': name for i, name in enumerate(all_items)}
            plex_item.edit(**edits)
            log_info(f"Added {len(new_items)} {spec.name}: {new_items}")
            result.add_success(spec.name)
            return True
        else:
            log_trace(f"{spec.name} already in Plex: {sanitized}")
            result.add_success(spec.name)
            return False

    except Exception as e:
        log_warn(f" Failed to sync {spec.name}: {e}")
        result.add_warning(spec.name, e)
        return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/worker/test_field_sync.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add worker/field_sync.py tests/worker/test_field_sync.py
git commit -m "refactor: extract generic field syncer from processor.py"
```

---

### Task 3: MetadataUpdater (`worker/metadata_updater.py`)

**Files:**
- Create: `worker/metadata_updater.py`
- Create: `tests/worker/test_metadata_updater.py`

Extracts `_update_metadata`, `_build_core_edits`, `_upload_image`, `_validate_edit_result`, and `_fetch_stash_image` from `SyncWorker` into a standalone class.

- [ ] **Step 1: Write the failing tests in `tests/worker/test_metadata_updater.py`**

```python
"""
Tests for worker/metadata_updater.py - MetadataUpdater.

Tests verify:
- Core text field edits (title, studio, summary, tagline, date)
- LOCKED decision: empty/None clears existing Plex values
- Field not in data preserves existing Plex value
- Delegates list field syncs to sync_field()
- Image upload with temp file
- Master sync toggle disables all syncing
- Partial sync result tracking
- Edit validation after reload
"""

import pytest
from unittest.mock import MagicMock, patch, call

from tests.factories import make_plex_item, make_config
from validation.errors import PartialSyncResult


# ─── Core text field edits ────────────────────────────────────────

class TestBuildCoreEdits:
    def setup_method(self):
        from worker.metadata_updater import MetadataUpdater
        self.updater = MetadataUpdater(config=make_config())

    def test_title_change_creates_edit(self):
        item = make_plex_item(title="Old Title")
        edits = self.updater._build_core_edits(item, {'title': 'New Title'})
        assert edits == {'title.value': 'New Title'}

    def test_title_unchanged_no_edit(self):
        item = make_plex_item(title="Same Title")
        edits = self.updater._build_core_edits(item, {'title': 'Same Title'})
        assert edits == {}

    def test_empty_title_preserves_plex_title(self):
        """LOCKED: empty Stash title should NOT clear Plex title."""
        item = make_plex_item(title="Existing Title")
        edits = self.updater._build_core_edits(item, {'title': ''})
        assert 'title.value' not in edits

    def test_none_title_preserves_plex_title(self):
        item = make_plex_item(title="Existing Title")
        edits = self.updater._build_core_edits(item, {'title': None})
        assert 'title.value' not in edits

    def test_none_studio_clears(self):
        """LOCKED: None studio clears existing Plex studio."""
        item = make_plex_item(studio="Existing Studio")
        edits = self.updater._build_core_edits(item, {'studio': None})
        assert edits == {'studio.value': ''}

    def test_empty_string_studio_clears(self):
        item = make_plex_item(studio="Existing Studio")
        edits = self.updater._build_core_edits(item, {'studio': ''})
        assert edits == {'studio.value': ''}

    def test_studio_not_in_data_preserves(self):
        item = make_plex_item(studio="Existing Studio")
        edits = self.updater._build_core_edits(item, {'title': 'X'})
        assert 'studio.value' not in edits

    def test_none_summary_clears(self):
        item = make_plex_item(summary="Existing Summary")
        edits = self.updater._build_core_edits(item, {'details': None})
        assert edits == {'summary.value': ''}

    def test_none_tagline_clears(self):
        item = make_plex_item(tagline="Existing Tagline")
        edits = self.updater._build_core_edits(item, {'tagline': None})
        assert edits == {'tagline.value': ''}

    def test_none_date_clears(self):
        from datetime import date
        item = make_plex_item(originally_available_at=date(2024, 1, 15))
        edits = self.updater._build_core_edits(item, {'date': None})
        assert edits == {'originallyAvailableAt.value': ''}

    def test_sync_toggle_off_skips_field(self):
        config = make_config(sync_studio=False)
        from worker.metadata_updater import MetadataUpdater
        updater = MetadataUpdater(config=config)
        item = make_plex_item(studio="Old")
        edits = updater._build_core_edits(item, {'studio': 'New Studio'})
        assert 'studio.value' not in edits


# ─── Update orchestration ────────────────────────────────────────

class TestUpdate:
    def setup_method(self):
        from worker.metadata_updater import MetadataUpdater
        self.updater = MetadataUpdater(config=make_config())

    def test_master_toggle_off_skips_all(self):
        config = make_config(sync_master=False)
        from worker.metadata_updater import MetadataUpdater
        updater = MetadataUpdater(config=config)
        item = make_plex_item()
        result = updater.update(item, {'title': 'New', 'studio': 'New Studio'})
        item.edit.assert_not_called()
        assert isinstance(result, PartialSyncResult)

    def test_core_edits_applied(self):
        item = make_plex_item(title="Old", studio="Old Studio")
        self.updater.update(item, {'title': 'New', 'studio': 'New Studio'})
        item.edit.assert_called()
        edit_kwargs = item.edit.call_args_list[0][1]
        assert edit_kwargs['title.value'] == 'New'
        assert edit_kwargs['studio.value'] == 'New Studio'

    def test_reload_called_after_edits(self):
        item = make_plex_item(title="Old")
        self.updater.update(item, {'title': 'New'})
        item.reload.assert_called_once()

    def test_no_reload_when_no_edits(self):
        item = make_plex_item(title="Same")
        # No performers/tags/collections changes either
        self.updater.update(item, {'title': 'Same'})
        item.reload.assert_not_called()

    def test_returns_partial_sync_result(self):
        item = make_plex_item(title="Old")
        result = self.updater.update(item, {'title': 'New'})
        assert isinstance(result, PartialSyncResult)
        assert 'metadata' in result.fields_updated

    def test_performers_delegated_to_sync_field(self):
        item = make_plex_item(actors=())
        self.updater.update(item, {'performers': ['Actor A']})
        # sync_field should have called edit for performers
        edit_calls = item.edit.call_args_list
        performer_edit = next(
            (c for c in edit_calls if any('actor[' in k for k in c[1])),
            None
        )
        assert performer_edit is not None

    def test_tags_delegated_to_sync_field(self):
        item = make_plex_item(genres=())
        self.updater.update(item, {'tags': ['Tag A']})
        edit_calls = item.edit.call_args_list
        tag_edit = next(
            (c for c in edit_calls if any('genre[' in k for k in c[1])),
            None
        )
        assert tag_edit is not None


# ─── Image upload ─────────────────────────────────────────────────

class TestUploadImage:
    def setup_method(self):
        from worker.metadata_updater import MetadataUpdater
        self.updater = MetadataUpdater(config=make_config())

    def test_uploads_image_via_temp_file(self):
        item = make_plex_item()
        result = PartialSyncResult()
        with patch.object(self.updater, '_fetch_stash_image', return_value=b'\xff\xd8\xff\xe0fake-jpeg-data'):
            self.updater._upload_image(item, 'http://stash/img.jpg', item.uploadPoster, 'poster', result, False)
        item.uploadPoster.assert_called_once()
        assert 'poster' in result.fields_updated

    def test_warning_on_no_image_data(self):
        item = make_plex_item()
        result = PartialSyncResult()
        with patch.object(self.updater, '_fetch_stash_image', return_value=None):
            self.updater._upload_image(item, 'http://stash/img.jpg', item.uploadPoster, 'poster', result, False)
        assert result.has_warnings
        assert result.warnings[0].field_name == 'poster'


# ─── Edit validation ─────────────────────────────────────────────

class TestValidateEditResult:
    def setup_method(self):
        from worker.metadata_updater import MetadataUpdater
        self.updater = MetadataUpdater(config=make_config())

    def test_no_issues_when_values_match(self):
        item = make_plex_item(title="New Title", studio="New Studio")
        edits = {'title.value': 'New Title', 'studio.value': 'New Studio'}
        issues = self.updater._validate_edit_result(item, edits)
        assert issues == []

    def test_detects_mismatch(self):
        item = make_plex_item(title="Wrong Title")
        edits = {'title.value': 'Expected Title'}
        issues = self.updater._validate_edit_result(item, edits)
        assert len(issues) > 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/worker/test_metadata_updater.py -v 2>&1 | head -20`
Expected: FAIL — `ModuleNotFoundError: No module named 'worker.metadata_updater'`

- [ ] **Step 3: Write `worker/metadata_updater.py` implementation**

Copy the following methods from `worker/processor.py` into the new class, adapting `self.config` references:

```python
"""
Metadata update logic for Plex items.

Handles core text field edits, list field syncs (via field_sync),
image uploads, and edit validation. Extracted from SyncWorker
to separate metadata concerns from job orchestration.
"""

import os
import tempfile
import urllib.request
import urllib.error
from typing import Optional

from validation.limits import (
    MAX_TITLE_LENGTH, MAX_STUDIO_LENGTH, MAX_SUMMARY_LENGTH, MAX_TAGLINE_LENGTH,
)
from validation.sanitizers import sanitize_for_plex
from validation.errors import PartialSyncResult
from worker.field_sync import sync_field, PERFORMERS_SPEC, TAGS_SPEC, COLLECTION_SPEC
from shared.log import create_logger

log_trace, log_debug, log_info, log_warn, log_error = create_logger("Updater")


class MetadataUpdater:
    """Applies Stash metadata to Plex items."""

    def __init__(self, config):
        self.config = config

    def update(self, plex_item, data: dict) -> PartialSyncResult:
        """
        Update Plex item metadata from sync job data.

        Implements LOCKED user decision: When Stash provides None/empty for an
        optional field, the existing Plex value is CLEARED (not preserved).
        When a field key is NOT in the data dict, the existing value is preserved.

        Non-critical field failures (performers, tags, poster, background, collection)
        are logged as warnings but don't fail the overall sync.

        Returns:
            PartialSyncResult tracking which fields succeeded and which had warnings
        """
        _dbg = getattr(self.config, 'debug_logging', False)
        result = PartialSyncResult()

        if not getattr(self.config, 'sync_master', True):
            log_debug("Master sync toggle is OFF - skipping all field syncs")
            return result

        # Phase 1: Build and apply core text field edits (CRITICAL)
        edits = self._build_core_edits(plex_item, data)
        _needs_reload = False
        if edits:
            if _dbg:
                log_info(f"[DEBUG] Metadata edits: {edits}")
            else:
                log_debug(f"Updating fields: {list(edits.keys())}")
            plex_item.edit(**edits)
            _needs_reload = True
            mode = "preserved" if self.config.preserve_plex_edits else "overwrite"
            log_info(f"Updated metadata ({mode} mode): {plex_item.title}")
            result.add_success('metadata')
        else:
            if _dbg:
                fields_in_data = [k for k in ('title', 'studio', 'details', 'summary', 'tagline', 'date') if k in data]
                log_info(f"[DEBUG] No core edits for '{plex_item.title}' — "
                         f"data keys present: {fields_in_data}, "
                         f"plex title='{plex_item.title}', stash title='{data.get('title', '<missing>')}'")
            else:
                log_trace(f"No metadata fields to update for: {plex_item.title}")

        # Phase 2: Non-critical field syncs
        if getattr(self.config, 'sync_performers', True) and 'performers' in data:
            _needs_reload |= sync_field(
                PERFORMERS_SPEC, plex_item, data.get('performers'), result, _dbg)

        if getattr(self.config, 'sync_poster', True) and data.get('poster_url'):
            self._upload_image(
                plex_item, data['poster_url'], plex_item.uploadPoster, 'poster', result, _dbg)

        if getattr(self.config, 'sync_background', True) and data.get('background_url'):
            self._upload_image(
                plex_item, data['background_url'], plex_item.uploadArt, 'background', result, _dbg)

        if getattr(self.config, 'sync_tags', True) and 'tags' in data:
            max_tags = getattr(self.config, 'max_tags', None)
            _needs_reload |= sync_field(
                TAGS_SPEC, plex_item, data.get('tags'), result, _dbg,
                max_count_override=max_tags)

        if getattr(self.config, 'sync_collection', True) and data.get('studio'):
            _needs_reload |= sync_field(
                COLLECTION_SPEC, plex_item, [data['studio']], result, _dbg)

        # Single deferred reload after all edits
        if _needs_reload:
            try:
                plex_item.reload()
                if edits:
                    validation_issues = self._validate_edit_result(plex_item, edits)
                    if validation_issues:
                        log_debug(f"Edit validation issues (may be expected): {validation_issues}")
            except Exception as e:
                log_debug(f"Post-edit reload failed (edits already applied): {e}")

        if result.has_warnings:
            log_warn(f"Partial sync for {plex_item.title}: {result.warning_summary}")

        return result

    def _build_core_edits(self, plex_item, data: dict) -> dict:
        """Build dict of core text field edits.

        LOCKED DECISION: Missing optional fields clear existing Plex values.
        - If key exists AND value is None/empty -> CLEAR (set to '')
        - If key exists AND value is present -> sanitize and set
        - If key does NOT exist in data dict -> do nothing (preserve)
        """
        edits = {}

        # Title (always synced — no toggle)
        if 'title' in data:
            title_value = data.get('title')
            if title_value is None or title_value == '':
                log_debug("Stash title is empty — preserving existing Plex title")
            else:
                sanitized = sanitize_for_plex(title_value, max_length=MAX_TITLE_LENGTH)
                if not self.config.preserve_plex_edits or not plex_item.title:
                    if (plex_item.title or '') != sanitized:
                        edits['title.value'] = sanitized

        # Studio
        if getattr(self.config, 'sync_studio', True) and 'studio' in data:
            studio_value = data.get('studio')
            if studio_value is None or studio_value == '':
                if plex_item.studio:
                    edits['studio.value'] = ''
                    log_debug("Clearing studio (Stash value is empty)")
            else:
                sanitized = sanitize_for_plex(studio_value, max_length=MAX_STUDIO_LENGTH)
                if not self.config.preserve_plex_edits or not plex_item.studio:
                    if (plex_item.studio or '') != sanitized:
                        edits['studio.value'] = sanitized

        # Summary (Stash 'details' -> Plex 'summary')
        if getattr(self.config, 'sync_summary', True):
            has_summary_key = 'details' in data or 'summary' in data
            if has_summary_key:
                summary_value = data.get('details') or data.get('summary')
                if summary_value is None or summary_value == '':
                    if plex_item.summary:
                        edits['summary.value'] = ''
                        log_debug("Clearing summary (Stash value is empty)")
                else:
                    sanitized = sanitize_for_plex(summary_value, max_length=MAX_SUMMARY_LENGTH)
                    if not self.config.preserve_plex_edits or not plex_item.summary:
                        if (plex_item.summary or '') != sanitized:
                            edits['summary.value'] = sanitized

        # Tagline
        if getattr(self.config, 'sync_tagline', True) and 'tagline' in data:
            tagline_value = data.get('tagline')
            if tagline_value is None or tagline_value == '':
                if getattr(plex_item, 'tagline', None):
                    edits['tagline.value'] = ''
                    log_debug("Clearing tagline (Stash value is empty)")
            else:
                sanitized = sanitize_for_plex(tagline_value, max_length=MAX_TAGLINE_LENGTH)
                if not self.config.preserve_plex_edits or not getattr(plex_item, 'tagline', None):
                    if (getattr(plex_item, 'tagline', '') or '') != sanitized:
                        edits['tagline.value'] = sanitized

        # Date
        if getattr(self.config, 'sync_date', True) and 'date' in data:
            date_value = data.get('date')
            if date_value is None or date_value == '':
                if getattr(plex_item, 'originallyAvailableAt', None):
                    edits['originallyAvailableAt.value'] = ''
                    log_debug("Clearing date (Stash value is empty)")
            else:
                if not self.config.preserve_plex_edits or not getattr(plex_item, 'originallyAvailableAt', None):
                    current_date = getattr(plex_item, 'originallyAvailableAt', None)
                    current_date_str = current_date.strftime('%Y-%m-%d') if current_date else ''
                    if current_date_str != (date_value or ''):
                        edits['originallyAvailableAt.value'] = date_value

        return edits

    def _upload_image(self, plex_item, url: str, upload_fn, field_name: str, result, _dbg: bool):
        """Download image from Stash and upload to Plex."""
        try:
            if _dbg:
                log_info(f"[DEBUG] Fetching {field_name} image from Stash")
            image_data = self._fetch_stash_image(url)
            if image_data:
                with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as f:
                    f.write(image_data)
                    temp_path = f.name
                try:
                    upload_fn(filepath=temp_path)
                    log_debug(f"Uploaded {field_name} ({len(image_data)} bytes)")
                    result.add_success(field_name)
                finally:
                    os.unlink(temp_path)
            else:
                result.add_warning(field_name, ValueError(f"No image data returned from Stash"))
        except Exception as e:
            log_warn(f" Failed to upload {field_name}: {e}")
            result.add_warning(field_name, e)

    def _fetch_stash_image(self, url: str) -> Optional[bytes]:
        """Fetch image from Stash URL."""
        try:
            req = urllib.request.Request(url)
            api_key = getattr(self.config, 'stash_api_key', None)
            if api_key:
                req.add_header('ApiKey', api_key)
            session_cookie = getattr(self.config, 'stash_session_cookie', None)
            if session_cookie:
                req.add_header('Cookie', session_cookie)
            with urllib.request.urlopen(req, timeout=30) as response:
                return response.read()
        except urllib.error.URLError as e:
            log_warn(f" Failed to fetch image from Stash: {e}")
            return None
        except Exception as e:
            log_warn(f" Image fetch error: {e}")
            return None

    def _validate_edit_result(self, plex_item, expected_edits: dict) -> list:
        """Validate that edit actually applied expected values."""
        issues = []
        field_mapping = {
            'title': 'title',
            'studio': 'studio',
            'summary': 'summary',
            'tagline': 'tagline',
            'originallyAvailableAt': 'originallyAvailableAt',
        }
        for field_key, expected_value in expected_edits.items():
            if '.locked' in field_key or not expected_value:
                continue
            field_name = field_key.replace('.value', '')
            attr_name = field_mapping.get(field_name)
            if not attr_name:
                continue
            actual_value = getattr(plex_item, attr_name, None)
            expected_str = str(expected_value) if expected_value else ''
            actual_str = str(actual_value) if actual_value else ''
            if expected_str and actual_str:
                if expected_str[:50] != actual_str[:50]:
                    issues.append(
                        f"{field_name}: sent '{expected_str[:20]}...', "
                        f"got '{actual_str[:20]}...'"
                    )
            elif expected_str and not actual_str:
                issues.append(f"{field_name}: sent value but field is empty")
        return issues
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/worker/test_metadata_updater.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add worker/metadata_updater.py tests/worker/test_metadata_updater.py
git commit -m "refactor: extract MetadataUpdater from SyncWorker"
```

---

### Task 4: Wire MetadataUpdater into SyncWorker

**Files:**
- Modify: `worker/processor.py`

This task replaces the old methods with delegation to `MetadataUpdater`. The old methods (`_update_metadata`, `_build_core_edits`, `_sync_performers`, `_sync_tags`, `_sync_collection`, `_upload_image`, `_fetch_stash_image`, `_validate_edit_result`) are removed and replaced with a lazy `_get_metadata_updater()`.

- [ ] **Step 1: Run existing tests to confirm baseline passes**

Run: `pytest tests/ -x -q`
Expected: All tests PASS

- [ ] **Step 2: Add `_metadata_updater` attribute and lazy getter to `SyncWorker.__init__`**

In `worker/processor.py`, add to `__init__` (after `self._match_cache` line ~85):

```python
        self._metadata_updater = None
```

Add a new method after `_get_caches()` (~line 708):

```python
    def _get_metadata_updater(self):
        """Get MetadataUpdater with lazy initialization."""
        if self._metadata_updater is None:
            from worker.metadata_updater import MetadataUpdater  # lazy: test isolation
            self._metadata_updater = MetadataUpdater(self.config)
        return self._metadata_updater
```

- [ ] **Step 3: Replace `self._update_metadata(plex_item, data)` calls in `_process_job`**

In `_process_job` (lines ~843 and ~877), replace:

```python
                    self._update_metadata(plex_item, data)
```

with:

```python
                    self._get_metadata_updater().update(plex_item, data)
```

Do this for both the HIGH confidence path (line ~843) and the LOW confidence path (line ~877).

- [ ] **Step 4: Remove old methods from `SyncWorker`**

Delete these methods entirely from `worker/processor.py`:
- `_update_metadata` (lines 958-1041)
- `_build_core_edits` (lines 1043-1130)
- `_sync_performers` (lines 1132-1184)
- `_upload_image` (lines 1186-1217)
- `_sync_tags` (lines 1219-1272)
- `_sync_collection` (lines 1274-1293)
- `_validate_edit_result` (lines 902-956)
- `_fetch_stash_image` (lines 633-670)

Keep these methods — they stay in processor.py:
- Everything from `__init__` through `_requeue_with_metadata`
- `_worker_loop`
- `_get_plex_client`, `_get_caches`, `_log_cache_stats`
- `_process_job` (with the updated delegation)
- `_log_dlq_status`, `_log_batch_summary`
- `start`, `stop`

- [ ] **Step 5: Run all tests**

Run: `pytest tests/ -x -q`
Expected: All tests PASS. Some `test_processor.py` tests that directly called `_update_metadata` will now fail — these are expected and fixed in Task 5.

- [ ] **Step 6: Commit**

```bash
git add worker/processor.py
git commit -m "refactor: wire MetadataUpdater into SyncWorker, remove extracted methods"
```

---

### Task 5: Update `test_processor.py` — redirect metadata tests

**Files:**
- Modify: `tests/worker/test_processor.py`

Tests that call `worker._update_metadata()` directly now need to call `worker._get_metadata_updater().update()` instead — or simply be deleted if equivalent coverage exists in `test_metadata_updater.py` and `test_field_sync.py`.

- [ ] **Step 1: Identify which tests to redirect vs. delete**

Tests to **delete** (covered by `test_metadata_updater.py` and `test_field_sync.py`):
- `TestFieldClearing` — all 5 tests (covered by `TestBuildCoreEdits`)
- `TestListFieldLimits` — all 6 tests (covered by `TestSyncFieldTruncation` and `TestSyncFieldClears`)

Tests to **redirect** (test SyncWorker integration, keep but update method call):
- `TestPartialSyncFailure` — 7 tests (test that partial failures don't fail the job via SyncWorker)
- `TestSyncToggles` — 11 tests (test config toggles through the full stack)

- [ ] **Step 2: Delete `TestFieldClearing` and `TestListFieldLimits` classes**

Remove classes at lines 446-724 from `tests/worker/test_processor.py`.

- [ ] **Step 3: Update `TestPartialSyncFailure` and `TestSyncToggles` to use `_get_metadata_updater().update()`**

In each test that calls `worker._update_metadata(item, data)`, replace with:

```python
worker._get_metadata_updater().update(item, data)
```

This is a find-and-replace within the two test classes. The `partial_worker` and `toggle_worker` fixtures stay as-is since they create `SyncWorker` instances.

- [ ] **Step 4: Run all tests**

Run: `pytest tests/ -x -q`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add tests/worker/test_processor.py
git commit -m "refactor: update processor tests to use MetadataUpdater delegation"
```

---

### Task 6: DRY Pydantic Validators

**Files:**
- Modify: `validation/metadata.py`

- [ ] **Step 1: Run existing validation tests to confirm baseline**

Run: `pytest tests/validation/test_metadata.py -v`
Expected: All tests PASS

- [ ] **Step 2: Replace three validator methods with factory function**

Replace the entire validator section in `validation/metadata.py` (lines 59-117) with:

```python
def _string_sanitizer(max_length: int, required: bool = False):
    """Create a Pydantic field_validator that sanitizes string fields.

    Args:
        max_length: Maximum allowed length after sanitization
        required: If True, None/empty raises ValueError
    """
    def validator(cls, v):
        if v is None:
            if required:
                raise ValueError("title is required")
            return None
        if not isinstance(v, str):
            v = str(v)
        sanitized = sanitize_for_plex(v, max_length=max_length)
        if required and not sanitized:
            raise ValueError("title cannot be empty after sanitization")
        return sanitized if sanitized else None
    return classmethod(validator)
```

Then replace the three validators in the class body with:

```python
    # Sanitize string fields via factory (DRY — all follow same pattern)
    sanitize_title = field_validator('title', mode='before')(
        _string_sanitizer(255, required=True))
    sanitize_details = field_validator('details', mode='before')(
        _string_sanitizer(10000))
    sanitize_studio = field_validator('studio', mode='before')(
        _string_sanitizer(255))
```

Keep `sanitize_string_list` as-is — it handles lists, not scalars.

- [ ] **Step 3: Run validation tests to verify no regressions**

Run: `pytest tests/validation/test_metadata.py -v`
Expected: All tests PASS (same behavior, DRYer code)

- [ ] **Step 4: Commit**

```bash
git add validation/metadata.py
git commit -m "refactor: DRY Pydantic validators with factory function"
```

---

### Task 7: Update fixtures to use factories

**Files:**
- Modify: `tests/conftest.py`

- [ ] **Step 1: Update fixtures to delegate to builders**

Replace the fixture bodies (not signatures) in `tests/conftest.py`:

For `mock_plex_item` (lines 76-135):
```python
@pytest.fixture
def mock_plex_item():
    """Mock Plex media item. See tests/factories.py for customization."""
    from tests.factories import make_plex_item
    return make_plex_item()
```

For `mock_config` (lines 142-181):
```python
@pytest.fixture
def mock_config():
    """Mock configuration. See tests/factories.py for customization."""
    from tests.factories import make_config
    return make_config()
```

For `sample_job` (lines 274-303):
```python
@pytest.fixture
def sample_job():
    """Sample sync job. See tests/factories.py for customization."""
    from tests.factories import make_job
    return make_job(performers=["Performer One", "Performer Two"], tags=["Tag One", "Tag Two"])
```

For `sample_stash_scene` (lines 362-391):
```python
@pytest.fixture
def sample_stash_scene():
    """Sample Stash scene data. See tests/factories.py for customization."""
    from tests.factories import make_stash_scene
    return make_stash_scene()
```

Keep `mock_plex_server`, `mock_plex_section`, `valid_config_dict`, `mock_queue`, `mock_dlq`, `sample_metadata_dict`, `mock_stash_interface` unchanged — they're either simple enough already or not covered by factories.

- [ ] **Step 2: Run full test suite**

Run: `pytest tests/ -x -q`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/conftest.py
git commit -m "refactor: fixtures delegate to factory builders"
```

---

### Task 8: Consolidate imports

**Files:**
- Modify: `worker/processor.py`
- Modify: `worker/metadata_updater.py` (already done — uses module-level imports)

- [ ] **Step 1: Move pure imports to module level in `processor.py`**

At the top of `worker/processor.py`, after the existing imports, add:

```python
from worker.backoff import calculate_delay, get_retry_params
from worker.circuit_breaker import CircuitBreaker, CircuitState
from plex.exceptions import PlexServerDown, PlexNotFound, PlexTemporaryError, PlexPermanentError, translate_plex_exception
```

Then remove the corresponding lazy imports from inside methods:

- `_prepare_for_retry`: remove `from worker.backoff import calculate_delay, get_retry_params`
- `_get_max_retries_for_error`: remove `from worker.backoff import get_retry_params`
- `_worker_loop`: remove `from worker.circuit_breaker import CircuitState` and `from plex.exceptions import PlexServerDown, PlexNotFound`
- `__init__`: remove `from worker.circuit_breaker import CircuitBreaker` (now module-level)

For health check backoff in `_worker_loop` (~line 370): remove `from worker.backoff import calculate_delay` (now module-level).

Keep these lazy with comments:
```python
# lazy: test isolation — tests mock at function level
from sync_queue.operations import get_pending, ack_job, nack_job, fail_job

# lazy: heavy init (network connection)
from plex.client import PlexClient

# lazy: imports plexapi which may not be installed
from plex.matcher import find_plex_items_with_confidence, MatchConfidence

# lazy: test isolation — cross-module coupling
from hooks.handlers import unmark_scene_pending

# lazy: only needed when data_dir is set
from worker.outage_history import OutageHistory
from worker.recovery import RecoveryScheduler

# lazy: heavy init
from plex.cache import PlexCache, MatchCache

# lazy: test isolation
from sync_queue.operations import save_sync_timestamp
from sync_queue.operations import ack_job as _ack_job, _job_counter

# lazy: only needed during health check
from plex.health import check_plex_health
```

- [ ] **Step 2: Run full test suite**

Run: `pytest tests/ -x -q`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add worker/processor.py
git commit -m "refactor: consolidate pure-function imports to module level"
```

---

### Task 9: Final verification

**Files:** None (verification only)

- [ ] **Step 1: Run full test suite with coverage**

Run: `pytest tests/ --cov=. --cov-report=term-missing -q`
Expected: All tests PASS, coverage ≥86%

- [ ] **Step 2: Verify processor.py line count reduced**

Run: `wc -l worker/processor.py worker/metadata_updater.py worker/field_sync.py`
Expected: `processor.py` ~600 lines, `metadata_updater.py` ~250 lines, `field_sync.py` ~120 lines

- [ ] **Step 3: Verify no remaining lazy imports for pure modules**

Run: `grep -n "from validation\.\|from worker.backoff" worker/processor.py | grep -v "^[0-9]*:from\|^[0-9]*:import" || echo "OK - no inline imports for pure modules"`

- [ ] **Step 4: Commit verification result (if any fixes needed)**

If coverage dropped or tests fail, fix and commit. Otherwise, this task produces no commit.
