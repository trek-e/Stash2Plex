"""
Concurrency tests for ReconciliationScheduler.claim_if_due().

Uses real fcntl locks (not mocks) with multiprocessing so the OS-level
mutual exclusion is actually exercised.
"""
import json
import multiprocessing
import os
import time


from reconciliation.scheduler import ReconciliationScheduler, ReconciliationState


# ---------------------------------------------------------------------------
# Helpers for multiprocessing workers (must be module-level for pickling)
# ---------------------------------------------------------------------------

def _worker_claim_startup(data_dir: str, result_queue):
    """Worker function: attempt claim_if_due(is_startup=True), push result."""
    scheduler = ReconciliationScheduler(data_dir)
    claimed = scheduler.claim_if_due('never', is_startup=True)
    result_queue.put(claimed)


def _worker_claim_interval(data_dir: str, interval: str, result_queue):
    """Worker function: attempt claim_if_due(interval), push result."""
    scheduler = ReconciliationScheduler(data_dir)
    claimed = scheduler.claim_if_due(interval, is_startup=False)
    result_queue.put(claimed)


# ---------------------------------------------------------------------------
# Startup-due mutual exclusion
# ---------------------------------------------------------------------------

def test_claim_if_due_startup_only_one_wins(tmp_path):
    """
    Two concurrent callers racing claim_if_due(is_startup=True) against the
    same state file: exactly ONE returns True, the other returns False.
    """
    data_dir = str(tmp_path)
    # No state file → last_run_time == 0.0 → startup due for first caller
    result_queue = multiprocessing.Queue()

    p1 = multiprocessing.Process(target=_worker_claim_startup, args=(data_dir, result_queue))
    p2 = multiprocessing.Process(target=_worker_claim_startup, args=(data_dir, result_queue))

    p1.start()
    p2.start()
    p1.join(timeout=10)
    p2.join(timeout=10)

    results = [result_queue.get_nowait() for _ in range(2)]
    true_count = sum(1 for r in results if r is True)
    false_count = sum(1 for r in results if r is False)

    assert true_count == 1, f"Expected exactly 1 True, got {results}"
    assert false_count == 1, f"Expected exactly 1 False, got {results}"


def test_claim_if_due_interval_only_one_wins(tmp_path):
    """
    Two concurrent callers racing claim_if_due('hourly') with an overdue
    last_run_time: exactly ONE returns True.
    """
    data_dir = str(tmp_path)
    # Write state with last_run_time 2 hours ago → hourly interval is due
    scheduler = ReconciliationScheduler(data_dir)
    scheduler.save_state(ReconciliationState(last_run_time=time.time() - 7200, run_count=1))

    result_queue = multiprocessing.Queue()

    p1 = multiprocessing.Process(
        target=_worker_claim_interval, args=(data_dir, 'hourly', result_queue)
    )
    p2 = multiprocessing.Process(
        target=_worker_claim_interval, args=(data_dir, 'hourly', result_queue)
    )

    p1.start()
    p2.start()
    p1.join(timeout=10)
    p2.join(timeout=10)

    results = [result_queue.get_nowait() for _ in range(2)]
    true_count = sum(1 for r in results if r is True)

    assert true_count == 1, f"Expected exactly 1 True, got {results}"


# ---------------------------------------------------------------------------
# Claim timestamp is written before the scan would start
# ---------------------------------------------------------------------------

def test_claim_writes_timestamp_before_returning(tmp_path):
    """
    After claim_if_due() returns True, last_run_time in the state file is
    already updated — not still 0.0. This proves the claim write happened
    before control returned to the caller (i.e. before any scan begins).
    """
    data_dir = str(tmp_path)
    scheduler = ReconciliationScheduler(data_dir)
    # No file → startup due
    before = time.time()
    claimed = scheduler.claim_if_due('never', is_startup=True)
    after = time.time()

    assert claimed is True

    # State file must exist and contain a timestamp in [before, after]
    state_path = os.path.join(data_dir, 'reconciliation_state.json')
    assert os.path.exists(state_path), "State file not written after claim"

    with open(state_path, 'r') as f:
        data = json.load(f)

    written_time = data['last_run_time']
    assert before <= written_time <= after, (
        f"Claim timestamp {written_time} not in expected range [{before}, {after}]"
    )


def test_second_caller_sees_claim_between_calls(tmp_path):
    """
    Simulate the TOCTOU window: first caller claims, THEN a second caller
    arrives. The second caller must see the updated timestamp and return False,
    even though the first caller has not yet called record_run().
    """
    data_dir = str(tmp_path)
    scheduler_a = ReconciliationScheduler(data_dir)
    scheduler_b = ReconciliationScheduler(data_dir)

    # First caller claims (startup due)
    first = scheduler_a.claim_if_due('never', is_startup=True)
    assert first is True

    # Second caller arrives BEFORE any record_run(); should see the claim
    second = scheduler_b.claim_if_due('never', is_startup=True)
    assert second is False, "Second caller must not re-enter the due window"


# ---------------------------------------------------------------------------
# claim_if_due returns False when not due
# ---------------------------------------------------------------------------

def test_claim_not_due_returns_false(tmp_path):
    """interval='never' → always False."""
    scheduler = ReconciliationScheduler(str(tmp_path))
    assert scheduler.claim_if_due('never', is_startup=False) is False


def test_claim_not_due_recent_run(tmp_path):
    """Ran 10 min ago, hourly interval → not due → False."""
    scheduler = ReconciliationScheduler(str(tmp_path))
    scheduler.save_state(ReconciliationState(last_run_time=time.time() - 600, run_count=1))
    assert scheduler.claim_if_due('hourly', is_startup=False) is False


def test_claim_startup_not_due_recent_run(tmp_path):
    """Ran 30 min ago → startup not due → False."""
    scheduler = ReconciliationScheduler(str(tmp_path))
    scheduler.save_state(ReconciliationState(last_run_time=time.time() - 1800, run_count=1))
    assert scheduler.claim_if_due('never', is_startup=True) is False


# ---------------------------------------------------------------------------
# record_run() still works as a post-scan "real" update
# ---------------------------------------------------------------------------

def test_record_run_after_claim(tmp_path):
    """
    claim_if_due() writes a provisional timestamp; record_run() can still
    overwrite it with a proper result, incrementing run_count etc.
    """
    from unittest.mock import Mock

    scheduler = ReconciliationScheduler(str(tmp_path))

    claimed = scheduler.claim_if_due('never', is_startup=True)
    assert claimed is True

    result = Mock()
    result.total_gaps = 3
    result.empty_metadata_count = 1
    result.stale_sync_count = 1
    result.missing_count = 1
    result.enqueued_count = 3
    result.scenes_checked = 50

    before_record = time.time()
    scheduler.record_run(result, scope="recent", is_startup=True)

    state = scheduler.load_state()
    assert state.run_count == 1
    assert state.last_run_scope == "recent"
    assert state.last_gaps_found == 3
    assert state.last_run_time >= before_record
