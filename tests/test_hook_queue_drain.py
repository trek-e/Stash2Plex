from unittest.mock import MagicMock, patch


def _identification_hook():
    return {
        'type': 'Scene.Update.Post',
        'id': 123,
        'input': {'stash_ids': [{'stash_id': 'abc'}]},
    }


def test_identification_hook_triggers_queue_drain_after_enqueue():
    from Stash2Plex import handle_hook

    with patch('Stash2Plex.get_plugin_data_dir', return_value='/tmp/data'), \
         patch('Stash2Plex.on_scene_update', return_value=True) as on_scene_update, \
         patch('Stash2Plex._trigger_async_queue_drain') as trigger_drain:

        handle_hook(_identification_hook(), stash=MagicMock(), server_connection={'Host': 'stash'})

    on_scene_update.assert_called_once()
    assert on_scene_update.call_args.kwargs['defer_scene_fetch'] is True
    trigger_drain.assert_called_once_with({'Host': 'stash'})


def test_identification_hook_triggers_queue_drain_when_scene_already_pending():
    from Stash2Plex import handle_hook

    with patch('Stash2Plex.get_plugin_data_dir', return_value='/tmp/data'), \
         patch('Stash2Plex.on_scene_update', return_value=False), \
         patch('Stash2Plex._trigger_async_queue_drain') as trigger_drain:

        handle_hook(_identification_hook(), stash=MagicMock(), server_connection={'Host': 'stash'})

    trigger_drain.assert_called_once_with({'Host': 'stash'})


def test_non_identification_hook_does_not_trigger_queue_drain():
    from Stash2Plex import handle_hook

    hook = {
        'type': 'Scene.Update.Post',
        'id': 123,
        'input': {'title': 'manual edit'},
    }

    with patch('Stash2Plex.on_scene_update') as on_scene_update, \
         patch('Stash2Plex._trigger_async_queue_drain') as trigger_drain:

        handle_hook(hook, stash=MagicMock(), server_connection={'Host': 'stash'})

    on_scene_update.assert_not_called()
    trigger_drain.assert_not_called()
