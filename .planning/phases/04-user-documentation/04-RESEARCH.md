# Phase 4: User Documentation - Research

**Researched:** 2026-02-03
**Domain:** Documentation of existing PlexSync codebase
**Confidence:** HIGH (documentation derived from actual source code analysis)

## Summary

This research analyzed the PlexSync codebase to extract all information needed for comprehensive user documentation. The primary sources were the actual Python source files, configuration models, and plugin manifests.

Key findings include:
- 17 configurable settings (10 in Stash UI via PlexSync.yml, 7 internal/code-only)
- Installation requires PythonDepManager Stash plugin and 5 Python dependencies
- Queue system uses SQLite-backed persistence with sophisticated retry logic
- Clear error classification between transient (retry) and permanent (DLQ) failures

**Primary recommendation:** Structure documentation as README.md (quick start) + docs/ folder (detailed guides: install.md, config.md, troubleshoot.md), extracting exact configuration values and error messages from source code.

## Configuration Reference (Extracted from Source)

### User-Configurable Settings (PlexSync.yml)

Settings exposed in Stash UI plugin configuration:

| Setting | Type | Default | Description | When to Change |
|---------|------|---------|-------------|----------------|
| `plex_url` | STRING | (required) | Plex server URL (e.g., `http://localhost:32400`) | Always set - your Plex server address |
| `plex_token` | STRING | (required) | Plex authentication token (X-Plex-Token) | Always set - get from Plex settings |
| `plex_library` | STRING | (empty) | Name of Plex library to sync (e.g., "Adult") | Set to speed up search; empty searches all |
| `enabled` | BOOLEAN | true | Enable or disable the plugin | Set false to pause syncing |
| `max_retries` | NUMBER | 5 | Max retry attempts for failed syncs (1-20) | Increase if network is flaky |
| `poll_interval` | NUMBER | 30 | Seconds between queue polls | Lower for faster processing |
| `strict_matching` | BOOLEAN | true | Skip sync when multiple Plex matches found | Set false to sync first match anyway |
| `preserve_plex_edits` | BOOLEAN | false | Skip fields that already have values in Plex | Set true to keep manual Plex edits |
| `connect_timeout` | NUMBER | 5 | Plex connection timeout in seconds (1-30) | Increase on slow networks |
| `read_timeout` | NUMBER | 30 | Plex read timeout in seconds (5-120) | Increase for large libraries |

### Code-Level Configuration (PlexSyncConfig model in validation/config.py)

Additional settings validated by Pydantic but not in Stash UI:

| Setting | Type | Default | Range | Description |
|---------|------|---------|-------|-------------|
| `strict_mode` | bool | False | - | Reject invalid metadata vs sanitize and continue |
| `dlq_retention_days` | int | 30 | 1-365 | Days to keep failed jobs in DLQ |
| `stash_url` | str | None | - | Auto-extracted from Stash connection |
| `stash_api_key` | str | None | - | Stash API key for authenticated image fetching |
| `stash_session_cookie` | str | None | - | Stash session cookie for authentication |

### Validation Rules (from PlexSyncConfig)

- `plex_url`: Must start with `http://` or `https://`, trailing slash removed
- `plex_token`: Minimum 10 characters
- `max_retries`: Range 1-20
- `poll_interval`: Range 0.1-60.0 seconds
- `connect_timeout`: Range 1.0-30.0 seconds
- `read_timeout`: Range 5.0-120.0 seconds

## Installation Requirements

### Plugin Manifest (index.yml)

```yaml
- id: PlexSync
  name: PlexSync
  metadata:
    description: Sync metadata from Stash to Plex with queue-based reliability
  version: 1.0.9-1252ca9
  requires:
    - PythonDepManager  # Required for auto-installing Python dependencies
```

### Python Dependencies (requirements.txt)

```
persist-queue>=1.1.0    # SQLite-backed persistent queue
stashapi                # Stash GraphQL API client
plexapi>=4.17.0         # Plex API client
tenacity>=9.0.0         # Retry library with backoff
pydantic>=2.0.0         # Data validation
```

### Plugin Structure

```
PlexSync/
  PlexSync.py           # Main entry point
  PlexSync.yml          # Plugin manifest with hooks/settings
  requirements.txt      # Python dependencies (installed by PythonDepManager)
  hooks/                # Event handlers
  plex/                 # Plex API wrapper
  sync_queue/           # Persistent queue system
  validation/           # Config and metadata validation
  worker/               # Background job processor
  data/                 # Runtime data (queue, DLQ, timestamps)
    queue/              # Persistent queue SQLite database
    dlq.db              # Dead letter queue database
    sync_timestamps.json  # Last sync times per scene
    device_id.json      # Persistent Plex device identity
```

### Plugin Hooks (PlexSync.yml)

- `Scene.Update.Post` - Triggers sync when a scene is manually updated

### Plugin Tasks (PlexSync.yml)

- `Sync All Scenes to Plex` - Force sync all scenes (use sparingly)
- `Sync Recent Scenes to Plex` - Sync scenes updated in last 24 hours

## System Architecture (for Troubleshooting Docs)

### Processing Flow

1. **Hook Handler** (hooks/handlers.py)
   - Receives `Scene.Update.Post` event from Stash
   - Filters non-metadata updates (play counts, etc.)
   - Checks for duplicate pending jobs
   - Compares timestamps to avoid re-syncing unchanged scenes
   - Fetches full scene metadata from Stash GraphQL
   - Validates and sanitizes metadata
   - Enqueues job to persistent queue
   - Target: <100ms execution time

2. **Queue Manager** (sync_queue/manager.py)
   - SQLite-backed persistent queue via `persist-queue`
   - Survives process restarts with `auto_resume=True`
   - Jobs stored as dicts with: `scene_id`, `update_type`, `data`, `enqueued_at`, `job_key`

3. **Background Worker** (worker/processor.py)
   - Polls queue on background daemon thread
   - Processes jobs with acknowledgment workflow:
     - Success: `ack_job` - removes from queue
     - Transient failure: `nack_job` - returns to queue with backoff metadata
     - Permanent failure: `fail_job` + add to DLQ

4. **Retry System** (worker/backoff.py)
   - Exponential backoff with full jitter
   - Standard errors: base=5s, cap=80s, max_retries=5
   - PlexNotFound errors: base=30s, cap=600s, max_retries=12 (~2 hour window for library scanning)

5. **Circuit Breaker** (worker/circuit_breaker.py)
   - Pauses processing during Plex outages
   - Opens after 5 consecutive failures
   - Recovery timeout: 60 seconds
   - States: CLOSED -> OPEN -> HALF_OPEN -> CLOSED

6. **Dead Letter Queue** (sync_queue/dlq.py)
   - SQLite database storing permanently failed jobs
   - Stores: job_data, error_type, error_message, stack_trace, retry_count, failed_at
   - Auto-cleanup of entries older than `dlq_retention_days`

### Plex Matching Algorithm (plex/matcher.py)

1. **Fast Path**: Title search derived from filename, then verify by filename match
2. **Slow Fallback**: Scan all library items if title search fails
3. **Confidence Scoring**:
   - HIGH: Single unique match - auto-sync safe
   - LOW: Multiple candidates - skipped if `strict_matching=true`

## Error Classification

### Transient Errors (Will Retry)

From `validation/errors.py` and `plex/exceptions.py`:

| Error Type | HTTP Codes | Description |
|------------|------------|-------------|
| Network errors | - | ConnectionError, TimeoutError, OSError |
| Rate limiting | 429 | Too many requests |
| Server errors | 500, 502, 503, 504 | Plex server issues |
| PlexNotFound | 404 | Item not found (may appear after library scan) |

### Permanent Errors (Goes to DLQ)

| Error Type | HTTP Codes | Description |
|------------|------------|-------------|
| Auth failure | 401 | Invalid Plex token |
| Permission denied | 403 | Forbidden |
| Bad request | 400 | Malformed request |
| Validation errors | - | ValueError, TypeError, KeyError, AttributeError |
| Low confidence match | - | Multiple Plex matches with strict_matching=true |
| Missing file path | - | Scene has no associated file |

## Log Output Examples

### Log Level Prefixes (Stash plugin format)

PlexSync uses Stash plugin log format: `\x01{level}\x02[Component] message`
- `t` = Trace (detailed debug)
- `d` = Debug
- `i` = Info
- `w` = Warning
- `e` = Error

### Success Flow Logs

```
[PlexSync] Initialization complete
[PlexSync Hook] Enqueued sync job for scene 123 in 45.2ms
[PlexSync Worker] Processing job 456 for scene 123 (attempt 1)
[PlexSync Matcher] Searching 'Adult' for: Scene Name - 2026-01-30.mp4
[PlexSync Matcher] Title search: 'Scene Name'
[PlexSync Matcher] Got 1 title matches
[PlexSync Matcher] Found: Scene Name
[PlexSync Worker] Updated metadata (overwrite mode): Scene Name
[PlexSync Worker] Added 2 performers: ['Performer A', 'Performer B']
[PlexSync Worker] Job 456 completed
```

### Transient Error Logs (Retry)

```
[PlexSync Worker] Job 456 failed (attempt 1/5), retry in 3.2s: Connection error: [Errno 111] Connection refused
[PlexSync Worker] Job 456 failed (attempt 2/5), retry in 7.8s: Connection error: [Errno 111] Connection refused
[PlexSync Worker] Circuit breaker OPENED - pausing processing
```

### Permanent Error Logs (DLQ)

```
[PlexSync Worker] Job 456 permanent failure, moving to DLQ: Authentication failed: Unauthorized
[PlexSync Worker] Job 456 exceeded max retries (5), moving to DLQ
[PlexSync Worker] DLQ contains 3 failed jobs requiring review
```

### Common Warning Logs

```
[PlexSync Hook] Scene 123 update filtered (no metadata changes)
[PlexSync Hook] Scene 123 already synced (Stash: 1706900000 <= Last: 1706899000)
[PlexSync Hook] Hook handler exceeded 100ms target (156.3ms)
[PlexSync] Searching all 5 libraries (set plex_library to speed up)
[PlexSync Matcher] LOW confidence match for 'filename.mp4': 3 candidates found
[PlexSync Worker] Failed to upload poster: [Error details]
```

### Configuration Error Logs

```
[PlexSync] Configuration error: plex_url: plex_url must start with http:// or https://
[PlexSync] Configuration error: plex_token: plex_token is required
[PlexSync] Plugin is disabled via configuration
```

## Docker vs Bare Metal Differences

### Path Mapping Considerations

PlexSync matches Plex items by file path. Docker deployments often have different path mappings:

| Component | Example Path (Bare Metal) | Example Path (Docker) |
|-----------|--------------------------|----------------------|
| Stash media | `/mnt/media/videos/` | `/data/videos/` |
| Plex media | `/mnt/media/videos/` | `/media/videos/` |

**Key Point**: The file path stored in Stash must match how Plex sees the file. If paths differ between Stash and Plex containers, matching will fail.

### Data Directory Locations

| Environment | Data Directory |
|-------------|----------------|
| Bare metal | `~/.stash/plugins/PlexSync/data/` |
| Docker (Stash) | `/root/.stash/plugins/PlexSync/data/` |
| Docker (custom) | `/config/plugins/PlexSync/data/` |

The data directory can be overridden via `STASH_PLUGIN_DATA` environment variable.

### Network Considerations

- Docker: Use container names or `host.docker.internal` for Plex URL
- Bare metal: Use localhost or actual IP address
- Both: Ensure Plex token is valid for the deployment context

## Example Configurations

### Basic Configuration

```yaml
# PlexSync.yml settings (set in Stash UI)
plex_url: "http://192.168.1.100:32400"
plex_token: "your-plex-token-here"
plex_library: "Adult"
enabled: true
```

### Preserve Plex Edits

```yaml
plex_url: "http://plex:32400"
plex_token: "your-plex-token-here"
plex_library: "Adult"
preserve_plex_edits: true    # Only update empty fields
strict_matching: true        # Skip ambiguous matches
```

### Relaxed Matching

```yaml
plex_url: "http://plex:32400"
plex_token: "your-plex-token-here"
plex_library: "Adult"
preserve_plex_edits: false   # Stash always wins
strict_matching: false       # Sync first match on ambiguous
max_retries: 10              # More retries for flaky network
```

## Common Issues Identified from Code

### Top Issues for Troubleshooting Guide

1. **Plex token invalid/expired**
   - Error: `Authentication failed: Unauthorized`
   - Solution: Get fresh token from Plex settings

2. **No Plex match found**
   - Error: `PlexNotFound: No Plex item found for filename`
   - Causes: File not scanned by Plex, path mismatch, library not specified
   - Solution: Scan Plex library, verify paths, set `plex_library`

3. **Multiple Plex matches (strict mode)**
   - Error: `Low confidence match skipped (strict_matching=true)`
   - Cause: Ambiguous filename matches multiple Plex items
   - Solution: Set `strict_matching: false` or rename files

4. **Queue processing timeout**
   - Warning: `Timeout waiting for queue (X items remaining)`
   - Cause: Stash plugin timeout limits
   - Solution: Run `process_queue.py` manually

5. **Scene has no file path**
   - Error: `No file path for scene X, cannot sync to Plex`
   - Cause: Scene in Stash without associated media file
   - Solution: Ensure scene has files linked

6. **Hook handler slow**
   - Warning: `Hook handler exceeded 100ms target`
   - Cause: Slow Stash GraphQL or network issues
   - Impact: Non-blocking, just informational

7. **Circuit breaker opened**
   - Warning: `Circuit breaker OPENED - pausing processing`
   - Cause: 5+ consecutive Plex failures
   - Resolution: Auto-recovers after 60 seconds

8. **DLQ has failed jobs**
   - Warning: `DLQ contains X failed jobs requiring review`
   - Action: Check logs for error details, address root cause

## Manual Queue Processing

For stalled queues, PlexSync includes `process_queue.py`:

```bash
# Show queue stats only
python process_queue.py --stats-only

# Process queue
python process_queue.py --data-dir /path/to/data \
  --plex-url http://plex:32400 \
  --plex-token YOUR_TOKEN \
  --plex-library Adult
```

## Sources

### Primary (HIGH confidence)
- `/Users/trekkie/projects/PlexSync/PlexSync.yml` - Plugin manifest with all UI settings
- `/Users/trekkie/projects/PlexSync/validation/config.py` - PlexSyncConfig Pydantic model
- `/Users/trekkie/projects/PlexSync/requirements.txt` - Python dependencies
- `/Users/trekkie/projects/PlexSync/index.yml` - Installation manifest

### Code Analysis (HIGH confidence)
- `/Users/trekkie/projects/PlexSync/PlexSync.py` - Main entry point
- `/Users/trekkie/projects/PlexSync/worker/processor.py` - Job processing with retry logic
- `/Users/trekkie/projects/PlexSync/sync_queue/dlq.py` - Dead letter queue
- `/Users/trekkie/projects/PlexSync/plex/exceptions.py` - Error classification
- `/Users/trekkie/projects/PlexSync/plex/matcher.py` - Plex item matching
- `/Users/trekkie/projects/PlexSync/hooks/handlers.py` - Hook event processing

## Metadata

**Confidence breakdown:**
- Configuration options: HIGH - extracted directly from PlexSyncConfig and PlexSync.yml
- Installation process: HIGH - derived from index.yml and requirements.txt
- System architecture: HIGH - traced through actual code flow
- Error scenarios: HIGH - extracted from exception classes and log statements
- Path handling: MEDIUM - Docker paths based on common patterns, not verified

**Research date:** 2026-02-03
**Valid until:** 2026-03-03 (stable documentation, 30-day validity)
