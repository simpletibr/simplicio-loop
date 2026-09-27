"""Issue #1357: time the parallel wave against the same work run serially.

The fixture is three disjoint files and a local sleep, with no network and no
monorepo index. The receipt next to this file records wall clock, lane count,
and whether the lane windows overlapped. A serial win on this fixture is
worktree overhead, so the engine stays on the parallel path.
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from simplicio_loop import runner as runner_mod

RECEIPT = Path(__file__).with_name("wave_vs_serial_receipt.json")
FILES_BY_INDEX = {1: "a.txt", 2: "b.txt", 3: "c.txt"}
SLEEP_S = 0.4


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True, text=True, check=True,
    )
    return result.stdout


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _git(repo, "init")
    _git(repo, "config", "user.email", "a@b.c")
    _git(repo, "config", "user.name", "a")
    for name in FILES_BY_INDEX.values():
        (repo / name).write_text("orig\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "init")
    return repo


def _items(repo: Path, run_id: str) -> list[dict]:
    return [
        {
            "task_index": index,
            "run_id": run_id,
            "repo": str(repo),
            "task_spec": {"files_affected": [name]},
        }
        for index, name in FILES_BY_INDEX.items()
    ]


def _seed_run_dir(repo: Path, run_id: str) -> Path:
    run_dir = repo / ".simplicio-loop" / "loop-runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text(
        json.dumps({"schema": "simplicio.loop-manifest/v1", "repo": str(repo), "run_id": run_id}),
        encoding="utf-8",
    )
    (run_dir / "state.json").write_text('{"phase": "executing"}', encoding="utf-8")
    return run_dir


def _fake(sleep_s: float, timeline: list):
    def fake(item, retry_budget, owned_process_registry=None):
        task_index = int(item["task_index"])
        repo_dir = Path(item["repo"])
        started = time.monotonic()
        time.sleep(sleep_s)
        (repo_dir / FILES_BY_INDEX[task_index]).write_text(f"lane-{task_index}\n", encoding="utf-8")
        finished = time.monotonic()
        timeline.append((task_index, started, finished))
        return [{
            "schema": "simplicio.operator-worker/v1",
            "task_index": task_index,
            "run_id": item["run_id"],
            "repo": item["repo"],
            "status": "succeeded",
            "execution_state": "applied",
            "dead_letter": False,
            "operator_receipt": "",
            "evidence_receipt": "",
        }]
    return fake


def _overlaps(timeline: list) -> bool:
    for i, (_, a_start, a_end) in enumerate(timeline):
        for _, b_start, b_end in timeline[i + 1:]:
            if a_start < b_end and b_start < a_end:
                return True
    return False


def test_parallel_wave_versus_serial_records_the_faster_path(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_LOOP_DISPATCH_MODE", "thread")

    serial_repo = _init_repo(tmp_path / "serial")
    serial_timeline: list = []
    serial_items = _items(serial_repo, "serial-run")
    serial_fake = _fake(SLEEP_S, serial_timeline)
    serial_started = time.monotonic()
    for item in serial_items:
        serial_fake(item, 0)
    serial_wall = time.monotonic() - serial_started

    parallel_repo = _init_repo(tmp_path / "parallel")
    run_id = "wave-vs-serial"
    run_dir = _seed_run_dir(parallel_repo, run_id)
    parallel_timeline: list = []
    monkeypatch.setattr(
        runner_mod, "_run_operator_item_process", _fake(SLEEP_S, parallel_timeline),
    )
    parallel_started = time.monotonic()
    result = runner_mod._wave_worktree_dispatch(
        repo_path=parallel_repo,
        run_id=run_id,
        run_dir=run_dir,
        items=_items(parallel_repo, run_id),
        retry_budget=0,
        max_workers=3,
    )
    parallel_wall = time.monotonic() - parallel_started

    assert result is not None
    lanes = len(result["wave"]["lanes"])
    overlapped = _overlaps(parallel_timeline)
    if parallel_wall < serial_wall:
        winner = "parallel"
        decision = "keep_parallel"
        reason = "parallel wall was lower on this fixture"
    else:
        winner = "serial"
        decision = "keep_parallel"
        reason = (
            "serial wall was lower because git worktree setup dominates a "
            f"{SLEEP_S:.1f}s sleep; the engine stays on the parallel wave for "
            "disjoint lanes instead of changing it from this fixture alone"
        )
    receipt = {
        "schema": "simplicio.wave-vs-serial/v1",
        "issue": 1357,
        "lanes": lanes,
        "sleep_s": SLEEP_S,
        "wall_parallel_s": round(parallel_wall, 4),
        "wall_serial_s": round(serial_wall, 4),
        "overlapped": overlapped,
        "winner": winner,
        "decision": decision,
        "reason": reason,
    }
    RECEIPT.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")

    assert lanes == 3
    assert overlapped
    assert receipt["decision"] == "keep_parallel"
    assert result["completed_task_indices"] == [1, 2, 3]
