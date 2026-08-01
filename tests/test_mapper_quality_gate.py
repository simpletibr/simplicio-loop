import sys
from pathlib import Path

from scripts.mapper_quality_gate import _release_evidence, _status, build_report, main


def test_quality_report_is_markdown_and_preserves_unavailable_evidence():
    root = Path(__file__).parents[1]
    report, code = build_report(root, runtime_binary="definitely-missing-simplicio")
    assert code == 0
    assert report.startswith("# Mapper quality gate")
    assert "Performance | null" in report
    assert "HBP receipt | null" in report
    assert "Runtime ecosystem doctor | null" in report


def test_runtime_requirement_blocks_missing_runtime():
    root = Path(__file__).parents[1]
    _, code = build_report(
        root,
        runtime_binary="definitely-missing-simplicio",
        require_runtime=True,
    )
    assert code == 1


def test_release_gate_fails_closed_on_legacy_json_and_missing_evidence():
    report, code = build_report(
        Path(__file__).parents[1],
        runtime_binary="definitely-missing-simplicio",
        release=True,
    )
    assert code == 1
    assert "Overall: **BLOCKED**" in report
    assert "INTERNAL_JSON .simplicio/project-map.json" in report
    assert "Cross-repository E2E | null" in report


def test_release_evidence_requires_boolean_observation_and_detail(tmp_path):
    evidence = tmp_path / "release-evidence.toml"
    evidence.write_text(
        '''[evidence.cross_repository_e2e]
observed = true
detail = "installed mapper 1.2 consumed by dev-cli 2.3"

[evidence.performance]
observed = false
detail = "peak RSS exceeded the bound"

[evidence.hbp_receipt]
observed = true

[evidence.hbi_conformance]
observed = "yes"
detail = "not a boolean"
''',
        encoding="utf-8",
    )
    checks = dict((name, (status, detail)) for name, status, detail in _release_evidence(evidence))
    assert checks["cross_repository_e2e"] == (
        "pass",
        "installed mapper 1.2 consumed by dev-cli 2.3",
    )
    assert checks["performance"] == ("fail", "peak RSS exceeded the bound")
    assert checks["hbp_receipt"][0] == "null"
    assert checks["hbi_conformance"][0] == "null"


def test_release_gate_accepts_complete_observed_evidence_when_other_checks_pass(tmp_path, monkeypatch):
    evidence = tmp_path / "release-evidence.toml"
    evidence.write_text(
        "\n".join(
            f'[evidence.{name}]\nobserved = true\ndetail = "observed {name}"\n'
            for name in ("cross_repository_e2e", "performance", "hbp_receipt", "hbi_conformance")
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("scripts.mapper_quality_gate._run", lambda *_: (True, "scanner passed"))
    monkeypatch.setattr("scripts.mapper_quality_gate._runtime_check", lambda *_: ("pass", "runtime passed"))
    monkeypatch.setattr(
        "scripts.mapper_quality_gate._status",
        lambda *_, **__: ("pass", "tool passed"),
    )
    report, code = build_report(
        tmp_path,
        full=True,
        release=True,
        evidence_path=evidence,
    )
    assert code == 0
    assert "Overall: **PASS**" in report


def test_report_escapes_multiline_and_table_delimiters(monkeypatch):
    monkeypatch.setattr("scripts.mapper_quality_gate._run", lambda *_: (True, "ok|next\nline"))
    monkeypatch.setattr("scripts.mapper_quality_gate._runtime_check", lambda *_: ("pass", "ok"))
    report, _ = build_report(Path(__file__).parents[1])
    assert "ok\\|next<br>line" in report


def test_status_distinguishes_pass_failure_and_missing_command(tmp_path):
    assert _status([sys.executable, "-c", "print('ok')"], tmp_path) == ("pass", "ok")
    status, detail = _status([sys.executable, "-c", "raise SystemExit('bad')"], tmp_path)
    assert status == "fail" and detail == "bad"
    status, _ = _status(["definitely-missing-command"], tmp_path)
    assert status == "null"


def test_status_classifies_localized_missing_tool_without_matching_error_text(monkeypatch, tmp_path):
    def missing_tool(*_args, **_kwargs):
        raise FileNotFoundError(2, "O sistema não pode encontrar o arquivo especificado")

    monkeypatch.setattr("scripts.mapper_quality_gate.subprocess.run", missing_tool)
    assert _status(["missing-tool"], tmp_path) == ("null", "required local tool is unavailable")


def test_status_preserves_fail_closed_result_for_undecodable_output(monkeypatch, tmp_path):
    def fake_run(command, **kwargs):
        assert command == ["probe"]
        assert kwargs["encoding"] == "utf-8"
        assert kwargs["errors"] == "replace"
        return type("Completed", (), {"returncode": 3, "stdout": None, "stderr": "bad"})()

    monkeypatch.setattr("scripts.mapper_quality_gate.subprocess.run", fake_run)
    status, detail = _status(["probe"], tmp_path)
    assert status == "fail"
    assert detail == "bad"


def test_main_writes_markdown_report(tmp_path, monkeypatch):
    monkeypatch.chdir(Path(__file__).parents[1])
    output = tmp_path / "quality.md"
    assert main(["--output", str(output), "--runtime-binary", "definitely-missing-simplicio"]) == 0
    assert output.read_text(encoding="utf-8").startswith("# Mapper quality gate")


def test_full_gate_records_each_local_check(monkeypatch):
    root = Path(__file__).parents[1]

    def fake_status(command, _root, env=None):
        assert env is None or isinstance(env, dict)
        return "pass", "observed"

    monkeypatch.setattr("scripts.mapper_quality_gate._status", fake_status)
    report, code = build_report(root, full=True)
    assert code == 0
    assert "Python tests | pass | observed" in report
    assert "Node unit tests | pass | observed" in report
    assert "Package contents | pass | observed" in report
