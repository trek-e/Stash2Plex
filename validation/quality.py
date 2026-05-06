"""
Metadata quality gate for Stash2Plex.

Determines whether a scene has enough meaningful metadata to be worth
syncing to Plex. Applied before enqueueing in both the hook handler and
the reconciliation gap detector.
"""


def has_meaningful_metadata(data: dict) -> bool:
    """Check whether a scene data dict contains meaningful metadata.

    A scene qualifies if it has at least one of:
    - studio
    - performers
    - tags
    - details
    - date

    NOTE: rating100 is intentionally EXCLUDED. A rating alone is not
    considered meaningful because:
    1. Ratings are often auto-assigned defaults, not user-curated.
    2. A scene with ONLY a rating would trigger sync and clear all other
       Plex fields (Stash is authoritative — empty fields clear Plex values).
    3. This is consistent with the LOCKED invariant: missing fields clear Plex.

    Args:
        data: Scene data dict (raw Stash scene or merged update_data).

    Returns:
        True if the scene has at least one meaningful metadata field.
    """
    return any([
        data.get('studio'),
        data.get('performers'),
        data.get('tags'),
        data.get('details'),
        data.get('date'),
    ])


__all__ = ['has_meaningful_metadata']
