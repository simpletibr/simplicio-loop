"""AGENTS.md wave-safeguards item 1: lane concurrency in the wave dispatch
path (`_wave_worktree_dispatch`) must be admitted by the same physical
admission governor the classic `dispatch_operator_batch` path uses
(`local_capacity.PhysicalAdmissionMonitor`) -- not a raw
``min(cpu_count, len(lanes))`` guess, and not a fixed ``max_workers`` request
regardless of measured physical capacity.
"""
from __future__ import annotations

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
    run_dir = repo / ".simplicio-loop" / "loop-runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text(
        '{"schema": "simplicio.loop-manifest/v1", "repo": "%s", "run_id": "%s"}' % (repo, run_id),
        encoding="utf-8",
    )
    (run_dir / "state.json").write_text('{"phase": "executing"}', encoding="utf-8")
    return run_dir


class _FakeSample:
    def __init__(self, safe_workers: int) -> None:
        self.safe_workers = safe_workers
        self.observed_at_ns = 0

    def to_dict(self):
        return {"safe_workers": self.safe_workers}


class _FakeMonitor:
    """Stands in for `local_capacity.PhysicalAdmissionMonitor` so the test can
    force a deterministic capacity decision instead of depending on this
    machine's real, non-deterministic CPU/disk/memory pressure."""

    instances: list = []

    def __init__(self, root, requested_workers, **kwargs):
        self.root = root
        self.requested_workers = requested_workers
        self.kwargs = kwargs
        _FakeMonitor.instances.append(self)

    def refresh(self, *, force=False):
        raise NotImplementedError

    def admission_status(self):
        raise NotImplementedError


def _make_fake_dispatch():
    def fake(item, retry_budget, owned_process_registry=None):
        task_index = int(item["task_index"])
        return [{
            "schema": "simplicio.operator-worker/v1", "task_index": task_index,
            "run_id": item["run_id"], "repo": item["repo"], "status": "succeeded",
            "execution_state": "applied", "dead_letter": False,
            "operator_receipt": "", "evidence_receipt": "",
        }]
    return fake


def test_wave_dispatch_asks_the_physical_admission_monitor_for_lane_capacity(tmp_path, monkeypatch):
    """The wave path must consult the same governor the classic path uses --
    proven by observing the monitor actually gets constructed and queried for
    this exact repo/lane-count, not bypassed for a raw CPU-count guess."""
    monkeypatch.setenv("SIMPLICIO_LOOP_DISPATCH_MODE", "thread")
    repo = _init_repo(tmp_path)
    run_id = "wave-run-capacity"
    run_dir = _seed_run_dir(repo, run_id)
    items = [
        {"task_index": 1, "run_id": run_id, "repo": str(repo), "task_spec": {"files_affected": ["a.txt"]}},
        {"task_index": 2, "run_id": run_id, "repo": str(repo), "task_spec": {"files_affected": ["b.txt"]}},
    ]
    monkeypatch.setattr(runner_mod, "_run_operator_item_process", _make_fake_dispatch())

    _FakeMonitor.instances = []

    class AdmittingMonitor(_FakeMonitor):
        def refresh(self, *, force=False):
            return _FakeSample(2)

        def admission_status(self):
            return {"admitted": True, "reason_code": "PHYSICAL_CAPACITY_AVAILABLE", "evidence": {}}

    monkeypatch.setattr(runner_mod.local_capacity, "PhysicalAdmissionMonitor", AdmittingMonitor)

    result = runner_mod._wave_worktree_dispatch(
        repo_path=repo, run_id=run_id, run_dir=run_dir,
        items=items, retry_budget=0, max_workers=2,
    )

    assert result is not None
    assert len(AdmittingMonitor.instances) == 1
    admitted_monitor = AdmittingMonitor.instances[0]
    # The monitor must be sized to the number of LANES (2, one per disjoint
    # file), the actual unit of live local concurrency this path creates.
    assert admitted_monitor.requested_workers == 2
    assert Path(admitted_monitor.root).resolve() == repo.resolve()
    assert result["capacity_admission"]["admitted"] is True
    assert result["completed_task_indices"] == [1, 2]


def test_wave_dispatch_defers_to_serial_fallback_when_capacity_is_not_admitted(tmp_path, monkeypatch):
    """When the physical governor refuses admission (measured pressure, not a
    guess), the wave path must not silently run anyway with degraded/ignored
    capacity -- it defers to the classic path, which already produces the
    correctly-typed blocked receipt for this exact admission state."""
    monkeypatch.setenv("SIMPLICIO_LOOP_DISPATCH_MODE", "thread")
    repo = _init_repo(tmp_path)
    run_id = "wave-run-blocked"
    run_dir = _seed_run_dir(repo, run_id)
    items = [
        {"task_index": 1, "run_id": run_id, "repo": str(repo), "task_spec": {"files_affected": ["a.txt"]}},
        {"task_index": 2, "run_id": run_id, "repo": str(repo), "task_spec": {"files_affected": ["b.txt"]}},
    ]
    calls: list = []

    def spy(item, retry_budget, owned_process_registry=None):
        calls.append(item["task_index"])
        raise AssertionError("must not dispatch any lane task when capacity is not admitted")

    monkeypatch.setattr(runner_mod, "_run_operator_item_process", spy)

    class RefusingMonitor(_FakeMonitor):
        def refresh(self, *, force=False):
            return _FakeSample(0)

        def admission_status(self):
            return {
                "admitted": False, "reason_code": "PHYSICAL_CAPACITY_PRESSURE",
                "reason": "no_safe_workers", "evidence": {},
            }

    monkeypatch.setattr(runner_mod.local_capacity, "PhysicalAdmissionMonitor", RefusingMonitor)

    result = runner_mod._wave_worktree_dispatch(
        repo_path=repo, run_id=run_id, run_dir=run_dir,
        items=items, retry_budget=0, max_workers=2,
    )

    assert result is None
    assert calls == []
    worktree_list = _git(repo, "worktree", "list")
    assert "lane-" not in worktree_list
