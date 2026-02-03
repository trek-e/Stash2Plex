# Phase 9: Reliability Hardening - Research

**Researched:** 2026-02-03
**Domain:** Input validation, data sanitization, error handling
**Confidence:** HIGH

## Summary

PlexSync already has robust sanitization infrastructure in place (`validation/sanitizers.py`), comprehensive error classification (`validation/errors.py`), and field validation (`validation/metadata.py`). This phase focuses on hardening edge cases not yet covered: very long fields, emoji/special Unicode, missing optional fields (with LOCKED user decision to clear Plex values), and malformed API responses.

The existing `sanitize_for_plex()` function handles most Unicode edge cases (control characters, smart quotes, normalization to NFC) and truncates at 255 characters by default. Tests in `tests/validation/test_sanitizers.py` cover extensive edge cases. The key gaps are: 1) Plex field length limits are not officially documented, 2) emoji support is uncertain (historical issues in plexapi), 3) list fields (performers, tags) lack explicit limits, and 4) partial field update failure handling is basic.

**Primary recommendation:** Build on existing sanitization by adding emoji handling, verifying Plex's practical field limits through testing, implementing the LOCKED user decision for missing optional fields (clear existing value), and adding granular error handling for partial field update failures.

## Standard Stack

The existing validation infrastructure is well-established:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pydantic | 2.x | Data validation | Industry standard for Python validation, already integrated |
| unicodedata | stdlib | Unicode normalization | Python standard library, no dependencies |
| plexapi | >=4.17.0 | Plex API client | Official Python binding for Plex API |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| logging | stdlib | Debug/warning output | Tracking sanitization decisions |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Custom validation | marshmallow | pydantic already integrated, no benefit to switching |
| String normalization | ftfy (fixes text for you) | Adds dependency, unicodedata sufficient |

**Installation:**
```bash
# No new dependencies needed - use existing stack
```

## Architecture Patterns

### Recommended Approach
```
validation/
├── sanitizers.py       # Text sanitization (already exists)
├── metadata.py         # Field validation (already exists)
├── errors.py           # Error classification (already exists)
└── limits.py           # NEW: Plex field limits as constants
```

### Pattern 1: Defensive Sanitization with Logging
**What:** Sanitize all string fields before validation, log when changes occur
**When to use:** All user-generated text fields (title, description, performer names, tags)
**Example:**
```python
# Source: Existing validation/sanitizers.py (lines 30-91)
def sanitize_for_plex(
    text: str,
    max_length: int = 255,
    logger: Optional[logging.Logger] = None
) -> str:
    """
    Sanitize text for safe use with Plex API.

    1. Returns empty string if None/empty
    2. Normalizes Unicode to NFC form
    3. Removes control characters (Cc) and format characters (Cf)
    4. Converts smart quotes/dashes to ASCII
    5. Collapses whitespace
    6. Truncates at max_length, preferring word boundaries
    """
    if not text:
        return ''

    # Normalize, remove control chars, convert smart quotes
    text = unicodedata.normalize('NFC', text)
    text = ''.join(char for char in text if unicodedata.category(char) not in ('Cc', 'Cf'))
    text = text.translate(QUOTE_MAP)
    text = ' '.join(text.split())

    # Truncate with word boundary preference
    if max_length > 0 and len(text) > max_length:
        truncated = text[:max_length]
        last_space = truncated.rfind(' ')
        if last_space > max_length * 0.8:
            text = truncated[:last_space]
        else:
            text = truncated

    if logger and text != original:
        logger.debug(f"Sanitized text: {len(original)} -> {len(text)} chars")

    return text
```

### Pattern 2: Missing Optional Fields - Clear Existing Value (LOCKED DECISION)
**What:** When Stash provides None for optional field, explicitly clear the Plex value
**When to use:** All optional metadata fields (studio, summary, tagline, date, performers, tags)
**Example:**
```python
# Source: User decision from CONTEXT.md
# When data.get('studio') is None, we must CLEAR plex_item.studio
# Don't preserve existing Plex value - clear it explicitly

if 'studio' in data:  # Field present in sync job
    if data['studio'] is None or data['studio'] == '':
        # LOCKED DECISION: Clear existing Plex value
        edits['studio.value'] = ''
    else:
        edits['studio.value'] = sanitize_for_plex(data['studio'], max_length=255)
```

### Pattern 3: Partial Field Update with Granular Error Handling
**What:** Wrap each field update in try-except, continue on failure, aggregate warnings
**When to use:** When updating multiple independent fields (performers, tags, collections)
**Example:**
```python
# Source: Existing worker/processor.py pattern (lines 656-737)
# Extended with granular error handling

warnings = []

# Each field update is independent - don't fail entire job if one field fails
try:
    if data.get('studio'):
        edits['studio.value'] = sanitize_for_plex(data['studio'])
except Exception as e:
    warnings.append(f"Failed to update studio: {e}")

try:
    if performers := data.get('performers', []):
        # Update actors
        actor_edits = build_actor_edits(performers)
        plex_item.edit(**actor_edits)
except Exception as e:
    warnings.append(f"Failed to update performers: {e}")

# Log aggregated warnings at end
if warnings:
    log_warn(f"Partial sync completed with {len(warnings)} warnings: {'; '.join(warnings)}")
```

### Anti-Patterns to Avoid
- **Fail entire job on single field error:** If studio update fails, still sync title/performers
- **Preserving malformed data:** Always sanitize, never pass through unchecked
- **Silent truncation:** Log when truncation occurs so users know data was shortened
- **Assuming Plex accepts unlimited length:** Always enforce max_length limits

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Unicode normalization | Custom combining char logic | `unicodedata.normalize('NFC', text)` | Handles all Unicode edge cases, composing/decomposing chars |
| Control character removal | Regex blacklist | `unicodedata.category(char) not in ('Cc', 'Cf')` | Unicode-aware, catches all control chars including zero-width |
| Smart quote conversion | Multiple str.replace() | `str.translate(QUOTE_MAP)` | Single pass, efficient, extensible |
| Word boundary truncation | Split/rejoin logic | Existing `sanitize_for_plex()` | Already tested, handles 80% threshold |
| Emoji detection/stripping | Regex patterns | `unicodedata.category(char) == 'So'` | Unicode-aware, covers all emoji |

**Key insight:** Unicode handling is complex with many edge cases (combining characters, variation selectors, zero-width joiners). Python's `unicodedata` module is battle-tested and handles cases you won't think of.

## Common Pitfalls

### Pitfall 1: Assuming Plex Field Limits Match Database Limits
**What goes wrong:** Text fields may have practical limits below database VARCHAR sizes
**Why it happens:** Plex API may enforce limits (e.g., UI restrictions, XML size) separate from database schema
**How to avoid:** Test empirically with progressively longer strings, document actual limits as constants
**Warning signs:**
- API accepts data but Plex UI truncates display
- No error returned but field value shorter than sent
- Silent failures on very long descriptions

### Pitfall 2: Emoji/Symbol Support Uncertainty
**What goes wrong:** Emojis may display as boxes, crash XML parsers, or get stripped silently
**Why it happens:** Plex's XML-based protocol and older database encodings may not handle all Unicode
**How to avoid:** Test with common emojis (😀 U+1F600), symbols (♠ U+2660), and decide: pass-through, strip, or convert to text
**Warning signs:**
- GitHub issue #147 in plexapi shows historical Unicode encoding errors
- Plex forum posts mention "Gap in modern Unicode support" (2024)
- Anime tags with multiplication sign (×) break in Plex

### Pitfall 3: List Field Length Limits Unknown
**What goes wrong:** Adding 500 performers may succeed in API but crash Plex UI or exceed database limits
**Why it happens:** Plex displays limited actors (5 visible in UI) but storage limit unclear
**How to avoid:** Impose practical limits (e.g., 50 performers, 20 tags) based on common usage patterns
**Warning signs:**
- Plex forums mention display limit of 5 actors, 2 genre tags in UI
- No documented maximum for stored values
- Database performance degrades with large tag lists

### Pitfall 4: Empty After Sanitization
**What goes wrong:** Field like `title="   \x00   "` becomes empty string after sanitization
**Why it happens:** Sanitization removes control chars and collapses whitespace, leaving nothing
**How to avoid:** Existing code handles this - empty title raises ValueError in metadata validation
**Warning signs:**
- Tests already cover: `sanitize_for_plex("   ") == ""`
- Validation catches empty required fields: `if not sanitized: raise ValueError`

### Pitfall 5: Partial Update Failure Not Granular
**What goes wrong:** If performer update fails, entire metadata sync fails (title, studio also lost)
**Why it happens:** Current implementation wraps entire _update_metadata() in try-except
**How to avoid:** Wrap each field group (title, performers, tags) separately, collect failures
**Warning signs:**
- One malformed performer name causes entire job to fail
- User sees "sync failed" but title/studio could have succeeded

## Code Examples

Verified patterns from existing codebase:

### Truncation with Word Boundary Preference
```python
# Source: validation/sanitizers.py lines 76-86
if max_length > 0 and len(text) > max_length:
    # Find last space within limit
    truncated = text[:max_length]
    last_space = truncated.rfind(' ')

    # Only use word boundary if it's reasonably close to max_length (>80%)
    if last_space > max_length * 0.8:
        text = truncated[:last_space]
    else:
        text = truncated
```

### Control Character and Format Character Removal
```python
# Source: validation/sanitizers.py lines 65-68
text = ''.join(
    char for char in text
    if unicodedata.category(char) not in ('Cc', 'Cf')
)
```

### Field Validation with Sanitization
```python
# Source: validation/metadata.py lines 61-75
@field_validator('title', mode='before')
@classmethod
def sanitize_title(cls, v: Any) -> str:
    """Sanitize title field, ensuring non-empty string."""
    if v is None:
        raise ValueError("title is required")
    if not isinstance(v, str):
        v = str(v)
    original = v
    sanitized = sanitize_for_plex(v, max_length=255)
    if sanitized != original:
        log.warning(f"Sanitized title: '{original[:50]}...' -> '{sanitized[:50]}...'")
    if not sanitized:
        raise ValueError("title cannot be empty after sanitization")
    return sanitized
```

### Missing Optional Field Handling (Current - will need update)
```python
# Source: worker/processor.py lines 622-645
# Current implementation - NEEDS UPDATE for LOCKED DECISION

if self.config.preserve_plex_edits:
    # Only update fields that are None or empty string in Plex
    if data.get('studio') and not plex_item.studio:
        edits['studio.value'] = data['studio']
else:
    # Stash always wins - overwrite all fields
    if data.get('studio'):  # Only if present in data
        edits['studio.value'] = data['studio']

# ISSUE: If data.get('studio') is None, existing Plex value is preserved
# LOCKED DECISION: Should explicitly clear with edits['studio.value'] = ''
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Pass-through text | Sanitize with unicodedata | Phase 3 (commit d3fff9b) | Prevents crashes from control chars |
| Single max_length | Field-specific limits | Phase 3 | title=255, details=10000 |
| Generic exceptions | Classified errors (Transient/Permanent) | Phase 2 | Proper retry behavior |
| No validation | Pydantic models | Phase 3 | Fail-fast on bad data |

**Deprecated/outdated:**
- Python 2.7 Unicode handling: plexapi issue #147 shows `ascii` codec errors, resolved in Python 3
- Smart quote pass-through: Now converted to ASCII equivalents to avoid display issues

## Open Questions

Things that couldn't be fully resolved:

1. **Plex Field Length Limits**
   - What we know: No official documentation found, plexapi docs don't specify limits
   - What's unclear: Practical limits for title, summary, performer names, tag names
   - Recommendation: Test empirically with progressively longer strings (1000, 5000, 10000 chars)

2. **Emoji Support in Plex**
   - What we know: Historical Unicode issues (plexapi #147), Plex forum mentions gaps in modern Unicode
   - What's unclear: Do emojis display correctly? Are they stored correctly? Do they break XML?
   - Recommendation: Test with sample emojis (😀🎬🎭), add emoji stripping option if needed

3. **List Field Limits (Performers, Tags)**
   - What we know: Plex UI displays 5 actors, no documented storage limit
   - What's unclear: Safe maximum for performers/tags lists (50? 100? 500?)
   - Recommendation: Impose practical limit (50 performers, 20 tags) to prevent issues

4. **RTL/Bidirectional Text**
   - What we know: Unicode normalization to NFC is applied
   - What's unclear: Does Plex display RTL text correctly? Are there rendering issues?
   - Recommendation: Test with Arabic/Hebrew titles if user base includes those languages

5. **Malformed Plex API Responses**
   - What we know: translate_plex_exception() handles plexapi exceptions, HTTP status codes
   - What's unclear: What about partial responses, missing required fields, type mismatches?
   - Recommendation: Add response validation for critical operations (edit, reload)

## Sources

### Primary (HIGH confidence)
- PlexSync codebase analysis:
  - `validation/sanitizers.py` - Comprehensive text sanitization (lines 30-91)
  - `validation/metadata.py` - Pydantic field validation (lines 18-151)
  - `validation/errors.py` - Error classification (lines 34-116)
  - `worker/processor.py` - Metadata update implementation (lines 605-758)
  - `tests/validation/test_sanitizers.py` - 302 lines of edge case tests
  - `tests/integration/test_error_scenarios.py` - Error handling integration tests

### Secondary (MEDIUM confidence)
- [Python PlexAPI Mixins Documentation](https://python-plexapi.readthedocs.io/en/latest/modules/mixins.html) - Field editing methods, no character limits documented
- [Plex Web API Overview](https://github.com/Arcanemagus/plex-api-wiki/Plex-Web-API-Overview) - API structure, limits not specified
- [Python unicodedata documentation](https://docs.python.org/3/library/unicodedata.html) - Unicode normalization and categories

### Tertiary (LOW confidence)
- [Unicode Issue #147 - pkkid/python-plexapi](https://github.com/pkkid/python-plexapi/issues/147) - Historical UnicodeEncodeError with ellipsis character (Python 2.7 era)
- [Gap in modern Unicode support - Plex Forum](https://forums.plex.tv/t/gap-in-modern-unicode-support/925848) - User report of emoji/symbol issues (2024)
- [Plex cast/genre display limits - Plex Forum](https://forums.plex.tv/t/option-to-change-the-limit-of-cast-members-and-genre-tags-displayed-in-plex-web/92549) - UI displays 5 actors, 2 genres (display limit, not storage limit)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Existing infrastructure is well-tested and integrated
- Architecture: HIGH - Clear patterns established in existing code
- Pitfalls: MEDIUM - Emoji support and field limits require empirical testing
- Missing field handling: HIGH - User decision is LOCKED, implementation straightforward
- List field limits: LOW - No official documentation, need to test or impose conservative limits

**Research date:** 2026-02-03
**Valid until:** 2026-03-03 (30 days - stable domain)

## Implementation Notes

**Key takeaways for planner:**

1. **Existing sanitization is strong** - `sanitize_for_plex()` handles most edge cases already
2. **Emoji handling needs decision** - Either pass-through (risky), strip (safe), or convert to text descriptions
3. **LOCKED user decision** - Missing optional fields MUST clear existing Plex values, not preserve them
4. **Field limits unknown** - Need empirical testing or conservative defaults (title=255, summary=10000, lists=50 items)
5. **Partial failure recovery** - Current implementation is all-or-nothing, should be granular per field group
6. **Comprehensive test coverage exists** - `test_sanitizers.py` has 302 lines covering edge cases, extend for new scenarios

**Risk areas:**
- Emoji support uncertainty (test with real Plex instance)
- List field length limits unknown (impose conservative maximums)
- Malformed API responses (add response validation)

**Low risk areas:**
- Unicode normalization (well-tested with unicodedata)
- Control character removal (comprehensive tests exist)
- Truncation logic (tested with word boundaries)
- Error classification (Phase 2 infrastructure solid)
