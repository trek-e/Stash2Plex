"""
Throttle for Plex library-scan triggers.

When many jobs raise PlexNotFound for files in the same Plex library section
in a short window, we only want to ask Plex to scan that section once per
window — not once per job. State is persisted to disk (JSON), following the
same load/save pattern as worker.circuit_breaker and worker.recovery, so the
throttle window survives worker restarts.

A corrupt or unreadable state file must never raise into the sync path — it
is treated as "no scan history", i.e. scan anyway.
"""

import json
import os
import time
from typing import Optional

from shared.log import create_logger

log_trace, log_debug, log_info, log_warn, log_error = create_logger("ScanThrottle")

STATE_FILE = 'plex_scan_throttle.json'

# Minimum time between triggered scans of the same Plex library section.
DEFAULT_THROTTLE_INTERVAL_SECONDS = 10 * 60  # 10 minutes


class ScanThrottle:
    """Tracks the last-triggered time of a Plex scan, per library section.

    Usage:
        throttle = ScanThrottle(data_dir)
        if throttle.should_scan("Adult"):
            trigger_scan(...)
            throttle.record_scan("Adult")
    """

    def __init__(self, data_dir: str, interval_seconds: float = DEFAULT_THROTTLE_INTERVAL_SECONDS):
        self.state_path = os.path.join(data_dir, STATE_FILE)
        self.interval_seconds = interval_seconds

    def _load(self) -> dict:
        """Load throttle state. Any corruption/IO error yields an empty dict
        (never raises) — a broken state file means "scan anyway"."""
        try:
            if os.path.exists(self.state_path):
                with open(self.state_path, 'r') as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception as e:
            log_debug(f"Scan throttle state unreadable/corrupt, treating as empty: {e}")
        return {}

    def _save(self, data: dict) -> None:
        tmp_path = self.state_path + '.tmp'
        try:
            with open(tmp_path, 'w') as f:
                json.dump(data, f, indent=2)
            os.replace(tmp_path, self.state_path)
        except OSError as e:
            log_debug(f"Failed to save scan throttle state: {e}")

    def should_scan(self, library_name: str, now: Optional[float] = None) -> bool:
        """Return True if a scan of `library_name` is not currently throttled.

        Never raises: any failure reading state is treated as "not throttled".
        """
        if now is None:
            now = time.time()
        try:
            state = self._load()
            last = state.get(library_name)
            if last is None:
                return True
            return (now - float(last)) >= self.interval_seconds
        except Exception as e:
            log_debug(f"Scan throttle check failed, scanning anyway: {e}")
            return True

    def record_scan(self, library_name: str, now: Optional[float] = None) -> None:
        """Record that a scan of `library_name` was triggered at `now`.

        Never raises: a failure to persist just means the next check may
        re-trigger sooner than intended, which is safe (never unsafe-silent).
        """
        if now is None:
            now = time.time()
        try:
            state = self._load()
            state[library_name] = now
            self._save(state)
        except Exception as e:
            log_debug(f"Failed to record scan throttle state: {e}")


__all__ = ['ScanThrottle', 'DEFAULT_THROTTLE_INTERVAL_SECONDS']
