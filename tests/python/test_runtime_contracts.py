from __future__ import annotations

import json

from simplicio import cli
from simplicio.runtime_contracts import doctor_contract, task_contract


def test_doctor_contract_reports_ecosystem_tool_status(tmp_path, monkeypatch):
    def fake_which(name: str):
        return f"/bin/{name}" if name in {"simplicio-mapper", "simplicio"} else None

    monkeypatch.setattr("simplicio.runtime_contracts.shutil.which", fake_which)
    monkeypatch.setattr(
        "simplicio.runtime_contracts._package_version",
        lambda name: "1.2.3" if name == "simplicio-cli" else None,
    )

    result = doctor_contract(tmp_path)

    assert result["schema"] == "simplicio.dev-cli.doctor/v1"
    assert result["root"] == str(tmp_path)
    assert result["tools"]["simplicio-mapper"]["available"] is True
    assert result["tools"]["simplicio-sprint"]["available"] is False
    assert result["packages"]["simplicio-cli"]["version"] == "1.2.3"


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
