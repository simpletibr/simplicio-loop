"""Truncate error messages while preserving both cause (start) and traceback end (tail)."""


def truncate_error_with_cause(
    text: str,
    head_chars: int = 200,
    tail_chars: int = 200,
    total_limit: int = 500,
) -> str:
    """Truncate long error messages while keeping cause and tail.
    
    If text is <= total_limit, returns it as-is.
    If text is > total_limit, returns: head + marker + tail.
    
    Args:
        text: The error message (may be multiline traceback)
        head_chars: How many chars to keep from the start (the cause)
        tail_chars: How many chars to keep from the end (the traceback end)
        total_limit: Max length before truncation kicks in
    
    Returns:
        Original text if <= total_limit, otherwise head + marker + tail.
    """
    if len(text) <= total_limit:
        return text
    
    # Calculate how many chars are hidden
    hidden = len(text) - head_chars - tail_chars - len(" ... [X characters truncated] ... ")
    
    head = text[:head_chars]
    tail = text[-tail_chars:]
    marker = f" ... [{hidden:,} characters truncated] ... "
    
    return head + marker + tail
