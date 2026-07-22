import json
import sys
from argparse import Namespace
from pathlib import Path

from simplicio.commands import prototype


def _args(**overrides):
    base = {
        "prototype_cmd": "plan",
        "input": None,
        "goal": "ship bounded prototype",
        "prototype_type": "code_spike",
        "output": "plan.json",
        "json": True,
        "root": ".",
        "plan": "plan.json",
        "candidate": None,
        "target": None,
        "receipt": None,
        "decision": None,
        "force": False,
        "timeout": 5.0,
    }
    base.update(overrides)
    return Namespace(**base)


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def _make_plan(tmp_path: Path, prototype_type: str = "code_spike", **extra) -> Path:
    plan_path = tmp_path / "plan.json"
    assert (
        prototype.run(
            _args(
                prototype_cmd="plan",
                output=str(plan_path),
                prototype_type=prototype_type,
                **extra,
            )
        )
        == 0
    )
    return plan_path


def test_prototype_scaffold_supports_loop_contract_types(tmp_path):
    for kind in prototype.TYPES:
        plan_path = _make_plan(tmp_path / kind, kind)
        candidate = tmp_path / kind / "candidate"

        assert (
            prototype.run(
                _args(prototype_cmd="scaffold", plan=str(plan_path), candidate=str(candidate), json=True)
            )
            == 0
        )

        files = {p.name for p in candidate.iterdir()}
        assert ".prototype-receipt.json" in files
        assert files - {".prototype-receipt.json"}


def test_dry_run_reports_writes_without_touching_target(tmp_path):
    plan_path = _make_plan(tmp_path, "schema")
    candidate = tmp_path / "candidate"
    target = tmp_path / "target"
    target.mkdir()
    (target / "existing.txt").write_text("keep\n", encoding="utf-8")

    assert (
        prototype.run(
            _args(prototype_cmd="scaffold", plan=str(plan_path), candidate=str(candidate), json=True)
        )
        == 0
    )
    before = prototype._tree(target)

    assert (
        prototype.run(
            _args(
                prototype_cmd="dry-run",
                plan=str(plan_path),
                candidate=str(candidate),
                target=str(target),
                json=True,
            )
        )
        == 0
    )

    assert prototype._tree(target) == before


def test_validate_writes_evidence_and_blocks_failing_validator(tmp_path):
    plan_path = _make_plan(
        tmp_path,
        "code_spike",
        input=None,
    )
    plan = _read(plan_path)
    plan["validators"] = [f"{sys.executable} -c 'print(42)'", f"{sys.executable} -c 'raise SystemExit(3)'"]
    plan["plan_hash"] = prototype._sha({k: v for k, v in plan.items() if k != "plan_hash"})
    _write(plan_path, plan)
    candidate = tmp_path / "candidate"

    assert (
        prototype.run(
            _args(prototype_cmd="scaffold", plan=str(plan_path), candidate=str(candidate), json=True)
        )
        == 0
    )
    assert (
        prototype.run(
            _args(prototype_cmd="validate", plan=str(plan_path), candidate=str(candidate), json=True)
        )
        == 1
    )

    receipt = _read(candidate / ".prototype-receipt.json")
    assert receipt["kind"] == "validation"
    assert receipt["valid"] is False
    assert [item["exit_code"] for item in receipt["validators"]] == [0, 3]


def test_promote_rejects_forged_decision(tmp_path):
    plan_path = _make_plan(tmp_path, "mock_or_fake")
    candidate = tmp_path / "candidate"
    assert (
        prototype.run(
            _args(prototype_cmd="scaffold", plan=str(plan_path), candidate=str(candidate), json=True)
        )
        == 0
    )
    receipt = _read(candidate / ".prototype-receipt.json")
    receipt.update({"kind": "validation", "valid": True})
    _write(candidate / ".prototype-receipt.json", receipt)
    _write(
        candidate / ".prototype-decision.json",
        {
            "schema": prototype.SCHEMA_DECISION,
            "decision": "ACCEPT",
            "plan_hash": "forged",
            "candidate_hash": receipt["candidate_hash"],
        },
    )

    assert (
        prototype.run(
            _args(
                prototype_cmd="promote",
                plan=str(plan_path),
                candidate=str(candidate),
                target=str(tmp_path / "target"),
            )
        )
        == 2
    )


def test_source_drift_invalidates_candidate(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    (target / "existing.txt").write_text("v1\n", encoding="utf-8")
    source_sha = prototype._sha(prototype._tree(target))
    input_plan = tmp_path / "input.json"
    _write(
        input_plan,
        {
            "schema": prototype.SCHEMA_PLAN,
            "goal": "ship bounded prototype",
            "prototype_type": "code_spike",
            "source_sha": source_sha,
            "validators": [],
        },
    )
    plan_path = tmp_path / "plan.json"
    assert prototype.run(_args(prototype_cmd="plan", input=str(input_plan), output=str(plan_path))) == 0
    (target / "existing.txt").write_text("v2\n", encoding="utf-8")

    assert (
        prototype.run(
            _args(
                prototype_cmd="scaffold",
                plan=str(plan_path),
                candidate=str(tmp_path / "candidate"),
                target=str(target),
            )
        )
        == 2
    )
