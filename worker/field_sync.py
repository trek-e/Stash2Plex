"""
Generic field sync for Plex list fields (performers, tags, collections).

Provides a single sync_field() function that handles:
- Clearing field when value is None/empty (LOCKED decision)
- Sanitizing incoming values
- Diffing current vs. new items
- Building indexed Plex edit dicts
- Truncation at max count with logging

Each field type is defined as a FieldSyncSpec dataclass.
"""

from dataclasses import dataclass

from validation.limits import (
    MAX_PERFORMER_NAME_LENGTH, MAX_PERFORMERS,
    MAX_TAG_NAME_LENGTH, MAX_TAGS,
    MAX_COLLECTIONS,
)
from validation.sanitizers import sanitize_for_plex
from shared.log import create_logger

log_trace, log_debug, log_info, log_warn, log_error = create_logger("FieldSync")


@dataclass(frozen=True)
class FieldSyncSpec:
    """Specification for syncing a Plex list field."""
    name: str              # Human name: 'performers', 'tags', 'collection'
    plex_attr: str         # Plex item attribute: 'actors', 'genres', 'collections'
    edit_prefix: str       # Plex edit key prefix: 'actor', 'genre', 'collection'
    max_count: int         # Maximum items allowed
    max_name_length: int   # Per-item name sanitization limit
    lock_edit_key: str     # Key for locking/clearing: 'actor.locked', etc.
    clear_on_empty: bool = True     # Whether None/[] clears the field
    sanitize_items: bool = True     # Whether to sanitize individual item names


PERFORMERS_SPEC = FieldSyncSpec(
    name='performers',
    plex_attr='actors',
    edit_prefix='actor',
    max_count=MAX_PERFORMERS,
    max_name_length=MAX_PERFORMER_NAME_LENGTH,
    lock_edit_key='actor.locked',
)

TAGS_SPEC = FieldSyncSpec(
    name='tags',
    plex_attr='genres',
    edit_prefix='genre',
    max_count=MAX_TAGS,
    max_name_length=MAX_TAG_NAME_LENGTH,
    lock_edit_key='genre.locked',
)

COLLECTION_SPEC = FieldSyncSpec(
    name='collection',
    plex_attr='collections',
    edit_prefix='collection',
    max_count=MAX_COLLECTIONS,
    max_name_length=255,
    lock_edit_key='collection.locked',
    clear_on_empty=False,
    sanitize_items=False,
)


def sync_field(
    spec: FieldSyncSpec,
    plex_item,
    values,
    result,
    debug: bool,
    max_count_override: int | None = None,
) -> bool:
    """
    Sync a list field to Plex. Returns True if reload needed.

    Args:
        spec: Field specification (which Plex attribute, edit prefix, limits)
        plex_item: Plex Video item to update
        values: List of string values to sync, or None/[] to clear
        result: PartialSyncResult to record outcome
        debug: Whether to log debug details
        max_count_override: Override spec.max_count (used for config.max_tags)

    Returns:
        True if plex_item.edit() was called (reload needed), False otherwise
    """
    max_count = max_count_override if max_count_override is not None else spec.max_count

    # Handle clear case
    if values is None or values == []:
        if not spec.clear_on_empty:
            return False
        try:
            plex_item.edit(**{spec.lock_edit_key: 1})
            log_debug(f"Clearing {spec.name} (Stash value is empty)")
            result.add_success(spec.name)
            return True
        except Exception as e:
            log_warn(f" Failed to clear {spec.name}: {e}")
            result.add_warning(spec.name, e)
            return False

    if not values:
        return False

    try:
        # Sanitize if needed
        if spec.sanitize_items:
            sanitized = [sanitize_for_plex(v, max_length=spec.max_name_length) for v in values]
        else:
            sanitized = list(values)

        # Truncate input list
        if len(sanitized) > max_count:
            log_warn(f"Truncating {spec.name} list from {len(sanitized)} to {max_count}")
            sanitized = sanitized[:max_count]

        # Get current items
        current = [item.tag for item in getattr(plex_item, spec.plex_attr, [])]

        if debug:
            log_info(f"[DEBUG] {spec.name}: current={current}, incoming={sanitized}")

        # Find new items not already present
        new_items = [v for v in sanitized if v not in current]

        if new_items:
            all_items = current + new_items
            if len(all_items) > max_count:
                log_warn(f"Truncating combined {spec.name} list from {len(all_items)} to {max_count}")
                all_items = all_items[:max_count]

            edits = {f'{spec.edit_prefix}[{i}].tag.tag': name for i, name in enumerate(all_items)}
            plex_item.edit(**edits)
            log_info(f"Added {len(new_items)} {spec.name}: {new_items}")
            result.add_success(spec.name)
            return True
        else:
            log_trace(f"{spec.name} already in Plex: {sanitized}")
            result.add_success(spec.name)
            return False

    except Exception as e:
        log_warn(f" Failed to sync {spec.name}: {e}")
        result.add_warning(spec.name, e)
        return False
