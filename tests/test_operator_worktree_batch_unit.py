"""WorktreeQueue bridge tests that do not invoke Git subprocesses."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from simplicio_loop import runner
from tests.runner_patch import patch_runner

pytestmark = pytest.mark.usefixtures("admitting_capacity")  # host pressure must not decide these dispatch tests


def test_auto_fan_out_requires_independent_plan_targets(monkeypatch, tmp_path):
    (tmp_path / ".git").mkdir()

    class Queue:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.registered = []

        def register_tasks(self, specs):
            self.registered = list(specs)

        @staticmethod
        def conflict_graph(specs):
            return {spec.id: [] for spec in specs}

    import scripts.worktree_queue as worktree_queue
    monkeypatch.setattr(worktree_queue, "WorktreeQueue", Queue)
    names = ["a", "b", "c", "d"]
    contract = {"tasks": [{"identity": {"feature": n.upper()}} for n in names]}
    plan = {"steps": [{"candidate_targets": [f"src/{n}.py"]} for n in names]}

    queue, contexts, reason = runner._auto_worktree_dispatch(
        str(tmp_path), "run-1", contract, plan, [1, 2, 3, 4]
    )

    assert isinstance(queue, Queue)
    assert reason == ""
    assert set(contexts) == {1, 2, 3, 4}
    assert {spec.files_affected[0] for spec in queue.registered} == {f"src/{n}.py" for n in names}


def test_one_task_stays_on_the_shared_checkout(tmp_path):
    """Exactly one task is ``tick`` on the shared tree, not a wave lane."""
    (tmp_path / ".git").mkdir()
    contract = {"tasks": [{"identity": {"feature": "only"}}]}
    plan = {"steps": [{"candidate_targets": ["src/only.py"]}]}
    queue, contexts, reason = runner._auto_worktree_dispatch(
        str(tmp_path), "run-1", contract, plan, [1]
    )
    assert (queue, contexts, reason) == (None, {}, "single_task")
    assert runner.WAVE_INLINE_MAX_TASKS == 1


def test_two_or_more_tasks_enter_the_wave(monkeypatch, tmp_path):
    """More than one task is a wave. Two and three no longer stay inline."""
    (tmp_path / ".git").mkdir()

    class Queue:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.registered = []

        def register_tasks(self, specs):
            self.registered = list(specs)

        @staticmethod
        def conflict_graph(specs):
            return {spec.id: [] for spec in specs}

    import scripts.worktree_queue as worktree_queue
    monkeypatch.setattr(worktree_queue, "WorktreeQueue", Queue)
    for count in (2, 3):
        contract = {"tasks": [{"identity": {"feature": str(i)}} for i in range(count)]}
        plan = {"steps": [{"candidate_targets": [f"src/{i}.py"]} for i in range(count)]}
        queue, contexts, reason = runner._auto_worktree_dispatch(
            str(tmp_path), "run-1", contract, plan, list(range(1, count + 1))
        )
        assert reason == ""
        assert isinstance(queue, Queue)
        assert set(contexts) == set(range(1, count + 1))


def test_auto_fan_out_falls_back_for_overlapping_targets(monkeypatch, tmp_path):
    (tmp_path / ".git").mkdir()
    contract = {"tasks": [{"identity": {"feature": str(i)}} for i in range(4)]}
    plan = {"steps": [{"candidate_targets": ["src/shared.py"]} for _ in range(4)]}

    queue, contexts, reason = runner._auto_worktree_dispatch(
        str(tmp_path), "run-1", contract, plan, [1, 2, 3, 4]
    )

    assert queue is None
    assert contexts == {}
    assert reason == "overlapping_task_impacts"


def test_auto_fan_out_can_be_disabled(monkeypatch, tmp_path):
    (tmp_path / ".git").mkdir()
    monkeypatch.setenv("SIMPLICIO_LOOP_AUTO_FAN_OUT", "0")
    queue, contexts, reason = runner._auto_worktree_dispatch(
        str(tmp_path), "run-1", {"tasks": [{}, {}]}, {"steps": [{}, {}]}, [1, 2]
    )
    assert queue is None
    assert contexts == {}
    assert reason == "auto_fan_out_disabled"


class FakeQueue:
    def __init__(self, root: Path):
        self.root = root
        self.registered = []
        self.allocations = []
        self.contexts = {}
        self.cleaned = []
        self.shared_active = False

    def register_tasks(self, specs):
        self.registered = list(specs)

    def allocate(self, spec, isolation="worktree", shared_policy=False):
        assert isolation in ("worktree", "shared")
        if isolation == "shared":
            if self.shared_active:
                raise RuntimeError("shared checkout already owned")
            self.shared_active = True
        path = self.root if isolation == "shared" else self.root / spec.id
        if isolation == "worktree":
            path.mkdir(parents=True, exist_ok=True)
        allocation = SimpleNamespace(
            task_id=spec.id,
            run_id="queue-run",
            mode=isolation,
            path=str(path),
            branch="simplicio/queue/" + spec.id,
            base_sha="base",
            head_sha="head",
            tree_sha="tree",
            lane="lane-" + ("shared" if isolation == "shared" else spec.id),
            reattached=False,
            lock_receipt="lock.json" if isolation == "shared" else None,
        )
        self.allocations.append(allocation)
        return allocation

    def record_context(self, task_id, context):
        self.contexts[task_id] = dict(context)

    def teardown(self, task_id):
        self.cleaned.append(task_id)
        self.shared_active = False


def _success(repo, run_id, task_index):
    return {
        "run_dir": str(Path(repo) / ".simplicio-loop/orchestrator" / "runs" / run_id),
        "state": {
            "phase": "validating",
            "attempts": 1,
            "operator": {
                "execution_state": "applied",
                "receipt": str(Path(repo) / "receipt.json"),
            },
        },
    }


def test_dispatch_allocates_and_persists_isolated_context_without_git(monkeypatch, tmp_path):
    monkeypatch.setenv("SIMPLICIO_LOOP_DISPATCH_MODE", "thread")
    queue = FakeQueue(tmp_path / "workers")
    calls = []

    def fake_execute(repo, run_id, task_index, **_kwargs):
        calls.append((repo, run_id, task_index))
        return _success(repo, run_id, task_index)

    patch_runner(monkeypatch, "execute_operator", fake_execute)
    result = runner.dispatch_operator_batch(
        [
            {"repo": str(tmp_path), "run_id": "run-1", "task_index": 1, "task_id": "A",
             "task_spec": {"id": "A", "files_affected": ["a.py"]}},
            {"repo": str(tmp_path), "run_id": "run-1", "task_index": 2, "task_id": "B",
             "task_spec": {"id": "B", "files_affected": ["b.py"]}},
        ],
        max_workers=2,
        retry_budget=0,
        worktree_queue=queue,
    )

    assert result["max_workers"] == 2
    assert result["serial_fallback_reason"] == ""
    assert result["completed_task_indices"] == [1, 2]
    assert {item[0] for item in calls} == {str((tmp_path / "workers" / "A").resolve()),
                                             str((tmp_path / "workers" / "B").resolve())}
    assert set(queue.contexts) == {"A", "B"}
    assert all(row["worktree_context"]["context_path"] for row in result["workers"])
    assert result["prism"]["schema"] == "simplicio.loop.native-prism-dispatch/v1"
    assert result["prism"]["mode"] == "direct-parallelism"
    assert result["prism"]["max_workers"] == 2
    assert result["prism"]["snapshot"] is None


def test_dispatch_partitions_independent_impacts_into_multiple_prism_slots(monkeypatch, tmp_path):
    monkeypatch.setenv("SIMPLICIO_LOOP_DISPATCH_MODE", "thread")
    queue = FakeQueue(tmp_path / "workers")

    def fake_execute(repo, run_id, task_index, **_kwargs):
        return _success(repo, run_id, task_index)

    patch_runner(monkeypatch, "execute_operator", fake_execute)
    result = runner.dispatch_operator_batch(
        [
            {"repo": str(tmp_path), "run_id": "run-1", "task_index": index,
             "task_id": chr(64 + index),
             "task_spec": {"id": chr(64 + index), "files_affected": [f"{name}/file.py"]}}
            for index, name in enumerate(("alpha", "beta", "gamma", "delta"), start=1)
        ],
        max_workers=4,
        retry_budget=0,
        worktree_queue=queue,
    )

    snapshot = result["prism"]["snapshot"]
    assert snapshot["metrics"]["logical_slots"] == 4
    assert len(snapshot["slots"]) == 4


def test_process_mode_keeps_queue_lease_coordinator_owned(monkeypatch, tmp_path):
    monkeypatch.setenv("SIMPLICIO_LOOP_DISPATCH_MODE", "process")
    queue = FakeQueue(tmp_path / "workers")

    result = runner.dispatch_operator_batch(
        [{
            "repo": str(tmp_path), "run_id": "run-process", "task_index": 1,
            "task_id": "A", "task_spec": {"id": "A", "files_affected": ["a.py"]},
        }],
        max_workers=1,
        retry_budget=0,
        worktree_queue=queue,
    )

    assert result["dispatch_mode"] == "process"
    assert result["serial_fallback_reason"] == ""
    assert result["workers"][0]["status"] == "failed"
    assert queue.contexts["A"]["context_path"]


def test_dispatch_serializes_explicit_shared_queue_context(monkeypatch, tmp_path):
    monkeypatch.setenv("SIMPLICIO_LOOP_DISPATCH_MODE", "thread")
    queue = FakeQueue(tmp_path / "shared")
    calls = []

    def fake_execute(repo, run_id, task_index, **_kwargs):
        calls.append(task_index)
        return _success(repo, run_id, task_index)

    patch_runner(monkeypatch, "execute_operator", fake_execute)
    result = runner.dispatch_operator_batch(
        [
            {"repo": str(tmp_path), "run_id": "run-2", "task_index": 1, "task_id": "A",
             "isolation": "shared", "task_spec": {"id": "A"}},
            {"repo": str(tmp_path), "run_id": "run-2", "task_index": 2, "task_id": "B",
             "isolation": "shared", "task_spec": {"id": "B"}},
        ],
        max_workers=2,
        retry_budget=0,
        worktree_queue=queue,
    )

    assert result["max_workers"] == 1
    assert result["serial_fallback_reason"] == "shared_run_state"
    assert calls == [1, 2]
    assert queue.cleaned == ["A", "B"]
    assert all(row["worktree_context"]["mode"] == "shared" for row in result["workers"])


def test_dispatch_queue_context_error_fails_closed(monkeypatch, tmp_path):
    monkeypatch.setenv("SIMPLICIO_LOOP_DISPATCH_MODE", "thread")
    class BrokenQueue(FakeQueue):
        def record_context(self, task_id, context):
            raise RuntimeError("context store offline")

    calls = []
    patch_runner(monkeypatch, "execute_operator", lambda *args, **kwargs: calls.append(args))
    result = runner.dispatch_operator_batch(
        [{"repo": str(tmp_path), "run_id": "run-3", "task_index": 1, "task_id": "A"}],
        max_workers=1,
        retry_budget=0,
        worktree_queue=BrokenQueue(tmp_path / "workers"),
    )

    assert not calls
    assert result["failed_task_indices"] == [1]
    assert result["workers"][0]["reason_code"] == "worktree_context_unpersisted"
