from __future__ import annotations

import json
import sys

from scripts.quality_gate import (
    DEFAULT_COMMANDS,
    SCHEMA,
    _tool_argv,
    _write_receipt,
    main,
    run_gate,
    verify_receipt,
)


def test_timeout_tree_falls_back_when_taskkill_is_unavailable(monkeypatch):
    from scripts import quality_gate

    class Process:
        pid = 123
        killed = False

        def poll(self):
            return None

        def kill(self):
            self.killed = True

        def communicate(self, timeout=None):
            return "", ""

    process = Process()
    monkeypatch.setattr(quality_gate.os, "name", "nt")
    monkeypatch.setattr(
        quality_gate.subprocess, "run", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError())
    )

    quality_gate._terminate_process_tree(process)

    assert process.killed is True


def test_tool_argv_prefers_path_entry_point(monkeypatch):
    monkeypatch.setattr("scripts.quality_gate.shutil.which", lambda name: f"/tools/{name}")
    assert _tool_argv("ruff", "check", "simplicio") == ["/tools/ruff", "check", "simplicio"]


def test_default_gate_contains_required_local_and_installed_lanes():
    names = [name for name, _argv in DEFAULT_COMMANDS]
    assert names == [
        "json-boundaries",
        "ruff",
        "ruff-format",
        "mypy",
        "pytest",
        "coverage-gate",
        "token-budget",
        "wheel-and-installed-smoke",
        "mapper-installed-matrix",
        "cli-help",
        "changeset-help",
    ]


def test_quality_gate_receipt_is_sha_bound_and_records_failures(tmp_path):
    passing = run_gate(
        tmp_path,
        commands=[("pass", [sys.executable, "-c", "print('ok')"])],
    )
    assert passing["schema"] == SCHEMA
    assert passing["commit_sha"] is None
    assert passing["passed"] is False
    assert passing["commands"][0]["name"] == "pass"
    assert passing["external_lanes"]["runtime"] == {
        "status": "UNVERIFIED",
        "value": None,
        "reason": "runtime_backed_E2E_requires_a_compatible_installed_capability",
    }
    assert passing["external_lanes"]["fast"]["value"] is None


def test_quality_gate_does_not_promote_windows_host_without_locked_file_evidence(monkeypatch, tmp_path):
    monkeypatch.setattr("scripts.quality_gate.platform.system", lambda: "Windows")
    monkeypatch.delenv("SIMPLICIO_QUALITY_GATE_E2E_REPORT", raising=False)

    payload = run_gate(tmp_path, commands=[("pass", [sys.executable, "-c", "pass"])])

    assert payload["external_lanes"]["windows"] == {
        "status": "UNVERIFIED",
        "value": None,
        "reason": "windows_locked_file_external_e2e_requires_installed_evidence",
    }


def test_quality_gate_cli_persists_failure_receipt(tmp_path):
    receipt = tmp_path / "receipt.json"
    code = main(
        [
            "--root",
            str(tmp_path),
            "--receipt",
            str(receipt),
            "--command",
            f"fail={sys.executable} -c exit(3)",
        ]
    )
    assert code == 1
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert payload["schema"] == SCHEMA
    assert payload["passed"] is False
    assert payload["commands"][0]["exit_code"] == 3
    assert payload["receipt_digest"].startswith("sha256:")


def test_quality_gate_verifier_rejects_tampering(tmp_path):
    receipt = tmp_path / "receipt.json"
    payload = run_gate(tmp_path, commands=[])
    payload["commit_sha"] = "not-current"
    _write_receipt(receipt, payload)
    ok, reason = verify_receipt(receipt, tmp_path)
    assert ok is False
    assert reason == "receipt_sha_stale"

    receipt.write_text(
        receipt.read_text(encoding="utf-8").replace('"passed": false', '"passed": true'), encoding="utf-8"
    )
    ok, reason = verify_receipt(receipt, tmp_path)
    assert ok is False
    assert reason == "receipt_digest_invalid"


def test_quality_gate_verifier_rejects_signed_failed_external_lane(monkeypatch, tmp_path):
    receipt = tmp_path / "receipt.json"
    payload = run_gate(tmp_path, commands=[("pass", [sys.executable, "-c", "pass"])])
    payload["commit_sha"] = "abc123"
    payload["passed"] = True
    payload["external_lanes"] = {
        "runtime": {"status": "FAIL", "reason": "receipt mismatch"},
    }
    monkeypatch.setattr(
        "scripts.quality_gate._git",
        lambda _root, *args: "abc123" if args == ("rev-parse", "HEAD") else None,
    )
    _write_receipt(receipt, payload)

    ok, reason = verify_receipt(receipt, tmp_path)

    assert ok is False
    assert reason == "external_lane_failed"


def test_quality_gate_records_command_timeout(tmp_path):
    payload = run_gate(
        tmp_path,
        commands=[("slow", [sys.executable, "-c", "import time; time.sleep(2)"])],
        timeout_s=1.0,
    )
    assert payload["passed"] is False
    assert payload["commands"][0]["exit_code"] == 124
    assert "TimeoutExpired" in payload["commands"][0]["error"]
    assert "process tree terminated" in payload["commands"][0]["error"]


def test_quality_gate_redacts_secret_shaped_command_output(tmp_path):
    payload = run_gate(
        tmp_path,
        commands=[
            (
                "secret-output",
                [
                    sys.executable,
                    "-c",
                    "print('Authorization: Bearer abc123 token=super-secret api_key=private')",
                ],
            )
        ],
    )

    output = payload["commands"][0]["output_tail"]
    assert "abc123" not in output
    assert "super-secret" not in output
    assert "private" not in output
    assert "[REDACTED]" in output


def test_quality_gate_redacts_secret_shaped_command_arguments(tmp_path):
    payload = run_gate(
        tmp_path,
        commands=[("secret-argument", [sys.executable, "-c", "pass", "--token=private-value"])],
    )

    argv = payload["commands"][0]["argv"]
    assert "private-value" not in " ".join(argv)
    assert "token=[REDACTED]" in " ".join(argv)


def test_quality_gate_accepts_sha_bound_external_e2e_report(monkeypatch, tmp_path):
    root = tmp_path
    (root / ".git").mkdir()
    monkeypatch.setattr(
        "scripts.quality_gate._git", lambda _root, *args: "abc123" if args == ("rev-parse", "HEAD") else None
    )
    report = root / "issue-422.json"
    report.write_text(
        json.dumps(
            {
                "schema": "simplicio.dev-cli.issue-422-evidence/v1",
                "commit_sha": "abc123",
                "scenarios": [
                    {"scenario": "windows_locked_file", "status": "PASS"},
                    {"scenario": "runtime_backed", "status": "PASS"},
                    {"scenario": "fast_rust", "status": "PASS"},
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("SIMPLICIO_QUALITY_GATE_E2E_REPORT", str(report))
    payload = run_gate(root, commands=[("pass", [sys.executable, "-c", "pass"])])
    assert payload["passed"] is True
    assert all(lane["status"] == "PASS" for lane in payload["external_lanes"].values())
    assert payload["external_e2e_report"].startswith("sha256:")


def test_quality_gate_rejects_stale_external_e2e_report(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "scripts.quality_gate._git", lambda _root, *args: "abc123" if args == ("rev-parse", "HEAD") else None
    )
    report = tmp_path / "issue-422.json"
    report.write_text(
        json.dumps(
            {
                "schema": "simplicio.dev-cli.issue-422-evidence/v1",
                "commit_sha": "different",
                "scenarios": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("SIMPLICIO_QUALITY_GATE_E2E_REPORT", str(report))
    payload = run_gate(tmp_path, commands=[])
    assert payload["passed"] is False
    assert payload["external_lanes"]["runtime"]["reason"] == "external_e2e_report_sha_stale"


def test_quality_gate_keeps_optional_unverified_lanes_separate(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "scripts.quality_gate._git", lambda _root, *args: "abc123" if args == ("rev-parse", "HEAD") else None
    )
    report = tmp_path / "issue-422.json"
    report.write_text(
        json.dumps(
            {
                "schema": "simplicio.dev-cli.issue-422-evidence/v1",
                "commit_sha": "abc123",
                "scenarios": [
                    {"scenario": "windows_locked_file", "status": "PASS"},
                    {
                        "scenario": "runtime_backed",
                        "status": "AVAILABLE_NOT_E2E",
                        "reason": "effect URL unset",
                    },
                    {"scenario": "fast_rust", "status": "UNVERIFIED", "reason": "native unavailable"},
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("SIMPLICIO_QUALITY_GATE_E2E_REPORT", str(report))

    payload = run_gate(tmp_path, commands=[("pass", [sys.executable, "-c", "pass"])])

    assert payload["passed"] is True
    assert payload["external_lanes"]["runtime"]["status"] == "UNVERIFIED"
    assert payload["external_lanes"]["runtime"]["reason"] == "effect URL unset"
    assert payload["external_lanes"]["fast"]["status"] == "UNVERIFIED"
