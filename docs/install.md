# Installation Guide

This guide covers installing Stash2Plex from scratch, including prerequisites, setup steps, and verification.

## Prerequisites

Before installing Stash2Plex, ensure you have:

- **Stash** installed and running ([Stash documentation](https://docs.stashapp.cc/))
- **Plex Media Server** installed and running
- Access to your Stash plugins folder
- A Plex authentication token (see [Getting Your Plex Token](#getting-your-plex-token) below)

## Step 1: Install PythonDepManager (Recommended)

PythonDepManager is a Stash plugin that automatically manages Python dependencies for other plugins. While not strictly required (Stash2Plex can install dependencies via pip as a fallback), it is the recommended approach.

1. In Stash, go to **Settings > Plugins > Available Plugins**
2. Search for "PythonDepManager" or "py_common"
3. Click **Install**
4. Reload plugins

PythonDepManager will automatically install Stash2Plex's Python dependencies (plexapi, pydantic, tenacity, persist-queue, diskcache, stashapp-tools) when the plugin loads.

> **Without PythonDepManager:** Stash2Plex will attempt to install dependencies via pip using Stash's Python interpreter. If that also fails, the error message will show the exact pip command to run manually.

## Step 2: Install Stash2Plex

### Method A: From Stash Community Plugins (Recommended)

If Stash2Plex is available in the Stash community plugin repository:

1. Go to **Settings > Plugins > Available Plugins**
2. Search for "Stash2Plex"
3. Click **Install**
4. Continue to [Step 3: Reload Plugins](#step-3-reload-plugins)

### Method B: Manual Installation

1. Clone or download the Stash2Plex repository:
   ```bash
   git clone https://github.com/trek-e/Stash2Plex.git
   ```

2. Copy the Stash2Plex folder to your Stash plugins directory:

   **Bare metal installation:**
   ```bash
   cp -r Stash2Plex ~/.stash/plugins/Stash2Plex/
   ```

   **Docker installation:**
   ```bash
   # Common Docker paths:
   cp -r Stash2Plex /root/.stash/plugins/Stash2Plex/
   # or
   cp -r Stash2Plex /config/plugins/Stash2Plex/
   ```

3. Verify the folder structure matches:
   ```
   Stash2Plex/
     Stash2Plex.py
     Stash2Plex.yml
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
3. Stash2Plex should appear in the plugin list
4. Check for any errors in Stash logs (Settings > Logs)

If Stash2Plex doesn't appear, check that:
- The folder is in the correct plugins directory
- PythonDepManager is installed
- All required files are present

## Step 4: Configure Stash2Plex

1. Go to **Settings > Plugins > Stash2Plex**
2. Set the required fields:

| Setting | Description | Example |
|---------|-------------|---------|
| `plex_url` | Your Plex server URL | `http://192.168.1.100:32400` |
| `plex_token` | Your Plex authentication token | (see below) |
| `plex_library` | Name of your Plex library | `Adult` |

3. Click **Save**

For all available settings, see the [Configuration Reference](config.md).

## Getting Your Plex Token

Your Plex token authenticates Stash2Plex with your Plex server. Here are two methods to obtain it:

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

Stash2Plex matches Plex items by file path. **Both Stash and Plex must see files at the same path** for matching to work.

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
2. Check Stash logs (**Settings > Logs**) for `[Stash2Plex]` messages
3. Look for success messages:
   ```
   [Stash2Plex Hook] Enqueued sync job for scene 123
   [Stash2Plex Worker] Job completed
   ```
4. Check Plex for updated metadata (may take a few seconds)

## Data Directory

Stash2Plex stores runtime data in a `data/` subdirectory:

| File/Folder | Purpose |
|-------------|---------|
| `queue/` | Persistent queue database (survives restarts) |
| `dlq.db` | Dead letter queue for permanently failed jobs |
| `sync_timestamps.json` | Tracks last sync time per scene |
| `device_id.json` | Persistent Plex device identity |

### Data Directory Locations

| Environment | Path |
|-------------|------|
| Bare metal | `~/.stash/plugins/Stash2Plex/data/` |
| Docker (default) | `/root/.stash/plugins/Stash2Plex/data/` |
| Docker (custom) | `/config/plugins/Stash2Plex/data/` |

The data directory can be overridden via the `STASH_PLUGIN_DATA` environment variable.

## Troubleshooting Installation

### Missing Dependencies (ModuleNotFoundError)

**Symptom:** Error about missing modules (e.g., `ModuleNotFoundError: No module named 'pydantic'`)

**How Stash2Plex installs dependencies (in order):**

1. **PythonDepManager** - Stash's built-in package manager (recommended)
2. **pip fallback** - Installs via `sys.executable -m pip install --break-system-packages` using Stash's Python
3. **Error with instructions** - Shows the exact Python path and pip command to run

**If you see a `ModuleNotFoundError`**, both automatic methods failed. The error message includes the fix:

```
Missing dependencies: ['pydantic']. Install with: /usr/bin/python3 -m pip install --break-system-packages pydantic>=2.0.0
```

Run the command shown in the error. The key is using **the same Python that Stash uses** — running `pip install` from your terminal may install to a different Python.

**Common cause in Docker:** The `pip` command in your shell uses a different Python interpreter than Stash. Always use the Python path shown in the error message.

**PEP 668 "externally managed environment":** If you see this error when manually running pip, add `--break-system-packages` to the command. This is standard for Docker containers running Alpine, Debian 12+, or Ubuntu 23.04+ with Python 3.12+. Stash2Plex v1.2.7+ includes this flag automatically.

### Plugin Not Appearing

**Symptom:** Stash2Plex doesn't show in the plugins list after reload

**Solutions:**
- Verify the folder is in the correct plugins directory
- Check that `Stash2Plex.yml` exists in the folder
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

- **[Configuration Reference](config.md)** - Tune Stash2Plex settings for your setup
- **[Troubleshooting Guide](troubleshoot.md)** - Resolve common issues
