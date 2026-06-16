"""Small cross-platform file locking helpers.

Uses fcntl on POSIX and msvcrt on Windows. If neither backend exists, locking
becomes a no-op so the plugin can still run in constrained Python builds.
"""

from __future__ import annotations

import os
from typing import TextIO

try:
    import fcntl as _fcntl
except ModuleNotFoundError:  # pragma: no cover - exercised via subprocess test
    _fcntl = None

try:
    import msvcrt as _msvcrt
except ModuleNotFoundError:  # pragma: no cover - non-Windows path
    _msvcrt = None


def _prepare_windows_lock_byte(file_obj: TextIO) -> None:
    """Ensure there is one byte available for msvcrt byte-range locking."""
    try:
        current = file_obj.tell()
        file_obj.seek(0, os.SEEK_END)
        if file_obj.tell() == 0 and file_obj.writable():
            file_obj.write("\0")
            file_obj.flush()
        file_obj.seek(0)
    except OSError:
        pass
    finally:
        try:
            file_obj.seek(0)
        except OSError:
            pass


def lock_exclusive(file_obj: TextIO, blocking: bool = True) -> bool:
    """Acquire an exclusive file lock.

    Returns False for non-blocking calls when another process owns the lock.
    """
    if _fcntl is not None:
        flags = _fcntl.LOCK_EX
        if not blocking:
            flags |= _fcntl.LOCK_NB
        try:
            _fcntl.flock(file_obj.fileno(), flags)
            return True
        except BlockingIOError:
            return False

    if _msvcrt is not None:
        _prepare_windows_lock_byte(file_obj)
        mode = _msvcrt.LK_LOCK if blocking else _msvcrt.LK_NBLCK
        try:
            _msvcrt.locking(file_obj.fileno(), mode, 1)
            return True
        except OSError:
            return False

    return True


def lock_shared(file_obj: TextIO) -> bool:
    """Acquire a shared read lock when the platform supports one."""
    if _fcntl is not None:
        _fcntl.flock(file_obj.fileno(), _fcntl.LOCK_SH)
    return True


def unlock(file_obj: TextIO) -> None:
    """Release a lock previously acquired with this module."""
    if _fcntl is not None:
        try:
            _fcntl.flock(file_obj.fileno(), _fcntl.LOCK_UN)
        except OSError:
            pass
        return

    if _msvcrt is not None:
        try:
            file_obj.seek(0)
            _msvcrt.locking(file_obj.fileno(), _msvcrt.LK_UNLCK, 1)
        except OSError:
            pass


__all__ = ["lock_exclusive", "lock_shared", "unlock"]
