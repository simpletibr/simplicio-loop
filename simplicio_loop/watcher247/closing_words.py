"""Rewrite and detect GitHub closing keywords to/from 'Parte de'."""
import re


# GitHub closing keywords: close, closes, closed, fix, fixes, fixed, resolve, resolves, resolved
_CLOSING_KEYWORDS = {'close', 'closes', 'closed', 'fix', 'fixes', 'fixed', 'resolve', 'resolves', 'resolved'}


def _make_pattern():
    """Create regex pattern for closing keywords with optional separators and issue references."""
    keywords = '|'.join(_CLOSING_KEYWORDS)
    # Pattern: keyword + optional separator (spaces, colon, equals) + issue ref
    # Allows for: "Closes #42", "Closes: #42", "Closes:#42", "Closes : #42", etc.
    # Issue ref: #N, owner/repo#N, or URL
    pattern = (
        r'\b(' + keywords + r')\b'  # closing keyword with word boundaries
        r'(?:\s*[:=]?\s*)'  # optional spaces, colon/equals, spaces (in any combination)
        r'(?=#|[\w\-]+/[\w\-]+#|https://)'  # lookahead for issue reference start (must be there)
        r'(?:#\d+|[\w\-]+/[\w\-]+#\d+|https://github\.com/[\w\-]+/[\w\-]+/issues/\d+)'  # issue reference
    )
    return re.compile(pattern, re.IGNORECASE)


_PATTERN = _make_pattern()


def rewrite(text: str) -> str:
    """
    Rewrite GitHub closing keywords in text to 'Parte de'.
    
    Replaces keywords (close, closes, closed, fix, fixes, fixed, resolve, resolves, resolved)
    followed by an issue reference (#N, owner/repo#N, or https://github.com/owner/repo/issues/N)
    with 'Parte de'. Handles optional colons/equals between keyword and reference,
    and normalizes separators to a single space.
    
    Args:
        text: Text potentially containing GitHub closing keywords.
    
    Returns:
        Text with closing keywords replaced by 'Parte de'.
    """
    def replace_fn(match):
        # Get the full match
        full = match.group(0)
        keyword = match.group(1)
        # Find where the keyword ends in the matched text
        keyword_start_in_match = full.lower().find(keyword.lower())
        keyword_end_in_match = keyword_start_in_match + len(keyword)
        # Get everything after the keyword
        after_keyword = full[keyword_end_in_match:]
        # Extract just the issue reference (skip past separators and spaces)
        reference = after_keyword.lstrip(' \t:=')
        # If there's no reference (shouldn't happen with lookahead), return original
        if not reference:
            return full
        # Return 'Parte de' + single space + reference
        return 'Parte de ' + reference
    
    return _PATTERN.sub(replace_fn, text)


def has_closing(text: str) -> bool:
    """
    Detect if text contains GitHub closing keywords.
    
    Returns True if text contains any GitHub closing keyword (close, closes, closed, 
    fix, fixes, fixed, resolve, resolves, resolved) followed by an issue reference.
    
    Args:
        text: Text to check.
    
    Returns:
        True if closing keywords are present, False otherwise.
    """
    return _PATTERN.search(text) is not None
