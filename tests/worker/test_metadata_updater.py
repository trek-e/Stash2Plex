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
from unittest.mock import MagicMock, patch

from tests.factories import make_plex_item, make_config
from worker.metadata_updater import MetadataUpdater
from validation.errors import PartialSyncResult


# ─── Core text field edits ────────────────────────────────────────

class TestBuildCoreEdits:
    def setup_method(self):
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
        updater = MetadataUpdater(config=config)
        item = make_plex_item(studio="Old")
        edits = updater._build_core_edits(item, {'studio': 'New Studio'})
        assert 'studio.value' not in edits


# ─── Update orchestration ────────────────────────────────────────

class TestUpdate:
    def setup_method(self):
        self.updater = MetadataUpdater(config=make_config())

    def test_master_toggle_off_skips_all(self):
        config = make_config(sync_master=False)
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
