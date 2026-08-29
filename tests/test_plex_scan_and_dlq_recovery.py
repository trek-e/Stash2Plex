"""
Tests for issue #12 (D1/D2/D3): Plex scan trigger on PlexNotFound, the
extended PlexNotFound retry schedule, and the "Retry Not-Found Entries" DLQ
recovery task.

D4 (hydration errors classified permanent) is fixed separately for #10 and
is not covered here.
"""

import pickle
import time
from unittest.mock import MagicMock, Mock, patch

import pytest


# =============================================================================
# D1 — worker/processor.py triggers a scan on PlexNotFound
# =============================================================================


class TestScanTriggerOnNotFound:
    """SyncWorker._handle_job fires a Plex scan on the first PlexNotFound."""

    def _make_item(self, scene_id=1, retry_count=0, path='/stash/movies/foo.mp4'):
        return {
            'job_id': scene_id,
            'scene_id': scene_id,
            'update_type': 'metadata',
            'data': {'path': path},
            'enqueued_at': 1000.0,
            'job_key': f'scene_{scene_id}',
            'retry_count': retry_count,
        }

    def _make_worker(self, mock_queue_manager, mock_dlq, mock_config, tmp_path):
        from worker.processor import SyncWorker

        mock_config.plex_connect_timeout = 10.0
        mock_config.plex_read_timeout = 30.0
        mock_config.preserve_plex_edits = False
        mock_config.strict_matching = False
        mock_config.dlq_retention_days = 30
        mock_config.skip_not_found = False
        mock_config.trigger_plex_scan = True

        return SyncWorker(
            queue_manager=mock_queue_manager,
            dlq=mock_dlq,
            config=mock_config,
            data_dir=str(tmp_path),
        )

    def test_first_not_found_triggers_exactly_one_scan_call(
        self, mock_queue_manager, mock_dlq, mock_config, tmp_path
    ):
        from plex.exceptions import PlexNotFound

        worker = self._make_worker(mock_queue_manager, mock_dlq, mock_config, tmp_path)
        item = self._make_item(retry_count=0)

        with patch.object(worker, '_process_job', side_effect=PlexNotFound("not found")), \
             patch('Stash2Plex.trigger_plex_scan_for_scene') as mock_trigger:
            result = worker._handle_job(item, set(), {})

        assert result == 'retrying'
        mock_trigger.assert_called_once_with(
            1, stash=None, file_path='/stash/movies/foo.mp4',
            data_dir=str(tmp_path), cfg=mock_config,
        )

    def test_retry_beyond_first_attempt_does_not_trigger_scan(
        self, mock_queue_manager, mock_dlq, mock_config, tmp_path
    ):
        """A job that's already retried once must not re-trigger a scan."""
        from plex.exceptions import PlexNotFound

        worker = self._make_worker(mock_queue_manager, mock_dlq, mock_config, tmp_path)
        item = self._make_item(retry_count=1)

        with patch.object(worker, '_process_job', side_effect=PlexNotFound("not found")), \
             patch('Stash2Plex.trigger_plex_scan_for_scene') as mock_trigger:
            worker._handle_job(item, set(), {})

        mock_trigger.assert_not_called()

    def test_skip_not_found_enabled_never_triggers_scan(
        self, mock_queue_manager, mock_dlq, mock_config, tmp_path
    ):
        """skip_not_found=True: no scan, and ack-without-DLQ behaviour unchanged."""
        from plex.exceptions import PlexNotFound

        worker = self._make_worker(mock_queue_manager, mock_dlq, mock_config, tmp_path)
        worker.config.skip_not_found = True
        item = self._make_item(retry_count=0)

        with patch.object(worker, '_process_job', side_effect=PlexNotFound("not found")), \
             patch('Stash2Plex.trigger_plex_scan_for_scene') as mock_trigger:
            result = worker._handle_job(item, set(), {})

        mock_trigger.assert_not_called()
        assert result == 'skipped'
        worker.queue_manager.ack.assert_called_once_with(item)
        worker.dlq.add.assert_not_called()

    def test_trigger_plex_scan_disabled_short_circuits_without_import_error(
        self, mock_queue_manager, mock_dlq, mock_config, tmp_path
    ):
        """trigger_plex_scan=False: no scan attempted, no exception."""
        from plex.exceptions import PlexNotFound

        worker = self._make_worker(mock_queue_manager, mock_dlq, mock_config, tmp_path)
        worker.config.trigger_plex_scan = False
        item = self._make_item(retry_count=0)

        with patch.object(worker, '_process_job', side_effect=PlexNotFound("not found")), \
             patch('Stash2Plex.trigger_plex_scan_for_scene') as mock_trigger:
            result = worker._handle_job(item, set(), {})

        mock_trigger.assert_not_called()
        assert result == 'retrying'

    def test_scan_trigger_exception_never_propagates_into_retry_pipeline(
        self, mock_queue_manager, mock_dlq, mock_config, tmp_path
    ):
        """A broken scan trigger must not stop the job from being requeued."""
        from plex.exceptions import PlexNotFound

        worker = self._make_worker(mock_queue_manager, mock_dlq, mock_config, tmp_path)
        item = self._make_item(retry_count=0)

        with patch.object(worker, '_process_job', side_effect=PlexNotFound("not found")), \
             patch('Stash2Plex.trigger_plex_scan_for_scene', side_effect=RuntimeError("boom")):
            result = worker._handle_job(item, set(), {})

        assert result == 'retrying'
        worker.queue_manager.reenqueue.assert_called_once()


# =============================================================================
# D1 — worker/scan_throttle.py
# =============================================================================


class TestScanThrottle:
    """Per-library-section throttle for triggered scans."""

    def test_should_scan_true_with_no_history(self, tmp_path):
        from worker.scan_throttle import ScanThrottle

        throttle = ScanThrottle(str(tmp_path))
        assert throttle.should_scan("Adult") is True

    def test_should_scan_false_within_window(self, tmp_path):
        from worker.scan_throttle import ScanThrottle

        throttle = ScanThrottle(str(tmp_path), interval_seconds=600)
        throttle.record_scan("Adult", now=1000.0)

        assert throttle.should_scan("Adult", now=1000.0 + 300) is False

    def test_should_scan_true_after_window_elapses(self, tmp_path):
        from worker.scan_throttle import ScanThrottle

        throttle = ScanThrottle(str(tmp_path), interval_seconds=600)
        throttle.record_scan("Adult", now=1000.0)

        assert throttle.should_scan("Adult", now=1000.0 + 601) is True

    def test_throttle_is_per_library(self, tmp_path):
        from worker.scan_throttle import ScanThrottle

        throttle = ScanThrottle(str(tmp_path), interval_seconds=600)
        throttle.record_scan("Adult", now=1000.0)

        assert throttle.should_scan("Movies", now=1000.0) is True

    def test_corrupt_state_file_does_not_raise_and_scans_anyway(self, tmp_path):
        from worker.scan_throttle import ScanThrottle, STATE_FILE

        state_path = tmp_path / STATE_FILE
        state_path.write_text("{not valid json")

        throttle = ScanThrottle(str(tmp_path))
        assert throttle.should_scan("Adult") is True

        # record_scan must also survive a corrupt file without raising
        throttle.record_scan("Adult")

    def test_unreadable_state_file_falls_back_to_scan_anyway(self, tmp_path):
        """A state file that raises on read (not just bad JSON) still must not
        propagate into the caller."""
        from worker.scan_throttle import ScanThrottle, STATE_FILE

        state_path = tmp_path / STATE_FILE
        state_path.write_text('{"Adult": 1000.0}')

        throttle = ScanThrottle(str(tmp_path))

        with patch("builtins.open", side_effect=OSError("permission denied")):
            assert throttle.should_scan("Adult") is True

    def test_default_interval_is_ten_minutes(self):
        from worker.scan_throttle import DEFAULT_THROTTLE_INTERVAL_SECONDS

        assert DEFAULT_THROTTLE_INTERVAL_SECONDS == 600


# =============================================================================
# D1 — Stash2Plex.trigger_plex_scan_for_scene (throttling + path translation)
# =============================================================================


class TestTriggerPlexScanForScene:
    def _cfg(self, **overrides):
        cfg = Mock()
        cfg.trigger_plex_scan = True
        cfg.plex_libraries = ["Adult"]
        cfg.plex_url = "http://localhost:32400"
        cfg.plex_token = "token"
        cfg.plex_connect_timeout = 5.0
        cfg.plex_read_timeout = 30.0
        cfg.plex_unmatched_path_map = None
        for k, v in overrides.items():
            setattr(cfg, k, v)
        return cfg

    def test_scans_all_configured_libraries_with_untranslated_path(self, tmp_path):
        from Stash2Plex import trigger_plex_scan_for_scene

        cfg = self._cfg(plex_libraries=["Adult", "Movies"])

        with patch('plex.client.PlexClient') as MockPlexClient:
            mock_client = MockPlexClient.return_value
            result = trigger_plex_scan_for_scene(
                1, stash=None, file_path='/stash/media/foo/bar.mp4',
                data_dir=str(tmp_path), cfg=cfg,
            )

        assert result is True
        assert mock_client.scan_library.call_count == 2
        calls = {c.args[0]: c.kwargs.get('path') for c in mock_client.scan_library.call_args_list}
        assert calls == {
            "Adult": "/stash/media/foo",
            "Movies": "/stash/media/foo",
        }

    def test_path_translated_when_mapping_configured(self, tmp_path):
        from Stash2Plex import trigger_plex_scan_for_scene

        # Format is 'plex_prefix=>stash_prefix' (matches plex_unmatched_path_map's
        # documented semantics; reconciliation/engine.py uses the same convention).
        cfg = self._cfg(plex_unmatched_path_map="/data/plex=>/data/stash")

        with patch('plex.client.PlexClient') as MockPlexClient:
            mock_client = MockPlexClient.return_value
            trigger_plex_scan_for_scene(
                1, stash=None, file_path='/data/stash/movies/foo.mp4',
                data_dir=str(tmp_path), cfg=cfg,
            )

        mock_client.scan_library.assert_called_once_with("Adult", path="/data/plex/movies")

    def test_path_unchanged_when_no_mapping_configured(self, tmp_path):
        from Stash2Plex import trigger_plex_scan_for_scene

        cfg = self._cfg(plex_unmatched_path_map=None)

        with patch('plex.client.PlexClient') as MockPlexClient:
            mock_client = MockPlexClient.return_value
            trigger_plex_scan_for_scene(
                1, stash=None, file_path='/data/stash/movies/foo.mp4',
                data_dir=str(tmp_path), cfg=cfg,
            )

        mock_client.scan_library.assert_called_once_with("Adult", path="/data/stash/movies")

    def test_second_call_within_throttle_window_does_not_scan_again(self, tmp_path):
        from Stash2Plex import trigger_plex_scan_for_scene

        cfg = self._cfg()

        with patch('plex.client.PlexClient') as MockPlexClient:
            mock_client = MockPlexClient.return_value
            trigger_plex_scan_for_scene(
                1, stash=None, file_path='/stash/a.mp4', data_dir=str(tmp_path), cfg=cfg,
            )
            result = trigger_plex_scan_for_scene(
                2, stash=None, file_path='/stash/b.mp4', data_dir=str(tmp_path), cfg=cfg,
            )

        assert result is False
        mock_client.scan_library.assert_called_once()

    def test_scan_after_throttle_window_elapses_fires_again(self, tmp_path):
        from Stash2Plex import trigger_plex_scan_for_scene
        from worker.scan_throttle import ScanThrottle

        cfg = self._cfg()

        # Pre-seed throttle state far enough in the past that the window has
        # already elapsed.
        throttle = ScanThrottle(str(tmp_path))
        throttle.record_scan("Adult", now=time.time() - 999999)

        with patch('plex.client.PlexClient') as MockPlexClient:
            mock_client = MockPlexClient.return_value
            result = trigger_plex_scan_for_scene(
                1, stash=None, file_path='/stash/a.mp4', data_dir=str(tmp_path), cfg=cfg,
            )

        assert result is True
        mock_client.scan_library.assert_called_once()

    def test_disabled_config_returns_false_without_touching_plex(self, tmp_path):
        from Stash2Plex import trigger_plex_scan_for_scene

        cfg = self._cfg(trigger_plex_scan=False)

        with patch('plex.client.PlexClient') as MockPlexClient:
            result = trigger_plex_scan_for_scene(
                1, stash=None, file_path='/stash/a.mp4', data_dir=str(tmp_path), cfg=cfg,
            )
            MockPlexClient.assert_not_called()

        assert result is False

    def test_corrupt_throttle_state_does_not_block_scan(self, tmp_path):
        from Stash2Plex import trigger_plex_scan_for_scene
        from worker.scan_throttle import STATE_FILE

        cfg = self._cfg()
        (tmp_path / STATE_FILE).write_text("not json at all")

        with patch('plex.client.PlexClient') as MockPlexClient:
            mock_client = MockPlexClient.return_value
            result = trigger_plex_scan_for_scene(
                1, stash=None, file_path='/stash/a.mp4', data_dir=str(tmp_path), cfg=cfg,
            )

        assert result is True
        mock_client.scan_library.assert_called_once()

    def test_falls_back_to_stash_lookup_when_no_file_path_given(self, tmp_path):
        """Backward-compat path: no file_path supplied -> looks up via stash."""
        from Stash2Plex import trigger_plex_scan_for_scene

        cfg = self._cfg()
        stash = Mock()
        stash.find_scene.return_value = {"files": [{"path": "/stash/x/y.mp4"}]}

        with patch('plex.client.PlexClient') as MockPlexClient:
            mock_client = MockPlexClient.return_value
            result = trigger_plex_scan_for_scene(42, stash=stash, data_dir=str(tmp_path), cfg=cfg)

        assert result is True
        stash.find_scene.assert_called_once_with(42)
        mock_client.scan_library.assert_called_once_with("Adult", path="/stash/x")


# =============================================================================
# D3 — Retry Not-Found Entries task
# =============================================================================


@pytest.fixture
def dlq(tmp_path):
    from sync_queue.dlq import DeadLetterQueue
    return DeadLetterQueue(str(tmp_path))


def _insert_dlq_entry(dlq, scene_id, error_type, failed_at):
    job = {"job_id": scene_id, "scene_id": scene_id, "update_type": "metadata", "data": {}}
    with dlq._get_connection() as conn:
        conn.execute(
            "INSERT INTO dead_letters (scene_id, job_data, error_type, failed_at) "
            "VALUES (?, ?, ?, datetime(?, 'unixepoch'))",
            (scene_id, pickle.dumps(job), error_type, failed_at),
        )
        conn.commit()


class TestGetDlqEntriesByErrorTypes:
    def test_ignores_time_window_returns_matching_type_regardless_of_age(self, dlq):
        from sync_queue.dlq_recovery import get_dlq_entries_by_error_types

        very_old = time.time() - (365 * 24 * 3600)
        _insert_dlq_entry(dlq, 100, "PlexNotFound", very_old)

        result = get_dlq_entries_by_error_types(dlq, ["PlexNotFound"])

        assert len(result) == 1
        assert result[0]["scene_id"] == 100

    def test_other_error_types_excluded(self, dlq):
        from sync_queue.dlq_recovery import get_dlq_entries_by_error_types

        _insert_dlq_entry(dlq, 100, "PlexNotFound", time.time())
        _insert_dlq_entry(dlq, 101, "PlexServerDown", time.time())
        _insert_dlq_entry(dlq, 102, "PlexTemporaryError", time.time())

        result = get_dlq_entries_by_error_types(dlq, ["PlexNotFound"])

        assert [r["scene_id"] for r in result] == [100]

    def test_empty_error_types_returns_empty_list(self, dlq):
        from sync_queue.dlq_recovery import get_dlq_entries_by_error_types

        _insert_dlq_entry(dlq, 100, "PlexNotFound", time.time())
        assert get_dlq_entries_by_error_types(dlq, []) == []


class TestHandleRetryNotFoundJobs:
    """Tests for Stash2Plex.handle_retry_not_found_jobs()."""

    def test_registered_in_management_handlers(self):
        from Stash2Plex import _MANAGEMENT_HANDLERS

        assert 'retry_not_found' in _MANAGEMENT_HANDLERS

    def test_registered_in_management_modes(self):
        import Stash2Plex
        source = open(Stash2Plex.__file__).read()

        assert "'retry_not_found'" in source
        assert "management_modes = {" in source

    def test_task_declared_in_yml(self):
        import os
        yml_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'Stash2Plex.yml')
        with open(yml_path) as f:
            yml_content = f.read()

        assert 'Retry Not-Found Entries' in yml_content
        assert 'mode: retry_not_found' in yml_content

    @patch('Stash2Plex.get_plugin_data_dir')
    def test_requeues_plex_not_found_entries_ignoring_outage_history(
        self, mock_get_data_dir, dlq, tmp_path
    ):
        import Stash2Plex

        mock_get_data_dir.return_value = str(tmp_path)

        # No OutageHistory records exist at all — unlike handle_recover_outage_jobs,
        # this must still find and requeue the PlexNotFound entry.
        old_time = time.time() - (365 * 24 * 3600)
        _insert_dlq_entry(dlq, 100, "PlexNotFound", old_time)
        _insert_dlq_entry(dlq, 101, "PlexServerDown", old_time)

        mock_queue_manager = MagicMock()
        mock_queue = Mock()
        mock_queue.path = str(tmp_path / "queue")
        mock_queue_manager.get_queue.return_value = mock_queue

        mock_config = Mock()
        mock_config.plex_url = "http://localhost:32400"
        mock_config.plex_token = "token"

        mock_stash = Mock()
        mock_stash.find_scene.return_value = {"id": 100}

        with patch.object(Stash2Plex, 'queue_manager', mock_queue_manager), \
             patch.object(Stash2Plex, 'config', mock_config), \
             patch.object(Stash2Plex, 'stash_interface', mock_stash), \
             patch('sync_queue.dlq_recovery.check_plex_health', return_value=(True, 5.0)), \
             patch('sync_queue.dlq_recovery.get_queued_scene_ids', return_value=set()), \
             patch('sync_queue.dlq_recovery.enqueue') as mock_enqueue, \
             patch('plex.client.PlexClient'):
            Stash2Plex.handle_retry_not_found_jobs()

        # Only the PlexNotFound entry (scene 100) was re-enqueued.
        assert mock_enqueue.call_count == 1
        assert mock_enqueue.call_args[0][1] == 100

    @patch('Stash2Plex.get_plugin_data_dir')
    def test_no_plex_not_found_entries_logs_and_returns(self, mock_get_data_dir, dlq, tmp_path):
        import Stash2Plex

        mock_get_data_dir.return_value = str(tmp_path)
        _insert_dlq_entry(dlq, 101, "PlexServerDown", time.time())

        with patch('Stash2Plex.log_info') as mock_log_info:
            Stash2Plex.handle_retry_not_found_jobs()

        log_calls = [c.args[0] for c in mock_log_info.call_args_list]
        assert any("No PlexNotFound DLQ entries found" in msg for msg in log_calls)


# =============================================================================
# Contract test — Stash2Plex.yml tasks stay in sync with _MANAGEMENT_HANDLERS
# =============================================================================


class TestYmlTaskHandlerContract:
    """Every management-mode task declared in Stash2Plex.yml must have a
    handler, and every _MANAGEMENT_HANDLERS entry must be reachable from a
    declared task (or be a bulk-sync mode handled separately)."""

    # Bulk-sync modes are routed through handle_bulk_sync(), not
    # _MANAGEMENT_HANDLERS — see Stash2Plex.handle_task().
    BULK_SYNC_MODES = {'all', 'recent'}

    def _yml_modes(self):
        import os
        import re

        yml_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'Stash2Plex.yml')
        with open(yml_path) as f:
            yml_content = f.read()

        # Only look within the `tasks:` section (stop at `settings:`).
        tasks_section = yml_content.split('settings:')[0]
        return set(re.findall(r'mode:\s*(\S+)', tasks_section))

    def test_every_yml_task_mode_is_handled(self):
        from Stash2Plex import _MANAGEMENT_HANDLERS

        modes = self._yml_modes()
        assert modes, "Expected at least one task mode in Stash2Plex.yml"

        for mode in modes:
            assert mode in _MANAGEMENT_HANDLERS or mode in self.BULK_SYNC_MODES, (
                f"Task mode '{mode}' in Stash2Plex.yml has no handler in "
                f"_MANAGEMENT_HANDLERS and isn't a bulk-sync mode"
            )

    def test_every_management_handler_is_declared_in_yml(self):
        from Stash2Plex import _MANAGEMENT_HANDLERS

        modes = self._yml_modes()
        for mode in _MANAGEMENT_HANDLERS:
            assert mode in modes, (
                f"_MANAGEMENT_HANDLERS entry '{mode}' has no corresponding "
                f"task declared in Stash2Plex.yml"
            )
