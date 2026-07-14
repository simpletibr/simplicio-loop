"""Lightweight timeit-based performance budgets for hot paths.

No benchmark previously existed for CLI dispatch or the mechanical-edit
apply path (the two hottest per-invocation code paths: every ``simplicio-py``
call parses argv and dispatches, and every mechanical-edit-backed command
applies a diff to disk). These are not micro-benchmarks meant to catch small
regressions — they assert a generous wall-clock budget so a genuine
performance cliff (e.g. an accidental O(n^2) loop or a blocking network call
introduced on a hot path) fails CI, while staying robust to normal
machine-to-machine variance.
"""

from __future__ import annotations

import time

from simplicio import cli
from simplicio.mechanical_edit import execute_plan


def _write(path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def test_cli_version_dispatch_is_fast(monkeypatch, capsys):
    """argv parsing + dispatch for the cheapest command (`--version`) should
    be effectively instantaneous; this catches accidental heavy work (e.g. a
    network call or disk scan) creeping into module import or dispatch."""
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")

    # Warm up import caches once outside the timed region.
    cli.main(["--version"])
    capsys.readouterr()

    iterations = 20
    start = time.perf_counter()
    for _ in range(iterations):
        assert cli.main(["--version"]) == 0
    elapsed = time.perf_counter() - start
    capsys.readouterr()

    per_call = elapsed / iterations
    print(f"\nBENCH cli --version dispatch: {per_call * 1000:.3f} ms/call ({iterations} calls)")
    # Generous budget (50ms/call) — this is a regression tripwire, not a
    # tight perf target.
    assert per_call < 0.05, f"cli.main(['--version']) took {per_call * 1000:.1f} ms/call, expected < 50ms"


def test_mechanical_edit_apply_replace_range_is_fast(tmp_path, monkeypatch):
    """Applying a small replace_range plan (the core of every mechanical-edit
    apply/dry-run) should complete well under a second per call even
    including transaction bookkeeping and disk I/O."""
    monkeypatch.setenv("SIMPLICIO_DEV_CLI_NO_RUNTIME_EDIT", "1")
    target = tmp_path / "app.py"
    _write(target, "line1\nline2\nline3\n" * 20)

    plan = {
        "schema": "simplicio.mechanical-edit/v1",
        "touched_files": ["app.py"],
        "operations": [
            {
                "op": "replace_range",
                "path": "app.py",
                "start_line": 1,
                "end_line": 1,
                "text": "replaced\n",
            }
        ],
    }

    iterations = 10
    start = time.perf_counter()
    for _ in range(iterations):
        result = execute_plan(plan, root=tmp_path, apply=True)
        assert result["status"] == "ok"
    elapsed = time.perf_counter() - start

    per_call = elapsed / iterations
    print(f"\nBENCH mechanical_edit apply: {per_call * 1000:.3f} ms/call ({iterations} calls)")
    assert per_call < 1.0, f"execute_plan(apply=True) took {per_call * 1000:.1f} ms/call, expected < 1000ms"
