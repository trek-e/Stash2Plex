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
    ):
        self.plugin_dir = plugin_dir
        self.data_dir = data_dir
        self.python_executable = python_executable
        self.cooldown_secs = cooldown_secs
        self.enabled = enabled

    def trigger(self, server_connection: Optional[dict] = None) -> QueueDrainTriggerResult:
        """Request an asynchronous process_queue drain.

        The cooldown is only a burst limiter. A skipped trigger is acceptable
        when another hook recently started a drainer; queued jobs persist until
        any process_queue run handles them.
        """
        if not self._is_enabled():
            return QueueDrainTriggerResult(False, reason='disabled')

        cooldown = self._cooldown_secs()
        marker = os.path.join(self.data_dir, 'hook_autodrain.last')
        now = time.time()
        last = self._read_last_trigger(marker)
        if now - last < cooldown:
            return QueueDrainTriggerResult(False, reason='cooldown')

        payload = {
            'server_connection': server_connection or {},
            'args': {'mode': 'process_queue'},
        }

        proc = subprocess.Popen(
            [self.python_executable, os.path.join(self.plugin_dir, 'Stash2Plex.py')],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            text=True,
        )
        try:
            if proc.stdin:
                proc.stdin.write(json.dumps(payload))
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


__all__ = ['QueueDrainTrigger', 'QueueDrainTriggerResult']
