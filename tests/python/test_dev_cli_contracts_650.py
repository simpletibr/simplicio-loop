from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace

import pytest

from simplicio import mechanical_edit
from simplicio.commands import edit as edit_command
from simplicio.dev_cli_contracts import apply, compile_plan, dry_run, reconcile


def _replace_plan(path: str = "file with spaces.txt") -> dict:
    return {
        "schema": "simplicio.mechanical-edit/v1",
        "touched_files": [path],
        "operations": [
            {
                "op": "replace_range",
                "path": path,
                "start_line": 1,
                "end_line": 1,
                "text": "new\n",
            }
        ],
    }


def test_plan_digest_ignores_mapping_and_touched_file_order(tmp_path: Path):
    for name in ("a.txt", "b.txt"):
        (tmp_path / name).write_text("old\n", encoding="utf-8")
    first = {
        "schema": "simplicio.mechanical-edit/v1",
        "touched_files": ["b.txt", "a.txt", "b.txt"],
        "operations": [
            {"op": "replace_range", "path": "b.txt", "start_line": 1, "end_line": 1, "text": "new\n"},
            {"op": "replace_range", "path": "a.txt", "start_line": 1, "end_line": 1, "text": "new\n"},
        ],
    }
    second = {
        "operations": [
            {"text": "new\n", "end_line": 1, "start_line": 1, "path": "a.txt", "op": "replace_range"},
            {"text": "new\n", "end_line": 1, "start_line": 1, "path": "b.txt", "op": "replace_range"},
        ],
        "touched_files": ["a.txt", "b.txt"],
        "schema": "simplicio.mechanical-edit/v1",
    }

    left = compile_plan(first, root=tmp_path, idempotency_key="left")
    right = compile_plan(second, root=tmp_path, idempotency_key="right")

    assert left["status"] == right["status"] == "planned"
    assert left["plan_digest"] == right["plan_digest"]
    assert left["plan"] == right["plan"]


@pytest.mark.parametrize("malicious", ["../outside.txt", "..\\outside.txt"])
def test_compile_plan_blocks_traversal_without_reading_outside_root(tmp_path: Path, malicious: str):
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret\n", encoding="utf-8")
    plan = _replace_plan(malicious)

    envelope = compile_plan(
        plan, root=tmp_path, idempotency_key=hashlib.sha256(malicious.encode()).hexdigest()
    )

    assert envelope["status"] == "blocked"
    assert envelope["diagnostics"]["errors"][0]["code"] == "unsafe_path"
    assert outside.read_text(encoding="utf-8") == "secret\n"


def test_compile_plan_blocks_operation_outside_declared_plan(tmp_path: Path):
    (tmp_path / "allowed.txt").write_text("old\n", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("secret\n", encoding="utf-8")
    plan = _replace_plan("secret.txt")
    plan["touched_files"] = ["allowed.txt"]

    envelope = compile_plan(plan, root=tmp_path, idempotency_key="outside-plan")

    assert envelope["status"] == "blocked"
    assert envelope["diagnostics"]["errors"][0]["code"] == "path_not_allowed"


def test_compile_plan_blocks_symlink_escape(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret\n", encoding="utf-8")
    try:
        (root / "link.txt").symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    envelope = compile_plan(_replace_plan("link.txt"), root=root, idempotency_key="symlink")

    assert envelope["status"] == "blocked"
    assert envelope["diagnostics"]["errors"][0]["code"] == "unsafe_path"
    assert outside.read_text(encoding="utf-8") == "secret\n"


def test_validation_subprocess_uses_bounded_argv_and_explicit_cwd(tmp_path: Path, monkeypatch):
    target = tmp_path / "file with spaces.txt"
    target.write_text("old\n", encoding="utf-8")
    injected = "value; echo not-a-shell"
    plan = _replace_plan()
    plan["validation"] = [
        {
            "cmd": [sys.executable, "-c", "raise SystemExit(0)", injected],
            "timeout": 5,
        }
    ]
    calls: list[tuple[list[str], dict]] = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(mechanical_edit.subprocess, "run", fake_run)
    envelope = compile_plan(plan, root=tmp_path, idempotency_key="subprocess")
    receipt = apply(envelope, root=tmp_path)

    assert receipt["status"] == "committed"
    assert len(calls) == 1
    argv, kwargs = calls[0]
    assert argv == [sys.executable, "-c", "raise SystemExit(0)", injected]
    assert kwargs["cwd"] == tmp_path.resolve()
    assert kwargs["timeout"] == 5
    assert kwargs["shell"] is False
    assert kwargs["stdin"] is subprocess.DEVNULL


def test_native_edit_subprocess_uses_bounded_argv_and_explicit_cwd(tmp_path: Path, monkeypatch):
    target = tmp_path / "file with spaces.txt"
    target.write_text("old\n", encoding="utf-8")
    calls: list[tuple[list[str], dict]] = []
    payload = {
        "schema": "simplicio.edit-result/v1",
        "status": "ok",
        "file": str(target),
        "dry_run": True,
        "changed": True,
        "operations_applied": 1,
        "before_sha256": "before",
        "after_sha256": "after",
    }

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.delenv("SIMPLICIO_DEV_CLI_NO_RUNTIME_EDIT", raising=False)
    monkeypatch.setattr(mechanical_edit.shutil, "which", lambda _name: "simplicio")
    monkeypatch.setattr(mechanical_edit.subprocess, "run", fake_run)

    result = mechanical_edit.execute_plan(_replace_plan(), root=tmp_path, apply=False)

    assert result["status"] == "ok"
    argv, kwargs = calls[0]
    assert isinstance(argv, list)
    assert kwargs["cwd"] == tmp_path.resolve()
    assert kwargs["timeout"] == 30.0
    assert kwargs["shell"] is False


def test_edit_command_confines_native_paths_before_subprocess(tmp_path: Path, monkeypatch):
    calls: list[tuple[list[str], dict]] = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        payload = {"status": "ok", "before_sha256": None, "after_sha256": "after"}
        return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(edit_command.subprocess, "run", fake_run)
    args = SimpleNamespace(root=str(tmp_path), apply=False)
    native_plan = [{"file": "file with spaces.txt", "operations": [{"op": "append", "text": "new\n"}]}]

    result = edit_command._run_native_edit_plans("simplicio", native_plan, args)
    blocked = edit_command._run_native_edit_plans(
        "simplicio",
        [{"file": "..\\outside.txt", "operations": [{"op": "append", "text": "bad\n"}]}],
        args,
    )

    assert result["status"] == "ok"
    _argv, kwargs = calls[0]
    assert kwargs["cwd"] == tmp_path.resolve()
    assert kwargs["timeout"] == 30.0
    assert kwargs["shell"] is False
    assert blocked["status"] == "refused"
    assert blocked["errors"][0]["code"] == "unsafe_path"
    assert len(calls) == 1


@pytest.mark.parametrize("timeout", [0, -1, 301, "5", True])
def test_validation_timeout_must_be_a_bounded_integer(tmp_path: Path, timeout):
    target = tmp_path / "file with spaces.txt"
    target.write_text("old\n", encoding="utf-8")
    plan = _replace_plan()
    plan["validation"] = [{"cmd": [sys.executable, "-c", "raise SystemExit(0)"], "timeout": timeout}]

    envelope = compile_plan(plan, root=tmp_path, idempotency_key=f"timeout-{timeout!r}")

    assert envelope["status"] == "blocked"
    assert envelope["diagnostics"]["errors"][0]["code"] == "invalid_validation"
    assert target.read_text(encoding="utf-8") == "old\n"


def test_tampered_effect_digest_is_rejected_identically(tmp_path: Path):
    target = tmp_path / "file with spaces.txt"
    target.write_text("old\n", encoding="utf-8")
    envelope = compile_plan(_replace_plan(), root=tmp_path, idempotency_key="tampered-effect")
    envelope["effect_digest"] = "0" * 64

    preview = dry_run(envelope, root=tmp_path)
    receipt = apply(envelope, root=tmp_path)

    assert preview["status"] == receipt["status"] == "blocked"
    assert preview["reason"] == receipt["reason"] == "effect_digest_mismatch"
    assert target.read_text(encoding="utf-8") == "old\n"


def test_dry_run_and_apply_share_diagnostics_and_emit_verifiable_receipt(tmp_path: Path):
    target = tmp_path / "file with spaces.txt"
    target.write_text("old\n", encoding="utf-8")
    envelope = compile_plan(_replace_plan(), root=tmp_path, idempotency_key="diagnostic-parity")

    preview = dry_run(envelope, root=tmp_path)
    receipt = apply(envelope, root=tmp_path)
    reconciled = reconcile(root=tmp_path, idempotency_key="diagnostic-parity")

    assert preview["status"] == "dry_run"
    assert receipt["status"] == "committed"
    assert preview["diagnostics"] == receipt["diagnostics"]
    assert receipt["applied"] is True
    assert len(receipt["receipt_digest"]) == 64
    expected = copy.deepcopy(receipt)
    digest = expected.pop("receipt_digest")
    expected.pop("replayed")
    assert (
        digest
        == hashlib.sha256(
            json.dumps(expected, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
    )
    assert reconciled["receipt_digest_valid"] is True
    assert target.read_text(encoding="utf-8") == "new\n"


def test_concurrent_apply_commits_once_and_replays_same_receipt(tmp_path: Path):
    target = tmp_path / "file with spaces.txt"
    target.write_text("old\n", encoding="utf-8")
    envelope = compile_plan(_replace_plan(), root=tmp_path, idempotency_key="concurrent")
    barrier = Barrier(2)

    def invoke() -> dict:
        barrier.wait()
        return apply(envelope, root=tmp_path)

    with ThreadPoolExecutor(max_workers=2) as pool:
        receipts = list(pool.map(lambda _index: invoke(), range(2)))

    assert [row["status"] for row in receipts] == ["committed", "committed"]
    assert sorted(row["replayed"] for row in receipts) == [False, True]
    assert len({row["receipt_digest"] for row in receipts}) == 1
    assert target.read_text(encoding="utf-8") == "new\n"
