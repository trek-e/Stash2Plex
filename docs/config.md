# Configuration Reference

All PlexSync settings are configured in the Stash UI under **Settings > Plugins > PlexSync**.

This document covers every setting, its purpose, default value, and when you might want to change it.

---

## Required Settings

These settings have no usable defaults and must be configured before PlexSync will work.

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

**Description:** Name of the Plex library to search for matches.

**Examples:** `Adult`, `Movies`, `Home Videos`

**Behavior:**
- **When set:** PlexSync only searches the specified library (faster)
- **When empty:** PlexSync searches ALL libraries (slower, may find wrong matches)

**Recommendation:** Always set this to your target library name for faster and more accurate matching.

---

## Behavior Settings

### enabled

| Property | Value |
|----------|-------|
| Type | BOOLEAN |
| Required | No |
| Default | `true` |

**Description:** Enable or disable PlexSync.

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

**Note:** PlexSync uses exponential backoff between retries (5s, 10s, 20s, 40s, 80s), so 5 retries covers several minutes of transient failures.

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

**Default behavior:** PlexSync sanitizes metadata automatically, so most users never need this.

---

### dlq_retention_days

| Property | Value |
|----------|-------|
| Type | NUMBER |
| Default | `30` |

**Description:** Days to keep failed jobs in the dead letter queue before automatic cleanup.

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

PlexSync validates your configuration on startup. Invalid settings log errors and may disable the plugin.

| Setting | Validation |
|---------|------------|
| plex_url | Must start with `http://` or `https://` |
| plex_token | Minimum 10 characters |
| max_retries | Must be 1-20 |
| poll_interval | Must be 0.1-60 |
| connect_timeout | Must be 1-30 |
| read_timeout | Must be 5-120 |

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
