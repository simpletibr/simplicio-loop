"""Preflight: Runtime optional when absent; bound when operational/strict."""
from __future__ import annotations

import contextlib
import io
import json
from types import SimpleNamespace

from simplicio_loop import cli


def test_preflight_continues_without_optional_runtime(monkeypatch, tmp_path):
    def fake_run(command, **_kwargs):
        binary = command[0]
        if binary == "simplicio" or binary.endswith("simplicio.exe"):
            return SimpleNamespace(returncode=127, stdout="", stderr="runtime missing")
        return SimpleNamespace(returncode=0, stdout="ready\n", stderr="")

    monkeypatch.setattr("simplicio_loop.strict_mode.subprocess.run", fake_run)
    monkeypatch.setattr("simplicio_loop.strict_mode.shutil.which", lambda b: None if b in {"simplicio"} else "/bin/" + b)
    monkeypatch.setattr("simplicio_loop.strict_mode._runtime_candidate_paths", lambda _env: [])
    findings = []
    monkeypatch.setattr(
        "simplicio_loop.finding_router.route_finding",
        lambda **finding: findings.append(finding),
    )
    monkeypatch.delenv("SIMPLICIO_LOOP_STRICT", raising=False)
    monkeypatch.setenv("SIMPLICIO_LOOP_REQUIRE_RUNTIME", "auto")

    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        assert cli.preflight(str(tmp_path), as_json=True) == 0

    receipt = json.loads(output.getvalue())
    assert receipt["all_present"] is True
    assert receipt["runtime_available"] is False
    assert "runtime-integration" in receipt["degraded_features"]
    assert findings == []


def test_preflight_strict_binds_operational_runtime(monkeypatch, tmp_path):
    def which(binary):
        return "/bin/" + binary

    def fake_run(command, **_kwargs):
        return SimpleNamespace(returncode=0, stdout="Simplicio Runtime 3.5.5\n", stderr="")

    monkeypatch.setattr("simplicio_loop.strict_mode.shutil.which", which)
    monkeypatch.setattr("simplicio_loop.strict_mode.subprocess.run", fake_run)
    monkeypatch.setattr(
        "simplicio_loop.strict_mode._runtime_candidate_paths", lambda _env: ["/bin/simplicio"]
    )
    monkeypatch.setattr(
        "simplicio_loop.finding_router.route_finding",
        lambda **_finding: None,
    )
    monkeypatch.setenv("SIMPLICIO_LOOP_REQUIRE_RUNTIME", "required")

    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        code = cli.preflight(str(tmp_path), as_json=True, strict=True)
    assert code == 0
    receipt = json.loads(output.getvalue())
    assert receipt["strict"] is True
    assert receipt["runtime_available"] is True
    assert receipt["execution_profile"] == "runtime-backed"
    assert receipt["hand_edit_forbidden"] is True
    assert "simplicio" in receipt["required_operators"]
