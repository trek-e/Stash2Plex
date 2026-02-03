#!/usr/bin/env python3
"""
PlexSync - Stash plugin for syncing metadata to Plex

Entry point for the Stash plugin. Initializes queue infrastructure,
starts background worker, and handles Stash hooks.
"""

import os
import sys
import json


# Stash plugin log levels - prefix format: \x01 + level + \x02 + message
def log_trace(msg): print(f"\x01t\x02[PlexSync] {msg}", file=sys.stderr)
def log_debug(msg): print(f"\x01d\x02[PlexSync] {msg}", file=sys.stderr)
def log_info(msg): print(f"\x01i\x02[PlexSync] {msg}", file=sys.stderr)
def log_warn(msg): print(f"\x01w\x02[PlexSync] {msg}", file=sys.stderr)
def log_error(msg): print(f"\x01e\x02[PlexSync] {msg}", file=sys.stderr)
def log_progress(p): print(f"\x01p\x02{p}")


log_trace("Script starting...")

# Add plugin directory to path for imports
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

log_trace(f"PLUGIN_DIR: {PLUGIN_DIR}")

try:
    from sync_queue.manager import QueueManager
    from sync_queue.dlq import DeadLetterQueue
    from sync_queue.operations import load_sync_timestamps
    from worker.processor import SyncWorker
    from hooks.handlers import on_scene_update
    from validation.config import validate_config, PlexSyncConfig
    log_trace("All imports successful")
except ImportError as e:
    log_error(f"Import error: {e}")
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
stash_interface = None


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
        log_warn(" stashapi not installed, cannot fetch settings")
    except Exception as e:
        log_warn(f" Could not connect to Stash: {e}")
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
        log_warn(f" Could not fetch settings from Stash: {e}")
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
    global stash_interface
    config_dict = {}

    # Extract Stash connection info for image fetching
    server_conn = input_data.get('server_connection', {})
    if server_conn:
        scheme = server_conn.get('Scheme', server_conn.get('scheme', 'http'))
        host = server_conn.get('Host', server_conn.get('host', '127.0.0.1'))
        port = server_conn.get('Port', server_conn.get('port', 9999))
        config_dict['stash_url'] = f"{scheme}://{host}:{port}"

        # Get session cookie for authentication
        session_cookie = server_conn.get('SessionCookie', {})
        if session_cookie:
            if isinstance(session_cookie, dict):
                cookie_name = session_cookie.get('Name', 'session')
                cookie_value = session_cookie.get('Value', '')
                config_dict['stash_session_cookie'] = f"{cookie_name}={cookie_value}"
            else:
                config_dict['stash_session_cookie'] = str(session_cookie)

    # Fetch settings from Stash using stashapi
    stash = get_stash_interface(input_data)
    stash_interface = stash  # Store globally for hook handlers
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
    print("[PlexSync] initialize() called")
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

    print(f"[PlexSync] Validating config: {list(config_dict.keys())}")
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
        log_error(f" {error_msg}")
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
        log_info("Plugin is disabled via configuration")
        return

    print("[PlexSync] Plugin is enabled, getting data dir...", file=sys.stderr)
    data_dir = get_plugin_data_dir()
    print(f"[PlexSync] Data dir: {data_dir}", file=sys.stderr)

    # Load sync timestamps for late update detection
    print("[PlexSync] Loading sync timestamps...", file=sys.stderr)
    sync_timestamps = load_sync_timestamps(data_dir)
    print(f"[PlexSync] Loaded {len(sync_timestamps)} sync timestamps")

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

    log_info("Initialization complete")


def shutdown():
    """Clean shutdown of worker and queue."""
    global worker, queue_manager

    if worker:
        print("[PlexSync] Stopping worker...", file=sys.stderr)
        worker.stop()

    if queue_manager:
        print("[PlexSync] Shutting down queue...", file=sys.stderr)
        queue_manager.shutdown()

    print("[PlexSync] Shutdown complete", file=sys.stderr)


def handle_hook(hook_context: dict, stash=None):
    """
    Handle incoming Stash hook.

    Expected hook_context structure:
    {
        "type": "Scene.Update.Post",
        "input": {...scene update data...}
    }

    Args:
        hook_context: Hook context from Stash
        stash: StashInterface for API calls
    """
    global sync_timestamps

    print(f"[PlexSync] handle_hook called with keys: {list(hook_context.keys())}", file=sys.stderr)
    hook_type = hook_context.get("type", "")
    input_data = hook_context.get("input") or {}  # Handle None explicitly
    print(f"[PlexSync] hook_type={hook_type}, input_data keys={list(input_data.keys()) if input_data else 'None'}", file=sys.stderr)

    if hook_type in ("Scene.Update.Post", "Scene.Create.Post"):
        scene_id = input_data.get("id")
        print(f"[PlexSync] {hook_type}: scene_id={scene_id}", file=sys.stderr)
        if scene_id:
            data_dir = get_plugin_data_dir()
            print(f"[PlexSync] Calling on_scene_update for scene {scene_id}...", file=sys.stderr)
            try:
                on_scene_update(
                    scene_id,
                    input_data,
                    queue_manager.get_queue(),
                    data_dir=data_dir,
                    sync_timestamps=sync_timestamps,
                    stash=stash
                )
                print(f"[PlexSync] on_scene_update completed for scene {scene_id}", file=sys.stderr)
            except Exception as e:
                print(f"[PlexSync] on_scene_update exception: {e}", file=sys.stderr)
                import traceback
                traceback.print_exc()
        else:
            log_warn(f" {hook_type} hook missing scene ID")
    else:
        print(f"[PlexSync] Unhandled hook type: {hook_type}", file=sys.stderr)


def handle_task(task_args: dict, stash=None):
    """
    Handle manual task trigger from Stash UI.

    Args:
        task_args: Task arguments (mode: 'all' or 'recent')
        stash: StashInterface for API calls
    """
    mode = task_args.get('mode', 'recent')
    print(f"[PlexSync Task] Starting task with mode: {mode}")

    if not stash:
        print("[PlexSync Task] ERROR: No Stash connection available")
        return

    try:
        # Query scenes based on mode
        if mode == 'all':
            print("[PlexSync Task] Fetching all scenes...")
            scenes = stash.find_scenes(fragment="id")
        else:  # recent - last 24 hours
            import datetime
            yesterday = (datetime.datetime.now() - datetime.timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
            print(f"[PlexSync Task] Fetching scenes updated since {yesterday}...")
            scenes = stash.find_scenes(
                f={"updated_at": {"value": yesterday, "modifier": "GREATER_THAN"}},
                fragment="id"
            )

        if not scenes:
            print("[PlexSync Task] No scenes found to sync")
            return

        print(f"[PlexSync Task] Found {len(scenes)} scenes to sync")

        # Queue each scene for sync
        data_dir = get_plugin_data_dir()
        queued = 0
        for scene in scenes:
            scene_id = scene.get('id')
            if scene_id:
                try:
                    on_scene_update(
                        int(scene_id),
                        {'id': scene_id},
                        queue_manager.get_queue(),
                        data_dir=data_dir,
                        sync_timestamps=None,  # Force sync, ignore timestamps
                        stash=stash
                    )
                    queued += 1
                except Exception as e:
                    print(f"[PlexSync Task] Failed to queue scene {scene_id}: {e}")

        print(f"[PlexSync Task] Queued {queued} scenes for sync")

    except Exception as e:
        print(f"[PlexSync Task] ERROR: {e}")
        import traceback
        traceback.print_exc()


def main():
    """Main entry point for Stash plugin."""
    print("[PlexSync] main() started")

    # Read input from stdin (Stash plugin protocol)
    try:
        raw_input = sys.stdin.read()
        print(f"[PlexSync] Got raw input ({len(raw_input)} bytes)")
        input_data = json.loads(raw_input)
        print(f"[PlexSync] Parsed JSON, keys: {list(input_data.keys())}")
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
        print(f"[PlexSync] Config dict keys: {list(config_dict.keys())}")
        print("[PlexSync] Calling initialize()...")
        initialize(config_dict)

    # Check if plugin is disabled (config may have loaded but plugin disabled)
    if config and not config.enabled:
        print(json.dumps({"output": "disabled"}))
        return

    # Handle hook or task
    args = input_data.get("args", {})

    if "hookContext" in args:
        # Hook triggered
        print("[PlexSync] Calling handle_hook...", file=sys.stderr)
        try:
            handle_hook(args["hookContext"], stash=stash_interface)
            print("[PlexSync] handle_hook completed", file=sys.stderr)
        except Exception as e:
            print(f"[PlexSync] handle_hook exception: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
    elif "mode" in args:
        # Task triggered (has mode argument)
        print("[PlexSync] Calling handle_task...", file=sys.stderr)
        try:
            handle_task(args, stash=stash_interface)
            print("[PlexSync] handle_task completed", file=sys.stderr)
        except Exception as e:
            print(f"[PlexSync] handle_task exception: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
    else:
        print("[PlexSync] No hookContext or task mode in input, skipping", file=sys.stderr)

    # Give worker time to process pending jobs before exiting
    # Worker thread is daemon, so it dies when main process exits
    if worker and queue_manager:
        import time
        queue = queue_manager.get_queue()
        # Wait up to 30 seconds for queue to drain
        max_wait = 30
        wait_interval = 0.5
        waited = 0
        last_logged_size = -1
        while waited < max_wait:
            try:
                # Check if queue has pending items
                size = queue.size
                if size == 0:
                    break
                # Only log on first check or if queue is growing (backlog)
                if last_logged_size == -1:
                    print(f"[PlexSync] Processing {size} queued item(s)...")
                elif size > last_logged_size:
                    print(f"[PlexSync] Queue backlog: {size} items", file=sys.stderr)
                last_logged_size = size
                time.sleep(wait_interval)
                waited += wait_interval
            except Exception as e:
                print(f"[PlexSync] Error checking queue: {e}", file=sys.stderr)
                break
        if waited >= max_wait:
            print(f"[PlexSync] Timeout waiting for queue ({queue.size} items remaining)")

    # Return empty response (success)
    print("[PlexSync] Returning ok response", file=sys.stderr)
    print(json.dumps({"output": "ok"}))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[PlexSync] Interrupted by user", file=sys.stderr)
        shutdown()
        sys.exit(0)
    except Exception as e:
        import traceback
        print(json.dumps({"error": str(e)}))
        traceback.print_exc()
        shutdown()
        sys.exit(1)
