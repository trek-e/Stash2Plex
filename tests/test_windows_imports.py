"""Regression tests for Windows-compatible imports."""

import ast
from pathlib import Path
import subprocess
import sys

POSIX_ONLY_MODULES = {"fcntl", "grp", "pwd", "termios", "tty", "resource"}
REPO_ROOT = Path(__file__).resolve().parents[1]
DIRECT_IMPORT_ALLOWLIST = {
    Path("shared/file_lock.py"),
}


def test_runtime_modules_import_without_posix_only_modules():
    """Modules imported during plugin startup must not require POSIX-only modules."""
    blocked_modules = repr(sorted(POSIX_ONLY_MODULES))
    code = f"""
import builtins

real_import = builtins.__import__
posix_only = set({blocked_modules})

def fake_import(name, *args, **kwargs):
    if name in posix_only:
        raise ModuleNotFoundError("No module named %r" % name)
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


def test_no_direct_imports_of_posix_only_modules():
    """Code should route POSIX-only modules through compatibility helpers."""
    violations = []

    for path in REPO_ROOT.rglob("*.py"):
        relative = path.relative_to(REPO_ROOT)
        if any(part in {".git", ".venv", "__pycache__", "site", "coverage_html"} for part in relative.parts):
            continue
        if relative in DIRECT_IMPORT_ALLOWLIST:
            continue

        tree = ast.parse(path.read_text(), filename=str(relative))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root_name = alias.name.split(".", 1)[0]
                    if root_name in POSIX_ONLY_MODULES:
                        violations.append(f"{relative}:{node.lineno}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                root_name = node.module.split(".", 1)[0]
                if root_name in POSIX_ONLY_MODULES:
                    violations.append(f"{relative}:{node.lineno}: from {node.module} import ...")

    assert violations == []
