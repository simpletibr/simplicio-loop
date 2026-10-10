"""Test that error truncation preserves both the cause (start) and the end."""

from simplicio_loop.error_truncation import truncate_error_with_cause


def test_short_error_not_truncated():
    """Error shorter than limit is returned as-is."""
    msg = "ValueError: missing parameter"
    result = truncate_error_with_cause(msg, head_chars=100, tail_chars=100, total_limit=500)
    assert result == msg, f"Short error should not be truncated. Got: {result}"


def test_long_error_keeps_cause_and_tail():
    """Long error keeps first N chars (cause) and last M chars (traceback end) with marker."""
    # Simulate an error with cause at start and traceback at end
    cause = "ValueError: connection timeout in database fetch"
    tail = "File 'db.py' line 42\n  File 'run.py' line 15\n  RuntimeError: out of memory"
    middle = "X" * 5000  # 5000 chars in the middle
    full_error = f"{cause}\n{middle}\n{tail}"
    
    result = truncate_error_with_cause(full_error, head_chars=100, tail_chars=150, total_limit=500)
    
    # Should contain both start and end
    assert cause[:80] in result, f"Cause (start) should be in truncated error. Got: {result[:200]}"
    assert tail[-50:] in result, f"Tail (end) should be in truncated error. Got: {result[-200:]}"
    # Should contain a truncation marker
    assert "truncated" in result.lower() or "..." in result, f"Should have truncation marker. Got: {result}"
    # Should be shorter than original
    assert len(result) < len(full_error), f"Truncated should be shorter"


def test_error_with_traceback_pattern():
    """Test with realistic Python traceback (cause + stack + tail)."""
    # Create a longer traceback that will be truncated
    error_text = """Traceback (most recent call last):
  File "run.py", line 42, in execute
    result = turbo_request(...)
  File "turbo.py", line 156, in turbo_request
    output = model.generate(...)
  File "model.py", line 89, in generate
    raise ValueError("No tokens available")
ValueError: No tokens available
Details: system is out of memory
Stack trace continues with more details
Another file: process.py line 200
And another: handler.py line 50
Final line: RuntimeError: operation failed"""
    
    result = truncate_error_with_cause(
        error_text,
        head_chars=150,  # capture "Traceback" + first few lines
        tail_chars=150,  # capture final lines
        total_limit=400
    )
    
    # Cause (first line "Traceback") should be there
    assert "Traceback" in result, f"Traceback should be at start. Got: {result[:100]}"
    # Tail (RuntimeError line) should be there
    assert "RuntimeError" in result, f"RuntimeError should be at end. Got: {result[-100:]}"
    # Not the full thing
    assert len(result) <= 500, f"Should respect reasonable limit. Got length {len(result)}"


def test_exact_limit_behavior():
    """Test boundary: error exactly at limit is not truncated."""
    msg = "X" * 500
    result = truncate_error_with_cause(msg, head_chars=200, tail_chars=200, total_limit=500)
    assert result == msg, "Error exactly at limit should not be truncated"


def test_truncate_always_includes_marker():
    """Test that truncation always includes a clear marker of what was removed."""
    msg = "Start error message\n" + ("Y" * 2000) + "\nEnd of traceback"
    result = truncate_error_with_cause(
        msg,
        head_chars=100,
        tail_chars=100,
        total_limit=400
    )
    
    assert "Start error" in result, "Should have start"
    assert "End of trace" in result, "Should have end"
    # Marker format: should indicate truncation
    assert any(m in result.lower() for m in ["truncated", "...", "omitted"]), \
        f"Should have a clear truncation marker. Got: {result}"
