from __future__ import annotations

import json
import subprocess
from pathlib import Path

from simplicio.mechanical_edit import execute_plan
from simplicio.standalone_migration import load_effect_unknown_lock


def _plan() -> dict:
    return {
        "schema": "simplicio.mechanical-edit/v1",
        "touched_files": ["app.py"],
        "operations": [
            {
                "op": "replace_range",
                "path": "app.py",
                "start_line": 1,
                "end_line": 1,
                "text": "new\n",
            }
        ],
    }


def _native_payload(root: Path, *, status: str = "checks_failed") -> dict:
    return {
        "schema": "simplicio.edit-result/v1",
        "status": status,
        "file": str(root / "app.py"),
        "dry_run": False,
        "changed": True,
        "operations_applied": 1,
        "before_sha256": "before",
        "after_sha256": "after",
    }


def test_invalid_plan_is_rejected_before_native_admission(tmp_path, monkeypatch):
    from simplicio import mechanical_edit

    called = False

    def fail_if_called(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("native executor must not start for invalid input")

    monkeypatch.setattr(mechanical_edit.shutil, "which", lambda _: "/bin/simplicio")
    monkeypatch.setattr(mechanical_edit.subprocess, "run", fail_if_called)

    result = execute_plan({"schema": "wrong", "operations": []}, root=tmp_path, apply=True)

    assert result["status"] == "refused"
    assert called is False


def test_checks_failed_after_native_write_is_effect_unknown_without_fallback(tmp_path, monkeypatch):
    from simplicio import mechanical_edit

    (tmp_path / "app.py").write_text("old\n", encoding="utf-8")

    def fake_run(*args, **kwargs):
        (tmp_path / "app.py").write_text("new\n", encoding="utf-8")

        class Completed:
            stdout = json.dumps(_native_payload(tmp_path))

        return Completed()

    monkeypatch.setattr(mechanical_edit.shutil, "which", lambda _: "/bin/simplicio")
    monkeypatch.setattr(mechanical_edit.subprocess, "run", fake_run)

    result = execute_plan(_plan(), root=tmp_path, apply=True)

    assert result["status"] == "effect_unknown"
    assert result["effect_unknown"] is True
    assert (tmp_path / "app.py").read_text(encoding="utf-8") == "new\n"
    lock = load_effect_unknown_lock(str(tmp_path))
    assert lock is not None
    assert lock["outcome"] == "effect_unknown"


def test_timeout_locks_reexecution_until_reconciliation(tmp_path, monkeypatch):
    from simplicio import mechanical_edit

    (tmp_path / "app.py").write_text("old\n", encoding="utf-8")
    calls = 0

    def timeout(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise subprocess.TimeoutExpired(args[0], timeout=30)

    monkeypatch.setattr(mechanical_edit.shutil, "which", lambda _: "/bin/simplicio")
    monkeypatch.setattr(mechanical_edit.subprocess, "run", timeout)

    first = execute_plan(_plan(), root=tmp_path, apply=True)
    second = execute_plan(_plan(), root=tmp_path, apply=True)

    assert first["status"] == "effect_unknown"
    assert second["status"] == "refused"
    assert second["errors"][0]["code"] == "EFFECT_UNKNOWN_RECONCILIATION_REQUIRED"
    assert calls == 1
