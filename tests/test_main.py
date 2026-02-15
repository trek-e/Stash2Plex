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
             patch('plex.client.PlexClient') as MockPlexClient, \
             patch('plex.health.check_plex_health') as mock_check_health:

            # Setup mocks
            mock_scheduler = MockRecoveryScheduler.return_value
            mock_scheduler.should_check_recovery.return_value = True
            mock_check_health.return_value = (True, 50.0)
            mock_client = MockPlexClient.return_value

            # Call function
            maybe_check_recovery()

            # Verify RecoveryScheduler was created
            MockRecoveryScheduler.assert_called_once_with("/tmp/test_data")

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
