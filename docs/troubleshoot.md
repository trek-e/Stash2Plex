# Troubleshooting Guide

This guide helps you diagnose and resolve common Stash2Plex issues. Understanding how Stash2Plex works makes troubleshooting easier, so we start with a brief overview of the system.

---

## How Stash2Plex Works

Understanding the processing flow helps you pinpoint where issues occur:

1. **Hook receives scene update** - When you edit a scene in Stash, Stash2Plex receives a notification (target: <100ms)
2. **Job added to queue** - The sync job is added to a persistent SQLite queue (survives restarts)
3. **Worker processes queue** - A background worker polls the queue every 30 seconds
4. **Worker retries failures** - Transient failures (network issues, Plex temporarily down) are retried with exponential backoff
5. **Permanent failures go to DLQ** - Jobs that fail repeatedly or have unrecoverable errors go to the dead letter queue

**Key insight:** Updates are NOT instant. There's a queue processing delay of up to 30 seconds, plus potential retry delays if Plex is temporarily unavailable.

---

## Reading the Logs

Stash2Plex logs are your primary diagnostic tool.

### Where to Find Logs

- **Stash UI:** Settings > Logs
- **Log files:** `logs/` folder in your Stash data directory

### Filtering Logs

Filter by `[Stash2Plex]` to see only Stash2Plex messages. All Stash2Plex log entries start with this prefix.

### Log Levels

| Level | Code | Meaning |
|-------|------|---------|
| Trace | `t` | Very detailed debug info (rarely needed) |
| Debug | `d` | Debug information for development |
| Info | `i` | Normal operations |
| Warning | `w` | Non-fatal issues worth noting |
| Error | `e` | Failures requiring attention |

### Example Success Flow

Here's what a successful sync looks like in the logs:

```
[Stash2Plex] Initialization complete
[Stash2Plex Hook] Enqueued sync job for scene 123 in 45.2ms
[Stash2Plex Worker] Processing job 456 for scene 123 (attempt 1)
[Stash2Plex Matcher] Searching 'Adult' for: Scene Name - 2026-01-30.mp4
[Stash2Plex Matcher] Title search: 'Scene Name'
[Stash2Plex Matcher] Got 1 title matches
[Stash2Plex Matcher] Found: Scene Name
[Stash2Plex Worker] Updated metadata (overwrite mode): Scene Name
[Stash2Plex Worker] Added 2 performers: ['Performer A', 'Performer B']
[Stash2Plex Worker] Job 456 completed
```

**Line-by-line breakdown:**

| Log Line | Meaning |
|----------|---------|
| `Initialization complete` | Plugin started successfully |
| `Enqueued sync job...in 45.2ms` | Job added to queue (good if <100ms) |
| `Processing job...attempt 1` | Worker picked up the job |
| `Searching 'Adult' for:` | Searching the specified library |
| `Title search: 'Scene Name'` | Trying to match by title |
| `Got 1 title matches` | Found exactly one match (ideal) |
| `Found: Scene Name` | Match confirmed |
| `Updated metadata (overwrite mode)` | Metadata written to Plex |
| `Added 2 performers` | Performers synced |
| `Job completed` | Success |

---

## Common Issues

### Issue 1: Missing Dependencies (ModuleNotFoundError)

**Symptom:**
```
[Plugin / Stash2Plex] ModuleNotFoundError: No module named 'pydantic'
```

**Cause:** Python dependencies aren't installed for the Python interpreter that Stash uses.

**How Stash2Plex installs dependencies:**

1. **PythonDepManager** (Stash's built-in package manager)
2. **pip fallback** (uses Stash's own Python with `--break-system-packages` for PEP 668 compatibility)
3. **Actionable error** (shows exact pip command with the correct Python path)

**Solutions:**

1. **Install PythonDepManager** (recommended): Settings > Plugins > Available Plugins > search "PythonDepManager" > Install, then reload plugins.

2. **Run the pip command from the error message.** The error shows the exact Python path Stash uses:
   ```
   Missing dependencies: ['pydantic']. Install with: /usr/bin/python3 -m pip install --break-system-packages pydantic>=2.0.0
   ```
   Use that exact command — running `pip install` from your terminal may install to a different Python.

3. **Docker users:** `docker exec` into the container and run the pip command shown in the error. Running pip from outside the container installs to the host Python, not the container's.

**Why `pip install` from my terminal doesn't work:** Your terminal's `pip` may use a different Python interpreter than Stash. For example, your terminal might use `/usr/local/bin/python3` while Stash uses `/usr/bin/python3`. Each Python has its own separate package directory.

**"Externally managed environment" error (PEP 668):** Python 3.12+ on Alpine, Debian 12+, and Ubuntu 23.04+ blocks system-wide pip installs. Stash2Plex v1.2.7+ handles this automatically with `--break-system-packages`. If running an older version, add the flag manually to the pip command.

---

### Issue 2: Plex Token Invalid/Expired

**Symptom:**
```
[Stash2Plex] Authentication failed: Unauthorized
```

**Cause:** Your Plex token is expired or incorrect.

**Solution:**
1. Get a fresh token from Plex (see [Installation Guide](install.md#getting-your-plex-token))
2. Update `plex_token` in Settings > Plugins > Stash2Plex
3. Reload plugins

**Related setting:** [`plex_token`](config.md#plex_token)

---

### Issue 3: No Plex Match Found

**Symptom:**
```
[Stash2Plex] PlexNotFound: No Plex item found for filename
```

**Causes:**
- File not scanned by Plex yet
- Path mismatch between Stash and Plex (common in Docker)
- Searching wrong library (no `plex_library` set)

**Solutions:**

1. **Scan Plex library:** In Plex, go to Library > ... (three dots) > Scan Library Files

2. **Verify paths match:** Check that Stash and Plex see the file at the same path (see [Docker Path Mapping](#docker-path-mapping-issues) below)

3. **Set `plex_library`:** Specify the exact library name to search

**Note:** Stash2Plex automatically retries "not found" errors up to 12 times over approximately 2 hours, giving Plex time to complete library scans.

**Related setting:** [`plex_library`](config.md#plex_library)

---

### Issue 4: Multiple Plex Matches (Strict Mode)

**Symptom:**
```
[Stash2Plex Matcher] LOW confidence match for 'filename.mp4': 3 candidates found
[Stash2Plex] Low confidence match skipped (strict_matching=true)
```

**Cause:** Multiple Plex items match the filename, and Stash2Plex cannot determine which is correct.

**Solutions:**

- **Option A:** Set `strict_matching: false` to sync to the first match (may cause incorrect updates)
- **Option B:** Rename files to be more unique

**Trade-off:** Relaxed matching may sync metadata to the wrong Plex item if filenames are ambiguous.

**Related setting:** [`strict_matching`](config.md#strict_matching)

---

### Issue 5: Queue Processing Timeout

**Symptom:**
```
[Stash2Plex] Timeout waiting for queue (X items remaining)
```

Or processing appears to stop mid-queue.

**Cause:** Stash plugins have execution time limits. Large queues may not finish in one cycle.

**How Stash2Plex handles this:** Dynamic timeouts scale with queue size (~2 seconds per item, minimum 30s, maximum 600s). Progress is logged every 5 items or 10 seconds. Scene data is fetched in a single batch query to minimize timeout risk.

**Solutions:**

1. **Use "Process Queue" task** - Run from Settings > Plugins > Stash2Plex > Process Queue. This runs in the foreground until the queue is empty with no timeout limits.
2. **Wait** - Processing resumes automatically on the next hook trigger or task run.
3. **Use smaller batches** - Run "Sync Recent Scenes" instead of "Sync All Scenes".

---

### Issue 6: Plex Read Timeout During Bulk Sync

**Symptom:**
```
[Stash2Plex Worker] Partial sync for Scene Name: 1 warnings: tags: HTTPConnectionPool(...): Read timed out. (read timeout=30.0)
```

**Cause:** Plex is overwhelmed by rapid-fire API requests during bulk sync.

**Resolution (v1.2.5+):** This issue is significantly reduced in v1.2.5 and later through:
- Connection pooling (HTTP keep-alive reduces connection overhead)
- Deferred reload (single HTTP roundtrip per job instead of up to 6)
- Inter-job throttle (150ms pause between jobs)
- Metadata comparison (skips API calls when values haven't changed)

**If still occurring:**
1. Increase `read_timeout` to 60 or higher
2. Use "Process Queue" task which runs without timeout limits
3. Check Plex server load (other clients streaming, library scanning)

**Related setting:** [`read_timeout`](config.md#read_timeout)

---

### Issue 7: Scene Has No File Path

**Symptom:**
```
[Stash2Plex] No file path for scene X, cannot sync to Plex
```

**Cause:** The scene in Stash has no associated media file (metadata-only entry).

**Solution:**
- Link a file to the scene in Stash, or
- This scene cannot be synced (Plex matching requires a file path)

---

### Issue 8: Hook Handler Slow

**Symptom:**
```
[Stash2Plex Hook] Hook handler exceeded 100ms target (156.3ms)
```

**Cause:** Slow Stash GraphQL response or network latency.

**Impact:** This is a non-blocking warning. Sync still works, just took longer than ideal.

**Solution:** Usually safe to ignore. If persistent:
- Check Stash server performance
- Check network between Stash components

---

### Issue 9: Circuit Breaker Opened

**Symptom:**
```
[Stash2Plex] Circuit breaker OPEN — Plex may be unavailable (last error: ReadTimeout: read timed out)
```

**Cause:** 5+ consecutive Plex failures (server down, network issues, read timeouts).

**Meaning:** Stash2Plex paused processing to avoid hammering a failing Plex server. The log message includes the last error that triggered the circuit breaker.

**Resolution:** Automatic. The circuit breaker recovers after 60 seconds and retries.

**If persistent:** Verify Plex server is running and accessible from Stash. Check the error type in the log message for clues (e.g., `ReadTimeout` suggests Plex is overloaded, `ConnectionRefused` suggests Plex is down).

---

### Issue 10: DLQ Has Failed Jobs

**Symptom:**
```
[Stash2Plex] DLQ contains X failed jobs requiring review
```

**Meaning:** Some jobs failed permanently and will not retry automatically.

**Action:**
1. **View status** - Run "View Queue Status" task to see DLQ count and error summary
2. Check logs for specific error messages on each failed job
3. Address the root cause (invalid token, missing file, etc.)
4. Re-trigger sync by editing affected scenes in Stash

**Managing the DLQ from Stash UI:**

| Task | What it does |
|------|-------------|
| **View Queue Status** | Shows pending + DLQ counts in logs |
| **Clear Dead Letter Queue** | Remove all DLQ entries |
| **Purge Old DLQ Entries** | Remove entries older than 30 days |

**Common causes of permanent failure:**
- Authentication failure (401) - token invalid
- Bad request (400) - malformed data
- Low confidence match with strict mode enabled

---

### Issue 11: Using Debug Logging

**When to use:** When you need detailed diagnostics for a specific sync issue and the normal logs don't provide enough information.

**Steps:**

1. Enable `debug_logging` in Settings > Plugins > Stash2Plex
2. Optionally enable `obfuscate_paths` if you plan to share logs publicly
3. Trigger the sync you want to debug (edit a scene, or run "Process Queue")
4. Check Stash logs — look for `[DEBUG]` prefixed messages
5. **Disable `debug_logging` when done** (it produces large volumes of output)

**What debug logging shows:**
- Queue polling activity and circuit breaker state
- Title search queries and how many results each returns
- File matching decisions (cache hits/misses, confidence scoring)
- Metadata field-by-field comparisons (current Plex value vs new Stash value)
- API call details for Plex updates

**Note:** Debug messages appear at INFO level in Stash logs (not DEBUG level), so they are visible with default Stash log settings.

---

## Docker Path Mapping Issues

Path mismatches are a common source of "No Plex match found" errors in Docker deployments.

### The Problem

Stash2Plex matches Plex items by file path. If Stash and Plex see files at different paths, matching fails.

**Example problem:**
- Stash container sees: `/data/videos/scene.mp4`
- Plex container sees: `/media/videos/scene.mp4`
- Result: No match found

### The Solution

Ensure both containers mount media at the **same internal path**:

```yaml
# docker-compose.yml example
services:
  stash:
    volumes:
      - /mnt/media:/media  # Use /media inside container

  plex:
    volumes:
      - /mnt/media:/media  # SAME /media path inside container
```

### Diagnosing Path Issues

1. In Stash, view a scene's details and note the file path
2. In Plex, view the same item's details and note the file path
3. Compare - they must match exactly

---

## Queue Management

### From Stash UI (Recommended)

Stash2Plex provides built-in tasks for queue management. Go to **Settings > Plugins > Stash2Plex** and run:

| Task | Use when... |
|------|-------------|
| **View Queue Status** | You want to check how many items are pending or failed |
| **Process Queue** | Queue is stuck or you want to process all items immediately (runs until empty, no timeout) |
| **Clear Pending Queue** | You want to discard all pending items and start fresh |
| **Clear Dead Letter Queue** | You want to clear all permanently failed items |
| **Purge Old DLQ Entries** | You want to clean up old failures (removes entries >30 days) |

### From Command Line

For advanced debugging, Stash2Plex includes a standalone queue processor:

```bash
# Check queue status
python process_queue.py --stats-only

# Process queue manually
python process_queue.py \
  --data-dir /path/to/Stash2Plex/data \
  --plex-url http://plex:32400 \
  --plex-token YOUR_TOKEN \
  --plex-library Adult
```

**Location:** `process_queue.py` in the Stash2Plex plugin folder.

---

## Understanding the Dead Letter Queue (DLQ)

The dead letter queue stores jobs that failed permanently.

| Property | Value |
|----------|-------|
| **What** | Storage for permanently failed jobs |
| **When** | Jobs that exceed `max_retries` OR have permanent errors |
| **Location** | `data/dlq.db` (SQLite database) |
| **Retention** | Auto-cleanup after 30 days (configurable via `dlq_retention_days`) |

**What to do with DLQ jobs:**
1. Review logs to understand why jobs failed
2. Fix the root cause (token, permissions, file path, etc.)
3. Re-sync affected scenes by editing them in Stash

---

## Error Classification

Understanding which errors retry vs. fail permanently helps diagnose issues.

### Transient Errors (Will Retry)

These errors trigger automatic retry with exponential backoff:

| Error Type | Examples |
|------------|----------|
| Network errors | Connection refused, timeout, DNS failure |
| Rate limiting | HTTP 429 |
| Server errors | HTTP 500, 502, 503, 504 |
| Not found | HTTP 404 (Plex may still be scanning) |

### Permanent Errors (Goes to DLQ)

These errors go directly to the dead letter queue:

| Error Type | Examples |
|------------|----------|
| Auth failure | HTTP 401 (invalid token) |
| Permission denied | HTTP 403 |
| Bad request | HTTP 400 |
| Validation errors | Invalid metadata format |
| Low confidence match | Multiple matches with `strict_matching=true` |

---

## How to Report Issues

When reporting issues on GitHub, include the following information to help diagnose the problem.

### Issue Template

```markdown
**Environment:**
- Stash version:
- Plex version:
- Stash2Plex version:
- Deployment: Docker / Bare metal

**Issue:**
[Describe what happened]

**Expected:**
[What you expected to happen]

**Logs:**
[Paste relevant [Stash2Plex] log lines]

**Steps to Reproduce:**
1.
2.
3.
```

### Tips for Effective Bug Reports

- **Enable `debug_logging`** to capture detailed diagnostics, then reproduce the issue
- **Enable `obfuscate_paths`** to automatically redact file paths before sharing logs
- **Filter logs** to `[Stash2Plex]` entries only
- **Include the full error message**, not just a summary
- **Redact tokens and personal info** before sharing
- **Include steps to reproduce** if the issue is repeatable
- **Mention any recent changes** (updated Stash, changed config, etc.)

---

## Related Documentation

- [Installation Guide](install.md) - Setup and prerequisites
- [Configuration Reference](config.md) - All available settings
