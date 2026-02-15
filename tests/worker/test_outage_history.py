"""
Tests for outage history tracking and metrics.

Covers OutageRecord, OutageHistory persistence, time formatting,
and outage metrics calculation (MTTR, MTBF, availability).
"""

import pytest
import os
import json
import time
import tempfile
from collections import deque

from worker.outage_history import (
    OutageRecord,
    OutageHistory,
    format_duration,
    format_elapsed_since,
    calculate_outage_metrics,
)


# ==============================================================================
# OutageRecord Tests
# ==============================================================================

def test_outage_record_creation():
    """Test basic OutageRecord creation."""
    record = OutageRecord(started_at=1000.0)
    assert record.started_at == 1000.0
    assert record.ended_at is None
    assert record.duration is None
    assert record.jobs_affected == 0


def test_outage_record_with_all_fields():
    """Test OutageRecord with all fields populated."""
    record = OutageRecord(
        started_at=1000.0,
        ended_at=1065.0,
        duration=65.0,
        jobs_affected=42
    )
    assert record.started_at == 1000.0
    assert record.ended_at == 1065.0
    assert record.duration == 65.0
    assert record.jobs_affected == 42


# ==============================================================================
# format_duration Tests
# ==============================================================================

def test_format_duration_zero():
    """Zero seconds formats as '0s'."""
    assert format_duration(0) == "0s"


def test_format_duration_negative():
    """Negative duration formats as '0s'."""
    assert format_duration(-10) == "0s"


def test_format_duration_seconds_only():
    """Seconds-only durations format correctly."""
    assert format_duration(5) == "5s"
    assert format_duration(59) == "59s"


def test_format_duration_minutes_and_seconds():
    """Minutes + seconds format correctly."""
    assert format_duration(60) == "1m 0s"
    assert format_duration(65) == "1m 5s"
    assert format_duration(125) == "2m 5s"


def test_format_duration_hours_and_minutes():
    """Hours + minutes format correctly (two units max)."""
    assert format_duration(3600) == "1h 0m"
    assert format_duration(3661) == "1h 1m"
    assert format_duration(7325) == "2h 2m"


def test_format_duration_days_and_hours():
    """Days + hours format correctly (two units max)."""
    assert format_duration(86400) == "1d 0h"
    assert format_duration(86401) == "1d 0h"  # Seconds dropped
    assert format_duration(90000) == "1d 1h"
    assert format_duration(172800) == "2d 0h"


def test_format_duration_floats():
    """Float seconds are truncated."""
    assert format_duration(5.9) == "5s"
    assert format_duration(65.7) == "1m 5s"


# ==============================================================================
# format_elapsed_since Tests
# ==============================================================================

def test_format_elapsed_since_with_explicit_now():
    """format_elapsed_since accepts 'now' parameter."""
    timestamp = 1000.0
    now = 1065.0
    result = format_elapsed_since(timestamp, now=now)
    assert result == "1m 5s ago"


def test_format_elapsed_since_zero_elapsed():
    """Zero elapsed time formats correctly."""
    now = 1000.0
    result = format_elapsed_since(now, now=now)
    assert result == "0s ago"


def test_format_elapsed_since_various_durations():
    """format_elapsed_since formats various durations."""
    base = 1000.0
    assert format_elapsed_since(base, now=base + 10) == "10s ago"
    assert format_elapsed_since(base, now=base + 125) == "2m 5s ago"
    assert format_elapsed_since(base, now=base + 3661) == "1h 1m ago"


# ==============================================================================
# OutageHistory Basic Tests
# ==============================================================================

@pytest.fixture
def temp_data_dir():
    """Create temporary directory for test state files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


def test_outage_history_initialization(temp_data_dir):
    """OutageHistory initializes with empty deque."""
    history = OutageHistory(temp_data_dir)
    assert history.get_history() == []
    assert history.get_current_outage() is None


def test_record_outage_start(temp_data_dir):
    """record_outage_start appends new record."""
    history = OutageHistory(temp_data_dir)
    history.record_outage_start(1000.0)

    records = history.get_history()
    assert len(records) == 1
    assert records[0].started_at == 1000.0
    assert records[0].ended_at is None


def test_record_outage_end_updates_most_recent(temp_data_dir):
    """record_outage_end updates the most recent ongoing outage."""
    history = OutageHistory(temp_data_dir)
    history.record_outage_start(1000.0)
    history.record_outage_end(ended_at=1065.0, jobs_affected=10)

    records = history.get_history()
    assert len(records) == 1
    assert records[0].ended_at == 1065.0
    assert records[0].duration == 65.0
    assert records[0].jobs_affected == 10


def test_record_outage_end_does_nothing_if_no_ongoing(temp_data_dir):
    """record_outage_end does nothing if no ongoing outage exists."""
    history = OutageHistory(temp_data_dir)
    history.record_outage_start(1000.0)
    history.record_outage_end(ended_at=1065.0, jobs_affected=5)

    # Try to end again (should be no-op)
    history.record_outage_end(ended_at=2000.0, jobs_affected=10)

    records = history.get_history()
    assert len(records) == 1
    assert records[0].ended_at == 1065.0  # Not updated


def test_get_current_outage_returns_ongoing(temp_data_dir):
    """get_current_outage returns record with ended_at=None."""
    history = OutageHistory(temp_data_dir)
    history.record_outage_start(1000.0)

    current = history.get_current_outage()
    assert current is not None
    assert current.started_at == 1000.0
    assert current.ended_at is None


def test_get_current_outage_returns_none_when_ended(temp_data_dir):
    """get_current_outage returns None when outage is ended."""
    history = OutageHistory(temp_data_dir)
    history.record_outage_start(1000.0)
    history.record_outage_end(ended_at=1065.0)

    current = history.get_current_outage()
    assert current is None


def test_circular_buffer_drops_oldest(temp_data_dir):
    """deque(maxlen=30) automatically drops oldest records."""
    history = OutageHistory(temp_data_dir)

    # Add 35 outages
    for i in range(35):
        history.record_outage_start(float(i * 100))
        history.record_outage_end(ended_at=float(i * 100 + 50))

    records = history.get_history()
    assert len(records) == 30
    # First record should be outage #5 (0-4 dropped)
    assert records[0].started_at == 500.0


# ==============================================================================
# OutageHistory Persistence Tests
# ==============================================================================

def test_outage_start_persists_to_disk(temp_data_dir):
    """record_outage_start saves state to disk."""
    history = OutageHistory(temp_data_dir)
    history.record_outage_start(1000.0)

    state_path = os.path.join(temp_data_dir, 'outage_history.json')
    assert os.path.exists(state_path)

    with open(state_path, 'r') as f:
        data = json.load(f)

    assert len(data) == 1
    assert data[0]['started_at'] == 1000.0


def test_outage_end_persists_to_disk(temp_data_dir):
    """record_outage_end saves updated state to disk."""
    history = OutageHistory(temp_data_dir)
    history.record_outage_start(1000.0)
    history.record_outage_end(ended_at=1065.0, jobs_affected=5)

    state_path = os.path.join(temp_data_dir, 'outage_history.json')
    with open(state_path, 'r') as f:
        data = json.load(f)

    assert data[0]['ended_at'] == 1065.0
    assert data[0]['duration'] == 65.0
    assert data[0]['jobs_affected'] == 5


def test_persistence_survives_re_instantiation(temp_data_dir):
    """OutageHistory loads prior state from disk."""
    # First instance
    history1 = OutageHistory(temp_data_dir)
    history1.record_outage_start(1000.0)
    history1.record_outage_end(ended_at=1065.0, jobs_affected=3)

    # Second instance
    history2 = OutageHistory(temp_data_dir)
    records = history2.get_history()

    assert len(records) == 1
    assert records[0].started_at == 1000.0
    assert records[0].ended_at == 1065.0
    assert records[0].jobs_affected == 3


def test_corrupted_json_resets_to_empty(temp_data_dir):
    """Corrupted outage_history.json resets to empty deque."""
    state_path = os.path.join(temp_data_dir, 'outage_history.json')

    # Write invalid JSON
    with open(state_path, 'w') as f:
        f.write("not valid json {[")

    # Should not crash, should start with empty history
    history = OutageHistory(temp_data_dir)
    assert history.get_history() == []


def test_missing_json_file_starts_empty(temp_data_dir):
    """Missing outage_history.json starts with empty deque."""
    history = OutageHistory(temp_data_dir)
    assert history.get_history() == []


# ==============================================================================
# calculate_outage_metrics Tests
# ==============================================================================

def test_calculate_metrics_empty_history():
    """Empty history returns zero metrics with 100% availability."""
    metrics = calculate_outage_metrics([])

    assert metrics['mttr'] == 0.0
    assert metrics['mtbf'] == 0.0
    assert metrics['availability'] == 100.0
    assert metrics['total_downtime'] == 0.0
    assert metrics['outage_count'] == 0


def test_calculate_metrics_ongoing_outage_ignored():
    """Ongoing outages (ended_at=None) are excluded."""
    records = [
        OutageRecord(started_at=1000.0, ended_at=None)
    ]
    metrics = calculate_outage_metrics(records)

    assert metrics['mttr'] == 0.0
    assert metrics['mtbf'] == 0.0
    assert metrics['availability'] == 100.0
    assert metrics['outage_count'] == 0


def test_calculate_metrics_single_completed_outage():
    """Single completed outage: MTTR calculated, MTBF=0."""
    records = [
        OutageRecord(started_at=1000.0, ended_at=1060.0, duration=60.0, jobs_affected=5)
    ]
    metrics = calculate_outage_metrics(records)

    assert metrics['mttr'] == 60.0
    assert metrics['mtbf'] == 0.0  # Need >= 2 for MTBF
    assert metrics['availability'] == 100.0  # MTBF=0 means no uptime span
    assert metrics['total_downtime'] == 60.0
    assert metrics['outage_count'] == 1


def test_calculate_metrics_two_completed_outages():
    """Two completed outages: MTTR and MTBF calculated."""
    records = [
        OutageRecord(started_at=1000.0, ended_at=1060.0, duration=60.0, jobs_affected=0),
        OutageRecord(started_at=2000.0, ended_at=2120.0, duration=120.0, jobs_affected=0)
    ]
    metrics = calculate_outage_metrics(records)

    # MTTR = (60 + 120) / 2 = 90
    assert metrics['mttr'] == 90.0

    # MTBF = (2000 - 1000) / (2 - 1) = 1000
    assert metrics['mtbf'] == 1000.0

    # Availability = (1000 / (1000 + 90)) * 100 ≈ 91.74%
    expected_availability = (1000.0 / (1000.0 + 90.0)) * 100
    assert abs(metrics['availability'] - expected_availability) < 0.01

    assert metrics['total_downtime'] == 180.0
    assert metrics['outage_count'] == 2


def test_calculate_metrics_multiple_outages():
    """Multiple outages compute correct metrics."""
    records = [
        OutageRecord(started_at=1000.0, ended_at=1030.0, duration=30.0, jobs_affected=0),
        OutageRecord(started_at=2000.0, ended_at=2050.0, duration=50.0, jobs_affected=0),
        OutageRecord(started_at=3000.0, ended_at=3040.0, duration=40.0, jobs_affected=0)
    ]
    metrics = calculate_outage_metrics(records)

    # MTTR = (30 + 50 + 40) / 3 = 40
    assert metrics['mttr'] == 40.0

    # MTBF = ((2000-1000) + (3000-2000)) / (3-1) = 2000 / 2 = 1000
    assert metrics['mtbf'] == 1000.0

    # Availability = (1000 / (1000 + 40)) * 100 ≈ 96.15%
    expected_availability = (1000.0 / (1000.0 + 40.0)) * 100
    assert abs(metrics['availability'] - expected_availability) < 0.01

    assert metrics['total_downtime'] == 120.0
    assert metrics['outage_count'] == 3


def test_calculate_metrics_mixed_ongoing_and_completed():
    """Mix of ongoing and completed outages: only completed count."""
    records = [
        OutageRecord(started_at=1000.0, ended_at=1060.0, duration=60.0, jobs_affected=0),
        OutageRecord(started_at=2000.0, ended_at=None),  # Ongoing
        OutageRecord(started_at=3000.0, ended_at=3120.0, duration=120.0, jobs_affected=0)
    ]
    metrics = calculate_outage_metrics(records)

    # Only 2 completed outages
    assert metrics['mttr'] == 90.0  # (60 + 120) / 2
    assert metrics['mtbf'] == 2000.0  # (3000 - 1000) / 1
    assert metrics['total_downtime'] == 180.0
    assert metrics['outage_count'] == 2


def test_calculate_metrics_availability_edge_case():
    """Availability is 100% when MTBF=0 (avoids division by zero)."""
    records = [
        OutageRecord(started_at=1000.0, ended_at=1060.0, duration=60.0, jobs_affected=0)
    ]
    metrics = calculate_outage_metrics(records)

    assert metrics['availability'] == 100.0


# ==============================================================================
# Integration Tests
# ==============================================================================

def test_full_lifecycle_with_persistence(temp_data_dir):
    """Full lifecycle: start → persist → reload → end → reload."""
    # Start outage
    history1 = OutageHistory(temp_data_dir)
    history1.record_outage_start(1000.0)

    # Reload (ongoing outage should exist)
    history2 = OutageHistory(temp_data_dir)
    current = history2.get_current_outage()
    assert current is not None
    assert current.started_at == 1000.0

    # End outage
    history2.record_outage_end(ended_at=1065.0, jobs_affected=7)

    # Reload (should have completed outage)
    history3 = OutageHistory(temp_data_dir)
    records = history3.get_history()
    assert len(records) == 1
    assert records[0].ended_at == 1065.0
    assert records[0].duration == 65.0
    assert records[0].jobs_affected == 7
    assert history3.get_current_outage() is None


def test_metrics_from_history_manager(temp_data_dir):
    """Calculate metrics from OutageHistory's get_history()."""
    history = OutageHistory(temp_data_dir)

    # Add 3 outages
    history.record_outage_start(1000.0)
    history.record_outage_end(ended_at=1030.0, jobs_affected=2)

    history.record_outage_start(2000.0)
    history.record_outage_end(ended_at=2050.0, jobs_affected=5)

    history.record_outage_start(3000.0)
    history.record_outage_end(ended_at=3040.0, jobs_affected=1)

    # Calculate metrics
    metrics = calculate_outage_metrics(history.get_history())

    assert metrics['outage_count'] == 3
    assert metrics['mttr'] == 40.0
    assert metrics['mtbf'] == 1000.0
