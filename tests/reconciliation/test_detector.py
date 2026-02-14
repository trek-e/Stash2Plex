"""Tests for gap detection engine."""
import pytest
from datetime import datetime, timezone
from reconciliation.detector import GapDetector, GapResult, has_meaningful_metadata


class TestHasMeaningfulMetadata:
    """Test the has_meaningful_metadata helper function."""

    def test_has_studio(self):
        """Returns True if data has studio."""
        data = {'studio': 'Some Studio'}
        assert has_meaningful_metadata(data) is True

    def test_has_performers(self):
        """Returns True if data has performers."""
        data = {'performers': [{'name': 'Actor'}]}
        assert has_meaningful_metadata(data) is True

    def test_has_tags(self):
        """Returns True if data has tags."""
        data = {'tags': [{'name': 'Genre'}]}
        assert has_meaningful_metadata(data) is True

    def test_has_details(self):
        """Returns True if data has details."""
        data = {'details': 'Some description'}
        assert has_meaningful_metadata(data) is True

    def test_has_date(self):
        """Returns True if data has date."""
        data = {'date': '2026-01-15'}
        assert has_meaningful_metadata(data) is True

    def test_no_meaningful_metadata(self):
        """Returns False if data has no meaningful metadata."""
        data = {'title': 'Just a title', 'path': '/some/path'}
        assert has_meaningful_metadata(data) is False

    def test_empty_dict(self):
        """Returns False for empty dict."""
        assert has_meaningful_metadata({}) is False

    def test_multiple_fields(self):
        """Returns True if data has multiple meaningful fields."""
        data = {
            'studio': 'Studio',
            'performers': [{'name': 'Actor'}],
            'tags': [{'name': 'Genre'}]
        }
        assert has_meaningful_metadata(data) is True


class TestDetectEmptyMetadata:
    """Test empty metadata detection."""

    def test_stash_has_metadata_plex_has_none(self):
        """Detects gap when Stash has metadata but Plex has none."""
        detector = GapDetector()
        stash_scenes = [
            {
                'id': 1,
                'studio': 'Test Studio',
                'performers': [{'name': 'Test Actor'}],
                'files': [{'path': '/videos/scene1.mp4'}]
            }
        ]
        plex_items_metadata = {
            '/videos/scene1.mp4': {
                'studio': None,
                'performers': [],
                'tags': [],
                'details': None,
                'date': None
            }
        }

        results = detector.detect_empty_metadata(stash_scenes, plex_items_metadata)

        assert len(results) == 1
        assert results[0].scene_id == 1
        assert results[0].gap_type == 'empty_metadata'
        assert results[0].scene_data == stash_scenes[0]
        assert 'no meaningful metadata' in results[0].reason.lower()

    def test_stash_has_tags_only_plex_has_none(self):
        """Detects gap when Stash has only tags but Plex has none."""
        detector = GapDetector()
        stash_scenes = [
            {
                'id': 2,
                'tags': [{'name': 'Drama'}],
                'files': [{'path': '/videos/scene2.mp4'}]
            }
        ]
        plex_items_metadata = {
            '/videos/scene2.mp4': {
                'studio': None,
                'performers': [],
                'tags': [],
                'details': None,
                'date': None
            }
        }

        results = detector.detect_empty_metadata(stash_scenes, plex_items_metadata)

        assert len(results) == 1
        assert results[0].scene_id == 2

    def test_both_have_metadata(self):
        """No gap when both Stash and Plex have metadata."""
        detector = GapDetector()
        stash_scenes = [
            {
                'id': 3,
                'studio': 'Test Studio',
                'files': [{'path': '/videos/scene3.mp4'}]
            }
        ]
        plex_items_metadata = {
            '/videos/scene3.mp4': {
                'studio': 'Plex Studio',
                'performers': [],
                'tags': [],
                'details': None,
                'date': None
            }
        }

        results = detector.detect_empty_metadata(stash_scenes, plex_items_metadata)

        assert len(results) == 0

    def test_neither_has_metadata(self):
        """No gap when neither Stash nor Plex has metadata."""
        detector = GapDetector()
        stash_scenes = [
            {
                'id': 4,
                'files': [{'path': '/videos/scene4.mp4'}]
            }
        ]
        plex_items_metadata = {
            '/videos/scene4.mp4': {
                'studio': None,
                'performers': [],
                'tags': [],
                'details': None,
                'date': None
            }
        }

        results = detector.detect_empty_metadata(stash_scenes, plex_items_metadata)

        assert len(results) == 0

    def test_plex_has_studio_no_gap(self):
        """No gap when Plex has studio even if missing other fields."""
        detector = GapDetector()
        stash_scenes = [
            {
                'id': 5,
                'studio': 'Stash Studio',
                'performers': [{'name': 'Actor'}],
                'files': [{'path': '/videos/scene5.mp4'}]
            }
        ]
        plex_items_metadata = {
            '/videos/scene5.mp4': {
                'studio': 'Plex Studio',
                'performers': [],
                'tags': [],
                'details': None,
                'date': None
            }
        }

        results = detector.detect_empty_metadata(stash_scenes, plex_items_metadata)

        assert len(results) == 0

    def test_no_plex_match(self):
        """Skips scenes with no Plex match."""
        detector = GapDetector()
        stash_scenes = [
            {
                'id': 6,
                'studio': 'Test Studio',
                'files': [{'path': '/videos/scene6.mp4'}]
            }
        ]
        plex_items_metadata = {}  # No Plex match for this scene

        results = detector.detect_empty_metadata(stash_scenes, plex_items_metadata)

        assert len(results) == 0

    def test_scene_without_files(self):
        """Skips scenes without files."""
        detector = GapDetector()
        stash_scenes = [
            {
                'id': 7,
                'studio': 'Test Studio',
                'files': []
            }
        ]
        plex_items_metadata = {}

        results = detector.detect_empty_metadata(stash_scenes, plex_items_metadata)

        assert len(results) == 0

    def test_multiple_scenes_mixed_results(self):
        """Correctly handles multiple scenes with mixed results."""
        detector = GapDetector()
        stash_scenes = [
            {
                'id': 8,
                'studio': 'Studio A',
                'files': [{'path': '/videos/scene8.mp4'}]
            },
            {
                'id': 9,
                'studio': 'Studio B',
                'files': [{'path': '/videos/scene9.mp4'}]
            },
            {
                'id': 10,
                'files': [{'path': '/videos/scene10.mp4'}]
            }
        ]
        plex_items_metadata = {
            '/videos/scene8.mp4': {
                'studio': None,
                'performers': [],
                'tags': [],
                'details': None,
                'date': None
            },
            '/videos/scene9.mp4': {
                'studio': 'Plex Studio',
                'performers': [],
                'tags': [],
                'details': None,
                'date': None
            },
            '/videos/scene10.mp4': {
                'studio': None,
                'performers': [],
                'tags': [],
                'details': None,
                'date': None
            }
        }

        results = detector.detect_empty_metadata(stash_scenes, plex_items_metadata)

        assert len(results) == 1
        assert results[0].scene_id == 8


class TestDetectStaleSyncs:
    """Test stale sync detection."""

    def test_stash_updated_after_sync(self):
        """Detects gap when Stash updated_at is newer than sync timestamp."""
        detector = GapDetector()
        stash_scenes = [
            {
                'id': 1,
                'updated_at': '2026-02-10T12:00:00Z',
                'files': [{'path': '/videos/scene1.mp4'}]
            }
        ]
        sync_timestamps = {
            1: datetime(2026, 2, 1, 12, 0, 0, tzinfo=timezone.utc).timestamp()
        }

        results = detector.detect_stale_syncs(stash_scenes, sync_timestamps)

        assert len(results) == 1
        assert results[0].scene_id == 1
        assert results[0].gap_type == 'stale_sync'
        assert results[0].scene_data == stash_scenes[0]
        assert 'stale' in results[0].reason.lower()

    def test_sync_timestamp_newer_than_updated_at(self):
        """No gap when sync timestamp is newer than Stash updated_at."""
        detector = GapDetector()
        stash_scenes = [
            {
                'id': 2,
                'updated_at': '2026-02-01T12:00:00Z',
                'files': [{'path': '/videos/scene2.mp4'}]
            }
        ]
        sync_timestamps = {
            2: datetime(2026, 2, 10, 12, 0, 0, tzinfo=timezone.utc).timestamp()
        }

        results = detector.detect_stale_syncs(stash_scenes, sync_timestamps)

        assert len(results) == 0

    def test_no_sync_timestamp(self):
        """No gap for scenes with no sync timestamp (handled by detect_missing)."""
        detector = GapDetector()
        stash_scenes = [
            {
                'id': 3,
                'updated_at': '2026-02-10T12:00:00Z',
                'files': [{'path': '/videos/scene3.mp4'}]
            }
        ]
        sync_timestamps = {}

        results = detector.detect_stale_syncs(stash_scenes, sync_timestamps)

        assert len(results) == 0

    def test_no_updated_at(self):
        """No gap for scenes without updated_at field."""
        detector = GapDetector()
        stash_scenes = [
            {
                'id': 4,
                'files': [{'path': '/videos/scene4.mp4'}]
            }
        ]
        sync_timestamps = {
            4: datetime(2026, 2, 1, 12, 0, 0, tzinfo=timezone.utc).timestamp()
        }

        results = detector.detect_stale_syncs(stash_scenes, sync_timestamps)

        assert len(results) == 0

    def test_updated_at_none(self):
        """No gap for scenes with updated_at set to None."""
        detector = GapDetector()
        stash_scenes = [
            {
                'id': 5,
                'updated_at': None,
                'files': [{'path': '/videos/scene5.mp4'}]
            }
        ]
        sync_timestamps = {
            5: datetime(2026, 2, 1, 12, 0, 0, tzinfo=timezone.utc).timestamp()
        }

        results = detector.detect_stale_syncs(stash_scenes, sync_timestamps)

        assert len(results) == 0

    def test_multiple_scenes_mixed_results(self):
        """Correctly handles multiple scenes with mixed staleness."""
        detector = GapDetector()
        stash_scenes = [
            {
                'id': 6,
                'updated_at': '2026-02-10T12:00:00Z',
                'files': [{'path': '/videos/scene6.mp4'}]
            },
            {
                'id': 7,
                'updated_at': '2026-02-01T12:00:00Z',
                'files': [{'path': '/videos/scene7.mp4'}]
            },
            {
                'id': 8,
                'updated_at': '2026-02-15T12:00:00Z',
                'files': [{'path': '/videos/scene8.mp4'}]
            }
        ]
        sync_timestamps = {
            6: datetime(2026, 2, 1, 12, 0, 0, tzinfo=timezone.utc).timestamp(),
            7: datetime(2026, 2, 10, 12, 0, 0, tzinfo=timezone.utc).timestamp(),
            8: datetime(2026, 2, 5, 12, 0, 0, tzinfo=timezone.utc).timestamp()
        }

        results = detector.detect_stale_syncs(stash_scenes, sync_timestamps)

        assert len(results) == 2
        assert {r.scene_id for r in results} == {6, 8}


class TestDetectMissing:
    """Test missing item detection."""

    def test_no_sync_no_match(self):
        """Detects gap when scene has no sync timestamp and no Plex match."""
        detector = GapDetector()
        stash_scenes = [
            {
                'id': 1,
                'files': [{'path': '/videos/scene1.mp4'}]
            }
        ]
        sync_timestamps = {}
        matched_paths = set()

        results = detector.detect_missing(stash_scenes, sync_timestamps, matched_paths)

        assert len(results) == 1
        assert results[0].scene_id == 1
        assert results[0].gap_type == 'missing'
        assert results[0].scene_data == stash_scenes[0]
        assert 'missing' in results[0].reason.lower()

    def test_no_sync_but_has_match(self):
        """No gap when scene has no sync timestamp but has a Plex match."""
        detector = GapDetector()
        stash_scenes = [
            {
                'id': 2,
                'files': [{'path': '/videos/scene2.mp4'}]
            }
        ]
        sync_timestamps = {}
        matched_paths = {'/videos/scene2.mp4'}

        results = detector.detect_missing(stash_scenes, sync_timestamps, matched_paths)

        assert len(results) == 0

    def test_has_sync_timestamp(self):
        """No gap when scene has a sync timestamp."""
        detector = GapDetector()
        stash_scenes = [
            {
                'id': 3,
                'files': [{'path': '/videos/scene3.mp4'}]
            }
        ]
        sync_timestamps = {
            3: datetime(2026, 2, 1, 12, 0, 0, tzinfo=timezone.utc).timestamp()
        }
        matched_paths = set()

        results = detector.detect_missing(stash_scenes, sync_timestamps, matched_paths)

        assert len(results) == 0

    def test_scene_without_files(self):
        """Skips scenes without files."""
        detector = GapDetector()
        stash_scenes = [
            {
                'id': 4,
                'files': []
            }
        ]
        sync_timestamps = {}
        matched_paths = set()

        results = detector.detect_missing(stash_scenes, sync_timestamps, matched_paths)

        assert len(results) == 0

    def test_multiple_scenes_mixed_results(self):
        """Correctly handles multiple scenes with mixed missing status."""
        detector = GapDetector()
        stash_scenes = [
            {
                'id': 5,
                'files': [{'path': '/videos/scene5.mp4'}]
            },
            {
                'id': 6,
                'files': [{'path': '/videos/scene6.mp4'}]
            },
            {
                'id': 7,
                'files': [{'path': '/videos/scene7.mp4'}]
            }
        ]
        sync_timestamps = {
            6: datetime(2026, 2, 1, 12, 0, 0, tzinfo=timezone.utc).timestamp()
        }
        matched_paths = {'/videos/scene7.mp4'}

        results = detector.detect_missing(stash_scenes, sync_timestamps, matched_paths)

        assert len(results) == 1
        assert results[0].scene_id == 5


class TestGapResult:
    """Test GapResult dataclass."""

    def test_create_gap_result(self):
        """Can create GapResult with all fields."""
        scene_data = {'id': 1, 'title': 'Test'}
        result = GapResult(
            scene_id=1,
            gap_type='empty_metadata',
            scene_data=scene_data,
            reason='Test reason'
        )

        assert result.scene_id == 1
        assert result.gap_type == 'empty_metadata'
        assert result.scene_data == scene_data
        assert result.reason == 'Test reason'
