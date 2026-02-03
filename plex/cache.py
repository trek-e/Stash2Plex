"""
Disk-backed cache for Plex library data.

Provides a PlexCache class that stores Plex library data on disk using diskcache
with TTL-based expiration. This reduces Plex API calls by caching:
- Library items (all() results)
- Search results

Key design decisions:
- SQLite-backed storage via diskcache (same pattern as persist-queue)
- Store only essential item data (key, title, file paths) to avoid memory bloat
- 1-hour TTL for library data (balances freshness vs API savings)
- 100MB default size limit to prevent unbounded growth

Example:
    >>> from plex.cache import PlexCache
    >>> cache = PlexCache("/path/to/data_dir")
    >>> # Cache library items
    >>> items = plex_library.all()
    >>> cache.set_library_items("Movies", items)
    >>> # Later retrieval (cache hit)
    >>> cached = cache.get_library_items("Movies")
    >>> if cached is not None:
    ...     print(f"Cache hit: {len(cached)} items")
"""

import logging
import os
from typing import Any, Dict, List, Optional

from diskcache import Cache

logger = logging.getLogger('PlexSync.plex.cache')


def _extract_item_data(item: Any) -> Optional[Dict[str, Any]]:
    """
    Extract essential fields from a plexapi Video object.

    Only extracts data needed for matching: key, title, and file paths.
    This avoids pickling full plexapi objects which can cause memory bloat.

    Args:
        item: A plexapi Video object (Movie, Episode, etc.)

    Returns:
        Dict with essential fields, or None if extraction fails

    Example:
        >>> data = _extract_item_data(plex_item)
        >>> print(data)
        {'key': '/library/metadata/123', 'title': 'Movie Title', 'file_paths': ['/media/movie.mp4']}
    """
    try:
        # Extract key and title
        key = getattr(item, 'key', None) or getattr(item, 'ratingKey', None)
        title = getattr(item, 'title', None)

        if key is None:
            logger.debug("Item missing key, skipping")
            return None

        # Extract file paths from media[].parts[].file
        file_paths = []
        media_list = getattr(item, 'media', None) or []
        for media in media_list:
            parts = getattr(media, 'parts', None) or []
            for part in parts:
                file_path = getattr(part, 'file', None)
                if file_path:
                    file_paths.append(file_path)

        return {
            'key': str(key),
            'title': title,
            'file_paths': file_paths,
        }
    except Exception as e:
        logger.warning(f"Failed to extract item data: {e}")
        return None


class PlexCache:
    """
    Disk-backed cache for Plex library data.

    Uses diskcache.Cache for SQLite-backed storage with TTL support.
    Stores only essential item data (keys, titles, file paths) to avoid
    memory bloat from caching full plexapi objects.

    Args:
        data_dir: Base directory for cache storage (cache/ subdirectory created)
        library_ttl: TTL in seconds for library data (default: 3600 = 1 hour)
        size_limit: Maximum cache size in bytes (default: 100MB)

    Example:
        >>> cache = PlexCache("/data/plexsync", library_ttl=1800)
        >>> # Store items (extracts essential data only)
        >>> cache.set_library_items("Movies", plex_library.all())
        >>> # Retrieve later (returns simplified dicts)
        >>> items = cache.get_library_items("Movies")
        >>> for item in items:
        ...     print(f"{item['title']}: {item['file_paths']}")
    """

    # Default TTL: 1 hour per RESEARCH.md recommendation
    DEFAULT_LIBRARY_TTL = 3600

    # Default size limit: 100MB
    DEFAULT_SIZE_LIMIT = 100 * 1024 * 1024

    def __init__(
        self,
        data_dir: str,
        library_ttl: int = DEFAULT_LIBRARY_TTL,
        size_limit: int = DEFAULT_SIZE_LIMIT,
    ) -> None:
        """
        Initialize cache in data_dir/cache/ directory.

        Args:
            data_dir: Base directory (cache/ subdirectory will be created)
            library_ttl: TTL in seconds for library data
            size_limit: Maximum cache size in bytes
        """
        self._data_dir = data_dir
        self._library_ttl = library_ttl
        self._size_limit = size_limit

        # Create cache directory
        cache_dir = os.path.join(data_dir, 'cache')
        os.makedirs(cache_dir, exist_ok=True)

        # Initialize diskcache with size limit
        self._cache = Cache(cache_dir, size_limit=size_limit)

        # Enable statistics tracking
        self._cache.stats(enable=True)

        # Track custom stats for this session
        self._hits = 0
        self._misses = 0

        logger.debug(f"PlexCache initialized at {cache_dir} (TTL: {library_ttl}s, limit: {size_limit} bytes)")

    def _make_library_key(self, library_name: str) -> str:
        """Generate cache key for library items."""
        return f"library:{library_name}:all"

    def _make_search_key(self, library_name: str, title: str) -> str:
        """Generate cache key for search results."""
        return f"search:{library_name}:{title}"

    def get_library_items(self, library_name: str) -> Optional[List[Dict[str, Any]]]:
        """
        Get cached library items.

        Returns simplified dicts (not plexapi objects) with:
        - key: Plex item key
        - title: Item title
        - file_paths: List of file paths

        Args:
            library_name: Name of the Plex library section

        Returns:
            List of item dicts if cached, None if cache miss

        Example:
            >>> items = cache.get_library_items("Movies")
            >>> if items is not None:
            ...     for item in items:
            ...         print(f"{item['key']}: {item['title']}")
        """
        cache_key = self._make_library_key(library_name)
        result = self._cache.get(cache_key)

        if result is not None:
            self._hits += 1
            logger.debug(f"Cache hit for library '{library_name}' ({len(result)} items)")
        else:
            self._misses += 1
            logger.debug(f"Cache miss for library '{library_name}'")

        return result

    def set_library_items(self, library_name: str, items: List[Any]) -> None:
        """
        Cache library items, extracting only essential fields.

        Transforms plexapi Video objects into simplified dicts containing
        only key, title, and file paths to avoid memory bloat.

        Args:
            library_name: Name of the Plex library section
            items: List of plexapi Video objects (Movie, Episode, etc.)

        Example:
            >>> library = plex.library.section("Movies")
            >>> cache.set_library_items("Movies", library.all())
        """
        cache_key = self._make_library_key(library_name)

        # Extract essential data from each item
        extracted_items = []
        for item in items:
            data = _extract_item_data(item)
            if data is not None:
                extracted_items.append(data)

        self._cache.set(cache_key, extracted_items, expire=self._library_ttl)
        logger.debug(f"Cached {len(extracted_items)} items for library '{library_name}' (TTL: {self._library_ttl}s)")

    def get_search_results(self, library_name: str, title: str) -> Optional[List[Dict[str, Any]]]:
        """
        Get cached search results.

        Args:
            library_name: Name of the Plex library section
            title: Search title

        Returns:
            List of item dicts if cached, None if cache miss

        Example:
            >>> results = cache.get_search_results("Movies", "Inception")
            >>> if results is not None:
            ...     print(f"Found {len(results)} cached results")
        """
        cache_key = self._make_search_key(library_name, title)
        result = self._cache.get(cache_key)

        if result is not None:
            self._hits += 1
            logger.debug(f"Cache hit for search '{library_name}:{title}' ({len(result)} results)")
        else:
            self._misses += 1
            logger.debug(f"Cache miss for search '{library_name}:{title}'")

        return result

    def set_search_results(self, library_name: str, title: str, results: List[Any]) -> None:
        """
        Cache search results.

        Args:
            library_name: Name of the Plex library section
            title: Search title
            results: List of plexapi Video objects from search

        Example:
            >>> results = library.search(title="Inception")
            >>> cache.set_search_results("Movies", "Inception", results)
        """
        cache_key = self._make_search_key(library_name, title)

        # Extract essential data from each result
        extracted_results = []
        for item in results:
            data = _extract_item_data(item)
            if data is not None:
                extracted_results.append(data)

        self._cache.set(cache_key, extracted_results, expire=self._library_ttl)
        logger.debug(f"Cached {len(extracted_results)} search results for '{library_name}:{title}'")

    def clear(self) -> None:
        """
        Clear all cached data.

        Removes all entries from the cache. Use when:
        - Plex library has been rescanned
        - Cache data appears stale
        - Manual cache reset requested

        Example:
            >>> cache.clear()
            >>> print("Cache cleared")
        """
        self._cache.clear()
        self._hits = 0
        self._misses = 0
        logger.info("Cache cleared")

    def get_stats(self) -> Dict[str, Any]:
        """
        Get cache hit/miss statistics.

        Returns session statistics for monitoring cache effectiveness.

        Returns:
            Dict with keys:
            - hits: Number of cache hits this session
            - misses: Number of cache misses this session
            - hit_rate: Hit rate as percentage (0-100)
            - size: Current cache size in bytes
            - count: Number of cached items

        Example:
            >>> stats = cache.get_stats()
            >>> print(f"Hit rate: {stats['hit_rate']:.1f}%")
        """
        total = self._hits + self._misses
        hit_rate = (self._hits / total * 100) if total > 0 else 0.0

        # Get diskcache internal stats
        try:
            size = self._cache.volume()
        except Exception:
            size = 0

        try:
            count = len(self._cache)
        except Exception:
            count = 0

        return {
            'hits': self._hits,
            'misses': self._misses,
            'hit_rate': hit_rate,
            'size': size,
            'count': count,
        }

    def close(self) -> None:
        """
        Close the cache connection.

        Should be called when done using the cache to release resources.

        Example:
            >>> cache = PlexCache("/data")
            >>> try:
            ...     # use cache
            ...     pass
            ... finally:
            ...     cache.close()
        """
        self._cache.close()
        logger.debug("Cache closed")

    def __repr__(self) -> str:
        """Return string representation of cache."""
        stats = self.get_stats()
        return (
            f"PlexCache(data_dir={self._data_dir!r}, "
            f"ttl={self._library_ttl}, "
            f"items={stats['count']}, "
            f"hit_rate={stats['hit_rate']:.1f}%)"
        )
