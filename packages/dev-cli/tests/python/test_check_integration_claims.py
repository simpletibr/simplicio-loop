"""#167 — "Claim de integração exige E2E": a commit/PR claiming a Runtime/
Agent integration is complete must be backed by an E2E test file in the same
diff. This exercises `scripts/check_integration_claims.py`, the heuristic
local guard for that AC (mirrors the `--check` drift-gate pattern used by
`scripts/gen_package_interdependence.py`)."""

from __future__ import annotations

from scripts.check_integration_claims import check, is_integration_claim, main, touches_e2e_evidence


def test_is_integration_claim_requires_all_three_keyword_groups():
    assert is_integration_claim("Runtime integration complete") is True
    assert is_integration_claim("Agent integração funcional finalizada") is True
    # missing completion word
    assert is_integration_claim("Runtime integration in progress") is False
    # missing subject word
    assert is_integration_claim("integration complete") is False
    # missing integration word
    assert is_integration_claim("Runtime is done") is False


def test_touches_e2e_evidence_matches_repo_convention():
    assert touches_e2e_evidence(["tests/contracts/test_end_to_end_flow.py"]) is True
    assert touches_e2e_evidence(["tests/python/test_mapper_handoff_integration.py"]) is True
    assert touches_e2e_evidence(["tests/python/test_plan_compiler_golden_e2e.py"]) is True
    assert touches_e2e_evidence(["simplicio/pipeline.py"]) is False
    assert touches_e2e_evidence(["tests/python/test_pipeline.py"]) is False


def test_check_blocks_integration_claim_without_e2e_evidence():
    ok, reason = check(
        "feat(runtime): Runtime integration with Agent is complete and functional",
        ["simplicio/runtime_bridge.py"],
    )

    assert ok is False
    assert "no E2E test file changed" in reason


def test_check_passes_integration_claim_with_e2e_evidence():
    ok, reason = check(
        "feat(runtime): Runtime integration with Agent is complete",
        ["simplicio/runtime_bridge.py", "tests/contracts/test_end_to_end_flow.py"],
    )

    assert ok is True
    assert "E2E" in reason


def test_check_passes_when_no_integration_claim_present():
    ok, reason = check("fix: tweak logging format", ["simplicio/observability.py"])

    assert ok is True
    assert "no Runtime/Agent integration claim" in reason


def test_main_exits_nonzero_for_unbacked_integration_claim(tmp_path, capsys):
    msg_file = tmp_path / "msg.txt"
    msg_file.write_text("Runtime integration with Agent is now complete and functional", encoding="utf-8")

    code = main(["--message-file", str(msg_file), "--files", "simplicio/runtime_bridge.py"])

    assert code == 1
    assert "BLOCKED" in capsys.readouterr().err


def test_main_exits_zero_when_e2e_file_is_in_the_diff(tmp_path, capsys):
    msg_file = tmp_path / "msg.txt"
    msg_file.write_text("Runtime integration with Agent is now complete", encoding="utf-8")

    code = main(
        [
            "--message-file",
            str(msg_file),
            "--files",
            "simplicio/runtime_bridge.py",
            "tests/contracts/test_end_to_end_flow.py",
        ]
    )

    assert code == 0
    assert "OK" in capsys.readouterr().out


def test_main_reads_changed_files_from_files_file(tmp_path):
    files_file = tmp_path / "files.txt"
    files_file.write_text("simplicio/runtime_bridge.py\ntests/python/test_mapper_handoff_integration.py\n")

    code = main(["--message", "Runtime integration complete", "--files-file", str(files_file)])

    assert code == 0


def test_main_defaults_to_no_changed_files_when_neither_flag_given():
    code = main(["--message", "Runtime integration complete and functional"])

    assert code == 1
