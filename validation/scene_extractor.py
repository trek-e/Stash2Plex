"""
Extract metadata from Stash GraphQL scene responses into flat job data.

Centralizes the scene-to-job-data transformation that was duplicated across
Stash2Plex.py (bulk sync), hooks/handlers.py (event capture), and
reconciliation/engine.py (gap detection).
"""

from typing import Any, Optional


def extract_scene_metadata(scene: dict[str, Any]) -> dict[str, Any]:
    """Extract flat metadata dict from a Stash GraphQL scene response.

    Handles nested fields (studio, performers, tags, paths) and normalizes
    them into the flat format expected by the sync queue.

    Args:
        scene: Stash GraphQL scene object with nested fields.

    Returns:
        Dict with keys: title, details, date, rating100, and optionally
        studio, performers, tags, poster_url, background_url.
    """
    data: dict[str, Any] = {
        'title': scene.get('title'),
        'details': scene.get('details'),
        'date': scene.get('date'),
        'rating100': scene.get('rating100'),
    }

    studio = scene.get('studio')
    if studio:
        data['studio'] = studio.get('name')

    performers = scene.get('performers', [])
    if performers:
        data['performers'] = [p.get('name') for p in performers if p.get('name')]

    tags = scene.get('tags', [])
    if tags:
        data['tags'] = [t.get('name') for t in tags if t.get('name')]

    paths = scene.get('paths', {})
    if paths:
        if paths.get('screenshot'):
            data['poster_url'] = paths['screenshot']
        if paths.get('preview'):
            data['background_url'] = paths['preview']

    return data


def get_scene_file_path(scene: dict[str, Any]) -> Optional[str]:
    """Extract the primary file path from a Stash scene response.

    Args:
        scene: Stash GraphQL scene object with 'files' field.

    Returns:
        File path string, or None if no files present.
    """
    files = scene.get('files', [])
    if not files:
        return None
    return files[0].get('path')
