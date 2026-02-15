"""
Outage history tracking and metrics calculation.

Stores up to 30 outage records in a circular buffer with persistence
to outage_history.json. Provides time formatting helpers and calculates
MTTR, MTBF, and availability metrics.
"""

import json
import os
import time
from collections import deque
from dataclasses import dataclass, asdict
from typing import Optional, List, Dict

from shared.log import create_logger

_, log_debug, log_info, _, log_error = create_logger("OutageHistory")


@dataclass
class OutageRecord:
    """Single outage record with timing and impact data."""
    started_at: float
    ended_at: Optional[float] = None
    duration: Optional[float] = None
    jobs_affected: int = 0


class OutageHistory:
    """
    Manages outage history with circular buffer persistence.

    Stores up to 30 outage records with atomic persistence to
    outage_history.json. Tracks ongoing outages and provides
    metrics calculation support.

    Args:
        data_dir: Directory for outage_history.json persistence

    Usage:
        history = OutageHistory(data_dir)

        # Start tracking outage
        history.record_outage_start(time.time())

        # End outage
        history.record_outage_end(ended_at=time.time(), jobs_affected=10)

        # Get metrics
        metrics = calculate_outage_metrics(history.get_history())
    """

    STATE_FILE = 'outage_history.json'
    MAX_OUTAGES = 30

    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self.state_path = os.path.join(data_dir, self.STATE_FILE)
        self._history: deque = deque(maxlen=self.MAX_OUTAGES)

        # Load persisted state if available
        self._load_state()

    def record_outage_start(self, started_at: float) -> None:
        """
        Record the start of a new outage.

        Args:
            started_at: Timestamp when outage began
        """
        record = OutageRecord(started_at=started_at)
        self._history.append(record)
        self._save_state()

        log_debug(f"Outage started at {started_at}")

    def record_outage_end(self, ended_at: float, jobs_affected: int = 0) -> None:
        """
        Record the end of the most recent ongoing outage.

        Updates the most recent record that has ended_at=None.
        Does nothing if no ongoing outage exists.

        Args:
            ended_at: Timestamp when outage ended
            jobs_affected: Number of jobs affected during outage
        """
        # Find most recent ongoing outage (ended_at is None)
        for i in range(len(self._history) - 1, -1, -1):
            if self._history[i].ended_at is None:
                # Update the record
                record = self._history[i]
                record.ended_at = ended_at
                record.duration = ended_at - record.started_at
                record.jobs_affected = jobs_affected

                self._save_state()

                log_debug(
                    f"Outage ended at {ended_at}, duration={record.duration:.1f}s, "
                    f"jobs_affected={jobs_affected}"
                )
                return

        # No ongoing outage found
        log_debug("record_outage_end called but no ongoing outage found")

    def get_history(self) -> List[OutageRecord]:
        """
        Get copy of outage history as a list.

        Returns:
            List of OutageRecord objects, oldest to newest
        """
        return list(self._history)

    def get_current_outage(self) -> Optional[OutageRecord]:
        """
        Get the current ongoing outage if one exists.

        Returns:
            OutageRecord with ended_at=None, or None if no ongoing outage
        """
        # Check from most recent backwards
        for i in range(len(self._history) - 1, -1, -1):
            if self._history[i].ended_at is None:
                return self._history[i]

        return None

    def _load_state(self) -> None:
        """Load outage history from disk."""
        if not os.path.exists(self.state_path):
            log_debug(f"No state file found at {self.state_path}, starting fresh")
            return

        try:
            with open(self.state_path, 'r') as f:
                data = json.load(f)

            # Reconstruct OutageRecord objects
            for record_dict in data:
                record = OutageRecord(**record_dict)
                self._history.append(record)

            log_debug(f"Loaded {len(self._history)} outage records from disk")

        except (json.JSONDecodeError, TypeError, KeyError) as e:
            log_error(f"Failed to load outage history, starting fresh: {e}")
            self._history.clear()

    def _save_state(self) -> None:
        """Save outage history to disk with atomic write."""
        try:
            # Convert deque to list of dicts
            data = [asdict(record) for record in self._history]

            # Atomic write: tmp file + os.replace
            tmp_path = self.state_path + '.tmp'

            with open(tmp_path, 'w') as f:
                json.dump(data, f, indent=2)

            os.replace(tmp_path, self.state_path)

        except Exception as e:
            log_error(f"Failed to save outage history: {e}")


# ==============================================================================
# Time Formatting Helpers
# ==============================================================================

def format_duration(seconds: float) -> str:
    """
    Format duration in seconds to human-readable string.

    Shows at most 2 units for brevity.

    Args:
        seconds: Duration in seconds

    Returns:
        Formatted string like "2m 5s", "1h 30m", "2d 3h"

    Examples:
        0 -> "0s"
        65 -> "1m 5s"
        3661 -> "1h 1m"
        86401 -> "1d 0h"
    """
    if seconds < 0:
        return "0s"

    # Truncate to int
    seconds = int(seconds)

    if seconds == 0:
        return "0s"

    # Calculate units
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    # Build string with at most 2 units
    parts = []

    if days > 0:
        parts.append(f"{days}d")
        parts.append(f"{hours}h")
    elif hours > 0:
        parts.append(f"{hours}h")
        parts.append(f"{minutes}m")
    elif minutes > 0:
        parts.append(f"{minutes}m")
        parts.append(f"{secs}s")
    else:
        parts.append(f"{secs}s")

    return " ".join(parts[:2])


def format_elapsed_since(timestamp: float, now: Optional[float] = None) -> str:
    """
    Format elapsed time since timestamp.

    Args:
        timestamp: Start time
        now: Current time (defaults to time.time())

    Returns:
        Formatted string like "5m 30s ago"
    """
    if now is None:
        now = time.time()

    elapsed = now - timestamp
    return f"{format_duration(elapsed)} ago"


# ==============================================================================
# Metrics Calculation
# ==============================================================================

def calculate_outage_metrics(history: List[OutageRecord]) -> Dict[str, float]:
    """
    Calculate outage metrics from history.

    Only completed outages (ended_at is not None) are included.

    Metrics:
        - mttr: Mean Time To Repair (average downtime duration)
        - mtbf: Mean Time Between Failures (average uptime between outages)
        - availability: Percentage uptime (mtbf / (mtbf + mttr) * 100)
        - total_downtime: Sum of all outage durations
        - outage_count: Number of completed outages

    Args:
        history: List of OutageRecord objects

    Returns:
        Dictionary with metrics (all floats)

    Notes:
        - MTBF requires >= 2 completed outages, returns 0.0 otherwise
        - Availability is 100.0 when MTBF=0 (avoids division by zero)
        - Empty history returns all zeros except availability=100.0
    """
    # Filter completed outages only
    completed = [r for r in history if r.ended_at is not None]

    if not completed:
        return {
            'mttr': 0.0,
            'mtbf': 0.0,
            'availability': 100.0,
            'total_downtime': 0.0,
            'outage_count': 0
        }

    # Calculate total downtime and MTTR
    # Defense: filter out records with None duration (should never happen but prevents crash)
    valid_durations = [r.duration for r in completed if r.duration is not None]
    if not valid_durations:
        return {
            'mttr': 0.0,
            'mtbf': 0.0,
            'availability': 100.0,
            'total_downtime': 0.0,
            'outage_count': 0
        }

    total_downtime = sum(valid_durations)
    mttr = total_downtime / len(valid_durations)

    # Calculate MTBF (requires >= 2 outages)
    mtbf = 0.0
    if len(completed) >= 2:
        # Sum time between consecutive outages (end of outage N to start of outage N+1)
        time_between_sum = 0.0
        for i in range(1, len(completed)):
            # MTBF = uptime = time from end of previous outage to start of next outage
            time_between_sum += completed[i].started_at - completed[i - 1].ended_at

        mtbf = time_between_sum / (len(completed) - 1)

    # Calculate availability
    if mtbf > 0:
        availability = (mtbf / (mtbf + mttr)) * 100
    else:
        availability = 100.0

    return {
        'mttr': mttr,
        'mtbf': mtbf,
        'availability': availability,
        'total_downtime': total_downtime,
        'outage_count': len(completed)
    }
