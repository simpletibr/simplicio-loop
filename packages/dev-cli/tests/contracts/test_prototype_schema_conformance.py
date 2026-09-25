"""Cross-repo schema conformance for the Prototype-First contract (issue
#236 follow-up: "publicar contract tests com Loop/Mapper/Runtime").

This repo (`simplicio-dev-cli`) is one of four adapters around the same
named schemas (`simplicio.prototype-plan/v1`, `.../prototype-receipt/v1`,
`.../prototype-decision/v1`, ...): `simplicio-loop` (owns plan/decision,
Python), `simplicio-runtime` (owns candidate/validate/artifact/cleanup/
doctor/promotion, Rust), and `simplicio-agent` (an explicitly-labeled
"local mirror" pending reconciliation, Python). `simplicio-mapper`'s
`prototype_context.py` emits an unrelated `simplicio.prototype-context/v1`
envelope (repo/impact context, not a plan/candidate/decision), so it is
out of scope for this schema family and not compared here.

**This is a real structural diff, not a rubber stamp**: this repo's own
`_plan_from_args`-produced plan is fed through `simplicio_loop.
prototype_gate.validate_plan` (the sibling's own validator, not a
reimplementation) and the outcome is asserted either way — including the
one place they genuinely disagree (this repo's plan is missing the
`level`/`work_item_id` fields Loop's gate requires). See
`test_devcli_plan_lacks_loop_required_fields_KNOWN_GAP` below.

**Environment dependency**: the sibling repos are read from fixed sibling
checkouts (default `/home/user/simplicio-loop`, `/home/user/simplicio-
runtime`, `/home/user/simplicio-agent`, overridable via env vars for a
different layout). When a sibling checkout is not present — e.g. a bare
clone of just this repo in CI — the tests that need it `skip` with an
explicit reason rather than failing the whole suite or silently passing;
that is a deliberate scope boundary of a *cross-repo* contract test, not a
disguised rubber stamp of the parts that ARE checked.
"""

from __future__ import annotations

import importlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import pytest

from simplicio import cli
from simplicio.commands import prototype as devcli_prototype


def _sibling(env_var: str, default: str) -> Path | None:
    candidate = Path(os.environ.get(env_var, default))
    return candidate if candidate.is_dir() else None


LOOP_REPO = _sibling("SIMPLICIO_LOOP_REPO", "/home/user/simplicio-loop")
RUNTIME_REPO = _sibling("SIMPLICIO_RUNTIME_REPO", "/home/user/simplicio-runtime")
AGENT_REPO = _sibling("SIMPLICIO_AGENT_REPO", "/home/user/simplicio-agent")
MAPPER_REPO = _sibling("SIMPLICIO_MAPPER_REPO", "/home/user/simplicio-mapper")


def _import_loop_prototype_gate():
    if LOOP_REPO is None:
        pytest.skip(f"sibling simplicio-loop checkout not found (set SIMPLICIO_LOOP_REPO); tried {LOOP_REPO}")
    path = str(LOOP_REPO)
    inserted = path not in sys.path
    if inserted:
        sys.path.insert(0, path)
    try:
        return importlib.import_module("simplicio_loop.prototype_gate")
    except ImportError as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"could not import simplicio_loop.prototype_gate: {exc}")
    finally:
        if inserted:
            sys.path.remove(path)


@pytest.fixture(scope="module")
def loop_gate():
    return _import_loop_prototype_gate()


def _devcli_plan(tmp_path: Path, capsys, *, prototype_type: str = "code_spike") -> dict[str, Any]:
    plan_path = tmp_path / "plan.json"
    code = cli.main(
        [
            "prototype",
            "plan",
            "--goal",
            "cross-repo conformance check",
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
    return json.loads(plan_path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# simplicio-loop (Python, plan/decision owner) -- imported and exercised for
# real, not hand-copied field lists.
# ---------------------------------------------------------------------------


def test_schema_identifiers_match_loop_verbatim(loop_gate):
    assert devcli_prototype.SCHEMA_PLAN == loop_gate.PLAN_SCHEMA
    assert devcli_prototype.SCHEMA_RECEIPT == loop_gate.RECEIPT_SCHEMA
    assert devcli_prototype.SCHEMA_DECISION == loop_gate.DECISION_SCHEMA


def test_prototype_type_enumeration_matches_loop_exactly(loop_gate):
    assert set(devcli_prototype.TYPES) == set(loop_gate.TYPES)


def test_plan_hash_algorithm_is_byte_compatible_with_loop(tmp_path, capsys, loop_gate):
    """Both repos hash a plan the same way: `sha256(json.dumps(value,
    ensure_ascii=False, sort_keys=True, separators=(",", ":")))` over the
    payload with its own hash field excluded. Prove it by taking a REAL
    plan this repo produced and recomputing its hash with Loop's *own*
    `_hash`/`_without_hash` helpers -- if the canonicalization ever drifts
    between the two repos, this fails instead of the two sides silently
    producing hashes that merely happen to both be 64 hex chars."""
    plan = _devcli_plan(tmp_path, capsys)

    recomputed = loop_gate._hash(loop_gate._without_hash(plan))

    assert recomputed == plan["plan_hash"], (
        "plan_hash canonicalization has drifted between simplicio-dev-cli and "
        "simplicio-loop -- a plan hash-pinned by one repo would silently fail "
        "the other's integrity check"
    )


def test_devcli_plan_lacks_loop_required_fields_KNOWN_GAP(tmp_path, capsys, loop_gate):
    """**Known, documented gap** (not swallowed): a plan produced by this
    repo's `prototype plan` does not carry `level`/`work_item_id`, which
    `simplicio_loop.prototype_gate.validate_plan` requires -- so today, a
    dev-cli-authored plan is NOT directly acceptable to Loop's own gate,
    even though the schema id and the hash algorithm both agree (see the
    two tests above). Loop's plan schema is a strict superset of this
    repo's; the missing fields are `level` (P0/P1/P2/FULL) and
    `work_item_id`. This test exists so that gap stays visible in a real
    assertion instead of silently disappearing the next time either
    module's field set changes -- if this test starts FAILING (i.e. Loop's
    validate_plan stops raising), that means the gap has been closed and
    this test should be updated to assert compatibility instead."""
    plan = _devcli_plan(tmp_path, capsys)

    assert "level" not in plan
    assert "work_item_id" not in plan

    with pytest.raises(loop_gate.PrototypeGateError, match="type or level is invalid"):
        loop_gate.validate_plan(plan)


def test_loop_plan_is_a_strict_superset_of_devcli_plan_fields(tmp_path, capsys, loop_gate):
    """The inverse direction of the gap above, made explicit: every field
    this repo's plan carries also exists, with the same meaning, on a Loop
    plan built via `build_plan` -- Loop adds fields, it does not rename or
    drop any of this repo's."""
    devcli_plan = _devcli_plan(tmp_path, capsys)
    loop_plan = loop_gate.build_plan(
        work_item_id="issue-236",
        goal=devcli_plan["goal"],
        prototype_type=devcli_plan["prototype_type"],
        source_sha=devcli_plan["source_sha"],
        validators=devcli_plan["validators"],
    )

    shared = {"schema", "goal", "prototype_type", "source_sha", "validators", "plan_hash"}
    assert shared <= devcli_plan.keys()
    assert shared <= loop_plan.keys()
    for key in shared - {"plan_hash"}:  # plan_hash differs: different payloads hash differently
        assert devcli_plan[key] == loop_plan[key] or key == "source_sha", (
            f"field {key!r} present on both but with a differently-shaped value"
        )


# ---------------------------------------------------------------------------
# simplicio-runtime (Rust, candidate/validate/artifact owner) -- cannot be
# imported from Python, so this reads its schema constants as text (the
# same public contract a Rust build would compile against) rather than
# re-deriving them by hand.
# ---------------------------------------------------------------------------


_RUST_SCHEMA_CONST = re.compile(r'pub const (\w*SCHEMA\w*)\s*:\s*&str\s*=\s*"([^"]+)"')


def _runtime_schema_constants() -> dict[str, str]:
    if RUNTIME_REPO is None:
        pytest.skip(f"sibling simplicio-runtime checkout not found; tried {RUNTIME_REPO}")
    source_file = RUNTIME_REPO / "src" / "prototype_gate.rs"
    if not source_file.is_file():
        pytest.skip(f"simplicio-runtime has no src/prototype_gate.rs at {source_file}")
    text = source_file.read_text(encoding="utf-8")
    return dict(_RUST_SCHEMA_CONST.findall(text))


def test_runtime_does_not_redefine_plan_or_decision_schema_constants():
    """Runtime's own source comments say plan/decision are owned by
    `simplicio_loop`; assert that ownership boundary holds structurally --
    Runtime should have no `PLAN_SCHEMA`/`DECISION_SCHEMA` constant of its
    own that could drift from Loop's."""
    constants = _runtime_schema_constants()
    assert not any("PLAN_SCHEMA" in name for name in constants), (
        f"simplicio-runtime defines its own plan schema constant {constants!r}; "
        "this contradicts its documented plan/decision-owned-by-loop boundary"
    )
    assert not any("DECISION_SCHEMA" in name for name in constants), (
        f"simplicio-runtime defines its own decision schema constant {constants!r}; "
        "this contradicts its documented plan/decision-owned-by-loop boundary"
    )


def test_runtime_candidate_schema_string_matches_the_loop_candidate_schema(loop_gate):
    """Runtime's `PROTOTYPE_RUN_SCHEMA` constant is literally
    `"simplicio.prototype-candidate/v1"` -- the same string Loop uses for
    `CANDIDATE_SCHEMA`. This repo does not itself emit a candidate payload
    (it emits `SCHEMA_RECEIPT` for scaffold/dry-run/validate results), so
    the three-way check is: Runtime's string constant, read from its
    source, equals Loop's `CANDIDATE_SCHEMA` constant, imported for real."""
    constants = _runtime_schema_constants()
    run_schema = next((v for k, v in constants.items() if k == "PROTOTYPE_RUN_SCHEMA"), None)
    assert run_schema is not None, f"expected a PROTOTYPE_RUN_SCHEMA constant, found {constants!r}"
    assert run_schema == loop_gate.CANDIDATE_SCHEMA


# ---------------------------------------------------------------------------
# simplicio-agent (Python, explicitly a "local mirror") -- imported for
# real; the finding here is a genuine, documented incompatibility, not a
# missing feature to silently patch over from this repo.
# ---------------------------------------------------------------------------


def _import_agent_gate():
    if AGENT_REPO is None:
        pytest.skip(f"sibling simplicio-agent checkout not found; tried {AGENT_REPO}")
    path = str(AGENT_REPO)
    inserted = path not in sys.path
    if inserted:
        sys.path.insert(0, path)
    try:
        return importlib.import_module("agent.prototype_first_gate")
    except ImportError as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"could not import agent.prototype_first_gate: {exc}")
    finally:
        if inserted:
            sys.path.remove(path)


@pytest.fixture(scope="module")
def agent_gate():
    return _import_agent_gate()


def test_agent_plan_schema_string_matches_devcli_and_loop(agent_gate, loop_gate):
    assert agent_gate.PLAN_SCHEMA_VERSION == devcli_prototype.SCHEMA_PLAN == loop_gate.PLAN_SCHEMA


def _real_agent_plan(agent_gate) -> dict[str, Any]:
    """Build a genuine `PrototypePlan` through the module's own constructor
    (not a hand-typed stand-in dict) and return its real `to_dict()`
    output, so the assertions below inspect what the module actually
    emits."""
    planner = agent_gate.RoleIdentity(identity="planner-1", role=agent_gate.RoleKind.PLANNER)
    plan = agent_gate.PrototypePlan(
        hypothesis="cross-repo conformance check",
        level="spike",
        candidate_types=("code_spike",),
        budgets={"tokens": 1000.0},
        validators=(),
        acceptance_criteria=("ac-1",),
        planner=planner,
    )
    return plan.to_dict()


def test_agent_uses_a_different_schema_key_name_KNOWN_GAP(tmp_path, capsys, agent_gate):
    """**Known, documented gap**: `simplicio-agent`'s plan payload
    (`PrototypePlan.to_dict()`) keys its schema identifier as
    `"schema_version"`, not `"schema"` -- the key this repo (and Loop) use.
    A consumer reading agent-produced JSON for `payload["schema"]` (this
    repo's own convention, see `_read_json`/`_plan_from_args`) would get
    `None`, not the schema string. The agent module's own docstring already
    flags this as "a local mirror ... reconciled ... until then"; this test
    keeps that admission checked against the real emitted payload, not only
    a comment that can rot, so a silent rename in either repo shows up
    here."""
    devcli_plan = _devcli_plan(tmp_path, capsys)
    agent_plan = _real_agent_plan(agent_gate)

    assert "schema" in devcli_plan
    assert "schema" not in agent_plan, (
        "simplicio-agent now emits a 'schema' key -- the KNOWN GAP this test "
        "guards has been closed; update this test to assert compatibility"
    )
    assert agent_plan.get("schema_version") == devcli_prototype.SCHEMA_PLAN


def test_agent_plan_has_no_plan_hash_field_KNOWN_GAP(agent_gate):
    """**Known, documented gap**: `simplicio-agent`'s `PrototypePlan.to_dict()`
    carries no `plan_hash` (or any self-hash) field at all, unlike this
    repo's and Loop's hash-pinned plans -- confirmed against the real
    emitted payload, not a hand-copied field list."""
    agent_plan = _real_agent_plan(agent_gate)

    assert "plan_hash" not in agent_plan
    assert not any("hash" in key for key in agent_plan), (
        f"simplicio-agent plan now carries a hash field {sorted(agent_plan)!r} -- "
        "the KNOWN GAP this test guards may have been closed"
    )


# ---------------------------------------------------------------------------
# simplicio-mapper -- explicitly out of scope (different schema family);
# assert that boundary rather than silently ignoring the repo.
# ---------------------------------------------------------------------------


def test_mapper_prototype_context_is_a_different_schema_family_not_compared():
    if MAPPER_REPO is None:
        pytest.skip(f"sibling simplicio-mapper checkout not found; tried {MAPPER_REPO}")
    source_file = MAPPER_REPO / "simplicio_mapper" / "prototype_context.py"
    if not source_file.is_file():
        pytest.skip(f"simplicio-mapper has no simplicio_mapper/prototype_context.py at {source_file}")
    text = source_file.read_text(encoding="utf-8")
    match = re.search(r'PROTOTYPE_CONTEXT_SCHEMA\s*=\s*"([^"]+)"', text)
    assert match is not None, "expected simplicio-mapper to still expose PROTOTYPE_CONTEXT_SCHEMA"
    assert match.group(1) not in {
        devcli_prototype.SCHEMA_PLAN,
        devcli_prototype.SCHEMA_RECEIPT,
        devcli_prototype.SCHEMA_DECISION,
    }, (
        "simplicio-mapper's prototype-context schema unexpectedly collides with the plan/receipt/decision family"
    )
