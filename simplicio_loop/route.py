"""Deterministic Prism route for the public Loop surface."""
from __future__ import annotations

import argparse
import hashlib
import json
from typing import Any

from .capability_catalog import load_catalog


def _expand_dependencies(requested: list[str], known: dict[str, dict[str, Any]]) -> tuple[list[str], list[str]]:
    ordered: list[str] = []
    unresolved: list[str] = []

    def visit(capability: str) -> None:
        if capability in ordered:
            return
        item = known.get(capability)
        if item is None:
            unresolved.append(capability)
            return
        for dependency in item.get("requires", []):
            visit(str(dependency))
        ordered.append(capability)

    for capability in requested:
        visit(capability)
    return ordered, sorted(set(unresolved))


def route(task: str) -> dict[str, Any]:
    text = task.casefold()
    headline = text.splitlines()[0] if text.splitlines() else text
    # Evidence and checkpoints are often outputs of ordinary Loop work. Only an explicit
    # governance request should switch the route to Runtime; a mention of Runtime as an
    # integration target must not steal an orchestration/mutation/validation route.
    governance = any(
        x in text
        for x in (
            "govern", "governed", "authorize", "authorization", "policy gate",
            "runtime gate", "mcp server", "mcp tool", "reconcile execution",
        )
    )
    orchestration = any(
        x in text
        for x in (
            "all issues", "todas as issues", "batch", "parallel", "paralel", "multiple",
            "retry", "until done", "orquestr", "deleg", "lifecycle", "completion",
            "abrir pr", "pull request", "fan-out", "fanout",
            "generation", "geração", "loop hub", "dag", "concurrency", "concorrência",
            "structured concurrency", "fan-out", "fanout",
        )
    )
    validation = any(x in text for x in ("test", "tests", "validate", "validar", "verify", "verificar", "lint", "check", "quality", "e2e", "prove", "scanner", "audit", "auditar", "review", "revisar", "benchmark", "performance", "release-blocking"))
    mutation = any(x in text for x in ("fix", "implement", "add", "edit", "change", "refactor", "migrate", "migration", "remove", "corrigir", "implementar", "alterar", "migrar", "migração", "remover"))
    retrieval = any(x in text for x in ("search", "find", "where", "similar", "precedent", "buscar", "localizar", "procurar"))

    # Issue bodies list every required test and receipt, so the headline is the
    # strongest signal for a single-issue route. Prevent validation requirements
    # from turning a migration into orchestration, and vice versa.
    headline_orchestration = any(
        x in headline for x in (
            "parallel", "paralel", "concurr", "fan-out", "fanout", "lifecycle",
            "completion", "delegat", "orchestrat", "loop hub", "generation", "geração",
            "all issues", "todas as issues", "batch", "multiple", "review all",
        )
    )
    headline_validation = any(
        x in headline for x in ("quality", "test", "validate", "verify", "prove", "e2e", "audit", "benchmark", "scanner")
    )
    headline_mutation = any(
        x in headline for x in ("migrate", "migration", "remove", "fix", "implement", "refactor", "migrar", "remover", "corrigir")
    )
    if headline_orchestration:
        orchestration = True
    elif headline_validation:
        orchestration = False
        validation = True
    elif headline_mutation:
        orchestration = False
        validation = False
        mutation = True

    if governance:
        intent = "govern"
        requested = ["runtime.gate", "runtime.checkpoint", "runtime.receipt", "runtime.reconcile"]
        pre = ["external Runtime is installed"]
        fallback = ["use Loop without Runtime when governance is not required"]
    elif orchestration:
        intent = "orchestrate"
        requested = ["mapper.snapshot-create", "mapper.context-select", "loop.plan", "loop.slot-dispatch", "loop.retry", "loop.complete"]
        if validation:
            requested[2:2] = ["dev-cli.preflight", "dev-cli.tests", "dev-cli.evidence"]
        pre = ["repository and revision are known", "one task per slot"]
        fallback = ["run a single-task recipe when fan-out is unnecessary"]
    elif validation:
        intent = "validate"
        requested = ["mapper.snapshot-create", "mapper.context-select", "dev-cli.preflight", "dev-cli.tests", "dev-cli.evidence"]
        pre = ["fresh compatible Mapper snapshot"]
        fallback = ["bounded read-only validation"]
    elif mutation:
        intent = "mutate"
        requested = ["mapper.snapshot-create", "mapper.context-select", "dev-cli.preflight", "dev-cli.edit", "dev-cli.tests", "dev-cli.evidence"]
        pre = ["fresh compatible Mapper snapshot", "Dev CLI preflight passes"]
        fallback = ["stop when revision or scope is unknown"]
    elif retrieval:
        intent = "retrieve"
        requested = ["mapper.snapshot-create", "mapper.context-select"]
        pre = ["fresh compatible Mapper snapshot"]
        fallback = ["bounded read-only Mapper survey"]
    else:
        intent = "survey"
        requested = ["mapper.project-survey", "mapper.snapshot-create", "mapper.context-select"]
        pre = ["repository, revision and scope are pinned"]
        fallback = ["survey-degraded read-only fallback"]

    catalog = load_catalog()
    known = {item["id"]: item for item in catalog["capabilities"]}
    selected, unresolved = _expand_dependencies(requested, known)
    skills = sorted({known[capability]["skill"] for capability in selected})
    adapters = []
    if any(capability.startswith("mapper.") for capability in selected):
        adapters.append({"component": "mapper", "surface": "scripts/preflight.py"})
    if any(capability.startswith("dev-cli.") for capability in selected):
        adapters.append({"component": "dev-cli", "surface": "simplicio-cli test/edit"})
    if any(capability.startswith("loop.") for capability in selected):
        adapters.append({"component": "loop", "surface": "scripts/route_mode.py"})
    if any(capability.startswith("runtime.") for capability in selected):
        adapters.append({"component": "runtime", "surface": "simplicio doctor --json"})
    digest = hashlib.sha256(task.encode()).hexdigest()[:16]
    return {
        "schema": "simplicio.route/v1",
        "language": "en",
        "instruction_language": "en",
        "catalog_schema": catalog["schema"],
        "route_id": "simplicio.route/" + digest,
        "intent": intent,
        "selected_capabilities": selected,
        "skills_to_load": skills,
        "existing_adapters": adapters,
        "order": selected,
        "preconditions": pre,
        "fallbacks": fallback,
        "cost_estimate": {"mode": "static", "status": "requires_measurement"},
        "evidence_requirements": ["selected capability emits evidence", "completion oracle is proven"],
        "unresolved": unresolved,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Route a task to Simplicio capabilities")
    parser.add_argument("task", nargs="+")
    args = parser.parse_args(argv)
    print(json.dumps(route(" ".join(args.task)), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
