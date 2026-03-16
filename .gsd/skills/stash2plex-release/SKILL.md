---
name: stash2plex-release
description: Release Stash2Plex plugin versions. Handles tagging, plugin zip, index.yml, and GitHub releases. Use when asked to release, tag, version bump, or ship a new version of Stash2Plex.
---

# Stash2Plex Release

## Overview

Stash2Plex is a Stash plugin distributed as a zip via a GitHub-hosted plugin index. Stash's plugin manager downloads from `index.yml` on the `main` branch.

## Release Flow

Releases are **automated via GitHub Actions** (`.github/workflows/release.yml`). The workflow triggers on any `v1.5.*` tag push and handles everything:

1. Builds `Stash2Plex.zip` with the correct file list
2. Updates `Stash2Plex.yml` version field
3. Updates `index.yml` (version, date, sha256)
4. Commits updated files back to `main`
5. Creates a GitHub release with the zip attached
6. Auto-generates release notes from commit history

### To release a new version

```bash
git tag v1.5.XX
git push origin v1.5.XX
```

That's it. The CI does the rest.

### When to release manually

Only if the CI workflow fails or needs to be bypassed. In that case, follow the manual steps below.

## Manual Release Steps (fallback only)

### 1. Update version in `Stash2Plex.yml`

```yaml
version: X.Y.Z
```

### 2. Build the zip

```bash
rm -f Stash2Plex.zip
zip -r Stash2Plex.zip \
  Stash2Plex.py Stash2Plex.yml requirements.txt \
  worker/ sync_queue/ plex/ validation/ shared/ hooks/ reconciliation/ \
  -x "*/test*" "*/__pycache__/*" "*.pyc" "*/.pytest*"
```

**Zip contents** (no tests, no pycache):
- `Stash2Plex.py` — main entry point
- `Stash2Plex.yml` — plugin manifest (version must match)
- `requirements.txt` — Python dependencies
- `worker/` — queue worker, processor, circuit breaker, backoff, rate limiter, stats
- `sync_queue/` — persistent queue, DLQ, operations
- `plex/` — Plex client, matcher, cache, health, device identity, exceptions
- `validation/` — config validation, metadata, sanitizers, obfuscation
- `shared/` — shared logging
- `hooks/` — Stash hook handlers
- `reconciliation/` — gap detection, engine, scheduler

### 3. Compute SHA256 and update `index.yml`

```bash
SHA=$(shasum -a 256 Stash2Plex.zip | awk '{print $1}')
```

Update these fields in `index.yml`:
```yaml
  version: X.Y.Z
  date: "YYYY-MM-DD HH:MM:SS"
  sha256: <computed hash>
```

### 4. Commit, tag, push

```bash
git add Stash2Plex.yml index.yml Stash2Plex.zip
git commit -m "chore: update plugin index and zip for vX.Y.Z"
git tag vX.Y.Z
git push origin main --tags
```

### 5. Create GitHub release

```bash
gh release create vX.Y.Z --title "vX.Y.Z" --notes "..." Stash2Plex.zip
```

## Key Files

| File | Purpose |
|------|---------|
| `Stash2Plex.yml` | Plugin manifest — `version` field must match release |
| `index.yml` | Plugin index — Stash downloads from here (`version`, `date`, `sha256`, `path`) |
| `Stash2Plex.zip` | Distributable plugin archive |
| `.github/workflows/release.yml` | CI workflow that automates the release |

## Versioning

- Current line: `1.5.x` (patch bumps)
- Tags: `v1.5.XX` (e.g., `v1.5.30`)
- Tag pattern in CI trigger: `v1.5.*`
- If major version changes, update the tag pattern in `.github/workflows/release.yml`

## Testing

Run the full test suite before tagging:

```bash
.venv/bin/pytest tests/ -v
```

All tests must pass. Coverage threshold is 80%.
