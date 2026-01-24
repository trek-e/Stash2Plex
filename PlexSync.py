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

# Globals (initialized in main)
queue_manager = None
dlq = None
worker = None


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


def initialize():
    """Initialize queue, DLQ, and worker."""
    global queue_manager, dlq, worker

    data_dir = get_plugin_data_dir()
    print(f"[PlexSync] Initializing with data directory: {data_dir}")

    # Initialize queue infrastructure
    queue_manager = QueueManager(data_dir)
    dlq = DeadLetterQueue(data_dir)

    # Start background worker
    worker = SyncWorker(queue_manager.get_queue(), dlq)
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
    global queue_manager
    if queue_manager is None:
        initialize()

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
