# Python Quality Refactoring — Design Spec

**Date:** 2026-03-30
**Scope:** Structural refactoring of worker, validation, and test code for quality
**Constraint:** No behavioral changes. Coverage stays ≥86%. Tests can be restructured.

---

## 1. Generic Field Syncer

**Problem:** `_sync_performers`, `_sync_tags`, `_sync_collection` in `processor.py` are near-identical (~160 lines of duplication). Each: handles clear case, sanitizes, diffs current vs. new, builds indexed edit dict, applies edits.

**Solution:** New file `worker/field_sync.py` with:

```python
@dataclass(frozen=True)
class FieldSyncSpec:
    name: str                    # 'performers', 'tags', 'collection'
    plex_attr: str               # 'actors', 'genres', 'collections'
    edit_prefix: str             # 'actor', 'genre', 'collection'
    max_count: int               # MAX_PERFORMERS, MAX_TAGS, MAX_COLLECTIONS
    max_name_length: int         # per-item sanitization limit
    lock_edit_key: str           # 'actor.locked', 'genre.locked', etc.

def sync_field(spec: FieldSyncSpec, plex_item, values, result, debug: bool) -> bool:
    """Generic field sync — handles clear, diff, edit for any list field."""
```

Three pre-defined specs: `PERFORMERS_SPEC`, `TAGS_SPEC`, `COLLECTION_SPEC`.

**Collection edge case:** `_sync_collection` differs slightly — it adds the studio name as a collection rather than syncing a list from Stash data. It has no "clear" behavior and no per-item sanitization. `sync_field()` handles this via optional flags on `FieldSyncSpec`:
- `clear_on_empty: bool = True` (False for collection)
- `sanitize_items: bool = True` (False for collection — studio already sanitized in core edits)
- `source_key: str = 'performers'` (overridden to `'studio'` for collection, where the value is a single string wrapped in a list)

The original methods in the updater become 3-line delegations to `sync_field()`.

**LOCKED decision respected:** Empty/None values clear existing Plex data (handled by `sync_field` clear branch).

---

## 2. Decompose `processor.py` (1293 lines → ~600 + ~350 + ~100)

**Problem:** `processor.py` mixes job orchestration, metadata updating, and field syncing.

**Solution:** Extract into focused modules:

| File | Responsibility | Key contents |
|---|---|---|
| `worker/processor.py` (stays) | Job loop orchestration | `SyncWorker`, `_worker_loop`, `_process_job`, retry methods, `start`/`stop` |
| `worker/metadata_updater.py` (new) | Metadata application | `MetadataUpdater` class with `update()`, `_build_core_edits()`, `_upload_image()`, `_validate_edit_result()`, `_fetch_stash_image()` |
| `worker/field_sync.py` (new) | Generic field sync | `FieldSyncSpec`, `sync_field()`, spec constants |

### `MetadataUpdater` class

```python
class MetadataUpdater:
    def __init__(self, config):
        self.config = config

    def update(self, plex_item, data: dict) -> PartialSyncResult:
        """Replaces SyncWorker._update_metadata"""
```

`SyncWorker` creates `MetadataUpdater` lazily and delegates:

```python
def _get_metadata_updater(self):
    if self._metadata_updater is None:
        self._metadata_updater = MetadataUpdater(self.config)
    return self._metadata_updater
```

### What stays in `processor.py`

- `SyncWorker.__init__`, `start`, `stop`
- `_worker_loop` (queue polling, circuit breaker, backoff balloon detection)
- `_process_job` (library search, candidate dedup, confidence scoring, delegates to updater)
- `_prepare_for_retry`, `_is_ready_for_retry`, `_get_max_retries_for_error`, `_requeue_with_metadata`
- `_get_plex_client`, `_get_caches`, `_log_cache_stats`, `_log_dlq_status`, `_log_batch_summary`

---

## 3. Consolidate Lazy Imports

**Problem:** Same imports repeated inside 2-3 methods each. Scatters dependency information.

**Rules:**

| Import | Action | Reason |
|---|---|---|
| `validation.limits` | **Module-level** | Pure constants, no side effects |
| `validation.sanitizers` | **Module-level** | Pure function |
| `validation.errors` | **Module-level** | Pure class |
| `worker.backoff` | **Module-level** | Pure functions |
| `worker.circuit_breaker` | **Module-level** | Already imported in `__init__`, just inconsistent |
| `plex.exceptions` | **Module-level** | Pure exception classes |
| `plex.client` / `plex.cache` | **Keep lazy** | Heavy init (network connection), test pollution |
| `plex.matcher` | **Keep lazy** | Imports plexapi which may not be installed |
| `sync_queue.operations` | **Keep lazy** | Test isolation — tests mock at function level |
| `hooks.handlers.unmark_scene_pending` | **Keep lazy** | Cross-module coupling, test mocking |
| `worker.outage_history` / `worker.recovery` | **Keep lazy** | Only needed when `data_dir` is set |

Each remaining lazy import gets a comment: `# lazy: <reason>` (e.g., `# lazy: heavy init`, `# lazy: test isolation`).

---

## 4. DRY Pydantic Validators

**Problem:** `sanitize_title`, `sanitize_details`, `sanitize_studio` in `SyncMetadata` are near-identical.

**Solution:** Factory function in `validation/metadata.py`:

```python
def _string_sanitizer(max_length: int, required: bool = False):
    """Create a Pydantic field_validator that sanitizes string fields."""
    def validator(cls, v):
        if v is None:
            if required:
                raise ValueError("field is required")
            return None
        if not isinstance(v, str):
            v = str(v)
        sanitized = sanitize_for_plex(v, max_length=max_length)
        if required and not sanitized:
            raise ValueError("field cannot be empty after sanitization")
        return sanitized if sanitized else None
    return classmethod(validator)
```

Applied to the model:

```python
class SyncMetadata(BaseModel):
    # field definitions unchanged

    sanitize_title = field_validator('title', mode='before')(_string_sanitizer(255, required=True))
    sanitize_details = field_validator('details', mode='before')(_string_sanitizer(10000))
    sanitize_studio = field_validator('studio', mode='before')(_string_sanitizer(255))
    # sanitize_string_list stays as-is (different pattern — list, not scalar)
```

Debug logging removed from validators (not actionable). If needed, belongs in the caller.

---

## 5. Test Modernization

### 5a. Builder Functions (`tests/factories.py`)

New file with builder functions that accept keyword overrides:

```python
def make_plex_item(title="Test Scene", studio="Test Studio", ...) -> MagicMock:
def make_config(plex_url="http://localhost:32400", ...) -> Mock:
def make_job(scene_id=123, ...) -> dict:
def make_stash_scene(id="789", ...) -> dict:
```

Existing fixtures (`mock_plex_item`, `mock_config`, etc.) delegate to builders — no breaking change for tests that use fixtures directly.

### 5b. Parametrized Field Sync Tests

With generic `sync_field()`, tests become parametrized across all three field types:

```python
@pytest.mark.parametrize("spec", [PERFORMERS_SPEC, TAGS_SPEC, COLLECTION_SPEC])
def test_sync_field_adds_new(spec, ...):

@pytest.mark.parametrize("spec", [PERFORMERS_SPEC, TAGS_SPEC, COLLECTION_SPEC])
def test_sync_field_clears_empty(spec, ...):

@pytest.mark.parametrize("spec", [PERFORMERS_SPEC, TAGS_SPEC, COLLECTION_SPEC])
def test_sync_field_noop_when_unchanged(spec, ...):
```

Each behavior tested once with all three specs. Test file: `tests/worker/test_field_sync.py`.

### 5c. `MetadataUpdater` Unit Tests

New file `tests/worker/test_metadata_updater.py` — tests `MetadataUpdater` in isolation without `SyncWorker`, queue, DLQ, or circuit breaker:

```python
def test_update_clears_empty_studio():
    updater = MetadataUpdater(config=make_config())
    item = make_plex_item(studio="Old Studio")
    updater.update(item, {"studio": None})
    item.edit.assert_called_once_with(**{"studio.value": ""})
```

Existing `test_processor.py` tests that cover `_update_metadata` behavior through `SyncWorker` can be removed once equivalent coverage exists in the new test files.

---

## File Impact Summary

| Action | File |
|---|---|
| **New** | `worker/field_sync.py` |
| **New** | `worker/metadata_updater.py` |
| **New** | `tests/factories.py` |
| **New** | `tests/worker/test_field_sync.py` |
| **New** | `tests/worker/test_metadata_updater.py` |
| **Modified** | `worker/processor.py` (remove extracted methods, add delegation) |
| **Modified** | `validation/metadata.py` (DRY validators) |
| **Modified** | `tests/conftest.py` (fixtures delegate to factories) |
| **Modified** | `tests/worker/test_processor.py` (remove tests moved to new files) |
| **Possibly modified** | `tests/hooks/test_handlers.py`, integration tests (if they reference moved methods) |

## Implementation Order

1. `worker/field_sync.py` + tests (no existing code changes needed)
2. `worker/metadata_updater.py` + tests (no existing code changes needed)
3. Wire `MetadataUpdater` into `SyncWorker`, remove old methods
4. DRY validators in `validation/metadata.py`
5. `tests/factories.py` + update fixtures
6. Consolidate imports across all modified files
7. Run full test suite, verify coverage ≥86%
