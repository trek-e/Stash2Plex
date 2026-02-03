# Phase 10: Metadata Sync Toggles - Research

**Researched:** 2026-02-03
**Domain:** Stash plugin configuration / field-level sync control
**Confidence:** HIGH

## Summary

This phase adds per-field toggles to control which metadata categories sync from Stash to Plex. The implementation is straightforward because:

1. **No external libraries needed** - Uses existing Pydantic v2 for config validation, Stash's built-in settings system for UI
2. **Well-defined scope** - 9 syncable fields (locked decision), all use BOOLEAN toggles with default ON
3. **Clear integration points** - `validation/config.py` (add toggle fields), `worker/processor.py` (`_update_metadata` checks toggles), `PlexSync.yml` (add settings UI)

The existing codebase already handles boolean settings with string coercion (e.g., `strict_matching`, `preserve_plex_edits`), providing a proven pattern to follow. The decision tree is simple: toggle OFF means skip entirely (no clear, no sync).

**Primary recommendation:** Add 9 boolean fields to PlexSyncConfig with defaults True, add corresponding settings to PlexSync.yml, then wrap each field sync block in processor.py with a toggle check.

## Standard Stack

This phase uses the existing project stack with no new dependencies.

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pydantic | 2.x | Config validation with type coercion | Already in use for PlexSyncConfig |
| PyYAML | - | Plugin manifest parsing (by Stash) | Stash-provided, no explicit dependency |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest | 8.x | Testing new toggle logic | Already configured with 80% coverage |
| unittest.mock | stdlib | Mocking config in tests | Per project decision (01-02) |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Individual booleans | Pydantic nested model | More complex, no clear benefit |
| BOOLEAN type | STRING (comma-separated list) | Stash UI less intuitive for users |
| 9 separate settings | Multi-select widget | Stash doesn't support multi-select for plugin settings |

**Installation:** No new packages required.

## Architecture Patterns

### Configuration Extension Pattern

Extend `PlexSyncConfig` with new boolean fields using the same pattern as existing booleans:

```python
# Source: /Users/trekkie/projects/PlexSync/validation/config.py (existing pattern)
class PlexSyncConfig(BaseModel):
    # ... existing fields ...

    # Field sync toggles - all default True (enabled)
    sync_studio: bool = Field(default=True, description="Sync studio field to Plex")
    sync_summary: bool = Field(default=True, description="Sync summary (details) to Plex")
    # ... etc

    @field_validator('sync_studio', 'sync_summary', ..., mode='before')
    @classmethod
    def validate_sync_booleans(cls, v):
        """Ensure boolean fields accept string values from Stash settings."""
        # Reuse existing validate_booleans logic
```

### Toggle Check Pattern in Processor

Wrap each field sync block with a toggle check before existing preserve_plex_edits logic:

```python
# Pattern for _update_metadata in processor.py
def _update_metadata(self, plex_item, data: dict):
    # TOGGLE CHECK FIRST, then existing preserve logic
    if self.config.sync_studio and 'studio' in data:
        # existing studio sync code
        studio_value = data.get('studio')
        if studio_value is None or studio_value == '':
            edits['studio.value'] = ''
        else:
            # ... existing preserve/sync logic
```

### Stash Settings YAML Pattern

Stash plugin settings use flat YAML with three types: `STRING`, `NUMBER`, `BOOLEAN`.

```yaml
# Source: https://pkg.go.dev/github.com/stashapp/stash/pkg/plugin
settings:
  setting_key:
    displayName: "Display Name for UI"
    description: "Help text shown to users"
    type: BOOLEAN
```

### Recommended Project Structure

No new files needed. Changes to existing files:

```
validation/
  config.py             # Add 10 toggle fields (9 individual + 1 master)
worker/
  processor.py          # Add toggle checks before field sync blocks
PlexSync.yml            # Add 10 settings entries in "Field Sync" section
tests/
  validation/
    test_config.py      # Add toggle validation tests
  worker/
    test_processor.py   # Add toggle behavior tests
```

### Anti-Patterns to Avoid
- **Checking toggle inside existing if blocks:** Always check toggle FIRST, before any other logic. Don't nest toggle check inside preserve_plex_edits check.
- **Adding toggle for title:** Title is LOCKED as always-synced (required for matching).
- **Complex master toggle override:** Master should only bulk-set individual toggles, not override them at runtime.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Boolean string parsing | Custom parser | Pydantic field_validator | Already has "true"/"1"/"yes" handling |
| Settings UI | Custom UI | Stash plugin settings | Native integration with Stash UI |
| Config validation | Manual checks | Pydantic model | Type coercion, defaults, error messages |

**Key insight:** The existing `validate_booleans` validator in PlexSyncConfig already handles string-to-bool coercion for Stash settings. Reuse it for all new toggle fields.

## Common Pitfalls

### Pitfall 1: Forgetting to Update YAML Settings
**What goes wrong:** Settings added to Python config but not to PlexSync.yml - users can't configure them
**Why it happens:** Two files must stay in sync (Python model + YAML manifest)
**How to avoid:** Checklist: for each config field, verify corresponding YAML setting exists
**Warning signs:** Tests pass but feature not visible in Stash UI

### Pitfall 2: Toggle Check After Preserve Check
**What goes wrong:** Toggle OFF but preserve mode still runs, causing unexpected behavior
**Why it happens:** Natural to add toggle check inside existing if blocks
**How to avoid:** Pattern is: `if toggle AND field_in_data:` then existing logic
**Warning signs:** Field syncs even when toggle is OFF in certain edge cases

### Pitfall 3: Breaking Clearing Logic
**What goes wrong:** Toggle OFF interpreted as "clear field" instead of "skip field"
**Why it happens:** LOCKED decision from Phase 9: missing/empty = clear. Must distinguish "toggle OFF" from "value is empty"
**How to avoid:** Toggle OFF = skip entire block (don't even check if key exists in data)
**Warning signs:** Fields get cleared when user disables sync for them

### Pitfall 4: Master Toggle Overwriting Individual Settings
**What goes wrong:** User sets master OFF, then master ON, losing their individual customizations
**Why it happens:** Master toggle actually modifies individual toggle state
**How to avoid:** Master is UI convenience only - sets all toggles, but doesn't override them at sync time
**Warning signs:** User reports toggle settings "resetting"

### Pitfall 5: Inconsistent Setting Key Names
**What goes wrong:** Python field name doesn't match Stash setting key, causing silent config failures
**Why it happens:** Stash passes settings by key name, must match exactly
**How to avoid:** Use snake_case consistently: `sync_studio` in Python and YAML
**Warning signs:** Setting value is always default despite user changing it

## Code Examples

### Adding Toggle Fields to PlexSyncConfig

```python
# Source: validation/config.py - extend PlexSyncConfig
# Add after existing preserve_plex_edits field

    # =========================================================================
    # Field Sync Toggles (all default True = enabled)
    # =========================================================================

    sync_master: bool = Field(
        default=True,
        description="Master toggle to enable/disable all field syncing"
    )
    sync_studio: bool = Field(
        default=True,
        description="Sync studio name to Plex"
    )
    sync_summary: bool = Field(
        default=True,
        description="Sync summary/details to Plex"
    )
    sync_tagline: bool = Field(
        default=True,
        description="Sync tagline to Plex"
    )
    sync_date: bool = Field(
        default=True,
        description="Sync release date to Plex"
    )
    sync_performers: bool = Field(
        default=True,
        description="Sync performers as Plex actors"
    )
    sync_tags: bool = Field(
        default=True,
        description="Sync tags as Plex genres"
    )
    sync_poster: bool = Field(
        default=True,
        description="Sync poster image to Plex"
    )
    sync_background: bool = Field(
        default=True,
        description="Sync background/fanart image to Plex"
    )
    sync_collection: bool = Field(
        default=True,
        description="Add to Plex collection based on studio"
    )

    # Add to existing validator decorator list
    @field_validator(
        'strict_matching', 'preserve_plex_edits',
        'sync_master', 'sync_studio', 'sync_summary', 'sync_tagline',
        'sync_date', 'sync_performers', 'sync_tags', 'sync_poster',
        'sync_background', 'sync_collection',
        mode='before'
    )
    @classmethod
    def validate_booleans(cls, v):
        # ... existing implementation
```

### Adding Settings to PlexSync.yml

```yaml
# Source: PlexSync.yml - add to settings section
# Group under "Field Sync" comment section

  # ----- Field Sync Settings -----
  sync_master:
    displayName: "Enable Field Sync"
    description: "Master toggle to enable/disable all metadata field syncing"
    type: BOOLEAN
  sync_studio:
    displayName: "Sync Studio"
    description: "Sync studio name from Stash to Plex"
    type: BOOLEAN
  sync_summary:
    displayName: "Sync Summary"
    description: "Sync description/details from Stash to Plex"
    type: BOOLEAN
  sync_tagline:
    displayName: "Sync Tagline"
    description: "Sync tagline from Stash to Plex"
    type: BOOLEAN
  sync_date:
    displayName: "Sync Date"
    description: "Sync release date from Stash to Plex"
    type: BOOLEAN
  sync_performers:
    displayName: "Sync Performers"
    description: "Sync performers as actors in Plex"
    type: BOOLEAN
  sync_tags:
    displayName: "Sync Tags"
    description: "Sync tags as genres in Plex"
    type: BOOLEAN
  sync_poster:
    displayName: "Sync Poster"
    description: "Sync poster image from Stash to Plex"
    type: BOOLEAN
  sync_background:
    displayName: "Sync Background"
    description: "Sync background/fanart image from Stash to Plex"
    type: BOOLEAN
  sync_collection:
    displayName: "Sync Collection"
    description: "Add items to Plex collection based on studio name"
    type: BOOLEAN
```

### Toggle Check Pattern in Processor

```python
# Source: worker/processor.py - _update_metadata method
# Pattern: check toggle FIRST, skip entire block if OFF

def _update_metadata(self, plex_item, data: dict):
    # ... imports and setup ...
    result = PartialSyncResult()
    edits = {}

    # TOGGLE: Check if ANY field sync is enabled
    if not getattr(self.config, 'sync_master', True):
        log_debug("Master sync toggle is OFF - skipping all field syncs")
        return result

    # Handle studio field - check toggle BEFORE data check
    if getattr(self.config, 'sync_studio', True) and 'studio' in data:
        # ... existing studio sync logic unchanged ...
        studio_value = data.get('studio')
        if studio_value is None or studio_value == '':
            edits['studio.value'] = ''
        else:
            sanitized = sanitize_for_plex(studio_value, max_length=MAX_STUDIO_LENGTH)
            if not self.config.preserve_plex_edits or not plex_item.studio:
                edits['studio.value'] = sanitized

    # Handle summary - toggle check pattern
    if getattr(self.config, 'sync_summary', True):
        has_summary_key = 'details' in data or 'summary' in data
        if has_summary_key:
            # ... existing summary logic ...

    # ... similar pattern for all other fields ...
```

### Helper Method for Toggle Checks (Optional)

```python
# Source: worker/processor.py - optional helper for cleaner code
def _is_field_sync_enabled(self, field_name: str) -> bool:
    """
    Check if sync is enabled for a specific field.

    Args:
        field_name: One of: studio, summary, tagline, date, performers, tags, poster, background, collection

    Returns:
        True if field should be synced (master ON and individual toggle ON)
    """
    # Master toggle check
    if not getattr(self.config, 'sync_master', True):
        return False

    # Individual toggle check
    toggle_attr = f'sync_{field_name}'
    return getattr(self.config, toggle_attr, True)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| All-or-nothing sync | Per-field toggles | This phase | Users control which fields sync |
| Config file only | Stash plugin settings | v1.0 | UI-based configuration |

**Deprecated/outdated:**
- None - this is a new feature building on existing patterns

## Open Questions

1. **Master toggle UI behavior**
   - What we know: Master is "convenience only" per CONTEXT.md
   - What's unclear: Does changing master in UI immediately update all individual toggles, or just affect sync behavior?
   - Recommendation: Master should SET individual toggles (UI shows them all change), but individual toggles can then be changed independently. This is pure UI behavior in Stash, not plugin logic.

2. **Migration from old configs**
   - What we know: No toggle settings existed before
   - What's unclear: What if user has old config without toggle keys?
   - Recommendation: Pydantic defaults handle this - all toggles default True. No migration code needed.

3. **Toggle OFF + key present in data**
   - What we know: Toggle OFF = skip field entirely
   - What's unclear: Does "skip" mean don't check the data dict at all, or check but don't sync?
   - Recommendation: Don't even check data dict. Pattern is `if toggle_enabled and 'key' in data:` - if toggle is OFF, the `and` short-circuits.

## Sources

### Primary (HIGH confidence)
- `/Users/trekkie/projects/PlexSync/validation/config.py` - Existing PlexSyncConfig pattern
- `/Users/trekkie/projects/PlexSync/worker/processor.py` - Current _update_metadata implementation
- `/Users/trekkie/projects/PlexSync/PlexSync.yml` - Existing settings format
- https://pkg.go.dev/github.com/stashapp/stash/pkg/plugin - Stash plugin SettingConfig structure

### Secondary (MEDIUM confidence)
- `/Users/trekkie/projects/PlexSync/tests/validation/test_config.py` - Test patterns for boolean fields

### Tertiary (LOW confidence)
- Web search results about Stash plugin settings - confirmed BOOLEAN type support

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - no new dependencies, uses existing patterns
- Architecture: HIGH - clear extension of existing config/processor
- Pitfalls: HIGH - derived from codebase analysis and LOCKED decisions

**Research date:** 2026-02-03
**Valid until:** 60 days (stable domain, internal patterns)
