import json
from pathlib import Path

from scripts import preflight


def test_version_parser_fails_closed_for_unknown_and_accepts_patch():
    assert preflight._version("unknown") == (0, 0, 0)
    assert preflight._version("simplicio-mapper 0.19.0") == (0, 19, 0)
    assert preflight._version("runtime 3.5") == (3, 5, 0)


def test_preflight_has_no_fast_floor():
    assert not hasattr(preflight, "FAST_MINIMUM")
    assert not hasattr(preflight, "FAST_CAPABILITIES")


def test_last_json_ignores_progress_lines():
    assert preflight._last_json('progress\n{"status":"passed"}\n') == {"status": "passed"}


def test_tool_report_requires_identity_version_and_capabilities():
    report = preflight._tool_report(
        "simplicio-dev-cli", "simplicio-dev-cli", (0, 11, 0),
        {"identity": "simplicio-dev-cli", "version_text": "0.10.0",
         "surface": "task", "returncode": 0},
        preflight.DEVCLI_CAPABILITIES,
    )
    assert report["identity"] == "simplicio-dev-cli"
    assert report["version_ok"] is False
    assert report["capabilities_ok"] is False


def test_tool_report_rejects_wrong_resolved_executable_identity():
    report = preflight._tool_report(
        "simplicio-dev-cli", "simplicio-dev-cli", (0, 11, 0),
        {"identity": "simplicio-dev-cli", "path": "/tmp/simplicio.exe",
         "version_text": "0.11.0", "surface": "edit --plan --apply --dry-run --json",
         "returncode": 0},
        preflight.DEVCLI_CAPABILITIES,
    )
    assert report["version_ok"] is True
    assert report["identity_ok"] is False


def test_build_report_is_stable_shape(monkeypatch, tmp_path: Path):
    def component(*args, **kwargs):
        name = args[0]
        return {"name": name, "version": "1.0.0", "minimum_version": "0.0.0",
                "returncode": 0, "identity_ok": True, "version_ok": True, "capabilities_ok": True}

    monkeypatch.setattr(preflight, "_probe_component", component)
    monkeypatch.setattr(preflight, "_probe_runtime", lambda cwd: {
        "name": "simplicio-runtime", "version": "3.5.0", "minimum_version": "3.5.0",
        "returncode": 0, "identity_ok": True, "version_ok": True, "capabilities_ok": True,
        "runtime_contract_ok": True,
    })
    report = preflight.build_report(tmp_path)
    assert report["schema"] == "simplicio.preflight/v1"
    assert report["ready"] is True
    assert [item["name"] for item in report["components"]] == [
        "simplicio-mapper", "simplicio-dev-cli", "simplicio-runtime"
    ]
    assert "fast" not in report
    assert not hasattr(preflight, "_probe_fast")
    json.dumps(report)


def test_build_report_is_ready_without_optional_runtime(monkeypatch, tmp_path: Path):
    def component(*args, **kwargs):
        name = args[0]
        return {"name": name, "version": "1.0.0", "minimum_version": "0.0.0",
                "returncode": 0, "identity_ok": True, "version_ok": True, "capabilities_ok": True}

    monkeypatch.setattr(preflight, "_probe_component", component)
    monkeypatch.setattr(preflight, "_probe_runtime", lambda cwd: {
        "name": "simplicio-runtime", "version": "0.0.0", "minimum_version": "3.5.0",
        "returncode": 1, "identity_ok": False, "version_ok": False, "capabilities_ok": True,
        "runtime_contract_ok": False, "error": "command not found",
    })
    report = preflight.build_report(tmp_path)

    assert report["ready"] is True
    assert report["runtime_available"] is False
    assert "fast" not in report
    assert report["degraded_features"] == ["runtime-integration"]
