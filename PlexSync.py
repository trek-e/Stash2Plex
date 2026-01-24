#!/usr/bin/env python3
"""
PlexSync - Stash plugin for syncing metadata to Plex

Entry point for the Stash plugin. Initializes queue infrastructure,
starts background worker, and handles Stash hooks.
"""

import os
import sys
import json

# Add plugin directory to path for imports
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

from queue.manager import QueueManager
from queue.dlq import DeadLetterQueue
from worker.processor import SyncWorker
from hooks.handlers import on_scene_update
from validation.config import validate_config, PlexSyncConfig

# Globals (initialized in main)
queue_manager = None
dlq = None
worker = None
config: PlexSyncConfig = None


def get_plugin_data_dir():
    """
    Get or create plugin data directory.

    Returns:
        Path to plugin data directory
    """
    # Check for Stash-provided path first
    data_dir = os.getenv('STASH_PLUGIN_DATA')
    if not data_dir:
        # Default to plugin_dir/data
        data_dir = os.path.join(PLUGIN_DIR, 'data')

    os.makedirs(data_dir, exist_ok=True)
    return data_dir


def extract_config_from_input(input_data: dict) -> dict:
    """
    Extract Plex configuration from Stash input data.

    Tries several locations where Stash might pass plugin config,
    then falls back to environment variables.

    Args:
        input_data: Input data from Stash plugin protocol

    Returns:
        Dictionary with config values (may be empty if nothing found)
    """
    config_dict = {}

    # Try Stash plugin settings locations
    # Location 1: server_connection (some Stash versions)
    if 'server_connection' in input_data:
        conn = input_data['server_connection']
        if 'plex_url' in conn:
            config_dict['plex_url'] = conn['plex_url']
        if 'plex_token' in conn:
            config_dict['plex_token'] = conn['plex_token']

    # Location 2: args.config (alternate location)
    args = input_data.get('args', {})
    if 'config' in args:
        cfg = args['config']
        if isinstance(cfg, dict):
            config_dict.update(cfg)

    # Location 3: pluginSettings (another Stash pattern)
    if 'pluginSettings' in input_data:
        settings = input_data['pluginSettings']
        if isinstance(settings, dict):
            for key in ['plex_url', 'plex_token', 'enabled', 'max_retries',
                        'poll_interval', 'strict_mode']:
                if key in settings:
                    config_dict[key] = settings[key]

    # Fallback to environment variables
    if 'plex_url' not in config_dict:
        env_url = os.getenv('PLEX_URL')
        if env_url:
            config_dict['plex_url'] = env_url

    if 'plex_token' not in config_dict:
        env_token = os.getenv('PLEX_TOKEN')
        if env_token:
            config_dict['plex_token'] = env_token

    return config_dict


def initialize(config_dict: dict = None):
    """
    Initialize queue, DLQ, and worker with validated configuration.

    Args:
        config_dict: Optional configuration dictionary. If not provided,
                     will attempt to read from environment variables.

    Raises:
        SystemExit: If configuration validation fails
    """
    global queue_manager, dlq, worker, config

    # Validate configuration
    if config_dict is None:
        config_dict = {}

    # If no config provided, try environment variables as fallback
    if not config_dict:
        env_url = os.getenv('PLEX_URL')
        env_token = os.getenv('PLEX_TOKEN')
        if env_url:
            config_dict['plex_url'] = env_url
        if env_token:
            config_dict['plex_token'] = env_token

    validated_config, error = validate_config(config_dict)
    if error:
        error_msg = f"PlexSync configuration error: {error}"
        print(f"[PlexSync] ERROR: {error_msg}", file=sys.stderr)
        raise SystemExit(1)

    config = validated_config
    config.log_config()

    # Check if plugin is disabled
    if not config.enabled:
        print("[PlexSync] Plugin is disabled via configuration")
        return

    data_dir = get_plugin_data_dir()
    print(f"[PlexSync] Initializing with data directory: {data_dir}")

    # Initialize queue infrastructure
    queue_manager = QueueManager(data_dir)
    dlq = DeadLetterQueue(data_dir)

    # Start background worker with config values
    worker = SyncWorker(queue_manager.get_queue(), dlq, max_retries=config.max_retries)
    worker.start()

    print("[PlexSync] Initialization complete")


def shutdown():
    """Clean shutdown of worker and queue."""
    global worker, queue_manager

    if worker:
        print("[PlexSync] Stopping worker...")
        worker.stop()

    if queue_manager:
        print("[PlexSync] Shutting down queue...")
        queue_manager.shutdown()

    print("[PlexSync] Shutdown complete")


def handle_hook(hook_context: dict):
    """
    Handle incoming Stash hook.

    Expected hook_context structure:
    {
        "type": "Scene.Update.Post",
        "input": {...scene update data...}
    }

    Args:
        hook_context: Hook context from Stash
    """
    hook_type = hook_context.get("type", "")
    input_data = hook_context.get("input", {})

    if hook_type == "Scene.Update.Post":
        scene_id = input_data.get("id")
        if scene_id:
            on_scene_update(scene_id, input_data, queue_manager.get_queue())
        else:
            print("[PlexSync] WARNING: Scene.Update.Post hook missing scene ID")
    else:
        print(f"[PlexSync] Unhandled hook type: {hook_type}")


def main():
    """Main entry point for Stash plugin."""
    # Read input from stdin (Stash plugin protocol)
    try:
        input_data = json.loads(sys.stdin.read())
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"Invalid JSON input: {e}"}), file=sys.stderr)
        sys.exit(1)

    # Initialize on first call
    global queue_manager, config
    if queue_manager is None:
        # Extract config from Stash input
        config_dict = extract_config_from_input(input_data)
        initialize(config_dict)

    # Check if plugin is disabled (config may have loaded but plugin disabled)
    if config and not config.enabled:
        print(json.dumps({"output": "disabled"}))
        return

    # Handle the hook
    if "args" in input_data and "hookContext" in input_data["args"]:
        handle_hook(input_data["args"]["hookContext"])
    else:
        print("[PlexSync] No hookContext in input, skipping")

    # Return empty response (success)
    print(json.dumps({"output": "ok"}))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[PlexSync] Interrupted by user")
        shutdown()
        sys.exit(0)
    except Exception as e:
        import traceback
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        traceback.print_exc()
        shutdown()
        sys.exit(1)
