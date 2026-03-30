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
