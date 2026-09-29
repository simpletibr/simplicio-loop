import json
from pathlib import Path

import pytest

from simplicio_loop import ecosystem_doctor as doctor


def _fake_dist(version="1.0.0", installed=True):
    return {"installed": installed, "version": version if installed else None,
            "path": "/tmp/site-packages", "entrypoints": ["fake-entry"]}


def _probe(monkeypatch, *, component="simplicio-mapper", version="0.26.11",
           help_text="orient recall", executable="/usr/local/bin/simplicio-mapper",
           installed=True):
    monkeypatch.setattr(doctor, "_distribution", lambda _: _fake_dist(version, installed))
    monkeypatch.setattr(doctor.shutil, "which", lambda _: executable)
    monkeypatch.setattr(doctor, "_git_sha", lambda _: "a" * 40)
    monkeypatch.setattr(doctor, "_submodule_shas", lambda _: {"vendor/mapper": "b" * 40})
    monkeypatch.setattr(doctor, "_run", lambda *args, **kwargs: type(
        "Result", (), {"returncode": 0, "stdout": help_text, "stderr": ""})())
    return doctor._probe_component(component, doctor.COMPONENTS[component], Path("."),
                                   doctor.PROFILES["standalone"][component])


def test_probe_reports_available_with_identity_version_capabilities_and_shas(monkeypatch):
    row = _probe(monkeypatch, help_text="simplicio-mapper 0.26.11 orient recall")
    assert row["status"] == doctor.STATUS_AVAILABLE
    assert row["git_sha"] is None
    assert row["sha_source"] == "unavailable"
    assert row["submodule_shas"]["vendor/mapper"] == "b" * 40
    assert row["entrypoints"] == ["fake-entry"]
    assert "simplicio.context-snapshot/v1" in row["supported_schemas"]


def test_mapper_recall_role_proven_by_handoff_ask_cli_surface(monkeypatch):
    """Real mapper --help exposes orient/handoff/ask, not the word 'recall'."""
    help_text = (
        "simplicio-mapper 0.26.11\n"
        "  simplicio-mapper orient <path>\n"
        "  simplicio-mapper handoff <path>\n"
        "  simplicio-mapper ask <path> <verb>\n"
        "  simplicio-mapper inspect <path>\n"
        "  simplicio-mapper scan <path>\n"
    )
    row = _probe(monkeypatch, version="0.26.11", help_text=help_text)
    assert row["status"] == doctor.STATUS_AVAILABLE
    assert "orient" in row["capabilities"]
    assert "recall" in row["capabilities"]
    assert row["missing_capabilities"] == []


def test_capability_evidence_aliases_are_documented():
    assert "handoff" in doctor.CAPABILITY_EVIDENCE["recall"]
    assert "ask" in doctor.CAPABILITY_EVIDENCE["recall"]
    assert doctor._capability_proven("recall", "handoff . --json")
    assert not doctor._capability_proven("recall", "scan only")


def test_version_probe_ignores_stderr_traceback_python_path(monkeypatch):
    """Windows Python install paths contain 3.14; must not become package version."""
    def fake_run(cmd, *args, **kwargs):
        if "--version" in cmd:
            return type("Result", (), {
                "returncode": 1,
                "stdout": "",
                "stderr": r"File \"C:\Python\pythoncore-3.14-64\lib\runpy.py\"",
            })()
        return type("Result", (), {
            "returncode": 0,
            "stdout": "orient handoff ask inspect scan",
            "stderr": "",
        })()

    monkeypatch.setattr(doctor, "_distribution", lambda _: _fake_dist("0.26.11", True))
    monkeypatch.setattr(doctor.shutil, "which", lambda _: "/bin/simplicio-mapper")
    monkeypatch.setattr(doctor, "_git_sha", lambda _: None)
    monkeypatch.setattr(doctor, "_submodule_shas", lambda _: {})
    monkeypatch.setattr(doctor, "_run", fake_run)
    row = doctor._probe_component(
        "simplicio-mapper",
        doctor.COMPONENTS["simplicio-mapper"],
        Path("."),
        doctor.PROFILES["standalone"]["simplicio-mapper"],
    )
    assert row["status"] == doctor.STATUS_AVAILABLE
    assert row["parsed_version"] == "0.26.11"
    assert row["parsed_version"] != "3.14.0"


def test_loop_sha_is_only_reported_for_the_loop_checkout(monkeypatch, tmp_path):
    monkeypatch.setattr(doctor, "_distribution", lambda _: _fake_dist("3.38.7", True))
    monkeypatch.setattr(doctor.shutil, "which", lambda _: None)
    monkeypatch.setattr(doctor, "_git_sha", lambda _: "a" * 40)
    monkeypatch.setattr(doctor, "_submodule_shas", lambda _: {})
    row = doctor._probe_component("simplicio-loop", doctor.COMPONENTS["simplicio-loop"],
                                  tmp_path, doctor.PROFILES["standalone"]["simplicio-loop"])
    assert row["git_sha"] == "a" * 40
    assert row["sha_source"] == "checkout"


def test_probe_distinguishes_missing_incompatible_disabled_and_degraded(monkeypatch, tmp_path):
    monkeypatch.setattr(doctor, "_distribution", lambda _: _fake_dist(installed=False))
    monkeypatch.setattr(doctor.shutil, "which", lambda _: None)
    missing = doctor._probe_component("simplicio-mapper", doctor.COMPONENTS["simplicio-mapper"],
                                      tmp_path, doctor.PROFILES["standalone"]["simplicio-mapper"])
    assert missing["status"] == doctor.STATUS_MISSING
    assert "install simplicio-mapper" in missing["remediation"]

    incompatible = _probe(monkeypatch, component="simplicio-mapper", version="0.1.0",
                          help_text="orient recall")
    assert incompatible["status"] == doctor.STATUS_INCOMPATIBLE
    assert "no automatic upgrade" in incompatible["remediation"]

    disabled = doctor._probe_component("simplicio-mapper", doctor.COMPONENTS["simplicio-mapper"],
                                       tmp_path, doctor.PROFILES["standalone"]["simplicio-mapper"],
                                       disabled=["simplicio-mapper"])
    assert disabled["status"] == doctor.STATUS_DISABLED
    assert disabled["reason_code"] == "disabled"

    # Metadata meets the floor, but the console entrypoint is missing → degraded.
    min_mapper = doctor.PROFILES["standalone"]["simplicio-mapper"]["min_version"]
    monkeypatch.setattr(doctor, "_distribution", lambda _: _fake_dist(min_mapper, installed=True))
    monkeypatch.setattr(doctor.shutil, "which", lambda _: None)
    degraded = doctor._probe_component("simplicio-mapper", doctor.COMPONENTS["simplicio-mapper"],
                                       tmp_path, doctor.PROFILES["standalone"]["simplicio-mapper"])
    assert degraded["status"] == doctor.STATUS_DEGRADED
    assert degraded["reason_code"] == "distribution_installed_but_entrypoint_missing"


def test_build_report_persists_preplanning_handshake_and_no_secrets(monkeypatch, tmp_path):
    rows = []
    for name, policy in doctor.PROFILES["standalone"].items():
        rows.append({"name": name, "status": doctor.STATUS_AVAILABLE, "required": policy["required"],
                     "version": policy["min_version"], "minimum_version": policy["min_version"],
                     "capabilities": list(policy["capabilities"]), "missing_capabilities": [],
                     "git_sha": "c" * 40, "submodule_shas": {}, "supported_schemas": [],
                     "entrypoints": [], "remediation": None})
    monkeypatch.setattr(doctor, "_probe_component", lambda *args, **kwargs: rows.pop(0))
    report = doctor.build_report(tmp_path, profile="standalone", persist=True)
    assert report["schema"] == doctor.SCHEMA
    assert report["status"] == "READY"
    handshake = report["handshake"]
    assert handshake["written"] is True
    line = (tmp_path / ".simplicio-loop/orchestrator/loop/journal.jsonl").read_text().strip()
    record = json.loads(line)
    assert record["schema"] == doctor.HANDSHAKE_SCHEMA
    assert record["phase"] == "pre_planning"
    assert record["handshake_sha"].startswith("sha256:")
    assert "API_KEY" not in line and "TOKEN" not in line


def test_standalone_profile_fails_closed_on_required_component(monkeypatch, tmp_path):
    def probe(name, spec, root, policy, **kwargs):
        return {"name": name, "status": doctor.STATUS_INCOMPATIBLE if name == "simplicio-dev-cli" else doctor.STATUS_AVAILABLE,
                "required": policy["required"], "version": "0.0.0", "minimum_version": policy["min_version"],
                "capabilities": [], "missing_capabilities": ["execute"] if name == "simplicio-dev-cli" else [],
                "git_sha": None, "submodule_shas": {}, "supported_schemas": [], "entrypoints": [],
                "remediation": "upgrade simplicio-cli"}
    monkeypatch.setattr(doctor, "_probe_component", probe)
    report = doctor.build_report(tmp_path, profile="standalone", persist=False)
    assert report["ready"] is False
    assert report["status"] == "BLOCKED"
    assert report["blockers"] == ["simplicio-dev-cli"]
    assert report["handshake"]["written"] is False


def test_standalone_stack_has_no_runtime_component_and_no_other_profile(monkeypatch, tmp_path):
    def probe(name, spec, root, policy, **kwargs):
        return {"name": name, "status": doctor.STATUS_AVAILABLE, "required": policy["required"],
                "version": policy["min_version"], "minimum_version": policy["min_version"],
                "capabilities": list(policy["capabilities"]), "missing_capabilities": [],
                "git_sha": None, "submodule_shas": {}, "supported_schemas": [], "entrypoints": [],
                "remediation": None}
    monkeypatch.setattr(doctor, "_probe_component", probe)
    report = doctor.build_report(tmp_path, profile="standalone", persist=False)
    assert report["ready"] is True
    assert [item["name"] for item in report["components"]] == [
        "simplicio-loop", "simplicio-mapper", "simplicio-dev-cli",
    ]
    assert report["policy"]["optional_components"] == []
    assert "fallbacks" not in report["policy"]
    with pytest.raises(ValueError, match="unknown profile"):
        doctor.build_report(tmp_path, profile="full-stack", persist=False)


def test_secret_like_probe_errors_are_redacted():
    assert doctor._redact("api_key=abc token:xyz password = foo") == (
        "api_key=[REDACTED] token:[REDACTED] password = [REDACTED]"
    )


def test_environment_probe_reports_python_platform_and_abi():
    row = doctor._environment_probe()
    assert row["status"] == doctor.STATUS_AVAILABLE
    assert row["minimum_python"] == "3.11"
    assert row["platform"]
    assert row["machine"]
    assert row["python_abi"]


def test_environment_probe_blocks_incompatible_python(monkeypatch, tmp_path):
    monkeypatch.setattr(doctor.sys, "version_info", (3, 10, 14))
    row = doctor._environment_probe()
    assert row["status"] == doctor.STATUS_INCOMPATIBLE
    assert "PYTHON_VERSION_INCOMPATIBLE" in row["reason_codes"]

    monkeypatch.setattr(
        doctor,
        "_probe_component",
        lambda name, spec, root, policy, **kwargs: {
            "name": name,
            "status": doctor.STATUS_AVAILABLE,
            "required": policy["required"],
            "version": policy["min_version"],
            "minimum_version": policy["min_version"],
            "capabilities": list(policy["capabilities"]),
            "missing_capabilities": [],
            "git_sha": None,
            "submodule_shas": {},
            "supported_schemas": [],
            "entrypoints": [],
            "remediation": None,
        },
    )
    report = doctor.build_report(tmp_path, persist=False)
    assert report["status"] == "BLOCKED"
    assert report["blockers"] == ["environment"]


def test_wheel_fallback_persists_without_checkout_scripts(monkeypatch, tmp_path):
    fake_module = tmp_path / "wheel" / "simplicio_loop" / "ecosystem_doctor.py"
    monkeypatch.setattr(doctor, "__file__", str(fake_module))
    target = tmp_path / "journal" / "journal.jsonl"
    assert doctor._append_journal_line(target, '{"schema":"test/v1"}') is True
    assert json.loads(target.read_text()) == {"schema": "test/v1"}


def test_no_fast_component_or_profile_entry():
    assert "simplicio-fast" not in doctor.COMPONENTS
    for profile in doctor.PROFILES.values():
        assert "simplicio-fast" not in profile
