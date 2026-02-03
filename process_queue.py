#!/usr/bin/env python3
"""
Manual queue processor for Stash2Plex.

Run this script to process all pending items in the sync queue.
Useful when the queue has stalled due to Stash plugin timeout limits.

Usage:
    python process_queue.py [--data-dir /path/to/data]
"""

import os
import sys
import json
import argparse
import logging

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger('Stash2Plex.manual')


def find_data_dir():
    """Find the Stash2Plex data directory."""
    # Common locations
    candidates = [
        '/root/.stash/plugins/Stash2Plex/data',
        '/config/plugins/Stash2Plex/data',
        os.path.expanduser('~/.stash/plugins/Stash2Plex/data'),
        './data',
    ]

    for path in candidates:
        if os.path.exists(path):
            return path

    return None


def load_config(data_dir):
    """Load Stash2Plex configuration."""
    config_path = os.path.join(os.path.dirname(data_dir), 'config.json')

    # Also check parent plugin directory
    if not os.path.exists(config_path):
        config_path = os.path.join(data_dir, '..', 'config.json')

    if os.path.exists(config_path):
        with open(config_path, 'r') as f:
            return json.load(f)

    # Try to load from environment or use defaults
    return {
        'plex_url': os.environ.get('PLEX_URL', ''),
        'plex_token': os.environ.get('PLEX_TOKEN', ''),
        'plex_library': os.environ.get('PLEX_LIBRARY', 'Movies'),
    }


def process_queue(data_dir, config):
    """Process all items in the queue."""
    # Import here to allow script to show help without dependencies
    from plex.device_identity import configure_plex_device_identity
    from sync_queue.manager import QueueManager
    from sync_queue.operations import get_stats, get_pending, ack_job, fail_job
    from worker.processor import SyncWorker
    from validation.config import Stash2PlexConfig

    # Configure device identity FIRST (before any Plex connections)
    device_id = configure_plex_device_identity(data_dir)
    logger.info(f"Using Plex device ID: {device_id[:8]}...")

    # Show queue stats
    stats = get_stats(data_dir)
    logger.info(f"Queue stats: {stats}")

    if stats.get('pending', 0) == 0 and stats.get('ready', 0) == 0:
        logger.info("Queue is empty. Nothing to process.")
        return 0

    # Validate config
    try:
        validated_config = Stash2PlexConfig(**config)
    except Exception as e:
        logger.error(f"Invalid configuration: {e}")
        logger.error("Set PLEX_URL, PLEX_TOKEN, and PLEX_LIBRARY environment variables or provide config.json")
        return 1

    # Create worker
    queue_manager = QueueManager(data_dir)
    queue = queue_manager.get_queue()

    worker = SyncWorker(
        queue=queue,
        config=validated_config,
        data_dir=data_dir,
    )

    # Process jobs until queue is empty
    processed = 0
    failed = 0

    logger.info("Starting queue processing...")

    while True:
        job = get_pending(queue, timeout=1)
        if job is None:
            break

        scene_id = job.get('scene_id', 'unknown')
        logger.info(f"Processing job for scene {scene_id}...")

        try:
            worker._process_job(job)
            ack_job(queue, job)
            processed += 1
            logger.info(f"✓ Scene {scene_id} synced successfully")
        except Exception as e:
            failed += 1
            logger.error(f"✗ Scene {scene_id} failed: {e}")
            # Let the worker handle retry logic
            try:
                worker._handle_failure(job, e)
            except Exception:
                fail_job(queue, job)

    logger.info(f"Queue processing complete. Processed: {processed}, Failed: {failed}")

    # Show final stats
    final_stats = get_stats(data_dir)
    logger.info(f"Final queue stats: {final_stats}")

    return 0 if failed == 0 else 1


def main():
    parser = argparse.ArgumentParser(description='Process Stash2Plex queue manually')
    parser.add_argument('--data-dir', '-d', help='Path to Stash2Plex data directory')
    parser.add_argument('--plex-url', help='Plex server URL (or set PLEX_URL env var)')
    parser.add_argument('--plex-token', help='Plex token (or set PLEX_TOKEN env var)')
    parser.add_argument('--plex-library', default='Movies', help='Plex library name')
    parser.add_argument('--stats-only', '-s', action='store_true', help='Only show queue stats')

    args = parser.parse_args()

    # Find data directory
    data_dir = args.data_dir or find_data_dir()
    if not data_dir:
        logger.error("Could not find Stash2Plex data directory. Use --data-dir to specify.")
        return 1

    logger.info(f"Using data directory: {data_dir}")

    # Load config
    config = load_config(data_dir)

    # Override with command line args
    if args.plex_url:
        config['plex_url'] = args.plex_url
    if args.plex_token:
        config['plex_token'] = args.plex_token
    if args.plex_library:
        config['plex_library'] = args.plex_library

    # Stats only mode
    if args.stats_only:
        from sync_queue.operations import get_stats
        stats = get_stats(data_dir)
        print(json.dumps(stats, indent=2))
        return 0

    return process_queue(data_dir, config)


if __name__ == '__main__':
    sys.exit(main())
