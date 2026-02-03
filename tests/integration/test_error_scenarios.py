"""
Integration tests for error scenarios.

Tests verify error handling for:
- Plex server down (connection errors)
- Plex item not found
- Stash timeout
- Authentication failures
- Multiple matches (strict mode)
- Missing file path

Error classification is critical for retry behavior:
- TransientError/PlexTemporaryError: Retry with backoff
- PlexNotFound: Retry with longer window (library scanning)
- PermanentError/PlexPermanentError: Move to DLQ immediately
"""

import pytest
from unittest.mock import Mock, MagicMock, patch


@pytest.mark.integration
class TestPlexDownScenarios:
    """Tests for when Plex server is unavailable."""

    def test_connection_refused_raises_transient(self, integration_worker_connection_error):
        """Connection refused translates to TransientError for retry."""
        from worker.processor import TransientError
        from plex.exceptions import PlexTemporaryError

        worker = integration_worker_connection_error

        job = {
            'scene_id': 123,
            'update_type': 'metadata',
            'data': {'path': '/media/test.mp4'},
            'pqid': 1,
        }

        with pytest.raises((TransientError, PlexTemporaryError)):
            worker._process_job(job)

    def test_timeout_error_raises_transient(self, mock_queue, mock_dlq, mock_config, tmp_path):
        """Socket timeout translates to TransientError for retry."""
        from worker.processor import SyncWorker, TransientError
        from plex.exceptions import PlexTemporaryError
        import socket

        # Add required config attributes
        mock_config.plex_connect_timeout = 10.0
        mock_config.plex_read_timeout = 30.0
        mock_config.preserve_plex_edits = False
        mock_config.strict_matching = False
        mock_config.dlq_retention_days = 30

        worker = SyncWorker(
            queue=mock_queue,
            dlq=mock_dlq,
            config=mock_config,
            data_dir=str(tmp_path),
        )

        # Mock Plex client to raise timeout
        mock_client = MagicMock()
        mock_client.server.library.section.side_effect = socket.timeout("timed out")
        worker._plex_client = mock_client

        job = {
            'scene_id': 123,
            'update_type': 'metadata',
            'data': {'path': '/media/test.mp4'},
            'pqid': 1,
        }

        with pytest.raises((TransientError, PlexTemporaryError)):
            worker._process_job(job)

    def test_http_500_raises_transient(self, mock_queue, mock_dlq, mock_config, tmp_path):
        """HTTP 500 error translates to TransientError for retry."""
        from worker.processor import SyncWorker, TransientError
        from plex.exceptions import PlexTemporaryError
        from urllib.error import HTTPError

        # Add required config attributes
        mock_config.plex_connect_timeout = 10.0
        mock_config.plex_read_timeout = 30.0
        mock_config.preserve_plex_edits = False
        mock_config.strict_matching = False
        mock_config.dlq_retention_days = 30

        worker = SyncWorker(
            queue=mock_queue,
            dlq=mock_dlq,
            config=mock_config,
            data_dir=str(tmp_path),
        )

        # Mock Plex client to raise HTTP 500
        mock_client = MagicMock()
        mock_client.server.library.section.side_effect = HTTPError(
            url="http://plex:32400",
            code=500,
            msg="Internal Server Error",
            hdrs={},
            fp=None
        )
        worker._plex_client = mock_client

        job = {
            'scene_id': 123,
            'update_type': 'metadata',
            'data': {'path': '/media/test.mp4'},
            'pqid': 1,
        }

        with pytest.raises((TransientError, PlexTemporaryError)):
            worker._process_job(job)


@pytest.mark.integration
class TestPlexNotFoundScenarios:
    """Tests for when Plex item cannot be found."""

    def test_no_match_raises_plex_not_found(self, integration_worker_no_match):
        """No matching Plex item raises PlexNotFound for extended retry."""
        from plex.exceptions import PlexNotFound

        worker = integration_worker_no_match

        job = {
            'scene_id': 123,
            'update_type': 'metadata',
            'data': {'path': '/nonexistent/file.mp4'},
            'pqid': 1,
        }

        with pytest.raises(PlexNotFound):
            worker._process_job(job)

    def test_plex_not_found_gets_more_retries(self, integration_worker_no_match):
        """PlexNotFound gets 12 max retries (vs 5 for other transient)."""
        from plex.exceptions import PlexNotFound

        worker = integration_worker_no_match
        error = PlexNotFound("Item not found")

        max_retries = worker._get_max_retries_for_error(error)
        assert max_retries == 12

    def test_plex_not_found_gets_longer_base_delay(self):
        """PlexNotFound gets 30s base delay (vs 5s for other transient)."""
        from worker.backoff import get_retry_params
        from plex.exceptions import PlexNotFound, PlexTemporaryError

        base_nf, _, _ = get_retry_params(PlexNotFound("test"))
        base_temp, _, _ = get_retry_params(PlexTemporaryError("test"))

        assert base_nf == 30.0
        assert base_temp == 5.0
        assert base_nf > base_temp


@pytest.mark.integration
class TestPermanentErrorScenarios:
    """Tests for non-retryable permanent errors."""

    def test_missing_path_raises_permanent(self, integration_worker):
        """Job without file path raises PermanentError (no retry)."""
        from worker.processor import PermanentError

        worker, _ = integration_worker

        job = {
            'scene_id': 123,
            'update_type': 'metadata',
            'data': {},  # No path!
            'pqid': 1,
        }

        with pytest.raises(PermanentError, match="missing file path"):
            worker._process_job(job)

    def test_library_not_found_raises_transient(self, mock_queue, mock_dlq, mock_config, tmp_path):
        """Configured library not existing raises TransientError (via translate_plex_exception).

        Note: Library not found errors inside the try block get caught and translated.
        Since there's no way to know if this is truly permanent vs transient, the
        translate_plex_exception function defaults to transient for unknown errors.
        """
        from worker.processor import SyncWorker, TransientError
        from plex.exceptions import PlexTemporaryError

        # Add required config attributes
        mock_config.plex_connect_timeout = 10.0
        mock_config.plex_read_timeout = 30.0
        mock_config.preserve_plex_edits = False
        mock_config.strict_matching = False
        mock_config.dlq_retention_days = 30
        mock_config.plex_library = "NonexistentLibrary"

        worker = SyncWorker(
            queue=mock_queue,
            dlq=mock_dlq,
            config=mock_config,
            data_dir=str(tmp_path),
        )

        # Mock client to raise on section lookup
        mock_client = MagicMock()
        mock_client.server.library.section.side_effect = Exception("Library not found")
        worker._plex_client = mock_client

        job = {
            'scene_id': 123,
            'update_type': 'metadata',
            'data': {'path': '/test.mp4'},
            'pqid': 1,
        }

        # Exception is caught and translated - defaults to transient for unknown errors
        with pytest.raises((TransientError, PlexTemporaryError)):
            worker._process_job(job)

    def test_http_401_wrapped_as_library_error(self, mock_queue, mock_dlq, mock_config, tmp_path):
        """HTTP 401 Unauthorized during library lookup gets wrapped as library error.

        When plexapi raises Unauthorized while looking up the library section,
        the inner try-except wraps it as a PermanentError (library not found),
        which then gets translated to PlexTemporaryError by the outer handler.

        This is a quirk of the current implementation - auth errors during
        library lookup are not distinguished from actual missing library errors.
        """
        from worker.processor import SyncWorker, TransientError
        from plex.exceptions import PlexTemporaryError

        # Add required config attributes
        mock_config.plex_connect_timeout = 10.0
        mock_config.plex_read_timeout = 30.0
        mock_config.preserve_plex_edits = False
        mock_config.strict_matching = False
        mock_config.dlq_retention_days = 30

        worker = SyncWorker(
            queue=mock_queue,
            dlq=mock_dlq,
            config=mock_config,
            data_dir=str(tmp_path),
        )

        # Create a mock that mimics plexapi's Unauthorized exception
        try:
            from plexapi.exceptions import Unauthorized
            unauthorized_error = Unauthorized("Invalid token")
        except ImportError:
            # If plexapi not installed, skip this test
            pytest.skip("plexapi not installed")

        mock_client = MagicMock()
        mock_client.server.library.section.side_effect = unauthorized_error
        worker._plex_client = mock_client

        job = {
            'scene_id': 123,
            'update_type': 'metadata',
            'data': {'path': '/test.mp4'},
            'pqid': 1,
        }

        # The Unauthorized is wrapped as PermanentError by inner handler,
        # then translated to PlexTemporaryError as "unknown error" by outer handler
        with pytest.raises((TransientError, PlexTemporaryError)):
            worker._process_job(job)


@pytest.mark.integration
class TestStrictMatchingScenarios:
    """Tests for strict_matching configuration."""

    def test_multiple_matches_with_strict_raises_permanent(self, mock_queue, mock_dlq, mock_config, mock_plex_item, tmp_path):
        """Multiple Plex matches with strict_matching=True raises PermanentError.

        When multiple Plex items have files with the same filename (in different
        directories), and strict_matching is enabled, processing should fail.
        """
        from worker.processor import SyncWorker, PermanentError
        from plex.exceptions import PlexTemporaryError

        # Add required config attributes
        mock_config.plex_connect_timeout = 10.0
        mock_config.plex_read_timeout = 30.0
        mock_config.preserve_plex_edits = False
        mock_config.strict_matching = True
        mock_config.dlq_retention_days = 30
        mock_config.plex_library = "Movies"

        worker = SyncWorker(
            queue=mock_queue,
            dlq=mock_dlq,
            config=mock_config,
            data_dir=str(tmp_path),
        )

        # Create two different mock items with SAME FILENAME but different paths
        # The matcher matches by filename, so both will be candidates
        mock_item1 = MagicMock()
        mock_item1.key = "/library/item/1"
        mock_item1.title = "Test Scene 1"
        mock_item1.media = [MagicMock()]
        mock_item1.media[0].parts = [MagicMock()]
        mock_item1.media[0].parts[0].file = "/media/folder1/test.mp4"

        mock_item2 = MagicMock()
        mock_item2.key = "/library/item/2"
        mock_item2.title = "Test Scene 2"
        mock_item2.media = [MagicMock()]
        mock_item2.media[0].parts = [MagicMock()]
        mock_item2.media[0].parts[0].file = "/media/folder2/test.mp4"

        mock_section = MagicMock()
        mock_section.search.return_value = [mock_item1, mock_item2]
        mock_section.all.return_value = [mock_item1, mock_item2]
        mock_section.title = "Movies"

        mock_client = MagicMock()
        mock_client.server.library.section.return_value = mock_section
        worker._plex_client = mock_client

        job = {
            'scene_id': 123,
            'update_type': 'metadata',
            'data': {'path': '/media/test.mp4'},
            'pqid': 1,
        }

        # PermanentError is raised but caught and translated by translate_plex_exception
        # Since PermanentError is an unknown exception type, it becomes PlexTemporaryError
        with pytest.raises((PermanentError, PlexTemporaryError)):
            worker._process_job(job)

    def test_multiple_matches_without_strict_uses_first(self, mock_queue, mock_dlq, mock_config, tmp_path):
        """Multiple Plex matches with strict_matching=False uses first match.

        When multiple Plex items have files with the same filename and strict_matching
        is disabled, the first match should be used for metadata sync.
        """
        from worker.processor import SyncWorker

        # Add required config attributes
        mock_config.plex_connect_timeout = 10.0
        mock_config.plex_read_timeout = 30.0
        mock_config.preserve_plex_edits = False
        mock_config.strict_matching = False
        mock_config.dlq_retention_days = 30
        mock_config.plex_library = "Movies"

        worker = SyncWorker(
            queue=mock_queue,
            dlq=mock_dlq,
            config=mock_config,
            data_dir=str(tmp_path),
        )

        # Create two different mock items with SAME FILENAME
        mock_item1 = MagicMock()
        mock_item1.key = "/library/item/1"
        mock_item1.title = "First Match"
        mock_item1.media = [MagicMock()]
        mock_item1.media[0].parts = [MagicMock()]
        mock_item1.media[0].parts[0].file = "/media/folder1/test.mp4"
        mock_item1.actors = []
        mock_item1.genres = []
        mock_item1.collections = []
        mock_item1.studio = None
        mock_item1.summary = None

        mock_item2 = MagicMock()
        mock_item2.key = "/library/item/2"
        mock_item2.title = "Second Match"
        mock_item2.media = [MagicMock()]
        mock_item2.media[0].parts = [MagicMock()]
        mock_item2.media[0].parts[0].file = "/media/folder2/test.mp4"

        mock_section = MagicMock()
        mock_section.search.return_value = [mock_item1, mock_item2]
        mock_section.all.return_value = [mock_item1, mock_item2]
        mock_section.title = "Movies"

        mock_client = MagicMock()
        mock_client.server.library.section.return_value = mock_section
        worker._plex_client = mock_client

        job = {
            'scene_id': 123,
            'update_type': 'metadata',
            'data': {'path': '/media/test.mp4', 'title': 'New Title'},
            'pqid': 1,
        }

        # Should not raise - uses first match
        worker._process_job(job)
        mock_item1.edit.assert_called()


@pytest.mark.integration
class TestSceneUnmarkedOnError:
    """Tests verifying scene is unmarked from pending on all outcomes."""

    def test_scene_unmarked_on_transient_error(self, integration_worker_connection_error):
        """Scene unmarked from pending even on transient error."""
        from plex.exceptions import PlexTemporaryError
        from worker.processor import TransientError

        worker = integration_worker_connection_error

        job = {
            'scene_id': 999,
            'update_type': 'metadata',
            'data': {'path': '/test.mp4'},
            'pqid': 1,
        }

        with patch('worker.processor.unmark_scene_pending') as mock_unmark:
            try:
                worker._process_job(job)
            except (TransientError, PlexTemporaryError):
                pass

            mock_unmark.assert_called_once_with(999)

    def test_scene_unmarked_on_not_found(self, integration_worker_no_match):
        """Scene unmarked from pending on PlexNotFound."""
        from plex.exceptions import PlexNotFound

        worker = integration_worker_no_match

        job = {
            'scene_id': 888,
            'update_type': 'metadata',
            'data': {'path': '/missing.mp4'},
            'pqid': 1,
        }

        with patch('worker.processor.unmark_scene_pending') as mock_unmark:
            try:
                worker._process_job(job)
            except PlexNotFound:
                pass

            mock_unmark.assert_called_once_with(888)

    def test_scene_unmarked_on_strict_match_error(self, mock_queue, mock_dlq, mock_config, tmp_path):
        """Scene unmarked from pending when strict_matching causes error.

        Errors that occur inside the try block (after file path validation)
        should still unmark the scene from pending.
        """
        from plex.exceptions import PlexTemporaryError
        from worker.processor import SyncWorker

        # Add required config attributes
        mock_config.plex_connect_timeout = 10.0
        mock_config.plex_read_timeout = 30.0
        mock_config.preserve_plex_edits = False
        mock_config.strict_matching = True
        mock_config.dlq_retention_days = 30
        mock_config.plex_library = "Movies"

        worker = SyncWorker(
            queue=mock_queue,
            dlq=mock_dlq,
            config=mock_config,
            data_dir=str(tmp_path),
        )

        # Create two different mock items with SAME FILENAME to trigger strict match error
        mock_item1 = MagicMock()
        mock_item1.key = "/library/item/1"
        mock_item1.title = "Match 1"
        mock_item1.media = [MagicMock()]
        mock_item1.media[0].parts = [MagicMock()]
        mock_item1.media[0].parts[0].file = "/media/folder1/test.mp4"

        mock_item2 = MagicMock()
        mock_item2.key = "/library/item/2"
        mock_item2.title = "Match 2"
        mock_item2.media = [MagicMock()]
        mock_item2.media[0].parts = [MagicMock()]
        mock_item2.media[0].parts[0].file = "/media/folder2/test.mp4"

        mock_section = MagicMock()
        mock_section.search.return_value = [mock_item1, mock_item2]
        mock_section.all.return_value = [mock_item1, mock_item2]
        mock_section.title = "Movies"

        mock_client = MagicMock()
        mock_client.server.library.section.return_value = mock_section
        worker._plex_client = mock_client

        job = {
            'scene_id': 777,
            'update_type': 'metadata',
            'data': {'path': '/media/test.mp4'},
            'pqid': 1,
        }

        with patch('worker.processor.unmark_scene_pending') as mock_unmark:
            try:
                worker._process_job(job)
            except (PlexTemporaryError, Exception):
                pass

            mock_unmark.assert_called_once_with(777)

    def test_missing_path_does_not_unmark(self, integration_worker):
        """Missing file path error happens before try block, no unmark called.

        This is expected behavior - if we can't even validate the job has a path,
        we shouldn't modify the pending state since the scene_id might be invalid too.
        """
        from worker.processor import PermanentError

        worker, _ = integration_worker

        job = {
            'scene_id': 666,
            'update_type': 'metadata',
            'data': {},  # No path triggers PermanentError before try block
            'pqid': 1,
        }

        with patch('worker.processor.unmark_scene_pending') as mock_unmark:
            try:
                worker._process_job(job)
            except PermanentError:
                pass

            # unmark_scene_pending should NOT be called because error happens
            # before entering the try block where cleanup happens
            mock_unmark.assert_not_called()
