"""
Tests for plex/matcher.py - Plex item matching logic with caching support.

Tests cover:
1. Matching with mock match_cache hit (returns cached item directly)
2. Matching with mock match_cache miss (stores result after search)
3. Stale cache handling (invalidates and re-searches)
4. Backward compatibility (works without cache parameters)
5. Helper function tests (_cached_item_has_file)
"""

import pytest
from unittest.mock import MagicMock, patch


# =============================================================================
# Mock Helpers
# =============================================================================


class MockPart:
    """Mock plexapi Part object."""

    def __init__(self, file_path: str):
        self.file = file_path


class MockMedia:
    """Mock plexapi Media object."""

    def __init__(self, file_paths: list):
        self.parts = [MockPart(p) for p in file_paths]


class MockPlexItem:
    """Mock plexapi Video object (Movie, Episode, etc.)."""

    def __init__(self, key: str, title: str, file_paths: list):
        self.key = key
        self.ratingKey = key
        self.title = title
        self.media = [MockMedia(file_paths)]


def create_mock_plex_item(key: str, title: str, file_paths: list = None) -> MockPlexItem:
    """Create a mock Plex item for testing."""
    return MockPlexItem(key, title, file_paths or [f"/media/{title.lower()}.mp4"])


class MockLibrarySection:
    """Mock plexapi LibrarySection object."""

    def __init__(self, title: str = "Movies", items: list = None, search_results: dict = None):
        self.title = title
        self._items = items or []
        self._search_results = search_results or {}
        self._fetch_items = {}

    def all(self):
        """Return all items in library."""
        return self._items

    def search(self, title: str = None):
        """Return search results for title."""
        return self._search_results.get(title, [])

    def fetchItem(self, key: str):
        """Fetch item by key."""
        if key in self._fetch_items:
            return self._fetch_items[key]
        for item in self._items:
            if item.key == key:
                return item
        raise Exception(f"Item {key} not found")

    def add_fetchable(self, key: str, item):
        """Add an item that can be fetched by key."""
        self._fetch_items[key] = item


# =============================================================================
# Helper Function Tests
# =============================================================================


class TestCachedItemHasFile:
    """Tests for _cached_item_has_file helper function."""

    def test_matches_filename_in_file_paths(self):
        """Returns True when filename matches entry in file_paths."""
        from plex.matcher import _cached_item_has_file

        item_data = {'file_paths': ['/media/movie.mp4', '/media/movie.mkv']}

        assert _cached_item_has_file(item_data, 'movie.mp4') is True
        assert _cached_item_has_file(item_data, 'movie.mkv') is True

    def test_no_match_returns_false(self):
        """Returns False when filename not in file_paths."""
        from plex.matcher import _cached_item_has_file

        item_data = {'file_paths': ['/media/movie.mp4']}

        assert _cached_item_has_file(item_data, 'other.mp4') is False

    def test_case_insensitive_matching(self):
        """Matches filenames case-insensitively by default."""
        from plex.matcher import _cached_item_has_file

        item_data = {'file_paths': ['/media/Movie.MP4']}

        assert _cached_item_has_file(item_data, 'movie.mp4') is True
        assert _cached_item_has_file(item_data, 'MOVIE.MP4') is True

    def test_empty_file_paths(self):
        """Returns False for empty file_paths."""
        from plex.matcher import _cached_item_has_file

        item_data = {'file_paths': []}

        assert _cached_item_has_file(item_data, 'movie.mp4') is False

    def test_missing_file_paths_key(self):
        """Returns False when file_paths key is missing."""
        from plex.matcher import _cached_item_has_file

        item_data = {}

        assert _cached_item_has_file(item_data, 'movie.mp4') is False


# =============================================================================
# Backward Compatibility Tests
# =============================================================================


class TestBackwardCompatibility:
    """Tests for backward compatibility (no cache parameters)."""

    def test_find_without_caches_single_match(self):
        """find_plex_items_with_confidence works without caches, single match."""
        from plex.matcher import find_plex_items_with_confidence, MatchConfidence

        item = create_mock_plex_item("/library/metadata/1", "Test Movie", ["/media/test movie.mp4"])
        library = MockLibrarySection("Movies", items=[item], search_results={"Test Movie": [item]})

        confidence, matched_item, candidates = find_plex_items_with_confidence(
            library, "/media/test movie.mp4"
        )

        assert confidence == MatchConfidence.HIGH
        assert matched_item.key == "/library/metadata/1"
        assert len(candidates) == 1

    def test_find_without_caches_no_match_raises(self):
        """find_plex_items_with_confidence raises PlexNotFound when no match."""
        from plex.matcher import find_plex_items_with_confidence
        from plex.exceptions import PlexNotFound

        library = MockLibrarySection("Movies", items=[], search_results={})

        with pytest.raises(PlexNotFound):
            find_plex_items_with_confidence(library, "/media/nonexistent.mp4")


# =============================================================================
# MatchCache Hit Tests
# =============================================================================


class TestMatchCacheHit:
    """Tests for match_cache hit scenarios."""

    def test_cache_hit_returns_item_directly(self, tmp_path):
        """When match_cache has entry, item is fetched directly without search."""
        from plex.matcher import find_plex_items_with_confidence, MatchConfidence
        from plex.cache import MatchCache

        # Setup item and library
        item = create_mock_plex_item("/library/metadata/123", "Cached Movie", ["/media/cached.mp4"])
        library = MockLibrarySection("Movies")
        library.add_fetchable("/library/metadata/123", item)

        # Pre-populate cache
        match_cache = MatchCache(str(tmp_path))
        match_cache.set_match("Movies", "/media/cached.mp4", "/library/metadata/123")

        # Call function
        confidence, matched_item, candidates = find_plex_items_with_confidence(
            library, "/media/cached.mp4", match_cache=match_cache
        )

        assert confidence == MatchConfidence.HIGH
        assert matched_item.key == "/library/metadata/123"
        assert matched_item.title == "Cached Movie"
        # Verify cache stats show hit
        stats = match_cache.get_stats()
        assert stats["hits"] == 1
        match_cache.close()

    def test_cache_hit_skips_library_search(self, tmp_path):
        """When match_cache has entry, library.search is not called."""
        from plex.matcher import find_plex_items_with_confidence
        from plex.cache import MatchCache

        # Setup item
        item = create_mock_plex_item("/library/metadata/123", "Movie", ["/media/movie.mp4"])

        # Use MagicMock to verify search is not called
        library = MagicMock()
        library.title = "Movies"
        library.fetchItem.return_value = item

        # Pre-populate cache
        match_cache = MatchCache(str(tmp_path))
        match_cache.set_match("Movies", "/media/movie.mp4", "/library/metadata/123")

        # Call function
        find_plex_items_with_confidence(
            library, "/media/movie.mp4", match_cache=match_cache
        )

        # search and all should not be called
        library.search.assert_not_called()
        library.all.assert_not_called()
        # fetchItem should be called with cached key
        library.fetchItem.assert_called_once_with("/library/metadata/123")
        match_cache.close()


# =============================================================================
# MatchCache Miss Tests
# =============================================================================


class TestMatchCacheMiss:
    """Tests for match_cache miss scenarios."""

    def test_cache_miss_searches_and_stores_result(self, tmp_path):
        """When match_cache misses, search is performed and result is cached."""
        from plex.matcher import find_plex_items_with_confidence, MatchConfidence
        from plex.cache import MatchCache

        # Setup item and library
        item = create_mock_plex_item("/library/metadata/456", "New Movie", ["/media/new movie.mp4"])
        library = MockLibrarySection("Movies", items=[item], search_results={"New Movie": [item]})

        # Empty cache
        match_cache = MatchCache(str(tmp_path))

        # Call function
        confidence, matched_item, candidates = find_plex_items_with_confidence(
            library, "/media/new movie.mp4", match_cache=match_cache
        )

        assert confidence == MatchConfidence.HIGH
        assert matched_item.key == "/library/metadata/456"

        # Verify result was cached
        cached_key = match_cache.get_match("Movies", "/media/new movie.mp4")
        assert cached_key == "/library/metadata/456"
        match_cache.close()

    def test_cache_miss_multiple_matches_not_cached(self, tmp_path):
        """When multiple matches found (LOW confidence), result is not cached."""
        from plex.matcher import find_plex_items_with_confidence, MatchConfidence
        from plex.cache import MatchCache

        # Setup multiple items with same filename
        item1 = create_mock_plex_item("/library/metadata/1", "Movie 1", ["/media/movie.mp4"])
        item2 = create_mock_plex_item("/library/metadata/2", "Movie 2", ["/media/movie.mp4"])
        library = MockLibrarySection("Movies", items=[item1, item2])

        # Empty cache
        match_cache = MatchCache(str(tmp_path))

        # Call function (will fall back to all() scan)
        confidence, matched_item, candidates = find_plex_items_with_confidence(
            library, "/media/movie.mp4", match_cache=match_cache
        )

        assert confidence == MatchConfidence.LOW
        assert matched_item is None
        assert len(candidates) == 2

        # Verify result was NOT cached (ambiguous)
        cached_key = match_cache.get_match("Movies", "/media/movie.mp4")
        assert cached_key is None
        match_cache.close()


# =============================================================================
# Stale Cache Tests
# =============================================================================


class TestStaleCacheHandling:
    """Tests for stale cache entry invalidation."""

    def test_stale_cache_invalidated_on_fetch_failure(self, tmp_path):
        """When cached key no longer exists, cache is invalidated and search continues."""
        from plex.matcher import find_plex_items_with_confidence, MatchConfidence
        from plex.cache import MatchCache

        # Setup item that will be found via search but NOT via cached key
        item = create_mock_plex_item("/library/metadata/999", "Moved Movie", ["/media/moved.mp4"])
        library = MockLibrarySection("Movies", items=[item], search_results={"Moved Movie": [item]})
        # Note: fetchItem("/library/metadata/old") will raise exception

        # Pre-populate cache with OLD (stale) key
        match_cache = MatchCache(str(tmp_path))
        match_cache.set_match("Movies", "/media/moved.mp4", "/library/metadata/old")

        # Call function
        confidence, matched_item, candidates = find_plex_items_with_confidence(
            library, "/media/moved.mp4", match_cache=match_cache
        )

        # Should find via search fallback
        assert confidence == MatchConfidence.HIGH
        assert matched_item.key == "/library/metadata/999"

        # Old cache entry should be invalidated, new one stored
        cached_key = match_cache.get_match("Movies", "/media/moved.mp4")
        assert cached_key == "/library/metadata/999"
        match_cache.close()


# =============================================================================
# LibraryCache Tests
# =============================================================================


class TestLibraryCacheIntegration:
    """Tests for library_cache (PlexCache) integration."""

    def test_search_results_cached(self, tmp_path):
        """Search results are cached in library_cache."""
        from plex.matcher import find_plex_items_with_confidence
        from plex.cache import PlexCache

        # Setup item and library
        item = create_mock_plex_item("/library/metadata/789", "Searchable", ["/media/searchable.mp4"])

        # Use MagicMock to track calls
        library = MagicMock()
        library.title = "Movies"
        library.search.return_value = [item]
        library.all.return_value = []

        # Empty cache
        library_cache = PlexCache(str(tmp_path))

        # First call
        find_plex_items_with_confidence(
            library, "/media/searchable.mp4", library_cache=library_cache
        )

        # Verify search results were cached
        cached = library_cache.get_search_results("Movies", "searchable")
        assert cached is not None
        assert len(cached) == 1
        assert cached[0]["key"] == "/library/metadata/789"
        library_cache.close()

    def test_library_all_cached(self, tmp_path):
        """Library all() results are cached in library_cache."""
        from plex.matcher import find_plex_items_with_confidence
        from plex.cache import PlexCache

        # Setup item that won't be found via search
        item = create_mock_plex_item("/library/metadata/111", "Hidden", ["/media/hidden.mp4"])

        # Library where search returns nothing, all() returns item
        library = MagicMock()
        library.title = "Movies"
        library.search.return_value = []  # Search miss
        library.all.return_value = [item]

        # Empty cache
        library_cache = PlexCache(str(tmp_path))

        # First call - triggers all() fallback
        find_plex_items_with_confidence(
            library, "/media/hidden.mp4", library_cache=library_cache
        )

        # Verify all() results were cached
        cached = library_cache.get_library_items("Movies")
        assert cached is not None
        assert len(cached) == 1
        assert cached[0]["key"] == "/library/metadata/111"
        library_cache.close()

    def test_cached_library_items_used_on_second_call(self, tmp_path):
        """Second call uses cached library items instead of calling all()."""
        from plex.matcher import find_plex_items_with_confidence
        from plex.cache import PlexCache

        # Setup
        item = create_mock_plex_item("/library/metadata/222", "Cached All", ["/media/cached_all.mp4"])

        library = MagicMock()
        library.title = "Movies"
        library.search.return_value = []  # Search always misses
        library.all.return_value = [item]
        library.fetchItem.return_value = item

        library_cache = PlexCache(str(tmp_path))

        # First call - populates cache
        find_plex_items_with_confidence(
            library, "/media/cached_all.mp4", library_cache=library_cache
        )

        # Reset mock call counts
        library.all.reset_mock()
        library.fetchItem.reset_mock()

        # Second call - should use cache
        find_plex_items_with_confidence(
            library, "/media/cached_all.mp4", library_cache=library_cache
        )

        # all() should NOT be called on second call (cache hit)
        library.all.assert_not_called()
        # fetchItem should be called to get actual item from cached key
        library.fetchItem.assert_called()
        library_cache.close()


# =============================================================================
# Combined Cache Tests
# =============================================================================


class TestCombinedCaches:
    """Tests for using both library_cache and match_cache together."""

    def test_match_cache_takes_priority(self, tmp_path):
        """When match_cache has entry, library_cache is not consulted."""
        from plex.matcher import find_plex_items_with_confidence
        from plex.cache import PlexCache, MatchCache

        item = create_mock_plex_item("/library/metadata/333", "Priority", ["/media/priority.mp4"])

        library = MagicMock()
        library.title = "Movies"
        library.fetchItem.return_value = item

        # Both caches
        library_cache = PlexCache(str(tmp_path / "lib"))
        match_cache = MatchCache(str(tmp_path / "match"))
        match_cache.set_match("Movies", "/media/priority.mp4", "/library/metadata/333")

        # Call function
        find_plex_items_with_confidence(
            library, "/media/priority.mp4",
            library_cache=library_cache,
            match_cache=match_cache
        )

        # Library cache should not be consulted (0 hits, 0 misses)
        lib_stats = library_cache.get_stats()
        assert lib_stats["hits"] == 0
        assert lib_stats["misses"] == 0

        # Match cache should have 1 hit
        match_stats = match_cache.get_stats()
        assert match_stats["hits"] == 1

        library_cache.close()
        match_cache.close()
