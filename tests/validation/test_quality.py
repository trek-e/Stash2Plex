"""
Tests for validation/quality.py — Metadata Quality Gate.

The quality gate is a load-bearing business rule: scenes without meaningful
metadata are not synced to Plex, preventing the LOCKED invariant
(empty fields clear Plex values) from erasing data during the stash-box
identification race window.
"""

from validation.quality import has_meaningful_metadata


class TestHasMeaningfulMetadata:
    """Unit tests for the metadata quality gate."""

    # ── Fields that qualify ──────────────────────────────────────────────────

    def test_studio_qualifies(self):
        assert has_meaningful_metadata({'studio': 'Acme Studios'}) is True

    def test_performers_qualifies(self):
        assert has_meaningful_metadata({'performers': ['Alice']}) is True

    def test_tags_qualifies(self):
        assert has_meaningful_metadata({'tags': ['action']}) is True

    def test_details_qualifies(self):
        assert has_meaningful_metadata({'details': 'A great scene.'}) is True

    def test_date_qualifies(self):
        assert has_meaningful_metadata({'date': '2024-01-15'}) is True

    def test_multiple_qualifying_fields(self):
        assert has_meaningful_metadata({
            'studio': 'Acme',
            'performers': ['Alice', 'Bob'],
            'tags': ['drama'],
        }) is True

    # ── Fields that do NOT qualify ───────────────────────────────────────────

    def test_empty_dict_does_not_qualify(self):
        assert has_meaningful_metadata({}) is False

    def test_title_only_does_not_qualify(self):
        """Title alone is not meaningful — would clear existing Plex metadata."""
        assert has_meaningful_metadata({'title': 'My Scene'}) is False

    def test_path_only_does_not_qualify(self):
        assert has_meaningful_metadata({'path': '/media/scene.mp4'}) is False

    def test_rating100_does_not_qualify(self):
        """rating100 is intentionally excluded: auto-assigned defaults are not
        user-curated, and syncing rating-only would clear all other Plex fields."""
        assert has_meaningful_metadata({'rating100': 75}) is False

    def test_rating100_with_title_does_not_qualify(self):
        assert has_meaningful_metadata({'title': 'Scene', 'rating100': 80}) is False

    def test_unrecognised_fields_do_not_qualify(self):
        assert has_meaningful_metadata({'scene_id': 42, 'updated_at': 1700000000}) is False

    # ── Falsy values ─────────────────────────────────────────────────────────

    def test_empty_studio_string_does_not_qualify(self):
        assert has_meaningful_metadata({'studio': ''}) is False

    def test_empty_performers_list_does_not_qualify(self):
        assert has_meaningful_metadata({'performers': []}) is False

    def test_none_fields_do_not_qualify(self):
        assert has_meaningful_metadata({
            'studio': None,
            'performers': None,
            'tags': None,
            'details': None,
            'date': None,
        }) is False

    def test_one_truthy_among_falsy_qualifies(self):
        """A single truthy field among many falsy ones is enough."""
        assert has_meaningful_metadata({
            'studio': None,
            'performers': [],
            'tags': ['drama'],   # truthy
            'details': None,
            'date': None,
        }) is True
