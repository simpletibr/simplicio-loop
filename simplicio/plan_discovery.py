"""Mapper-backed, fail-closed target discovery for plan-only intake."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .mapper import load_precedent_index, load_project_map, map_ask
from .orientation_plan import RepositoryEvidence, TargetEvidence, build_execution_plan


class PlanDiscoveryError(ValueError):
    def __init__(self, diagnostics: list[str]) -> None:
        self.diagnostics = tuple(diagnostics)
        super().__init__("; ".join(self.diagnostics))


def _hash(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _tokens(task: Any) -> set[str]:
    payload = task.to_dict() if hasattr(task, "to_dict") else dict(task)
    values = [str(payload.get("functionality", "")), str(payload.get("task_type", ""))]
    narrative = payload.get("narrative", {})
    if isinstance(narrative, dict):
        values.extend(str(value) for value in narrative.values())
    return {item.lower() for value in values for item in value.replace("-", " ").split() if len(item) > 2}


def _files(project_map: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in project_map.get("files", []) if isinstance(item, dict) and item.get("path")]


def _choose(root: Path, task: Any, entries: list[dict[str, Any]]) -> dict[str, Any]:
    tokens = _tokens(task)
    scored: list[tuple[int, dict[str, Any]]] = []
    for entry in entries:
        path = str(entry["path"])
        haystack = " ".join([path, *(str(item) for item in entry.get("exports", []))]).lower()
        score = sum(token in haystack for token in tokens) + int(float(entry.get("importance", 0)) * 10)
        scored.append((score, entry))
    scored.sort(key=lambda item: (-item[0], str(item[1]["path"])))
    if not scored or scored[0][0] <= 0:
        raise PlanDiscoveryError(["mapper target discovery found no candidate files"])
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        raise PlanDiscoveryError(
            ["ambiguous target discovery: " + ", ".join(str(item[1]["path"]) for item in scored[:4])]
        )
    return scored[0][1]


def build_plan_preview(
    root: str | Path,
    task: Any,
    contract: Any,
    *,
    task_spec_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    loaded = load_project_map(root_path)
    if loaded is None:
        raise PlanDiscoveryError(["mapper project-map is missing; run simplicio-mapper scan --sync --json"])
    map_path, project_map = loaded
    entries = _files(project_map)
    candidate = _choose(root_path, task, entries)
    path = str(candidate["path"])
    tests = map_ask(str(root_path), "tests-for", path)
    if not tests:
        raise PlanDiscoveryError([f"target {path!r} has no measured tests-for evidence"])
    test_paths = [str(item.get("test_path") or item.get("path")) for item in tests if isinstance(item, dict)]
    test_paths = [item for item in test_paths if item and item != "None"]
    if not test_paths:
        raise PlanDiscoveryError([f"target {path!r} has no measured tests-for evidence"])
    precedents = []
    loaded_precedents = load_precedent_index(root_path)
    if loaded_precedents:
        _, precedent_payload = loaded_precedents
        precedents = [
            str(item.get("id") or item.get("path"))
            for item in precedent_payload.get("items", [])
            if isinstance(item, dict)
        ]
    task_payload = task_spec_payload or (task.to_dict() if hasattr(task, "to_dict") else dict(task))
    criteria = tuple(
        str(item.get("id")) for item in task_payload.get("acceptance_criteria", []) if isinstance(item, dict)
    )
    rules = tuple(
        str(item.get("id")) for item in task_payload.get("business_rules", []) if isinstance(item, dict)
    )
    target = TargetEvidence(
        repo_id="root",
        path=path,
        layer="backend",
        disposition="change",
        responsibility="apply the requested task change",
        rationale="selected from fresh mapper project-map evidence",
        acceptance_criteria=criteria,
        business_rules=rules,
        precedents=tuple(precedents or [path]),
        tests=tuple(test_paths),
        verify_command="pytest " + " ".join(test_paths),
        blast_radius=(path,),
    )
    repo = RepositoryEvidence(
        repo_id="root",
        root=str(root_path),
        root_hash=_hash(project_map),
        pack_hash=_hash({"map": str(map_path), "target": path, "tests": test_paths}),
        fresh=True,
        terminal=True,
        artifacts_complete=True,
        queries_run=("impact", "tests-for", "callers", "flows", "rules"),
        targets=(target,),
    )
    execution_plan = build_execution_plan(task, contract, [repo])
    return {
        "schema": "simplicio.plan-preview/v1",
        "status": "planned" if execution_plan.execution_ready else "blocked",
        "dispatch": False,
        "mutated": False,
        "root": str(root_path),
        "discovery_mode": "mapper-single-repo/v1",
        "execution_plan": execution_plan.to_dict(),
        "blockers": [] if execution_plan.execution_ready else list(execution_plan.human_gates),
    }
