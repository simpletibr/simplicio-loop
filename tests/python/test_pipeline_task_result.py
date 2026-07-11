"""_task_result's cost_usd/cost_basis contract (issue #88 AC4).

cost_usd used to be hardcoded to 0.0 unconditionally. It is now computed
from the same pricing helper the cost governor charges against, and
`cost_basis` always says whether that number came from configured pricing
("estimated") or is genuinely unknown ("unknown_no_pricing_configured") —
never a silently fake real cost.

Issue #93 adds impact-test verification — tests here cover the impact block
in _task_result and the _run_impact_tests helper.
"""

from __future__ import annotations

from simplicio.pipeline import (
    IMPACT_RESULT_FAILED,
    IMPACT_RESULT_NOT_NEEDED,
    IMPACT_RESULT_PASSED,
    IMPACT_RESULT_UNVERIFIED,
    _run_impact_tests,
    _task_result,
)
from simplicio.prompt_envelope import PromptEnvelope

# ---------------------------------------------------------------------------
# _task_result — impact block
# ---------------------------------------------------------------------------


def test_task_result_omits_impact_when_not_provided(monkeypatch):
    monkeypatch.delenv("SIMPLICIO_PRICE_PER_MTOK", raising=False)
    monkeypatch.delenv("SIMPLICIO_PRICE_PROMPT_PER_MTOK", raising=False)
    monkeypatch.delenv("SIMPLICIO_PRICE_COMPLETION_PER_MTOK", raising=False)

    result = _task_result("t1", "a prompt", "diff --git a/x b/x\n--- a/x\n+++ b/x\n", applied=True)

    assert "impact" not in result


def test_task_result_impact_passed(monkeypatch):
    monkeypatch.delenv("SIMPLICIO_PRICE_PER_MTOK", raising=False)

    result = _task_result(
        "t1",
        "a prompt",
        "diff --git a/x b/x\n--- a/x\n+++ b/x\n",
        applied=True,
        impact={
            "callers": ["caller.py"],
            "tests_run": ["tests/test_caller.py"],
            "result": IMPACT_RESULT_PASSED,
            "status": "ok",
        },
    )

    assert "impact" in result
    assert result["impact"]["callers"] == ["caller.py"]
    assert result["impact"]["tests_run"] == ["tests/test_caller.py"]
    assert result["impact"]["result"] == IMPACT_RESULT_PASSED


def test_task_result_impact_failed(monkeypatch):
    monkeypatch.delenv("SIMPLICIO_PRICE_PER_MTOK", raising=False)

    result = _task_result(
        "t1",
        "a prompt",
        "diff --git a/x b/x\n--- a/x\n+++ b/x\n",
        applied=True,
        impact={
            "callers": ["caller.py"],
            "tests_run": ["tests/test_caller.py"],
            "result": IMPACT_RESULT_FAILED,
            "status": "failed",
        },
    )

    assert result["impact"]["result"] == IMPACT_RESULT_FAILED
    assert result["impact"]["status"] == "failed"


def test_task_result_includes_structured_primary_verify_receipt(monkeypatch):
    monkeypatch.delenv("SIMPLICIO_PRICE_PER_MTOK", raising=False)

    result = _task_result(
        "t1",
        "a prompt",
        "diff --git a/x b/x\n--- a/x\n+++ b/x\n",
        applied=True,
        verify={
            "transaction_id": "tx-1",
            "base_sha": "base",
            "candidate_sha": "candidate",
            "receipt_digest": "digest",
            "commands": ["pytest -q"],
            "exit_codes": [0],
            "stdout_tail": "1 passed",
            "stderr_tail": "",
            "files": [{"path": "src/app.py"}],
        },
    )

    assert result["verify"]["status"] == "verified"
    assert result["verify"]["receipt"]["command"] == "pytest -q"
    assert result["verify"]["receipt"]["exit_code"] == 0
    assert result["verify"]["receipt"]["receipt_digest"] == "digest"
    assert result["verify"]["receipt"]["files"] == [{"path": "src/app.py"}]


def test_task_result_marks_failed_primary_verify_receipt(monkeypatch):
    monkeypatch.delenv("SIMPLICIO_PRICE_PER_MTOK", raising=False)

    result = _task_result(
        "t1",
        "a prompt",
        "diff --git a/x b/x\n--- a/x\n+++ b/x\n",
        applied=False,
        verify={
            "transaction_id": "tx-2",
            "base_sha": "base",
            "candidate_sha": "candidate",
            "receipt_digest": "digest-2",
            "commands": ["pytest -q"],
            "exit_codes": [1],
            "stdout_tail": "",
            "stderr_tail": "AssertionError: boom",
            "files": [{"path": "src/app.py"}],
        },
    )

    assert result["verify"]["status"] == "failed"
    assert result["verify"]["receipt"]["stderr_tail"] == "AssertionError: boom"


def test_task_result_includes_prompt_envelope_receipt(monkeypatch):
    monkeypatch.delenv("SIMPLICIO_PRICE_PER_MTOK", raising=False)

    envelope = PromptEnvelope.from_layers({"goal": "fix bug", "target": "src/app.py"}, template_version="v1")
    result = _task_result(
        "t1",
        "a prompt",
        "diff --git a/x b/x\n--- a/x\n+++ b/x\n",
        applied=True,
        prompt_envelope=envelope,
    )

    assert result["prompt_envelope"]["schema"] == "simplicio.prompt-envelope/v1"
    assert result["prompt_envelope"]["prefix_hash"] == envelope.prefix_hash


def test_task_result_impact_includes_structured_receipt(monkeypatch):
    monkeypatch.delenv("SIMPLICIO_PRICE_PER_MTOK", raising=False)

    result = _task_result(
        "t1",
        "a prompt",
        "diff --git a/x b/x\n--- a/x\n+++ b/x\n",
        applied=True,
        impact={
            "callers": ["caller.py"],
            "tests_run": ["tests/test_caller.py"],
            "result": IMPACT_RESULT_FAILED,
            "status": "failed",
            "command": "pytest tests/test_caller.py",
            "returncode": 1,
            "output_tail": "AssertionError: boom",
        },
    )

    assert result["impact"]["receipt"]["command"] == "pytest tests/test_caller.py"
    assert result["impact"]["receipt"]["exit_code"] == 1
    assert "boom" in result["impact"]["receipt"]["output_tail"]


def test_task_result_impact_unverified(monkeypatch):
    monkeypatch.delenv("SIMPLICIO_PRICE_PER_MTOK", raising=False)

    result = _task_result(
        "t1",
        "a prompt",
        "diff --git a/x b/x\n--- a/x\n+++ b/x\n",
        applied=True,
        impact={
            "callers": [],
            "tests_run": [],
            "result": IMPACT_RESULT_UNVERIFIED,
            "status": "unverified",
        },
    )

    assert result["impact"]["result"] == IMPACT_RESULT_UNVERIFIED
    assert result["impact"]["status"] == "unverified"


def test_task_result_impact_not_needed(monkeypatch):
    monkeypatch.delenv("SIMPLICIO_PRICE_PER_MTOK", raising=False)

    result = _task_result(
        "t1",
        "a prompt",
        "diff --git a/x b/x\n--- a/x\n+++ b/x\n",
        applied=True,
        impact={
            "callers": [],
            "tests_run": [],
            "result": IMPACT_RESULT_NOT_NEEDED,
            "status": "no_callers_found",
        },
    )

    assert result["impact"]["result"] == IMPACT_RESULT_NOT_NEEDED


# ---------------------------------------------------------------------------
# _run_impact_tests — blast-radius test discovery and execution
# ---------------------------------------------------------------------------


def test_run_impact_tests_no_files():
    result = _run_impact_tests("/tmp", [])
    assert result["result"] == IMPACT_RESULT_NOT_NEEDED


def test_run_impact_tests_no_changed_files():
    result = _run_impact_tests("/tmp", [])
    assert result["result"] == IMPACT_RESULT_NOT_NEEDED
    assert result["status"] == "no_changed_files"


def test_run_impact_tests_mapper_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr("simplicio.pipeline.map_ask", lambda *a, **k: None)

    result = _run_impact_tests(tmp_path, ["src/lib.py"])

    assert result["result"] == IMPACT_RESULT_UNVERIFIED
    assert result["status"] == "mapper_unavailable"


def test_run_impact_tests_mapper_returns_no_callers(tmp_path, monkeypatch):
    monkeypatch.setattr("simplicio.pipeline.map_ask", lambda *a, **k: [])

    result = _run_impact_tests(tmp_path, ["src/lib.py"])

    assert result["result"] == IMPACT_RESULT_NOT_NEEDED


def test_run_impact_tests_finds_callers_but_no_tests(tmp_path, monkeypatch):
    def fake_map_ask(root, verb, arg=""):
        if verb == "impact":
            return [{"caller": "src/caller.py", "symbol": "some_func"}]
        return None

    monkeypatch.setattr("simplicio.pipeline.map_ask", fake_map_ask)

    result = _run_impact_tests(tmp_path, ["src/lib.py"])

    assert result["result"] == IMPACT_RESULT_UNVERIFIED
    assert result["callers"] == ["src/caller.py"]
    assert result["tests_run"] == []


def test_run_impact_tests_runs_discovered_tests(tmp_path, monkeypatch):
    """Verify _run_impact_tests finds callers + tests and runs the tests."""

    # Create a real test file so subprocess has something to run
    test_file = tmp_path / "tests" / "test_caller.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text(
        "def test_ok():\n    assert 1 + 1 == 2\n",
        encoding="utf-8",
    )

    def fake_map_ask(root, verb, arg=""):
        if verb == "impact":
            return [{"caller": "src/caller.py", "symbol": "some_func"}]
        if verb == "tests-for":
            return [{"test_path": str(test_file)}]
        return None

    monkeypatch.setattr("simplicio.pipeline.map_ask", fake_map_ask)
    monkeypatch.setenv("SIMPLICIO_TEST_CMD", "pytest")

    result = _run_impact_tests(tmp_path, ["src/lib.py"])

    assert result["result"] == IMPACT_RESULT_PASSED
    assert result["callers"] == ["src/caller.py"]
    assert str(test_file) in result["tests_run"]
    assert result["command"] == "pytest"


def test_run_impact_tests_reports_failure(tmp_path, monkeypatch):
    """Verify impact test failure is reported back correctly."""

    test_file = tmp_path / "tests" / "test_fail.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text(
        "def test_fail():\n    assert 1 + 1 == 3\n",
        encoding="utf-8",
    )

    def fake_map_ask(root, verb, arg=""):
        if verb == "impact":
            return [{"caller": "src/caller.py", "symbol": "some_func"}]
        if verb == "tests-for":
            return [{"test_path": str(test_file)}]
        return None

    monkeypatch.setattr("simplicio.pipeline.map_ask", fake_map_ask)
    monkeypatch.setenv("SIMPLICIO_TEST_CMD", "pytest")

    result = _run_impact_tests(tmp_path, ["src/lib.py"])

    assert result["result"] == IMPACT_RESULT_FAILED
    assert result["status"] == "failed"
    assert result["returncode"] != 0


def test_run_impact_tests_respects_custom_test_cmd(tmp_path, monkeypatch):
    def fake_map_ask(root, verb, arg=""):
        if verb == "impact":
            return [{"caller": "src/caller.py", "symbol": "some_func"}]
        if verb == "tests-for":
            return [{"test_path": "tests/test_caller.py"}]
        return None

    monkeypatch.setattr("simplicio.pipeline.map_ask", fake_map_ask)

    # Custom test command that always passes — "true" on macOS/Linux
    # ignores appended test-file args and exits 0.
    result = _run_impact_tests(tmp_path, ["src/lib.py"], test_cmd="true")

    assert result["result"] == IMPACT_RESULT_PASSED


def test_run_impact_tests_handles_subprocess_error(tmp_path, monkeypatch):
    def fake_map_ask(root, verb, arg=""):
        if verb == "impact":
            return [{"caller": "src/caller.py", "symbol": "some_func"}]
        if verb == "tests-for":
            return [{"test_path": "tests/test_caller.py"}]
        return None

    monkeypatch.setattr("simplicio.pipeline.map_ask", fake_map_ask)

    # A non-existent binary run via shell returns exit 127, not an OSError
    result = _run_impact_tests(tmp_path, ["src/lib.py"], test_cmd="/nonexistent/binary")

    # Shell returns non-zero for missing binary
    assert result["result"] == IMPACT_RESULT_FAILED
    assert result["status"] == "failed"
