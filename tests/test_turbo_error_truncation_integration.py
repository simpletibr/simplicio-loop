"""Integration tests: error truncation in real turbo/watcher points."""

from simplicio_loop.error_truncation import truncate_error_with_cause


def test_turbo_request_failed_keeps_cause():
    """Test that turbo request error keeps the cause (ValueError) at start."""
    stderr = """Traceback (most recent call last):
  File "turbo.py", line 42, in request
    result = model.generate(...)
  File "model.py", line 89
    raise ValueError("No tokens left in model")
ValueError: No tokens left in model
  Context: tried to generate with 0 tokens
    Trying pool A... failed
    Trying pool B... failed
    Trying pool C... failed
    Trying pool D... failed
    Trying pool E... failed
    No more pools to try
  File "provider.py", line 200
    raise RuntimeError("Quota exhausted")
RuntimeError: Quota exhausted
  Additional context from handler
  Another debug line
  More details about the error
  System state information
  Memory status and configuration"""
    
    bad_reason = (stderr or "")[-300:]
    assert "Traceback" not in bad_reason, "BUG DEMO: cause lost in [-300:]"
    
    good_reason = truncate_error_with_cause(
        stderr or "",
        head_chars=200,
        tail_chars=200,
        total_limit=600
    )
    good_error = f"turbo request failed: {good_reason}"
    
    assert "Traceback" in good_error, f"FIXED: cause should appear. Got: {good_error[:150]}"
    assert "RuntimeError" in good_error, f"FIXED: tail should appear. Got: {good_error[-150:]}"
    assert "truncated" in good_error.lower(), "Should have truncation marker"


def test_verify_parse_turbo_output_keeps_cause():
    """Test that verify.parse_turbo's output_tail keeps cause."""
    output = "FAILED: database connection timeout\n" + ("X" * 600) + """
  Error: connection refused after 30s
  Stack trace: process.py:150 -> handler.py:50 -> db.py:42
  Assertion: expected True, got False
  Details: network is unreachable, check firewall rules"""
    
    _REASON_CAP = 400
    bad_tail = (output or "")[-_REASON_CAP:]
    assert "FAILED" not in bad_tail, "BUG DEMO: cause 'FAILED' lost in [-400:]"
    
    good_tail = truncate_error_with_cause(
        output or "",
        head_chars=150,
        tail_chars=150,
        total_limit=500
    )
    assert "FAILED" in good_tail, f"FIXED: cause should appear. Got start: {good_tail[:100]}"
    assert "firewall" in good_tail or "network" in good_tail, f"FIXED: tail should appear"


def test_stderr_in_point_result_keeps_cause():
    """Test that watcher247/points/judge.py:104 keeps cause."""
    stderr = "error: pathspec 'file.txt' did not match any files\n" + ("Y" * 600) + """
  hint: maybe you misspelled...
  fatal: did not match any file patterns
  Repository state may be corrupted"""
    
    bad_error = (stderr or "")[-300:]
    assert "error:" not in bad_error, "BUG DEMO: cause 'error:' lost in [-300:]"
    
    good_error = truncate_error_with_cause(
        stderr or "",
        head_chars=150,
        tail_chars=150,
        total_limit=500
    )
    assert "error" in good_error.lower(), f"FIXED: cause should appear. Got start: {good_error[:100]}"
    assert "corrupted" in good_error, f"FIXED: tail should appear. Got end: {good_error[-100:]}"
