from __future__ import annotations

import hashlib
import json
import sys

from simplicio.mechanical_edit import execute_plan, execute_plan_json


def _write(path, text: str | bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_text(text, encoding="utf-8")


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
