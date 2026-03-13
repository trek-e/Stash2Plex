# S03: Automated Reconciliation Reporting

**Goal:** Implement automated reconciliation scheduling, configurable scope, and enhanced queue status reporting.
**Demo:** Implement automated reconciliation scheduling, configurable scope, and enhanced queue status reporting.

## Must-Haves


## Tasks

- [x] **T01: 16-automated-reconciliation-reporting 01**
  - Implement automated reconciliation scheduling, configurable scope, and enhanced queue status reporting.

Purpose: Complete the v1.4 reconciliation feature set by allowing the plugin to automatically detect and repair metadata gaps on a schedule, with startup triggers and rich status reporting.

Output: Working auto-reconciliation system that triggers on Stash startup (recent scope) and at configurable intervals (never/hourly/daily/weekly), with scope options (all/24h/7days/custom), and enhanced "View Queue Status" showing reconciliation history.
- [x] **T02: 16-automated-reconciliation-reporting 02**
  - Comprehensive test coverage for automated reconciliation scheduling, state persistence, and enhanced queue status.

Purpose: Ensure the auto-reconciliation scheduler, config validation, state persistence, and enhanced queue status reporting all work correctly and handle edge cases.

Output: Two test files covering scheduler unit tests and auto-reconciliation integration tests, maintaining 80%+ coverage.

## Files Likely Touched

- `validation/config.py`
- `Stash2Plex.yml`
- `reconciliation/scheduler.py`
- `reconciliation/__init__.py`
- `Stash2Plex.py`
- `tests/reconciliation/test_scheduler.py`
- `tests/reconciliation/test_auto_reconcile.py`
