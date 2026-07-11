"""#100 — stable JSON payloads for the critical dev-cli commands.

Covers `detect --json`, `doctor --json` (the top-level CLI command, distinct
from `runtime doctor --json` already schema-tested in
tests/python/test_runtime_contracts.py), and the task-equivalent command
(`task --json`, the raw pipeline result) plus its `runtime_contracts.
task_contract` runtime-handoff envelope. Structural (required-keys) checks,
never a full literal snapshot — pipeline prose/wording is an intentional
optimization target elsewhere in this repo (see
test_mapping_retry_flow.py's comment on the same trade-off), so pinning
exact strings here would make the gate reject legitimate wording
improvements by construction.
"""

from __future__ import annotations

import json

from simplicio import cli
from simplicio.runtime_contracts import task_contract

from ._schema import assert_has_keys, assert_schema_id


def test_detect_json_contract(capsys):
    code = cli.main(["detect", "--prompt", "fix the null check in src/app.py", "--json", "--quiet"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert_has_keys(payload, {"is_code_task", "score", "scope", "signals"}, where="detect --json")
    assert isinstance(payload["is_code_task"], bool)
    assert isinstance(payload["signals"], list)


def test_version_json_contract(capsys, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")

    code = cli.main(["version", "--json"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert_schema_id(payload, "simplicio.dev-cli.version/v1", where="version --json")
    assert_has_keys(
        payload,
        {"package", "identity", "entrypoints", "capabilities", "compatibility", "dependencies"},
        where="version --json",
    )
    assert payload["identity"]["product"] == "simplicio-dev-cli"
    assert payload["compatibility"]["runtime"]["reserved_command"] == "simplicio"


def test_doctor_json_contract_no_network(capsys):
    # --no-check-updates: the PyPI freshness check is a real HTTP call: the
    # #100 AC is "no external calls" for this suite, so it stays off here.
    # (tests/python/test_doctor_freshness.py exercises the network branch,
    # with the HTTP call itself mocked at that layer.)
    code = cli.main(["doctor", "--json", "--no-check-updates"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    # doctor.py's RecommendationResult.to_dict() shape (simplicio/local_models.py)
    # — not the separate simplicio.dev-cli.doctor/v1 envelope emitted by
    # `runtime doctor --json` (already covered in test_runtime_contracts.py).
    assert_has_keys(
        payload,
        {"tier", "model_id", "can_run", "can_download", "installed", "reason"},
        where="doctor --json",
    )
    assert "dependencies" not in payload  # only present when update checks ran


def test_task_json_contract_over_real_mapper_fixture(
    sample_project, stub_local_provider, capsys, monkeypatch
):
    """The full local (standalone-Python) executor path: real mapper
    artifacts feed the prompt, a stubbed provider stands in for the LLM (no
    network), and SIMPLICIO_TEST_CMD stands in for the project's real test
    suite (also no network) — this is the "minimal flow" from #100's AC:
    load mapper artifacts -> classify -> build contract -> structured
    output."""
    import os

    monkeypatch.setattr(
        "simplicio.pipeline._run_impact_tests",
        lambda *_args, **_kwargs: {
            "result": "no_impact_tests",
            "status": "no_callers_found",
            "callers": [],
            "tests_run": [],
        },
    )

    # Match the stub provider's canned unified diff (-old/+new), same
    # pattern tests/python/test_task_json_contract.py uses for the same
    # reason: `_apply_and_test` runs `git apply` for real.
    (sample_project / "src" / "app.py").write_text("old\n", encoding="utf-8")
    os.environ["SIMPLICIO_TEST_CMD"] = f'"{__import__("sys").executable}" -c "raise SystemExit(0)"'
    try:
        code = cli.main(
            [
                "task",
                "add a farewell helper",
                "--root",
                str(sample_project),
                "--target",
                "src/app.py",
                "--json",
            ]
        )
    finally:
        os.environ.pop("SIMPLICIO_TEST_CMD", None)

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert_has_keys(
        payload,
        {"task_id", "applied", "files_changed", "diff_summary", "warnings"},
        where="task --json",
    )
    assert payload["applied"] is True
    assert payload["files_changed"] == ["src/app.py"]
    assert payload["patch"]["parser_strategy"] == "unified_diff"
    assert stub_local_provider, "the stubbed provider should have been called at least once"

    # Runtime-handoff envelope: what simplicio-runtime consumes when it
    # wraps this same task result (Python-level integration point; the
    # top-level `task --json` command doesn't emit this envelope itself,
    # see runtime_contracts.py's module docstring).
    envelope = task_contract(payload, root=sample_project)
    assert_schema_id(envelope, "simplicio.dev-cli.task/v1", where="task_contract")
    assert envelope["applied"] is True
    assert envelope["files_changed"] == ["src/app.py"]
