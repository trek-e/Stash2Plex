"""
Tests for plex.timing module.

Verifies timing decorator and context manager work correctly
and log at appropriate levels based on operation duration.
"""

import logging
import time

import pytest

from plex.timing import timed, OperationTimer, log_timing


class TestTimedDecorator:
    """Tests for the @timed decorator."""

    def test_timed_returns_function_result(self):
        """Decorated function returns its result unchanged."""
        @timed
        def add(a, b):
            return a + b

        result = add(2, 3)
        assert result == 5

    def test_timed_preserves_function_name(self):
        """Decorated function preserves its __name__ attribute."""
        @timed
        def my_function():
            pass

        assert my_function.__name__ == "my_function"

    def test_timed_logs_at_debug_for_fast_operations(self, caplog):
        """Fast operations (<1s) log at DEBUG level."""
        @timed
        def fast_function():
            return "done"

        with caplog.at_level(logging.DEBUG, logger="Stash2Plex.plex.timing"):
            result = fast_function()

        assert result == "done"
        assert len(caplog.records) == 1
        assert caplog.records[0].levelno == logging.DEBUG
        assert "fast_function took" in caplog.records[0].message
        assert "s" in caplog.records[0].message

    def test_timed_logs_at_info_for_slow_operations(self, caplog):
        """Slow operations (>=1s) log at INFO level."""
        @timed
        def slow_function():
            time.sleep(1.0)
            return "done"

        with caplog.at_level(logging.DEBUG, logger="Stash2Plex.plex.timing"):
            result = slow_function()

        assert result == "done"
        assert len(caplog.records) == 1
        assert caplog.records[0].levelno == logging.INFO
        assert "slow_function took" in caplog.records[0].message

    def test_timed_handles_exception(self, caplog):
        """Decorator logs timing even when function raises."""
        @timed
        def error_function():
            raise ValueError("test error")

        with caplog.at_level(logging.DEBUG, logger="Stash2Plex.plex.timing"):
            with pytest.raises(ValueError, match="test error"):
                error_function()

        # Should still log timing
        assert len(caplog.records) == 1
        assert "error_function took" in caplog.records[0].message

    def test_timed_with_args_and_kwargs(self):
        """Decorator works with positional and keyword arguments."""
        @timed
        def func_with_args(a, b, c=None, d=None):
            return (a, b, c, d)

        result = func_with_args(1, 2, c=3, d=4)
        assert result == (1, 2, 3, 4)


class TestOperationTimer:
    """Tests for the OperationTimer context manager."""

    def test_timer_measures_elapsed_time(self):
        """Timer accurately measures elapsed time."""
        with OperationTimer("test operation") as timer:
            time.sleep(0.1)

        assert timer.elapsed >= 0.1
        assert timer.elapsed < 0.2

    def test_timer_logs_at_debug_for_fast_operations(self, caplog):
        """Fast operations (<1s) log at DEBUG level."""
        with caplog.at_level(logging.DEBUG, logger="Stash2Plex.plex.timing"):
            with OperationTimer("quick task"):
                pass

        assert len(caplog.records) == 1
        assert caplog.records[0].levelno == logging.DEBUG
        assert "quick task took" in caplog.records[0].message

    def test_timer_logs_at_info_for_slow_operations(self, caplog):
        """Slow operations (>=1s) log at INFO level."""
        with caplog.at_level(logging.DEBUG, logger="Stash2Plex.plex.timing"):
            with OperationTimer("slow task"):
                time.sleep(1.0)

        assert len(caplog.records) == 1
        assert caplog.records[0].levelno == logging.INFO
        assert "slow task took" in caplog.records[0].message

    def test_timer_stores_operation_name(self):
        """Timer stores operation name for reference."""
        timer = OperationTimer("my operation")
        assert timer.operation_name == "my operation"

    def test_timer_elapsed_available_after_exit(self):
        """Elapsed time is available after context exit."""
        timer = OperationTimer("test")
        with timer:
            time.sleep(0.05)

        # Access elapsed after the context
        assert timer.elapsed >= 0.05

    def test_timer_logs_on_exception(self, caplog):
        """Timer logs timing even when block raises."""
        with caplog.at_level(logging.DEBUG, logger="Stash2Plex.plex.timing"):
            with pytest.raises(ValueError):
                with OperationTimer("error task"):
                    raise ValueError("test")

        # Should still log timing
        assert len(caplog.records) == 1
        assert "error task took" in caplog.records[0].message


class TestLogTiming:
    """Tests for the log_timing function."""

    def test_log_timing_writes_to_stderr(self, capsys):
        """log_timing writes message to stderr with Stash format."""
        log_timing("Test timing message")

        captured = capsys.readouterr()
        assert "[Stash2Plex Timing]" in captured.err
        assert "Test timing message" in captured.err

    def test_log_timing_uses_debug_prefix(self, capsys):
        """log_timing uses Stash debug level prefix."""
        log_timing("Search completed in 0.5s")

        captured = capsys.readouterr()
        # Stash debug level prefix is \x01d\x02
        assert "\x01d\x02" in captured.err


class TestTimingIntegration:
    """Integration tests combining timing utilities."""

    def test_nested_timing(self, caplog):
        """Nested timers work correctly."""
        with caplog.at_level(logging.DEBUG, logger="Stash2Plex.plex.timing"):
            with OperationTimer("outer"):
                with OperationTimer("inner"):
                    time.sleep(0.01)

        # Should have two log messages
        assert len(caplog.records) == 2
        messages = [r.message for r in caplog.records]
        assert any("inner took" in m for m in messages)
        assert any("outer took" in m for m in messages)

    def test_timed_decorator_with_timer_context(self, caplog):
        """Decorator and context manager can be used together."""
        @timed
        def outer_function():
            with OperationTimer("inner block"):
                time.sleep(0.01)
            return "done"

        with caplog.at_level(logging.DEBUG, logger="Stash2Plex.plex.timing"):
            result = outer_function()

        assert result == "done"
        # Should have two log messages
        assert len(caplog.records) == 2
