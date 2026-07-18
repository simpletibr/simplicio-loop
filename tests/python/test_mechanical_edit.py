from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from simplicio.mechanical_edit import execute_plan, execute_plan_json


def _write(path, text: str | bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_text(text, encoding="utf-8", newline="\n")


def _sha(text: str | bytes) -> str:
    if isinstance(text, str):
        text = text.encode("utf-8")
    return hashlib.sha256(text).hexdigest()


def _plan(path: str, operation: dict, *, touched_files: list[str] | None = None) -> dict:
    return {
        "schema": "simplicio.mechanical-edit/v1",
        "touched_files": touched_files or [path],
        "operations": [operation],
    }


def test_dry_run_and_apply_replace_range_contract(tmp_path):
    target = tmp_path / "app.py"
    _write(target, "old\nkeep\n")
    operation = {
        "op": "replace_range",
        "path": "app.py",
        "start_line": 1,
        "end_line": 1,
        "text": "new\n",
        "file_sha256": _sha("old\nkeep\n"),
        "range_sha256": _sha("old\n"),
    }

    dry = execute_plan(_plan("app.py", operation), root=tmp_path, apply=False)

    assert dry["schema"] == "simplicio.mechanical-edit-result/v1"
    assert dry["status"] == "ok"
    assert dry["applied"] is False
    assert sum(1 for line in dry["planned_diff"].splitlines() if line.startswith("@@ ")) == 1
    assert "-old" in dry["planned_diff"]
    assert "+new" in dry["planned_diff"]
    assert target.read_text(encoding="utf-8") == "old\nkeep\n"

    applied = execute_plan(_plan("app.py", operation), root=tmp_path, apply=True)

    assert applied["status"] == "ok"
    assert applied["applied"] is True
    assert applied["files"][0]["after_sha256"] == _sha("new\nkeep\n")
    assert target.read_text(encoding="utf-8") == "new\nkeep\n"


def test_hash_contract_accepts_lf_hashes_for_crlf_text_files(tmp_path):
    target = tmp_path / "app.py"
    _write(target, b"old\r\nkeep\r\n")
    operation = {
        "op": "replace_range",
        "path": "app.py",
        "start_line": 1,
        "end_line": 1,
        "text": "new\n",
        "file_sha256": _sha("old\nkeep\n"),
        "range_sha256": _sha("old\n"),
    }

    result = execute_plan(_plan("app.py", operation), root=tmp_path, apply=True)

    assert result["status"] == "ok"
    assert result["applied"] is True
    assert result["files"][0]["before_sha256"] == _sha("old\nkeep\n")
    assert result["files"][0]["after_sha256"] == _sha("new\nkeep\n")
    assert target.read_bytes() == b"new\r\nkeep\r\n"


def test_strict_json_refuses_prose_wrapped_plan(tmp_path):
    result = execute_plan_json(
        'Here is the plan: {"schema":"simplicio.mechanical-edit/v1"}',
        root=tmp_path,
    )

    assert result["status"] == "refused"
    assert result["errors"][0]["code"] == "invalid_json"


def test_refuses_file_hash_mismatch(tmp_path):
    _write(tmp_path / "app.py", "current\n")
    operation = {
        "op": "replace_range",
        "path": "app.py",
        "start_line": 1,
        "end_line": 1,
        "text": "new\n",
        "file_sha256": _sha("stale\n"),
    }

    result = execute_plan(_plan("app.py", operation), root=tmp_path, apply=True)

    assert result["status"] == "refused"
    assert result["applied"] is False
    assert result["errors"][0]["code"] == "file_hash_mismatch"
    assert (tmp_path / "app.py").read_text(encoding="utf-8") == "current\n"


def test_refuses_edit_outside_declared_allowlist(tmp_path):
    _write(tmp_path / "allowed.py", "old\n")
    _write(tmp_path / "secret.py", "old\n")
    operation = {
        "op": "replace_range",
        "path": "secret.py",
        "start_line": 1,
        "end_line": 1,
        "text": "new\n",
    }

    result = execute_plan(
        _plan("secret.py", operation, touched_files=["allowed.py"]),
        root=tmp_path,
        apply=True,
    )

    assert result["status"] == "refused"
    assert result["errors"][0]["code"] == "path_not_allowed"
    assert (tmp_path / "secret.py").read_text(encoding="utf-8") == "old\n"


def test_refuses_overlapping_operations_without_order(tmp_path):
    _write(tmp_path / "app.py", "a\nb\nc\n")
    plan = {
        "schema": "simplicio.mechanical-edit/v1",
        "touched_files": ["app.py"],
        "operations": [
            {
                "op": "replace_range",
                "path": "app.py",
                "start_line": 1,
                "end_line": 2,
                "text": "x\n",
            },
            {
                "op": "delete_range",
                "path": "app.py",
                "start_line": 2,
                "end_line": 3,
            },
        ],
    }

    result = execute_plan(plan, root=tmp_path, apply=True)

    assert result["status"] == "refused"
    assert result["errors"][0]["code"] == "overlapping_operations"


def test_refuses_text_operation_on_binary_file(tmp_path):
    _write(tmp_path / "image.bin", b"\x00old")
    operation = {
        "op": "replace_range",
        "path": "image.bin",
        "start_line": 1,
        "end_line": 1,
        "text": "new\n",
    }

    result = execute_plan(_plan("image.bin", operation), root=tmp_path, apply=True)

    assert result["status"] == "refused"
    assert result["errors"][0]["code"] == "binary_file"
    assert (tmp_path / "image.bin").read_bytes() == b"\x00old"


def test_validation_failure_rolls_back_and_returns_compact_evidence(tmp_path):
    _write(tmp_path / "app.py", "old\n")
    plan = _plan(
        "app.py",
        {
            "op": "replace_range",
            "path": "app.py",
            "start_line": 1,
            "end_line": 1,
            "text": "new\n",
        },
    )
    plan["validation"] = [
        {
            "cmd": [
                sys.executable,
                "-c",
                "print('very long log ' * 200); raise SystemExit(7)",
            ]
        }
    ]

    result = execute_plan(plan, root=tmp_path, apply=True)

    assert result["status"] == "refused"
    assert result["applied"] is False
    assert result["errors"][0]["code"] == "validation_failed"
    assert result["validation"][0]["returncode"] == 7
    assert result["validation"][0]["log_summary"]["schema"] == "simplicio.log-summary/v1"
    assert len(result["validation"][0]["log_summary"]["summary"]) < 1000
    assert (tmp_path / "app.py").read_text(encoding="utf-8") == "old\n"


def test_validation_failure_restores_bytes_exactly(tmp_path):
    original = b"old\r\nkeep\r\n"
    (tmp_path / "app.py").write_bytes(original)
    plan = _plan(
        "app.py",
        {
            "op": "replace_range",
            "path": "app.py",
            "start_line": 1,
            "end_line": 1,
            "text": "new\n",
        },
    )
    plan["validation"] = [{"cmd": [sys.executable, "-c", "raise SystemExit(1)"]}]

    result = execute_plan(plan, root=tmp_path, apply=True)

    assert result["status"] == "refused"
    assert (tmp_path / "app.py").read_bytes() == original


def test_refuses_symlink_escape_outside_root(tmp_path, monkeypatch):
    # The symlink target must live genuinely outside the edit root for this
    # to exercise the escape guard; placing it under tmp_path (as a sibling
    # of the root) rather than inside it is what makes this an "escape".
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret\n", encoding="utf-8")
    try:
        (root / "link.txt").symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable on this machine: {exc}")
    plan = _plan(
        "link.txt",
        {
            "op": "replace_range",
            "path": "link.txt",
            "start_line": 1,
            "end_line": 1,
            "text": "new\n",
        },
    )
    monkeypatch.setenv("SIMPLICIO_DEV_CLI_NO_RUNTIME_EDIT", "1")

    result = execute_plan(plan, root=root, apply=True)

    assert result["status"] == "refused"
    assert result["errors"][0]["code"] == "unsafe_path"
    assert outside.read_text(encoding="utf-8") == "secret\n"


def test_accepts_normal_path_with_runtime_edit_disabled(tmp_path, monkeypatch):
    _write(tmp_path / "app.py", "old\n")
    monkeypatch.setenv("SIMPLICIO_DEV_CLI_NO_RUNTIME_EDIT", "1")

    result = execute_plan(
        _plan(
            "app.py",
            {
                "op": "replace_range",
                "path": "app.py",
                "start_line": 1,
                "end_line": 1,
                "text": "new\n",
            },
        ),
        root=tmp_path,
        apply=True,
    )

    assert result["status"] == "ok"
    assert (tmp_path / "app.py").read_text(encoding="utf-8") == "new\n"


def test_noop_result_is_machine_readable_and_compact(tmp_path):
    _write(tmp_path / "app.py", "same\n")
    operation = {
        "op": "replace_range",
        "path": "app.py",
        "start_line": 1,
        "end_line": 1,
        "text": "same\n",
    }

    result = execute_plan(_plan("app.py", operation), root=tmp_path, apply=True)

    assert result["status"] == "ok"
    assert result["noop"] is True
    assert result["applied"] is False
    assert result["planned_diff"] == ""


def test_cli_json_contract_for_dry_run(tmp_path, monkeypatch, capsys):
    from simplicio import cli

    _write(tmp_path / "app.py", "old\n")
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps(
            _plan(
                "app.py",
                {
                    "op": "replace_range",
                    "path": "app.py",
                    "start_line": 1,
                    "end_line": 1,
                    "text": "new\n",
                },
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")

    code = cli.main(
        [
            "mechanical-edit",
            "--root",
            str(tmp_path),
            "--plan",
            str(plan_path),
            "--dry-run",
            "--json",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "simplicio.mechanical-edit-result/v1"
    assert payload["applied"] is False
    assert "+new" in payload["planned_diff"]


def test_cli_edit_alias_uses_local_fallback_when_runtime_disabled(tmp_path, monkeypatch, capsys):
    from simplicio import cli

    _write(tmp_path / "app.py", "old\n")
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps(
            _plan(
                "app.py",
                {
                    "op": "replace_range",
                    "path": "app.py",
                    "start_line": 1,
                    "end_line": 1,
                    "text": "new\n",
                },
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")
    monkeypatch.setenv("SIMPLICIO_DEV_CLI_NO_RUNTIME_EDIT", "1")

    code = cli.main(
        [
            "edit",
            "--root",
            str(tmp_path),
            "--plan",
            str(plan_path),
            "--dry-run",
            "--json",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "simplicio.mechanical-edit-result/v1"
    assert payload["applied"] is False
    assert "+new" in payload["planned_diff"]


def test_cli_edit_alias_delegates_to_runtime_when_available(tmp_path, monkeypatch):
    from simplicio import cli
    from simplicio.commands import edit as edit_cmd

    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps(
            _plan(
                "app.py",
                {
                    "op": "replace_range",
                    "path": "app.py",
                    "start_line": 1,
                    "end_line": 1,
                    "text": "new\n",
                },
            )
        ),
        encoding="utf-8",
    )
    calls = []

    class Completed:
        returncode = 17

    def fake_run(cmd, input=None, text=False):
        calls.append({"cmd": cmd, "input": input, "text": text})
        return Completed()

    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")
    monkeypatch.delenv("SIMPLICIO_DEV_CLI_NO_RUNTIME_EDIT", raising=False)
    monkeypatch.setattr(
        edit_cmd.shutil, "which", lambda name: "/bin/simplicio" if name == "simplicio" else None
    )
    monkeypatch.setattr(edit_cmd.subprocess, "run", fake_run)

    code = cli.main(
        [
            "edit",
            "--root",
            str(tmp_path),
            "--plan",
            str(plan_path),
            "--dry-run",
            "--json",
        ]
    )

    assert code == 17
    assert calls == [
        {
            "cmd": [
                "/bin/simplicio",
                "edit",
                "--plan",
                str(plan_path),
                "--repo",
                str(tmp_path),
                "--json",
                "--dry-run",
            ],
            "input": None,
            "text": True,
        }
    ]


# ---------------------------------------------------------------------------
# Native-first delegation inside execute_plan (mechanical_edit.py's own
# native-binary attempt, distinct from the commands/edit.py alias tested
# above). See simplicio/mechanical_edit.py's _try_native_edit/
# _translate_native_result/_native_edit_binary.
# ---------------------------------------------------------------------------


def test_execute_plan_uses_python_fallback_when_native_binary_absent(tmp_path, monkeypatch):
    from simplicio import mechanical_edit

    monkeypatch.setattr(mechanical_edit.shutil, "which", lambda name: None)
    _write(tmp_path / "app.py", "old\nkeep\n")
    operation = {
        "op": "replace_range",
        "path": "app.py",
        "start_line": 1,
        "end_line": 1,
        "text": "new\n",
    }

    result = execute_plan(_plan("app.py", operation), root=tmp_path, apply=True)

    assert result["schema"] == "simplicio.mechanical-edit-result/v1"
    assert result["status"] == "ok"
    assert result["applied"] is True
    assert (tmp_path / "app.py").read_text(encoding="utf-8") == "new\nkeep\n"


def test_execute_plan_disabled_by_kill_switch_env_var(tmp_path, monkeypatch):
    from simplicio import mechanical_edit

    monkeypatch.setenv("SIMPLICIO_DEV_CLI_NO_RUNTIME_EDIT", "1")
    monkeypatch.setattr(mechanical_edit.shutil, "which", lambda name: "/bin/simplicio")

    def fail_if_called(cmd, **kwargs):
        raise AssertionError("subprocess.run must not run when the kill-switch is set")

    monkeypatch.setattr(mechanical_edit.subprocess, "run", fail_if_called)
    _write(tmp_path / "app.py", "old\n")
    operation = {"op": "replace_range", "path": "app.py", "start_line": 1, "end_line": 1, "text": "new\n"}

    result = execute_plan(_plan("app.py", operation), root=tmp_path, apply=True)

    assert result["status"] == "ok"
    assert result["applied"] is True
    assert (tmp_path / "app.py").read_text(encoding="utf-8") == "new\n"


def _native_edit_payload(root, **overrides):
    """A well-formed fake of the native `simplicio edit --json` payload —
    the REAL shape (`simplicio.edit-result/v1`), confirmed by running the
    live binary, not this module's own `simplicio.mechanical-edit-result/v1`.
    """
    payload = {
        "schema": "simplicio.edit-result/v1",
        "status": "ok",
        "file": str(Path(root) / "app.py"),
        "created": False,
        "dry_run": False,
        "changed": True,
        "mechanical_only": True,
        "operations_applied": 1,
        "operations": [{"op": "replace_range", "detail": "line 1", "changes": 1}],
        "before_sha256": "fake-before-sha",
        "after_sha256": "fake-after-sha",
        "commit_hash": None,
        "commit_message": None,
        "bytes_before": 8,
        "bytes_after": 8,
        "post_edit_phases": [],
        "post_edit_skipped_reason": None,
        "reflection": {},
        "token_ledger": {"schema": "simplicio.communication-token-ledger/v1"},
    }
    payload.update(overrides)
    return payload


def test_execute_plan_delegates_and_translates_native_result_when_binary_present(tmp_path, monkeypatch):
    from simplicio import mechanical_edit

    _write(tmp_path / "app.py", "old\nkeep\n")
    operation = {
        "op": "replace_range",
        "path": "app.py",
        "start_line": 1,
        "end_line": 1,
        "text": "new\n",
    }
    plan = _plan("app.py", operation)
    fake_payload = _native_edit_payload(tmp_path, dry_run=True)
    calls = []

    class FakeCompleted:
        returncode = 0
        stdout = json.dumps(fake_payload)

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        plan_path = Path(cmd[cmd.index("--plan") + 1])
        assert json.loads(plan_path.read_text(encoding="utf-8")) == plan
        return FakeCompleted()

    monkeypatch.setattr(
        mechanical_edit.shutil, "which", lambda name: "/bin/simplicio" if name == "simplicio" else None
    )
    monkeypatch.setattr(mechanical_edit.subprocess, "run", fake_run)

    result = execute_plan(plan, root=tmp_path, apply=False)

    assert len(calls) == 1
    cmd = calls[0]
    assert cmd[0] == "/bin/simplicio"
    assert cmd[1] == "edit"
    assert "--repo" in cmd
    assert cmd[cmd.index("--repo") + 1] == str(tmp_path)
    assert "--json" in cmd
    assert "--dry-run" in cmd

    # the temp plan file is cleaned up after the call
    plan_path = Path(cmd[cmd.index("--plan") + 1])
    assert not plan_path.exists()

    # translated into THIS module's own shape, not a pass-through of the
    # native payload (which uses a different schema/field set entirely)
    assert result["schema"] == "simplicio.mechanical-edit-result/v1"
    assert result["root"] == str(tmp_path)  # ours, never the native payload's
    assert result["status"] == "ok"
    assert result["applied"] is False  # dry_run=True in the fake payload
    assert result["noop"] is False  # changed=True in the fake payload
    assert result["planned_diff"] == ""  # native --json doesn't expose one
    assert result["files"] == [
        {"path": "app.py", "before_sha256": "fake-before-sha", "after_sha256": "fake-after-sha"}
    ]
    assert result["operation_count"] == 1
    assert result["errors"] == []
    assert result["validation"] == []

    # the Python fallback path never ran
    assert (tmp_path / "app.py").read_text(encoding="utf-8") == "old\nkeep\n"


def test_execute_plan_apply_true_omits_dry_run_flag_on_native_call(tmp_path, monkeypatch):
    from simplicio import mechanical_edit

    _write(tmp_path / "app.py", "old\n")
    operation = {"op": "replace_range", "path": "app.py", "start_line": 1, "end_line": 1, "text": "new\n"}
    plan = _plan("app.py", operation)
    calls = []

    class FakeCompleted:
        returncode = 0
        stdout = json.dumps(_native_edit_payload(tmp_path, dry_run=False))

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return FakeCompleted()

    monkeypatch.setattr(mechanical_edit.shutil, "which", lambda name: "/bin/simplicio")
    monkeypatch.setattr(mechanical_edit.subprocess, "run", fake_run)

    result = execute_plan(plan, root=tmp_path, apply=True)

    assert "--dry-run" not in calls[0]
    assert result["applied"] is True  # dry_run=False in the fake payload


def test_execute_plan_falls_back_when_native_status_is_checks_failed(tmp_path, monkeypatch):
    """Real semantic gap, not just caution: on a failed post-edit phase the
    native binary does NOT roll back the write, while this module's own
    Python path restores the pre-edit file on the same failure. Translating
    "checks_failed" as a normal result would misrepresent that the file is
    unchanged when it is not — must fall through to Python instead, which
    genuinely rolls back."""
    from simplicio import mechanical_edit

    _write(tmp_path / "app.py", "old\n")
    operation = {"op": "replace_range", "path": "app.py", "start_line": 1, "end_line": 1, "text": "new\n"}

    class FakeCompleted:
        returncode = 0
        stdout = json.dumps(
            _native_edit_payload(tmp_path, status="checks_failed", post_edit_skipped_reason=None)
        )

    monkeypatch.setattr(mechanical_edit.shutil, "which", lambda name: "/bin/simplicio")
    monkeypatch.setattr(mechanical_edit.subprocess, "run", lambda cmd, **kwargs: FakeCompleted())

    result = execute_plan(_plan("app.py", operation), root=tmp_path, apply=True)

    # fell through to the real Python path, which ran the edit itself
    assert result["status"] == "ok"
    assert result["applied"] is True
    assert (tmp_path / "app.py").read_text(encoding="utf-8") == "new\n"


def test_execute_plan_falls_back_on_subprocess_oserror(tmp_path, monkeypatch):
    from simplicio import mechanical_edit

    _write(tmp_path / "app.py", "old\n")
    operation = {"op": "replace_range", "path": "app.py", "start_line": 1, "end_line": 1, "text": "new\n"}

    def fake_run(cmd, **kwargs):
        raise OSError("simplicio binary vanished mid-call")

    monkeypatch.setattr(mechanical_edit.shutil, "which", lambda name: "/bin/simplicio")
    monkeypatch.setattr(mechanical_edit.subprocess, "run", fake_run)

    result = execute_plan(_plan("app.py", operation), root=tmp_path, apply=True)

    assert result["status"] == "ok"
    assert result["applied"] is True
    assert (tmp_path / "app.py").read_text(encoding="utf-8") == "new\n"


def test_execute_plan_falls_back_on_subprocess_timeout(tmp_path, monkeypatch):
    from simplicio import mechanical_edit

    _write(tmp_path / "app.py", "old\n")
    operation = {"op": "replace_range", "path": "app.py", "start_line": 1, "end_line": 1, "text": "new\n"}

    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=30)

    monkeypatch.setattr(mechanical_edit.shutil, "which", lambda name: "/bin/simplicio")
    monkeypatch.setattr(mechanical_edit.subprocess, "run", fake_run)

    result = execute_plan(_plan("app.py", operation), root=tmp_path, apply=True)

    assert result["status"] == "ok"
    assert result["applied"] is True
    assert (tmp_path / "app.py").read_text(encoding="utf-8") == "new\n"


def test_execute_plan_falls_back_on_unparseable_json(tmp_path, monkeypatch):
    from simplicio import mechanical_edit

    _write(tmp_path / "app.py", "old\n")
    operation = {"op": "replace_range", "path": "app.py", "start_line": 1, "end_line": 1, "text": "new\n"}

    class FakeCompleted:
        returncode = 1
        stdout = "not json at all"

    monkeypatch.setattr(mechanical_edit.shutil, "which", lambda name: "/bin/simplicio")
    monkeypatch.setattr(mechanical_edit.subprocess, "run", lambda cmd, **kwargs: FakeCompleted())

    result = execute_plan(_plan("app.py", operation), root=tmp_path, apply=True)

    assert result["status"] == "ok"
    assert result["applied"] is True
    assert (tmp_path / "app.py").read_text(encoding="utf-8") == "new\n"


def test_execute_plan_falls_back_when_native_schema_is_unknown(tmp_path, monkeypatch):
    """An unrecognized schema (typo, future breaking change, wrong tool
    entirely) must fall through to Python rather than being trusted
    partially. The REAL native schema (`simplicio.edit-result/v1`) is
    covered by the translation tests above — this covers anything else."""
    from simplicio import mechanical_edit

    _write(tmp_path / "app.py", "old\n")
    operation = {"op": "replace_range", "path": "app.py", "start_line": 1, "end_line": 1, "text": "new\n"}

    class FakeCompleted:
        returncode = 0
        stdout = json.dumps(
            {"schema": "simplicio.some-other-tool-result/v1", "status": "ok", "file": "app.py"}
        )

    monkeypatch.setattr(mechanical_edit.shutil, "which", lambda name: "/bin/simplicio")
    monkeypatch.setattr(mechanical_edit.subprocess, "run", lambda cmd, **kwargs: FakeCompleted())

    result = execute_plan(_plan("app.py", operation), root=tmp_path, apply=True)

    assert result["schema"] == "simplicio.mechanical-edit-result/v1"
    assert result["status"] == "ok"
    assert result["applied"] is True
    assert (tmp_path / "app.py").read_text(encoding="utf-8") == "new\n"


def test_execute_plan_falls_back_when_native_payload_has_wrong_types(tmp_path, monkeypatch):
    """The real native schema tag, but a field of the wrong type (e.g. a
    future minor field-shape drift) — must fall through rather than crash
    or trust a partially-shaped payload."""
    from simplicio import mechanical_edit

    _write(tmp_path / "app.py", "old\n")
    operation = {"op": "replace_range", "path": "app.py", "start_line": 1, "end_line": 1, "text": "new\n"}

    class FakeCompleted:
        returncode = 0
        stdout = json.dumps(_native_edit_payload(tmp_path, operations_applied="not-an-int"))

    monkeypatch.setattr(mechanical_edit.shutil, "which", lambda name: "/bin/simplicio")
    monkeypatch.setattr(mechanical_edit.subprocess, "run", lambda cmd, **kwargs: FakeCompleted())

    result = execute_plan(_plan("app.py", operation), root=tmp_path, apply=True)

    assert result["status"] == "ok"
    assert result["applied"] is True
    assert (tmp_path / "app.py").read_text(encoding="utf-8") == "new\n"


def test_execute_plan_real_native_binary_activates_when_installed(tmp_path):
    """End-to-end against the REAL installed `simplicio` binary, not a mock
    — proves the translation genuinely activates today, not just against a
    hand-written fake payload. Skips cleanly if the binary isn't on PATH
    (e.g. CI), matching how this repo's other real-binary tests behave."""
    import shutil as _shutil

    if _shutil.which("simplicio") is None:
        pytest.skip("simplicio binary not on PATH")

    _write(tmp_path / "app.py", "old\nkeep\n")
    operation = {
        "op": "replace_range",
        "path": "app.py",
        "start_line": 1,
        "end_line": 1,
        "text": "new\n",
    }

    result = execute_plan(_plan("app.py", operation), root=tmp_path, apply=True)

    assert result["schema"] == "simplicio.mechanical-edit-result/v1"
    assert result["status"] == "ok"
    assert result["applied"] is True
    assert result["noop"] is False
    assert len(result["files"]) == 1
    assert result["files"][0]["path"] == "app.py"
    assert result["files"][0]["before_sha256"] != result["files"][0]["after_sha256"]
    assert (tmp_path / "app.py").read_text(encoding="utf-8") == "new\nkeep\n"


def test_translate_create_file_plan_for_native_translates_every_op(tmp_path):
    from simplicio.commands.edit import _translate_create_file_plan_for_native

    plan = {
        "schema": "simplicio.mechanical-edit/v1",
        "operations": [
            {"op": "create_file", "path": "a.py", "text": "print(1)\n"},
            {"op": "create_file", "path": "b.py", "text": "print(2)\n"},
        ],
    }

    native_plans = _translate_create_file_plan_for_native(plan)

    assert native_plans == [
        {"file": "a.py", "operations": [{"op": "append", "text": "print(1)\n"}]},
        {"file": "b.py", "operations": [{"op": "append", "text": "print(2)\n"}]},
    ]


def test_translate_create_file_plan_for_native_refuses_mixed_operations(tmp_path):
    """A single non-create_file op anywhere in the plan must refuse
    translation entirely -- this repo's op vocabulary (replace_range,
    json_patch, ast_patch, move_file, delete_file) has no safe mapping to
    the native binary's vocabulary (replace_all/insert_before/insert_after/
    replace_line/delete_line/append/prepend), so guessing would risk a
    silent mistranslation rather than a clean fallback."""
    from simplicio.commands.edit import _translate_create_file_plan_for_native

    plan = {
        "operations": [
            {"op": "create_file", "path": "a.py", "text": "print(1)\n"},
            {"op": "replace_range", "path": "b.py", "start_line": 1, "end_line": 1, "text": "x\n"},
        ]
    }

    assert _translate_create_file_plan_for_native(plan) is None


def test_translate_create_file_plan_for_native_refuses_empty_or_missing_operations(tmp_path):
    from simplicio.commands.edit import _translate_create_file_plan_for_native

    assert _translate_create_file_plan_for_native({}) is None
    assert _translate_create_file_plan_for_native({"operations": []}) is None
    assert _translate_create_file_plan_for_native({"operations": "not-a-list"}) is None


def test_cli_edit_alias_translates_multi_file_create_plan_to_native_calls(tmp_path, monkeypatch):
    """The exact regression this closes: a multi-file create_file plan (the
    shape `simplicio-py prototype scaffold`-style callers naturally produce)
    used to fail outright against the native binary ('edit plan must
    specify a target "file"'). Proves it now issues one native subprocess
    call per file instead."""
    from simplicio import cli
    from simplicio.commands import edit as edit_cmd

    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "schema": "simplicio.mechanical-edit/v1",
                "operations": [
                    {"op": "create_file", "path": "a.py", "text": "print(1)\n"},
                    {"op": "create_file", "path": "b.py", "text": "print(2)\n"},
                ],
            }
        ),
        encoding="utf-8",
    )
    calls = []

    class Completed:
        returncode = 0
        stderr = ""

        def __init__(self, path):
            self.stdout = json.dumps(
                {
                    "schema": "simplicio.edit-result/v1",
                    "status": "ok",
                    "file": path,
                    "before_sha256": "before",
                    "after_sha256": "after",
                }
            )

    def fake_run(cmd, input=None, text=False, capture_output=False):
        calls.append({"cmd": cmd, "input": input})
        native_plan = json.loads(input)
        return Completed(native_plan["file"])

    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")
    monkeypatch.delenv("SIMPLICIO_DEV_CLI_NO_RUNTIME_EDIT", raising=False)
    monkeypatch.setattr(
        edit_cmd.shutil, "which", lambda name: "/bin/simplicio" if name == "simplicio" else None
    )
    monkeypatch.setattr(edit_cmd.subprocess, "run", fake_run)

    code = cli.main(
        ["edit", "--root", str(tmp_path), "--plan", str(plan_path), "--apply", "--json"]
    )

    assert code == 0
    assert len(calls) == 2, "one native subprocess call per file, not one call for the whole plan"
    called_files = {json.loads(c["input"])["file"] for c in calls}
    assert called_files == {"a.py", "b.py"}
    for call in calls:
        native_plan = json.loads(call["input"])
        assert native_plan["operations"] == [
            {"op": "append", "text": {"a.py": "print(1)\n", "b.py": "print(2)\n"}[native_plan["file"]]}
        ]


def test_cli_edit_alias_falls_back_when_plan_has_non_create_file_ops(tmp_path, monkeypatch):
    """A plan mixing create_file with any other op type must NOT be
    translated -- it should hit the untranslated pass-through path (single
    `simplicio edit --plan <path>` call), not be silently dropped or
    mistranslated."""
    from simplicio import cli
    from simplicio.commands import edit as edit_cmd

    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps(
            _plan(
                "app.py",
                {
                    "op": "replace_range",
                    "path": "app.py",
                    "start_line": 1,
                    "end_line": 1,
                    "text": "new\n",
                },
            )
        ),
        encoding="utf-8",
    )
    calls = []

    class Completed:
        returncode = 0

    def fake_run(cmd, input=None, text=False):
        calls.append(cmd)
        return Completed()

    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")
    monkeypatch.delenv("SIMPLICIO_DEV_CLI_NO_RUNTIME_EDIT", raising=False)
    monkeypatch.setattr(
        edit_cmd.shutil, "which", lambda name: "/bin/simplicio" if name == "simplicio" else None
    )
    monkeypatch.setattr(edit_cmd.subprocess, "run", fake_run)

    code = cli.main(["edit", "--root", str(tmp_path), "--plan", str(plan_path), "--apply", "--json"])

    assert code == 0
    assert len(calls) == 1, "untranslatable plans pass straight through as one call, unchanged"
    assert "--plan" in calls[0] and str(plan_path) in calls[0]


def test_cli_edit_alias_real_native_binary_translates_create_file_plan(tmp_path):
    """End-to-end against the REAL installed `simplicio` binary -- proves
    the translation genuinely works today against the real binary's own
    operation vocabulary, not just a hand-written fake payload. Skips
    cleanly if the binary isn't on PATH (e.g. CI)."""
    import shutil as _shutil

    from simplicio import cli

    if _shutil.which("simplicio") is None:
        pytest.skip("simplicio binary not on PATH")

    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "schema": "simplicio.mechanical-edit/v1",
                "operations": [
                    {"op": "create_file", "path": "snake.py", "text": "print('snake')\n"},
                    {"op": "create_file", "path": "test_snake.py", "text": "def test_x():\n    pass\n"},
                ],
            }
        ),
        encoding="utf-8",
    )

    code = cli.main(
        ["edit", "--root", str(tmp_path), "--plan", str(plan_path), "--apply", "--json"]
    )

    assert code == 0
    assert (tmp_path / "snake.py").read_text(encoding="utf-8") == "print('snake')\n"
    assert (tmp_path / "test_snake.py").read_text(encoding="utf-8") == "def test_x():\n    pass\n"
