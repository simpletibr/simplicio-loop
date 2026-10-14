"""The OpenRouter worker records the counts of each provider request in the run's execution report (#1608).

Only integers the provider reported are recorded; an absent count is None, and a request that was answered is recorded
even when its proposal is refused afterwards (the provider billed it).
"""
from __future__ import annotations

import json
from io import BytesIO

import pytest

from simplicio_loop import execution_report, provider_worker
from simplicio_loop.input_ceiling import ENV_NAME


class _Reply:
    def __init__(self, body):
        self._raw = json.dumps(body).encode("utf-8")

    def __enter__(self):
        return BytesIO(self._raw)

    def __exit__(self, *_args):
        return False


def _body(content=None, usage=None):
    if content is None:
        content = json.dumps({"files": {"a.txt": "x"}})
    body = {"choices": [{"finish_reason": "stop", "message": {"content": content}}]}
    if usage is not None:
        body["usage"] = usage
    return body


@pytest.fixture
def repo(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.delenv(ENV_NAME, raising=False)
    return root


def _dispatch(repo_root, body, task_index=1):
    worker = provider_worker.OpenRouterWorker(opener=lambda request, *, timeout: _Reply(body))
    return worker.dispatch(
        task={"id": "T-1", "goal": "create the file"}, context={"mapper_generation": "g1"}, run_id="run-1",
        task_index=task_index, allowed_paths=("a.txt",), env={"OPENROUTER_API_KEY": "runtime-only-secret"},
        repo_root=repo_root)


def _tasks(repo):
    report = execution_report.load_latest(repo)
    return [] if report is None else report["tasks"]


def test_the_reported_counts_of_a_request_reach_the_run_report(repo):
    usage = {"prompt_tokens": 1000, "completion_tokens": 50,
             "prompt_tokens_details": {"cached_tokens": 600, "cache_write_tokens": 100}}
    _dispatch(repo, _body(usage=usage))
    [task] = _tasks(repo)
    assert task["task_id"] == "run-1-1"
    tokens = task["tokens"]
    assert (tokens["tokens_in"], tokens["tokens_cached"], tokens["tokens_cache_write"], tokens["tokens_out"]) == (300, 600, 100, 50)
    assert tokens["source"] == "cli_measured"


def test_a_request_without_cache_counts_records_them_as_none(repo):
    _dispatch(repo, _body(usage={"prompt_tokens": 1000, "completion_tokens": 50}))
    [task] = _tasks(repo)
    assert task["tokens"]["tokens_in"] is None and task["tokens"]["tokens_cached"] is None
    assert task["tokens"]["tokens_cache_write"] is None and task["tokens"]["tokens_out"] == 50


def test_a_reply_without_usage_records_the_request_with_none_counters(repo):
    _dispatch(repo, _body())
    [task] = _tasks(repo)
    assert task["tokens"]["tokens_in"] is None and task["tokens"]["tokens_cached"] is None
    assert task["tokens"]["source"] == "absent"


def test_a_refused_proposal_is_still_recorded_because_the_provider_billed_it(repo):
    usage = {"prompt_tokens": 1000, "completion_tokens": 5,
             "prompt_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0}}
    with pytest.raises(provider_worker.ProviderWorkerError):
        _dispatch(repo, _body(content="not json", usage=usage))
    [task] = _tasks(repo)
    assert task["tokens"]["tokens_in"] == 1000 and task["tokens"]["tokens_cached"] == 0


def test_each_request_is_one_more_task_in_the_report(repo):
    usage = {"prompt_tokens": 10, "completion_tokens": 1, "prompt_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0}}
    _dispatch(repo, _body(usage=usage), task_index=1)
    _dispatch(repo, _body(usage=usage), task_index=2)
    assert [t["task_id"] for t in _tasks(repo)] == ["run-1-1", "run-1-2"]


def test_without_a_repo_root_no_report_is_written(repo, tmp_path):
    usage = {"prompt_tokens": 10, "completion_tokens": 1, "prompt_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0}}
    _dispatch(None, _body(usage=usage))
    assert not (tmp_path / "elsewhere" / ".simplicio-loop").exists()
    assert not (repo / ".simplicio-loop").exists()
