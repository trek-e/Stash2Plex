#!/usr/bin/env python3
import sys
import json

print("[PlexSync] SCRIPT STARTED", file=sys.stderr)
try:
    data = sys.stdin.read()
    print(f"[PlexSync] INPUT: {data[:200]}", file=sys.stderr)
except Exception as e:
    print(f"[PlexSync] ERROR: {e}", file=sys.stderr)
print(json.dumps({"output": "ok"}))
