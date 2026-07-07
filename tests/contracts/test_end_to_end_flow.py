"""#100 — the minimal executor/runtime-integration flow, end to end:

    load mapper artifacts -> classify a small task -> build execution
    contract -> produce structured output -> run a simple local
    verification

against the real fixture project (tests/contracts/fixtures/sample_project),
with no network calls. Covers both legs of "standalone-Python execution
and, where feasible, the integrated-with-runtime path":

- standalone: `simplicio.commands.test_run.run()` falls back to a plain
  subprocess when no `simplicio` Rust binary is on PATH / SIMPLICIO_BIN.
- runtime-integrated: same call, but SIMPLICIO_BIN points at a **stub**
  binary (see conftest.py's `stub_runtime_binary` fixture) — the real
  Rust runtime isn't built in this environment, so this leg is explicitly
  a stub of the delegation contract, not a real integration test. Anything
  claiming otherwise would be faking a real integration; this doesn't.
"""

from __future__ import annotations

import argparse
import json

from simplicio import cli, detect, mapper

from ._schema import assert_has_keys, assert_schema_id


def test_minimal_flow_standalone(sample_project, stub_local_provider, monkeypatch, capsys):
    # 1. load mapper artifacts
    artifacts = mapper.artifact_status(sample_project)
    assert artifacts["project_map"]["present"] is True
    assert artifacts["precedent_index"]["present"] is True

    # 2. classify a small task
    classification = detect.detect("fix the greeting in src/app.py")
    assert classification.is_code_task is True

    # 3 & 4. build execution contract -> produce structured output
    # Match the stub provider's canned unified diff (-old/+new): `git apply`
    # runs for real in `_apply_and_test`, so the pre-image must match.
    (sample_project / "src" / "app.py").write_text("old\n", encoding="utf-8")
    monkeypatch.setenv(
        "SIMPLICIO_TEST_CMD", '"' + __import__("sys").executable + '" -c "raise SystemExit(0)"'
    )
    code = cli.main(
        [
            "task",
            "fix the greeting",
            "--root",
            str(sample_project),
            "--target",
            "src/app.py",
            "--json",
        ]
    )
    assert code == 0
    task_payload = json.loads(capsys.readouterr().out)
    assert_has_keys(task_payload, {"applied", "files_changed"}, where="task --json")
    assert task_payload["applied"] is True

    # 5. run a simple local verification, standalone Python path (no
    # SIMPLICIO_BIN / no `simplicio` on PATH -> subprocess fallback).
    monkeypatch.delenv("SIMPLICIO_BIN", raising=False)
    monkeypatch.setattr("simplicio.commands.test_run.discover_simplicio", lambda: None)
    import sys as _sys

    # `--cmd` is argv[0] directly, never through a shell (see
    # simplicio/commands/test_run.py's module docstring) — extra args ride
    # in `extra_args`, not folded into a quoted string.
    verify_ns = argparse.Namespace(
        cmd=_sys.executable,
        json=True,
        repo=str(sample_project),
        timeout=30.0,
    )
    from simplicio.commands.test_run import run as test_run_run

    rc = test_run_run(verify_ns, ["-c", "print(1)"])
    assert rc == 0
    verify_payload = json.loads(capsys.readouterr().out)
    assert_schema_id(verify_payload, "simplicio.test-run/v1", where="test run --json (standalone)")
    assert verify_payload["exit_code"] == 0


def test_minimal_flow_runtime_integrated_leg_is_stubbed(sample_project, stub_runtime_binary, capsys):
    """Same `test run` contract, but delegated to SIMPLICIO_BIN (stub Rust
    runtime — see conftest.py). Proves `simplicio/commands/test_run.py`'s
    runtime-delegation branch (`_run_via_runtime`) round-trips the
    `simplicio.test-run/v1` schema correctly; does NOT prove the real Rust
    binary behaves identically (that needs `simplicio-runtime` built and
    installed, which this sandbox does not have)."""
    from simplicio.commands.test_run import run as test_run_run

    ns = argparse.Namespace(cmd="pytest", json=True, repo=str(sample_project), timeout=30.0)
    rc = test_run_run(ns, [])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert_schema_id(payload, "simplicio.test-run/v1", where="test run --json (stubbed runtime)")
    assert payload["summary"] == "1 passed in 0.01s (stub runtime binary)"
