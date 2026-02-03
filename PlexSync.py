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
    from plex.device_identity import configure_plex_device_identity
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
            log_trace(f"Loaded settings from Stash: {list(stash_settings.keys())}")
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
    log_trace("initialize() called")
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

    log_trace(f"Validating config: {list(config_dict.keys())}")
    try:
        validated_config, error = validate_config(config_dict)
    except Exception as e:
        log_error(f"validate_config exception: {e}")
        import traceback
        traceback.print_exc()
        raise

    if error:
        log_error(f"Configuration error: {error}")
        raise SystemExit(1)

    config = validated_config

    # Check if plugin is disabled
    if not config.enabled:
        log_info("Plugin is disabled via configuration")
        return

    data_dir = get_plugin_data_dir()

    # Configure persistent Plex device identity (must be before PlexClient creation)
    device_id = configure_plex_device_identity(data_dir)
    log_trace(f"Using Plex device ID: {device_id[:8]}...")

    # Load sync timestamps for late update detection
    sync_timestamps = load_sync_timestamps(data_dir)
    log_trace(f"Loaded {len(sync_timestamps)} sync timestamps")

    # Initialize queue infrastructure
    queue_manager = QueueManager(data_dir)
    dlq = DeadLetterQueue(data_dir)

    # Start background worker with data_dir for timestamp updates
    worker = SyncWorker(
        queue_manager.get_queue(),
        dlq,
        config,
        data_dir=data_dir,
        max_retries=config.max_retries
    )
    worker.start()

    log_info("Initialization complete")


def shutdown():
    """Clean shutdown of worker and queue."""
    global worker, queue_manager

    if worker:
        worker.stop()

    if queue_manager:
        queue_manager.shutdown()

    log_trace("Shutdown complete")


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

    hook_type = hook_context.get("type", "")
    # Scene ID is at top level of hookContext, not inside input
    scene_id = hook_context.get("id")
    input_data = hook_context.get("input") or {}

    log_trace(f"handle_hook: type={hook_type}, scene_id={scene_id}")

    # Only process Scene.Update.Post with actual user input
    # Scene.Create.Post is typically from scans - skip those
    # Empty input means scan-triggered update, not user edit
    if hook_type == "Scene.Update.Post":
        if not input_data:
            log_trace(f"Skipping {hook_type} - no input data (likely scan)")
            return

        if scene_id:
            data_dir = get_plugin_data_dir()
            try:
                on_scene_update(
                    scene_id,
                    input_data,
                    queue_manager.get_queue(),
                    data_dir=data_dir,
                    sync_timestamps=sync_timestamps,
                    stash=stash
                )
                log_trace(f"on_scene_update completed for scene {scene_id}")
            except Exception as e:
                log_error(f"on_scene_update exception: {e}")
                import traceback
                traceback.print_exc()
        else:
            log_warn(f"{hook_type} hook missing scene ID")
    elif hook_type == "Scene.Create.Post":
        log_trace(f"Skipping {hook_type} - scene creation from scan")
    else:
        log_trace(f"Unhandled hook type: {hook_type}")


def handle_task(task_args: dict, stash=None):
    """
    Handle manual task trigger from Stash UI.

    Args:
        task_args: Task arguments (mode: 'all' or 'recent')
        stash: StashInterface for API calls
    """
    mode = task_args.get('mode', 'recent')
    log_info(f"Task starting with mode: {mode}")

    if not stash:
        log_error("No Stash connection available")
        return

    try:
        # Query scenes based on mode
        if mode == 'all':
            log_info("Fetching all scenes...")
            scenes = stash.find_scenes(fragment="id")
        else:  # recent - last 24 hours
            import datetime
            yesterday = (datetime.datetime.now() - datetime.timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
            log_info(f"Fetching scenes updated since {yesterday}...")
            scenes = stash.find_scenes(
                f={"updated_at": {"value": yesterday, "modifier": "GREATER_THAN"}},
                fragment="id"
            )

        if not scenes:
            log_info("No scenes found to sync")
            return

        log_info(f"Found {len(scenes)} scenes to sync")

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
                    log_warn(f"Failed to queue scene {scene_id}: {e}")

        log_info(f"Queued {queued} scenes for sync")

    except Exception as e:
        log_error(f"Task error: {e}")
        import traceback
        traceback.print_exc()


def is_scan_job_running(stash) -> bool:
    """Check if a scan/generate job is running in Stash."""
    if not stash:
        return False
    try:
        # Stash Job type has: id, status, subTasks, description, progress, startTime, endTime, addTime
        result = stash.call_GQL("""
            query { jobQueue { status description } }
        """)
        jobs = result.get('jobQueue', []) if result else []
        # Check description for scan-related keywords
        scan_keywords = ['scan', 'auto tag', 'generate', 'identify']
        for job in jobs:
            status = (job.get('status') or '').upper()
            description = (job.get('description') or '').lower()
            if status in ('RUNNING', 'READY') and any(kw in description for kw in scan_keywords):
                return True
    except Exception:
        pass
    return False


def main():
    """Main entry point for Stash plugin."""
    # Read input from stdin (Stash plugin protocol)
    try:
        raw_input = sys.stdin.read()
        input_data = json.loads(raw_input)
    except json.JSONDecodeError as e:
        log_error(f"JSON decode error: {e}")
        print(json.dumps({"error": f"Invalid JSON input: {e}"}))
        sys.exit(1)

    # Check args first - for hooks, check if scan is running before heavy init
    args = input_data.get("args", {})
    is_hook = "hookContext" in args

    # For hooks: create minimal stash connection to check for scans
    if is_hook:
        temp_stash = get_stash_interface(input_data)
        if is_scan_job_running(temp_stash):
            # Scan running - exit immediately without initialization
            print(json.dumps({"output": "ok"}))
            return

    # Initialize on first call
    global queue_manager, config
    if queue_manager is None:
        config_dict = extract_config_from_input(input_data)
        initialize(config_dict)

    # Check if plugin is disabled (config may have loaded but plugin disabled)
    if config and not config.enabled:
        print(json.dumps({"output": "disabled"}))
        return

    # Handle hook or task
    if is_hook:
        try:
            handle_hook(args["hookContext"], stash=stash_interface)
        except Exception as e:
            log_error(f"handle_hook exception: {e}")
            import traceback
            traceback.print_exc()
    elif "mode" in args:
        try:
            handle_task(args, stash=stash_interface)
        except Exception as e:
            log_error(f"handle_task exception: {e}")
            import traceback
            traceback.print_exc()

    # Give worker time to process pending jobs before exiting
    # Worker thread is daemon, so it dies when main process exits
    if worker and queue_manager:
        import time
        queue = queue_manager.get_queue()
        # Wait up to 30 seconds for queue to drain
        max_wait = 30
        wait_interval = 0.5
        waited = 0
        while waited < max_wait:
            try:
                size = queue.size
                if size == 0:
                    break
                if waited == 0:
                    log_info(f"Processing {size} queued item(s)...")
                time.sleep(wait_interval)
                waited += wait_interval
            except Exception as e:
                log_error(f"Error checking queue: {e}")
                break
        if waited >= max_wait:
            log_warn(f"Timeout waiting for queue ({queue.size} items remaining)")

    # Return empty response (success)
    print(json.dumps({"output": "ok"}))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        shutdown()
        sys.exit(0)
    except Exception as e:
        import traceback
        print(json.dumps({"error": str(e)}))
        traceback.print_exc()
        shutdown()
        sys.exit(1)
