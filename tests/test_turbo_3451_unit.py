"""3.45.1: kept-alive connection, hedged request, one-task map slice, repair with test output (the warm-up call is gone in 3.47.0)."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest

from simplicio_loop import turbo_provider
from simplicio_loop.cli_impl import main as cli_main
from simplicio_loop.turbo import focus_paths, mapper_reading, run_turbo

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "bench" / "llm_ab" / "fixture_hard"
SOLUTION = ROOT / "tests" / "fixtures" / "llm_ab_hard_solution"
HIDDEN = ROOT / "bench" / "llm_ab" / "hidden" / "check_hard.py"


def _reply(content="{}", provider="Together"):
    return {"provider": provider, "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 2, "cost": 0.0001,
                      "prompt_tokens_details": {"cached_tokens": 8}, "completion_tokens_details": {"reasoning_tokens": 0}}}


@pytest.fixture
def mock_client(monkeypatch):
    """Route the provider's pooled client through an httpx.MockTransport."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    state = {"handler": lambda request: httpx.Response(200, json=_reply()), "seen": []}

    def handler(request):
        state["seen"].append({"headers": dict(request.headers), "body": json.loads(request.content)})
        return state["handler"](request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(turbo_provider, "_http_client", lambda: client)
    turbo_provider.drain_hedges(timeout=0)
    return state


def test_every_call_reuses_one_pooled_client(monkeypatch):
    monkeypatch.setattr(turbo_provider, "_client", None)
    assert turbo_provider._http_client() is turbo_provider._http_client()


def test_provider_sends_the_benchmarked_request(mock_client):
    reply = turbo_provider.complete("simplicio", [{"role": "user", "content": "x"}], session_id="s-1", hedge=0)
    seen = mock_client["seen"][0]
    assert seen["headers"]["authorization"] == "Bearer sk-test" and seen["headers"]["x-session-id"] == "s-1"
    assert seen["body"]["model"] == "deepseek/deepseek-v4.1-flash"
    assert seen["body"]["reasoning"] == {"enabled": False} and seen["body"]["temperature"] == 0
    assert reply["ok"] and reply["provider"] == "Together" and reply["hedged"] is False


def test_provider_model_override_and_reasoning_toggle(mock_client, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_TURBO_MODEL", "other/model")
    turbo_provider.complete("simplicio", [], session_id="s", reasoning_off=False, hedge=0)
    body = mock_client["seen"][0]["body"]
    assert body["model"] == "other/model" and "reasoning" not in body


def test_provider_fails_closed_without_a_key(mock_client, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY")
    with pytest.raises(turbo_provider.TurboProviderError) as err:
        turbo_provider.complete("simplicio", [], session_id="s")
    assert err.value.reason_code == "turbo_provider_key_missing" and mock_client["seen"] == []


def test_a_fast_call_is_never_hedged(mock_client):
    turbo_provider.complete("simplicio", [], session_id="s", hedge=1.0)
    assert len(mock_client["seen"]) == 1


def test_a_slow_call_is_hedged_on_another_session_and_the_loser_is_billed(mock_client):
    def handler(request):
        if request.headers["x-session-id"] == "s":  # the pinned provider is stuck
            time.sleep(0.6)
            return httpx.Response(200, json=_reply('{"slow":1}', "Slow"))
        return httpx.Response(200, json=_reply('{"fast":1}', "Fast"))

    mock_client["handler"] = handler
    started = time.time()
    reply = turbo_provider.complete("simplicio", [], session_id="s", hedge=0.1)
    assert time.time() - started < 0.5
    assert reply["hedged"] is True and reply["hedge_winner"] == "duplicate" and reply["provider"] == "Fast"
    assert [s["headers"]["x-session-id"] for s in mock_client["seen"]][-1] == "s-hedge"
    losers = turbo_provider.drain_hedges(timeout=5)
    assert len(losers) == 1 and losers[0]["provider"] == "Slow" and losers[0]["hedge_loser"] is True


def test_a_failed_first_answer_waits_for_the_other(mock_client):
    def handler(request):
        if request.headers["x-session-id"].endswith("-hedge"):
            return httpx.Response(500, text="boom")
        time.sleep(0.3)
        return httpx.Response(200, json=_reply('{"ok":1}', "Primary"))

    mock_client["handler"] = handler
    reply = turbo_provider.complete("simplicio", [], session_id="s", hedge=0.05)
    assert reply["ok"] and reply["provider"] == "Primary" and reply["hedge_winner"] == "primary"
    assert turbo_provider.drain_hedges(timeout=1) == []


def test_max_tokens_reaches_the_request(mock_client):
    turbo_provider.complete("simplicio", [], session_id="s", hedge=0, max_tokens=1)
    assert mock_client["seen"][0]["body"]["max_tokens"] == 1


def _seed(tmp_path):
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE, repo)
    for args in (["init", "-q"], ["config", "user.email", "a@b.c"], ["config", "user.name", "a"],
                 ["add", "-A"], ["commit", "-qm", "seed"]):
        subprocess.run(["git", *args], cwd=repo, check=True)
    return repo


def _map(repo):
    state = repo / ".simplicio-loop"
    state.mkdir(exist_ok=True)
    project = {"schema": "simplicio.project-map/v1", "product": "shop-utils",
               "files": [{"path": "inventory.py", "symbols": ["Inventory"]},
                         {"path": "shop/report.py", "symbols": ["summary"]},
                         {"path": "shop/invoice.py", "symbols": ["invoice_total"]}],
               "architecture": {"notes": "x" * 2000}}
    (state / "project-map.json").write_text(json.dumps(project), encoding="utf-8")


def test_a_single_task_sends_only_its_slice_of_the_map(tmp_path):
    repo = _seed(tmp_path)
    _map(repo)
    full = mapper_reading(repo)
    sliced = json.loads(mapper_reading(repo, focus=["inventory.py"]))
    assert [f["path"] for f in sliced["files"]] == ["inventory.py"]
    assert "architecture" not in sliced and len(json.dumps(sliced)) < len(full) / 3
    assert focus_paths([{"target": "shop/money.py", "context": ["shop/report.py"]}]) == ["shop/money.py", "shop/report.py"]


def test_independent_tasks_fan_out_at_once_with_no_warm_up_call(tmp_path, monkeypatch):
    repo = _seed(tmp_path)
    monkeypatch.setattr("simplicio_loop.cli_impl._ensure_project_map", lambda root: None)
    _map(repo)
    seen, lock = [], threading.Lock()

    def complete(arm, messages, **kwargs):
        with lock:
            seen.append(([dict(m) for m in messages], dict(kwargs)))
        name = messages[-1]["content"].split("Tasks:", 1)[1].strip().split(".", 1)[0].strip()
        return {"ok": True, "content": json.dumps({"operations": [{"path": f"p{name}.txt", "find": "", "replace": name}]})}

    tasks = [{"index": i, "text": f"Create p{i}.txt", "target": f"p{i}.txt", "depends_on": []} for i in range(1, 5)]
    result = run_turbo(repo, tasks, complete)
    assert len(seen) == 4 and all(kwargs == {} for _, kwargs in seen)  # no 1-token warm-up
    assert all(len(msgs) == 2 and msgs[0]["role"] == "system" for msgs, _ in seen)  # header + task: no first-task prefix
    assert result["applied_all"] is True and not any("warm" in call for call in result["llm_calls"])
    assert all((repo / f"p{i}.txt").read_text() == str(i) for i in range(1, 5))


def test_cli_repairs_once_with_the_test_output(tmp_path, monkeypatch, capsys):
    repo = _seed(tmp_path)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    turns = []
    good = (SOLUTION / "inventory.py").read_text(encoding="utf-8")
    bad = good.replace("if qty <= available:", "if qty < available:")  # the off-by-one survives

    def fake_complete(arm, messages, **kwargs):
        turns.append(messages[-1]["content"])
        current = (repo / "inventory.py").read_text(encoding="utf-8")
        fixed = bad if len(turns) == 1 else good
        return {"ok": True, "content": json.dumps({"operations": [{"path": "inventory.py", "find": current, "replace": fixed}]}),
                "prompt_tokens": 100, "cached_tokens": 80, "completion_tokens": 40, "cost": 0.0001}

    monkeypatch.setattr(turbo_provider, "complete", fake_complete)
    verify = f'"{sys.executable}" "{HIDDEN}" --stage 2'
    rc = cli_main(["turbo", "--provider", "openrouter", "--repo", str(repo),
                   "--task", "Fix the two bugs in inventory.py.", "--verify", verify])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0, out
    assert out["verify_retry"] == {"attempted": True, "applied": True, "reason": None, "passed": True}
    assert out["verify"]["passed"] is True and out["model_calls"] == 2
    assert "The tests failed after your plan was applied" in turns[1] and "FAIL:" in turns[1]


# `simplicio-loop "<task>"` runs the task: a first argument that is not a subcommand is prose.

def test_plain_prose_runs_host_mode(monkeypatch):
    seen = {}
    monkeypatch.setattr("simplicio_loop.turbo_cli.run", lambda repo, texts, **kw: seen.update(repo=repo, texts=list(texts), **kw) or 0)
    assert cli_main(["adicione um campo telefone no cadastro.html", "--verify", "pytest -q"]) == 0
    assert seen["repo"] == "." and seen["texts"] == ["adicione um campo telefone no cadastro.html"]
    assert seen["verify"] == "pytest -q" and not seen.get("apply") and not seen.get("provider")


def test_plain_prose_split_over_several_words_is_one_task_and_keeps_later_flags(monkeypatch):
    seen = {}
    monkeypatch.setattr("simplicio_loop.turbo_cli.run", lambda repo, texts, **kw: seen.update(repo=repo, texts=list(texts), **kw) or 0)
    assert cli_main(["add", "a", "phone", "field", "to", "form.html", "--repo", "/tmp/x"]) == 0
    assert seen["texts"] == ["add a phone field to form.html"] and seen["repo"] == "/tmp/x"


def test_a_drain_request_still_goes_to_the_drain_intake(monkeypatch):
    called = {}
    monkeypatch.setattr("simplicio_loop.turbo_cli.run", lambda *a, **k: pytest.fail("prose default took a drain request"))
    monkeypatch.setattr("simplicio_loop.github_drain_intake_cli.main", lambda argv: called.update(argv=list(argv)) or 0)
    assert cli_main(["resolva todas as issues"]) == 0
    assert called["argv"] == ["resolva todas as issues"]


def test_bare_invocation_keeps_its_behavior(monkeypatch):
    monkeypatch.setattr("simplicio_loop.turbo_cli.run", lambda *a, **k: pytest.fail("bare call must not run a task"))
    with pytest.raises(SystemExit) as exc:
        cli_main(["--version"])
    assert exc.value.code == 0
