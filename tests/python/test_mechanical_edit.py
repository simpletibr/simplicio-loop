from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

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

    # Sentinel values a real Python execution of this plan could never
    # produce, so a match proves the native JSON was trusted verbatim (after
    # shape validation) rather than the Python path having run anyway.
    fake_payload = {
        "schema": "simplicio.mechanical-edit-result/v1",
        "root": "/native/reported/root/must/be/ignored",
        "status": "ok",
        "applied": True,
        "noop": False,
        "planned_diff": "FAKE_NATIVE_DIFF",
        "files": [{"path": "app.py", "before_sha256": "fake-before", "after_sha256": "fake-after"}],
        "operation_count": 42,
        "errors": [],
        "validation": [],
    }
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

    assert result["schema"] == "simplicio.mechanical-edit-result/v1"
    assert result["root"] == str(tmp_path)  # ours, never the native payload's
    assert result["status"] == "ok"
    assert result["applied"] is True
    assert result["noop"] is False
    assert result["planned_diff"] == "FAKE_NATIVE_DIFF"
    assert result["files"] == fake_payload["files"]
    assert result["operation_count"] == 42
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
        stdout = json.dumps(
            {
                "schema": "simplicio.mechanical-edit-result/v1",
                "status": "ok",
                "applied": True,
                "noop": False,
                "planned_diff": "",
                "files": [],
                "operation_count": 1,
                "errors": [],
                "validation": [],
            }
        )

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return FakeCompleted()

    monkeypatch.setattr(mechanical_edit.shutil, "which", lambda name: "/bin/simplicio")
    monkeypatch.setattr(mechanical_edit.subprocess, "run", fake_run)

    execute_plan(plan, root=tmp_path, apply=True)

    assert "--dry-run" not in calls[0]


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


def test_execute_plan_falls_back_when_native_schema_does_not_match(tmp_path, monkeypatch):
    """Regression guard for the real-world mismatch: the installed simplicio
    binary's ``edit`` command currently answers with
    ``schema: simplicio.edit-result/v1`` (a different plan/result contract),
    not this module's ``simplicio.mechanical-edit-result/v1``. Any
    schema/shape mismatch must fall through to the Python implementation
    rather than being trusted partially.
    """
    from simplicio import mechanical_edit

    _write(tmp_path / "app.py", "old\n")
    operation = {"op": "replace_range", "path": "app.py", "start_line": 1, "end_line": 1, "text": "new\n"}

    class FakeCompleted:
        returncode = 0
        stdout = json.dumps({"schema": "simplicio.edit-result/v1", "status": "ok", "file": "app.py"})

    monkeypatch.setattr(mechanical_edit.shutil, "which", lambda name: "/bin/simplicio")
    monkeypatch.setattr(mechanical_edit.subprocess, "run", lambda cmd, **kwargs: FakeCompleted())

    result = execute_plan(_plan("app.py", operation), root=tmp_path, apply=True)

    assert result["schema"] == "simplicio.mechanical-edit-result/v1"
    assert result["status"] == "ok"
    assert result["applied"] is True
    assert (tmp_path / "app.py").read_text(encoding="utf-8") == "new\n"
