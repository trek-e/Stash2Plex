"""
Tests for sanitize_for_plex function.

Tests text sanitization including control character removal, smart quote
conversion, whitespace normalization, and truncation behavior.
"""

import pytest

from validation.sanitizers import sanitize_for_plex


class TestSanitizeForPlexBasicInput:
    """Tests for basic input handling."""

    def test_returns_empty_for_none(self):
        """None input returns empty string."""
        assert sanitize_for_plex(None) == ""

    def test_returns_empty_for_empty_string(self):
        """Empty string input returns empty string."""
        assert sanitize_for_plex("") == ""

    def test_preserves_normal_text(self):
        """Normal ASCII text is unchanged."""
        assert sanitize_for_plex("Hello World") == "Hello World"

    def test_preserves_unicode_letters(self):
        """Unicode letters (non-control) are preserved."""
        assert sanitize_for_plex("Caf\u00e9") == "Caf\u00e9"  # e with acute

    def test_preserves_numbers(self):
        """Numbers are unchanged."""
        assert sanitize_for_plex("Test 123") == "Test 123"

    def test_preserves_punctuation(self):
        """Basic punctuation is preserved."""
        assert sanitize_for_plex("Hello, World!") == "Hello, World!"


class TestSanitizeForPlexControlCharacterRemoval:
    """Tests for control character removal."""

    def test_removes_null_bytes(self):
        """Null bytes are removed."""
        result = sanitize_for_plex("Hello\x00World")
        assert "\x00" not in result
        assert "Hello" in result
        assert "World" in result

    def test_removes_control_chars_start(self):
        """Control chars at start are removed."""
        result = sanitize_for_plex("\x01\x02Test")
        assert "\x01" not in result
        assert "\x02" not in result
        assert "Test" in result

    def test_removes_control_chars_end(self):
        """Control chars at end are removed."""
        result = sanitize_for_plex("Test\x1e\x1f")
        assert "\x1e" not in result
        assert "\x1f" not in result
        assert result == "Test"

    def test_removes_control_chars_middle(self):
        """Control chars in middle are removed."""
        result = sanitize_for_plex("A\x0fB")
        assert "\x0f" not in result
        assert "A" in result
        assert "B" in result

    def test_removes_tab_characters(self):
        """Tab characters (Cc category) are removed entirely."""
        result = sanitize_for_plex("Hello\tWorld")
        assert "\t" not in result
        # Tab is control char, removed entirely (not replaced with space)
        assert result == "HelloWorld"

    def test_removes_form_feed(self):
        """Form feed character is removed."""
        result = sanitize_for_plex("Hello\x0cWorld")
        assert "\x0c" not in result

    def test_removes_vertical_tab(self):
        """Vertical tab character is removed."""
        result = sanitize_for_plex("Hello\x0bWorld")
        assert "\x0b" not in result

    def test_removes_format_chars(self):
        """Unicode format characters (zero-width) are removed."""
        # Zero-width space (U+200B)
        result = sanitize_for_plex("Hello\u200bWorld")
        assert "\u200b" not in result

        # Zero-width non-joiner (U+200C)
        result2 = sanitize_for_plex("Hello\u200cWorld")
        assert "\u200c" not in result2

        # Zero-width joiner (U+200D)
        result3 = sanitize_for_plex("Hello\u200dWorld")
        assert "\u200d" not in result3


class TestSanitizeForPlexSmartQuoteConversion:
    """Tests for smart quote and typographic character conversion."""

    def test_converts_left_double_quote(self):
        """Left double quotation mark is converted to ASCII."""
        assert '"' in sanitize_for_plex("\u201cQuote")
        assert "\u201c" not in sanitize_for_plex("\u201cQuote")

    def test_converts_right_double_quote(self):
        """Right double quotation mark is converted to ASCII."""
        assert '"' in sanitize_for_plex("Quote\u201d")
        assert "\u201d" not in sanitize_for_plex("Quote\u201d")

    def test_converts_left_single_quote(self):
        """Left single quotation mark is converted to apostrophe."""
        result = sanitize_for_plex("\u2018Hello")
        assert "'" in result
        assert "\u2018" not in result

    def test_converts_right_single_quote(self):
        """Right single quotation mark is converted to apostrophe."""
        result = sanitize_for_plex("Hello\u2019s")
        assert "'" in result
        assert "\u2019" not in result

    def test_converts_en_dash(self):
        """En dash is converted to hyphen-minus."""
        result = sanitize_for_plex("2020\u20132021")
        assert result == "2020-2021"
        assert "\u2013" not in result

    def test_converts_em_dash(self):
        """Em dash is converted to hyphen-minus."""
        result = sanitize_for_plex("Word\u2014word")
        assert result == "Word-word"
        assert "\u2014" not in result

    def test_converts_ellipsis(self):
        """Horizontal ellipsis is converted to three dots."""
        result = sanitize_for_plex("Wait\u2026")
        assert result == "Wait..."
        assert "\u2026" not in result

    def test_multiple_smart_quotes(self):
        """Multiple smart quotes in one string are all converted."""
        result = sanitize_for_plex("\u201cHello\u201d and \u2018goodbye\u2019")
        assert result == '"Hello" and \'goodbye\''


class TestSanitizeForPlexWhitespaceNormalization:
    """Tests for whitespace normalization."""

    def test_collapses_multiple_spaces(self):
        """Multiple consecutive spaces collapse to single space."""
        assert sanitize_for_plex("a  b   c") == "a b c"

    def test_removes_tabs(self):
        """Tabs (control chars) are removed entirely."""
        # Tabs are Cc category, removed not converted to space
        assert sanitize_for_plex("a\tb") == "ab"

    def test_removes_newlines(self):
        """Newlines (control chars) are removed entirely."""
        # Newlines are Cc category, removed not converted to space
        assert sanitize_for_plex("a\nb") == "ab"

    def test_removes_carriage_returns(self):
        """Carriage returns (control chars) are removed entirely."""
        # CR is Cc category, removed not converted to space
        assert sanitize_for_plex("a\rb") == "ab"

    def test_removes_crlf(self):
        """CRLF (control chars) are removed entirely."""
        assert sanitize_for_plex("a\r\nb") == "ab"

    def test_strips_leading_whitespace(self):
        """Leading whitespace is stripped."""
        assert sanitize_for_plex("  text") == "text"

    def test_strips_trailing_whitespace(self):
        """Trailing whitespace is stripped."""
        assert sanitize_for_plex("text  ") == "text"

    def test_strips_leading_trailing_combined(self):
        """Both leading and trailing whitespace is stripped."""
        assert sanitize_for_plex("  text  ") == "text"

    def test_mixed_whitespace(self):
        """Mixed whitespace types are normalized."""
        assert sanitize_for_plex(" \t a \n b \r c  ") == "a b c"


class TestSanitizeForPlexTruncation:
    """Tests for text truncation behavior."""

    def test_no_truncation_under_limit(self):
        """Text under max_length is not truncated."""
        text = "x" * 200
        result = sanitize_for_plex(text, max_length=255)
        assert len(result) == 200

    def test_truncation_at_max_length(self):
        """Text over max_length is truncated."""
        text = "x" * 300
        result = sanitize_for_plex(text, max_length=255)
        assert len(result) <= 255

    def test_truncation_prefers_word_boundary(self):
        """Truncation prefers word boundary when available."""
        # Create text with spaces that exceeds max_length
        text = "word " * 60  # 300 chars
        result = sanitize_for_plex(text, max_length=255)
        # Should end at a word boundary (no trailing partial word)
        assert len(result) <= 255
        assert not result.endswith("wor")  # No partial word

    def test_truncation_hard_cut_when_no_good_boundary(self):
        """Truncation uses hard cut when no good word boundary."""
        # Single long "word" with no spaces
        text = "x" * 300
        result = sanitize_for_plex(text, max_length=255)
        assert len(result) == 255  # Hard cut

    def test_truncation_with_zero_max_length_no_limit(self):
        """max_length=0 means no truncation."""
        text = "x" * 500
        result = sanitize_for_plex(text, max_length=0)
        assert len(result) == 500

    def test_truncation_respects_word_boundary_threshold(self):
        """Truncation only uses word boundary if it's >80% of max_length."""
        # Create text where last space is at 70% (below threshold)
        # "short_text " (11 chars) + "x"*244 = 255 total, space at position 10 (~4%)
        text = "short_text " + "x" * 244 + "extra"  # Space early, then continuous chars
        result = sanitize_for_plex(text, max_length=255)
        # Space at position 10 is <80% of 255, so hard cut at 255
        assert len(result) == 255

    def test_default_max_length_is_255(self):
        """Default max_length is 255 characters."""
        text = "x" * 300
        result = sanitize_for_plex(text)  # No max_length specified
        assert len(result) == 255


class TestSanitizeForPlexUnicodeNormalization:
    """Tests for Unicode normalization."""

    def test_normalizes_to_nfc(self):
        """Text is normalized to NFC form."""
        # e + combining acute = e with acute (NFC composed)
        decomposed = "e\u0301"  # e + combining acute accent (NFD)
        result = sanitize_for_plex(decomposed)
        # Should be composed form
        assert result == "\u00e9" or len(result) == 1  # Either composed or simplified


class TestSanitizeForPlexWithLogger:
    """Tests for logger parameter."""

    def test_logs_when_text_changed(self, mocker):
        """Logger is called when text is sanitized."""
        mock_logger = mocker.MagicMock()
        sanitize_for_plex("Hello\x00World", logger=mock_logger)
        mock_logger.debug.assert_called_once()

    def test_no_log_when_text_unchanged(self, mocker):
        """Logger is not called when text is unchanged."""
        mock_logger = mocker.MagicMock()
        sanitize_for_plex("Hello World", logger=mock_logger)
        mock_logger.debug.assert_not_called()


class TestSanitizeForPlexEdgeCases:
    """Edge case tests."""

    def test_only_whitespace_becomes_empty(self):
        """String of only whitespace becomes empty."""
        assert sanitize_for_plex("   ") == ""
        assert sanitize_for_plex("\t\n\r") == ""

    def test_only_control_chars_becomes_empty(self):
        """String of only control chars becomes empty."""
        assert sanitize_for_plex("\x00\x01\x02") == ""

    def test_mixed_control_and_whitespace_becomes_empty(self):
        """Mixed control chars and whitespace becomes empty."""
        assert sanitize_for_plex("\x00 \t \x01") == ""

    def test_single_character(self):
        """Single valid character is preserved."""
        assert sanitize_for_plex("A") == "A"

    def test_exact_max_length(self):
        """Text exactly at max_length is unchanged."""
        text = "x" * 255
        result = sanitize_for_plex(text, max_length=255)
        assert len(result) == 255
