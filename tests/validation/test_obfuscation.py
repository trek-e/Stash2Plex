"""Tests for path obfuscation utility."""

import pytest
from validation.obfuscation import (
    configure_obfuscation,
    obfuscate_path,
    reset_obfuscation,
    WORD_LIST,
)


@pytest.fixture(autouse=True)
def clean_state():
    """Reset obfuscation state before and after each test."""
    reset_obfuscation()
    yield
    reset_obfuscation()


class TestObfuscatePathDisabled:
    """When obfuscation is disabled, paths pass through unchanged."""

    def test_returns_original_path(self):
        path = "/media/videos/Studio/scene.mp4"
        assert obfuscate_path(path) == path

    def test_returns_empty_string(self):
        assert obfuscate_path("") == ""

    def test_returns_none_equivalent(self):
        assert obfuscate_path("") == ""


class TestObfuscatePathEnabled:
    """When obfuscation is enabled, paths are transformed."""

    def setup_method(self):
        configure_obfuscation(True)

    def test_path_is_changed(self):
        path = "/media/videos/Studio/scene.mp4"
        result = obfuscate_path(path)
        assert result != path

    def test_preserves_file_extension(self):
        result = obfuscate_path("/data/files/video.mp4")
        assert result.endswith(".mp4")

    def test_preserves_leading_slash(self):
        result = obfuscate_path("/data/files/video.mp4")
        assert result.startswith("/")

    def test_no_leading_slash_when_relative(self):
        result = obfuscate_path("data/files/video.mp4")
        assert not result.startswith("/")

    def test_deterministic_within_session(self):
        path = "/media/videos/Studio/scene.mp4"
        result1 = obfuscate_path(path)
        result2 = obfuscate_path(path)
        assert result1 == result2

    def test_different_paths_produce_different_results(self):
        result_a = obfuscate_path("/path/a/file1.mp4")
        result_b = obfuscate_path("/path/b/file2.mp4")
        assert result_a != result_b

    def test_same_segment_same_word(self):
        """Same directory name in different paths maps to same word."""
        result_a = obfuscate_path("/media/Studio/video1.mp4")
        result_b = obfuscate_path("/media/Studio/video2.mp4")
        # Both should have the same obfuscated word for "Studio"
        parts_a = result_a.split("/")
        parts_b = result_b.split("/")
        # parts: ['', 'word_for_media', 'word_for_Studio', 'word_for_video1.mp4']
        assert parts_a[2] == parts_b[2]  # "Studio" maps to same word

    def test_preserves_path_depth(self):
        path = "/a/b/c/d/file.mp4"
        result = obfuscate_path(path)
        # Should have same number of segments
        assert result.count("/") == path.count("/")

    def test_only_uses_words_from_list(self):
        result = obfuscate_path("/some/deep/path/file.txt")
        parts = result.strip("/").split("/")
        for part in parts:
            # Strip extension and collision suffix for check
            stem = part.rsplit(".", 1)[0] if "." in part else part
            # Remove collision suffix digits
            base = stem.rstrip("0123456789")
            assert base in WORD_LIST, f"'{base}' not in WORD_LIST"

    def test_empty_string_passthrough(self):
        assert obfuscate_path("") == ""

    def test_handles_no_extension(self):
        result = obfuscate_path("/data/files/README")
        assert "/" in result
        # Last segment should be a word with no extension
        last = result.split("/")[-1]
        assert "." not in last


class TestWindowsPaths:
    """Test Windows-style path handling."""

    def setup_method(self):
        configure_obfuscation(True)

    def test_backslash_paths(self):
        result = obfuscate_path("C:\\Users\\media\\video.mp4")
        assert result.endswith(".mp4")
        assert "\\" in result


class TestCollisionHandling:
    """Test that hash collisions are handled gracefully."""

    def setup_method(self):
        configure_obfuscation(True)

    def test_many_segments_dont_crash(self):
        """Even with many unique segments, obfuscation completes."""
        for i in range(100):
            result = obfuscate_path(f"/dir_{i}/file_{i}.mp4")
            assert result.endswith(".mp4")

    def test_collision_gets_suffix(self):
        """If two different segments hash to the same base word, one gets a numeric suffix."""
        configure_obfuscation(True)
        words = []
        for i in range(200):
            result = obfuscate_path(f"/unique_segment_{i}/file.mp4")
            word = result.strip("/").split("/")[0]
            words.append(word)
        # With 200 segments and 64 base words, collisions are guaranteed
        # Collision handling appends numeric suffixes like "Fox2", "Fox3"
        suffixed = [w for w in words if w[-1].isdigit()]
        assert len(suffixed) > 0, "Expected some words with numeric collision suffixes"


class TestConfigureObfuscation:
    """Test configuration functions."""

    def test_configure_true_enables(self):
        configure_obfuscation(True)
        path = "/test/file.mp4"
        assert obfuscate_path(path) != path

    def test_configure_false_disables(self):
        configure_obfuscation(False)
        path = "/test/file.mp4"
        assert obfuscate_path(path) == path

    def test_reconfigure_resets_mapping(self):
        """Reconfiguring clears the session mapping."""
        configure_obfuscation(True)
        result1 = obfuscate_path("/test/file.mp4")
        # Reconfigure (new session)
        configure_obfuscation(True)
        result2 = obfuscate_path("/test/file.mp4")
        # Same hash-based logic, so same result (deterministic)
        # But the internal _segment_map was cleared
        assert result1 == result2  # Deterministic from hash

    def test_reset_clears_state(self):
        configure_obfuscation(True)
        assert obfuscate_path("/a/b.mp4") != "/a/b.mp4"
        reset_obfuscation()
        assert obfuscate_path("/a/b.mp4") == "/a/b.mp4"
