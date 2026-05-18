"""Queue drain trigger for hook-captured work.

Stash hook invocations are short-lived, so a hook cannot rely on its own
process staying alive to drain deferred queue work. This module owns the
fire-and-forget process kickoff used after hook enqueue attempts.
"""

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Optional

try:
    from sync_queue.process_guard import ProcessGuard as ProcessGuard
except ImportError:  # pragma: no cover
    ProcessGuard = None  # type: ignore[assignment,misc]


_DISABLED_VALUES = {'0', 'false', 'no', 'off'}


@dataclass(frozen=True)
class QueueDrainTriggerResult:
    """Outcome of requesting a queue drain."""

    triggered: bool
    reason: Optional[str] = None
    pid: Optional[int] = None


class QueueDrainTrigger:
    """Starts a one-shot process_queue task for queued hook work."""

    def __init__(
        self,
        plugin_dir: str,
        data_dir: str,
        python_executable: str = sys.executable,
        cooldown_secs: Optional[float] = None,
        enabled: Optional[bool] = None,
        max_processes: Optional[int] = None,
    ):
        self.plugin_dir = plugin_dir
        self.data_dir = data_dir
        self.python_executable = python_executable
        self.cooldown_secs = cooldown_secs
        self.enabled = enabled
        self.max_processes = max_processes  # None means read from env / default

    def trigger(self, server_connection: Optional[dict] = None) -> QueueDrainTriggerResult:
        """Request an asynchronous process_queue drain.

        The cooldown is a burst limiter. A skipped trigger is acceptable when
        another hook recently started a drainer; queued jobs persist until any
        process_queue run handles them.

        Additionally, the trigger is skipped when the process concurrency cap
        (STASH2PLEX_MAX_CONCURRENT_PROCESSES, default 5) is already reached.
        Spawning a drainer that would immediately be rejected by ProcessGuard
        wastes a full Python interpreter startup just to exit with slot=denied.
        """
        if not self._is_enabled():
            return QueueDrainTriggerResult(False, reason='disabled')

        cooldown = self._cooldown_secs()
        marker = os.path.join(self.data_dir, 'hook_autodrain.last')
        now = time.time()
        last = self._read_last_trigger(marker)
        if now - last < cooldown:
            return QueueDrainTriggerResult(False, reason='cooldown')

        # Check process concurrency cap before spawning.
        # If already at the cap, skip — the existing drainer(s) will handle the queue.
        try:
            if ProcessGuard is not None:
                guard = ProcessGuard(self.data_dir, max_processes=self.max_processes)
                live = guard.live_count()
                cap = guard.max_processes
                if live >= cap:
                    return QueueDrainTriggerResult(False, reason=f'at_capacity ({live}/{cap})')
        except Exception:
            # If the guard check fails (or ProcessGuard unavailable), allow spawn.
            # The guard inside the spawned process will still enforce the cap.
            pass

        payload = {
            'server_connection': server_connection or {},
            'args': {'mode': 'process_queue'},
        }
        payload_json = json.dumps(payload)
        log_path = self._log_path()
        self._rotate_log_if_needed(log_path)
        log_dir = os.path.dirname(log_path)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)

        with open(log_path, 'a', buffering=1) as log_file:
            log_file.write(
                f"{time.strftime('%Y-%m-%d %H:%M:%S')} "
                "starting process_queue hook autodrain\n"
            )
            proc = subprocess.Popen(
                [self.python_executable, os.path.join(self.plugin_dir, 'Stash2Plex.py')],
                stdin=subprocess.PIPE,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                text=True,
            )
            log_file.write(
                f"{time.strftime('%Y-%m-%d %H:%M:%S')} "
                f"started process_queue hook autodrain pid={proc.pid}\n"
            )
        try:
            if proc.stdin:
                proc.stdin.write(payload_json)
                proc.stdin.close()
        except Exception:
            proc.kill()
            raise

        self._write_last_trigger(marker, now)
        return QueueDrainTriggerResult(True, pid=proc.pid)

    def _is_enabled(self) -> bool:
        if self.enabled is not None:
            return self.enabled
        value = os.getenv('STASH2PLEX_HOOK_AUTODRAIN', '1').strip().lower()
        return value not in _DISABLED_VALUES

    def _cooldown_secs(self) -> float:
        if self.cooldown_secs is not None:
            return self.cooldown_secs
        try:
            return float(os.getenv('STASH2PLEX_HOOK_AUTODRAIN_COOLDOWN_SECS', '8') or 8)
        except ValueError:
            return 8.0

    @staticmethod
    def _read_last_trigger(marker: str) -> float:
        try:
            with open(marker, 'r') as f:
                return float(f.read().strip())
        except Exception:
            return 0.0

    @staticmethod
    def _write_last_trigger(marker: str, timestamp: float) -> None:
        os.makedirs(os.path.dirname(marker), exist_ok=True)
        with open(marker, 'w') as f:
            f.write(str(timestamp))

    def _log_path(self) -> str:
        return os.getenv(
            'STASH2PLEX_HOOK_AUTODRAIN_LOG',
            os.path.join(self.data_dir, 'hook_autodrain.log'),
        )

    @staticmethod
    def _rotate_log_if_needed(log_path: str) -> None:
        try:
            max_bytes = int(os.getenv('STASH2PLEX_HOOK_AUTODRAIN_LOG_MAX_BYTES', '1048576'))
        except ValueError:
            max_bytes = 1048576
        if max_bytes <= 0:
            return
        try:
            if os.path.getsize(log_path) <= max_bytes:
                return
            rotated = log_path + '.1'
            try:
                os.replace(log_path, rotated)
            except OSError:
                pass
        except FileNotFoundError:
            return


__all__ = ['QueueDrainTrigger', 'QueueDrainTriggerResult']
