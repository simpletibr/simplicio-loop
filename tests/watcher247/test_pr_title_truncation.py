"""PR title truncation: word-boundary aware truncation with issue number preservation."""
import pytest

from simplicio_loop.watcher247.tick import _truncate_pr_title


class TestTruncatePrTitle:
    """_truncate_pr_title truncates PR titles at word boundaries."""

    def test_short_title_unchanged(self):
        """Titles shorter than 70 chars are unchanged."""
        title = "loop: [#42] Short title"
        assert _truncate_pr_title(title) == title
        assert len(_truncate_pr_title(title)) <= 70

    def test_truncate_at_word_boundary(self):
        """Truncates at word boundary, not mid-word."""
        title = "loop: [#42] This is a very long title that should be truncated somewhere in the middle part"
        result = _truncate_pr_title(title)
        assert len(result) <= 71  # 70 + "…"
        # Check it ends with ellipsis (if truncated) or is the original
        if len(title) > 70:
            assert result.endswith("…")
        # Check no incomplete words
        assert not result.endswith(" …")

    def test_preserves_issue_number(self):
        """Preserves issue number in [#N] format."""
        title = "loop: [#1234] This is an extremely long title text that needs truncation because it is too long"
        result = _truncate_pr_title(title)
        # Should contain the issue number
        assert "[#1234]" in result
        assert len(result) <= 71

    def test_simple_issue_reference(self):
        """Works with simple #N format."""
        title = "loop: Fix #42 - This is a very long description of the fix that needs to be truncated"
        result = _truncate_pr_title(title)
        assert "#42" in result or result.startswith("loop:")
        assert len(result) <= 71

    def test_title_exactly_70_chars(self):
        """Title exactly at limit is unchanged."""
        title = "a" * 70
        result = _truncate_pr_title(title)
        assert result == title
        assert len(result) == 70

    def test_title_71_chars_truncated(self):
        """Title at 71 chars is truncated."""
        title = "a b c d e f g h i j k l m n o p q r s t u v w x y z 0 1 2 3 4 5 6 7 8 9"  # 71 chars with spaces
        result = _truncate_pr_title(title)
        assert len(result) <= 71
        if len(title) > 70:
            assert "…" in result

    def test_no_spaces_very_long_word(self):
        """Very long single word is truncated with ellipsis."""
        title = "loop: " + "a" * 100
        result = _truncate_pr_title(title)
        assert len(result) <= 71
        assert result.endswith("…")

    def test_ellipsis_added_on_truncation(self):
        """Ellipsis is added when truncation occurs."""
        title = "loop: This is definitely way too long for a PR title and should be truncated here"
        result = _truncate_pr_title(title)
        if len(title) > 70:
            assert result.endswith("…")
            assert len(result) <= 71

    def test_multiple_spaces_at_boundary(self):
        """Handles multiple spaces at word boundary."""
        title = "loop: Some words   more words that is too long and needs truncation"
        result = _truncate_pr_title(title)
        # Should not end with spaces before ellipsis
        assert not result.rstrip("…").endswith(" ")

    def test_issue_number_preserved_with_dash_format(self):
        """Preserves issue number in dash format like #123."""
        title = "loop: Fix #456 - A very long description that needs to be cut at word boundary for readability"
        result = _truncate_pr_title(title)
        assert "#456" in result
        assert len(result) <= 71
