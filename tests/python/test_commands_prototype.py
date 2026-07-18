"""Unit + integration coverage for `simplicio prototype ...`
(`simplicio/commands/prototype.py`), the Prototype-First Gate adapter for
simplicio-loop epic #568 (issue simplicio-dev-cli#236).

Drives every subcommand through `cli.main(...)` (integration, real argparse
dispatch). Covers the acceptance criteria from #236:

- scaffold produces a real artifact in an isolated sandbox, never touching
  the working tree it was planned against;
- dry-run proves zero working-tree change (hash before/after);
- validate actually runs a real validator command and captures evidence;
- promote refuses without a valid, schema-conformant ACCEPT decision
  (missing and forged decisions are both rejected);
- a stale candidate (source tree changed since the plan was created) is
  detected and rejected at both validate and promote.

All plan/decision JSON artifacts written by these tests live under
`<tmp_path>/.simplicio/...` (the adapter's own bookkeeping dir, excluded from
the source-tree hash by `_SOURCE_EXCLUDES`) rather than directly under
`--root`, mirroring the CLI's own default (`--output
.simplicio/prototype-plan.json`). Writing them straight into `--root` would
make every plan self-invalidate the moment it's written, since the file
would not have existed yet when `source_sha` was computed.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

from simplicio import cli

# `sys.executable`, not a hardcoded "python3": the validator commands below
# are shell strings that actually run (see test_validate_runs_real_validator_
# and_captures_evidence's docstring intent), and "python3" is not guaranteed
# on every platform (notably plain Windows installs, which expose "python"
# but not "python3") — see simplicio/commands/prototype.py's module
# docstring on the shell=True portability boundary this exercises for real.
PYTHON = f'"{sys.executable}"'


def _tree_hash(root: Path) -> str:
    """Recompute a whole-of-`root` content hash the same way the test
    assertions need it — independent of the module's own `_tree`/`_source_tree`
    helpers, so this isn't just re-testing the implementation against itself."""
    digest = hashlib.sha256()
    for item in sorted(root.rglob("*")):
        if item.is_file():
            digest.update(item.relative_to(root).as_posix().encode("utf-8"))
            digest.update(item.read_bytes())
    return digest.hexdigest()


def _artifacts_dir(tmp_path: Path) -> Path:
    directory = tmp_path / ".simplicio" / "artifacts"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _make_plan(
    tmp_path: Path, capsys, *, prototype_type: str, goal: str = "prove the gate"
) -> tuple[dict, Path]:
    plan_path = _artifacts_dir(tmp_path) / "plan.json"
    code = cli.main(
        [
            "prototype",
            "plan",
            "--goal",
            goal,
            "--type",
            prototype_type,
            "--root",
            str(tmp_path),
            "--output",
            str(plan_path),
            "--json",
        ]
    )
    assert code == 0
    capsys.readouterr()
    return json.loads(plan_path.read_text(encoding="utf-8")), plan_path


def _plan_from_input(tmp_path: Path, capsys, *, goal: str, validators: list[str]) -> Path:
    input_path = _artifacts_dir(tmp_path) / "input.json"
    input_path.write_text(
        json.dumps({"goal": goal, "prototype_type": "code_spike", "validators": validators}),
        encoding="utf-8",
    )
    plan_path = _artifacts_dir(tmp_path) / "plan.json"
    code = cli.main(
        ["prototype", "plan", "--input", str(input_path), "--root", str(tmp_path), "--output", str(plan_path)]
    )
    assert code == 0
    capsys.readouterr()
    return plan_path


def _scaffold_and_validate(tmp_path: Path, capsys, *, validators: list[str]) -> tuple[Path, Path]:
    plan_path = _plan_from_input(tmp_path, capsys, goal="promote flow", validators=validators)
    cli.main(["prototype", "scaffold", "--root", str(tmp_path), "--plan", str(plan_path)])
    capsys.readouterr()
    cli.main(["prototype", "validate", "--root", str(tmp_path), "--plan", str(plan_path), "--json"])
    receipt = json.loads(capsys.readouterr().out)
    return plan_path, Path(receipt["candidate"])


def test_doctor_reports_schemas_and_isolation_default(capsys):
    code = cli.main(["prototype", "doctor", "--json"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["plan_schema"] == "simplicio.prototype-plan/v1"
    assert payload["isolated_default"] is True


def test_plan_accepts_every_documented_prototype_type(tmp_path, capsys):
    for prototype_type in ("schema", "data_model", "failing_reproducer", "mock_or_fake", "code_spike", "vertical_slice"):
        plan, _ = _make_plan(
            tmp_path, capsys, prototype_type=prototype_type, goal=f"goal for {prototype_type}"
        )
        assert plan["prototype_type"] == prototype_type


@pytest.mark.parametrize("prototype_type", ["schema", "failing_reproducer", "code_spike"])
def test_scaffold_writes_only_inside_isolated_candidate_dir(tmp_path, capsys, prototype_type):
    source_file = tmp_path / "src.py"
    source_file.write_text("print('real working tree file')\n", encoding="utf-8")

    plan, plan_path = _make_plan(tmp_path, capsys, prototype_type=prototype_type)
    assert plan["prototype_type"] == prototype_type

    code = cli.main(["prototype", "scaffold", "--root", str(tmp_path), "--plan", str(plan_path), "--json"])
    assert code == 0
    receipt = json.loads(capsys.readouterr().out)
    candidate = Path(receipt["candidate"])

    # Real artifact landed in the sandbox...
    assert candidate.is_dir()
    assert candidate.is_relative_to(tmp_path / ".simplicio" / "prototypes")
    assert any(candidate.iterdir())

    # ...and the working-tree source file is byte-for-byte untouched.
    assert source_file.read_bytes() == b"print('real working tree file')\n"


def test_scaffold_refuses_to_overwrite_existing_candidate_without_force(tmp_path, capsys):
    _, plan_path = _make_plan(tmp_path, capsys, prototype_type="code_spike")
    cli.main(["prototype", "scaffold", "--root", str(tmp_path), "--plan", str(plan_path)])
    capsys.readouterr()

    code = cli.main(["prototype", "scaffold", "--root", str(tmp_path), "--plan", str(plan_path), "--json"])
    err = capsys.readouterr().err

    assert code == 2
    assert "use --force explicitly" in err


def test_dry_run_proves_zero_working_tree_change(tmp_path, capsys):
    (tmp_path / "src.py").write_text("value = 1\n", encoding="utf-8")
    plan, plan_path = _make_plan(tmp_path, capsys, prototype_type="code_spike")
    assert plan["source_sha"]

    code = cli.main(["prototype", "scaffold", "--root", str(tmp_path), "--plan", str(plan_path), "--json"])
    assert code == 0
    capsys.readouterr()

    before = _tree_hash(tmp_path)
    code = cli.main(["prototype", "dry-run", "--root", str(tmp_path), "--plan", str(plan_path), "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    after = _tree_hash(tmp_path)

    assert before == after, "dry-run must never mutate the working tree"
    assert payload["kind"] == "dry-run"
    assert payload["writes"]  # proves it inspected the candidate, not a no-op


def test_validate_runs_real_validator_and_captures_evidence(tmp_path, capsys):
    plan_path = _plan_from_input(
        tmp_path,
        capsys,
        goal="run a real command",
        validators=[f"{PYTHON} -c \"print('validator ran for real')\""],
    )
    cli.main(["prototype", "scaffold", "--root", str(tmp_path), "--plan", str(plan_path), "--json"])
    capsys.readouterr()

    code = cli.main(["prototype", "validate", "--root", str(tmp_path), "--plan", str(plan_path), "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["kind"] == "validation"
    assert payload["valid"] is True
    assert len(payload["validators"]) == 1
    assert payload["validators"][0]["exit_code"] == 0
    assert "validator ran for real" in payload["validators"][0]["stdout"]


def test_validate_captures_a_real_failure_not_a_stub_pass(tmp_path, capsys):
    plan_path = _plan_from_input(
        tmp_path, capsys, goal="fail on purpose", validators=[f'{PYTHON} -c "import sys; sys.exit(7)"']
    )
    cli.main(["prototype", "scaffold", "--root", str(tmp_path), "--plan", str(plan_path)])
    capsys.readouterr()

    code = cli.main(["prototype", "validate", "--root", str(tmp_path), "--plan", str(plan_path), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 1
    assert payload["valid"] is False
    assert payload["validators"][0]["exit_code"] == 7


def test_promote_refuses_without_any_decision_file(tmp_path, capsys):
    plan_path, candidate = _scaffold_and_validate(tmp_path, capsys, validators=[f'{PYTHON} -c "pass"'])
    target = tmp_path / "promoted"

    code = cli.main(
        [
            "prototype",
            "promote",
            "--root",
            str(tmp_path),
            "--plan",
            str(plan_path),
            "--candidate",
            str(candidate),
            "--target",
            str(target),
            "--json",
        ]
    )

    assert code == 2
    err = capsys.readouterr().err
    assert "cannot read JSON artifact" in err
    assert not target.exists()


def test_promote_refuses_a_forged_decision_file(tmp_path, capsys):
    plan_path, candidate = _scaffold_and_validate(tmp_path, capsys, validators=[f'{PYTHON} -c "pass"'])
    target = tmp_path / "promoted"

    forged = _artifacts_dir(tmp_path) / "forged-decision.json"
    forged.write_text(
        json.dumps(
            {
                "schema": "simplicio.prototype-decision/v1",
                "decision": "ACCEPT",
                "plan_hash": "not-the-real-plan-hash",
                "candidate_hash": "not-the-real-candidate-hash",
            }
        ),
        encoding="utf-8",
    )

    code = cli.main(
        [
            "prototype",
            "promote",
            "--root",
            str(tmp_path),
            "--plan",
            str(plan_path),
            "--candidate",
            str(candidate),
            "--decision",
            str(forged),
            "--target",
            str(target),
            "--json",
        ]
    )

    assert code == 2
    err = capsys.readouterr().err
    assert "promote requires a current ACCEPT decision receipt" in err
    assert not target.exists()


def test_promote_succeeds_with_a_valid_accept_decision_and_revalidates(tmp_path, capsys):
    plan_path, candidate = _scaffold_and_validate(tmp_path, capsys, validators=[f'{PYTHON} -c "pass"'])
    # Promotion target lives OUTSIDE --root deliberately: promoting into the
    # tracked source tree would itself change that tree's hash, which the
    # post-promotion revalidation step below would then (correctly) flag as
    # stale — that's a real, separate concern (re-plan against the new state),
    # not what this test is exercising.
    target = tmp_path.parent / (tmp_path.name + "-promoted")
    receipt = json.loads((candidate / ".prototype-receipt.json").read_text(encoding="utf-8"))

    decision_path = _artifacts_dir(tmp_path) / "decision.json"
    decision_path.write_text(
        json.dumps(
            {
                "schema": "simplicio.prototype-decision/v1",
                "decision": "ACCEPT",
                "plan_hash": receipt["plan_hash"],
                "candidate_hash": receipt["candidate_hash"],
            }
        ),
        encoding="utf-8",
    )

    code = cli.main(
        [
            "prototype",
            "promote",
            "--root",
            str(tmp_path),
            "--plan",
            str(plan_path),
            "--candidate",
            str(candidate),
            "--decision",
            str(decision_path),
            "--target",
            str(target),
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["decision"] == "ACCEPT"
    assert target.is_dir()
    assert (target / "spike.py").is_file()

    # Post-promotion revalidation (AC #9): validate can be re-run against the
    # same candidate sandbox after promotion and still finds real evidence.
    code = cli.main(
        [
            "prototype",
            "validate",
            "--root",
            str(tmp_path),
            "--plan",
            str(plan_path),
            "--candidate",
            str(candidate),
            "--json",
        ]
    )
    revalidated = json.loads(capsys.readouterr().out)
    assert code == 0
    assert revalidated["valid"] is True


def test_stale_candidate_is_detected_and_rejected_at_validate(tmp_path, capsys):
    (tmp_path / "src.py").write_text("value = 1\n", encoding="utf-8")
    plan, plan_path = _make_plan(tmp_path, capsys, prototype_type="code_spike")
    assert plan["source_sha"]  # sanity: a real baseline was recorded

    cli.main(["prototype", "scaffold", "--root", str(tmp_path), "--plan", str(plan_path)])
    capsys.readouterr()

    # Mutate the working tree *after* the plan/candidate were created.
    (tmp_path / "src.py").write_text("value = 2  # changed after planning\n", encoding="utf-8")

    code = cli.main(["prototype", "validate", "--root", str(tmp_path), "--plan", str(plan_path), "--json"])
    err = capsys.readouterr().err

    assert code == 2
    assert "stale candidate" in err


def test_stale_candidate_is_detected_and_rejected_at_promote(tmp_path, capsys):
    (tmp_path / "src.py").write_text("value = 1\n", encoding="utf-8")
    plan_path, candidate = _scaffold_and_validate(tmp_path, capsys, validators=[f'{PYTHON} -c "pass"'])
    receipt = json.loads((candidate / ".prototype-receipt.json").read_text(encoding="utf-8"))
    decision_path = _artifacts_dir(tmp_path) / "decision.json"
    decision_path.write_text(
        json.dumps(
            {
                "schema": "simplicio.prototype-decision/v1",
                "decision": "ACCEPT",
                "plan_hash": receipt["plan_hash"],
                "candidate_hash": receipt["candidate_hash"],
            }
        ),
        encoding="utf-8",
    )

    # Source changes after validate already produced a fresh, valid receipt.
    (tmp_path / "src.py").write_text("value = 999  # drifted post-validation\n", encoding="utf-8")

    target = tmp_path / "promoted"
    code = cli.main(
        [
            "prototype",
            "promote",
            "--root",
            str(tmp_path),
            "--plan",
            str(plan_path),
            "--candidate",
            str(candidate),
            "--decision",
            str(decision_path),
            "--target",
            str(target),
            "--json",
        ]
    )
    err = capsys.readouterr().err

    assert code == 2
    assert "stale candidate" in err
    assert not target.exists()


def test_reject_writes_a_reject_decision(tmp_path, capsys):
    plan_path, candidate = _scaffold_and_validate(
        tmp_path, capsys, validators=[f'{PYTHON} -c "import sys; sys.exit(1)"']
    )

    code = cli.main(
        [
            "prototype",
            "reject",
            "--root",
            str(tmp_path),
            "--plan",
            str(plan_path),
            "--candidate",
            str(candidate),
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["decision"] == "REJECT"
    decision_on_disk = json.loads((candidate / ".prototype-decision.json").read_text(encoding="utf-8"))
    assert decision_on_disk["decision"] == "REJECT"


def test_diff_reports_added_and_removed_files_between_target_and_candidate(tmp_path, capsys):
    target = tmp_path / "target"
    target.mkdir()
    (target / "existing.py").write_text("existing = True\n", encoding="utf-8")

    plan_path, candidate = _scaffold_and_validate(tmp_path, capsys, validators=[f'{PYTHON} -c "pass"'])

    code = cli.main(
        [
            "prototype",
            "diff",
            "--root",
            str(tmp_path),
            "--plan",
            str(plan_path),
            "--candidate",
            str(candidate),
            "--target",
            str(target),
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert "spike.py" in payload["added"]
    assert payload["removed"] == ["existing.py"]
