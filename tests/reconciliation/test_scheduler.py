"""Unit tests for ReconciliationScheduler."""

import json
import os
import time
from unittest.mock import Mock
import pytest
from pydantic import ValidationError

from reconciliation.scheduler import (
    ReconciliationScheduler,
    ReconciliationState,
    INTERVAL_SECONDS,
)
from validation.config import Stash2PlexConfig


# =============================================================================
# ReconciliationState Defaults
# =============================================================================

def test_default_state():
    """Fresh ReconciliationState has last_run_time=0.0, run_count=0, empty gaps_by_type."""
    state = ReconciliationState()
    assert state.last_run_time == 0.0
    assert state.run_count == 0
    assert state.last_run_scope == ""
    assert state.last_gaps_found == 0
    assert state.last_gaps_by_type == {}
    assert state.last_enqueued == 0
    assert state.last_scenes_checked == 0
    assert state.is_startup_run is False


# =============================================================================
# State Persistence
# =============================================================================

def test_load_state_no_file(tmp_path):
    """load_state() returns defaults when no file exists."""
    scheduler = ReconciliationScheduler(str(tmp_path))
    state = scheduler.load_state()

    assert isinstance(state, ReconciliationState)
    assert state.last_run_time == 0.0
    assert state.run_count == 0


def test_save_and_load_state(tmp_path):
    """Save state, load it back, verify all fields match."""
    scheduler = ReconciliationScheduler(str(tmp_path))

    # Create state with specific values
    original_state = ReconciliationState(
        last_run_time=1234567890.5,
        last_run_scope="recent",
        last_gaps_found=15,
        last_gaps_by_type={'empty_metadata': 5, 'stale_sync': 3, 'missing': 7},
        last_enqueued=12,
        last_scenes_checked=100,
        is_startup_run=True,
        run_count=3
    )

    # Save and load
    scheduler.save_state(original_state)
    loaded_state = scheduler.load_state()

    # Verify all fields match
    assert loaded_state.last_run_time == original_state.last_run_time
    assert loaded_state.last_run_scope == original_state.last_run_scope
    assert loaded_state.last_gaps_found == original_state.last_gaps_found
    assert loaded_state.last_gaps_by_type == original_state.last_gaps_by_type
    assert loaded_state.last_enqueued == original_state.last_enqueued
    assert loaded_state.last_scenes_checked == original_state.last_scenes_checked
    assert loaded_state.is_startup_run == original_state.is_startup_run
    assert loaded_state.run_count == original_state.run_count


def test_load_state_corrupt_json(tmp_path):
    """Corrupt JSON file returns defaults (graceful degradation)."""
    scheduler = ReconciliationScheduler(str(tmp_path))

    # Write corrupt JSON
    state_path = os.path.join(str(tmp_path), 'reconciliation_state.json')
    with open(state_path, 'w') as f:
        f.write("{invalid json content")

    # Should return defaults without raising
    state = scheduler.load_state()
    assert isinstance(state, ReconciliationState)
    assert state.last_run_time == 0.0


def test_save_state_atomic(tmp_path):
    """State file is written atomically (tmp then rename)."""
    scheduler = ReconciliationScheduler(str(tmp_path))
    state = ReconciliationState(last_run_time=123.456, run_count=1)

    scheduler.save_state(state)

    # Final file should exist
    final_path = os.path.join(str(tmp_path), 'reconciliation_state.json')
    assert os.path.exists(final_path)

    # Temp file should not exist
    tmp_file = final_path + '.tmp'
    assert not os.path.exists(tmp_file)

    # Verify content
    with open(final_path, 'r') as f:
        data = json.load(f)
    assert data['last_run_time'] == 123.456


# =============================================================================
# is_due() Logic
# =============================================================================

def test_is_due_never(tmp_path):
    """interval='never' always returns False."""
    scheduler = ReconciliationScheduler(str(tmp_path))
    assert scheduler.is_due('never', now=time.time()) is False


def test_is_due_hourly_not_elapsed(tmp_path):
    """30 min since last run, hourly interval -> False."""
    scheduler = ReconciliationScheduler(str(tmp_path))

    # Save state with last_run_time 30 minutes ago
    now = time.time()
    state = ReconciliationState(last_run_time=now - 1800, run_count=1)  # 1800s = 30 min
    scheduler.save_state(state)

    assert scheduler.is_due('hourly', now=now) is False


def test_is_due_hourly_elapsed(tmp_path):
    """61 min since last run, hourly interval -> True."""
    scheduler = ReconciliationScheduler(str(tmp_path))

    # Save state with last_run_time 61 minutes ago
    now = time.time()
    state = ReconciliationState(last_run_time=now - 3660, run_count=1)  # 3660s = 61 min
    scheduler.save_state(state)

    assert scheduler.is_due('hourly', now=now) is True


def test_is_due_daily_elapsed(tmp_path):
    """25 hours since last run, daily interval -> True."""
    scheduler = ReconciliationScheduler(str(tmp_path))

    # Save state with last_run_time 25 hours ago
    now = time.time()
    state = ReconciliationState(last_run_time=now - 90000, run_count=1)  # 90000s = 25 hours
    scheduler.save_state(state)

    assert scheduler.is_due('daily', now=now) is True


def test_is_due_weekly_not_elapsed(tmp_path):
    """3 days since last run, weekly interval -> False."""
    scheduler = ReconciliationScheduler(str(tmp_path))

    # Save state with last_run_time 3 days ago
    now = time.time()
    state = ReconciliationState(last_run_time=now - 259200, run_count=1)  # 259200s = 3 days
    scheduler.save_state(state)

    assert scheduler.is_due('weekly', now=now) is False


def test_is_due_first_run(tmp_path):
    """No previous run (last_run_time=0.0), any interval -> True."""
    scheduler = ReconciliationScheduler(str(tmp_path))

    # Default state has last_run_time=0.0
    assert scheduler.is_due('hourly', now=time.time()) is True
    assert scheduler.is_due('daily', now=time.time()) is True
    assert scheduler.is_due('weekly', now=time.time()) is True


# =============================================================================
# is_startup_due() Logic
# =============================================================================

def test_startup_due_never_run(tmp_path):
    """No previous run -> True."""
    scheduler = ReconciliationScheduler(str(tmp_path))

    # Default state has last_run_time=0.0
    assert scheduler.is_startup_due(now=time.time()) is True


def test_startup_due_recent_run(tmp_path):
    """Ran 30 min ago -> False (avoid rapid restart spam)."""
    scheduler = ReconciliationScheduler(str(tmp_path))

    # Save state with last_run_time 30 minutes ago
    now = time.time()
    state = ReconciliationState(last_run_time=now - 1800, run_count=1)  # 1800s = 30 min
    scheduler.save_state(state)

    assert scheduler.is_startup_due(now=now) is False


def test_startup_due_old_run(tmp_path):
    """Ran 2 hours ago -> True."""
    scheduler = ReconciliationScheduler(str(tmp_path))

    # Save state with last_run_time 2 hours ago
    now = time.time()
    state = ReconciliationState(last_run_time=now - 7200, run_count=1)  # 7200s = 2 hours
    scheduler.save_state(state)

    assert scheduler.is_startup_due(now=now) is True


# =============================================================================
# record_run()
# =============================================================================

def test_record_run_basic(tmp_path):
    """Record a run, verify all fields populated including gaps_by_type."""
    scheduler = ReconciliationScheduler(str(tmp_path))

    # Create mock result
    result = Mock()
    result.total_gaps = 15
    result.empty_metadata_count = 5
    result.stale_sync_count = 3
    result.missing_count = 7
    result.enqueued_count = 12
    result.scenes_checked = 100

    # Record the run
    scheduler.record_run(result, scope="recent", is_startup=False)

    # Load state and verify
    state = scheduler.load_state()
    assert state.last_run_time > 0
    assert state.last_run_scope == "recent"
    assert state.last_gaps_found == 15
    assert state.last_gaps_by_type == {
        'empty_metadata': 5,
        'stale_sync': 3,
        'missing': 7
    }
    assert state.last_enqueued == 12
    assert state.last_scenes_checked == 100
    assert state.is_startup_run is False
    assert state.run_count == 1


def test_record_run_increments_count(tmp_path):
    """Multiple records increment run_count."""
    scheduler = ReconciliationScheduler(str(tmp_path))

    result = Mock()
    result.total_gaps = 5
    result.empty_metadata_count = 2
    result.stale_sync_count = 1
    result.missing_count = 2
    result.enqueued_count = 4
    result.scenes_checked = 50

    # Record first run
    scheduler.record_run(result, scope="all", is_startup=False)
    state = scheduler.load_state()
    assert state.run_count == 1

    # Record second run
    scheduler.record_run(result, scope="recent", is_startup=False)
    state = scheduler.load_state()
    assert state.run_count == 2

    # Record third run
    scheduler.record_run(result, scope="recent", is_startup=True)
    state = scheduler.load_state()
    assert state.run_count == 3


def test_record_run_startup_flag(tmp_path):
    """is_startup flag is stored correctly."""
    scheduler = ReconciliationScheduler(str(tmp_path))

    result = Mock()
    result.total_gaps = 0
    result.empty_metadata_count = 0
    result.stale_sync_count = 0
    result.missing_count = 0
    result.enqueued_count = 0
    result.scenes_checked = 10

    # Record startup run
    scheduler.record_run(result, scope="recent", is_startup=True)
    state = scheduler.load_state()
    assert state.is_startup_run is True

    # Record non-startup run
    scheduler.record_run(result, scope="all", is_startup=False)
    state = scheduler.load_state()
    assert state.is_startup_run is False


# =============================================================================
# Config Validation
# =============================================================================

def test_config_reconcile_interval_valid():
    """All valid values accepted (never, hourly, daily, weekly)."""
    valid_intervals = ['never', 'hourly', 'daily', 'weekly']

    for interval in valid_intervals:
        config = Stash2PlexConfig(
            plex_url='http://localhost:32400',
            plex_token='test_token_12345',
            reconcile_interval=interval
        )
        assert config.reconcile_interval == interval


def test_config_reconcile_interval_invalid():
    """Invalid value raises ValidationError."""
    with pytest.raises(ValidationError) as exc_info:
        Stash2PlexConfig(
            plex_url='http://localhost:32400',
            plex_token='test_token_12345',
            reconcile_interval='invalid'
        )

    errors = exc_info.value.errors()
    assert any('reconcile_interval' in str(e['loc']) for e in errors)


def test_config_reconcile_interval_default():
    """Default is 'never'."""
    config = Stash2PlexConfig(
        plex_url='http://localhost:32400',
        plex_token='test_token_12345'
    )
    assert config.reconcile_interval == 'never'


def test_config_reconcile_scope_valid():
    """All valid values accepted (all, 24h, 7days)."""
    valid_scopes = ['all', '24h', '7days']

    for scope in valid_scopes:
        config = Stash2PlexConfig(
            plex_url='http://localhost:32400',
            plex_token='test_token_12345',
            reconcile_scope=scope
        )
        assert config.reconcile_scope == scope


def test_config_reconcile_scope_invalid():
    """Invalid value raises ValidationError."""
    with pytest.raises(ValidationError) as exc_info:
        Stash2PlexConfig(
            plex_url='http://localhost:32400',
            plex_token='test_token_12345',
            reconcile_scope='invalid'
        )

    errors = exc_info.value.errors()
    assert any('reconcile_scope' in str(e['loc']) for e in errors)


def test_config_reconcile_scope_default():
    """Default is '24h'."""
    config = Stash2PlexConfig(
        plex_url='http://localhost:32400',
        plex_token='test_token_12345'
    )
    assert config.reconcile_scope == '24h'
