"""Recovery and packaging coverage for the loop's bound operators."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from simplicio_loop import operator_bootstrap
from simplicio_loop import runner


class _Result:
    def __init__(self, returncode: int, stderr: str = ""):
        self.returncode = returncode
        self.stdout = ""
        self.stderr = stderr


def test_normal_package_contract_requests_both_operator_distributions():
    pyproject = (Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    assert '"simplicio-cli>=0.18.12,<0.19"' in pyproject
    assert '"simplicio-mapper>=0.26.31,<0.27"' in pyproject


def test_available_operators_do_not_run_pip(tmp_path, monkeypatch):
    monkeypatch.setattr(operator_bootstrap, "_missing_binaries", lambda: [])
    monkeypatch.setattr(
        operator_bootstrap.shutil, "which", lambda name: "/tools/" + name
    )

    def forbidden(*_args, **_kwargs):
        raise AssertionError("pip must not run when both operators are available")

    receipt = operator_bootstrap.ensure_operators(tmp_path, run=forbidden)
    assert receipt["status"] == "already_available"
    assert receipt["attempted"] is False


def test_missing_operators_install_together_and_become_visible(tmp_path, monkeypatch):
    probes = iter([
        ["simplicio-mapper", "simplicio-dev-cli"],
        [],
    ])
    monkeypatch.setattr(
        operator_bootstrap, "_missing_binaries", lambda: next(probes)
    )
    monkeypatch.setattr(operator_bootstrap, "_refresh_process_path", lambda: None)
    monkeypatch.setattr(
        operator_bootstrap.shutil, "which", lambda name: "/tools/" + name
    )
    calls = []

    def fake_run(argv, **_kwargs):
        calls.append(argv)
        return _Result(0)

    receipt = operator_bootstrap.ensure_operators(tmp_path, env={}, run=fake_run)
    assert receipt["status"] == "installed"
    assert receipt["missing_after"] == []
    assert calls and "simplicio-cli" in calls[0]
    assert "simplicio-mapper" in calls[0]
    assert "simplicio-fast" not in calls[0]
    assert operator_bootstrap.REQUIRED_BINARIES == ("simplicio-mapper", "simplicio-dev-cli")
    assert "simplicio-loop" in calls[0]


def test_bootstrap_uses_safe_user_fallback_without_break_system_packages(
    tmp_path, monkeypatch
):
    probes = iter([["simplicio-mapper"], []])
    monkeypatch.setattr(
        operator_bootstrap, "_missing_binaries", lambda: next(probes)
    )
    monkeypatch.setattr(operator_bootstrap, "_refresh_process_path", lambda: None)
    monkeypatch.setattr(
        operator_bootstrap.shutil, "which", lambda name: "/tools/" + name
    )
    calls = []

    def fake_run(argv, **_kwargs):
        calls.append(argv)
        return _Result(1, "externally-managed-environment") if len(calls) == 1 else _Result(0)

    receipt = operator_bootstrap.ensure_operators(tmp_path, env={}, run=fake_run)
    assert receipt["status"] == "installed"
    assert "--user" in calls[1]
    assert "--break-system-packages" not in calls[1]


def test_disabled_bootstrap_remains_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(
        operator_bootstrap, "_missing_binaries",
        lambda: ["simplicio-mapper"],
    )
    with pytest.raises(operator_bootstrap.OperatorBootstrapError):
        operator_bootstrap.ensure_operators(
            tmp_path,
            env={operator_bootstrap.AUTO_BOOTSTRAP_ENV: "0"},
        )
    receipt = json.loads(
        (tmp_path / "operator-bootstrap.json").read_text(encoding="utf-8")
    )
    assert receipt["status"] == "disabled"


def test_path_refresh_missing_probe_and_secret_redaction(monkeypatch):
    monkeypatch.setenv("PATH", "/old/bin")
    monkeypatch.setattr(
        operator_bootstrap, "_candidate_script_dirs", lambda: ["/new/bin", "/old/bin"]
    )
    operator_bootstrap._refresh_process_path()
    assert operator_bootstrap.os.environ["PATH"].split(operator_bootstrap.os.pathsep)[0] == "/new/bin"

    monkeypatch.setattr(
        operator_bootstrap.shutil,
        "which",
        lambda name: None if name == "simplicio-mapper" else "/tools/" + name,
    )
    assert operator_bootstrap._missing_binaries() == ["simplicio-mapper"]
    assert "pypi-secret" not in operator_bootstrap._redact(
        "failed with pypi-secret token"
    )


def test_successful_attempt_receipt_is_reused_without_second_install(
    tmp_path, monkeypatch
):
    receipt = {
        "schema": operator_bootstrap.SCHEMA,
        "status": "installed",
        "attempted": True,
        "detail": "done",
    }
    (tmp_path / "operator-bootstrap.json").write_text(
        json.dumps(receipt), encoding="utf-8"
    )
    probes = iter([["simplicio-mapper"], []])
    monkeypatch.setattr(
        operator_bootstrap, "_missing_binaries", lambda: next(probes)
    )
    monkeypatch.setattr(operator_bootstrap, "_refresh_process_path", lambda: None)

    result = operator_bootstrap.ensure_operators(
        tmp_path,
        force=True,
        env={},
        run=lambda *_args, **_kwargs: pytest.fail("unexpected second install"),
    )
    assert result["status"] == "installed"


def test_failed_attempt_is_persisted_and_not_retried(tmp_path, monkeypatch):
    monkeypatch.setattr(
        operator_bootstrap,
        "_missing_binaries",
        lambda: ["simplicio-mapper", "simplicio-dev-cli"],
    )
    monkeypatch.setattr(operator_bootstrap, "_refresh_process_path", lambda: None)
    calls = {"count": 0}

    def failing_run(_argv, **_kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise OSError("network pypi-secret")
        return _Result(1, "index unavailable")

    with pytest.raises(
        operator_bootstrap.OperatorBootstrapError, match="bootstrap failed"
    ):
        operator_bootstrap.ensure_operators(tmp_path, env={}, run=failing_run)
    stored = json.loads(
        (tmp_path / "operator-bootstrap.json").read_text(encoding="utf-8")
    )
    assert stored["status"] == "failed"
    assert len(stored["attempts"]) == 2
    assert "pypi-secret" not in json.dumps(stored)

    with pytest.raises(
        operator_bootstrap.OperatorBootstrapError, match="already attempted"
    ):
        operator_bootstrap.ensure_operators(tmp_path, force=True, env={}, run=failing_run)
    assert calls["count"] == 2


def test_runner_retries_recoverable_operator_failure_once(tmp_path, monkeypatch):
    (tmp_path / "state.json").write_text(
        json.dumps({"run_id": "run-1", "phase": "mapping", "events": []}),
        encoding="utf-8",
    )
    calls = {"operation": 0, "bootstrap": 0}

    def operation():
        calls["operation"] += 1
        if calls["operation"] == 1:
            raise FileNotFoundError("simplicio-mapper")
        return {"status": "ready"}

    def bootstrap(run_dir, force=False):
        calls["bootstrap"] += 1
        assert Path(run_dir) == tmp_path
        assert force is True
        (tmp_path / "operator-bootstrap.json").write_text(
            json.dumps({"schema": operator_bootstrap.SCHEMA, "status": "installed",
                        "attempted": True}),
            encoding="utf-8",
        )
        return {"status": "installed"}

    monkeypatch.setattr(runner, "_ensure_required_operators", bootstrap)
    result = runner._run_with_operator_recovery(
        "simplicio-mapper", tmp_path, operation
    )
    assert result["status"] == "ready"
    assert calls == {"operation": 2, "bootstrap": 1}
    receipt = json.loads(
        (tmp_path / "operator-bootstrap.json").read_text(encoding="utf-8")
    )
    assert receipt["retry_succeeded"] is True


def test_runner_does_not_download_for_non_operator_block(tmp_path, monkeypatch):
    monkeypatch.setattr(
        runner,
        "_ensure_required_operators",
        lambda *_args, **_kwargs: pytest.fail("unexpected bootstrap"),
    )
    with pytest.raises(RuntimeError, match="source drift"):
        runner._run_with_operator_recovery(
            "simplicio-mapper",
            tmp_path,
            lambda: (_ for _ in ()).throw(RuntimeError("source drift")),
        )
