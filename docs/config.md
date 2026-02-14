# Configuration Reference

All Stash2Plex settings are configured in the Stash UI under **Settings > Plugins > Stash2Plex**.

This document covers every setting, its purpose, default value, and when you might want to change it.

---

## Required Settings

These settings have no usable defaults and must be configured before Stash2Plex will work.

### plex_url

| Property | Value |
|----------|-------|
| Type | STRING |
| Required | Yes |
| Default | (none) |

**Description:** URL of your Plex Media Server.

**Format:** `http://hostname:32400` or `https://hostname:32400`

**Examples:**

| Setup | URL |
|-------|-----|
| Local network | `http://192.168.1.100:32400` |
| Docker container name | `http://plex:32400` |
| Docker to host machine | `http://host.docker.internal:32400` |
| Remote server | `http://plex.example.com:32400` |

**Note:** The URL must be reachable from your Stash server. If Stash runs in Docker, use container networking or `host.docker.internal`.

---

### plex_token

| Property | Value |
|----------|-------|
| Type | STRING |
| Required | Yes |
| Default | (none) |

**Description:** Your Plex authentication token (X-Plex-Token).

**Format:** Alphanumeric string, typically 20+ characters.

**How to get:** See [Finding Your Plex Token](#finding-your-plex-token) below.

**Security note:** Treat this like a password. Do not share it or commit it to version control.

---

## Recommended Settings

### plex_library

| Property | Value |
|----------|-------|
| Type | STRING |
| Required | No |
| Default | (empty) |

**Description:** Name of the Plex library (or libraries) to search for matches.

**Examples:** `Adult`, `Movies`, `Adult, Movies, TV Shows`

**Behavior:**
- **Single library:** `Adult` — searches only that library (fastest)
- **Multiple libraries:** `Adult, Movies` — searches each listed library in order
- **When empty:** Stash2Plex searches ALL libraries (slowest, may find wrong matches)

**Recommendation:** Always set this to your target library name(s) for faster and more accurate matching.

---

## Behavior Settings

### enabled

| Property | Value |
|----------|-------|
| Type | BOOLEAN |
| Required | No |
| Default | `true` |

**Description:** Enable or disable Stash2Plex.

**Use case:** Temporarily pause syncing without uninstalling the plugin. Useful during bulk imports or Plex maintenance.

---

### strict_matching

| Property | Value |
|----------|-------|
| Type | BOOLEAN |
| Required | No |
| Default | `true` |

**Description:** How to handle multiple Plex matches for a scene.

**Behavior:**
- **When true:** Skip sync if multiple matches found (safer, prevents incorrect updates)
- **When false:** Sync to the first match found (may cause incorrect metadata updates)

**Recommendation:** Keep `true` unless you have unique filenames and are confident there won't be duplicate matches.

---

### preserve_plex_edits

| Property | Value |
|----------|-------|
| Type | BOOLEAN |
| Required | No |
| Default | `false` |

**Description:** How to handle fields that already have values in Plex.

**Behavior:**
- **When true:** Only update empty fields in Plex (preserves your manual edits)
- **When false:** Overwrite Plex values with Stash values (Stash is the source of truth)

**Use case:** Set to `true` if you manually edit metadata in Plex and want to keep those edits. Set to `false` if Stash should always be the authoritative source.

---

## Performance Settings

### max_retries

| Property | Value |
|----------|-------|
| Type | NUMBER |
| Required | No |
| Default | `5` |
| Range | 1-20 |

**Description:** Maximum retry attempts for failed sync jobs.

**Behavior:** After this many retries, jobs move to the dead letter queue for manual review.

**When to change:**
- **Increase** if your network is unreliable or Plex server occasionally goes offline
- **Decrease** if you want faster feedback on permanent failures

**Note:** Stash2Plex uses exponential backoff between retries (5s, 10s, 20s, 40s, 80s), so 5 retries covers several minutes of transient failures.

---

### poll_interval

| Property | Value |
|----------|-------|
| Type | NUMBER |
| Required | No |
| Default | `30` |
| Range | 0.1-60 |

**Description:** Seconds between queue processing cycles.

**When to change:**
- **Lower value** (e.g., 5): Faster syncing, but more CPU usage
- **Higher value** (e.g., 60): More resource-friendly, but slower syncing

**Recommendation:** 30 seconds is good for most users. Lower if you want near-instant sync, higher if running on low-power hardware.

---

### connect_timeout

| Property | Value |
|----------|-------|
| Type | NUMBER |
| Required | No |
| Default | `5` |
| Range | 1-30 |

**Description:** Seconds to wait for initial Plex connection.

**When to change:**
- **Increase** if Plex is on a slow network or remote server
- **Decrease** if you want faster failure detection

---

### read_timeout

| Property | Value |
|----------|-------|
| Type | NUMBER |
| Required | No |
| Default | `30` |
| Range | 5-120 |

**Description:** Seconds to wait for Plex API responses.

**When to change:**
- **Increase** if you have large libraries that take long to search
- **Decrease** if you want faster failure detection on a fast local network

---

### max_tags

| Property | Value |
|----------|-------|
| Type | NUMBER |
| Required | No |
| Default | `100` |
| Range | 10-500 |

**Description:** Maximum number of tags/genres to sync per Plex item.

**Behavior:** When a scene has more tags than this limit, the list is truncated and a warning is logged. Plex has no documented limit on genres.

**When to change:**
- **Increase** if you have scenes with very many tags and want them all synced
- **Decrease** if you want cleaner genre lists in Plex

---

### trigger_plex_scan

| Property | Value |
|----------|-------|
| Type | BOOLEAN |
| Required | No |
| Default | `false` |

**Description:** Trigger a Plex library scan when Stash identifies a new scene.

**Behavior:**
- **When true:** Stash2Plex tells Plex to scan the library when a `Scene.Create.Post` event fires, ensuring Plex discovers newly added files before metadata sync occurs.
- **When false:** Plex must discover files through its own scan schedule.

**Use case:** Enable if you add media files via Stash and want Plex to pick them up immediately without waiting for Plex's scheduled scan.

**Note:** This only triggers on new scene creation, not on scene updates. The scan is non-blocking and does not delay metadata syncing.

---

## Reconciliation Settings

### reconcile_interval

| Property | Value |
|----------|-------|
| Type | STRING |
| Required | No |
| Default | `never` |
| Values | `never`, `hourly`, `daily`, `weekly` |

**Description:** How often Stash2Plex automatically checks for metadata gaps between Stash and Plex.

**Behavior:**
- **`never`** (default): Auto-reconciliation is disabled. Use manual reconciliation tasks instead.
- **`hourly`**: Check every hour.
- **`daily`**: Check every 24 hours.
- **`weekly`**: Check every 7 days.

**How it works:** Since Stash plugins are invoked per-event (not long-running), Stash2Plex uses a check-on-invocation pattern: each plugin run checks a state file to determine if reconciliation is due. It also runs on Stash startup if more than 1 hour has passed since the last run (using the `reconcile_scope` setting).

**What it detects:**
- **Empty metadata:** Plex item has no metadata but Stash scene does
- **Stale syncs:** Stash scene was updated after the last sync
- **Missing items:** Stash scene has no Plex match

Detected gaps are automatically enqueued for sync through the normal queue pipeline.

---

### reconcile_scope

| Property | Value |
|----------|-------|
| Type | STRING |
| Required | No |
| Default | `24h` |
| Values | `all`, `24h`, `7days` |

**Description:** Default scope for auto-reconciliation (how far back to check).

**Behavior:**
- **`all`**: Check every scene in Stash (slowest, most thorough)
- **`24h`** (default): Check scenes updated in the last 24 hours (fastest, good for regular intervals)
- **`7days`**: Check scenes updated in the last 7 days (balanced)

**Note:** This only applies to auto-reconciliation. Manual reconciliation tasks ("Reconcile Library (All)", "Recent", "Last 7 Days") have their own fixed scopes.

---

## Internal Settings

These settings are not exposed in the Stash UI but are recognized by the code. Advanced users can set them by modifying the plugin configuration directly.

### strict_mode

| Property | Value |
|----------|-------|
| Type | BOOLEAN |
| Default | `false` |

**Description:** How to handle invalid metadata.

- **When true:** Reject invalid metadata (job fails validation)
- **When false:** Sanitize invalid metadata (remove control characters, truncate long strings)

**Default behavior:** Stash2Plex sanitizes metadata automatically, so most users never need this.

**Note:** As of v1.1.2, sanitization messages (for cleaning invisible characters) log at debug level instead of warning level, reducing false error noise in Stash logs.

---

### dlq_retention_days

| Property | Value |
|----------|-------|
| Type | NUMBER |
| Default | `30` |

**Description:** Days to keep failed jobs in the dead letter queue before automatic cleanup.

---

## Debug & Privacy Settings

### debug_logging

| Property | Value |
|----------|-------|
| Type | BOOLEAN |
| Required | No |
| Default | `false` |

**Description:** Enable verbose step-by-step debug logging.

**Behavior:** When enabled, Stash2Plex logs detailed information about:
- Queue polling and circuit breaker state
- Title search queries and result counts
- File matching decisions and confidence scoring
- Metadata field comparisons (current vs new values)
- Cache hits and misses

**Warning:** This produces large volumes of log output. Enable only when troubleshooting a specific problem, run for a few sync cycles, then disable.

---

### obfuscate_paths

| Property | Value |
|----------|-------|
| Type | BOOLEAN |
| Required | No |
| Default | `false` |

**Description:** Replace file paths in logs with deterministic word substitutions for privacy.

**Behavior:** When enabled, file paths like `/media/videos/scene.mp4` are replaced with random word combinations in log output. The substitutions are deterministic within a session (same path always maps to same words), so you can still correlate log entries.

**Use case:** Enable when sharing logs publicly (e.g., GitHub issues) to avoid exposing your file structure.

---

## Field Sync Settings

Control which metadata fields sync from Stash to Plex. All toggles are **enabled by default**.

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `sync_master` | boolean | `true` | Master toggle - when OFF, no fields are synced |
| `sync_studio` | boolean | `true` | Sync studio name to Plex |
| `sync_summary` | boolean | `true` | Sync summary/details to Plex |
| `sync_tagline` | boolean | `true` | Sync tagline to Plex |
| `sync_date` | boolean | `true` | Sync release date to Plex |
| `sync_performers` | boolean | `true` | Sync performers as Plex actors |
| `sync_tags` | boolean | `true` | Sync tags as Plex genres |
| `sync_poster` | boolean | `true` | Sync poster image to Plex |
| `sync_background` | boolean | `true` | Sync background/fanart image to Plex |
| `sync_collection` | boolean | `true` | Add to Plex collection based on studio name |

### Toggle Behavior

- **Toggle OFF:** Field is skipped entirely. Plex keeps its existing value.
- **Toggle ON + empty value:** Field is cleared in Plex (Stash value is authoritative).
- **Toggle ON + `preserve_plex_edits`:** Existing Plex values are preserved if present.

### Common Use Cases

**Sync only core metadata (skip images and collections):**

```yaml
sync_poster: false
sync_background: false
sync_collection: false
```

**Sync only performers (for cast-focused libraries):**

```yaml
sync_studio: false
sync_summary: false
sync_tagline: false
sync_date: false
sync_tags: false
sync_poster: false
sync_background: false
sync_collection: false
# sync_performers defaults to true
```

**Disable all syncing temporarily:**

```yaml
sync_master: false
```

> **Note:** Title and file path are always synced (required for matching) and cannot be toggled off.

---

## Example Configurations

### Basic Setup (Most Users)

```yaml
plex_url: "http://192.168.1.100:32400"
plex_token: "your-plex-token"
plex_library: "Adult"
enabled: true
```

### Preserve Plex Edits (Manual Editors)

For users who manually edit metadata in Plex and want to keep those edits:

```yaml
plex_url: "http://192.168.1.100:32400"
plex_token: "your-plex-token"
plex_library: "Adult"
preserve_plex_edits: true
strict_matching: true
```

### Relaxed Matching (Unique Filenames)

For users with unique filenames who want sync even when multiple matches exist:

```yaml
plex_url: "http://192.168.1.100:32400"
plex_token: "your-plex-token"
plex_library: "Adult"
strict_matching: false
preserve_plex_edits: false
```

### Unreliable Network

For remote Plex servers or unstable connections:

```yaml
plex_url: "http://remote-plex.example.com:32400"
plex_token: "your-plex-token"
plex_library: "Adult"
max_retries: 15
connect_timeout: 15
read_timeout: 60
```

### Docker Setup

When both Stash and Plex run in Docker on the same network:

```yaml
plex_url: "http://plex:32400"  # Container name
plex_token: "your-plex-token"
plex_library: "Adult"
```

---

## Validation Rules

Stash2Plex validates your configuration on startup. Invalid settings log errors and may disable the plugin.

| Setting | Validation |
|---------|------------|
| plex_url | Must start with `http://` or `https://` |
| plex_token | Minimum 10 characters |
| max_retries | Must be 1-20 |
| poll_interval | Must be 0.1-60 |
| connect_timeout | Must be 1-30 |
| read_timeout | Must be 5-120 |
| max_tags | Must be 10-500 |
| reconcile_interval | Must be one of: never, hourly, daily, weekly |
| reconcile_scope | Must be one of: all, 24h, 7days |

---

## Finding Your Plex Token

1. Sign into Plex Web App
2. Browse to any library item
3. Click the "..." menu > "Get Info" > "View XML"
4. Look for `X-Plex-Token=` in the URL
5. Copy the token value (everything after the `=`)

**Alternative method:** Check your Plex config at:
- **Linux:** `~/.config/Plex Media Server/Preferences.xml`
- **macOS:** `~/Library/Application Support/Plex Media Server/Preferences.xml`
- **Windows:** `%LOCALAPPDATA%\Plex Media Server\Preferences.xml`

Look for `PlexOnlineToken` in the file.

---

## Common Configuration Issues

| Error Message | Cause | Solution |
|---------------|-------|----------|
| "plex_url must start with http:// or https://" | Missing or malformed URL | Add `http://` prefix |
| "plex_token is required" | Missing or too-short token | Get token from Plex (see above) |
| "Connection refused" | Wrong URL or Plex not running | Verify URL and Plex status |
| "Unauthorized" | Invalid token | Get fresh token from Plex |
| "Library not found" | Wrong library name | Check exact name in Plex (case-sensitive) |

For more help, see [Troubleshooting](troubleshoot.md).
