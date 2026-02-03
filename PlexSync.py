#!/usr/bin/env python3
"""
PlexSync - Stash plugin for syncing metadata to Plex

Entry point for the Stash plugin. Initializes queue infrastructure,
starts background worker, and handles Stash hooks.
"""

import os
import sys
import json

print("[PlexSync] Script starting...", file=sys.stderr)

# Add plugin directory to path for imports
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

print(f"[PlexSync] PLUGIN_DIR: {PLUGIN_DIR}", file=sys.stderr)

try:
    from sync_queue.manager import QueueManager
    from sync_queue.dlq import DeadLetterQueue
    from sync_queue.operations import load_sync_timestamps
    from worker.processor import SyncWorker
    from hooks.handlers import on_scene_update
    from validation.config import validate_config, PlexSyncConfig
    print("[PlexSync] All imports successful", file=sys.stderr)
except ImportError as e:
    print(f"[PlexSync] Import error: {e}", file=sys.stderr)
    import traceback
    traceback.print_exc()
    print(json.dumps({"error": str(e)}))
    sys.exit(1)

# Globals (initialized in main)
queue_manager = None
dlq = None
worker = None
config: PlexSyncConfig = None
sync_timestamps: dict = None


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


def get_stash_interface(input_data: dict):
    """
    Create StashInterface from input data.

    Returns:
        StashInterface instance or None if connection fails
    """
    try:
        from stashapi.stashapp import StashInterface
        conn = input_data.get('server_connection', {})
        if conn:
            return StashInterface(conn)
    except ImportError:
        print("[PlexSync] Warning: stashapi not installed, cannot fetch settings", file=sys.stderr)
    except Exception as e:
        print(f"[PlexSync] Warning: Could not connect to Stash: {e}", file=sys.stderr)
    return None


def fetch_plugin_settings(stash) -> dict:
    """
    Fetch PlexSync plugin settings from Stash configuration.

    Args:
        stash: StashInterface instance

    Returns:
        Dictionary with plugin settings
    """
    if not stash:
        return {}

    try:
        config = stash.get_configuration()
        plugins = config.get('plugins', {})
        return plugins.get('PlexSync', {})
    except Exception as e:
        print(f"[PlexSync] Warning: Could not fetch settings from Stash: {e}", file=sys.stderr)
        return {}


def extract_config_from_input(input_data: dict) -> dict:
    """
    Extract Plex configuration from Stash input data.

    Fetches plugin settings from Stash GraphQL API using stashapi,
    then falls back to environment variables.

    Args:
        input_data: Input data from Stash plugin protocol

    Returns:
        Dictionary with config values (may be empty if nothing found)
    """
    config_dict = {}

    # Fetch settings from Stash using stashapi
    stash = get_stash_interface(input_data)
    if stash:
        stash_settings = fetch_plugin_settings(stash)
        if stash_settings:
            print(f"[PlexSync] Loaded settings from Stash: {list(stash_settings.keys())}")
            config_dict.update(stash_settings)

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
    print("[PlexSync] initialize() called", file=sys.stderr)
    global queue_manager, dlq, worker, config, sync_timestamps

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

    print(f"[PlexSync] Validating config: {list(config_dict.keys())}", file=sys.stderr)
    try:
        validated_config, error = validate_config(config_dict)
        print(f"[PlexSync] Validation result: error={error}, config={validated_config}", file=sys.stderr)
    except Exception as e:
        print(f"[PlexSync] validate_config exception: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        raise

    if error:
        error_msg = f"PlexSync configuration error: {error}"
        print(f"[PlexSync] ERROR: {error_msg}", file=sys.stderr)
        raise SystemExit(1)

    try:
        config = validated_config
        print(f"[PlexSync] Config assigned, plex_url={config.plex_url}", file=sys.stderr)
    except Exception as e:
        print(f"[PlexSync] Config assignment exception: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        raise

    # Check if plugin is disabled
    if not config.enabled:
        print("[PlexSync] Plugin is disabled via configuration", file=sys.stderr)
        return

    print("[PlexSync] Plugin is enabled, getting data dir...", file=sys.stderr)
    data_dir = get_plugin_data_dir()
    print(f"[PlexSync] Data dir: {data_dir}", file=sys.stderr)

    # Load sync timestamps for late update detection
    print("[PlexSync] Loading sync timestamps...", file=sys.stderr)
    sync_timestamps = load_sync_timestamps(data_dir)
    print(f"[PlexSync] Loaded {len(sync_timestamps)} sync timestamps", file=sys.stderr)

    # Initialize queue infrastructure
    print("[PlexSync] Creating QueueManager...", file=sys.stderr)
    queue_manager = QueueManager(data_dir)
    print("[PlexSync] Creating DeadLetterQueue...", file=sys.stderr)
    dlq = DeadLetterQueue(data_dir)

    # Start background worker with data_dir for timestamp updates
    print("[PlexSync] Creating SyncWorker...", file=sys.stderr)
    worker = SyncWorker(
        queue_manager.get_queue(),
        dlq,
        config,
        data_dir=data_dir,
        max_retries=config.max_retries
    )
    print("[PlexSync] Starting worker...", file=sys.stderr)
    worker.start()

    print("[PlexSync] Initialization complete", file=sys.stderr)


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
    global sync_timestamps

    hook_type = hook_context.get("type", "")
    input_data = hook_context.get("input", {})

    if hook_type == "Scene.Update.Post":
        scene_id = input_data.get("id")
        if scene_id:
            data_dir = get_plugin_data_dir()
            on_scene_update(
                scene_id,
                input_data,
                queue_manager.get_queue(),
                data_dir=data_dir,
                sync_timestamps=sync_timestamps
            )
        else:
            print("[PlexSync] WARNING: Scene.Update.Post hook missing scene ID")
    else:
        print(f"[PlexSync] Unhandled hook type: {hook_type}")


def main():
    """Main entry point for Stash plugin."""
    print("[PlexSync] main() started", file=sys.stderr)

    # Read input from stdin (Stash plugin protocol)
    try:
        raw_input = sys.stdin.read()
        print(f"[PlexSync] Got raw input ({len(raw_input)} bytes)", file=sys.stderr)
        input_data = json.loads(raw_input)
        print(f"[PlexSync] Parsed JSON, keys: {list(input_data.keys())}", file=sys.stderr)
    except json.JSONDecodeError as e:
        print(f"[PlexSync] JSON decode error: {e}", file=sys.stderr)
        print(json.dumps({"error": f"Invalid JSON input: {e}"}))
        sys.exit(1)

    # Initialize on first call
    global queue_manager, config
    print(f"[PlexSync] queue_manager is None: {queue_manager is None}", file=sys.stderr)
    if queue_manager is None:
        # Extract config from Stash input
        print("[PlexSync] Extracting config...", file=sys.stderr)
        config_dict = extract_config_from_input(input_data)
        print(f"[PlexSync] Config dict keys: {list(config_dict.keys())}", file=sys.stderr)
        print("[PlexSync] Calling initialize()...", file=sys.stderr)
        initialize(config_dict)

    # Check if plugin is disabled (config may have loaded but plugin disabled)
    if config and not config.enabled:
        print(json.dumps({"output": "disabled"}))
        return

    # Handle the hook
    print(f"[PlexSync] Checking for hook: 'args' in input_data={('args' in input_data)}", file=sys.stderr)
    if "args" in input_data:
        print(f"[PlexSync] args keys: {list(input_data['args'].keys())}", file=sys.stderr)
        print(f"[PlexSync] 'hookContext' in args={('hookContext' in input_data['args'])}", file=sys.stderr)

    if "args" in input_data and "hookContext" in input_data["args"]:
        print("[PlexSync] Calling handle_hook...", file=sys.stderr)
        try:
            handle_hook(input_data["args"]["hookContext"])
            print("[PlexSync] handle_hook completed", file=sys.stderr)
        except Exception as e:
            print(f"[PlexSync] handle_hook exception: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
    else:
        print("[PlexSync] No hookContext in input, skipping", file=sys.stderr)

    # Return empty response (success)
    print("[PlexSync] Returning ok response", file=sys.stderr)
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
