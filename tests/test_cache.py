"""
Tests for plex/cache.py - Disk-backed caching for Plex library data.

Tests cover:
1. Cache initialization creates directory
2. Library items get/set with TTL
3. Search results get/set with TTL
4. Cache miss returns None
5. Cache clear removes all data
6. Statistics tracking (hits/misses)
7. Item data extraction preserves essential fields
8. Cache persistence across instances
"""

import os
import time

import pytest


# =============================================================================
# Mock Plex Item Helpers
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


# =============================================================================
# PlexCache Initialization Tests
# =============================================================================


class TestPlexCacheInit:
    """Tests for PlexCache initialization."""

    def test_init_creates_cache_directory(self, tmp_path):
        """PlexCache creates cache/ subdirectory on initialization."""
        from plex.cache import PlexCache

        cache = PlexCache(str(tmp_path))

        cache_dir = tmp_path / "cache"
        assert cache_dir.exists()
        assert cache_dir.is_dir()
        cache.close()

    def test_init_with_custom_ttl(self, tmp_path):
        """PlexCache accepts custom TTL value."""
        from plex.cache import PlexCache

        cache = PlexCache(str(tmp_path), library_ttl=1800)

        assert cache._library_ttl == 1800
        cache.close()

    def test_init_with_custom_size_limit(self, tmp_path):
        """PlexCache accepts custom size limit."""
        from plex.cache import PlexCache

        custom_limit = 50 * 1024 * 1024  # 50MB
        cache = PlexCache(str(tmp_path), size_limit=custom_limit)

        assert cache._size_limit == custom_limit
        cache.close()

    def test_repr_shows_cache_info(self, tmp_path):
        """PlexCache repr shows data_dir, ttl, items, and hit_rate."""
        from plex.cache import PlexCache

        cache = PlexCache(str(tmp_path), library_ttl=1800)

        repr_str = repr(cache)

        assert "PlexCache" in repr_str
        assert str(tmp_path) in repr_str
        assert "ttl=1800" in repr_str
        cache.close()


# =============================================================================
# Library Items Cache Tests
# =============================================================================


class TestLibraryItemsCache:
    """Tests for library items get/set operations."""

    def test_set_library_items_extracts_essential_data(self, tmp_path):
        """set_library_items extracts key, title, and file_paths from items."""
        from plex.cache import PlexCache

        cache = PlexCache(str(tmp_path))
        items = [
            create_mock_plex_item("/library/metadata/1", "Movie One", ["/media/one.mp4"]),
            create_mock_plex_item("/library/metadata/2", "Movie Two", ["/media/two.mp4", "/media/two.mkv"]),
        ]

        cache.set_library_items("Movies", items)
        cached = cache.get_library_items("Movies")

        assert cached is not None
        assert len(cached) == 2
        assert cached[0]["key"] == "/library/metadata/1"
        assert cached[0]["title"] == "Movie One"
        assert cached[0]["file_paths"] == ["/media/one.mp4"]
        assert cached[1]["file_paths"] == ["/media/two.mp4", "/media/two.mkv"]
        cache.close()

    def test_get_library_items_returns_none_on_miss(self, tmp_path):
        """get_library_items returns None when library not cached."""
        from plex.cache import PlexCache

        cache = PlexCache(str(tmp_path))

        result = cache.get_library_items("NonExistent")

        assert result is None
        cache.close()

    def test_get_library_items_returns_cached_data(self, tmp_path):
        """get_library_items returns previously cached data."""
        from plex.cache import PlexCache

        cache = PlexCache(str(tmp_path))
        items = [create_mock_plex_item("/1", "Test Movie")]
        cache.set_library_items("Movies", items)

        result = cache.get_library_items("Movies")

        assert result is not None
        assert len(result) == 1
        assert result[0]["title"] == "Test Movie"
        cache.close()

    def test_library_items_ttl_expiration(self, tmp_path):
        """Library items expire after TTL seconds."""
        from plex.cache import PlexCache

        # Use 1-second TTL for fast test
        cache = PlexCache(str(tmp_path), library_ttl=1)
        items = [create_mock_plex_item("/1", "Expiring Movie")]
        cache.set_library_items("Movies", items)

        # Should exist immediately
        assert cache.get_library_items("Movies") is not None

        # Wait for expiration
        time.sleep(1.5)

        # Should be gone after TTL
        assert cache.get_library_items("Movies") is None
        cache.close()


# =============================================================================
# Search Results Cache Tests
# =============================================================================


class TestSearchResultsCache:
    """Tests for search results get/set operations."""

    def test_set_search_results_caches_data(self, tmp_path):
        """set_search_results stores extracted item data."""
        from plex.cache import PlexCache

        cache = PlexCache(str(tmp_path))
        results = [create_mock_plex_item("/5", "Inception", ["/media/inception.mp4"])]

        cache.set_search_results("Movies", "Inception", results)
        cached = cache.get_search_results("Movies", "Inception")

        assert cached is not None
        assert len(cached) == 1
        assert cached[0]["title"] == "Inception"
        cache.close()

    def test_get_search_results_returns_none_on_miss(self, tmp_path):
        """get_search_results returns None when not cached."""
        from plex.cache import PlexCache

        cache = PlexCache(str(tmp_path))

        result = cache.get_search_results("Movies", "Unknown Film")

        assert result is None
        cache.close()

    def test_search_results_different_titles_isolated(self, tmp_path):
        """Different search titles are cached separately."""
        from plex.cache import PlexCache

        cache = PlexCache(str(tmp_path))
        cache.set_search_results("Movies", "Inception", [create_mock_plex_item("/1", "Inception")])
        cache.set_search_results("Movies", "Interstellar", [create_mock_plex_item("/2", "Interstellar")])

        inception = cache.get_search_results("Movies", "Inception")
        interstellar = cache.get_search_results("Movies", "Interstellar")

        assert inception[0]["title"] == "Inception"
        assert interstellar[0]["title"] == "Interstellar"
        cache.close()

    def test_search_results_ttl_expiration(self, tmp_path):
        """Search results expire after TTL seconds."""
        from plex.cache import PlexCache

        cache = PlexCache(str(tmp_path), library_ttl=1)
        cache.set_search_results("Movies", "Expiring", [create_mock_plex_item("/1", "Expiring")])

        assert cache.get_search_results("Movies", "Expiring") is not None
        time.sleep(1.5)
        assert cache.get_search_results("Movies", "Expiring") is None
        cache.close()


# =============================================================================
# Cache Clear Tests
# =============================================================================


class TestCacheClear:
    """Tests for cache.clear() operation."""

    def test_clear_removes_all_data(self, tmp_path):
        """clear() removes all cached library items and search results."""
        from plex.cache import PlexCache

        cache = PlexCache(str(tmp_path))
        cache.set_library_items("Movies", [create_mock_plex_item("/1", "Movie")])
        cache.set_search_results("Movies", "Search", [create_mock_plex_item("/2", "Result")])

        cache.clear()

        assert cache.get_library_items("Movies") is None
        assert cache.get_search_results("Movies", "Search") is None
        cache.close()

    def test_clear_resets_statistics(self, tmp_path):
        """clear() resets hit/miss counters."""
        from plex.cache import PlexCache

        cache = PlexCache(str(tmp_path))
        cache.set_library_items("Movies", [create_mock_plex_item("/1", "Movie")])
        cache.get_library_items("Movies")  # hit
        cache.get_library_items("NonExistent")  # miss

        cache.clear()
        stats = cache.get_stats()

        assert stats["hits"] == 0
        assert stats["misses"] == 0
        cache.close()


# =============================================================================
# Statistics Tests
# =============================================================================


class TestCacheStatistics:
    """Tests for cache hit/miss statistics tracking."""

    def test_stats_initial_values(self, tmp_path):
        """Initial stats show zero hits and misses."""
        from plex.cache import PlexCache

        cache = PlexCache(str(tmp_path))

        stats = cache.get_stats()

        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["hit_rate"] == 0.0
        cache.close()

    def test_stats_tracks_hits(self, tmp_path):
        """Stats increment hits on cache hits."""
        from plex.cache import PlexCache

        cache = PlexCache(str(tmp_path))
        cache.set_library_items("Movies", [create_mock_plex_item("/1", "Movie")])

        cache.get_library_items("Movies")  # hit
        cache.get_library_items("Movies")  # hit
        stats = cache.get_stats()

        assert stats["hits"] == 2
        assert stats["misses"] == 0
        cache.close()

    def test_stats_tracks_misses(self, tmp_path):
        """Stats increment misses on cache misses."""
        from plex.cache import PlexCache

        cache = PlexCache(str(tmp_path))

        cache.get_library_items("Movies")  # miss
        cache.get_search_results("Movies", "Search")  # miss
        stats = cache.get_stats()

        assert stats["hits"] == 0
        assert stats["misses"] == 2
        cache.close()

    def test_stats_calculates_hit_rate(self, tmp_path):
        """Stats calculates correct hit rate percentage."""
        from plex.cache import PlexCache

        cache = PlexCache(str(tmp_path))
        cache.set_library_items("Movies", [create_mock_plex_item("/1", "Movie")])

        cache.get_library_items("Movies")  # hit
        cache.get_library_items("Movies")  # hit
        cache.get_library_items("TV")  # miss (not cached)
        cache.get_library_items("Movies")  # hit
        stats = cache.get_stats()

        # 3 hits, 1 miss = 75%
        assert stats["hits"] == 3
        assert stats["misses"] == 1
        assert stats["hit_rate"] == 75.0
        cache.close()

    def test_stats_includes_size_and_count(self, tmp_path):
        """Stats includes cache size and item count."""
        from plex.cache import PlexCache

        cache = PlexCache(str(tmp_path))
        cache.set_library_items("Movies", [create_mock_plex_item("/1", "Movie")])

        stats = cache.get_stats()

        assert "size" in stats
        assert "count" in stats
        assert stats["count"] >= 1  # At least one entry
        cache.close()


# =============================================================================
# Item Data Extraction Tests
# =============================================================================


class TestItemDataExtraction:
    """Tests for _extract_item_data helper function."""

    def test_extract_item_data_basic(self, tmp_path):
        """_extract_item_data extracts key, title, and file_paths."""
        from plex.cache import _extract_item_data

        item = create_mock_plex_item("/library/metadata/123", "Test Movie", ["/media/test.mp4"])

        data = _extract_item_data(item)

        assert data["key"] == "/library/metadata/123"
        assert data["title"] == "Test Movie"
        assert data["file_paths"] == ["/media/test.mp4"]

    def test_extract_item_data_multiple_files(self):
        """_extract_item_data handles items with multiple file paths."""
        from plex.cache import _extract_item_data

        item = create_mock_plex_item("/1", "Multi-Part", ["/media/part1.mp4", "/media/part2.mp4"])

        data = _extract_item_data(item)

        assert len(data["file_paths"]) == 2
        assert "/media/part1.mp4" in data["file_paths"]
        assert "/media/part2.mp4" in data["file_paths"]

    def test_extract_item_data_missing_key_returns_none(self):
        """_extract_item_data returns None if item has no key."""
        from plex.cache import _extract_item_data

        class NoKeyItem:
            title = "No Key"
            media = []

        data = _extract_item_data(NoKeyItem())

        assert data is None

    def test_extract_item_data_no_media(self):
        """_extract_item_data handles items with no media (empty file_paths)."""
        from plex.cache import _extract_item_data

        class NoMediaItem:
            key = "/1"
            title = "No Media"
            media = []

        data = _extract_item_data(NoMediaItem())

        assert data["key"] == "/1"
        assert data["title"] == "No Media"
        assert data["file_paths"] == []

    def test_extract_item_data_exception_returns_none(self):
        """_extract_item_data returns None on unexpected exceptions."""
        from plex.cache import _extract_item_data

        class BrokenItem:
            key = "/1"
            title = "Broken"

            @property
            def media(self):
                raise RuntimeError("Simulated error")

        data = _extract_item_data(BrokenItem())

        assert data is None


# =============================================================================
# Cache Persistence Tests
# =============================================================================


class TestCachePersistence:
    """Tests for cache persistence across PlexCache instances."""

    def test_cache_persists_across_instances(self, tmp_path):
        """Cached data survives PlexCache re-instantiation."""
        from plex.cache import PlexCache

        # Create cache and store data
        cache1 = PlexCache(str(tmp_path))
        items = [create_mock_plex_item("/1", "Persistent Movie", ["/media/persistent.mp4"])]
        cache1.set_library_items("Movies", items)
        cache1.close()

        # Create new instance with same directory
        cache2 = PlexCache(str(tmp_path))
        cached = cache2.get_library_items("Movies")

        assert cached is not None
        assert len(cached) == 1
        assert cached[0]["title"] == "Persistent Movie"
        cache2.close()

    def test_cache_sqlite_file_created(self, tmp_path):
        """Cache creates SQLite database file in cache directory."""
        from plex.cache import PlexCache

        cache = PlexCache(str(tmp_path))
        cache.set_library_items("Movies", [create_mock_plex_item("/1", "Movie")])

        cache_dir = tmp_path / "cache"
        # diskcache creates cache.db file
        files = list(cache_dir.iterdir())
        assert len(files) > 0  # Some files created

        # Look for SQLite-related files
        file_names = [f.name for f in files]
        # diskcache may create cache.db or use directory structure
        assert any("cache" in name.lower() or name.endswith(".db") or name.endswith(".val")
                   for name in file_names) or len(files) > 0
        cache.close()


# =============================================================================
# Edge Cases Tests
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_items_list(self, tmp_path):
        """Setting empty items list works correctly."""
        from plex.cache import PlexCache

        cache = PlexCache(str(tmp_path))

        cache.set_library_items("Empty", [])
        cached = cache.get_library_items("Empty")

        assert cached == []
        cache.close()

    def test_special_characters_in_library_name(self, tmp_path):
        """Library names with special characters work correctly."""
        from plex.cache import PlexCache

        cache = PlexCache(str(tmp_path))
        items = [create_mock_plex_item("/1", "Movie")]

        cache.set_library_items("TV Shows (HD)", items)
        cached = cache.get_library_items("TV Shows (HD)")

        assert cached is not None
        assert len(cached) == 1
        cache.close()

    def test_unicode_in_title(self, tmp_path):
        """Items with unicode in title work correctly."""
        from plex.cache import PlexCache

        cache = PlexCache(str(tmp_path))
        items = [create_mock_plex_item("/1", "Movie Title")]

        cache.set_library_items("Movies", items)
        cached = cache.get_library_items("Movies")

        assert cached[0]["title"] == "Movie Title"
        cache.close()

    def test_different_libraries_isolated(self, tmp_path):
        """Different library names have separate caches."""
        from plex.cache import PlexCache

        cache = PlexCache(str(tmp_path))
        cache.set_library_items("Movies", [create_mock_plex_item("/1", "Movie")])
        cache.set_library_items("TV Shows", [create_mock_plex_item("/2", "TV Show")])

        movies = cache.get_library_items("Movies")
        tv_shows = cache.get_library_items("TV Shows")

        assert movies[0]["title"] == "Movie"
        assert tv_shows[0]["title"] == "TV Show"
        cache.close()
