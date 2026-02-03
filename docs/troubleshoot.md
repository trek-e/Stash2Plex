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

### Issue 1: Plex Token Invalid/Expired

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

### Issue 2: No Plex Match Found

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

### Issue 3: Multiple Plex Matches (Strict Mode)

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

### Issue 4: Queue Processing Timeout

**Symptom:**
```
[Stash2Plex] Timeout waiting for queue (X items remaining)
```

Or processing appears to stop mid-queue.

**Cause:** Stash plugins have execution time limits. Large queues may not finish in one cycle.

**Solutions:**

1. **Wait:** Processing resumes automatically on the next cycle
2. **Use smaller batches:** Run "Sync Recent Scenes" task instead of "Sync All Scenes"
3. **Manual processing:** For large backlogs, run `process_queue.py` manually (see [Manual Queue Processing](#manual-queue-processing))

---

### Issue 5: Scene Has No File Path

**Symptom:**
```
[Stash2Plex] No file path for scene X, cannot sync to Plex
```

**Cause:** The scene in Stash has no associated media file (metadata-only entry).

**Solution:**
- Link a file to the scene in Stash, or
- This scene cannot be synced (Plex matching requires a file path)

---

### Issue 6: Hook Handler Slow

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

### Issue 7: Circuit Breaker Opened

**Symptom:**
```
[Stash2Plex] Circuit breaker OPENED - pausing processing
```

**Cause:** 5+ consecutive Plex failures (server down, network issues).

**Meaning:** Stash2Plex paused processing to avoid hammering a failing Plex server.

**Resolution:** Automatic. The circuit breaker recovers after 60 seconds and retries.

**If persistent:** Verify Plex server is running and accessible from Stash.

---

### Issue 8: DLQ Has Failed Jobs

**Symptom:**
```
[Stash2Plex] DLQ contains X failed jobs requiring review
```

**Meaning:** Some jobs failed permanently and will not retry automatically.

**Action:**
1. Check logs for specific error messages on each failed job
2. Address the root cause (invalid token, missing file, etc.)
3. Re-trigger sync by editing affected scenes in Stash

**Common causes of permanent failure:**
- Authentication failure (401) - token invalid
- Bad request (400) - malformed data
- Low confidence match with strict mode enabled

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

## Manual Queue Processing

For stuck queues or large backlogs, Stash2Plex includes a standalone queue processor.

### Check Queue Status

```bash
python process_queue.py --stats-only
```

This shows queue size and DLQ status without processing anything.

### Process Queue Manually

```bash
python process_queue.py \
  --data-dir /path/to/Stash2Plex/data \
  --plex-url http://plex:32400 \
  --plex-token YOUR_TOKEN \
  --plex-library Adult
```

**Location:** `process_queue.py` in the Stash2Plex plugin folder.

**When to use:**
- Queue is stuck due to Stash plugin timeout
- Large backlog from initial import
- Testing/debugging sync issues

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

- **Filter logs** to `[Stash2Plex]` entries only
- **Include the full error message**, not just a summary
- **Redact tokens and personal info** before sharing
- **Include steps to reproduce** if the issue is repeatable
- **Mention any recent changes** (updated Stash, changed config, etc.)

---

## Related Documentation

- [Installation Guide](install.md) - Setup and prerequisites
- [Configuration Reference](config.md) - All available settings
