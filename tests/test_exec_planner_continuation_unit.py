"""Over-ceiling planner request: write a handoff and continue in a new run of the same family and role (#1608, part C).

No model is called: the planner runs fake CLIs from tests/test_exec_planner_unit.py, and the handoff writer is injected.

The default writer keeps the whole task in the handoff's objective (never a silent cut). A task that does not fit that
objective is ``needs_human`` (``handoff_would_truncate_the_task``) and no request is sent. ``checkpoint`` below stands in
for a model-written handoff, whose objective is a short summary.
"""
from __future__ import annotations

import json

import pytest

from simplicio_loop import agent_handoff, exec_planner, input_ceiling, model_roles
from tests.test_exec_planner_unit import PLAN, bindir, call_of, fake_cli, run  # noqa: F401  (bindir is a fixture)

CEILING = 2000
ENV_CEILING = input_ceiling.ENV_NAME
CHAIN_ENV = "SIMPLICIO_AGENT_CONTINUATION_CHAIN_LIMIT"
TAIL = " TAIL-MARKER"
# Fits the schema's 2000-character objective, so the default writer keeps all of it.
FITS = "HEAD-MARKER " + "word " * 380 + TAIL
# Over the 2000-character objective: the default writer cannot keep it intact.
TOO_LONG = "HEAD-MARKER " + "word " * 600 + TAIL
# A ceiling below the task, so the first request is always refused; the default handoff is then never small enough.
SMALL_CEILING = 300
SECRET = "sk-" + "A1b2C3d4E5f6G7h8I9j0K1l2"


def checkpoint(ctx):
    """A model-written stand-in: the objective is a short summary, so the continuation fits the ceiling."""
    return exec_planner.default_handoff({**ctx, "prompt": "MARKER-TASK checkpoint"})


def _padded(extra_criteria):
    """A checkpoint with ``extra_criteria`` more long criteria: a bigger handoff, the same contract."""
    def writer(ctx):
        doc = checkpoint(ctx)
        doc["acceptance_criteria"] += ["x" * 1000] * extra_criteria
        return doc
    return writer


def _recording(writer, sink):
    def record(ctx):
        sink.append(ctx)
        return writer(ctx)
    return record


def _handoffs(repo):
    return sorted((repo / ".simplicio-loop").rglob("*.json"))


def _order(bindir):
    log = bindir / "order.log"
    return log.read_text().split() if log.exists() else []


def _prompt_arg(argv):
    return next(a for a in argv if a.startswith(exec_planner.PLAN_ONLY_PREAMBLE))


def test_an_over_ceiling_prompt_writes_one_handoff_and_the_next_attempt_starts_with_it(bindir, tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_CEILING, str(CEILING))
    fake_cli(bindir, "claude")
    contexts = []
    res = run(exec_planner.run_planner_with_fallback(
        "planning", "MARKER-TASK " + "word " * 5000, cwd=str(tmp_path), families=["claude"], repo_root=tmp_path,
        handoff_writer=_recording(checkpoint, contexts), run_id="run-a"))

    assert res.is_ok() and res.plan == PLAN
    assert res.continuations == 1 and res.to_dict()["continuations"] == 1
    assert [c["continuation"] for c in contexts] == [1]
    files = _handoffs(tmp_path)
    assert files == [agent_handoff.handoff_path(tmp_path, "run-a-claude", 1)]
    stored = files[0].read_text()
    doc = json.loads(stored)
    assert doc["run_id"] == "run-a-claude" and doc["continuation"] == 1 and doc["reason"] == "input_ceiling"

    argv = call_of(bindir, "claude")["argv"]
    prompt = _prompt_arg(argv)
    # The stable prefix (planner instructions) comes first, then the handoff text.
    assert prompt.index(exec_planner.CONTINUATION_PREFIX) < prompt.index(stored.strip())
    assert "MARKER-TASK" in prompt  # the handoff carries the task
    assert input_ceiling.Projection.estimated(prompt).tokens <= CEILING


def test_the_continuation_keeps_the_same_family_and_role(bindir, tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_CEILING, str(CEILING))
    fake_cli(bindir, "claude")
    fake_cli(bindir, "codex")  # must never be reached: the chain stays on claude
    contexts = []
    res = run(exec_planner.run_planner_with_fallback(
        "planning", "MARKER-TASK " + "word " * 5000, cwd=str(tmp_path), families=["claude", "codex"], repo_root=tmp_path,
        handoff_writer=_recording(checkpoint, contexts), run_id="run-b"))

    assert res.is_ok() and res.family == "claude" and res.role == "planning"
    assert _order(bindir) == ["claude"]
    want = model_roles.resolve("claude", "planning")
    assert want["model"] in call_of(bindir, "claude")["argv"]
    assert (contexts[0]["family"], contexts[0]["role"], contexts[0]["model"]) == ("claude", "planning", want["model"])
    doc = json.loads(_handoffs(tmp_path)[0].read_text())
    assert (doc["agent"]["family"], doc["agent"]["role"]) == ("claude", "planning")


def test_the_chain_stops_after_five_continuations_with_needs_human_and_no_request(bindir, tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_CEILING, str(CEILING))
    fake_cli(bindir, "claude")
    # 4 long criteria make every handoff bigger than the ceiling (about 3k tokens) and still under the 6k limit,
    # so each attempt is refused and needs one more run.
    contexts = []
    res = run(exec_planner.run_planner_with_fallback(
        "planning", "MARKER-TASK " + "word " * 5000, cwd=str(tmp_path), families=["claude"], repo_root=tmp_path,
        handoff_writer=_recording(_padded(4), contexts), run_id="run-c"))

    assert res.reason_code == "needs_human"
    assert "continuation_chain_exhausted" in res.error
    assert res.continuations == 5
    assert [c["continuation"] for c in contexts] == [1, 2, 3, 4, 5]
    files = _handoffs(tmp_path)
    assert [f.name for f in files] == ["%d.json" % n for n in range(1, 6)]
    docs = [json.loads(f.read_text()) for f in files]
    assert {d["lease"]["owner"] for d in docs} == {"run-c"}  # one lease for the whole chain
    assert _order(bindir) == []  # no request left the process


def test_the_chain_limit_from_the_environment_stops_the_chain_with_needs_human_and_the_cause(bindir, tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_CEILING, str(CEILING))
    monkeypatch.setenv(CHAIN_ENV, "2")
    fake_cli(bindir, "claude")
    contexts = []
    res = run(exec_planner.run_planner_with_fallback(
        "planning", "MARKER-TASK " + "word " * 5000, cwd=str(tmp_path), families=["claude"], repo_root=tmp_path,
        handoff_writer=_recording(_padded(4), contexts), run_id="run-j"))

    assert res.reason_code == "needs_human"
    assert "continuation_chain_exhausted" in res.error and "chain limit is 2" in res.error
    assert res.continuations == 2
    assert [c["continuation"] for c in contexts] == [1, 2]
    assert [f.name for f in _handoffs(tmp_path)] == ["1.json", "2.json"]
    assert _order(bindir) == []


def test_an_invalid_chain_limit_fails_loud_before_a_handoff_is_written_or_a_request_is_sent(bindir, tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_CEILING, str(CEILING))
    monkeypatch.setenv(CHAIN_ENV, "0")
    fake_cli(bindir, "claude")
    with pytest.raises(input_ceiling.CeilingConfigError, match=CHAIN_ENV):
        run(exec_planner.run_planner_with_fallback(
            "planning", "MARKER-TASK " + "word " * 5000, cwd=str(tmp_path), families=["claude"], repo_root=tmp_path,
            handoff_writer=_padded(4), run_id="run-k"))
    assert _handoffs(tmp_path) == []
    assert _order(bindir) == []


def test_a_handoff_above_the_token_limit_is_refused_with_its_reason(bindir, tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_CEILING, str(CEILING))
    fake_cli(bindir, "claude")
    res = run(exec_planner.run_planner_with_fallback(
        "planning", "MARKER-TASK " + "word " * 5000, cwd=str(tmp_path), families=["claude"], repo_root=tmp_path,
        handoff_writer=_padded(49), run_id="run-d"))

    assert res.reason_code == "needs_human"
    assert "handoff_too_large" in res.error
    assert _handoffs(tmp_path) == []
    assert _order(bindir) == []


def test_a_prompt_under_the_ceiling_writes_no_handoff(bindir, tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_CEILING, str(CEILING))
    fake_cli(bindir, "claude")
    res = run(exec_planner.run_planner_with_fallback(
        "planning", "small task", cwd=str(tmp_path), families=["claude"], repo_root=tmp_path, run_id="run-e"))
    assert res.is_ok() and res.continuations == 0
    assert _handoffs(tmp_path) == []


# --- the task is kept whole, for the whole chain (no silent cut, no lost objective) --------------------------------------

def test_a_task_that_fits_the_objective_is_kept_whole_with_its_tail_in_every_handoff_of_the_chain(bindir, tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_CEILING, str(SMALL_CEILING))
    fake_cli(bindir, "claude")
    contexts = []
    res = run(exec_planner.run_planner_with_fallback(
        "planning", FITS, cwd=str(tmp_path), families=["claude"], repo_root=tmp_path,
        handoff_writer=_recording(exec_planner.default_handoff, contexts), run_id="run-f"))

    # Three generations at least: every handoff of the chain carries the original task, not the previous handoff.
    assert res.reason_code == "needs_human" and "continuation_chain_exhausted" in res.error
    assert res.continuations == 5
    assert [c["prompt"] for c in contexts] == [FITS] * 5
    docs = [json.loads(f.read_text()) for f in _handoffs(tmp_path)]
    assert len(docs) == 5
    for doc in docs:
        assert doc["objective"] == FITS and doc["objective"].endswith(TAIL)
    assert _order(bindir) == []


def test_a_task_over_the_objective_limit_is_needs_human_and_no_request_is_sent(bindir, tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_CEILING, str(SMALL_CEILING))
    fake_cli(bindir, "claude")
    res = run(exec_planner.run_planner_with_fallback(
        "planning", TOO_LONG, cwd=str(tmp_path), families=["claude"], repo_root=tmp_path, run_id="run-g"))

    assert res.reason_code == "needs_human"
    assert res.error.startswith("handoff_would_truncate_the_task")
    assert res.continuations == 0
    assert _handoffs(tmp_path) == []
    assert _order(bindir) == []


def test_a_needs_human_on_the_first_family_stops_the_fallback_before_the_next_family(bindir, tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_CEILING, str(CEILING))
    fake_cli(bindir, "claude")
    fake_cli(bindir, "codex")  # would answer if reached: the stop list must keep it from running
    contexts = []

    def writer(ctx):
        # The big task fits no default objective on claude; codex gets a model-style checkpoint, so it would succeed.
        if ctx["family"] == "claude":
            return exec_planner.default_handoff(ctx)
        contexts.append(ctx)
        return checkpoint(ctx)

    res = run(exec_planner.run_planner_with_fallback(
        "planning", "MARKER-TASK " + "word " * 5000, cwd=str(tmp_path), families=["claude", "codex"], repo_root=tmp_path,
        handoff_writer=writer, run_id="run-h"))

    assert res.reason_code == "needs_human" and res.family == "claude"
    assert "handoff_would_truncate_the_task" in res.error
    assert _order(bindir) == []
    assert contexts == []  # codex never started a chain


def test_a_secret_in_an_over_ceiling_task_is_redacted_in_the_handoff_the_planner_writes(bindir, tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_CEILING, str(SMALL_CEILING))
    fake_cli(bindir, "claude")
    task = "deploy with key " + SECRET + " " + "word " * 300 + TAIL
    res = run(exec_planner.run_planner_with_fallback(
        "planning", task, cwd=str(tmp_path), families=["claude"], repo_root=tmp_path, run_id="run-i"))

    assert res.reason_code == "needs_human"
    files = _handoffs(tmp_path)
    assert files, "the first handoff must be written"
    stored = files[0].read_text()
    assert SECRET not in stored
    doc = json.loads(stored)
    assert "[REDACTED_SECRET]" in doc["objective"] and doc["objective"].endswith(TAIL)
    assert _order(bindir) == []
