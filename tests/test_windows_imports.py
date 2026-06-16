"""Regression tests for Windows-compatible imports."""

import subprocess
import sys


def test_runtime_modules_import_without_fcntl():
    """Modules imported during plugin startup must not require POSIX fcntl."""
    code = """
import builtins

real_import = builtins.__import__

def fake_import(name, *args, **kwargs):
    if name == "fcntl":
        raise ModuleNotFoundError("No module named 'fcntl'")
    return real_import(name, *args, **kwargs)

builtins.__import__ = fake_import

import worker.circuit_breaker
import sync_queue.process_guard
import reconciliation.scheduler
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
