"""Deterministic, fail-closed orientation plans built from mapper evidence."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from .execution_contract import ExecutionContract

ORIENTATION_PLAN_SCHEMA = "simplicio.orientation-plan/v1"
REQUIRED_QUERIES = frozenset({"impact", "tests-for", "callers", "flows", "rules"})
_FRONTEND_LAYERS = frozenset({"ui", "frontend", "state", "query"})
_BACKEND_LAYERS = frozenset({"api", "backend", "service", "repository"})


class OrientationBlockedError(ValueError):
    """Raised when mapper evidence cannot support a non-arbitrary plan."""

    def __init__(self, diagnostics: Sequence[str]) -> None:
        self.diagnostics = tuple(diagnostics)
        super().__init__("; ".join(self.diagnostics))


class PlanInvalidatedError(RuntimeError):
    """Raised when a frozen plan no longer matches its task or repositories."""


@dataclass(frozen=True)
class TargetEvidence:
    repo_id: str
    path: str
    layer: str
    disposition: str
    responsibility: str
    rationale: str
    acceptance_criteria: tuple[str, ...]
    business_rules: tuple[str, ...]
    precedents: tuple[str, ...]
    tests: tuple[str, ...]
    verify_command: str
    dependencies: tuple[str, ...] = ()
    blast_radius: tuple[str, ...] = ()
    dependents: tuple[str, ...] = ()
    reviewed_dependents: tuple[str, ...] = ()


@dataclass(frozen=True)
class FlowEvidence:
    name: str
    targets: tuple[str, ...]
    rationale: str


@dataclass(frozen=True)
class RepositoryEvidence:
    repo_id: str
    root: str
    root_hash: str
    pack_hash: str
    fresh: bool
    terminal: bool
    artifacts_complete: bool
    queries_run: tuple[str, ...]
    targets: tuple[TargetEvidence, ...]
    flows: tuple[FlowEvidence, ...] = ()
    operator: str = "simplicio-dev-cli"
    recovery_action: str = "simplicio-mapper scan <repo> --sync --json"


@dataclass(frozen=True)
class PlanSlice:
    slice_id: str
    repo_id: str
    operator: str
    targets: tuple[str, ...]
    layer: str
    responsibility: str
    rationale: str
    acceptance_criteria: tuple[str, ...]
    business_rules: tuple[str, ...]
    precedents: tuple[str, ...]
    tests: tuple[str, ...]
    verify_command: str
    dependencies: tuple[str, ...]
    blast_radius: tuple[str, ...]
    ordering_rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "slice_id": self.slice_id,
            "repo_id": self.repo_id,
            "operator": self.operator,
            "targets": list(self.targets),
            "layer": self.layer,
            "responsibility": self.responsibility,
            "rationale": self.rationale,
            "acceptance_criteria": list(self.acceptance_criteria),
            "business_rules": list(self.business_rules),
            "precedents": list(self.precedents),
            "tests": list(self.tests),
            "verify_command": self.verify_command,
            "dependencies": list(self.dependencies),
            "blast_radius": list(self.blast_radius),
            "ordering_rationale": self.ordering_rationale,
        }


# Per-layer ordering rationale recorded on each slice so the frozen plan explains
# *why* sorting/ordering happens at that specific layer. Issue #117:
# "registra por que a ordenacao sera feita em cada camada".
_LAYER_ORDER_RATIONALE: dict[str, str] = {
    "ui": "UI renders the order produced by the state/backend layer; no local re-sort is applied.",
    "frontend": "Frontend reflects the canonical order from the backend; ordering is not changed here.",
    "state": "State layer propagates the backend order to the view so the UI stays consistent.",
    "query": "Query layer applies the canonical backend order before the view consumes it.",
    "api": "API/backend owns the canonical order; apply ordering here so all consumers agree.",
    "backend": "Backend owns the canonical order; apply ordering here so all consumers agree.",
    "service": "Service layer applies the canonical order upstream of the API boundary.",
    "repository": "Repository layer persists the canonical order before it propagates upward.",
}


def _layer_order_rationale(layer: str) -> str:
    return _LAYER_ORDER_RATIONALE.get(
        layer,
        "Layer ordering rationale not classified; review mapper evidence for this layer.",
    )


def _derive_full_stack_flow(
    changed_frontend: Sequence[TargetEvidence],
    changed_backend: Sequence[TargetEvidence],
    flows: tuple[FlowEvidence, ...],
) -> tuple[FlowEvidence, ...]:
    """Auto-derive a UI -> state/query -> API/backend ordering flow when a full-stack
    change exists but no mapper-supplied flow already connects both ends.

    Returns ``flows`` unchanged when either side is missing or an existing flow already
    covers the frontend/backend pair (issue #117: never shadow measured mapper evidence).
    """
    if not changed_frontend or not changed_backend:
        return flows
    frontend_paths = {item.path for item in changed_frontend}
    backend_paths = {item.path for item in changed_backend}
    already_covered = any(
        frontend_paths & set(flow.targets) and backend_paths & set(flow.targets)
        for flow in flows
    )
    if already_covered:
        return flows
    targets = tuple(item.path for item in (*changed_frontend, *changed_backend))
    derived = FlowEvidence(
        name="derived-ui-backend-ordering",
        targets=targets,
        rationale=(
            "Auto-derived UI->state/query->API/backend ordering because full-stack change "
            "targets exist without an explicit mapper flow connecting both ends."
        ),
    )
    return (*flows, derived)


@dataclass(frozen=True)
class RepositoryAnchor:
    repo_id: str
    root: str
    root_hash: str
    pack_hash: str
    operator: str

    def to_dict(self) -> dict[str, str]:
        return {
            "repo_id": self.repo_id,
            "root": self.root,
            "root_hash": self.root_hash,
            "pack_hash": self.pack_hash,
            "operator": self.operator,
        }


@dataclass(frozen=True)
class ExecutionPlan:
    task_id: str
    task_source_hash: str
    contract_hash: str
    pack_hash: str
    repositories: tuple[RepositoryAnchor, ...]
    slices: tuple[PlanSlice, ...]
    flows: tuple[FlowEvidence, ...]
    human_gates: tuple[str, ...]
    execution_ready: bool

    @property
    def plan_hash(self) -> str:
        canonical = json.dumps(
            self.to_dict(include_plan_hash=False),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return sha256(canonical.encode()).hexdigest()

    def to_dict(self, *, include_plan_hash: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema": ORIENTATION_PLAN_SCHEMA,
            "task_id": self.task_id,
            "task_source_hash": self.task_source_hash,
            "contract_hash": self.contract_hash,
            "pack_hash": self.pack_hash,
            "repositories": [item.to_dict() for item in self.repositories],
            "slices": [item.to_dict() for item in self.slices],
            "flows": [
                {"name": item.name, "targets": list(item.targets), "rationale": item.rationale}
                for item in self.flows
            ],
            "human_gates": list(self.human_gates),
            "execution_ready": self.execution_ready,
        }
        if include_plan_hash:
            payload["plan_hash"] = self.plan_hash
        return payload

    def assert_current(
        self,
        *,
        task_source_hash: str,
        contract_hash: str,
        repositories: Mapping[str, tuple[str, str]],
    ) -> None:
        failures: list[str] = []
        if task_source_hash != self.task_source_hash:
            failures.append("TaskSpec source hash changed")
        if contract_hash != self.contract_hash:
            failures.append("ExecutionContract changed")
        for anchor in self.repositories:
            current = repositories.get(anchor.repo_id)
            if current != (anchor.root_hash, anchor.pack_hash):
                failures.append(f"repository {anchor.repo_id!r} changed")
        if failures:
            raise PlanInvalidatedError("; ".join(failures) + "; re-orientation required")


def _task_payload(task: Any) -> Mapping[str, Any]:
    if hasattr(task, "to_dict"):
        value = task.to_dict()
    elif isinstance(task, Mapping):
        value = task
    else:
        raise TypeError("task must be a TaskSpec or mapping")
    if not isinstance(value, Mapping):
        raise TypeError("task to_dict() must return a mapping")
    return value


def _signal_status(task: Mapping[str, Any], name: str) -> str:
    signals = task.get("impact_signals", {})
    if not isinstance(signals, Mapping):
        return "unknown"
    signal = signals.get(name, {})
    if not isinstance(signal, Mapping):
        return "unknown"
    return str(signal.get("status", "unknown")).lower()


def _validate_repository(repo: RepositoryEvidence) -> list[str]:
    diagnostics: list[str] = []
    if not repo.terminal or not repo.fresh or not repo.artifacts_complete:
        diagnostics.append(
            f"mapper evidence for {repo.repo_id!r} is stale/incomplete; recovery: {repo.recovery_action}"
        )
    missing_queries = REQUIRED_QUERIES - set(repo.queries_run)
    if missing_queries:
        diagnostics.append(
            f"mapper investigation for {repo.repo_id!r} missing: {', '.join(sorted(missing_queries))}"
        )
    if not repo.root_hash or not repo.pack_hash:
        diagnostics.append(f"repository {repo.repo_id!r} has no root_hash/pack_hash")
    if repo.operator != "simplicio-dev-cli":
        diagnostics.append(f"repository {repo.repo_id!r} has unsupported operator {repo.operator!r}")
    for target in repo.targets:
        if target.repo_id != repo.repo_id:
            diagnostics.append(f"target {target.path!r} is assigned to the wrong repository")
        if target.disposition not in {"change", "review", "no-change"}:
            diagnostics.append(f"target {target.path!r} remains ambiguous")
        if not target.rationale.strip():
            diagnostics.append(f"target {target.path!r} has no mapper-backed rationale")
        unreviewed = set(target.dependents) - set(target.reviewed_dependents)
        if unreviewed:
            diagnostics.append(
                f"shared target {target.path!r} has unreviewed dependents: {', '.join(sorted(unreviewed))}"
            )
        if target.disposition == "change":
            missing = []
            if not target.acceptance_criteria:
                missing.append("acceptance criteria")
            if not target.precedents:
                missing.append("precedents")
            if not target.tests:
                missing.append("tests-for")
            if not target.verify_command.strip():
                missing.append("verify command")
            if missing:
                diagnostics.append(f"slice for {target.path!r} missing: {', '.join(missing)}")
    return diagnostics


def build_execution_plan(
    task: Any,
    contract: ExecutionContract,
    repositories: Sequence[RepositoryEvidence],
) -> ExecutionPlan:
    """Freeze mapper findings into a stable plan without choosing arbitrary targets."""

    task_payload = _task_payload(task)
    diagnostics: list[str] = []
    if not repositories:
        diagnostics.append("no mapper repositories were supplied")
    if str(task_payload.get("source_hash", "")) != contract.source_hash:
        diagnostics.append("TaskSpec and ExecutionContract source hashes differ")
    for repo in repositories:
        diagnostics.extend(_validate_repository(repo))

    targets = [target for repo in repositories for target in repo.targets]
    frontend = [target for target in targets if target.layer in _FRONTEND_LAYERS]
    backend = [target for target in targets if target.layer in _BACKEND_LAYERS]
    for signal, candidates in (("frontend", frontend), ("backend", backend)):
        if _signal_status(task_payload, signal) in {"yes", "possible"} and not candidates:
            diagnostics.append(f"impact signal {signal!r} was not measurably investigated")

    changed_frontend = tuple(item for item in frontend if item.disposition == "change")
    changed_backend = tuple(item for item in backend if item.disposition == "change")
    flows = _derive_full_stack_flow(
        changed_frontend,
        changed_backend,
        tuple(flow for repo in repositories for flow in repo.flows),
    )
    if changed_frontend and changed_backend:
        changed_paths = {item.path for item in (*changed_frontend, *changed_backend)}
        if not any(changed_paths.issubset(set(flow.targets)) for flow in flows):
            diagnostics.append("full-stack targets have no measured UI/state/API flow")

    if diagnostics:
        raise OrientationBlockedError(diagnostics)

    ordered_targets = sorted(
        (target for target in targets if target.disposition == "change"),
        key=lambda item: (item.repo_id, item.layer, item.path),
    )
    path_to_slice = {target.path: f"slice-{index:03d}" for index, target in enumerate(ordered_targets, 1)}
    repo_by_id = {repo.repo_id: repo for repo in repositories}
    slices = tuple(
        PlanSlice(
            slice_id=path_to_slice[target.path],
            repo_id=target.repo_id,
            operator=repo_by_id[target.repo_id].operator,
            targets=(target.path,),
            layer=target.layer,
            responsibility=target.responsibility,
            rationale=target.rationale,
            acceptance_criteria=target.acceptance_criteria,
            business_rules=target.business_rules,
            precedents=target.precedents,
            tests=target.tests,
            verify_command=target.verify_command,
            dependencies=tuple(path_to_slice.get(item, item) for item in target.dependencies),
            blast_radius=target.blast_radius,
            ordering_rationale=_layer_order_rationale(target.layer),
        )
        for target in ordered_targets
    )
    anchors = tuple(
        RepositoryAnchor(repo.repo_id, repo.root, repo.root_hash, repo.pack_hash, repo.operator)
        for repo in sorted(repositories, key=lambda item: item.repo_id)
    )
    aggregate_pack_hash = sha256(
        "\n".join(f"{item.repo_id}:{item.pack_hash}" for item in anchors).encode()
    ).hexdigest()
    gates = tuple(gate.id for gate in contract.human_gates if gate.unresolved)
    return ExecutionPlan(
        task_id=contract.task_id,
        task_source_hash=contract.source_hash,
        contract_hash=contract.contract_hash,
        pack_hash=aggregate_pack_hash,
        repositories=anchors,
        slices=slices,
        flows=flows,
        human_gates=gates,
        execution_ready=contract.execution_ready and bool(slices),
    )
