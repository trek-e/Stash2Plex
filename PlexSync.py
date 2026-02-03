#!/usr/bin/env python3
"""
PlexSync - Stash plugin for syncing metadata to Plex

Entry point for the Stash plugin. Initializes queue infrastructure,
starts background worker, and handles Stash hooks.
"""

import os
import sys
import json
import urllib.request
import urllib.error

# Add plugin directory to path for imports
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

from queue.manager import QueueManager
from queue.dlq import DeadLetterQueue
from queue.operations import load_sync_timestamps
from worker.processor import SyncWorker
from hooks.handlers import on_scene_update
from validation.config import validate_config, PlexSyncConfig

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


def get_stash_connection(input_data: dict) -> tuple:
    """
    Extract Stash server connection details from input data.

    Returns:
        Tuple of (base_url, session_cookie, api_key) or (None, None, None) if not found
    """
    conn = input_data.get('server_connection', {})

    scheme = conn.get('Scheme', 'http')
    host = conn.get('Host', 'localhost')
    port = conn.get('Port', 9999)
    session_cookie = conn.get('SessionCookie', {})
    api_key = conn.get('ApiKey', '')

    base_url = f"{scheme}://{host}:{port}"
    return base_url, session_cookie, api_key


def fetch_plugin_settings(base_url: str, session_cookie: dict, api_key: str) -> dict:
    """
    Fetch PlexSync plugin settings from Stash GraphQL API.

    Args:
        base_url: Stash server base URL
        session_cookie: Session cookie dict from Stash
        api_key: Stash API key

    Returns:
        Dictionary with plugin settings
    """
    query = """
    query Configuration {
        configuration {
            plugins
        }
    }
    """

    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }

    # Try multiple auth methods
    if api_key:
        headers['ApiKey'] = api_key
    if session_cookie:
        # Build cookie header from session cookie dict
        if isinstance(session_cookie, dict):
            cookie_parts = [f"{k}={v}" for k, v in session_cookie.items()]
            if cookie_parts:
                headers['Cookie'] = '; '.join(cookie_parts)
        elif isinstance(session_cookie, str):
            headers['Cookie'] = session_cookie

    data = json.dumps({'query': query}).encode('utf-8')
    req = urllib.request.Request(
        f"{base_url}/graphql",
        data=data,
        headers=headers,
        method='POST'
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            result = json.loads(response.read().decode('utf-8'))
            plugins = result.get('data', {}).get('configuration', {}).get('plugins', {})
            return plugins.get('PlexSync', {})
    except (urllib.error.URLError, json.JSONDecodeError) as e:
        print(f"[PlexSync] Warning: Could not fetch settings from Stash: {e}", file=sys.stderr)
        return {}


def extract_config_from_input(input_data: dict) -> dict:
    """
    Extract Plex configuration from Stash input data.

    Fetches plugin settings from Stash GraphQL API, then falls back
    to environment variables.

    Args:
        input_data: Input data from Stash plugin protocol

    Returns:
        Dictionary with config values (may be empty if nothing found)
    """
    config_dict = {}

    # Debug: log what we received from Stash
    conn = input_data.get('server_connection', {})
    print(f"[PlexSync] DEBUG: server_connection keys: {list(conn.keys())}", file=sys.stderr)

    # Fetch settings from Stash GraphQL API
    base_url, session_cookie, api_key = get_stash_connection(input_data)
    print(f"[PlexSync] DEBUG: base_url={base_url}, has_cookie={bool(session_cookie)}, has_api_key={bool(api_key)}", file=sys.stderr)
    if base_url:
        stash_settings = fetch_plugin_settings(base_url, session_cookie, api_key)
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

    # Load sync timestamps for late update detection
    sync_timestamps = load_sync_timestamps(data_dir)
    print(f"[PlexSync] Loaded {len(sync_timestamps)} sync timestamps")

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
