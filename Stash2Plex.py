#!/usr/bin/env python3
"""
Stash2Plex - Stash plugin for syncing metadata to Plex

Entry point for the Stash plugin. Initializes queue infrastructure,
starts background worker, and handles Stash hooks.
"""

import os
import sys
import json
import time


from shared.log import create_logger, create_progress_logger
log_trace, log_debug, log_info, log_warn, log_error = create_logger()
log_progress = create_progress_logger()


log_trace("Script starting...")

# Add plugin directory to path for imports
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

log_trace(f"PLUGIN_DIR: {PLUGIN_DIR}")

# --- Dependency installation (driven by requirements.txt) ---
# Override map for packages where names don't follow standard conventions.
# Standard convention: import name = pip name with hyphens replaced by underscores.
# Format: requirements.txt name → (import_name, pip_install_name)
_PKG_NAMES = {
    "persist-queue": ("persistqueue", "persist-queue"),
    "stashapi": ("stashapi", "stashapp-tools"),
}


def _parse_requirements():
    """Parse requirements.txt → [(import_name, pip_spec), ...]"""
    path = os.path.join(PLUGIN_DIR, "requirements.txt")
    deps = []
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                # Split "package>=1.0.0" → base name + version specifier
                for i, ch in enumerate(line):
                    if ch in ">=<!~":
                        req_name, ver_spec = line[:i], line[i:]
                        break
                else:
                    req_name, ver_spec = line, ""
                import_name, pip_name = _PKG_NAMES.get(
                    req_name, (req_name.replace("-", "_"), req_name)
                )
                deps.append((import_name, pip_name + ver_spec))
    except FileNotFoundError:
        log_warn(f"requirements.txt not found at {path}")
    return deps


def _check_missing(deps):
    """Return deps where the module can't be imported."""
    missing = []
    for import_name, pip_spec in deps:
        try:
            __import__(import_name)
        except ImportError:
            missing.append((import_name, pip_spec))
    return missing


_required_deps = _parse_requirements()

# Step 1: Try PythonDepManager (Stash's built-in package manager)
try:
    from PythonDepManager import ensure_import
    log_trace("Installing dependencies via PythonDepManager...")
    # Build ensure_import args: "import_name:pip_spec" when names differ
    _ei_args = []
    for _imp, _pip in _required_deps:
        _pip_base = _pip
        for _ch in ">=<!~":
            _idx = _pip_base.find(_ch)
            if _idx >= 0:
                _pip_base = _pip_base[:_idx]
                break
        if _imp == _pip_base or _imp == _pip_base.replace("-", "_"):
            _ei_args.append(_pip)
        else:
            _ei_args.append(f"{_imp}:{_pip}")
    ensure_import(*_ei_args)
    log_trace("Dependencies installed via PythonDepManager")
except ImportError:
    log_trace("PythonDepManager not available")
except Exception as e:
    log_warn(f"PythonDepManager failed: {e}")

# Step 2: Verify deps and fallback to pip if any are missing
_missing = _check_missing(_required_deps)
if _missing:
    log_trace(f"Missing after PythonDepManager: {[m for m, _ in _missing]}")
    log_trace(f"Attempting pip install with: {sys.executable}")
    import subprocess
    for _mod, _pkg in _missing:
        try:
            _result = subprocess.run(
                [sys.executable, "-m", "pip", "install",
                 "--break-system-packages", _pkg],
                capture_output=True, text=True, timeout=120,
            )
            if _result.returncode == 0:
                log_trace(f"Installed {_pkg}")
            else:
                log_warn(f"pip install {_pkg} failed: {_result.stderr.strip()}")
        except Exception as e:
            log_warn(f"pip install {_pkg} failed: {e}")

# Step 3: Final verification — actionable error if still missing
_still_missing = _check_missing(_required_deps)
if _still_missing:
    _names = [m for m, _ in _still_missing]
    _pkgs = [p for _, p in _still_missing]
    _pip_cmd = f"{sys.executable} -m pip install --break-system-packages {' '.join(_pkgs)}"
    log_error(f"Missing required dependencies: {_names}")
    log_error(f"Stash is using Python: {sys.executable}")
    log_error(f"To fix, run: {_pip_cmd}")
    print(json.dumps({
        "error": f"Missing dependencies: {', '.join(_names)}. "
                 f"Install with: {_pip_cmd}"
    }))
    sys.exit(1)

try:
    from sync_queue.manager import QueueManager
    from sync_queue.dlq import DeadLetterQueue
    from sync_queue.operations import load_sync_timestamps
    from worker.processor import SyncWorker
    from hooks.handlers import on_scene_update
    from validation.config import validate_config, Stash2PlexConfig
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
config: Stash2PlexConfig = None
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
    Fetch Stash2Plex plugin settings from Stash configuration.

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
        return plugins.get('Stash2Plex', {})
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

    # Configure path obfuscation (must be before any logging that includes paths)
    from validation.obfuscation import configure_obfuscation
    configure_obfuscation(getattr(config, 'obfuscate_paths', False))

    # Log configuration summary (includes debug_logging startup warning)
    config.log_config()

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


def trigger_plex_scan_for_scene(scene_id: int, stash) -> bool:
    """
    Trigger a Plex library scan for a scene's file location.

    Args:
        scene_id: Stash scene ID
        stash: StashInterface for API calls

    Returns:
        True if scan was triggered, False otherwise
    """
    if not config or not config.trigger_plex_scan:
        return False

    libraries = config.plex_libraries
    if not libraries:
        log_warn("trigger_plex_scan enabled but plex_library not set")
        return False

    if not stash:
        log_warn("No Stash connection available for scene lookup")
        return False

    try:
        # Get scene file path
        scene = stash.find_scene(scene_id)
        if not scene:
            log_warn(f"Scene {scene_id} not found")
            return False

        files = scene.get('files', [])
        if not files:
            log_warn(f"Scene {scene_id} has no files")
            return False

        file_path = files[0].get('path')
        if not file_path:
            log_warn(f"Scene {scene_id} file has no path")
            return False

        # Get the parent directory for partial scan
        import os
        scan_path = os.path.dirname(file_path)

        # Create Plex client and trigger scan
        from plex.client import PlexClient
        plex_client = PlexClient(
            url=config.plex_url,
            token=config.plex_token,
            connect_timeout=config.plex_connect_timeout,
            read_timeout=config.plex_read_timeout
        )

        # Scan all configured libraries
        for lib_name in libraries:
            try:
                plex_client.scan_library(lib_name, path=scan_path)
                log_info(f"Triggered Plex scan of '{lib_name}' for: {scan_path}")
            except Exception as e:
                log_warn(f"Failed to scan library '{lib_name}': {e}")
        return True

    except Exception as e:
        from plex.exceptions import PlexServerDown
        if isinstance(e, PlexServerDown):
            log_warn("Plex server is down — scene queued, will sync when Plex is back")
        else:
            log_error(f"Failed to trigger Plex scan: {e}")
        return False


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

        # Check if this is an identification event (stash_ids added)
        is_identification = 'stash_ids' in input_data
        if is_identification and scene_id:
            log_debug(f"Scene {scene_id} identified via stash-box")

        if scene_id:
            data_dir = get_plugin_data_dir()
            try:
                on_scene_update(
                    scene_id,
                    input_data,
                    queue_manager.get_queue(),
                    data_dir=data_dir,
                    sync_timestamps=sync_timestamps,
                    stash=stash,
                    is_identification=is_identification
                )
                log_trace(f"on_scene_update completed for scene {scene_id}")
            except Exception as e:
                log_error(f"on_scene_update exception: {e}")
                import traceback
                traceback.print_exc()
        else:
            log_warn(f"{hook_type} hook missing scene ID")
    elif hook_type == "Scene.Create.Post":
        # Scene was just created by Stash scan
        # If trigger_plex_scan is enabled, notify Plex so it discovers the file
        if not scene_id:
            log_trace(f"Skipping {hook_type} - no scene ID")
        elif not config:
            log_trace(f"Skipping {hook_type} - config not loaded")
        elif not config.trigger_plex_scan:
            log_trace(f"Skipping {hook_type} - trigger_plex_scan disabled")
        else:
            log_info(f"New scene {scene_id} created, triggering Plex scan")
            trigger_plex_scan_for_scene(scene_id, stash)
    else:
        log_trace(f"Unhandled hook type: {hook_type}")


def handle_queue_status():
    """Display current queue and DLQ statistics."""
    try:
        data_dir = get_plugin_data_dir()
        queue_path = os.path.join(data_dir, 'queue')

        from sync_queue.operations import get_stats
        from sync_queue.dlq import DeadLetterQueue

        stats = get_stats(queue_path)
        dlq = DeadLetterQueue(data_dir)
        dlq_count = dlq.get_count()
        dlq_summary = dlq.get_error_summary()

        log_info("=== Queue Status ===")
        log_info(f"Pending: {stats['pending']}")
        log_info(f"In Progress: {stats['in_progress']}")
        log_info(f"Completed: {stats['completed']}")
        log_info(f"Failed (queue): {stats['failed']}")
        log_info(f"Dead Letter Queue: {dlq_count} items")

        if dlq_summary:
            log_info("DLQ Error Breakdown:")
            for error_type, count in dlq_summary.items():
                log_info(f"  {error_type}: {count}")

        # Reconciliation status (RPT-01)
        try:
            from reconciliation.scheduler import ReconciliationScheduler
            scheduler = ReconciliationScheduler(data_dir)
            state = scheduler.load_state()

            log_info("=== Reconciliation Status ===")
            if state.last_run_time > 0:
                import datetime
                last_run_dt = datetime.datetime.fromtimestamp(state.last_run_time)
                log_info(f"Last run: {last_run_dt.strftime('%Y-%m-%d %H:%M:%S')}")
                log_info(f"Scope: {state.last_run_scope}")
                log_info(f"Scenes checked: {state.last_scenes_checked}")
                log_info(f"Gaps found: {state.last_gaps_found}")
                if state.last_gaps_by_type:
                    log_info(f"  Empty metadata: {state.last_gaps_by_type.get('empty_metadata', 0)}")
                    log_info(f"  Stale sync: {state.last_gaps_by_type.get('stale_sync', 0)}")
                    log_info(f"  Missing from Plex: {state.last_gaps_by_type.get('missing', 0)}")
                log_info(f"Enqueued: {state.last_enqueued}")
                if state.is_startup_run:
                    log_info("(Triggered by startup)")
                log_info(f"Total reconciliation runs: {state.run_count}")
            else:
                log_info("No reconciliation runs yet")
        except Exception as e:
            log_debug(f"Failed to load reconciliation status: {e}")

    except Exception as e:
        log_error(f"Failed to get queue status: {e}")
        import traceback
        traceback.print_exc()


def handle_clear_queue():
    """Clear all pending queue items."""
    try:
        data_dir = get_plugin_data_dir()
        queue_path = os.path.join(data_dir, 'queue')

        from sync_queue.operations import get_stats, clear_pending_items

        before_stats = get_stats(queue_path)
        pending = before_stats['pending']

        if pending == 0:
            log_info("Queue is empty - nothing to clear")
            return

        log_warn(f"Clearing {pending} pending queue items...")
        deleted = clear_pending_items(queue_path)
        log_info(f"Successfully cleared {deleted} pending items from queue")

        after_stats = get_stats(queue_path)
        log_info(f"Remaining - Pending: {after_stats['pending']}, In Progress: {after_stats['in_progress']}")

    except Exception as e:
        log_error(f"Failed to clear queue: {e}")
        import traceback
        traceback.print_exc()


def handle_clear_dlq():
    """Clear all items from dead letter queue."""
    try:
        data_dir = get_plugin_data_dir()

        from sync_queue.dlq import DeadLetterQueue
        dlq = DeadLetterQueue(data_dir)

        count_before = dlq.get_count()

        if count_before == 0:
            log_info("Dead letter queue is empty - nothing to clear")
            return

        log_warn(f"Clearing {count_before} items from dead letter queue...")

        with dlq._get_connection() as conn:
            cursor = conn.execute("DELETE FROM dead_letters")
            deleted = cursor.rowcount
            conn.commit()

        log_info(f"Successfully cleared {deleted} items from DLQ")

    except Exception as e:
        log_error(f"Failed to clear DLQ: {e}")
        import traceback
        traceback.print_exc()


def handle_purge_dlq(days: int = 30):
    """Remove DLQ entries older than specified days."""
    try:
        data_dir = get_plugin_data_dir()

        from sync_queue.dlq import DeadLetterQueue
        dlq = DeadLetterQueue(data_dir)

        count_before = dlq.get_count()
        log_info(f"Purging DLQ entries older than {days} days...")

        dlq.delete_older_than(days)

        count_after = dlq.get_count()
        removed = count_before - count_after

        log_info(f"Removed {removed} old DLQ entries ({count_after} remain)")

    except Exception as e:
        log_error(f"Failed to purge old DLQ entries: {e}")
        import traceback
        traceback.print_exc()


def handle_process_queue():
    """
    Process all pending queue items until empty.

    Runs in foreground (not daemon thread), processing until queue is empty.
    Reports progress via log_progress() for Stash UI visibility.
    Respects circuit breaker - stops if Plex becomes unavailable.
    """
    global config, worker, queue_manager, dlq

    try:
        data_dir = get_plugin_data_dir()
        queue_path = os.path.join(data_dir, 'queue')

        # Stop global background worker to avoid competing for queue items
        if worker:
            worker.stop()

        # Check initial queue state
        from sync_queue.operations import get_stats, get_pending, ack_job, fail_job
        stats = get_stats(queue_path)
        total = stats['pending'] + stats['in_progress']

        if total == 0:
            log_info("Queue is empty - nothing to process")
            return

        log_info(f"Starting batch processing of {total} items...")
        log_progress(0)

        from worker.processor import SyncWorker, TransientError, PermanentError

        # Configure device identity before Plex operations
        configure_plex_device_identity(data_dir)

        # Use global queue (don't create a second QueueManager — auto_resume
        # on a second instance can steal in-flight items from the first)
        queue = queue_manager.get_queue()

        # Create worker instance for processing (NOT started as background thread)
        worker_local = SyncWorker(queue, dlq, config, data_dir=data_dir)

        processed = 0
        failed = 0
        last_error = None
        start_time = time.time()
        last_progress_time = start_time

        while True:
            # Check circuit breaker before processing
            if not worker_local.circuit_breaker.can_execute():
                cause = f" (last error: {type(last_error).__name__}: {last_error})" if last_error else ""
                log_warn(f"Circuit breaker OPEN — Plex may be unavailable{cause}")
                log_info(f"Processed {processed} items before circuit break")
                break

            # Get next job (1 second timeout to check for empty queue)
            job = get_pending(queue, timeout=1)
            if job is None:
                break  # Queue is empty

            scene_id = job.get('scene_id', '?')
            retry_count = job.get('retry_count', 0)

            try:
                worker_local._process_job(job)
                ack_job(queue, job)
                worker_local.circuit_breaker.record_success()
                processed += 1

                # Brief pause between jobs to avoid overwhelming Plex
                time.sleep(0.15)

            except TransientError as e:
                last_error = e
                worker_local.circuit_breaker.record_failure()
                log_warn(f"Scene {scene_id}: {type(e).__name__}: {e}")
                job = worker_local._prepare_for_retry(job, e)
                max_retries = worker_local._get_max_retries_for_error(e)

                if job.get('retry_count', 0) >= max_retries:
                    log_warn(f"Scene {scene_id}: max retries exceeded, moving to DLQ")
                    fail_job(queue, job)
                    dlq.add(job, e, job.get('retry_count', 0))
                    failed += 1
                else:
                    # Re-queue for retry
                    worker_local._requeue_with_metadata(job)

            except PermanentError as e:
                log_warn(f"Scene {scene_id}: permanent error: {e}")
                fail_job(queue, job)
                dlq.add(job, e, retry_count)
                failed += 1

            except Exception as e:
                last_error = e
                log_error(f"Scene {scene_id}: unexpected error: {e}")
                fail_job(queue, job)
                dlq.add(job, e, retry_count)
                failed += 1

            # Report progress every 5 items or every 10 seconds
            now = time.time()
            if processed % 5 == 0 or (now - last_progress_time) >= 10:
                progress = (processed / total) * 100 if total > 0 else 100
                remaining = queue.size
                log_progress(progress)
                elapsed = now - start_time
                rate = processed / elapsed if elapsed > 0 else 0
                log_info(f"Progress: {processed}/{total} ({progress:.0f}%), "
                        f"{remaining} remaining, {rate:.1f} items/sec")
                last_progress_time = now

        # Final summary
        elapsed = time.time() - start_time
        log_progress(100)
        log_info(f"Batch processing complete: {processed} succeeded, {failed} failed in {elapsed:.1f}s")

        # Show DLQ count if items were added
        if failed > 0:
            dlq_count = dlq.get_count()
            log_warn(f"DLQ contains {dlq_count} items requiring review")

    except Exception as e:
        log_error(f"Process queue error: {e}")
        import traceback
        traceback.print_exc()


def handle_reconcile(scope: str):
    """
    Run gap detection and enqueue discovered gaps for sync.

    Args:
        scope: "all" (all scenes) or "recent" (last 24 hours)
    """
    try:
        data_dir = get_plugin_data_dir()

        from reconciliation.engine import GapDetectionEngine, GapDetectionResult

        # Need stash and config globals
        if not stash_interface:
            log_error("No Stash connection available for reconciliation")
            return
        if not config:
            log_error("No config available for reconciliation")
            return

        # Get queue for enqueue mode
        queue = queue_manager.get_queue() if queue_manager else None
        if not queue:
            log_warn("No queue available - running in detection-only mode")

        scope_label = "all scenes" if scope == "all" else "recent scenes (last 24 hours)"
        log_info(f"Starting reconciliation: {scope_label}")

        engine = GapDetectionEngine(
            stash=stash_interface,
            config=config,
            data_dir=data_dir,
            queue=queue
        )
        result = engine.run(scope=scope)

        # Record run in scheduler state (resets auto-reconcile timer)
        from reconciliation.scheduler import ReconciliationScheduler
        scheduler = ReconciliationScheduler(data_dir)
        scheduler.record_run(result, scope=scope, is_startup=False)

        # Log progress summary (RECON-02: gap counts by type)
        log_info("=== Reconciliation Summary ===")
        log_info(f"Scenes checked: {result.scenes_checked}")
        log_info(f"Gaps found: {result.total_gaps}")
        log_info(f"  Empty metadata: {result.empty_metadata_count}")
        log_info(f"  Stale sync: {result.stale_sync_count}")
        log_info(f"  Missing from Plex: {result.missing_count}")
        if queue:
            log_info(f"Enqueued: {result.enqueued_count}")
            if result.skipped_already_queued:
                log_info(f"Skipped (already queued): {result.skipped_already_queued}")
        else:
            log_info("Detection-only mode (no items enqueued)")

        if result.errors:
            for err in result.errors:
                log_warn(f"Error during reconciliation: {err}")

    except Exception as e:
        log_error(f"Reconciliation failed: {e}")
        import traceback
        traceback.print_exc()


def maybe_check_recovery():
    """Check if recovery detection is due and run it if so.

    Called on every plugin invocation (hook or task) BEFORE maybe_auto_reconcile().
    If circuit breaker is OPEN/HALF_OPEN and check interval has elapsed, probes
    Plex health and transitions circuit breaker state based on result.

    This is a lightweight check when circuit is CLOSED (reads circuit state only).
    Only creates PlexClient and runs health check when recovery probe is actually due.
    """
    if not config or not worker:
        return

    try:
        # Quick check: if circuit is CLOSED, nothing to recover
        circuit_state = worker.circuit_breaker.state
        from worker.circuit_breaker import CircuitState
        if circuit_state == CircuitState.CLOSED:
            return

        data_dir = get_plugin_data_dir()
        from worker.recovery import RecoveryScheduler

        scheduler = RecoveryScheduler(data_dir)

        if not scheduler.should_check_recovery(circuit_state):
            return

        # Recovery probe is due - run health check
        from plex.client import PlexClient
        from plex.health import check_plex_health

        client = PlexClient(
            url=config.plex_url,
            token=config.plex_token,
            connect_timeout=5.0,
            read_timeout=5.0
        )

        is_healthy, latency_ms = check_plex_health(client, timeout=5.0)
        scheduler.record_health_check(is_healthy, latency_ms, worker.circuit_breaker)

        # Log queue drain info if recovery completed
        if is_healthy and worker.circuit_breaker.state == CircuitState.CLOSED:
            queue = queue_manager.get_queue() if queue_manager else None
            pending = queue.size if queue else 0
            if pending > 0:
                log_info(f"Queue will drain automatically ({pending} jobs pending)")

    except Exception as e:
        log_debug(f"Recovery check failed: {e}")


def maybe_auto_reconcile():
    """Check if auto-reconciliation is due and run it if so.

    Called on every plugin invocation (hook or task). Checks:
    1. If this is the first invocation since Stash startup -> run recent scope
    2. If reconcile_interval has elapsed -> run configured scope

    This is a lightweight check (reads one JSON file) that only triggers
    the heavier gap detection when reconciliation is actually due.
    """
    if not config or config.reconcile_interval == 'never':
        return

    if not stash_interface or not queue_manager:
        return

    try:
        data_dir = get_plugin_data_dir()
        from reconciliation.scheduler import ReconciliationScheduler

        scheduler = ReconciliationScheduler(data_dir)

        # Check startup trigger first (AUTO-02)
        if scheduler.is_startup_due():
            log_info("Auto-reconciliation: startup trigger (recent scenes)")
            _run_auto_reconcile(scheduler, scope="recent", is_startup=True)
            return

        # Check interval trigger (AUTO-01)
        if scheduler.is_due(config.reconcile_interval):
            # Map config scope to engine scope (AUTO-03)
            scope_map = {'all': 'all', '24h': 'recent', '7days': 'recent_7days'}
            engine_scope = scope_map.get(config.reconcile_scope, 'recent')
            log_info(f"Auto-reconciliation: interval trigger ({config.reconcile_interval}, scope: {config.reconcile_scope})")
            _run_auto_reconcile(scheduler, scope=engine_scope, is_startup=False)
            return

    except Exception as e:
        log_warn(f"Auto-reconciliation check failed: {e}")


def _run_auto_reconcile(scheduler, scope: str, is_startup: bool):
    """Execute auto-reconciliation and record results.

    Args:
        scheduler: ReconciliationScheduler instance
        scope: Engine scope ('all', 'recent', or 'recent_7days')
        is_startup: Whether triggered by startup
    """
    try:
        data_dir = get_plugin_data_dir()
        from reconciliation.engine import GapDetectionEngine

        queue = queue_manager.get_queue() if queue_manager else None

        engine = GapDetectionEngine(
            stash=stash_interface,
            config=config,
            data_dir=data_dir,
            queue=queue
        )
        result = engine.run(scope=scope)

        # Record the run
        scope_label = config.reconcile_scope if not is_startup else "recent (startup)"
        scheduler.record_run(result, scope=scope_label, is_startup=is_startup)

        log_info(f"Auto-reconciliation complete: {result.total_gaps} gaps found, {result.enqueued_count} enqueued")

    except Exception as e:
        log_warn(f"Auto-reconciliation failed: {e}")


def handle_health_check():
    """Check Plex server connectivity and circuit breaker status."""
    try:
        data_dir = get_plugin_data_dir()
        log_info("=== Plex Health Check ===")

        # Report circuit breaker state
        cb_file = os.path.join(data_dir, 'circuit_breaker.json')
        if os.path.exists(cb_file):
            try:
                with open(cb_file, 'r') as f:
                    cb_data = json.load(f)
                state = cb_data.get('state', 'closed').upper()
                log_info(f"Circuit Breaker State: {state}")

                if state == "OPEN" and cb_data.get('opened_at'):
                    opened_at = cb_data['opened_at']
                    elapsed = time.time() - opened_at
                    minutes = int(elapsed / 60)
                    seconds = int(elapsed % 60)
                    log_info(f"Circuit opened {minutes}m {seconds}s ago")
            except Exception as e:
                log_info(f"Circuit Breaker State: UNKNOWN (corrupted state file: {e})")
        else:
            log_info("Circuit Breaker State: CLOSED (no state file)")

        # Test Plex connectivity with health probe
        if not config:
            log_error("No config available for health check")
            return

        from plex.client import PlexClient
        from plex.health import check_plex_health

        client = PlexClient(
            url=config.plex_url,
            token=config.plex_token,
            connect_timeout=5.0,
            read_timeout=5.0
        )

        is_healthy, latency_ms = check_plex_health(client, timeout=5.0)

        if is_healthy:
            log_info(f"Plex is HEALTHY (responded in {latency_ms:.0f}ms)")
        else:
            log_warn("Plex is UNREACHABLE")
            log_info("Verify Plex URL and network connectivity")

        # Report queue size
        if queue_manager:
            queue = queue_manager.get_queue()
            pending = queue.size
            if pending > 0:
                log_info(f"Queue: {pending} pending items")

                # If circuit is open and jobs are waiting, warn user
                if os.path.exists(cb_file):
                    try:
                        with open(cb_file, 'r') as f:
                            cb_data = json.load(f)
                        if cb_data.get('state', 'closed').lower() == 'open':
                            log_warn(f"{pending} jobs waiting for Plex to recover")
                    except:
                        pass
            else:
                log_info("Queue: empty")

        log_info("=== Health Check Complete ===")

    except Exception as e:
        log_error(f"Health check failed: {e}")
        import traceback
        traceback.print_exc()


# Dispatch table for management modes (no Stash connection needed)
_MANAGEMENT_HANDLERS = {
    'queue_status': lambda args: handle_queue_status(),
    'clear_queue': lambda args: handle_clear_queue(),
    'clear_dlq': lambda args: handle_clear_dlq(),
    'purge_dlq': lambda args: handle_purge_dlq(args.get('days', 30)),
    'process_queue': lambda args: handle_process_queue(),
    'reconcile_all': lambda args: handle_reconcile('all'),
    'reconcile_recent': lambda args: handle_reconcile('recent'),
    'reconcile_7days': lambda args: handle_reconcile('recent_7days'),
    'health_check': lambda args: handle_health_check(),
}


def handle_task(task_args: dict, stash=None):
    """Handle manual task trigger from Stash UI.

    Args:
        task_args: Task arguments (mode determines operation)
        stash: StashInterface for API calls (required for sync modes)
    """
    mode = task_args.get('mode', 'recent')
    log_info(f"Task starting with mode: {mode}")

    handler = _MANAGEMENT_HANDLERS.get(mode)
    if handler:
        handler(task_args)
        return

    # Sync tasks require Stash connection
    handle_bulk_sync(mode, stash)


def handle_bulk_sync(mode: str, stash):
    """Batch-query scenes from Stash and enqueue them for Plex sync.

    Args:
        mode: 'all' for every scene, 'recent' for last 24 hours.
        stash: StashInterface for GQL queries.
    """
    from sync_queue.operations import enqueue, get_queued_scene_ids
    from validation.scene_extractor import extract_scene_metadata, get_scene_file_path

    if not stash:
        log_error("No Stash connection available")
        return

    try:
        scenes = _fetch_scenes_for_sync(mode, stash)
        if not scenes:
            log_info("No scenes found to sync")
            return

        log_info(f"Found {len(scenes)} scenes to sync")

        data_dir = get_plugin_data_dir()
        current_timestamps = load_sync_timestamps(data_dir)
        queue_path = os.path.join(data_dir, 'queue')
        existing_in_queue = get_queued_scene_ids(queue_path)
        if existing_in_queue:
            log_debug(f"{len(existing_in_queue)} scenes already in queue, will skip duplicates")

        queue = queue_manager.get_queue()
        queued = 0
        skipped = 0
        already_synced = 0
        already_queued = 0

        for scene in scenes:
            scene_id = scene.get('id')
            if not scene_id:
                continue

            file_path = get_scene_file_path(scene)
            if not file_path:
                skipped += 1
                continue

            if _is_already_synced(scene, int(scene_id), current_timestamps):
                already_synced += 1
                continue

            if int(scene_id) in existing_in_queue:
                already_queued += 1
                continue

            job_data = extract_scene_metadata(scene)
            job_data['path'] = file_path

            try:
                enqueue(queue, int(scene_id), "metadata", job_data)
                queued += 1
            except Exception as e:
                log_warn(f"Failed to queue scene {scene_id}: {e}")

        parts = [f"Queued {queued} scenes for sync"]
        if already_synced:
            parts.append(f"{already_synced} already synced")
        if already_queued:
            parts.append(f"{already_queued} already in queue")
        if skipped:
            parts.append(f"{skipped} without files")
        log_info(parts[0] + (" (" + ", ".join(parts[1:]) + ")" if len(parts) > 1 else ""))

    except Exception as e:
        log_error(f"Task error: {e}")
        import traceback
        traceback.print_exc()


# Batch query fragment for bulk sync — all needed fields in one call
_BATCH_FRAGMENT = """
    id
    title
    details
    date
    rating100
    updated_at
    files { path }
    studio { name }
    performers { name }
    tags { name }
    paths { screenshot preview }
"""


def _fetch_scenes_for_sync(mode: str, stash) -> list:
    """Fetch scenes from Stash based on sync mode."""
    if mode == 'all':
        log_info("Fetching all scenes...")
        return stash.find_scenes(fragment=_BATCH_FRAGMENT) or []

    import datetime
    yesterday = (datetime.datetime.now() - datetime.timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    log_info(f"Fetching scenes updated since {yesterday}...")
    return stash.find_scenes(
        f={"updated_at": {"value": yesterday, "modifier": "GREATER_THAN"}},
        fragment=_BATCH_FRAGMENT
    ) or []


def _is_already_synced(scene: dict, scene_id: int, timestamps: dict) -> bool:
    """Check if a scene was already synced since its last update."""
    scene_updated_at = scene.get('updated_at')
    if not scene_updated_at or not timestamps:
        return False
    last_synced = timestamps.get(scene_id)
    if not last_synced:
        return False
    try:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(scene_updated_at.replace('Z', '+00:00'))
        return dt.timestamp() <= last_synced
    except (ValueError, AttributeError):
        return False


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
    # Exception: Scene.Create.Post may need to trigger Plex scan even during Stash scan
    if is_hook:
        hook_context = args.get("hookContext", {})
        hook_type = hook_context.get("type", "")
        temp_stash = get_stash_interface(input_data)

        # Allow Scene.Create.Post through - it triggers Plex scan for new files
        # Allow identification events through - stash_ids in input means user identified a scene
        # Other hooks (Scene.Update.Post) are skipped during scans to avoid noise
        hook_input = hook_context.get("input") or {}
        is_identification = 'stash_ids' in hook_input
        if hook_type != "Scene.Create.Post" and not is_identification and is_scan_job_running(temp_stash):
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

    # Recovery detection (runs on every invocation, lightweight when circuit CLOSED)
    maybe_check_recovery()

    # Auto-reconciliation check (runs on every invocation, lightweight)
    maybe_auto_reconcile()

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
    # Skip for management tasks that don't enqueue work
    management_modes = {'clear_queue', 'clear_dlq', 'purge_dlq', 'queue_status', 'process_queue', 'reconcile_all', 'reconcile_recent', 'reconcile_7days', 'health_check'}
    task_mode = args.get("mode", "") if not is_hook else ""
    if worker and queue_manager and task_mode not in management_modes:
        import time
        from worker.stats import SyncStats
        queue = queue_manager.get_queue()
        data_dir = get_plugin_data_dir()

        # Load stats for dynamic timeout calculation
        stats_path = os.path.join(data_dir, 'stats.json')
        stats = SyncStats.load_from_file(stats_path)

        # Dynamic timeout based on measured processing time
        initial_size = queue.size
        max_wait = stats.get_estimated_timeout(initial_size)
        wait_interval = 0.5
        waited = 0
        last_size = initial_size

        # Determine time_per_item for messaging
        time_per_item = stats.avg_processing_time if stats.jobs_processed >= 5 else stats.DEFAULT_TIME_PER_ITEM

        if initial_size > 0:
            if stats.jobs_processed >= 5:
                log_info(f"Processing {initial_size} queued item(s), timeout {max_wait:.0f}s (based on {stats.avg_processing_time:.2f}s/item avg)")
            else:
                log_info(f"Processing {initial_size} queued item(s), timeout {max_wait:.0f}s (using default estimate)")

        while waited < max_wait:
            try:
                size = queue.size
                if size == 0:
                    break
                # Log progress every 10 items processed
                if last_size - size >= 10:
                    log_info(f"Progress: {initial_size - size}/{initial_size} processed, {size} remaining")
                    last_size = size
                time.sleep(wait_interval)
                waited += wait_interval
            except Exception as e:
                log_error(f"Error checking queue: {e}")
                break

        if waited >= max_wait and queue.size > 0:
            remaining = queue.size
            estimated_remaining_time = remaining * time_per_item
            log_warn(
                f"Timeout after {max_wait:.0f}s with {remaining} items remaining "
                f"(est. {estimated_remaining_time:.0f}s more needed). "
                f"Run 'Process Queue' task to continue without timeout limits."
            )

    # Graceful shutdown: stop worker so in-flight items are acked/nacked
    # (prevents auto_resume from re-processing them in next invocation)
    shutdown()

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
