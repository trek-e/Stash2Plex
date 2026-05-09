from unittest.mock import MagicMock, patch

from sync_queue.drain_trigger import QueueDrainTrigger


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
        self.pid = 4321
        self.stdin = _FakeStdin()
        self.killed = False

    def kill(self):
        self.killed = True


def test_queue_drain_trigger_starts_process_queue(tmp_path):
    process = _FakeProcess()

    with patch('sync_queue.drain_trigger.subprocess.Popen', return_value=process) as popen:
        result = QueueDrainTrigger(
            plugin_dir='/plugin',
            data_dir=str(tmp_path),
            python_executable='/python',
            cooldown_secs=8,
            enabled=True,
        ).trigger({'Host': 'stash'})

    assert result.triggered is True
    assert result.pid == 4321
    popen.assert_called_once()
    args = popen.call_args[0][0]
    assert args == ['/python', '/plugin/Stash2Plex.py']
    assert '"mode": "process_queue"' in process.stdin.writes[0]
    assert '"Host": "stash"' in process.stdin.writes[0]
    assert process.stdin.closed is True
    assert (tmp_path / 'hook_autodrain.last').exists()


def test_queue_drain_trigger_honors_cooldown(tmp_path):
    marker = tmp_path / 'hook_autodrain.last'
    marker.write_text('100.0')

    with patch('sync_queue.drain_trigger.time.time', return_value=101.0), \
         patch('sync_queue.drain_trigger.subprocess.Popen') as popen:
        result = QueueDrainTrigger(
            plugin_dir='/plugin',
            data_dir=str(tmp_path),
            python_executable='/python',
            cooldown_secs=8,
            enabled=True,
        ).trigger()

    assert result.triggered is False
    assert result.reason == 'cooldown'
    popen.assert_not_called()


def test_queue_drain_trigger_can_be_disabled(tmp_path):
    with patch('sync_queue.drain_trigger.subprocess.Popen') as popen:
        result = QueueDrainTrigger(
            plugin_dir='/plugin',
            data_dir=str(tmp_path),
            python_executable='/python',
            enabled=False,
        ).trigger()

    assert result.triggered is False
    assert result.reason == 'disabled'
    popen.assert_not_called()


def test_queue_drain_trigger_kills_process_when_payload_write_fails(tmp_path):
    process = _FakeProcess()
    process.stdin.write = MagicMock(side_effect=RuntimeError('pipe closed'))

    with patch('sync_queue.drain_trigger.subprocess.Popen', return_value=process):
        trigger = QueueDrainTrigger(
            plugin_dir='/plugin',
            data_dir=str(tmp_path),
            python_executable='/python',
            cooldown_secs=8,
            enabled=True,
        )
        try:
            trigger.trigger()
        except RuntimeError:
            pass

    assert process.killed is True
    assert not (tmp_path / 'hook_autodrain.last').exists()
