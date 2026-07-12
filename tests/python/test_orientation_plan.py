from __future__ import annotations

from dataclasses import replace
from hashlib import sha256

import pytest

from simplicio.execution_contract import compile_execution_contract
from simplicio.orientation_plan import (
    FlowEvidence,
    OrientationBlockedError,
    PlanInvalidatedError,
    RepositoryEvidence,
    TargetEvidence,
    _layer_order_rationale,
    build_execution_plan,
)


def _task(*, frontend: str = "yes", backend: str = "no") -> dict:
    return {
        "schema": "simplicio.task-spec/v2",
        "task_id": "planes-order",
        "source_hash": sha256(b"planes").hexdigest(),
        "source": {"kind": "text", "original_text": "planes"},
        "language": "pt-BR",
        "system": "PLANES",
        "functionality": "Ordenacao",
        "task_type": "Evolucao",
        "narrative": {"as_a": "analista", "i_want": "ordenar", "so_that": "analisar"},
        "acceptance_criteria": [
            {
                "id": "AC1",
                "title": "ordena",
                "given": "linhas",
                "when": "exibe",
                "then": "ordena por data",
                "business_rule_refs": ["RN01"],
            }
        ],
        "business_rules": [{"id": "RN01", "text": "data crescente"}],
        "impact_signals": {
            "frontend": {"status": frontend},
            "backend": {"status": backend},
        },
        "original_text": "planes",
    }


def _contract(task: dict):
    return compile_execution_contract(task)


def _target(repo: str, path: str, layer: str, **changes) -> TargetEvidence:
    values = {
        "repo_id": repo,
        "path": path,
        "layer": layer,
        "disposition": "change",
        "responsibility": "apply stable ordering",
        "rationale": "mapper rules and callers locate ordering here",
        "acceptance_criteria": ("AC1",),
        "business_rules": ("RN01",),
        "precedents": ("existing stable sort",),
        "tests": ("tests/test_order.py",),
        "verify_command": "pytest tests/test_order.py",
        "blast_radius": (path,),
    }
    values.update(changes)
    return TargetEvidence(**values)


def _repo(repo: str, *targets: TargetEvidence, flows=()) -> RepositoryEvidence:
    return RepositoryEvidence(
        repo_id=repo,
        root=f"/{repo}",
        root_hash=f"root-{repo}",
        pack_hash=f"pack-{repo}",
        fresh=True,
        terminal=True,
        artifacts_complete=True,
        queries_run=("impact", "tests-for", "callers", "flows", "rules"),
        targets=targets,
        flows=flows,
    )


def test_frontend_only_plan_is_stable_and_contains_traceability() -> None:
    task = _task()
    repo = _repo("web", _target("web", "src/modeling/order.ts", "state"))

    first = build_execution_plan(task, _contract(task), [repo])
    second = build_execution_plan(task, _contract(task), [repo])

    assert first.plan_hash == second.plan_hash
    assert first.to_dict()["plan_hash"] == first.plan_hash
    assert first.slices[0].acceptance_criteria == ("AC1",)
    assert first.slices[0].operator == "simplicio-dev-cli"


def test_backend_possible_requires_measured_investigation() -> None:
    task = _task(backend="possible")
    repo = _repo("web", _target("web", "src/modeling/order.ts", "state"))

    with pytest.raises(OrientationBlockedError, match="backend.*not measurably investigated"):
        build_execution_plan(task, _contract(task), [repo])


def test_backend_sorted_plan_can_record_frontend_no_change() -> None:
    task = _task(frontend="possible", backend="yes")
    repo = _repo(
        "app",
        _target(
            "app",
            "src/view.ts",
            "ui",
            disposition="no-change",
            acceptance_criteria=(),
            precedents=(),
            tests=(),
            verify_command="",
            rationale="UI preserves API order without a local sort",
        ),
        _target("app", "src/api/order.py", "backend"),
    )

    plan = build_execution_plan(task, _contract(task), [repo])

    assert [item.targets for item in plan.slices] == [("src/api/order.py",)]


def test_full_stack_requires_and_preserves_explicit_flow() -> None:
    task = _task(backend="yes")
    ui = _target("app", "src/ui.tsx", "ui")
    api = _target("app", "src/api.py", "backend", dependencies=("src/ui.tsx",))
    flow = FlowEvidence("modeling", ("src/ui.tsx", "src/api.py"), "UI consumes API order")

    plan = build_execution_plan(task, _contract(task), [_repo("app", ui, api, flows=(flow,))])

    assert plan.flows == (flow,)
    assert plan.slices[1].dependencies == ("slice-002",) or plan.slices[0].dependencies


def test_full_stack_recorded_slices_carry_layer_ordering_rationale() -> None:
    task = _task(backend="yes")
    ui = _target("app", "src/ui.tsx", "ui")
    api = _target("app", "src/api.py", "backend")

    plan = build_execution_plan(task, _contract(task), [_repo("app", ui, api)])

    by_id = {item.slice_id: item for item in plan.slices}
    ui_slice = next(item for item in plan.slices if item.layer == "ui")
    api_slice = next(item for item in plan.slices if item.layer == "backend")
    assert ui_slice.ordering_rationale == _layer_order_rationale("ui")
    assert api_slice.ordering_rationale == _layer_order_rationale("backend")
    assert "no local re-sort" in ui_slice.ordering_rationale
    assert "canonical order" in api_slice.ordering_rationale
    assert "ordering_rationale" in by_id[ui_slice.slice_id].to_dict()


def test_full_stack_without_flow_auto_derives_ui_backend_ordering() -> None:
    task = _task(backend="yes")
    ui = _target("app", "src/ui.tsx", "ui")
    api = _target("app", "src/api.py", "backend")

    plan = build_execution_plan(task, _contract(task), [_repo("app", ui, api)])

    derived = [flow for flow in plan.flows if flow.name == "derived-ui-backend-ordering"]
    assert derived, "expected an auto-derived full-stack ordering flow"
    assert set(derived[0].targets) == {"src/ui.tsx", "src/api.py"}
    # Existing mapper-supplied flows are preserved, not shadowed.
    explicit = FlowEvidence("modeling", ("src/ui.tsx", "src/api.py"), "UI consumes API order")
    plan2 = build_execution_plan(task, _contract(task), [_repo("app", ui, api, flows=(explicit,))])
    assert plan2.flows == (explicit,)



def test_monorepo_records_operator_and_anchor_per_repo() -> None:
    task = _task(backend="yes")
    ui = _target("web", "src/ui.tsx", "ui")
    api = _target("api", "src/api.py", "backend")
    flow = FlowEvidence("modeling", ("src/ui.tsx", "src/api.py"), "cross-repo request")
    web = _repo("web", ui, flows=(flow,))
    backend = _repo("api", api)

    plan = build_execution_plan(task, _contract(task), [web, backend])

    assert {item.repo_id for item in plan.repositories} == {"web", "api"}
    assert {item.operator for item in plan.repositories} == {"simplicio-dev-cli"}


@pytest.mark.parametrize(
    ("repo_change", "message"),
    [
        ({"fresh": False}, "stale/incomplete"),
        ({"queries_run": ("impact",)}, "missing"),
    ],
)
def test_mapper_stale_or_incomplete_blocks_with_recovery(repo_change, message) -> None:
    task = _task()
    repo = replace(_repo("web", _target("web", "src/ui.ts", "ui")), **repo_change)

    with pytest.raises(OrientationBlockedError, match=message):
        build_execution_plan(task, _contract(task), [repo])


def test_ambiguous_target_and_unreviewed_shared_dependents_block() -> None:
    task = _task()
    ambiguous = _target("web", "src/a.ts", "ui", disposition="candidate")
    shared = _target("web", "src/b.ts", "state", dependents=("src/c.ts",))

    with pytest.raises(OrientationBlockedError) as exc_info:
        build_execution_plan(task, _contract(task), [_repo("web", ambiguous, shared)])

    assert "remains ambiguous" in str(exc_info.value)
    assert "unreviewed dependents" in str(exc_info.value)


def test_frozen_plan_invalidates_on_task_contract_or_repo_drift() -> None:
    task = _task()
    contract = _contract(task)
    repo = _repo("web", _target("web", "src/ui.ts", "ui"))
    plan = build_execution_plan(task, contract, [repo])

    plan.assert_current(
        task_source_hash=task["source_hash"],
        contract_hash=contract.contract_hash,
        repositories={"web": ("root-web", "pack-web")},
    )
    with pytest.raises(PlanInvalidatedError, match="TaskSpec"):
        plan.assert_current(
            task_source_hash="changed",
            contract_hash=contract.contract_hash,
            repositories={"web": ("root-web", "pack-web")},
        )
