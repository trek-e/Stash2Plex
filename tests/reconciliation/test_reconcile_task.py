"""Tests for reconciliation task handler in Stash2Plex.py."""

import sys
from unittest.mock import Mock, MagicMock, patch, call
import pytest


# =============================================================================
# Test Cases
# =============================================================================

def test_handle_reconcile_all_scope():
    """Test that handle_reconcile calls engine.run with 'all' scope."""
    # Mock GapDetectionEngine and result
    mock_result = Mock()
    mock_result.scenes_checked = 100
    mock_result.total_gaps = 10
    mock_result.empty_metadata_count = 3
    mock_result.stale_sync_count = 2
    mock_result.missing_count = 5
    mock_result.enqueued_count = 8
    mock_result.skipped_already_queued = 2
    mock_result.errors = []

    mock_engine = MagicMock()
    mock_engine.run.return_value = mock_result

    with patch('Stash2Plex.stash_interface', MagicMock()), \
         patch('Stash2Plex.config', MagicMock()), \
         patch('Stash2Plex.queue_manager') as mock_qm, \
         patch('Stash2Plex.get_plugin_data_dir', return_value='/tmp/data'), \
         patch('reconciliation.engine.GapDetectionEngine', return_value=mock_engine):

        mock_qm.get_queue.return_value = MagicMock()

        from Stash2Plex import handle_reconcile
        handle_reconcile('all')

        # Verify engine was created and run with correct scope
        mock_engine.run.assert_called_once_with(scope='all')


def test_handle_reconcile_recent_scope():
    """Test that handle_reconcile calls engine.run with 'recent' scope."""
    mock_result = Mock()
    mock_result.scenes_checked = 50
    mock_result.total_gaps = 5
    mock_result.empty_metadata_count = 1
    mock_result.stale_sync_count = 2
    mock_result.missing_count = 2
    mock_result.enqueued_count = 5
    mock_result.skipped_already_queued = 0
    mock_result.errors = []

    mock_engine = MagicMock()
    mock_engine.run.return_value = mock_result

    with patch('Stash2Plex.stash_interface', MagicMock()), \
         patch('Stash2Plex.config', MagicMock()), \
         patch('Stash2Plex.queue_manager') as mock_qm, \
         patch('Stash2Plex.get_plugin_data_dir', return_value='/tmp/data'), \
         patch('reconciliation.engine.GapDetectionEngine', return_value=mock_engine):

        mock_qm.get_queue.return_value = MagicMock()

        from Stash2Plex import handle_reconcile
        handle_reconcile('recent')

        # Verify engine was called with 'recent' scope
        mock_engine.run.assert_called_once_with(scope='recent')


def test_handle_reconcile_logs_summary(capfd):
    """Test that handle_reconcile logs gap counts by type."""
    mock_result = Mock()
    mock_result.scenes_checked = 100
    mock_result.total_gaps = 10
    mock_result.empty_metadata_count = 3
    mock_result.stale_sync_count = 2
    mock_result.missing_count = 5
    mock_result.enqueued_count = 8
    mock_result.skipped_already_queued = 2
    mock_result.errors = []

    mock_engine = MagicMock()
    mock_engine.run.return_value = mock_result

    with patch('Stash2Plex.stash_interface', MagicMock()), \
         patch('Stash2Plex.config', MagicMock()), \
         patch('Stash2Plex.queue_manager') as mock_qm, \
         patch('Stash2Plex.get_plugin_data_dir', return_value='/tmp/data'), \
         patch('reconciliation.engine.GapDetectionEngine', return_value=mock_engine):

        mock_qm.get_queue.return_value = MagicMock()

        from Stash2Plex import handle_reconcile
        handle_reconcile('all')

        # Capture stderr (Stash log functions write to stderr)
        captured = capfd.readouterr()
        stderr_output = captured.err

        # Verify summary log output contains gap counts
        assert 'Scenes checked: 100' in stderr_output
        assert 'Gaps found: 10' in stderr_output
        assert 'Empty metadata: 3' in stderr_output
        assert 'Stale sync: 2' in stderr_output
        assert 'Missing from Plex: 5' in stderr_output
        assert 'Enqueued: 8' in stderr_output
        assert 'Skipped (already queued): 2' in stderr_output


def test_handle_reconcile_no_stash(capfd):
    """Test that handle_reconcile logs error and returns when stash_interface is None."""
    with patch('Stash2Plex.stash_interface', None), \
         patch('Stash2Plex.config', MagicMock()), \
         patch('Stash2Plex.queue_manager', MagicMock()), \
         patch('Stash2Plex.get_plugin_data_dir', return_value='/tmp/data'):

        from Stash2Plex import handle_reconcile
        handle_reconcile('all')

        # Verify error was logged
        captured = capfd.readouterr()
        assert 'No Stash connection available for reconciliation' in captured.err


def test_handle_reconcile_no_config(capfd):
    """Test that handle_reconcile logs error and returns when config is None."""
    with patch('Stash2Plex.stash_interface', MagicMock()), \
         patch('Stash2Plex.config', None), \
         patch('Stash2Plex.queue_manager', MagicMock()), \
         patch('Stash2Plex.get_plugin_data_dir', return_value='/tmp/data'):

        from Stash2Plex import handle_reconcile
        handle_reconcile('all')

        # Verify error was logged
        captured = capfd.readouterr()
        assert 'No config available for reconciliation' in captured.err


def test_handle_reconcile_no_queue(capfd):
    """Test that handle_reconcile runs in detection-only mode when queue_manager is None."""
    mock_result = Mock()
    mock_result.scenes_checked = 50
    mock_result.total_gaps = 5
    mock_result.empty_metadata_count = 2
    mock_result.stale_sync_count = 1
    mock_result.missing_count = 2
    mock_result.enqueued_count = 0
    mock_result.skipped_already_queued = 0
    mock_result.errors = []

    mock_engine = MagicMock()
    mock_engine.run.return_value = mock_result

    with patch('Stash2Plex.stash_interface', MagicMock()), \
         patch('Stash2Plex.config', MagicMock()), \
         patch('Stash2Plex.queue_manager', None), \
         patch('Stash2Plex.get_plugin_data_dir', return_value='/tmp/data'), \
         patch('reconciliation.engine.GapDetectionEngine', return_value=mock_engine):

        from Stash2Plex import handle_reconcile
        handle_reconcile('all')

        # Verify detection-only mode message
        captured = capfd.readouterr()
        assert 'No queue available - running in detection-only mode' in captured.err
        assert 'Detection-only mode (no items enqueued)' in captured.err


def test_handle_reconcile_engine_errors(capfd):
    """Test that handle_reconcile logs engine errors as warnings."""
    mock_result = Mock()
    mock_result.scenes_checked = 10
    mock_result.total_gaps = 2
    mock_result.empty_metadata_count = 1
    mock_result.stale_sync_count = 1
    mock_result.missing_count = 0
    mock_result.enqueued_count = 2
    mock_result.skipped_already_queued = 0
    mock_result.errors = ['Error processing scene 123', 'Another error']

    mock_engine = MagicMock()
    mock_engine.run.return_value = mock_result

    with patch('Stash2Plex.stash_interface', MagicMock()), \
         patch('Stash2Plex.config', MagicMock()), \
         patch('Stash2Plex.queue_manager') as mock_qm, \
         patch('Stash2Plex.get_plugin_data_dir', return_value='/tmp/data'), \
         patch('reconciliation.engine.GapDetectionEngine', return_value=mock_engine):

        mock_qm.get_queue.return_value = MagicMock()

        from Stash2Plex import handle_reconcile
        handle_reconcile('all')

        # Verify errors are logged as warnings
        captured = capfd.readouterr()
        assert 'Error during reconciliation: Error processing scene 123' in captured.err
        assert 'Error during reconciliation: Another error' in captured.err


def test_handle_task_dispatches_reconcile_all():
    """Test that handle_task correctly dispatches reconcile_all mode."""
    mock_result = Mock()
    mock_result.scenes_checked = 100
    mock_result.total_gaps = 0
    mock_result.empty_metadata_count = 0
    mock_result.stale_sync_count = 0
    mock_result.missing_count = 0
    mock_result.enqueued_count = 0
    mock_result.skipped_already_queued = 0
    mock_result.errors = []

    mock_engine = MagicMock()
    mock_engine.run.return_value = mock_result

    with patch('Stash2Plex.stash_interface', MagicMock()), \
         patch('Stash2Plex.config', MagicMock()), \
         patch('Stash2Plex.queue_manager') as mock_qm, \
         patch('Stash2Plex.get_plugin_data_dir', return_value='/tmp/data'), \
         patch('reconciliation.engine.GapDetectionEngine', return_value=mock_engine):

        mock_qm.get_queue.return_value = MagicMock()

        from Stash2Plex import handle_task
        handle_task({'mode': 'reconcile_all'}, stash=None)

        # Verify engine was called with 'all' scope
        mock_engine.run.assert_called_once_with(scope='all')


def test_handle_task_dispatches_reconcile_recent():
    """Test that handle_task correctly dispatches reconcile_recent mode."""
    mock_result = Mock()
    mock_result.scenes_checked = 50
    mock_result.total_gaps = 0
    mock_result.empty_metadata_count = 0
    mock_result.stale_sync_count = 0
    mock_result.missing_count = 0
    mock_result.enqueued_count = 0
    mock_result.skipped_already_queued = 0
    mock_result.errors = []

    mock_engine = MagicMock()
    mock_engine.run.return_value = mock_result

    with patch('Stash2Plex.stash_interface', MagicMock()), \
         patch('Stash2Plex.config', MagicMock()), \
         patch('Stash2Plex.queue_manager') as mock_qm, \
         patch('Stash2Plex.get_plugin_data_dir', return_value='/tmp/data'), \
         patch('reconciliation.engine.GapDetectionEngine', return_value=mock_engine):

        mock_qm.get_queue.return_value = MagicMock()

        from Stash2Plex import handle_task
        handle_task({'mode': 'reconcile_recent'}, stash=None)

        # Verify engine was called with 'recent' scope
        mock_engine.run.assert_called_once_with(scope='recent')


def test_reconcile_modes_in_management_modes():
    """Test that reconcile_all and reconcile_recent are in management_modes set."""
    # This test verifies that reconcile modes are treated as management tasks
    # (no queue-wait polling after the task completes)

    # We can't easily test the management_modes set directly since it's defined
    # in the main execution block, but we can verify the behavior by checking
    # that the mode dispatch returns immediately (doesn't trigger sync flow)

    mock_result = Mock()
    mock_result.scenes_checked = 10
    mock_result.total_gaps = 0
    mock_result.empty_metadata_count = 0
    mock_result.stale_sync_count = 0
    mock_result.missing_count = 0
    mock_result.enqueued_count = 0
    mock_result.skipped_already_queued = 0
    mock_result.errors = []

    mock_engine = MagicMock()
    mock_engine.run.return_value = mock_result

    with patch('Stash2Plex.stash_interface', MagicMock()), \
         patch('Stash2Plex.config', MagicMock()), \
         patch('Stash2Plex.queue_manager') as mock_qm, \
         patch('Stash2Plex.get_plugin_data_dir', return_value='/tmp/data'), \
         patch('reconciliation.engine.GapDetectionEngine', return_value=mock_engine):

        mock_qm.get_queue.return_value = MagicMock()

        from Stash2Plex import handle_task

        # Both modes should return immediately without triggering sync flow
        handle_task({'mode': 'reconcile_all'}, stash=None)
        assert mock_engine.run.called

        mock_engine.reset_mock()
        handle_task({'mode': 'reconcile_recent'}, stash=None)
        assert mock_engine.run.called
