"""Process concurrency guard for Stash2Plex.

Bounds the number of concurrent Stash2Plex.py processes to prevent spawn
storms during bulk imports. Uses a directory of per-slot fcntl lockfiles so
slots are automatically reclaimed on process exit or crash with no cleanup.

Usage (entry point):

    from sync_queue.process_guard import ProcessGuard

    guard = ProcessGuard(data_dir)
    if not guard.acquire():
        # At capacity — exit immediately before any expensive init
        sys.exit(0)
    # ... run plugin ...
    # guard.release() is called automatically on GC / explicit call

Usage (drain trigger check):

    from sync_queue.process_guard import ProcessGuard

    guard = ProcessGuard(data_dir)
    count = guard.live_count()
    if count >= guard.max_processes:
        # Already at capacity — skip spawning another drainer
        pass

Environment variables:

    STASH2PLEX_MAX_CONCURRENT_PROCESSES  integer, default 5
"""

import fcntl
import os
from typing import Optional


_DEFAULT_MAX = 5
_SLOT_PREFIX = 'proc_slot.'


def _max_processes_from_env() -> int:
    try:
        v = os.getenv('STASH2PLEX_MAX_CONCURRENT_PROCESSES', '')
        if v.strip():
            n = int(v.strip())
            return max(1, n)
    except (ValueError, AttributeError):
        pass
    return _DEFAULT_MAX


class ProcessGuard:
    """Slot-based process concurrency limiter backed by fcntl lockfiles.

    Each slot is a file ``<slots_dir>/proc_slot.<N>`` (N = 0 .. max-1).
    Acquiring a slot takes an exclusive non-blocking flock on one of these
    files. The kernel releases the lock automatically when the file descriptor
    is closed or the process exits (including SIGKILL / OOM-kill).

    Thread safety: acquire() / release() must be called from the main thread.
    This class is not designed for use across threads within a single process.
    """

    def __init__(
        self,
        data_dir: str,
        max_processes: Optional[int] = None,
    ):
        self.data_dir = data_dir
        self.max_processes = max_processes if max_processes is not None else _max_processes_from_env()
        self._slots_dir = os.path.join(data_dir, 'proc_slots')
        self._held_fd: Optional[object] = None  # open file object for held slot
        self._held_slot: Optional[int] = None

    def _ensure_dir(self) -> None:
        os.makedirs(self._slots_dir, exist_ok=True)

    def _slot_path(self, n: int) -> str:
        return os.path.join(self._slots_dir, f'{_SLOT_PREFIX}{n}')

    def acquire(self) -> bool:
        """Try to acquire a process slot.

        Returns True if a slot was acquired (caller may proceed).
        Returns False if all slots are occupied (caller should exit immediately).

        On success, the slot is held until release() is called or the process
        exits. Calling acquire() twice from the same process is undefined.
        """
        self._ensure_dir()
        for n in range(self.max_processes):
            path = self._slot_path(n)
            try:
                fd = open(path, 'w')
                fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                # Write PID for observability (best-effort)
                try:
                    fd.write(str(os.getpid()))
                    fd.flush()
                except OSError:
                    pass
                self._held_fd = fd
                self._held_slot = n
                return True
            except (BlockingIOError, OSError):
                # Slot occupied — try next
                try:
                    fd.close()
                except Exception:
                    pass
                continue
        return False

    def release(self) -> None:
        """Release the held slot, if any."""
        if self._held_fd is None:
            return
        try:
            fcntl.flock(self._held_fd.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            self._held_fd.close()
        except OSError:
            pass
        self._held_fd = None
        self._held_slot = None

    def live_count(self) -> int:
        """Return the number of slots currently held by live processes.

        Uses non-blocking trylock on each slot file. A slot is live if its
        file is locked by another process. This is cheap (no subprocess) and
        accurate because the kernel tracks fcntl locks per-process.
        """
        try:
            self._ensure_dir()
        except OSError:
            return 0

        count = 0
        for n in range(self.max_processes):
            path = self._slot_path(n)
            try:
                with open(path, 'r') as fd:
                    try:
                        fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        # Got the lock — slot is free
                        fcntl.flock(fd.fileno(), fcntl.LOCK_UN)
                    except (BlockingIOError, OSError):
                        # Could not lock — slot is held by another process
                        count += 1
            except FileNotFoundError:
                # Slot file doesn't exist yet — definitely free
                pass
            except OSError:
                # Other I/O error; treat as free to avoid false positives
                pass
        return count

    def __del__(self):
        self.release()


__all__ = ['ProcessGuard']
