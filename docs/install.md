# Installation Guide

This guide covers installing PlexSync from scratch, including prerequisites, setup steps, and verification.

## Prerequisites

Before installing PlexSync, ensure you have:

- **Stash** installed and running ([Stash documentation](https://docs.stashapp.cc/))
- **Plex Media Server** installed and running
- Access to your Stash plugins folder
- A Plex authentication token (see [Getting Your Plex Token](#getting-your-plex-token) below)

## Step 1: Install PythonDepManager

PlexSync requires Python dependencies that are automatically installed by the **PythonDepManager** Stash plugin. This is a one-time setup.

1. In Stash, go to **Settings > Plugins > Available Plugins**
2. Search for "PythonDepManager" or "py_common"
3. Click **Install**
4. Reload plugins

PythonDepManager will automatically install PlexSync's Python dependencies (plexapi, tenacity, pydantic, persist-queue) when the plugin loads.

## Step 2: Install PlexSync

### Method A: From Stash Community Plugins (Recommended)

If PlexSync is available in the Stash community plugin repository:

1. Go to **Settings > Plugins > Available Plugins**
2. Search for "PlexSync"
3. Click **Install**
4. Continue to [Step 3: Reload Plugins](#step-3-reload-plugins)

### Method B: Manual Installation

1. Clone or download the PlexSync repository:
   ```bash
   git clone https://github.com/your-repo/PlexSync.git
   ```

2. Copy the PlexSync folder to your Stash plugins directory:

   **Bare metal installation:**
   ```bash
   cp -r PlexSync ~/.stash/plugins/PlexSync/
   ```

   **Docker installation:**
   ```bash
   # Common Docker paths:
   cp -r PlexSync /root/.stash/plugins/PlexSync/
   # or
   cp -r PlexSync /config/plugins/PlexSync/
   ```

3. Verify the folder structure matches:
   ```
   PlexSync/
     PlexSync.py
     PlexSync.yml
     requirements.txt
     hooks/
     plex/
     sync_queue/
     validation/
     worker/
   ```

## Step 3: Reload Plugins

1. Go to **Settings > Plugins**
2. Click the **Reload Plugins** button
3. PlexSync should appear in the plugin list
4. Check for any errors in Stash logs (Settings > Logs)

If PlexSync doesn't appear, check that:
- The folder is in the correct plugins directory
- PythonDepManager is installed
- All required files are present

## Step 4: Configure PlexSync

1. Go to **Settings > Plugins > PlexSync**
2. Set the required fields:

| Setting | Description | Example |
|---------|-------------|---------|
| `plex_url` | Your Plex server URL | `http://192.168.1.100:32400` |
| `plex_token` | Your Plex authentication token | (see below) |
| `plex_library` | Name of your Plex library | `Adult` |

3. Click **Save**

For all available settings, see the [Configuration Reference](config.md).

## Getting Your Plex Token

Your Plex token authenticates PlexSync with your Plex server. Here are two methods to obtain it:

### Option 1: From Plex Web App

1. Log into your Plex server via web browser (e.g., `http://your-plex-ip:32400/web`)
2. Play any media file
3. Open browser developer tools (press **F12** or right-click > Inspect)
4. Go to the **Network** tab
5. Look for requests to your Plex server
6. Find `X-Plex-Token` in the request headers or URL parameters
7. Copy the token value

### Option 2: From Plex Settings File

1. Locate your Plex Media Server preferences file:
   - **Windows:** `%LOCALAPPDATA%\Plex Media Server\Preferences.xml`
   - **macOS:** `~/Library/Application Support/Plex Media Server/Preferences.xml`
   - **Linux:** `/var/lib/plexmediaserver/Library/Application Support/Plex Media Server/Preferences.xml`
2. Open the file and find the `PlexOnlineToken` attribute
3. Copy the token value

For more details, see the [Plex support article on authentication tokens](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/).

## Docker Considerations

When running Stash and/or Plex in Docker containers, pay attention to:

### Path Mapping

PlexSync matches Plex items by file path. **Both Stash and Plex must see files at the same path** for matching to work.

Example docker-compose volume configuration:
```yaml
services:
  stash:
    volumes:
      - /mnt/media:/data/media  # Media files
      - ./stash-config:/root/.stash

  plex:
    volumes:
      - /mnt/media:/data/media  # Same path mapping as Stash
      - ./plex-config:/config
```

If paths differ between containers (e.g., Stash sees `/data/videos/` but Plex sees `/media/videos/`), matching will fail.

### Network Configuration

For the `plex_url` setting:

- **Same Docker network:** Use the container name (e.g., `http://plex:32400`)
- **Host network mode:** Use `localhost` or `127.0.0.1`
- **Different networks:** Use `host.docker.internal` (Docker Desktop) or the host IP

## Verifying Installation

1. Update any scene in Stash (edit title, add a performer, etc.)
2. Check Stash logs (**Settings > Logs**) for `[PlexSync]` messages
3. Look for success messages:
   ```
   [PlexSync Hook] Enqueued sync job for scene 123
   [PlexSync Worker] Job completed
   ```
4. Check Plex for updated metadata (may take a few seconds)

## Data Directory

PlexSync stores runtime data in a `data/` subdirectory:

| File/Folder | Purpose |
|-------------|---------|
| `queue/` | Persistent queue database (survives restarts) |
| `dlq.db` | Dead letter queue for permanently failed jobs |
| `sync_timestamps.json` | Tracks last sync time per scene |
| `device_id.json` | Persistent Plex device identity |

### Data Directory Locations

| Environment | Path |
|-------------|------|
| Bare metal | `~/.stash/plugins/PlexSync/data/` |
| Docker (default) | `/root/.stash/plugins/PlexSync/data/` |
| Docker (custom) | `/config/plugins/PlexSync/data/` |

The data directory can be overridden via the `STASH_PLUGIN_DATA` environment variable.

## Troubleshooting Installation

### PythonDepManager Not Installed

**Symptom:** Error about missing modules (`ModuleNotFoundError: No module named 'plexapi'`)

**Solution:** Install PythonDepManager plugin first (see [Step 1](#step-1-install-pythondepmanager))

### Plugin Not Appearing

**Symptom:** PlexSync doesn't show in the plugins list after reload

**Solutions:**
- Verify the folder is in the correct plugins directory
- Check that `PlexSync.yml` exists in the folder
- Look for errors in Stash logs

### Permission Errors

**Symptom:** Errors accessing plugin files or data directory

**Solutions:**
- Ensure Stash has read/write access to the plugins folder
- Check file ownership matches the Stash process user
- Docker: verify volume mount permissions

### Configuration Errors

**Symptom:** Log messages like `Configuration error: plex_url must start with http://`

**Solutions:**
- Ensure `plex_url` includes the protocol (`http://` or `https://`)
- Verify `plex_token` is at least 10 characters
- Check the [Configuration Reference](config.md) for valid value ranges

For more troubleshooting help, see the [Troubleshooting Guide](troubleshoot.md).

## Next Steps

- **[Configuration Reference](config.md)** - Tune PlexSync settings for your setup
- **[Troubleshooting Guide](troubleshoot.md)** - Resolve common issues
