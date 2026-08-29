"""
Regression tests for GitHub issue #9: "Removing tags is not recognised as an
update for the scene."

Two compounding defects meant a tag removal never reached Plex:

1. extract_scene_metadata() omitted studio/performers/tags from job data
   whenever they were empty, so a cleared field looked identical to a field
   the hook simply hadn't mentioned (worker/processor.py distinguishes
   "key absent" = preserve from "key present + empty" = clear).
2. has_meaningful_metadata() was applied as a blanket gate to every scene,
   including ones synced long ago that are demonstrably past the stash-box
   identify race the gate exists to protect.

These tests are organised in the same vertical slices used to build the fix.
"""
from unittest.mock import MagicMock

import pytest

from hooks.handlers import on_scene_update
from reconciliation.detector import GapResult


# =============================================================================
# Slice 1 — extract_scene_metadata always emits studio/performers/tags keys
# =============================================================================

class TestExtractSceneMetadataEmptyCollections:
    """extract_scene_metadata must emit present-but-empty keys, not omit them."""

    def test_emits_empty_tags_when_scene_has_no_tags(self):
        from validation.scene_extractor import extract_scene_metadata

        scene = {
            'title': 'Scene',
            'details': 'Some details',
            'date': '2024-01-01',
            'rating100': 80,
            'studio': {'name': 'Studio A'},
            'performers': [{'name': 'Performer A'}],
            'tags': [],  # tags removed in Stash
            'files': [{'path': '/media/scene.mp4'}],
        }

        data = extract_scene_metadata(scene)

        assert 'tags' in data
        assert data['tags'] == []

    def test_emits_empty_performers_when_scene_has_no_performers(self):
        from validation.scene_extractor import extract_scene_metadata

        scene = {
            'title': 'Scene',
            'studio': {'name': 'Studio A'},
            'performers': [],
            'tags': [{'name': 'Tag A'}],
        }

        data = extract_scene_metadata(scene)

        assert 'performers' in data
        assert data['performers'] == []

    def test_emits_none_studio_when_scene_has_no_studio(self):
        from validation.scene_extractor import extract_scene_metadata

        scene = {
            'title': 'Scene',
            'studio': None,
            'performers': [{'name': 'Performer A'}],
            'tags': [{'name': 'Tag A'}],
        }

        data = extract_scene_metadata(scene)

        assert 'studio' in data
        assert data['studio'] is None

    def test_emits_populated_values_correctly(self):
        """The fix must not regress the populated case."""
        from validation.scene_extractor import extract_scene_metadata

        scene = {
            'title': 'Scene',
            'studio': {'name': 'Studio A'},
            'performers': [{'name': 'Performer A'}, {'name': 'Performer B'}],
            'tags': [{'name': 'Tag A'}, {'name': 'Tag B'}],
        }

        data = extract_scene_metadata(scene)

        assert data['studio'] == 'Studio A'
        assert data['performers'] == ['Performer A', 'Performer B']
        assert data['tags'] == ['Tag A', 'Tag B']


# =============================================================================
# Slice 2 — quality gate applies only to never-synced scenes
# =============================================================================

class TestOnSceneUpdateGateHonoursSyncHistory:
    """hooks.handlers.on_scene_update: the quality gate must let a deliberate
    removal through for a scene that has synced before, while still blocking
    a genuinely-unidentified scene that has never synced."""

    def _mock_stash_with_all_metadata_emptied(self):
        """The last tag/performer/studio was just removed in Stash — the
        scene now has no meaningful metadata at all, only title/path."""
        mock_stash = MagicMock()
        mock_stash.call_GQL.return_value = {
            "findScene": {
                "id": "123",
                "title": "Test Scene",
                "files": [{"path": "/media/test.mp4"}],
                "studio": None,
                "performers": [],
                "tags": [],  # last tag removed in Stash
                "paths": {},
            }
        }
        return mock_stash

    def test_enqueues_emptied_tags_when_scene_previously_synced(
        self, mock_queue_manager, mocker
    ):
        """A scene with a prior sync timestamp is past the identify race —
        removing its last tag must be enqueued so Plex learns about it."""
        mocker.patch('hooks.handlers.is_scan_running', return_value=False)
        mock_stash = self._mock_stash_with_all_metadata_emptied()

        result = on_scene_update(
            scene_id=123,
            update_data={"title": "Test Scene", "tag_ids": []},
            queue_manager=mock_queue_manager,
            stash=mock_stash,
            sync_timestamps={123: 1700000000.0},
        )

        assert result is True
        mock_queue_manager.try_enqueue.assert_called_once()

    def test_skips_never_synced_scene_with_no_metadata(
        self, mock_queue_manager, mocker
    ):
        """Identify-race protection: a scene that has NEVER synced and has no
        meaningful metadata must still be skipped — it may still be
        mid-identification. This must not regress."""
        mocker.patch('hooks.handlers.is_scan_running', return_value=False)

        mock_stash = MagicMock()
        mock_stash.call_GQL.return_value = {
            "findScene": {
                "id": "123",
                "title": "Test Scene",
                "files": [{"path": "/media/test.mp4"}],
                "studio": None,
                "performers": [],
                "tags": [],
                "paths": {},
            }
        }

        result = on_scene_update(
            scene_id=123,
            update_data={"title": "Test Scene"},
            queue_manager=mock_queue_manager,
            stash=mock_stash,
            sync_timestamps={},  # never synced
        )

        assert result is False
        mock_queue_manager.try_enqueue.assert_not_called()


# =============================================================================
# Slice 2 (continued) — reconciliation gate honours sync history too
# =============================================================================

class TestEnqueueGapsGateHonoursSyncHistory:
    """reconciliation.engine.GapDetectionEngine._enqueue_gaps: same gate
    behaviour as hooks.handlers.on_scene_update, exercised at its own
    call site."""

    def _empty_metadata_scene(self, scene_id: str, updated_at: str):
        return {
            'id': scene_id,
            'title': 'Test Scene',
            'details': None,
            'date': None,
            'rating100': None,
            'updated_at': updated_at,
            'files': [{'path': f'/media/scene{scene_id}.mp4'}],
            'studio': None,
            'performers': [],
            'tags': [],
            'paths': {},
        }

    def test_enqueues_stale_gap_with_no_metadata_when_scene_previously_synced(
        self, mock_stash_interface, mock_config, tmp_path, mock_queue_manager
    ):
        """A scene with a prior sync timestamp is past the identify race —
        a gap that reduces it to no metadata must still be enqueued."""
        from reconciliation.engine import GapDetectionEngine
        from sync_queue.operations import save_sync_timestamp

        save_sync_timestamp(str(tmp_path), 1, 1700000000.0)

        scene = self._empty_metadata_scene('1', '2024-06-01T00:00:00Z')
        gap = GapResult(
            scene_id=1,
            gap_type='stale_sync',
            scene_data=scene,
            reason='test',
        )

        engine = GapDetectionEngine(mock_stash_interface, mock_config, str(tmp_path), queue_manager=mock_queue_manager)
        enqueued, skipped, skipped_no_metadata = engine._enqueue_gaps([], [gap], [])

        assert enqueued == 1
        assert skipped_no_metadata == 0

    def test_skips_gap_with_no_metadata_when_scene_never_synced(
        self, mock_stash_interface, mock_config, tmp_path, mock_queue_manager
    ):
        """Identify-race protection: a scene that has NEVER synced and has no
        meaningful metadata must still be skipped."""
        from reconciliation.engine import GapDetectionEngine

        scene = self._empty_metadata_scene('2', '2024-06-01T00:00:00Z')
        gap = GapResult(
            scene_id=2,
            gap_type='missing',
            scene_data=scene,
            reason='test',
        )

        engine = GapDetectionEngine(mock_stash_interface, mock_config, str(tmp_path), queue_manager=mock_queue_manager)
        enqueued, skipped, skipped_no_metadata = engine._enqueue_gaps([], [], [gap])

        assert enqueued == 0
        assert skipped_no_metadata == 1
        mock_queue_manager.try_enqueue.assert_not_called()


# =============================================================================
# Slice 3 — _sync_collection clears the Plex collection on studio removal
# =============================================================================

class TestStudioRemovalClearsCollection:
    """worker.processor.SyncWorker._update_metadata: removing a studio in
    Stash must clear the item from its Plex collection, matching the
    'key present + empty = clear' contract used by performers/tags/studio."""

    @pytest.fixture
    def worker(self, mock_queue, mock_dlq, mock_config, tmp_path, mock_queue_manager):
        from worker.processor import SyncWorker

        mock_config.plex_connect_timeout = 10.0
        mock_config.plex_read_timeout = 30.0
        mock_config.preserve_plex_edits = False
        mock_config.strict_matching = False
        mock_config.dlq_retention_days = 30

        return SyncWorker(
            queue_manager=mock_queue_manager,
            dlq=mock_dlq,
            config=mock_config,
            data_dir=str(tmp_path),
        )

    def test_removed_studio_clears_collection(self, worker):
        mock_plex_item = MagicMock()
        mock_plex_item.title = "Test"
        mock_plex_item.studio = "Old Studio"
        mock_plex_item.summary = ""
        mock_plex_item.actors = []
        mock_plex_item.genres = []

        old_collection = MagicMock()
        old_collection.tag = "Old Studio"
        mock_plex_item.collections = [old_collection]

        data = {
            'path': '/test.mp4',
            'title': 'Test',
            'studio': None,  # studio removed in Stash — key present, empty
        }

        result = worker._update_metadata(mock_plex_item, data)

        assert 'collection' in result.fields_updated
        mock_plex_item.edit.assert_any_call(**{'collection.locked': 1})

    def test_present_studio_still_adds_to_collection(self, worker):
        """Regression guard: populated studio must still add to collection."""
        mock_plex_item = MagicMock()
        mock_plex_item.title = "Test"
        mock_plex_item.studio = ""
        mock_plex_item.summary = ""
        mock_plex_item.actors = []
        mock_plex_item.genres = []
        mock_plex_item.collections = []

        data = {
            'path': '/test.mp4',
            'title': 'Test',
            'studio': 'New Studio',
        }

        result = worker._update_metadata(mock_plex_item, data)

        assert 'collection' in result.fields_updated
        mock_plex_item.edit.assert_any_call(**{'collection[0].tag.tag': 'New Studio'})
