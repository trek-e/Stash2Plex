# PlexSync Improvements

## What This Is

Improvements to the PlexSync plugin for Stash, which syncs metadata from Stash to Plex. The current version has timing and reliability issues — syncs fail when Plex is unavailable, late Stash metadata updates don't propagate, and matching sometimes fails even when a match exists.

## Core Value

Reliable sync: when metadata changes in Stash, it eventually reaches Plex — even if Plex was temporarily unavailable or Stash hadn't finished indexing yet.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Retry logic when Plex is unavailable (e.g., during backup)
- [ ] Late update handling — push metadata to Plex when Stash updates after initial sync
- [ ] Input sanitization — validate/clean data before sending to Plex API
- [ ] Improved matching logic — reduce false negatives when finding Plex items for Stash scenes

### Out of Scope

- Plex → Stash sync — Stash remains the primary metadata source
- New features unrelated to reliability/security — focus is fixing existing functionality

## Context

**Current state:** PlexSync is a Python plugin from the stashapp/CommunityScripts repo. It fires on Stash scene updates and pushes metadata to Plex.

**Known issues:**
- If Plex is down (backup, restart), sync fails silently with no retry
- If Stash hasn't indexed a file when it's first added, the initial sync has no metadata — later updates don't trigger a re-sync
- Matching logic sometimes misses matches, requiring manual intervention
- No input validation between systems

**Source:** https://github.com/stashapp/CommunityScripts/tree/main/plugins/PlexSync

## Constraints

- **Compatibility**: Must work with existing Stash plugin architecture
- **Dependencies**: Should minimize new dependencies beyond what's already in requirements.txt (stashapi, unidecode, requests)

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Fork locally for development | Need to test changes against real Stash/Plex setup | — Pending |

---
*Last updated: 2025-01-24 after initialization*
