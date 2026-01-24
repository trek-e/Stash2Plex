# Phase 2: Validation & Error Classification - Research

**Researched:** 2026-01-24
**Domain:** Pydantic validation, text sanitization, HTTP error classification
**Confidence:** HIGH

## Summary

This phase focuses on three interconnected validation domains: metadata validation using Pydantic models, character sanitization for Plex API compatibility, and centralized error classification for retry/DLQ routing. Pydantic v2 (current: v2.12.5) provides the foundation for all validation with sub-millisecond performance suitable for the <100ms hook handler requirement. Text sanitization requires handling control characters, smart quotes, and Unicode normalization - standard Python `unicodedata` and `str.translate()` provide efficient solutions without external dependencies.

Error classification follows established HTTP patterns: 5xx errors and 429 are transient (retry), while 4xx errors (except 429) are permanent (DLQ). The existing `TransientError`/`PermanentError` exception classes from Phase 1 provide the classification interface. A centralized classifier function examines HTTP status codes, exception types, and error messages to route appropriately.

For plugin configuration, `pydantic-settings` extends Pydantic with environment variable support, though for this plugin direct dict validation is sufficient. The existing PlexSync code reveals required configuration: Plex server URL and token, with optional tunables like max_retries (already in worker) and poll_interval.

**Primary recommendation:** Use Pydantic v2 BaseModel for metadata validation with `field_validator` decorators for sanitization; keep validation under 10ms to preserve <100ms hook handler budget.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pydantic | 2.12.5 | Schema validation, type coercion | Rust core (fast), field validators, clear errors |
| pydantic-settings | 2.x | Config validation | Extends BaseModel with env var support |
| unicodedata | Built-in | Unicode normalization | Python stdlib, handles NFC/NFD normalization |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| re | Built-in | Control character regex | Stripping invisible characters |
| html | Built-in | HTML entity handling | Decoding `&amp;` to `&` if present |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Pydantic | dataclasses + manual validation | Pydantic 6x slower than dataclasses but provides built-in validators, coercion, error messages - worth the ~50ms overhead |
| unicodedata + re | clean-text package | External dependency for simple task; stdlib sufficient |
| pydantic-settings | Plain Pydantic BaseModel | BaseModel sufficient if not using env vars; plugin reads config from Stash |

**Installation:**
```bash
pip install pydantic pydantic-settings
```

## Architecture Patterns

### Recommended Project Structure
```
PlexSync/
├── validation/
│   ├── __init__.py
│   ├── metadata.py      # SyncMetadata pydantic model with validators
│   ├── sanitizers.py    # Text sanitization functions
│   ├── config.py        # PlexSyncConfig pydantic model
│   └── errors.py        # Error classification (extend existing)
├── worker/
│   └── processor.py     # Existing TransientError/PermanentError
└── hooks/
    └── handlers.py      # Calls validation before enqueue
```

### Pattern 1: Pydantic Model with Sanitizing Validators
**What:** Use `field_validator` with `mode='before'` to sanitize input before type validation.
**When to use:** Metadata fields that need sanitization (title, summary).

**Example:**
```python
# Source: https://docs.pydantic.dev/latest/concepts/validators/
from pydantic import BaseModel, field_validator
from typing import Optional

class SyncMetadata(BaseModel):
    """Validated metadata for Plex sync."""
    scene_id: int
    title: str
    details: Optional[str] = None
    date: Optional[str] = None
    rating100: Optional[int] = None

    @field_validator('title', 'details', mode='before')
    @classmethod
    def sanitize_text(cls, v: str) -> str:
        if v is None:
            return v
        # Sanitization happens before type validation
        return sanitize_for_plex(v)

    @field_validator('scene_id', mode='after')
    @classmethod
    def validate_positive_id(cls, v: int) -> int:
        if v <= 0:
            raise ValueError('scene_id must be positive')
        return v
```

### Pattern 2: Centralized Error Classifier
**What:** Single function that examines exceptions and returns classification.
**When to use:** Worker error handling to decide retry vs DLQ.

**Example:**
```python
# Source: https://github.com/austind/retryhttp patterns
from worker.processor import TransientError, PermanentError

# Transient HTTP codes (retry)
TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}
# Permanent HTTP codes (DLQ)
PERMANENT_STATUS_CODES = {400, 401, 403, 404, 405, 410, 422}

def classify_error(exc: Exception) -> type:
    """
    Classify exception as TransientError or PermanentError.

    Returns the exception class to raise, not an instance.
    """
    # Check for HTTP response errors
    if hasattr(exc, 'response') and exc.response is not None:
        status = exc.response.status_code
        if status in TRANSIENT_STATUS_CODES:
            return TransientError
        if status in PERMANENT_STATUS_CODES:
            return PermanentError

    # Network errors are transient
    if isinstance(exc, (ConnectionError, TimeoutError, OSError)):
        return TransientError

    # Validation errors are permanent
    if isinstance(exc, (ValueError, TypeError, KeyError)):
        return PermanentError

    # Unknown errors default to transient (safer - allows retry)
    return TransientError
```

### Pattern 3: Config Validation with Sensible Defaults
**What:** Pydantic model for plugin configuration with optional tunables.
**When to use:** Plugin initialization to validate config from Stash.

**Example:**
```python
# Source: https://docs.pydantic.dev/latest/concepts/pydantic_settings/
from pydantic import BaseModel, Field, field_validator
from typing import Optional

class PlexSyncConfig(BaseModel):
    """Plugin configuration with validation."""
    # Required - no defaults
    plex_url: str
    plex_token: str

    # Optional tunables with sensible defaults
    max_retries: int = Field(default=5, ge=1, le=20)
    poll_interval: float = Field(default=1.0, ge=0.1, le=60.0)
    batch_size: int = Field(default=10, ge=1, le=100)

    @field_validator('plex_url', mode='after')
    @classmethod
    def validate_url(cls, v: str) -> str:
        if not v.startswith(('http://', 'https://')):
            raise ValueError('plex_url must start with http:// or https://')
        return v.rstrip('/')  # Normalize: no trailing slash

    @field_validator('plex_token', mode='after')
    @classmethod
    def validate_token(cls, v: str) -> str:
        if len(v) < 10:
            raise ValueError('plex_token appears invalid (too short)')
        return v
```

### Anti-Patterns to Avoid
- **Validation in worker:** Don't validate in the worker thread - validate in hook handler before enqueue so bad data never hits queue
- **Raising during sanitization:** Don't raise exceptions during sanitization - sanitize and log warnings instead (per CONTEXT.md decision)
- **Hand-rolling type coercion:** Don't write manual type conversion - Pydantic handles int/str/float coercion automatically
- **Over-sanitizing:** Don't strip all unicode - only control characters and problematic symbols; preserve international characters

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Type validation | Manual isinstance() checks | Pydantic BaseModel | Handles coercion, nested validation, clear errors |
| Required field checks | Manual `if field is None` | Pydantic required fields | Automatic with proper error messages |
| Unicode normalization | Manual codepoint ranges | `unicodedata.normalize('NFC', text)` | Handles edge cases, composition/decomposition |
| Smart quote conversion | Manual replace chains | `str.translate()` with mapping dict | Single pass, efficient for multiple replacements |
| Control char removal | Regex guessing | `unicodedata.category()` == 'Cc' | Authoritative category identification |
| HTTP error classification | Scattered if/elif | Centralized classifier function | Single source of truth, testable |

**Key insight:** Text sanitization looks simple but Unicode has thousands of edge cases. Use stdlib `unicodedata` for normalization and category checks - it's based on the official Unicode database.

## Common Pitfalls

### Pitfall 1: Validation Performance Blocking Hook Handler
**What goes wrong:** Hook handler exceeds 100ms because validation does too much work.
**Why it happens:** Complex regex, multiple normalization passes, or deep model nesting.
**How to avoid:**
- Keep validation simple: required field checks + sanitization
- Use `mode='before'` validators for sanitization (runs before type checking)
- Profile validation: target <10ms for metadata validation
- Use TypedDict for performance-critical paths (2.5x faster than nested models)
**Warning signs:** Hook handler timing warnings in logs (already implemented in handlers.py).

### Pitfall 2: Overly Strict Validation Rejecting Good Data
**What goes wrong:** Valid metadata rejected due to edge case characters.
**Why it happens:** Aggressive sanitization removes legitimate international characters.
**How to avoid:**
- Only remove control characters (category 'Cc' and 'Cf')
- Preserve letters, numbers, punctuation (categories 'L*', 'N*', 'P*')
- Use NFC normalization (composed form) not NFD (decomposed)
- Test with international characters: Japanese, Hebrew, emoji
**Warning signs:** User reports of metadata not syncing for non-English content.

### Pitfall 3: Inconsistent Error Classification
**What goes wrong:** Same error type sometimes retries, sometimes goes to DLQ.
**Why it happens:** Error classification scattered across codebase, each handler has different logic.
**How to avoid:**
- Single `classify_error()` function used everywhere
- Error classification based on exception type first, HTTP status second
- Log classification decisions for debugging
- Unit tests for all known error types
**Warning signs:** Jobs bouncing between retry and DLQ, inconsistent retry counts.

### Pitfall 4: Config Validation Failing Silently
**What goes wrong:** Plugin runs with invalid config, fails later with cryptic errors.
**Why it happens:** Config loaded as dict, missing keys only discovered during API calls.
**How to avoid:**
- Validate config immediately on plugin init
- Fail loudly with clear error message: "PlexSync config error: plex_url is required"
- Log validated config (masking token) on startup
**Warning signs:** Plugin crashes mid-sync with KeyError or AttributeError.

### Pitfall 5: Plex API Character Issues Not Caught
**What goes wrong:** Sanitized text still causes Plex API 400/500 errors.
**Why it happens:** Unknown character restrictions in Plex API not documented.
**How to avoid:**
- Log sanitization actions at WARN level (per CONTEXT.md)
- Capture actual Plex API error messages for pattern analysis
- Build sanitization rules incrementally based on observed failures
- Keep list of known problematic patterns in sanitizers.py
**Warning signs:** Consistent 400 errors for certain content.

## Code Examples

### Text Sanitization Function
```python
# Source: Python unicodedata stdlib + community patterns
import unicodedata
import re

# Smart quote mappings
QUOTE_MAP = str.maketrans({
    '\u201c': '"',  # left double quote
    '\u201d': '"',  # right double quote
    '\u2018': "'",  # left single quote
    '\u2019': "'",  # right single quote
    '\u2013': '-',  # en dash
    '\u2014': '-',  # em dash
    '\u2026': '...',  # ellipsis
})

def sanitize_for_plex(text: str, max_length: int = 255) -> str:
    """
    Sanitize text for Plex API compatibility.

    - Removes control characters
    - Converts smart quotes to straight quotes
    - Normalizes Unicode (NFC form)
    - Truncates to max_length (word boundary preferred)

    Args:
        text: Input text to sanitize
        max_length: Maximum length (0 = no limit)

    Returns:
        Sanitized text safe for Plex API
    """
    if not text:
        return text

    # Normalize Unicode (composed form)
    text = unicodedata.normalize('NFC', text)

    # Remove control characters (category Cc) and format chars (Cf)
    text = ''.join(
        char for char in text
        if unicodedata.category(char) not in ('Cc', 'Cf')
    )

    # Convert smart quotes and dashes
    text = text.translate(QUOTE_MAP)

    # Normalize whitespace (collapse multiple spaces, strip)
    text = ' '.join(text.split())

    # Truncate if needed (prefer word boundary)
    if max_length and len(text) > max_length:
        truncated = text[:max_length]
        # Try to break at word boundary
        last_space = truncated.rfind(' ')
        if last_space > max_length * 0.8:  # Only if we keep 80%+
            truncated = truncated[:last_space]
        text = truncated.rstrip()

    return text
```

### Metadata Validation Model
```python
# Source: Pydantic v2 documentation
from pydantic import BaseModel, Field, field_validator
from typing import Optional, Any
import logging

log = logging.getLogger('PlexSync')

class SyncMetadata(BaseModel):
    """
    Validated metadata for Plex sync.

    Required: scene_id, title
    Optional: all other fields
    """
    scene_id: int = Field(..., gt=0)
    title: str = Field(..., min_length=1, max_length=255)
    details: Optional[str] = Field(default=None, max_length=10000)
    date: Optional[str] = None
    rating100: Optional[int] = Field(default=None, ge=0, le=100)
    studio: Optional[str] = Field(default=None, max_length=255)
    performers: Optional[list[str]] = None
    tags: Optional[list[str]] = None

    @field_validator('title', 'details', 'studio', mode='before')
    @classmethod
    def sanitize_string_field(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        if not isinstance(v, str):
            v = str(v)

        original = v
        sanitized = sanitize_for_plex(v)

        if sanitized != original:
            log.warning(f"Sanitized text field: '{original[:50]}...' -> '{sanitized[:50]}...'")

        return sanitized

    @field_validator('performers', 'tags', mode='before')
    @classmethod
    def sanitize_string_list(cls, v: Any) -> Optional[list[str]]:
        if v is None:
            return None
        if not isinstance(v, list):
            return None

        return [sanitize_for_plex(str(item)) for item in v if item]
```

### Error Classification
```python
# Source: retryhttp patterns + existing worker.processor
from typing import Type
import logging

log = logging.getLogger('PlexSync')

# Import existing exception classes
from worker.processor import TransientError, PermanentError

# HTTP status code classification
TRANSIENT_CODES = frozenset({429, 500, 502, 503, 504})
PERMANENT_CODES = frozenset({400, 401, 403, 404, 405, 410, 422})

def classify_http_error(status_code: int) -> Type[Exception]:
    """Classify HTTP status code as transient or permanent."""
    if status_code in TRANSIENT_CODES:
        return TransientError
    if status_code in PERMANENT_CODES:
        return PermanentError
    if 400 <= status_code < 500:
        return PermanentError  # Default 4xx to permanent
    if status_code >= 500:
        return TransientError  # Default 5xx to transient
    return TransientError  # Unknown = transient (allow retry)

def classify_exception(exc: Exception) -> Type[Exception]:
    """
    Classify any exception as TransientError or PermanentError.

    Used by worker to decide retry vs DLQ routing.
    """
    exc_type = type(exc).__name__

    # Check for HTTP response (requests/httpx pattern)
    if hasattr(exc, 'response') and exc.response is not None:
        status = getattr(exc.response, 'status_code', None)
        if status:
            result = classify_http_error(status)
            log.debug(f"Classified HTTP {status} as {result.__name__}")
            return result

    # Network/connection errors are transient
    if isinstance(exc, (ConnectionError, TimeoutError, OSError)):
        log.debug(f"Classified {exc_type} (network) as TransientError")
        return TransientError

    # Validation errors are permanent
    if isinstance(exc, (ValueError, TypeError, KeyError, AttributeError)):
        log.debug(f"Classified {exc_type} (validation) as PermanentError")
        return PermanentError

    # Already classified
    if isinstance(exc, TransientError):
        return TransientError
    if isinstance(exc, PermanentError):
        return PermanentError

    # Unknown defaults to transient (safer - allows retry)
    log.debug(f"Classified {exc_type} (unknown) as TransientError")
    return TransientError
```

### Config Model
```python
# Source: Existing PlexSync.py analysis + pydantic-settings
from pydantic import BaseModel, Field, field_validator
from typing import Optional

class PlexSyncConfig(BaseModel):
    """
    PlexSync plugin configuration.

    Required fields determined from PlexSync.py analysis:
    - plex_url: Plex server URL (for API calls)
    - plex_token: Plex authentication token

    Optional tunables:
    - max_retries: Already used in SyncWorker (default 5)
    - poll_interval: Worker loop delay
    - enabled: Master on/off switch
    """
    # Required
    plex_url: str
    plex_token: str

    # Optional with defaults
    enabled: bool = True
    max_retries: int = Field(default=5, ge=1, le=20)
    poll_interval: float = Field(default=1.0, ge=0.1, le=60.0)

    # Validation strictness
    strict_mode: bool = Field(
        default=False,
        description="If True, reject invalid metadata. If False, sanitize and continue."
    )

    @field_validator('plex_url', mode='after')
    @classmethod
    def validate_plex_url(cls, v: str) -> str:
        if not v:
            raise ValueError('plex_url is required')
        if not v.startswith(('http://', 'https://')):
            raise ValueError('plex_url must start with http:// or https://')
        return v.rstrip('/')

    @field_validator('plex_token', mode='after')
    @classmethod
    def validate_plex_token(cls, v: str) -> str:
        if not v or len(v) < 10:
            raise ValueError('plex_token is required and must be valid')
        return v

    def log_config(self, logger) -> None:
        """Log config with masked token."""
        masked_token = self.plex_token[:4] + '****' + self.plex_token[-4:]
        logger.info(
            f"PlexSync config: url={self.plex_url}, token={masked_token}, "
            f"max_retries={self.max_retries}, enabled={self.enabled}"
        )
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Pydantic v1 validators | Pydantic v2 `field_validator` decorator | v2.0 (Jun 2023) | New decorator syntax, mode parameter |
| `@validator` | `@field_validator` | v2.0 | Clearer naming, explicit mode |
| Config class | `model_config = ConfigDict(...)` | v2.0 | Class-based config deprecated |
| Manual type coercion | Pydantic auto-coercion | v2.0 | 17x faster, Rust core |

**Deprecated/outdated:**
- `@validator` decorator: Use `@field_validator` in v2
- `Config` inner class: Use `model_config = ConfigDict(...)` instead
- `schema_extra`: Use `json_schema_extra` in v2
- Pydantic v1 `parse_obj`: Use `model_validate` in v2

## Open Questions

1. **Plex API Field Length Limits**
   - What we know: File naming recommends <255 chars; edition names limited to 32 chars
   - What's unclear: Actual database/API limits for title, summary fields
   - Recommendation: Default to 255 for title, 10000 for summary; adjust based on observed API errors

2. **Specific Problematic Characters for Plex**
   - What we know: Control characters and encoding issues cause problems; UTF-8 encoding required
   - What's unclear: Exact characters that cause Plex API 400/500 errors
   - Recommendation: Start with control chars, smart quotes; log sanitization; expand based on failures

3. **Stash Config Format**
   - What we know: Stash passes JSON config to plugins via stdin
   - What's unclear: Exact structure and where Plex URL/token are stored
   - Recommendation: Check Stash plugin documentation; likely in plugin settings or config.yml

4. **Performance Budget Allocation**
   - What we know: 100ms total budget for hook handler (from Phase 1)
   - What's unclear: How much of budget already used by filtering + enqueue
   - Recommendation: Profile current handler; allocate remaining time (likely 50-80ms available for validation)

## Sources

### Primary (HIGH confidence)
- [Pydantic Validators Documentation](https://docs.pydantic.dev/latest/concepts/validators/) - field_validator syntax, modes
- [Pydantic Performance Documentation](https://docs.pydantic.dev/latest/concepts/performance/) - optimization tips
- [Pydantic Settings Documentation](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) - config validation patterns
- [Python unicodedata Documentation](https://docs.python.org/3/library/unicodedata.html) - Unicode normalization, categories
- [Plex API Movie Update](https://www.plexopedia.com/plex-media-server/api/library/movie-update/) - field types, error codes
- [retryhttp GitHub](https://github.com/austind/retryhttp) - HTTP error classification patterns

### Secondary (MEDIUM confidence)
- [python-plexapi Documentation](https://python-plexapi.readthedocs.io/en/latest/) - API patterns, encoding
- [Text Sanitization Patterns](https://sbozich.github.io/posts/text-cleanup-sanitization-python/) - Python sanitization examples
- [Pydantic v2 Best Practices (Medium)](https://medium.com/algomart/working-with-pydantic-v2-the-best-practices-i-wish-i-had-known-earlier-83da3aa4d17a) - performance tips

### Tertiary (LOW confidence)
- [Plex Forum discussions](https://forums.plex.tv/) - Character encoding issues (anecdotal)
- Smart quote handling patterns (Stack Overflow, various)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Pydantic v2 is well-documented, stdlib for text handling
- Architecture: HIGH - Patterns derived from official Pydantic docs
- Pitfalls: MEDIUM - Some based on general validation experience, not Plex-specific
- Plex character limits: LOW - Not officially documented, based on file naming conventions

**Research date:** 2026-01-24
**Valid until:** 2026-02-24 (30 days - Pydantic stable, Plex API unlikely to change)
