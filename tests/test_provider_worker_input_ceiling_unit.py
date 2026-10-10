"""The OpenRouter worker does not send a request above the input-token ceiling (#1608, part C)."""
from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

import pytest

from simplicio_loop import provider_worker
from simplicio_loop.input_ceiling import ENV_NAME, TOML_KEY


class _Response:
    def __enter__(self):
        body = {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps({"files": {"a.txt": "x"}})}}]}
        return BytesIO(json.dumps(body).encode("utf-8"))

    def __exit__(self, *_args):
        return False


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """The repo being worked on; the process cwd is ANOTHER directory, so a cwd fallback cannot pass by accident."""
    root = tmp_path / "repo"
    root.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.delenv(ENV_NAME, raising=False)
    return root


def _write_toml(root, body):
    (root / ".simplicio-loop").mkdir(exist_ok=True)
    (root / ".simplicio-loop" / "loop.toml").write_text(body, encoding="utf-8")


def _dispatch(opener, repo, *, goal="create the file", **env):
    environ = {"OPENROUTER_API_KEY": "runtime-only-secret", **env}
    return provider_worker.OpenRouterWorker(opener=opener).dispatch(
        task={"id": "T-1", "goal": goal}, context={"mapper_generation": "g1"}, run_id="run-1", task_index=1,
        allowed_paths=("a.txt",), env=environ, repo_root=repo)


def _counting_opener():
    calls = []

    def opener(request, *, timeout):
        calls.append(request)
        return _Response()

    return opener, calls


def test_a_prompt_under_the_ceiling_is_sent_and_labelled_estimated(repo):
    opener, calls = _counting_opener()
    result = _dispatch(opener, repo)
    assert len(calls) == 1
    budget = result["input_budget"]
    assert budget["basis"] == "ESTIMATED" and budget["ceiling"] == 98_000 and budget["status"] == "ok"


def test_a_prompt_over_the_ceiling_is_not_sent(repo):
    opener, calls = _counting_opener()
    with pytest.raises(provider_worker.ProviderWorkerError) as raised:
        _dispatch(opener, repo, goal="word " * 5000, **{ENV_NAME: "1000"})
    assert raised.value.reason_code == "input_ceiling_exceeded"
    assert calls == []


def test_the_ceiling_of_loop_toml_applies(repo):
    _write_toml(repo, "%s = 1000\n" % TOML_KEY)
    opener, calls = _counting_opener()
    with pytest.raises(provider_worker.ProviderWorkerError) as raised:
        _dispatch(opener, repo, goal="word " * 5000)
    assert raised.value.reason_code == "input_ceiling_exceeded" and calls == []


def test_a_bad_ceiling_fails_loud_without_sending(repo):
    opener, calls = _counting_opener()
    with pytest.raises(provider_worker.ProviderWorkerError) as raised:
        _dispatch(opener, repo, **{ENV_NAME: "abc"})
    assert raised.value.reason_code == "ceiling_invalid" and calls == []


def test_a_bad_loop_toml_ceiling_fails_loud_without_sending(repo):
    _write_toml(repo, '%s = "abc"\n' % TOML_KEY)
    opener, calls = _counting_opener()
    with pytest.raises(provider_worker.ProviderWorkerError) as raised:
        _dispatch(opener, repo)
    assert raised.value.reason_code == "ceiling_invalid" and calls == []


def test_the_loop_toml_of_the_cwd_is_not_the_one_read(repo):
    """A call that names its repo never reads the loop.toml of the cwd."""
    _write_toml(Path.cwd(), "%s = 1\n" % TOML_KEY)
    opener, calls = _counting_opener()
    assert _dispatch(opener, repo)["input_budget"]["ceiling"] == 98_000 and len(calls) == 1


def test_the_ceiling_boundary_refuses_only_above_it(repo):
    """tokens - 1 refuses with 0 calls; tokens and tokens + 1 send."""
    opener, calls = _counting_opener()
    tokens = _dispatch(opener, repo)["input_budget"]["tokens"]
    assert len(calls) == 1
    for ceiling, sends in ((tokens - 1, False), (tokens, True), (tokens + 1, True)):
        opener, calls = _counting_opener()
        env = {ENV_NAME: str(ceiling)}
        if sends:
            assert _dispatch(opener, repo, **env)["input_budget"]["tokens"] == tokens and len(calls) == 1
        else:
            with pytest.raises(provider_worker.ProviderWorkerError) as raised:
                _dispatch(opener, repo, **env)
            assert raised.value.reason_code == "input_ceiling_exceeded" and calls == []


def test_the_runner_plan_hands_its_repo_root_to_the_worker(repo, tmp_path, monkeypatch):
    """runner_plan._provider_worker_plan must pass repo_root=root, or the gate reads the cwd's loop.toml."""
    from simplicio_loop import runner_plan

    seen = {}

    def dispatch(self, **kwargs):
        seen.update(kwargs)
        raise provider_worker.ProviderWorkerError("stop here", reason_code="provider_stop")

    monkeypatch.setattr(provider_worker.OpenRouterWorker, "dispatch", dispatch)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    with pytest.raises(provider_worker.ProviderWorkerError):
        runner_plan._provider_worker_plan(
            task={"id": "T-1", "goal": "g"}, context={}, run_id="run-1", task_index=1, attempt=1, root=repo,
            allowed_paths=("a.txt",), run_dir=run_dir, provider_worker="openrouter")
    assert seen.get("repo_root") == repo
