"""
Tests for shared_lib.path_mapper — bidirectional regex path mapping engine.

Tests written in RED phase (TDD) before implementation.
"""
import json
import pytest
from shared_lib.path_mapper import PathMapper, PathRule


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_mapper(*rules_kwargs) -> PathMapper:
    """Build a PathMapper from keyword-argument dicts for convenience."""
    rules = [PathRule(**kw) for kw in rules_kwargs]
    return PathMapper(rules)


SIMPLE_RULE = dict(
    name="simple",
    plex_pattern=r"^/plex/media/(.*)",
    stash_pattern=r"/stash/media/\1",
)


# ---------------------------------------------------------------------------
# Basic bidirectional translation
# ---------------------------------------------------------------------------

def test_plex_to_stash_simple_prefix_swap():
    mapper = make_mapper(SIMPLE_RULE)
    result = mapper.plex_to_stash("/plex/media/video.mkv")
    assert result == "/stash/media/video.mkv"


def test_stash_to_plex_simple_prefix_swap():
    mapper = make_mapper(SIMPLE_RULE)
    result = mapper.stash_to_plex("/stash/media/video.mkv")
    assert result == "/plex/media/video.mkv"


def test_plex_to_stash_nested_path():
    mapper = make_mapper(SIMPLE_RULE)
    result = mapper.plex_to_stash("/plex/media/dir/subdir/file.mp4")
    assert result == "/stash/media/dir/subdir/file.mp4"


# ---------------------------------------------------------------------------
# No-match behaviour
# ---------------------------------------------------------------------------

def test_no_match_returns_none():
    mapper = make_mapper(SIMPLE_RULE)
    result = mapper.plex_to_stash("/other/path/file.mkv")
    assert result is None


# ---------------------------------------------------------------------------
# Multiple rules
# ---------------------------------------------------------------------------

def test_multiple_rules_first_match_wins():
    mapper = make_mapper(
        dict(name="rule_a", plex_pattern=r"^/plex/nas/(.*)",   stash_pattern=r"/stash/nas/\1"),
        dict(name="rule_b", plex_pattern=r"^/plex/local/(.*)", stash_pattern=r"/stash/local/\1"),
    )
    assert mapper.plex_to_stash("/plex/nas/file.mkv")   == "/stash/nas/file.mkv"
    assert mapper.plex_to_stash("/plex/local/file.mkv") == "/stash/local/file.mkv"
    # rule_b input should NOT match rule_a
    assert mapper.plex_to_stash("/plex/nas/file.mkv") != "/stash/local/file.mkv"


def test_multiple_rules_priority_order():
    """First rule wins even when a later rule would also match."""
    mapper = make_mapper(
        dict(name="rule_a", plex_pattern=r"^/media/(.*)",         stash_pattern=r"/stash_a/\1"),
        dict(name="rule_b", plex_pattern=r"^/media/special/(.*)", stash_pattern=r"/stash_b/\1"),
    )
    # rule_a is first, so /media/special/file.mkv must route through rule_a
    result = mapper.plex_to_stash("/media/special/file.mkv")
    assert result == "/stash_a/special/file.mkv"
    assert result != "/stash_b/file.mkv"


# ---------------------------------------------------------------------------
# Backslash normalisation
# ---------------------------------------------------------------------------

def test_backslash_normalization():
    mapper = make_mapper(SIMPLE_RULE)
    # Windows-style backslash input
    result = mapper.plex_to_stash("\\plex\\media\\file.mkv")
    assert result == "/stash/media/file.mkv"


# ---------------------------------------------------------------------------
# Case sensitivity
# ---------------------------------------------------------------------------

def test_case_insensitive_flag():
    mapper = make_mapper(
        dict(name="ci", plex_pattern=r"^/plex/media/(.*)", stash_pattern=r"/stash/media/\1",
             case_insensitive=True)
    )
    result = mapper.plex_to_stash("/PLEX/Media/FILE.mkv")
    assert result == "/stash/media/FILE.mkv"


def test_case_sensitive_default():
    """Without case_insensitive=True, uppercase input must not match lowercase pattern."""
    mapper = make_mapper(SIMPLE_RULE)  # case_insensitive defaults to False
    result = mapper.plex_to_stash("/PLEX/media/file.mkv")
    assert result is None


# ---------------------------------------------------------------------------
# from_env class method
# ---------------------------------------------------------------------------

def test_from_env_parses_json():
    env_value = json.dumps([
        {"name": "nas", "plex_pattern": r"^/plex/(.*)", "stash_pattern": r"/stash/\1"}
    ])
    mapper = PathMapper.from_env(env_value)
    result = mapper.plex_to_stash("/plex/video.mkv")
    assert result == "/stash/video.mkv"


def test_from_env_empty_array():
    mapper = PathMapper.from_env("[]")
    assert mapper.plex_to_stash("/any/path.mkv") is None
    assert mapper.stash_to_plex("/any/path.mkv") is None


def test_from_env_invalid_json_raises():
    with pytest.raises((ValueError, Exception)):
        PathMapper.from_env("not json")


# ---------------------------------------------------------------------------
# Bidirectional round-trip
# ---------------------------------------------------------------------------

def test_bidirectional_roundtrip():
    mapper = make_mapper(SIMPLE_RULE)
    original = "/plex/media/dir/movie.mkv"
    stash_path = mapper.plex_to_stash(original)
    assert stash_path is not None
    recovered = mapper.stash_to_plex(stash_path)
    assert recovered == original
