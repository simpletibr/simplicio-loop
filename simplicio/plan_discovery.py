"""Mapper-backed, fail-closed target discovery for plan-only intake.

Issue #117: autonomous orientation. Build a frozen ``ExecutionPlan`` from
mapper evidence (project-map + ``ask`` queries) *without* ``--stack`` /
``--target`` flags. The planner:

1. classifies each discovered file into an architectural layer
   (``ui`` / ``state`` / ``query`` for the frontend, ``api`` / ``service`` /
   ``repository`` for the backend);
2. runs the five required mapper investigations (``impact`` / ``tests-for`` /
   ``callers`` / ``flows`` / ``rules``) for every candidate;
3. freezes change-slices only where the evidence actually supports them,
   recording per-layer rationale and measured dependencies / blast radius;
4. links full-stack change-sets through a measured ``flows`` edge so the
   planner can register *why* ordering happens in each layer.

When the mapper is absent, stale, or incomplete, or when an impact signal was
asserted (``yes`` / ``possible``) but no measurable target exists in that
layer, the plan fails closed with actionable blockers -- it never falls back
to an improvised survey.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .mapper import load_precedent_index, load_project_map, map_ask
from .orientation_plan import (
    FlowEvidence,
    OrientationBlockedError,
    RepositoryEvidence,
    TargetEvidence,
    build_execution_plan,
)

_FRONTEND_LAYERS = frozenset({"ui", "frontend", "state", "query"})
_BACKEND_LAYERS = frozenset({"api", "backend", "service", "repository"})
_REQUIRED_QUERIES = ("impact", "tests-for", "callers", "flows", "rules")

_UI_HINTS = ("ui", "components", "screens", "pages", "views", "widgets")
_STATE_HINTS = ("state", "store", "stores", "hooks", "redux", "context")
_QUERY_HINTS = ("query", "queries", "selector", "selectors")
_API_HINTS = (
    "api",
    "apis",
    "routes",
    "route",
    "controllers",
    "controller",
    "endpoints",
    "handlers",
    "handler",
)
_SERVICE_HINTS = ("service", "services", "usecase", "use-case", "usecases", "domain")
_REPO_HINTS = (
    "repo",
    "repos",
    "repository",
    "repositories",
    "dao",
    "models",
    "model",
    "entities",
    "entity",
)
_FRONTEND_EXT = (".tsx", ".jsx", ".vue", ".svelte")


class PlanDiscoveryError(ValueError):
    """Raised when mapper evidence is absent or target discovery is ambiguous."""

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


def _classify_layer(entry: dict[str, Any]) -> str:
    """Map a mapper file entry to an orientation layer from path/language hints."""
    path = str(entry.get("path", "")).lower()
    lang = str(entry.get("language", "")).lower()
    name = path.rsplit("/", 1)[-1]
    if name.endswith(_FRONTEND_EXT) or lang in {"tsx", "jsx", "vue", "svelte"}:
        if any(hint in path for hint in _STATE_HINTS):
            return "state"
        if any(hint in path for hint in _QUERY_HINTS):
            return "query"
        return "ui"
    if any(hint in path for hint in _UI_HINTS):
        return "ui"
    if any(hint in path for hint in _STATE_HINTS):
        return "state"
    if any(hint in path for hint in _QUERY_HINTS):
        return "query"
    if any(hint in path for hint in _API_HINTS):
        return "api"
    if any(hint in path for hint in _SERVICE_HINTS):
        return "service"
    if any(hint in path for hint in _REPO_HINTS):
        return "repository"
    if lang in {"py", "go", "rs", "php", "java", "kt", "cs", "rb"} or name.endswith(
        (".py", ".go", ".rs", ".php", ".java")
    ):
        return "service"
    return "backend"


def _rank(entries: list[dict[str, Any]], task: Any) -> list[tuple[int, dict[str, Any]]]:
    tokens = _tokens(task)
    scored: list[tuple[int, dict[str, Any]]] = []
    for entry in entries:
        path = str(entry.get("path", ""))
        haystack = " ".join([path, *(str(item) for item in entry.get("exports", []))]).lower()
        score = sum(token in haystack for token in tokens) + int(float(entry.get("importance", 0)) * 10)
        scored.append((score, entry))
    scored.sort(key=lambda item: (-item[0], str(item[1].get("path", ""))))
    return scored


def _required_layer_groups(task_payload: dict[str, Any]) -> dict[str, frozenset[str]]:
    """Return the layer groups an impact signal asserts must be measurably investigated."""
    signals = task_payload.get("impact_signals", {})
    if not isinstance(signals, dict):
        return {}
    groups: dict[str, frozenset[str]] = {}
    for key in ("frontend", "backend"):
        signal = signals.get(key, {})
        if isinstance(signal, dict):
            status = str(signal.get("status", signal.get("text", ""))).lower()
        else:
            status = str(signal).lower()
        if status in {"yes", "possible", "sim", "talvez", "maybe"}:
            groups[key] = _FRONTEND_LAYERS if key == "frontend" else _BACKEND_LAYERS
    return groups


def _select_targets(
    entries_ranked: list[tuple[int, dict[str, Any]]], task_payload: dict[str, Any]
) -> list[dict[str, Any]]:
    """Pick the measured change-targets without guessing.

    When impact signals assert a layer (``yes`` / ``possible``) we require at
    least one candidate in that layer; otherwise orientation fails closed.
    With no signals we fall back to a single best target and reject ambiguous
    ties -- the legacy fail-closed contract.
    """
    groups = _required_layer_groups(task_payload)
    chosen: dict[str, dict[str, Any]] = {}
    if groups:
        allowed_layers = frozenset().union(*groups.values())
        # One representative, highest-ranked target per distinct layer so the
        # full-stack flow (ui -> state/query -> api/backend) is surfaced.
        for score, entry in entries_ranked:
            if score <= 0:
                continue
            layer = _classify_layer(entry)
            if layer in allowed_layers and str(entry["path"]) not in chosen:
                chosen[str(entry["path"])] = entry
    elif entries_ranked and entries_ranked[0][0] > 0:
        if len(entries_ranked) > 1 and entries_ranked[0][0] == entries_ranked[1][0]:
            tied = [str(item[1]["path"]) for item in entries_ranked[:4]]
            raise PlanDiscoveryError(["ambiguous target discovery: " + ", ".join(tied)])
        chosen[str(entries_ranked[0][1]["path"])] = entries_ranked[0][1]
    return list(chosen.values())


def _collect_query(root: Path, verb: str, path: str) -> list[dict[str, Any]] | None:
    try:
        return map_ask(str(root), verb, path)
    except Exception:
        return None


def _path_bits(value: Any) -> list[str]:
    out: list[str] = []
    if isinstance(value, str) and value and value != "None":
        out.append(value)
    elif isinstance(value, dict):
        path = value.get("path")
        if isinstance(path, str) and path and path != "None":
            out.append(path)
    elif isinstance(value, list):
        for item in value:
            out.extend(_path_bits(item))
    return out


def _extract_flows(root: Path, path: str, results: list[dict[str, Any]] | None) -> list[FlowEvidence]:
    flows: list[FlowEvidence] = []
    if not results:
        return flows
    for result in results:
        paths: list[str] = []
        for key in ("targets", "path", "callees", "callers"):
            paths.extend(_path_bits(result.get(key)))
        name = result.get("name") or result.get("flow") or f"flow:{path}"
        rationale = (
            result.get("rationale")
            or result.get("why")
            or "mapper flows evidence links the changed targets across layers"
        )
        targets = tuple(dict.fromkeys([path, *paths]))
        flows.append(FlowEvidence(name=str(name), targets=targets, rationale=str(rationale)))
    return flows


def _load_precedents(root_path: Path) -> list[str]:
    loaded = load_precedent_index(root_path)
    if not loaded:
        return []
    _, payload = loaded
    return [
        str(item.get("id") or item.get("path"))
        for item in payload.get("items", payload.get("precedents", []))
        if isinstance(item, dict)
    ]


def _rationale(impact: list[dict[str, Any]] | None, layer: str) -> str:
    if impact:
        for item in impact[:3]:
            if not isinstance(item, dict):
                continue
            for key in ("why", "rationale", "reason"):
                value = item.get(key)
                if value:
                    return str(value)
    return f"mapper impact/callers evidence locates the change in the {layer} layer"


def _verify_command(test_paths: list[str]) -> str:
    if not test_paths:
        return ""
    exts = {path.rsplit(".", 1)[-1].lower() for path in test_paths if "." in path}
    if exts <= {"py", "pytest"}:
        return "pytest " + " ".join(test_paths)
    if exts & {"ts", "tsx", "js", "jsx"}:
        return "npx jest " + " ".join(test_paths)
    return "npm test -- " + " ".join(test_paths)


def _freeze_or_block(
    task: Any,
    contract: Any,
    repos: list[RepositoryEvidence],
    root_path: Path,
    mode: str,
) -> dict[str, Any]:
    try:
        plan = build_execution_plan(task, contract, repos)
    except OrientationBlockedError as exc:
        return {
            "schema": "simplicio.plan-preview/v1",
            "status": "blocked",
            "dispatch": False,
            "mutated": False,
            "root": str(root_path),
            "discovery_mode": mode,
            "execution_plan": None,
            "blockers": list(exc.diagnostics),
        }
    return {
        "schema": "simplicio.plan-preview/v1",
        "status": "planned" if plan.execution_ready else "blocked",
        "dispatch": False,
        "mutated": False,
        "root": str(root_path),
        "discovery_mode": mode,
        "execution_plan": plan.to_dict(),
        "blockers": [] if plan.execution_ready else list(plan.human_gates),
    }


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
    if not entries:
        raise PlanDiscoveryError(["mapper project-map has no files; run simplicio-mapper scan --sync --json"])

    task_payload = task_spec_payload or (task.to_dict() if hasattr(task, "to_dict") else dict(task))
    entries_ranked = _rank(entries, task)
    chosen = _select_targets(entries_ranked, task_payload)

    if not chosen:
        # No measurable target for the asserted signals. Orientation must fail
        # closed with the standard diagnostics rather than invent one.
        repo = RepositoryEvidence(
            repo_id="root",
            root=str(root_path),
            root_hash=_hash(project_map),
            pack_hash=_hash({"map": str(map_path)}),
            fresh=True,
            terminal=True,
            artifacts_complete=True,
            queries_run=_REQUIRED_QUERIES,
            targets=(),
        )
        return _freeze_or_block(task, contract, [repo], root_path, "mapper-single-repo/v1")

    criteria = tuple(
        str(item.get("id")) for item in task_payload.get("acceptance_criteria", []) if isinstance(item, dict)
    )
    rules = tuple(
        str(item.get("id")) for item in task_payload.get("business_rules", []) if isinstance(item, dict)
    )
    precedents = _load_precedents(root_path)

    targets: list[TargetEvidence] = []
    flows: list[FlowEvidence] = []
    ran_queries: set[str] = set()
    for entry in chosen:
        path = str(entry["path"])
        layer = _classify_layer(entry)
        impact = _collect_query(root_path, "impact", path)
        tests = _collect_query(root_path, "tests-for", path)
        callers = _collect_query(root_path, "callers", path)
        flows_result = _collect_query(root_path, "flows", path)
        rules_q = _collect_query(root_path, "rules", path)
        for verb, result in (
            ("impact", impact),
            ("tests-for", tests),
            ("callers", callers),
            ("flows", flows_result),
            ("rules", rules_q),
        ):
            if result is not None:
                ran_queries.add(verb)

        test_paths = [
            str(item.get("test_path") or item.get("path")) for item in (tests or []) if isinstance(item, dict)
        ]
        test_paths = [item for item in test_paths if item and item != "None"]
        caller_paths = [
            str(item.get("caller") or item.get("path")) for item in (callers or []) if isinstance(item, dict)
        ]
        caller_paths = [item for item in caller_paths if item and item != "None"]

        targets.append(
            TargetEvidence(
                repo_id="root",
                path=path,
                layer=layer,
                disposition="change",
                responsibility=f"apply the requested change in the {layer} layer",
                rationale=_rationale(impact, layer),
                acceptance_criteria=criteria,
                business_rules=rules,
                precedents=tuple(precedents or [path]),
                tests=tuple(test_paths),
                verify_command=_verify_command(test_paths),
                dependencies=tuple(dict.fromkeys(caller_paths)),
                blast_radius=tuple(dict.fromkeys([path, *caller_paths]))[:8],
            )
        )
        flows.extend(_extract_flows(root_path, path, flows_result))

    seen: set[tuple[str, tuple[str, ...]]] = set()
    flows_dedup: list[FlowEvidence] = []
    for flow in flows:
        key = (flow.name, flow.targets)
        if key in seen:
            continue
        seen.add(key)
        flows_dedup.append(flow)

    queries_run = tuple(sorted(ran_queries))
    repo = RepositoryEvidence(
        repo_id="root",
        root=str(root_path),
        root_hash=_hash(project_map),
        pack_hash=_hash(
            {
                "map": str(map_path),
                "targets": [target.path for target in targets],
                "tests": [list(target.tests) for target in targets],
                "flows": [(flow.name, list(flow.targets)) for flow in flows_dedup],
            }
        ),
        fresh=True,
        terminal=True,
        artifacts_complete=set(queries_run) == set(_REQUIRED_QUERIES),
        queries_run=queries_run,
        targets=tuple(targets),
        flows=tuple(flows_dedup),
    )
    return _freeze_or_block(task, contract, [repo], root_path, "mapper-single-repo/v1")
