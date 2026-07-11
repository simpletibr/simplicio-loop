from __future__ import annotations

import json

from simplicio import cli
from simplicio.runtime_contracts import doctor_contract, task_contract, version_contract


def test_version_contract_exposes_canonical_capabilities(monkeypatch):
    monkeypatch.setattr("simplicio.runtime_contracts.__version__", "0.12.0")
    payload = version_contract()

    assert payload["schema"] == "simplicio.dev-cli.version/v1"
    assert payload["package"] == {"name": "simplicio-cli", "version": "0.12.0"}
    assert payload["identity"] == {
        "product": "simplicio-dev-cli",
        "role": "adapter",
        "family": "simplicio",
        "canonical_entrypoint": "simplicio-dev-cli",
    }
    assert "simplicio.task-spec/v2" in payload["capabilities"]
    assert "simplicio.dev-cli.patch-receipt/v1" in payload["capabilities"]
    assert "simplicio.dev-cli.task-batch/v1" in payload["capabilities"]
    assert "simplicio.prompt-envelope/v1" in payload["capabilities"]
    assert payload["compatibility"]["task_spec"]["minimum_consumer_major"] == 2
    assert payload["compatibility"]["runtime"] == {
        "product": "simplicio-runtime",
        "reserved_command": "simplicio",
        "reject_products": ["simplicio-agent", "hermes"],
        "diagnostic": (
            "Expected Simplicio Runtime on `simplicio`; if PATH resolves to "
            "Agent/Desktop, use `simplicio-agent` for that binary and point "
            "runtime consumers at the Rust runtime explicitly."
        ),
    }


def test_version_cli_supports_text_and_json(monkeypatch, capsys):
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")

    assert cli.main(["--version"]) == 0
    assert "simplicio-py 0.14.1" in capsys.readouterr().out

    assert cli.main(["version", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "simplicio.dev-cli.version/v1"
    assert payload["identity"]["product"] == "simplicio-dev-cli"
    assert payload["compatibility"]["runtime"]["reserved_command"] == "simplicio"


def test_doctor_contract_reports_ecosystem_tool_status(tmp_path, monkeypatch):
    def fake_which(name: str):
        return f"/bin/{name}" if name in {"simplicio-mapper", "simplicio-dev-cli", "simplicio-py"} else None

    monkeypatch.setattr("simplicio.runtime_contracts.shutil.which", fake_which)
    monkeypatch.setattr(
        "simplicio.runtime_contracts._package_version",
        lambda name: "1.2.3" if name == "simplicio-cli" else None,
    )

    result = doctor_contract(tmp_path)

    assert result["schema"] == "simplicio.dev-cli.doctor/v1"
    assert result["root"] == str(tmp_path)
    assert result["tools"]["simplicio-mapper"]["available"] is True
    assert result["tools"]["simplicio-dev-cli"]["available"] is True
    assert result["tools"]["simplicio-py"]["available"] is True
    assert result["tools"]["simplicio-sprint"]["available"] is False
    assert "simplicio" not in result["tools"]
    assert result["packages"]["simplicio-cli"]["version"] == "1.2.3"
    assert result["package"]["version"] == "1.2.3"
    assert result["identity"] == {
        "product": "simplicio-dev-cli",
        "role": "adapter",
        "family": "simplicio",
        "canonical_entrypoint": "simplicio-dev-cli",
    }
    assert result["entrypoints"] == {
        "adapter": "simplicio-dev-cli",
        "python_adapter": "simplicio-py",
        "reserved_runtime": "simplicio",
    }
    assert result["runtime"]["model"] == "openbmb/minicpm5:latest"


def test_doctor_contract_falls_back_to_local_version_for_editable_checkout(tmp_path, monkeypatch):
    monkeypatch.setattr("simplicio.runtime_contracts.shutil.which", lambda name: None)
    monkeypatch.setattr("simplicio.runtime_contracts._package_version", lambda name: None)

    result = doctor_contract(tmp_path)

    assert result["package"]["version"]
    assert result["packages"]["simplicio-cli"]["version"] == result["package"]["version"]


def test_task_contract_wraps_existing_task_result_for_runtime_handoff(tmp_path):
    result = task_contract(
        {
            "task_id": "src/app.py",
            "applied": True,
            "files_changed": ["src/app.py"],
            "warnings": [],
        },
        root=tmp_path,
    )

    assert result["schema"] == "simplicio.dev-cli.task/v1"
    assert result["root"] == str(tmp_path)
    assert result["task"]["task_id"] == "src/app.py"
    assert result["applied"] is True


def test_runtime_doctor_cli_outputs_json_contract(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")
    monkeypatch.setattr("simplicio.runtime_contracts.shutil.which", lambda name: None)

    code = cli.main(["runtime", "doctor", "--root", str(tmp_path), "--json"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "simplicio.dev-cli.doctor/v1"
    assert payload["root"] == str(tmp_path)


def test_smoke_cli_can_emit_stable_json(monkeypatch, capsys):
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")
    monkeypatch.setattr("simplicio.providers.info", lambda: "test-provider")
    monkeypatch.setattr("simplicio.providers.generate", lambda prompt: "OK simplicio connected.")

    code = cli.main(["smoke", "--json"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "simplicio.dev-cli.smoke/v1"
    assert payload["provider"] == "test-provider"
    assert payload["ok"] is True


# ── Issue #93: impact-test evidence in task_contract ─────────────────────


def test_task_contract_carries_impact_block_when_present():
    result = task_contract(
        {
            "task_id": "src/lib.py",
            "applied": True,
            "files_changed": ["src/lib.py"],
            "warnings": [],
            "impact": {
                "callers": ["src/caller.py"],
                "tests_run": ["tests/test_caller.py"],
                "result": "passed",
                "status": "verified",
            },
        },
    )

    assert "impact" in result
    assert result["impact"]["callers"] == ["src/caller.py"]
    assert result["impact"]["tests_run"] == ["tests/test_caller.py"]
    assert result["impact"]["result"] == "passed"
    assert result["impact"]["status"] == "verified"


def test_task_contract_carries_prompt_envelope_when_present():
    result = task_contract(
        {
            "task_id": "src/lib.py",
            "applied": True,
            "files_changed": ["src/lib.py"],
            "warnings": [],
            "prompt_envelope": {
                "schema": "simplicio.prompt-envelope/v1",
                "prefix_hash": "sha256:abc",
            },
        },
    )

    assert result["prompt_envelope"]["schema"] == "simplicio.prompt-envelope/v1"
    assert result["task"]["prompt_envelope"]["prefix_hash"] == "sha256:abc"


def test_task_contract_carries_verify_block_when_present():
    result = task_contract(
        {
            "task_id": "src/lib.py",
            "applied": True,
            "files_changed": ["src/lib.py"],
            "warnings": [],
            "verify": {
                "status": "verified",
                "receipt": {
                    "command": "pytest -q",
                    "exit_code": 0,
                    "receipt_digest": "digest",
                },
            },
        },
    )

    assert result["verify"]["status"] == "verified"
    assert result["verify"]["receipt"]["command"] == "pytest -q"
    assert result["task"]["verify"]["status"] == "verified"
    assert result["task"]["verify"]["receipt"]["command"] == "pytest -q"
    assert result["task"]["verify"]["receipt"]["receipt_digest"] == "digest"


def test_task_contract_omits_impact_block_when_absent():
    result = task_contract(
        {
            "task_id": "src/lib.py",
            "applied": True,
            "files_changed": ["src/lib.py"],
            "warnings": [],
        },
    )

    assert "impact" not in result


def test_task_contract_impact_block_shows_unverified_when_unknown():
    result = task_contract(
        {
            "task_id": "src/lib.py",
            "applied": True,
            "files_changed": ["src/lib.py"],
            "warnings": [],
            "impact": {"callers": [], "tests_run": [], "result": "unverified"},
        },
    )

    assert "impact" in result
    assert result["impact"]["result"] == "unverified"
    assert result["impact"]["status"] == "unverified"
