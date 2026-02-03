#!/bin/bash

docker exec -i stash sh -c 'cat > /config/plugins/test/PlexSync/PlexSync.py' << 'ENDSCRIPT'
#!/usr/bin/env python3
import sys
import json

print("[PlexSync] SCRIPT STARTED", file=sys.stderr)
try:
    data = sys.stdin.read()
    print("[PlexSync] INPUT: " + data[:200], file=sys.stderr)
except Exception as e:
    print("[PlexSync] ERROR: " + str(e), file=sys.stderr)
print(json.dumps({"output": "ok"}))
ENDSCRIPT

docker exec -i stash chown stash:stash /config/plugins/test/PlexSync/PlexSync.py
docker restart stash

echo "Done. Now edit a scene in Stash, then run:"
echo "docker logs stash 2>&1 | grep -i plexsync | tail -10"
