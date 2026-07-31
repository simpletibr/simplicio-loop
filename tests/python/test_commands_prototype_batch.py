"""Coverage for `simplicio prototype batch` (`simplicio/commands/prototype.py`),
the bounded fan-out over scaffold+validate added for issue #236's "Implementar
batch/fan-out com backpressure" checklist item.

Covers the acceptance criteria from the task:

- backpressure: concurrency is capped at `--concurrency`, never unbounded,
  even when more plans are queued than workers;
- failure isolation: one candidate's validator failing, or a plan crashing
  the pipeline outright (malformed JSON), never blocks or corrupts siblings;
- no shared-state corruption: concurrent candidates write only into their
  own plan_hash-keyed sandbox dir, never into a sibling's;
- a large-ish batch (50 plans) completes without unbounded thread/resource
  growth.

All plan JSON files live under `<tmp_path>/.simplicio/plans/` (the adapter's
own bookkeeping dir, excluded from the source-tree hash) so that writing N
plan files one after another never invalidates an earlier plan's
`source_sha` baseline — same rationale documented in
`test_commands_prototype.py`.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

import pytest

from simplicio import cli
from simplicio.commands import prototype


def _plans_dir(tmp_path: Path) -> Path:
    directory = tmp_path / ".simplicio" / "plans"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _write_plan(
    tmp_path: Path,
    capsys,
    plans_dir: Path,
    *,
    name: str,
    goal: str,
    validators: list[str] | None = None,
    prototype_type: str = "code_spike",
) -> Path:
    input_path = plans_dir / f"{name}.input.json"
    input_path.write_text(
        json.dumps(
            {
                "goal": goal,
                "prototype_type": prototype_type,
                "name": name,
                "validators": validators or [],
            }
        ),
        encoding="utf-8",
    )
    plan_path = plans_dir / f"{name}.json"
    code = cli.main(
        [
            "prototype",
            "plan",
            "--input",
            str(input_path),
            "--root",
            str(tmp_path),
            "--output",
            str(plan_path),
        ]
    )
    assert code == 0
    capsys.readouterr()
    input_path.unlink()  # keep --plans glob (`*.json`) matching only real plans
    return plan_path


def test_batch_scaffolds_and_validates_every_plan_ok(tmp_path, capsys):
    plans_dir = _plans_dir(tmp_path)
    for i in range(4):
        _write_plan(tmp_path, capsys, plans_dir, name=f"plan{i}", goal=f"goal {i}")

    code = cli.main(
        [
            "prototype",
            "batch",
            "--root",
            str(tmp_path),
            "--plans",
            str(plans_dir),
            "--concurrency",
            "2",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["kind"] == "batch"
    assert payload["total"] == 4
    assert payload["ok"] == 4
    assert payload["failed"] == 0
    assert payload["errored"] == 0
    assert len(payload["results"]) == 4
    for result in payload["results"]:
        assert result["status"] == "ok"
        assert Path(result["candidate"]).is_dir()


def test_batch_no_cross_candidate_artifact_corruption(tmp_path, capsys):
    """Each candidate's skeleton is written with a per-plan goal baked into
    its content; concurrently scaffolding must never let one candidate's
    files leak into (or get overwritten by) a sibling's."""
    plans_dir = _plans_dir(tmp_path)
    names = [f"candidate-{i}" for i in range(6)]
    for name in names:
        _write_plan(
            tmp_path,
            capsys,
            plans_dir,
            name=name,
            goal=f"unique goal for {name}",
            prototype_type="wireframe",
        )

    code = cli.main(
        [
            "prototype",
            "batch",
            "--root",
            str(tmp_path),
            "--plans",
            str(plans_dir),
            "--concurrency",
            "4",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["ok"] == len(names)

    candidate_dirs = [Path(r["candidate"]) for r in payload["results"]]
    # every candidate dir is distinct...
    assert len(set(candidate_dirs)) == len(candidate_dirs)
    by_plan = {Path(r["plan"]).stem: r for r in payload["results"]}
    for name in names:
        candidate = Path(by_plan[name]["candidate"])
        proto_md = candidate / "WIREFRAME.md"
        assert proto_md.is_file()
        content = proto_md.read_text(encoding="utf-8")
        # each candidate's artifact contains ONLY its own goal, never a
        # sibling's — proof no concurrent write crossed sandbox boundaries.
        assert f"Goal: unique goal for {name}\n" in content
        for other in names:
            if other != name:
                assert f"unique goal for {other}" not in content


def test_batch_isolates_a_failing_validator_from_siblings(tmp_path, capsys):
    plans_dir = _plans_dir(tmp_path)
    succeeds = f'"{sys.executable}" -c "import sys; sys.exit(0)"'
    fails = f'"{sys.executable}" -c "import sys; sys.exit(1)"'
    _write_plan(tmp_path, capsys, plans_dir, name="good-a", goal="passes", validators=[succeeds])
    _write_plan(tmp_path, capsys, plans_dir, name="bad", goal="fails", validators=[fails])
    _write_plan(tmp_path, capsys, plans_dir, name="good-b", goal="also passes", validators=[succeeds])

    code = cli.main(
        [
            "prototype",
            "batch",
            "--root",
            str(tmp_path),
            "--plans",
            str(plans_dir),
            "--concurrency",
            "3",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    # non-zero exit signals "batch had a real failure", but the batch itself
    # ran to completion and reported every candidate individually.
    assert code == 1
    assert payload["total"] == 3
    assert payload["ok"] == 2
    assert payload["failed"] == 1
    assert payload["errored"] == 0
    by_plan = {Path(r["plan"]).stem: r for r in payload["results"]}
    assert by_plan["good-a"]["status"] == "ok"
    assert by_plan["good-b"]["status"] == "ok"
    assert by_plan["bad"]["status"] == "failed"
    assert by_plan["bad"]["valid"] is False


def test_batch_isolates_a_malformed_plan_crash_from_siblings(tmp_path, capsys):
    """A plan file that fails the hash/schema check must error out for just
    that one candidate — never abort or corrupt the batch."""
    plans_dir = _plans_dir(tmp_path)
    _write_plan(tmp_path, capsys, plans_dir, name="good-a", goal="fine")
    (plans_dir / "corrupt.json").write_text(
        json.dumps({"schema": "simplicio.prototype-plan/v1", "goal": "no plan_hash at all"}),
        encoding="utf-8",
    )
    _write_plan(tmp_path, capsys, plans_dir, name="good-b", goal="also fine")

    code = cli.main(
        [
            "prototype",
            "batch",
            "--root",
            str(tmp_path),
            "--plans",
            str(plans_dir),
            "--concurrency",
            "3",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert code == 1
    assert payload["total"] == 3
    assert payload["ok"] == 2
    assert payload["errored"] == 1
    by_plan = {Path(r["plan"]).stem: r for r in payload["results"]}
    assert by_plan["good-a"]["status"] == "ok"
    assert by_plan["good-b"]["status"] == "ok"
    assert by_plan["corrupt"]["status"] == "error"
    assert "hash/schema mismatch" in by_plan["corrupt"]["error"]


def test_batch_rejects_no_matching_plans(tmp_path):
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    code = cli.main(["prototype", "batch", "--root", str(tmp_path), "--plans", str(empty_dir), "--json"])
    assert code == 2


def test_batch_enforces_concurrency_cap_never_exceeded(tmp_path, capsys, monkeypatch):
    """Backpressure proof: instrument the per-plan worker with a shared
    counter/lock. However many plans are queued, the number running at any
    instant must never exceed --concurrency."""
    plans_dir = _plans_dir(tmp_path)
    total_plans = 12
    concurrency = 3
    for i in range(total_plans):
        _write_plan(tmp_path, capsys, plans_dir, name=f"plan{i}", goal=f"goal {i}")

    lock = threading.Lock()
    state = {"active": 0, "peak": 0}
    real_process_one_plan = prototype._process_one_plan

    def _tracked(plan_path, args):
        with lock:
            state["active"] += 1
            state["peak"] = max(state["peak"], state["active"])
        try:
            time.sleep(0.05)  # widen the window so overlapping calls are likely
            return real_process_one_plan(plan_path, args)
        finally:
            with lock:
                state["active"] -= 1

    monkeypatch.setattr(prototype, "_process_one_plan", _tracked)

    code = cli.main(
        [
            "prototype",
            "batch",
            "--root",
            str(tmp_path),
            "--plans",
            str(plans_dir),
            "--concurrency",
            str(concurrency),
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["total"] == total_plans
    assert payload["ok"] == total_plans
    assert state["peak"] <= concurrency
    # and it actually DID run concurrently (not silently serialized to 1)
    assert state["peak"] > 1


def test_batch_completes_large_batch_without_unbounded_growth(tmp_path, capsys, monkeypatch):
    """50 plans, bounded concurrency: proves the batch doesn't spawn a
    thread/process per plan (unbounded growth) and completes cleanly."""
    plans_dir = _plans_dir(tmp_path)
    total_plans = 50
    concurrency = 5
    for i in range(total_plans):
        _write_plan(tmp_path, capsys, plans_dir, name=f"plan{i:03d}", goal=f"goal {i}")

    lock = threading.Lock()
    state = {"active": 0, "peak": 0}
    real_process_one_plan = prototype._process_one_plan

    def _tracked(plan_path, args):
        with lock:
            state["active"] += 1
            state["peak"] = max(state["peak"], state["active"])
        try:
            return real_process_one_plan(plan_path, args)
        finally:
            with lock:
                state["active"] -= 1

    monkeypatch.setattr(prototype, "_process_one_plan", _tracked)

    threads_before = threading.active_count()
    code = cli.main(
        [
            "prototype",
            "batch",
            "--root",
            str(tmp_path),
            "--plans",
            str(plans_dir),
            "--concurrency",
            str(concurrency),
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    threads_after = threading.active_count()

    assert code == 0, payload
    assert payload["total"] == total_plans
    assert payload["ok"] == total_plans
    assert state["peak"] <= concurrency
    # the executor's pool must be fully torn down afterwards -- no thread
    # leak proportional to the 50 plans processed.
    assert threads_after <= threads_before + 1


def test_batch_serial_path_when_concurrency_is_one(tmp_path, capsys, monkeypatch):
    plans_dir = _plans_dir(tmp_path)
    for i in range(3):
        _write_plan(tmp_path, capsys, plans_dir, name=f"plan{i}", goal=f"goal {i}")

    lock = threading.Lock()
    state = {"active": 0, "peak": 0}
    real_process_one_plan = prototype._process_one_plan

    def _tracked(plan_path, args):
        with lock:
            state["active"] += 1
            state["peak"] = max(state["peak"], state["active"])
        try:
            return real_process_one_plan(plan_path, args)
        finally:
            with lock:
                state["active"] -= 1

    monkeypatch.setattr(prototype, "_process_one_plan", _tracked)

    code = cli.main(
        [
            "prototype",
            "batch",
            "--root",
            str(tmp_path),
            "--plans",
            str(plans_dir),
            "--concurrency",
            "1",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["ok"] == 3
    assert state["peak"] == 1


def test_batch_rejects_invalid_concurrency(tmp_path, capsys):
    plans_dir = _plans_dir(tmp_path)
    _write_plan(tmp_path, capsys, plans_dir, name="plan0", goal="goal 0")

    code = cli.main(
        [
            "prototype",
            "batch",
            "--root",
            str(tmp_path),
            "--plans",
            str(plans_dir),
            "--concurrency",
            "0",
            "--json",
        ]
    )
    err = capsys.readouterr().err
    assert code == 2
    assert "--concurrency must be >= 1" in err


def test_batch_accepts_glob_pattern_for_plans(tmp_path, capsys):
    plans_dir = _plans_dir(tmp_path)
    for i in range(3):
        _write_plan(tmp_path, capsys, plans_dir, name=f"plan{i}", goal=f"goal {i}")

    code = cli.main(
        [
            "prototype",
            "batch",
            "--root",
            str(tmp_path),
            "--plans",
            str(plans_dir / "*.json"),
            "--concurrency",
            "2",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["total"] == 3
    assert payload["ok"] == 3


@pytest.mark.parametrize("concurrency", [1, 2, 5])
def test_batch_never_writes_outside_its_own_candidate_dirs(tmp_path, capsys, concurrency):
    """Cross-check against the full working tree hash, mirroring
    test_scaffold_writes_only_inside_isolated_candidate_dir: everything the
    batch produces must land under .simplicio/prototypes/<plan_hash>, and a
    real working-tree file must remain untouched."""
    source_file = tmp_path / "src.py"
    source_file.write_text("print('real working tree file')\n", encoding="utf-8")
    source_before = source_file.read_bytes()
    plans_dir = _plans_dir(tmp_path)
    for i in range(4):
        _write_plan(tmp_path, capsys, plans_dir, name=f"plan{i}", goal=f"goal {i}")

    code = cli.main(
        [
            "prototype",
            "batch",
            "--root",
            str(tmp_path),
            "--plans",
            str(plans_dir),
            "--concurrency",
            str(concurrency),
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    for result in payload["results"]:
        candidate = Path(result["candidate"])
        assert candidate.is_relative_to(tmp_path / ".simplicio" / "prototypes")
    assert source_file.read_bytes() == source_before
