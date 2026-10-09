"""closing_words: rewrite GitHub closing keywords to 'Parte de' and detect presence."""
import pytest

from simplicio_loop.watcher247.closing_words import rewrite, has_closing


class TestRewrite:
    """rewrite(text) replaces GitHub closing keywords with 'Parte de'."""

    def test_basic_closes(self):
        """Replaces 'Closes #N' with 'Parte de #N'."""
        assert rewrite("Closes #42") == "Parte de #42"

    def test_close_singular(self):
        """Replaces 'Close #N' with 'Parte de #N'."""
        assert rewrite("Close #42") == "Parte de #42"

    def test_closed_past_tense(self):
        """Replaces 'Closed #N' with 'Parte de #N'."""
        assert rewrite("Closed #42") == "Parte de #42"

    def test_fix_variant(self):
        """Replaces 'Fix #N' with 'Parte de #N'."""
        assert rewrite("Fix #42") == "Parte de #42"

    def test_fixes_variant(self):
        """Replaces 'Fixes #N' with 'Parte de #N'."""
        assert rewrite("Fixes #42") == "Parte de #42"

    def test_fixed_variant(self):
        """Replaces 'Fixed #N' with 'Parte de #N'."""
        assert rewrite("Fixed #42") == "Parte de #42"

    def test_resolve_variant(self):
        """Replaces 'Resolve #N' with 'Parte de #N'."""
        assert rewrite("Resolve #42") == "Parte de #42"

    def test_resolves_variant(self):
        """Replaces 'Resolves #N' with 'Parte de #N'."""
        assert rewrite("Resolves #42") == "Parte de #42"

    def test_resolved_variant(self):
        """Replaces 'Resolved #N' with 'Parte de #N'."""
        assert rewrite("Resolved #42") == "Parte de #42"

    def test_case_insensitive_lower(self):
        """Handles lowercase 'closes'."""
        assert rewrite("closes #42") == "Parte de #42"

    def test_case_insensitive_upper(self):
        """Handles uppercase 'CLOSES'."""
        assert rewrite("CLOSES #42") == "Parte de #42"

    def test_case_insensitive_mixed(self):
        """Handles mixed case 'ClOsEs'."""
        assert rewrite("ClOsEs #42") == "Parte de #42"

    def test_with_colon_separator_no_space(self):
        """Handles colon after keyword with no space: 'Closes:#42'."""
        assert rewrite("Closes:#42") == "Parte de #42"

    def test_with_colon_and_space(self):
        """Handles colon with space: 'Closes : #42' (multiple spaces)."""
        assert rewrite("Closes : #42") == "Parte de #42"

    def test_with_tab_separator(self):
        """Handles tab separator: 'Closes\t#42'."""
        # Tab followed by # should be normalized to single space
        assert rewrite("Closes\t#42") == "Parte de #42"

    def test_owner_repo_reference(self):
        """Handles owner/repo#N format."""
        assert rewrite("Closes owner/repo#42") == "Parte de owner/repo#42"

    def test_owner_repo_with_colon_no_space(self):
        """Handles owner/repo#N with colon, no space."""
        assert rewrite("Closes:owner/repo#42") == "Parte de owner/repo#42"

    def test_quoted_with_double_quotes(self):
        """Handles text in double quotes."""
        assert rewrite('"Closes #42"') == '"Parte de #42"'

    def test_quoted_with_single_quotes(self):
        """Handles text in single quotes."""
        assert rewrite("'Closes #42'") == "'Parte de #42'"

    def test_quoted_with_backticks(self):
        """Handles text in backticks (markdown code)."""
        assert rewrite("`Closes #42`") == "`Parte de #42`"

    def test_in_multiline_text(self):
        """Replaces in multiline text."""
        text = "This PR\nCloses #42\nand fixes things"
        expected = "This PR\nParte de #42\nand fixes things"
        assert rewrite(text) == expected

    def test_multiple_occurrences(self):
        """Replaces multiple occurrences."""
        text = "Closes #1 and fixes #2"
        expected = "Parte de #1 and Parte de #2"
        assert rewrite(text) == expected

    def test_url_format_https(self):
        """Handles URL format: https://github.com/owner/repo/issues/N."""
        text = "Closes https://github.com/owner/repo/issues/42"
        expected = "Parte de https://github.com/owner/repo/issues/42"
        assert rewrite(text) == expected

    def test_no_replacement_for_similar_word(self):
        """Does not replace 'prefixes #42' (word boundary check)."""
        assert rewrite("prefixes #42") == "prefixes #42"

    def test_no_replacement_for_closest(self):
        """Does not replace 'closest #42' (word boundary check)."""
        assert rewrite("closest #42") == "closest #42"

    def test_preserves_non_closing_text(self):
        """Does not touch unrelated text."""
        assert rewrite("This is a normal text") == "This is a normal text"

    def test_double_space_preserved_or_normalized(self):
        """Handles double space between keyword and #."""
        # Double space should be normalized to single space
        assert rewrite("Closes  #42") == "Parte de #42"


class TestHasClosing:
    """has_closing(text) detects GitHub closing keywords."""

    def test_closes_present(self):
        """Returns True when 'Closes' is present."""
        assert has_closing("Closes #42") is True

    def test_fixes_present(self):
        """Returns True when 'Fixes' is present."""
        assert has_closing("Fixes #42") is True

    def test_resolves_present(self):
        """Returns True when 'Resolves' is present."""
        assert has_closing("Resolves #42") is True

    def test_not_present(self):
        """Returns False when no closing keyword is present."""
        assert has_closing("This PR does something") is False

    def test_similar_word_not_matched(self):
        """Returns False for similar words like 'closest'."""
        assert has_closing("This is closest to what we want") is False

    def test_case_insensitive_detection(self):
        """Returns True regardless of case."""
        assert has_closing("CLOSES #42") is True
        assert has_closing("closes #42") is True
        assert has_closing("ClOsEs #42") is True

    def test_in_multiline_text(self):
        """Returns True when closing keyword appears in multiline text."""
        text = "This PR\nCloses #42\nand does something"
        assert has_closing(text) is True

    def test_owner_repo_format(self):
        """Returns True for owner/repo#N format."""
        assert has_closing("Closes owner/repo#42") is True

    def test_url_format(self):
        """Returns True for URL format."""
        assert has_closing("Closes https://github.com/owner/repo/issues/42") is True

    def test_empty_string(self):
        """Returns False for empty string."""
        assert has_closing("") is False

    def test_whitespace_only(self):
        """Returns False for whitespace-only string."""
        assert has_closing("   \n\t  ") is False

    def test_prefixes_not_matched(self):
        """Does not match 'prefixes #N'."""
        assert has_closing("prefixes #42") is False
