"""Tests for ProcessGuard — slot-based process concurrency limiter."""
import subprocess
import sys
import time
from unittest.mock import patch


from sync_queue.process_guard import ProcessGuard


# ---------------------------------------------------------------------------
# Slot acquisition basics
# ---------------------------------------------------------------------------

def test_acquire_returns_true_when_slot_available(tmp_path):
    guard = ProcessGuard(str(tmp_path), max_processes=3)
    assert guard.acquire() is True
    guard.release()


def test_acquire_returns_false_when_all_slots_taken(tmp_path):
    guards = [ProcessGuard(str(tmp_path), max_processes=2) for _ in range(2)]
    assert guards[0].acquire() is True
    assert guards[1].acquire() is True

    overflow = ProcessGuard(str(tmp_path), max_processes=2)
    assert overflow.acquire() is False
    overflow.release()  # no-op, but should not raise

    guards[0].release()
    guards[1].release()


def test_released_slot_can_be_reacquired(tmp_path):
    guard1 = ProcessGuard(str(tmp_path), max_processes=1)
    guard2 = ProcessGuard(str(tmp_path), max_processes=1)

    assert guard1.acquire() is True
    assert guard2.acquire() is False  # cap reached

    guard1.release()

    assert guard2.acquire() is True  # slot now free
    guard2.release()


# ---------------------------------------------------------------------------
# live_count
# ---------------------------------------------------------------------------

def test_live_count_zero_when_no_slots_held(tmp_path):
    guard = ProcessGuard(str(tmp_path), max_processes=3)
    assert guard.live_count() == 0


def test_live_count_reflects_held_slots(tmp_path):
    g1 = ProcessGuard(str(tmp_path), max_processes=3)
    g2 = ProcessGuard(str(tmp_path), max_processes=3)

    assert g1.acquire() is True
    assert guard_live(tmp_path, max_processes=3) == 1

    assert g2.acquire() is True
    assert guard_live(tmp_path, max_processes=3) == 2

    g1.release()
    assert guard_live(tmp_path, max_processes=3) == 1

    g2.release()
    assert guard_live(tmp_path, max_processes=3) == 0


def guard_live(tmp_path, max_processes):
    """Helper: create a fresh guard and return live_count."""
    return ProcessGuard(str(tmp_path), max_processes=max_processes).live_count()


def test_live_count_decrements_after_release(tmp_path):
    g = ProcessGuard(str(tmp_path), max_processes=2)
    assert g.acquire() is True
    assert guard_live(tmp_path, 2) == 1
    g.release()
    assert guard_live(tmp_path, 2) == 0


# ---------------------------------------------------------------------------
# Environment variable configuration
# ---------------------------------------------------------------------------

def test_max_processes_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv('STASH2PLEX_MAX_CONCURRENT_PROCESSES', '2')
    # Re-import to pick up env (or construct explicitly)
    guard = ProcessGuard(str(tmp_path))
    assert guard.max_processes == 2


def test_max_processes_env_invalid_falls_back_to_default(tmp_path, monkeypatch):
    monkeypatch.setenv('STASH2PLEX_MAX_CONCURRENT_PROCESSES', 'not_a_number')
    guard = ProcessGuard(str(tmp_path))
    assert guard.max_processes == 5  # default


def test_max_processes_env_zero_clamped_to_one(tmp_path, monkeypatch):
    monkeypatch.setenv('STASH2PLEX_MAX_CONCURRENT_PROCESSES', '0')
    guard = ProcessGuard(str(tmp_path))
    assert guard.max_processes == 1


# ---------------------------------------------------------------------------
# Multiple acquire calls from same object
# ---------------------------------------------------------------------------

def test_double_acquire_occupies_two_slots(tmp_path):
    """Calling acquire() twice from the same object object acquires two slots."""
    # (In production this doesn't happen, but guard against it)
    g1 = ProcessGuard(str(tmp_path), max_processes=2)
    g2 = ProcessGuard(str(tmp_path), max_processes=2)

    assert g1.acquire() is True
    assert g2.acquire() is True

    overflow = ProcessGuard(str(tmp_path), max_processes=2)
    assert overflow.acquire() is False
    overflow.release()

    g1.release()
    g2.release()


# ---------------------------------------------------------------------------
# Cross-process slot visibility
# ---------------------------------------------------------------------------

def test_slot_held_by_child_process_seen_as_live(tmp_path):
    """A slot held by a subprocess appears occupied to the parent's live_count."""
    # Spawn a child that acquires a slot and then sleeps briefly
    script = f"""
import sys
sys.path.insert(0, {repr(str(tmp_path.parent.parent))})
from sync_queue.process_guard import ProcessGuard
import time, os, signal

g = ProcessGuard({repr(str(tmp_path))}, max_processes=3)
ok = g.acquire()
# Signal parent that slot is held
import pathlib
pathlib.Path({repr(str(tmp_path / 'ready'))}).write_text('1')
# Hold the slot until parent signals us to stop
while not pathlib.Path({repr(str(tmp_path / 'stop'))}).exists():
    time.sleep(0.05)
g.release()
"""
    child = subprocess.Popen([sys.executable, '-c', script])
    ready_file = tmp_path / 'ready'
    deadline = time.time() + 5.0
    while not ready_file.exists() and time.time() < deadline:
        time.sleep(0.05)

    assert ready_file.exists(), "Child did not signal readiness"

    # Parent sees 1 live slot
    observer = ProcessGuard(str(tmp_path), max_processes=3)
    assert observer.live_count() == 1

    # Signal child to stop and wait
    (tmp_path / 'stop').write_text('1')
    child.wait(timeout=5)

    # Slot should be free now
    assert observer.live_count() == 0


# ---------------------------------------------------------------------------
# Drain trigger capacity check
# ---------------------------------------------------------------------------

class _FakeStdin:
    def __init__(self):
        self.writes = []
        self.closed = False

    def write(self, data):
        self.writes.append(data)

    def close(self):
        self.closed = True


class _FakeProcess:
    def __init__(self):
        self.pid = 9999
        self.stdin = _FakeStdin()

    def kill(self):
        pass


def test_drain_trigger_skips_when_at_capacity(tmp_path):
    """drain_trigger skips spawning when live_count >= max_processes."""
    from sync_queue.drain_trigger import QueueDrainTrigger

    # Hold all slots
    g1 = ProcessGuard(str(tmp_path), max_processes=2)
    g2 = ProcessGuard(str(tmp_path), max_processes=2)
    assert g1.acquire() is True
    assert g2.acquire() is True

    with patch('sync_queue.drain_trigger.subprocess.Popen') as popen:
        result = QueueDrainTrigger(
            plugin_dir='/plugin',
            data_dir=str(tmp_path),
            python_executable='/python',
            cooldown_secs=0,
            enabled=True,
            max_processes=2,
        ).trigger()

    assert result.triggered is False
    assert 'at_capacity' in result.reason
    popen.assert_not_called()

    g1.release()
    g2.release()


def test_drain_trigger_spawns_when_below_capacity(tmp_path):
    """drain_trigger spawns when a slot is available."""
    from sync_queue.drain_trigger import QueueDrainTrigger

    process = _FakeProcess()
    with patch('sync_queue.drain_trigger.subprocess.Popen', return_value=process):
        result = QueueDrainTrigger(
            plugin_dir='/plugin',
            data_dir=str(tmp_path),
            python_executable='/python',
            cooldown_secs=0,
            enabled=True,
            max_processes=3,
        ).trigger({'Host': 'stash'})

    assert result.triggered is True
    assert result.pid == 9999


def test_drain_trigger_guard_failure_allows_spawn(tmp_path):
    """If ProcessGuard raises unexpectedly, drain_trigger proceeds anyway."""
    from sync_queue.drain_trigger import QueueDrainTrigger

    process = _FakeProcess()
    with patch('sync_queue.drain_trigger.subprocess.Popen', return_value=process), \
         patch('sync_queue.drain_trigger.ProcessGuard', side_effect=RuntimeError('disk full')):
        result = QueueDrainTrigger(
            plugin_dir='/plugin',
            data_dir=str(tmp_path),
            python_executable='/python',
            cooldown_secs=0,
            enabled=True,
        ).trigger()

    assert result.triggered is True
