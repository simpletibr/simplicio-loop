from __future__ import annotations

from types import SimpleNamespace

from simplicio import pipeline_stages as stages


def test_timeout_and_patch_candidate_edge_cases(monkeypatch, tmp_path):
    monkeypatch.setenv("SIMPLICIO_TEST_TIMEOUT_S", "not-a-number")
    assert stages._verification_timeout_seconds() is None
    monkeypatch.setenv("SIMPLICIO_TEST_TIMEOUT_S", "0")
    assert stages._verification_timeout_seconds() is None
    assert stages._extract_patch_candidate("text", str(tmp_path), None).reason.startswith("no unified")
    assert stages._extract_patch_candidate("FILE: app.py\nnew\n", str(tmp_path), ["app.py"]).strategy == "full_file_artifact"
    (tmp_path / "app.py").write_text("same\n", encoding="utf-8")
    assert stages._extract_patch_candidate("FILE: app.py\nsame\n", str(tmp_path), ["app.py"]).strategy == "full_file_noop"


def test_impact_paths_report_mapper_and_command_failures(tmp_path, monkeypatch):
    assert stages.run_impact_tests(tmp_path, [], map_ask_fn=lambda *args: None)["result"] == stages.IMPACT_RESULT_NOT_NEEDED
    no_mapper = stages.run_impact_tests(tmp_path, ["app.py"], map_ask_fn=lambda *args: None)
    assert no_mapper["status"] == "mapper_unavailable"
    no_callers = stages.run_impact_tests(tmp_path, ["app.py"], map_ask_fn=lambda *args: [])
    assert no_callers["status"] == "no_callers_found"

    def mapper(_root, verb, _path):
        return [{"caller": "src/app.py"}] if verb == "impact" else [{"test_path": "tests/test_app.py"}]

    missing = stages.run_impact_tests(tmp_path, ["app.py"], map_ask_fn=mapper)
    assert missing["status"] == "missing_test_command"
    monkeypatch.setattr(stages.subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("no process")))
    errored = stages.run_impact_tests(tmp_path, ["app.py"], test_cmd="pytest", map_ask_fn=mapper)
    assert errored["status"] == "error"


def test_impact_paths_capture_nonzero_and_success_receipts(tmp_path, monkeypatch):
    def mapper(_root, verb, _path):
        return [{"caller": "src/app.py"}] if verb == "impact" else [{"test_path": "tests/test_app.py"}]

    monkeypatch.setattr(stages.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="out", stderr="err"))
    failed = stages.run_impact_tests(tmp_path, ["app.py"], test_cmd="pytest", map_ask_fn=mapper)
    assert failed["status"] == "failed"
    monkeypatch.setattr(stages.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="ok", stderr=""))
    passed = stages.run_impact_tests(tmp_path, ["app.py"], test_cmd="pytest", map_ask_fn=mapper)
    assert passed["status"] == "ok"
    assert passed["receipt"]["exit_code"] == 0


def test_validation_and_authorization_reject_scope_and_placeholder_cases(tmp_path, monkeypatch):
    repo = str(tmp_path)
    assert stages.authorized_path_warnings(["../secret.py"], root=repo)
    assert stages.authorized_path_warnings(["app.py"], root=repo, repo_root=str(tmp_path / "other"))
    assert stages.authorized_path_warnings(["app.py"], root=repo, scope_root=str(tmp_path / "other"))
    monkeypatch.setenv("SIMPLICIO_TEST_CMD", "")
    result = stages.validate_generated_output("pseudocode", bound_paths=["app.py"], mode="strict", root=repo)
    assert result.ok is False
    assert any("placeholder" in hint for hint in result.hints)


def test_failure_classification_covers_remaining_categories():
    assert stages.classify_failure("assertionerror expected actual").kind == "assertion"
    assert stages.classify_failure("no module named x").kind == "dependency"
    assert stages.classify_failure("timed out").kind == "timeout"
    assert stages.classify_failure("traceback exception").kind == "runtime"
    assert stages.classify_failure("mystery").kind == "unknown"


def test_full_file_replacement_and_bound_drift_warnings(tmp_path):
    target = tmp_path / "app.py"
    target.write_text("1\n2\n3\n4\n5\n6\n7\n8\n9\n10\n", encoding="utf-8")
    patch = "diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1,10 +1,1 @@\n-1\n-2\n-3\n-4\n-5\n-6\n-7\n-8\n-9\n-10\n+new\n"
    assert stages._full_file_replacement_hints(patch, str(tmp_path), ["app.py"])
    baseline = stages.snapshot_bound_paths(str(tmp_path), ["app.py"])
    target.write_text("changed\n", encoding="utf-8")
    assert stages.bound_path_drift(str(tmp_path), ["app.py"], baseline)
