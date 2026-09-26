"""AGENTS.md wave-safeguards item 3: the wave dispatch path must record
per-task start/finish in the same durable journal the classic
`dispatch_operator_batch` path uses (this run's own
``operator-batch.jsonl``, `_load_prior_dispatch_records`/`_persist_attempt`),
so a resumed batch recognizes a durably-succeeded task and never
re-dispatches it -- whichever path (wave or classic serial) handles the
resume.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from simplicio_loop import runner as runner_mod


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, check=True)
    return result.stdout


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "a@b.c")
    _git(repo, "config", "user.name", "a")
    (repo / "a.txt").write_text("orig-a\n", encoding="utf-8")
    (repo / "b.txt").write_text("orig-b\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "init")
    return repo


def _seed_run_dir(repo: Path, run_id: str) -> Path:
    run_dir = repo / ".simplicio" / "loop-runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text(
        '{"schema": "simplicio.loop-manifest/v1", "repo": "%s", "run_id": "%s"}' % (repo, run_id),
        encoding="utf-8",
    )
    (run_dir / "state.json").write_text('{"phase": "executing"}', encoding="utf-8")
    return run_dir


def _items(repo: Path, run_id: str):
    return [
        {"task_index": 1, "run_id": run_id, "repo": str(repo), "task_spec": {"files_affected": ["a.txt"]}},
        {"task_index": 2, "run_id": run_id, "repo": str(repo), "task_spec": {"files_affected": ["b.txt"]}},
    ]


def _make_fake_dispatch():
    def fake(item, retry_budget, owned_process_registry=None):
        task_index = int(item["task_index"])
        repo_dir = Path(item["repo"])
        (repo_dir / ("a.txt" if task_index == 1 else "b.txt")).write_text(f"lane-{task_index}\n", encoding="utf-8")
        return [{
            "schema": "simplicio.operator-worker/v1", "task_index": task_index,
            "run_id": item["run_id"], "repo": item["repo"], "status": "succeeded",
            "execution_state": "applied", "dead_letter": False,
            "operator_receipt": "", "evidence_receipt": "",
        }]
    return fake


def test_a_fresh_wave_run_writes_succeeded_records_to_operator_batch_jsonl(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_LOOP_DISPATCH_MODE", "thread")
    repo = _init_repo(tmp_path)
    run_id = "wave-run-journal"
    run_dir = _seed_run_dir(repo, run_id)
    monkeypatch.setattr(runner_mod, "_run_operator_item_process", _make_fake_dispatch())

    result = runner_mod._wave_worktree_dispatch(
        repo_path=repo, run_id=run_id, run_dir=run_dir,
        items=_items(repo, run_id), retry_budget=0, max_workers=2,
    )
    assert result is not None
    assert result["completed_task_indices"] == [1, 2]

    journal_path = run_dir / "operator-batch.jsonl"
    assert journal_path.is_file()
    records = [json.loads(line) for line in journal_path.read_text(encoding="utf-8").splitlines()]
    by_index = {int(r["task_index"]): r for r in records}
    assert set(by_index) == {1, 2}
    assert by_index[1]["status"] == "succeeded"
    assert by_index[2]["status"] == "succeeded"
    assert by_index[1]["run_id"] == run_id
    assert by_index[1]["repo"] == str(repo)


def test_resume_with_prior_success_defers_to_serial_path_and_never_redispatches_it(tmp_path, monkeypatch):
    """Simulate a crash-recovered resume: the journal already shows task 1
    durably succeeded (from an earlier, now-finished wave attempt). The wave
    path must not re-lane-group and silently redispatch task 1 -- it must
    defer (return None) so the caller's existing classic fallback, which
    already reads this same journal file, is the one that skips it."""
    monkeypatch.setenv("SIMPLICIO_LOOP_DISPATCH_MODE", "thread")
    repo = _init_repo(tmp_path)
    run_id = "wave-run-resume"
    run_dir = _seed_run_dir(repo, run_id)
    journal_path = run_dir / "operator-batch.jsonl"
    journal_path.write_text(
        json.dumps({
            "schema": "simplicio.operator-worker/v1", "task_index": 1,
            "run_id": run_id, "repo": str(repo), "status": "succeeded",
        }) + "\n",
        encoding="utf-8",
    )

    calls: list = []

    def spy(item, retry_budget, owned_process_registry=None):
        calls.append(int(item["task_index"]))
        raise AssertionError("a durably-succeeded task must never be redispatched by the wave path")

    monkeypatch.setattr(runner_mod, "_run_operator_item_process", spy)

    result = runner_mod._wave_worktree_dispatch(
        repo_path=repo, run_id=run_id, run_dir=run_dir,
        items=_items(repo, run_id), retry_budget=0, max_workers=2,
    )

    assert result is None
    assert calls == []
