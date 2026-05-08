"""
Reconciliation runner — single seam for the run-record-log lifecycle.

Both handle_reconcile (manual task) and maybe_auto_reconcile (auto trigger)
delegate here instead of wiring GapDetectionEngine + ReconciliationScheduler
themselves. The three-step dance lives in exactly one place.
"""

from typing import TYPE_CHECKING

from reconciliation.engine import GapDetectionEngine, GapDetectionResult
from reconciliation.scheduler import ReconciliationScheduler
from shared.log import create_logger

_, log_debug, log_info, log_warn, _ = create_logger("Reconciliation")

if TYPE_CHECKING:
    pass


_SCOPE_LABELS = {
    "all": "all scenes",
    "recent": "scenes added in last 24 hours",
    "recent_7days": "scenes added in last 7 days",
    "missing_metadata": "scenes with missing Plex metadata (all scenes)",
}


class ReconciliationRunner:
    """Single seam for reconciliation: detect gaps, record run, log summary.

    Owns the three-step lifecycle shared by the manual task handler and
    the auto-reconcile trigger:
        1. GapDetectionEngine.run(scope) — detect and enqueue gaps
        2. ReconciliationScheduler.record_run() — persist state for next trigger check
        3. Log the full result breakdown

    Args:
        stash: StashInterface instance for GQL queries
        config: Stash2PlexConfig with Plex connection details
        data_dir: Plugin data directory (for queue, sync timestamps, scheduler state)
        queue_manager: QueueManager instance, or None for detection-only mode
    """

    def __init__(self, stash, config, data_dir: str, queue_manager=None):
        self.stash = stash
        self.config = config
        self.data_dir = data_dir
        self.queue_manager = queue_manager

    def run(self, scope: str, is_startup: bool = False) -> GapDetectionResult:
        """Run gap detection, record state, and log the summary.

        Args:
            scope: Engine scope — "all", "recent", or "recent_7days"
            is_startup: True when triggered by startup auto-reconcile

        Returns:
            GapDetectionResult with counts and any non-fatal errors
        """
        engine = GapDetectionEngine(
            stash=self.stash,
            config=self.config,
            data_dir=self.data_dir,
            queue_manager=self.queue_manager,
        )
        result = engine.run(scope=scope)

        scope_label = _SCOPE_LABELS.get(scope, scope)
        if is_startup:
            scope_label = f"{scope_label} (startup)"

        scheduler = ReconciliationScheduler(self.data_dir)
        scheduler.record_run(result, scope=scope_label, is_startup=is_startup)

        self._log_result(result)
        return result

    def _log_result(self, result: GapDetectionResult) -> None:
        """Log the full reconciliation summary breakdown."""
        log_info("=== Reconciliation Summary ===")
        log_info(f"Scenes checked: {result.scenes_checked}")
        log_info(f"Gaps found: {result.total_gaps}")
        log_info(f"  Empty metadata: {result.empty_metadata_count}")
        log_info(f"  Stale sync: {result.stale_sync_count}")
        log_info(f"  Missing from Plex: {result.missing_count}")

        if self.queue_manager is not None:
            log_info(f"Enqueued: {result.enqueued_count}")
            if result.skipped_already_queued:
                log_info(f"Skipped (already queued): {result.skipped_already_queued}")
            if result.skipped_no_metadata:
                log_info(f"Skipped (no Stash metadata yet): {result.skipped_no_metadata}")
                log_info("  Add studio, performers, tags, date, or details in Stash to allow sync")
        else:
            log_info("Detection-only mode (no items enqueued)")

        for err in result.errors:
            log_warn(f"Error during reconciliation: {err}")


__all__ = ['ReconciliationRunner']
