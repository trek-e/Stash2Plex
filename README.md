# PlexSync

Sync metadata from Stash to Plex with queue-based reliability.

## Overview

PlexSync is a Stash plugin that automatically syncs scene metadata from Stash to Plex. When you update a scene in Stash (title, studio, performers, tags), PlexSync queues the change and syncs it to the matching item in your Plex library.

**Key features:**

- **Persistent queue** - Jobs survive Stash restarts; nothing is lost if Stash crashes
- **Automatic retry** - Failed syncs retry with exponential backoff
- **Circuit breaker** - Protects Plex from being hammered when it's down
- **Crash recovery** - In-progress jobs automatically resume after restart

**Use PlexSync if you:**

- Organize your media metadata in Stash
- Want Plex to reflect the same titles, studios, performers, and tags
- Need reliable syncing that handles network issues gracefully

## Quick Start

**Prerequisites:**

- Stash running with [PythonDepManager](https://github.com/stashapp/CommunityScripts/tree/main/plugins/PythonDepManager) plugin installed
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

1. **Download PlexSync** to your Stash plugins directory:

   ```bash
   cd ~/.stash/plugins
   git clone https://github.com/trek-e/PlexSync.git
   ```

   Or download and extract the ZIP from the releases page.

2. **Reload plugins** in Stash:

   Settings > Plugins > Reload Plugins

3. **Configure required settings** in Stash:

   Settings > Plugins > PlexSync

   | Setting | Value |
   |---------|-------|
   | Plex URL | `http://localhost:32400` (or your Plex server address) |
   | Plex Token | Your X-Plex-Token from above |
   | Plex Library | Name of your Plex library (e.g., `Movies`) |

4. **Test the sync:**

   - Edit any scene in Stash (change the title slightly)
   - Check Plex within 30 seconds - the title should update

That's it! PlexSync is now syncing metadata from Stash to Plex.

## How It Works

1. **Hook triggers** - When you update a scene in Stash, PlexSync receives a hook event
2. **Job queued** - The sync job is saved to a SQLite-backed persistent queue
3. **Worker syncs** - Background worker matches the scene to Plex and applies metadata
4. **Retry on failure** - If Plex is down, the job retries with exponential backoff
5. **Dead letter queue** - Permanently failed jobs (e.g., no Plex match) go to a DLQ for review

## Documentation

- [Installation Guide](docs/install.md) - Full setup instructions including Docker
- [Configuration Reference](docs/config.md) - All settings explained
- [Troubleshooting](docs/troubleshoot.md) - Common issues and solutions

## Requirements

- **Stash** - Any recent version
- **Plex Media Server** - Any recent version
- **PythonDepManager** - Stash plugin for managing Python dependencies
- **Python dependencies** - Installed automatically by PythonDepManager:
  - `plexapi` - Plex API client
  - `pydantic` - Data validation
  - `tenacity` - Retry logic
  - `persistqueue` - SQLite-backed queue

## Settings Reference

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `plex_url` | string | - | Plex server URL (required) |
| `plex_token` | string | - | Plex authentication token (required) |
| `plex_library` | string | - | Plex library name (recommended) |
| `enabled` | boolean | `true` | Enable/disable the plugin |
| `max_retries` | number | `5` | Max retry attempts before DLQ |
| `poll_interval` | number | `30` | Seconds between queue polls |
| `strict_matching` | boolean | `true` | Skip sync when multiple matches found |
| `preserve_plex_edits` | boolean | `false` | Don't overwrite existing Plex values |
| `connect_timeout` | number | `5` | Plex connection timeout (seconds) |
| `read_timeout` | number | `30` | Plex read timeout (seconds) |

## License

This project is licensed under the [GNU Affero General Public License v3.0](LICENSE).
