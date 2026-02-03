---
phase: 10-metadata-sync-toggles
captured: 2026-02-03
status: ready-for-planning
---

# Phase 10: Metadata Sync Toggles - Context

**Goal:** Add toggles for enabling/disabling each metadata category sync

## Discussion Areas Covered

### 1. Toggle Granularity

| Decision | Status | Choice |
|----------|--------|--------|
| Toggle level | LOCKED | Individual fields (one toggle per syncable field) |
| Fields covered | LOCKED | All syncable fields get toggles |
| Title toggle | LOCKED | Title always synced, not toggle-able (required for matching) |
| Master toggle | LOCKED | Yes, include a master enable/disable toggle |

### 2. Default Behavior

| Decision | Status | Choice |
|----------|--------|--------|
| Default state | LOCKED | All enabled by default |
| New fields | LOCKED | New fields default ON |

### 3. Configuration Location

| Decision | Status | Choice |
|----------|--------|--------|
| Config method | LOCKED | Stash plugin settings only (not config file) |
| UI organization | LOCKED | New 'Field Sync' section in settings |
| Help text | LOCKED | Yes, descriptions for each toggle |
| Toggle OFF behavior | Claude discretion | - |
| Settings migration | Claude discretion | - |
| UI pattern (checkboxes vs multi-select) | Claude discretion | - |

### 4. Interaction with Preserve Mode

| Decision | Status | Choice |
|----------|--------|--------|
| Toggle OFF + preserve OFF | LOCKED | Skip field entirely (Plex keeps existing value) |
| Preserve ON + toggle ON | LOCKED | Preserve behavior unchanged (skip if Plex has value) |
| Master toggle priority | LOCKED | Master is convenience only (individual toggles can override) |

## Syncable Fields

Based on existing codebase (worker/processor.py), these fields should have toggles:

**Scalar fields:**
- studio
- summary (details)
- tagline
- date (release date)

**List fields:**
- performers (actors)
- tags (genres)

**Media fields:**
- poster
- background (fanart)

**Collection:**
- collection

**Always synced (no toggle):**
- title (required for matching)
- path (required for matching)

## Implementation Notes

1. **Toggle evaluation order:**
   - Check master toggle first (if OFF and individual toggle OFF, skip)
   - Check individual field toggle
   - If toggle ON, apply existing preserve_plex_edits logic

2. **Master toggle behavior:**
   - Master toggle is convenience for bulk enable/disable
   - Setting master OFF sets all individual toggles OFF
   - Setting master ON sets all individual toggles ON
   - Individual toggles can then be adjusted independently
   - Master does NOT override individual settings after initial set

3. **Field sync decision tree:**
   ```
   if field_toggle is OFF:
       skip field entirely (no clear, no sync)
   elif preserve_plex_edits is ON and plex_has_value:
       skip field (preserve existing)
   else:
       sync field (apply LOCKED clearing logic from Phase 9)
   ```

4. **Stash plugin settings format:**
   - Use Stash's boolean setting type for each toggle
   - Group under "Field Sync" section
   - Include descriptive help text

## Claude Discretion Items

- **Toggle OFF behavior details:** Claude to determine exact skip implementation
- **Settings migration:** Claude to decide if migration from old config needed
- **UI pattern:** Claude to choose between individual checkboxes or multi-select
- **Setting naming conventions:** Claude to determine Stash setting key names

---

*Captured: 2026-02-03*
*Ready for: /gsd:plan-phase 10*
