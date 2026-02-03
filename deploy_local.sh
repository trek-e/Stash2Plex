#!/bin/bash
# Deploy PlexSync.py directly to container, bypassing GitHub cache

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONTAINER="stash"
PLUGIN_PATH="/config/plugins/test/PlexSync"

echo "Deploying PlexSync.py to $CONTAINER:$PLUGIN_PATH..."

# Copy the main script
docker cp "$SCRIPT_DIR/PlexSync.py" "$CONTAINER:$PLUGIN_PATH/PlexSync.py"

# Copy all module directories
for dir in sync_queue worker hooks validation plex; do
    if [ -d "$SCRIPT_DIR/$dir" ]; then
        echo "Copying $dir/..."
        docker cp "$SCRIPT_DIR/$dir" "$CONTAINER:$PLUGIN_PATH/"
    fi
done

# Copy requirements if exists
if [ -f "$SCRIPT_DIR/requirements.txt" ]; then
    docker cp "$SCRIPT_DIR/requirements.txt" "$CONTAINER:$PLUGIN_PATH/"
fi

# Fix permissions
echo "Fixing permissions..."
docker exec "$CONTAINER" chown -R stash:stash "$PLUGIN_PATH"

# Restart stash to pick up changes
echo "Restarting stash..."
docker restart "$CONTAINER"

echo ""
echo "Done! Wait a few seconds, then edit a scene in Stash."
echo "Check logs with: docker logs $CONTAINER 2>&1 | grep -i plexsync | tail -30"
