"""
Integration tests for main loop functions in Stash2Plex.py.

Tests for maybe_check_recovery() function that runs recovery detection
on every plugin invocation.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch

from worker.circuit_breaker import CircuitState


class TestMaybeCheckRecovery:
    """Integration tests for maybe_check_recovery()."""

    @patch('Stash2Plex.config', None)
    @patch('Stash2Plex.worker', None)
    def test_skips_when_no_config(self):
        """Skips when config is None."""
        from Stash2Plex import maybe_check_recovery

        # Should not raise, just return early
        maybe_check_recovery()
        # No assertions needed - test passes if no exception raised

    @patch('Stash2Plex.config', Mock())
    @patch('Stash2Plex.worker', None)
    def test_skips_when_no_worker(self):
        """Skips when worker is None."""
        from Stash2Plex import maybe_check_recovery

        # Should not raise, just return early
        maybe_check_recovery()

    @patch('Stash2Plex.get_plugin_data_dir')
    @patch('Stash2Plex.config')
    @patch('Stash2Plex.worker')
    def test_skips_when_circuit_closed(self, mock_worker, mock_config, mock_get_data_dir):
        """Skips when circuit breaker is CLOSED (early return before RecoveryScheduler)."""
        from Stash2Plex import maybe_check_recovery

        # Setup: circuit is CLOSED
        mock_worker.circuit_breaker.state = CircuitState.CLOSED
        mock_config.plex_url = "http://plex:32400"
        mock_config.plex_token = "test-token"

        # Should return early, not call RecoveryScheduler
        maybe_check_recovery()

        # Verify no data_dir access (means early return happened)
        mock_get_data_dir.assert_not_called()

    @patch('Stash2Plex.queue_manager')
    @patch('Stash2Plex.get_plugin_data_dir')
    @patch('Stash2Plex.config')
    @patch('Stash2Plex.worker')
    def test_runs_health_check_when_circuit_open(self, mock_worker, mock_config, mock_get_data_dir, mock_queue_manager):
        """Runs health check when circuit is OPEN and check is due."""
        from Stash2Plex import maybe_check_recovery

        # Setup: circuit is OPEN
        mock_worker.circuit_breaker.state = CircuitState.OPEN
        mock_config.plex_url = "http://plex:32400"
        mock_config.plex_token = "test-token"
        mock_get_data_dir.return_value = "/tmp/test_data"

        # Mock queue manager
        mock_queue = Mock()
        mock_queue.size = 0
        mock_queue_manager.get_queue.return_value = mock_queue

        with patch('worker.recovery.RecoveryScheduler') as MockRecoveryScheduler, \
             patch('worker.outage_history.OutageHistory') as MockOutageHistory, \
             patch('plex.client.PlexClient') as MockPlexClient, \
             patch('plex.health.check_plex_health') as mock_check_health:

            # Setup mocks
            mock_outage_history = MockOutageHistory.return_value
            mock_scheduler = MockRecoveryScheduler.return_value
            mock_scheduler.should_check_recovery.return_value = True
            mock_check_health.return_value = (True, 50.0)
            mock_client = MockPlexClient.return_value

            # Call function
            maybe_check_recovery()

            # Verify RecoveryScheduler was created with outage_history
            MockRecoveryScheduler.assert_called_once_with("/tmp/test_data", outage_history=mock_outage_history)

            # Verify should_check_recovery was called
            mock_scheduler.should_check_recovery.assert_called_once_with(CircuitState.OPEN)

            # Verify PlexClient was created with correct params
            MockPlexClient.assert_called_once_with(
                url="http://plex:32400",
                token="test-token",
                connect_timeout=5.0,
                read_timeout=5.0
            )

            # Verify health check was called
            mock_check_health.assert_called_once_with(mock_client, timeout=5.0)

            # Verify record_health_check was called
            mock_scheduler.record_health_check.assert_called_once_with(
                True, 50.0, mock_worker.circuit_breaker
            )

    @patch('Stash2Plex.get_plugin_data_dir')
    @patch('Stash2Plex.config')
    @patch('Stash2Plex.worker')
    def test_skips_when_not_due(self, mock_worker, mock_config, mock_get_data_dir):
        """Skips health check when should_check_recovery returns False."""
        from Stash2Plex import maybe_check_recovery

        # Setup: circuit is OPEN but check not due
        mock_worker.circuit_breaker.state = CircuitState.OPEN
        mock_config.plex_url = "http://plex:32400"
        mock_config.plex_token = "test-token"
        mock_get_data_dir.return_value = "/tmp/test_data"

        with patch('worker.recovery.RecoveryScheduler') as MockRecoveryScheduler, \
             patch('plex.health.check_plex_health') as mock_check_health:

            # Setup: should_check_recovery returns False
            mock_scheduler = MockRecoveryScheduler.return_value
            mock_scheduler.should_check_recovery.return_value = False

            # Call function
            maybe_check_recovery()

            # Verify health check was NOT called
            mock_check_health.assert_not_called()

    @patch('Stash2Plex.queue_manager')
    @patch('Stash2Plex.get_plugin_data_dir')
    @patch('Stash2Plex.config')
    @patch('Stash2Plex.worker')
    def test_logs_queue_drain_on_recovery(self, mock_worker, mock_config, mock_get_data_dir, mock_queue_manager):
        """Logs queue drain message when circuit transitions to CLOSED."""
        from Stash2Plex import maybe_check_recovery

        # Setup: circuit transitions from OPEN to CLOSED
        mock_worker.circuit_breaker.state = CircuitState.OPEN
        mock_config.plex_url = "http://plex:32400"
        mock_config.plex_token = "test-token"
        mock_get_data_dir.return_value = "/tmp/test_data"

        # Mock queue with pending items
        mock_queue = Mock()
        mock_queue.size = 5
        mock_queue_manager.get_queue.return_value = mock_queue

        with patch('worker.recovery.RecoveryScheduler') as MockRecoveryScheduler, \
             patch('plex.client.PlexClient'), \
             patch('plex.health.check_plex_health') as mock_check_health, \
             patch('Stash2Plex.log_info') as mock_log_info:

            # Setup mocks
            mock_scheduler = MockRecoveryScheduler.return_value
            mock_scheduler.should_check_recovery.return_value = True
            mock_check_health.return_value = (True, 50.0)

            # Simulate circuit transition: after record_health_check, circuit is CLOSED
            def record_and_transition(success, latency, circuit_breaker):
                # Simulate transition to CLOSED
                mock_worker.circuit_breaker.state = CircuitState.CLOSED

            mock_scheduler.record_health_check.side_effect = record_and_transition

            # Call function
            maybe_check_recovery()

            # Verify log_info was called with queue drain message
            log_calls = [str(call) for call in mock_log_info.call_args_list]
            assert any("Queue will drain automatically" in str(call) and "5 jobs pending" in str(call)
                      for call in log_calls), f"Expected queue drain log message, got: {log_calls}"

    @patch('Stash2Plex.get_plugin_data_dir')
    @patch('Stash2Plex.config')
    @patch('Stash2Plex.worker')
    def test_exception_does_not_crash(self, mock_worker, mock_config, mock_get_data_dir):
        """Exceptions are caught and logged at debug level without crashing."""
        from Stash2Plex import maybe_check_recovery

        # Setup: circuit is OPEN
        mock_worker.circuit_breaker.state = CircuitState.OPEN
        mock_config.plex_url = "http://plex:32400"
        mock_config.plex_token = "test-token"
        mock_get_data_dir.return_value = "/tmp/test_data"

        with patch('worker.recovery.RecoveryScheduler') as MockRecoveryScheduler, \
             patch('Stash2Plex.log_debug') as mock_log_debug:

            # Make RecoveryScheduler raise an exception
            MockRecoveryScheduler.side_effect = Exception("Test exception")

            # Should not raise
            maybe_check_recovery()

            # Verify exception was logged at debug level
            mock_log_debug.assert_called_once()
            assert "Recovery check failed" in mock_log_debug.call_args[0][0]


class TestOutageUIHandlers:
    """Tests for outage summary and queue status enhancements."""

    @patch('Stash2Plex.get_plugin_data_dir')
    def test_handle_outage_summary_no_outages(self, mock_get_data_dir):
        """handle_outage_summary logs 'No outages recorded' when history is empty."""
        from Stash2Plex import handle_outage_summary

        mock_get_data_dir.return_value = "/tmp/test_data"

        with patch('worker.outage_history.OutageHistory') as MockHistory, \
             patch('Stash2Plex.log_info') as mock_log_info:

            # Mock empty history
            mock_history_instance = MockHistory.return_value
            mock_history_instance.get_history.return_value = []

            handle_outage_summary()

            # Verify "No outages recorded" was logged
            log_calls = [call[0][0] for call in mock_log_info.call_args_list]
            assert any("No outages recorded" in msg for msg in log_calls)

    @patch('Stash2Plex.get_plugin_data_dir')
    def test_handle_outage_summary_with_outages(self, mock_get_data_dir):
        """handle_outage_summary displays metrics when outages exist."""
        from Stash2Plex import handle_outage_summary
        from worker.outage_history import OutageRecord

        mock_get_data_dir.return_value = "/tmp/test_data"

        # Create sample outage records
        records = [
            OutageRecord(started_at=1000.0, ended_at=1060.0, duration=60.0, jobs_affected=5),
            OutageRecord(started_at=2000.0, ended_at=2120.0, duration=120.0, jobs_affected=3),
        ]

        with patch('worker.outage_history.OutageHistory') as MockHistory, \
             patch('Stash2Plex.log_info') as mock_log_info:

            mock_history_instance = MockHistory.return_value
            mock_history_instance.get_history.return_value = records
            mock_history_instance.get_current_outage.return_value = None

            handle_outage_summary()

            # Verify metrics were logged
            log_calls = [call[0][0] for call in mock_log_info.call_args_list]
            log_output = " ".join(log_calls)

            assert "Outage Summary Report" in log_output
            assert "Total outages tracked" in log_output
            assert "MTTR" in log_output
            assert "Recent Outages" in log_output

    @patch('Stash2Plex.get_plugin_data_dir')
    def test_handle_queue_status_includes_circuit_breaker_section(self, mock_get_data_dir, tmp_path):
        """handle_queue_status includes Circuit Breaker Status section."""
        from Stash2Plex import handle_queue_status
        import json

        data_dir = str(tmp_path)
        mock_get_data_dir.return_value = data_dir

        # Create circuit_breaker.json
        cb_file = tmp_path / "circuit_breaker.json"
        cb_data = {
            "state": "closed",
            "failure_count": 0,
            "success_count": 0,
            "opened_at": None
        }
        cb_file.write_text(json.dumps(cb_data))

        # Create queue directory
        queue_dir = tmp_path / "queue"
        queue_dir.mkdir()

        with patch('Stash2Plex.log_info') as mock_log_info:
            handle_queue_status()

            # Verify Circuit Breaker Status section was logged
            log_calls = [call[0][0] for call in mock_log_info.call_args_list]
            log_output = " ".join(log_calls)

            assert "Circuit Breaker Status" in log_output
            assert "Recovery Status" in log_output
            assert "Recent Outages" in log_output

    def test_outage_summary_in_management_handlers(self):
        """Verify outage_summary is registered in _MANAGEMENT_HANDLERS."""
        from Stash2Plex import _MANAGEMENT_HANDLERS

        assert 'outage_summary' in _MANAGEMENT_HANDLERS

    def test_outage_summary_in_management_modes(self):
        """Verify outage_summary is in management_modes set."""
        # This is checked at runtime in main(), so we verify the string appears in the file
        import Stash2Plex
        source = open(Stash2Plex.__file__).read()

        assert 'outage_summary' in source
        assert "management_modes = {" in source

    # === Recover Outage Jobs Tests ===

    def test_recover_outage_jobs_in_management_handlers(self):
        """Verify recover_outage_jobs is registered in _MANAGEMENT_HANDLERS."""
        from Stash2Plex import _MANAGEMENT_HANDLERS

        assert 'recover_outage_jobs' in _MANAGEMENT_HANDLERS

    def test_recover_outage_jobs_in_management_modes(self):
        """Verify recover_outage_jobs is in management_modes set."""
        import Stash2Plex
        source = open(Stash2Plex.__file__).read()

        assert 'recover_outage_jobs' in source
        assert "management_modes = {" in source

    @patch('Stash2Plex.get_plugin_data_dir')
    def test_handle_recover_outage_jobs_no_outages(self, mock_get_data_dir):
        """handle_recover_outage_jobs logs 'No outage history found' when history is empty."""
        from Stash2Plex import handle_recover_outage_jobs

        mock_get_data_dir.return_value = "/tmp/test_data"

        with patch('worker.outage_history.OutageHistory') as MockHistory, \
             patch('Stash2Plex.log_info') as mock_log_info:

            # Mock empty history
            mock_history_instance = MockHistory.return_value
            mock_history_instance.get_history.return_value = []

            handle_recover_outage_jobs()

            # Verify "No outage history found" was logged
            log_calls = [call[0][0] for call in mock_log_info.call_args_list]
            assert any("No outage history found" in msg for msg in log_calls)

    @patch('Stash2Plex.get_plugin_data_dir')
    def test_handle_recover_outage_jobs_no_completed_outages(self, mock_get_data_dir):
        """handle_recover_outage_jobs logs error when no completed outages exist."""
        from Stash2Plex import handle_recover_outage_jobs
        from worker.outage_history import OutageRecord

        mock_get_data_dir.return_value = "/tmp/test_data"

        # Create ongoing outage (no ended_at)
        records = [
            OutageRecord(started_at=1000.0, ended_at=None, duration=0.0, jobs_affected=0)
        ]

        with patch('worker.outage_history.OutageHistory') as MockHistory, \
             patch('Stash2Plex.log_info') as mock_log_info:

            mock_history_instance = MockHistory.return_value
            mock_history_instance.get_history.return_value = records

            handle_recover_outage_jobs()

            # Verify "No completed outages found" was logged
            log_calls = [call[0][0] for call in mock_log_info.call_args_list]
            assert any("No completed outages found" in msg for msg in log_calls)

    @patch('Stash2Plex.get_plugin_data_dir')
    def test_handle_recover_outage_jobs_no_dlq_entries(self, mock_get_data_dir):
        """handle_recover_outage_jobs logs when no recoverable DLQ entries found."""
        from Stash2Plex import handle_recover_outage_jobs
        from worker.outage_history import OutageRecord

        mock_get_data_dir.return_value = "/tmp/test_data"

        # Completed outage
        records = [
            OutageRecord(started_at=1000.0, ended_at=1060.0, duration=60.0, jobs_affected=0)
        ]

        with patch('worker.outage_history.OutageHistory') as MockHistory, \
             patch('sync_queue.dlq.DeadLetterQueue') as MockDLQ, \
             patch('sync_queue.dlq_recovery.get_outage_dlq_entries') as mock_get_entries, \
             patch('sync_queue.dlq_recovery.get_error_types_for_recovery') as mock_get_error_types, \
             patch('Stash2Plex.log_info') as mock_log_info:

            mock_history_instance = MockHistory.return_value
            mock_history_instance.get_history.return_value = records

            # Mock no DLQ entries found
            mock_get_entries.return_value = []
            mock_get_error_types.return_value = ["PlexServerDown"]

            handle_recover_outage_jobs()

            # Verify "No recoverable DLQ entries found" was logged
            log_calls = [call[0][0] for call in mock_log_info.call_args_list]
            assert any("No recoverable DLQ entries found" in msg for msg in log_calls)

    @patch('Stash2Plex.stash_interface')
    @patch('Stash2Plex.queue_manager')
    @patch('Stash2Plex.config')
    @patch('Stash2Plex.get_plugin_data_dir')
    def test_handle_recover_outage_jobs_successful_recovery(self, mock_get_data_dir, mock_config, mock_queue_manager, mock_stash):
        """handle_recover_outage_jobs successfully recovers DLQ entries."""
        from Stash2Plex import handle_recover_outage_jobs
        from worker.outage_history import OutageRecord
        from sync_queue.dlq_recovery import RecoveryResult

        mock_get_data_dir.return_value = "/tmp/test_data"

        # Setup config
        mock_config.plex_url = "http://localhost:32400"
        mock_config.plex_token = "test-token"

        # Completed outage
        records = [
            OutageRecord(started_at=1000.0, ended_at=1060.0, duration=60.0, jobs_affected=2)
        ]

        # Mock DLQ entries
        dlq_entries = [
            {'id': 1, 'scene_id': 101, 'error_type': 'PlexServerDown'},
            {'id': 2, 'scene_id': 102, 'error_type': 'PlexServerDown'}
        ]

        # Mock recovery result
        recovery_result = RecoveryResult(
            total_dlq_entries=2,
            recovered=2,
            skipped_already_queued=0,
            skipped_plex_down=0,
            skipped_scene_missing=0,
            failed=0,
            recovered_scene_ids=[101, 102]
        )

        with patch('worker.outage_history.OutageHistory') as MockHistory, \
             patch('sync_queue.dlq.DeadLetterQueue') as MockDLQ, \
             patch('sync_queue.dlq_recovery.get_outage_dlq_entries') as mock_get_entries, \
             patch('sync_queue.dlq_recovery.get_error_types_for_recovery') as mock_get_error_types, \
             patch('sync_queue.dlq_recovery.recover_outage_jobs') as mock_recover, \
             patch('Stash2Plex.log_info') as mock_log_info:

            mock_history_instance = MockHistory.return_value
            mock_history_instance.get_history.return_value = records

            mock_get_entries.return_value = dlq_entries
            mock_get_error_types.return_value = ["PlexServerDown"]
            mock_recover.return_value = recovery_result

            # Mock queue manager
            mock_queue = MagicMock()
            mock_queue_manager.get_queue.return_value = mock_queue

            handle_recover_outage_jobs()

            # Verify recovery was called
            mock_recover.assert_called_once()

            # Verify results were logged
            log_calls = [call[0][0] for call in mock_log_info.call_args_list]
            log_output = " ".join(log_calls)

            assert "Recovery complete: 2 recovered" in log_output
            assert "Re-queued scene IDs" in log_output

    @patch('Stash2Plex.get_plugin_data_dir')
    def test_handle_recover_outage_jobs_uses_conservative_defaults(self, mock_get_data_dir):
        """handle_recover_outage_jobs uses conservative defaults (PlexServerDown only)."""
        from Stash2Plex import handle_recover_outage_jobs
        from worker.outage_history import OutageRecord

        mock_get_data_dir.return_value = "/tmp/test_data"

        # Completed outage
        records = [
            OutageRecord(started_at=1000.0, ended_at=1060.0, duration=60.0, jobs_affected=0)
        ]

        with patch('worker.outage_history.OutageHistory') as MockHistory, \
             patch('sync_queue.dlq.DeadLetterQueue') as MockDLQ, \
             patch('sync_queue.dlq_recovery.get_outage_dlq_entries') as mock_get_entries, \
             patch('sync_queue.dlq_recovery.get_error_types_for_recovery') as mock_get_error_types, \
             patch('Stash2Plex.log_info') as mock_log_info:

            mock_history_instance = MockHistory.return_value
            mock_history_instance.get_history.return_value = records

            mock_get_entries.return_value = []
            mock_get_error_types.return_value = ["PlexServerDown"]

            handle_recover_outage_jobs()

            # Verify get_error_types_for_recovery was called with include_optional=False
            mock_get_error_types.assert_called_once_with(include_optional=False)

            # Verify conservative filter was logged
            log_calls = [call[0][0] for call in mock_log_info.call_args_list]
            log_output = " ".join(log_calls)
            assert "Recovery filter: PlexServerDown" in log_output

    def test_recover_outage_jobs_task_registered_in_yml(self):
        """Verify 'Recover Outage Jobs' task exists in Stash2Plex.yml."""
        import os

        yml_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'Stash2Plex.yml')
        with open(yml_path, 'r') as f:
            yml_content = f.read()

        # Verify task exists with correct structure
        assert 'Recover Outage Jobs' in yml_content, "Task name not found in Stash2Plex.yml"
        assert 'mode: recover_outage_jobs' in yml_content, "Task mode not found in Stash2Plex.yml"

        # Verify description contains key information
        lines = yml_content.split('\n')
        found_task = False
        for i, line in enumerate(lines):
            if 'Recover Outage Jobs' in line:
                found_task = True
                # Check nearby lines for description
                context = '\n'.join(lines[max(0, i-2):min(len(lines), i+5)])
                assert 'PlexServerDown' in context, "Description should mention PlexServerDown errors"
                break

        assert found_task, "Could not find 'Recover Outage Jobs' task in yml"
