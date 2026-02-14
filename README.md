# Stash2Plex

Sync metadata from Stash to Plex with queue-based reliability.

[![Tests](https://img.shields.io/badge/tests-999%2B-brightgreen)](tests/)
[![Coverage](https://img.shields.io/badge/coverage-%3E80%25-brightgreen)](pytest.ini)
[![License](https://img.shields.io/badge/license-AGPL--3.0-blue)](LICENSE)

## Overview

Stash2Plex is a Stash plugin that automatically syncs scene metadata from Stash to Plex. When you update a scene in Stash (title, studio, performers, tags), Stash2Plex queues the change and syncs it to the matching item in your Plex library.

**Key features:**

- **Persistent queue** - Jobs survive Stash restarts; nothing is lost if Stash crashes
- **Automatic retry** - Failed syncs retry with exponential backoff
- **Circuit breaker** - Protects Plex from being hammered when it's down
- **Crash recovery** - In-progress jobs automatically resume after restart
- **Queue management** - View status, clear queue, and manage failed jobs from Stash UI
- **Process Queue** - Foreground processing that runs until the queue is empty
- **Performance caching** - Reduces Plex API calls with disk-backed caching
- **Selective sync** - Toggle which metadata fields sync to Plex
- **Dynamic timeouts** - Processing timeout scales with queue size automatically
- **Metadata reconciliation** - Detect and fix gaps: empty metadata, stale syncs, missing Plex items
- **Auto-reconciliation** - Scheduled gap detection on startup and at configurable intervals
- **Plex scan trigger** - Optionally trigger Plex library scan when Stash discovers new scenes
- **Sync statistics** - Track success rates and timing with batch summaries
- **Connection pooling** - HTTP keep-alive reduces connection overhead during bulk sync
- **Smart skip** - Bulk sync skips already-synced scenes and unchanged metadata fields
- **Automatic dependency installation** - Dependencies install via PythonDepManager or pip fallback

**Use Stash2Plex if you:**

- Organize your media metadata in Stash
- Want Plex to reflect the same titles, studios, performers, and tags
- Need reliable syncing that handles network issues gracefully

## Quick Start

**Prerequisites:**

- Stash running (any recent version)
- Plex Media Server running and accessible from Stash
- Your Plex authentication token

### Get Your Plex Token

1. Open Plex Web App and sign in
2. Open any item in your library
3. Click the three-dot menu and select "Get Info"
4. Click "View XML"
5. In the URL bar, find `X-Plex-Token=YOUR_TOKEN_HERE`

Alternatively, see [Plex's official guide](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/).

### Installation

1. **Install PythonDepManager** (recommended):

   Settings > Plugins > Available Plugins > search "PythonDepManager" > Install

   > PythonDepManager is recommended but not strictly required. Stash2Plex can install dependencies via pip as a fallback.

2. **Download Stash2Plex** to your Stash plugins directory:

   ```bash
   cd ~/.stash/plugins
   git clone https://github.com/trek-e/Stash2Plex.git
   ```

   Or download and extract the ZIP from the [releases page](https://github.com/trek-e/Stash2Plex/releases).

3. **Reload plugins** in Stash:

   Settings > Plugins > Reload Plugins

4. **Configure required settings** in Stash:

   Settings > Plugins > Stash2Plex

   | Setting | Value |
   |---------|-------|
   | Plex URL | `http://localhost:32400` (or your Plex server address) |
   | Plex Token | Your X-Plex-Token from above |
   | Plex Library | Name of your Plex library (e.g., `Movies`) |

5. **Test the sync:**

   - Edit any scene in Stash (change the title slightly)
   - Check Plex within 30 seconds - the title should update

That's it! Stash2Plex is now syncing metadata from Stash to Plex.

## How It Works

1. **Hook triggers** - When you update a scene in Stash, Stash2Plex receives a hook event
2. **Job queued** - The sync job is saved to a SQLite-backed persistent queue
3. **Worker syncs** - Background worker matches the scene to Plex and applies metadata
4. **Retry on failure** - If Plex is down, the job retries with exponential backoff
5. **Dead letter queue** - Permanently failed jobs (e.g., no Plex match) go to a DLQ for review

## Plugin Tasks

Stash2Plex provides 10 tasks accessible from **Settings > Plugins > Stash2Plex**:

| Task | Description |
|------|-------------|
| **Sync All Scenes** | Force sync all scenes to Plex (use sparingly) |
| **Sync Recent Scenes** | Sync scenes updated in the last 24 hours |
| **View Queue Status** | Show pending queue, DLQ counts, and reconciliation history |
| **Clear Pending Queue** | Remove all pending queue items |
| **Clear Dead Letter Queue** | Remove all DLQ entries |
| **Purge Old DLQ Entries** | Remove DLQ entries older than 30 days |
| **Process Queue** | Process all pending items until empty (foreground, no timeout) |
| **Reconcile Library (All)** | Detect and queue metadata gaps for all scenes |
| **Reconcile Library (Recent)** | Detect and queue metadata gaps for scenes updated in 24 hours |
| **Reconcile Library (Last 7 Days)** | Detect and queue metadata gaps for scenes updated in 7 days |

## Documentation

- [Installation Guide](docs/install.md) - Full setup instructions including Docker
- [Configuration Reference](docs/config.md) - All settings explained
- [Troubleshooting](docs/troubleshoot.md) - Common issues and solutions
- [Architecture](docs/ARCHITECTURE.md) - System design and data flow
- [Changelog](CHANGELOG.md) - Version history

## Requirements

- **Stash** - Any recent version
- **Plex Media Server** - Any recent version
- **Python 3.9+** - Required by Stash
- **Python dependencies** - Installed automatically via PythonDepManager or pip:
  - `plexapi` - Plex API client
  - `pydantic` - Data validation
  - `tenacity` - Retry logic
  - `persist-queue` - SQLite-backed queue
  - `diskcache` - Performance caching
  - `stashapp-tools` - Stash API client

> **Note:** PythonDepManager is recommended for automatic dependency management. If unavailable, Stash2Plex falls back to installing dependencies via pip using Stash's Python interpreter (with `--break-system-packages` for PEP 668 compatibility on modern Linux distros). If both methods fail, the error message shows the exact pip command to run manually.

## Settings Reference

### Core Settings

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `plex_url` | string | - | Plex server URL (required) |
| `plex_token` | string | - | Plex authentication token (required) |
| `plex_library` | string | - | Plex library name (recommended) |
| `enabled` | boolean | `true` | Enable/disable the plugin |

### Behavior Settings

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `max_retries` | number | `5` | Max retry attempts before DLQ |
| `poll_interval` | number | `30` | Seconds between queue polls |
| `strict_matching` | boolean | `true` | Skip sync when multiple matches found |
| `preserve_plex_edits` | boolean | `false` | Don't overwrite existing Plex values |
| `connect_timeout` | number | `5` | Plex connection timeout (seconds) |
| `read_timeout` | number | `30` | Plex read timeout (seconds) |
| `trigger_plex_scan` | boolean | `false` | Trigger Plex library scan on new scenes |
| `reconcile_interval` | string | `never` | Auto-reconciliation interval (never/hourly/daily/weekly) |
| `reconcile_scope` | string | `24h` | Auto-reconciliation scope (all/24h/7days) |
| `reconcile_missing` | boolean | `true` | Include "missing from Plex" detection in reconciliation |

### Field Sync Toggles

Control which metadata fields sync from Stash to Plex. All enabled by default.

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `sync_master` | boolean | `true` | Master toggle - when OFF, no fields sync |
| `sync_studio` | boolean | `true` | Sync studio name |
| `sync_summary` | boolean | `true` | Sync summary/details |
| `sync_tagline` | boolean | `true` | Sync tagline |
| `sync_date` | boolean | `true` | Sync release date |
| `sync_performers` | boolean | `true` | Sync performers as actors |
| `sync_tags` | boolean | `true` | Sync tags as genres |
| `sync_poster` | boolean | `true` | Sync poster image |
| `sync_background` | boolean | `true` | Sync background/fanart image |
| `sync_collection` | boolean | `true` | Add to collection by studio name |

See [Configuration Reference](docs/config.md) for detailed documentation of all settings.

## Contributing

Contributions are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and guidelines.

## License

This project is licensed under the [GNU Affero General Public License v3.0](LICENSE).
