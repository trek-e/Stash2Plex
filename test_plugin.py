#!/usr/bin/env python3
import sys
import json

print("[Stash2Plex] SCRIPT STARTED", file=sys.stderr)
try:
    data = sys.stdin.read()
    print(f"[Stash2Plex] INPUT: {data[:200]}", file=sys.stderr)
except Exception as e:
    print(f"[Stash2Plex] ERROR: {e}", file=sys.stderr)
print(json.dumps({"output": "ok"}))
