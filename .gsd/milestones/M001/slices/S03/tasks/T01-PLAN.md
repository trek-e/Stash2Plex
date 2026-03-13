# T01: 16-automated-reconciliation-reporting 01

**Slice:** S03 — **Milestone:** M001

## Description

Implement automated reconciliation scheduling, configurable scope, and enhanced queue status reporting.

Purpose: Complete the v1.4 reconciliation feature set by allowing the plugin to automatically detect and repair metadata gaps on a schedule, with startup triggers and rich status reporting.

Output: Working auto-reconciliation system that triggers on Stash startup (recent scope) and at configurable intervals (never/hourly/daily/weekly), with scope options (all/24h/7days/custom), and enhanced "View Queue Status" showing reconciliation history.

## Must-Haves

- [ ] "Plugin runs periodic reconciliation at configured interval (never/hourly/daily/weekly) without user action"
- [ ] "Plugin auto-triggers reconciliation on Stash startup, scoped to recent scenes only (last 24 hours)"
- [ ] "User can configure reconciliation scope with date range options (all/24h/7days/custom range)"
- [ ] "View Queue Status task displays last reconciliation run time, total gaps found, and gaps queued by type"

## Files

- `validation/config.py`
- `Stash2Plex.yml`
- `reconciliation/scheduler.py`
- `reconciliation/__init__.py`
- `Stash2Plex.py`
