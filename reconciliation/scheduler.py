"""
Reconciliation scheduler for automatic gap detection.

Since Stash plugins are invoked per-event (not long-running), the scheduler
uses a check-on-invocation pattern: each plugin run checks if reconciliation
is due based on persisted state in reconciliation_state.json.
"""

import json
import os
import time
from dataclasses import dataclass, field, asdict
from typing import Optional

from shared.log import create_logger
_, log_debug, log_info, _, _ = create_logger("Scheduler")

# Interval to seconds mapping
INTERVAL_SECONDS = {
    'never': 0,
    'hourly': 3600,
    'daily': 86400,
    'weekly': 604800,
}

# Scope to engine scope mapping
SCOPE_MAP = {
    'all': 'all',
    '24h': 'recent',
    '7days': 'recent_7days',
}


@dataclass
class ReconciliationState:
    """Persisted state for reconciliation scheduling."""
    last_run_time: float = 0.0          # time.time() of last run
    last_run_scope: str = ""            # scope used
    last_gaps_found: int = 0            # total gaps detected
    last_gaps_by_type: dict = field(default_factory=dict)  # {empty: N, stale: N, missing: N}
    last_enqueued: int = 0              # gaps enqueued
    last_scenes_checked: int = 0        # scenes checked
    is_startup_run: bool = False        # was last run a startup trigger?
    run_count: int = 0                  # total runs


class ReconciliationScheduler:
    """Manages auto-reconciliation scheduling via persisted state.

    NOT a timer/thread. On each plugin invocation, call is_due() to check
    if reconciliation should run based on interval config and last run time.
    """

    STATE_FILE = 'reconciliation_state.json'

    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self.state_path = os.path.join(data_dir, self.STATE_FILE)

    def load_state(self) -> ReconciliationState:
        """Load reconciliation state from disk."""
        try:
            if os.path.exists(self.state_path):
                with open(self.state_path, 'r') as f:
                    data = json.load(f)
                return ReconciliationState(**data)
        except (json.JSONDecodeError, TypeError, KeyError) as e:
            log_debug(f"Failed to load reconciliation state, using defaults: {e}")
        return ReconciliationState()

    def save_state(self, state: ReconciliationState) -> None:
        """Save reconciliation state to disk atomically."""
        tmp_path = self.state_path + '.tmp'
        try:
            with open(tmp_path, 'w') as f:
                json.dump(asdict(state), f, indent=2)
            os.replace(tmp_path, self.state_path)
        except OSError as e:
            log_debug(f"Failed to save reconciliation state: {e}")

    def is_due(self, interval: str, now: Optional[float] = None) -> bool:
        """Check if auto-reconciliation is due based on interval and last run time.

        Args:
            interval: 'never', 'hourly', 'daily', 'weekly'
            now: Current time (default: time.time()). For testing.

        Returns:
            True if reconciliation should run now.
        """
        if interval == 'never':
            return False

        interval_secs = INTERVAL_SECONDS.get(interval, 0)
        if interval_secs == 0:
            return False

        if now is None:
            now = time.time()

        state = self.load_state()
        elapsed = now - state.last_run_time
        return elapsed >= interval_secs

    def is_startup_due(self, now: Optional[float] = None) -> bool:
        """Check if startup reconciliation should run.

        Startup reconciliation runs if the plugin has never run reconciliation
        before, or if more than 1 hour has passed since the last run.
        This avoids re-running on rapid Stash restarts.

        Args:
            now: Current time (default: time.time()). For testing.

        Returns:
            True if startup reconciliation should run.
        """
        if now is None:
            now = time.time()

        state = self.load_state()
        if state.last_run_time == 0.0:
            return True  # Never run before

        elapsed = now - state.last_run_time
        return elapsed >= 3600  # At least 1 hour since last run

    def record_run(self, result, scope: str, is_startup: bool = False) -> None:
        """Record a completed reconciliation run.

        Args:
            result: GapDetectionResult from engine.run()
            scope: Scope string used
            is_startup: Whether this was a startup-triggered run
        """
        state = self.load_state()
        state.last_run_time = time.time()
        state.last_run_scope = scope
        state.last_gaps_found = result.total_gaps
        state.last_gaps_by_type = {
            'empty_metadata': result.empty_metadata_count,
            'stale_sync': result.stale_sync_count,
            'missing': result.missing_count,
        }
        state.last_enqueued = result.enqueued_count
        state.last_scenes_checked = result.scenes_checked
        state.is_startup_run = is_startup
        state.run_count += 1
        self.save_state(state)
