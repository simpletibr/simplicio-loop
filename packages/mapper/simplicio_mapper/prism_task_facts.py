"""PrismTaskFacts/v1 — bounded causal facts for hierarchical slots.

Mapper owns measured/declared/inferred *facts* only. It never grants mutation
authority, picks agents, or schedules slots. Loop consumes these facts to build
a conflict graph safely.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from .context_graph_v1 import ContextGraphError, digest, impact_query, validate_graph

TASK_FACTS_SCHEMA = "simplicio.prism-task-facts/v1"
_DEFAULT_BUDGET = {
    "max_nodes": 128,
    "max_depth": 4,
    "max_bytes": 65536,
    "max_external_tokens": 4000,
}
_PATH_RE = re.compile(r"[A-Za-z0-9_./\\-]+\.(?:py|ts|tsx|js|jsx|go|rs|cs|java|md|json|toml|yml|yaml)\b")
_SYMBOL_RE = re.compile(r"\b[A-Z][A-Za-z0-9_]{2,}\b|\b[a-z_][a-z0-9_]{2,}\b")


class PrismFactsError(ValueError):
    def __init__(self, reason_code: str, detail: str = "") -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {detail}" if detail else reason_code)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _hint(
    value: str,
    *,
    source: str,
    confidence: float,
    evidence_refs: Sequence[str] | None = None,
) -> dict[str, Any]:
    if source not in {"measured", "declared", "inferred"}:
        raise PrismFactsError("source_invalid", source)
    if not 0.0 <= confidence <= 1.0:
        raise PrismFactsError("confidence_invalid", str(confidence))
    return {
        "value": value,
        "source": source,
        "confidence": confidence,
        "evidence_refs": sorted(set(evidence_refs or ())),
    }


def _budget(overrides: Mapping[str, Any] | None) -> dict[str, int]:
    budget = dict(_DEFAULT_BUDGET)
    if overrides:
        for key, value in overrides.items():
            if key not in budget:
                raise PrismFactsError("budget_unknown_field", key)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise PrismFactsError("budget_invalid", key)
            budget[key] = value
    return budget


def _extract_paths(text: str) -> list[str]:
    return sorted({item.replace("\\", "/") for item in _PATH_RE.findall(text or "")})


def _extract_symbols(text: str) -> list[str]:
    stop = {
        "the", "and", "for", "with", "from", "this", "that", "into", "when", "then",
        "issue", "task", "test", "tests", "file", "path", "repo", "main", "true", "false",
    }
    out = []
    for token in _SYMBOL_RE.findall(text or ""):
        low = token.casefold()
        if low in stop or len(token) < 3:
            continue
        out.append(token)
    return sorted(set(out))


def _looks_like_test(path: str) -> bool:
    lower = path.casefold()
    name = path.rsplit("/", 1)[-1].casefold()
    return (
        "/tests/" in f"/{lower}"
        or name.startswith("test_")
        or name.endswith("_test.py")
        or name.endswith(".spec.ts")
        or name.endswith(".test.ts")
    )


def _conflict_pair(left: str, right: str, *, kind: str, reason: str, confidence: float,
                   evidence_refs: Sequence[str], source: str) -> dict[str, Any]:
    a, b = sorted((left, right))
    identity = {"kind": kind, "left": a, "right": b, "reason": reason}
    return {
        "conflict_id": digest(identity),
        "kind": kind,
        "left": a,
        "right": b,
        "reason_code": reason,
        "confidence": confidence,
        "source": source,
        "evidence_refs": sorted(set(evidence_refs)),
        # Prediction only — never mutation authority.
        "authority": None,
        "authority_null_reason": "PREDICTION_NOT_AUTHORITY",
    }


def build_prism_task_facts(
    graph: Mapping[str, Any],
    *,
    task_id: str,
    task_text: str = "",
    declared_write_set: Sequence[str] | None = None,
    declared_read_set: Sequence[str] | None = None,
    declared_dependencies: Sequence[str] | None = None,
    seed_fact_ids: Sequence[str] | None = None,
    budget: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Project a task into bounded PrismTaskFacts/v1.

    write_set_hints are *predictions*. Declared write-sets (e.g. from Dev CLI)
    stay in a separate namespace from observed/predicted paths.
    """
    if not task_id or not isinstance(task_id, str):
        raise PrismFactsError("task_id_invalid", str(task_id))
    clean = validate_graph(graph)
    limits = _budget(budget)

    seeds = list(seed_fact_ids or ())
    if not seeds:
        # Infer seeds from declared paths matching graph provenance paths.
        wanted = set(declared_write_set or ()) | set(declared_read_set or ()) | set(_extract_paths(task_text))
        for item in clean["facts"]:
            path = item.get("provenance", {}).get("path", "")
            if path in wanted or any(path.endswith(w) or w.endswith(path) for w in wanted):
                seeds.append(item["fact_id"])
        seeds = sorted(set(seeds))[: limits["max_nodes"]]

    impact: dict[str, Any] | None = None
    impact_error: str | None = None
    if seeds:
        try:
            impact = impact_query(
                clean,
                seeds,
                max_depth=limits["max_depth"],
                max_nodes=limits["max_nodes"],
            )
        except ContextGraphError as exc:
            impact_error = getattr(exc, "reason_code", str(exc))
            impact = None

    measured_write = list(impact.get("write_set_hints", [])) if impact else []
    measured_tests = list(impact.get("verification_hints", {}).get("test_fact_ids", [])) if impact else []
    declared_write = sorted({p.replace("\\", "/") for p in (declared_write_set or ())})
    declared_read = sorted({p.replace("\\", "/") for p in (declared_read_set or ())})
    inferred_paths = _extract_paths(task_text)
    inferred_symbols = _extract_symbols(task_text)

    read_set_hints = [
        *[_hint(p, source="declared", confidence=0.95, evidence_refs=["task.declared_read_set"]) for p in declared_read],
        *[_hint(p, source="inferred", confidence=0.55, evidence_refs=["task.text"]) for p in inferred_paths if p not in declared_read],
    ]
    write_set_hints = [
        *[_hint(p, source="declared", confidence=0.95, evidence_refs=["task.declared_write_set"]) for p in declared_write],
        *[_hint(p, source="measured", confidence=0.85, evidence_refs=["impact_query.write_set_hints"]) for p in measured_write if p not in declared_write],
        *[_hint(p, source="inferred", confidence=0.45, evidence_refs=["task.text"]) for p in inferred_paths if p not in declared_write and p not in measured_write],
    ]
    # Keep declared vs observed namespaces explicit for consumers.
    write_set_declared = list(declared_write)
    write_set_observed = list(measured_write)

    symbol_hints = [_hint(s, source="inferred", confidence=0.5, evidence_refs=["task.text"]) for s in inferred_symbols[:64]]
    test_hints = [
        _hint(fid, source="measured", confidence=0.8, evidence_refs=["impact_query.verification_hints"])
        for fid in measured_tests
    ]
    for path in [*declared_write, *measured_write, *inferred_paths]:
        if _looks_like_test(path):
            test_hints.append(_hint(path, source="inferred", confidence=0.6, evidence_refs=["path.heuristic"]))

    resource_hints: list[dict[str, Any]] = []
    for path in sorted(set(declared_write + measured_write + declared_read)):
        if path.endswith((".lock", "package-lock.json", "uv.lock", "Cargo.lock")):
            resource_hints.append(_hint("lockfile", source="measured", confidence=0.9, evidence_refs=[path]))
        if "/models/" in path or path.endswith((".onnx", ".tflite", ".gguf")):
            resource_hints.append(_hint("model", source="inferred", confidence=0.7, evidence_refs=[path]))
        if any(token in path.casefold() for token in ("network", "http", "client", "api")):
            resource_hints.append(_hint("network", source="inferred", confidence=0.55, evidence_refs=[path]))

    dependency_hints = [
        _hint(dep, source="declared", confidence=1.0, evidence_refs=["task.declared_dependencies"])
        for dep in sorted(set(declared_dependencies or ()))
    ]

    hard: list[dict[str, Any]] = []
    soft: list[dict[str, Any]] = []
    write_values = sorted({h["value"] for h in write_set_hints})
    for i, left in enumerate(write_values):
        for right in write_values[i + 1 :]:
            hard.append(
                _conflict_pair(
                    left,
                    right,
                    kind="hard",
                    reason="SHARED_WRITE_PATH",
                    confidence=0.9,
                    evidence_refs=["write_set_hints"],
                    source="measured" if left in measured_write and right in measured_write else "inferred",
                )
            )
    # Soft exclusive resources
    for res in {h["value"] for h in resource_hints}:
        soft.append(
            _conflict_pair(
                task_id,
                f"resource:{res}",
                kind="soft",
                reason=f"SHARED_RESOURCE_{res.upper()}",
                confidence=0.6,
                evidence_refs=["resource_hints"],
                source="inferred",
            )
        )

    coverage = 0.0
    if impact and not impact.get("truncated"):
        coverage = min(1.0, len(seeds) / max(1, min(len(clean["facts"]), limits["max_nodes"])))
    elif seeds:
        coverage = 0.35
    fidelity = None
    if write_set_hints or read_set_hints:
        fidelity = sum(h["confidence"] for h in write_set_hints + read_set_hints) / max(
            1, len(write_set_hints) + len(read_set_hints)
        )
    truncated = bool(impact and impact.get("truncated")) or impact is None
    abstained = truncated or coverage < 0.25 or fidelity is None
    reason_code = None
    if abstained:
        if impact_error:
            reason_code = f"IMPACT_{impact_error.upper()}"
        elif not seeds:
            reason_code = "NO_SEED_FACTS"
        elif truncated:
            reason_code = "BUDGET_TRUNCATED"
        else:
            reason_code = "LOW_COVERAGE"

    body = {
        "schema": TASK_FACTS_SCHEMA,
        "task_id": task_id,
        "repo_id": clean["repo_id"],
        "generation": clean["generation"],
        "graph_digest": clean["graph_digest"],
        "read_set_hints": sorted(read_set_hints, key=lambda item: (item["value"], item["source"])),
        "write_set_hints": sorted(write_set_hints, key=lambda item: (item["value"], item["source"])),
        "write_set_declared": write_set_declared,
        "write_set_observed": write_set_observed,
        "symbol_hints": sorted(symbol_hints, key=lambda item: item["value"]),
        "test_hints": sorted(test_hints, key=lambda item: item["value"]),
        "resource_hints": sorted(resource_hints, key=lambda item: (item["value"], item["source"])),
        "dependency_hints": sorted(dependency_hints, key=lambda item: item["value"]),
        "hard_conflict_candidates": sorted(hard, key=lambda item: item["conflict_id"]),
        "soft_conflict_candidates": sorted(soft, key=lambda item: item["conflict_id"]),
        "coverage": coverage,
        "fidelity": fidelity,
        "truncated": truncated,
        "abstained": abstained,
        "reason_code": reason_code,
        "budget": limits,
        "seed_fact_ids": sorted(set(seeds)),
    }
    encoded = _canonical(body)
    if len(encoded) > limits["max_bytes"]:
        body["truncated"] = True
        body["abstained"] = True
        body["reason_code"] = "MAX_BYTES_EXCEEDED"
        # Fail closed on oversized projection: drop soft candidates first.
        body["soft_conflict_candidates"] = []
        encoded = _canonical(body)
        if len(encoded) > limits["max_bytes"]:
            body["hard_conflict_candidates"] = []
            body["symbol_hints"] = body["symbol_hints"][:8]
    body["facts_digest"] = _sha(body)
    body["encoded_bytes"] = len(_canonical(body))
    return body


def validate_prism_task_facts(payload: Mapping[str, Any]) -> dict[str, Any]:
    if payload.get("schema") != TASK_FACTS_SCHEMA:
        raise PrismFactsError("schema_invalid", str(payload.get("schema")))
    for key in ("task_id", "repo_id", "generation", "graph_digest", "facts_digest"):
        if not payload.get(key):
            raise PrismFactsError("field_missing", key)
    unsigned = {k: v for k, v in payload.items() if k not in {"facts_digest", "encoded_bytes"}}
    if payload["facts_digest"] != _sha(unsigned):
        raise PrismFactsError("digest_mismatch", payload["facts_digest"])
    # Determinism: ordered lists must already be sorted by construction.
    return dict(payload)


def project_task_batch(
    graph: Mapping[str, Any],
    tasks: Sequence[Mapping[str, Any]],
    *,
    budget: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Project up to 10 tasks deterministically regardless of input order."""
    if len(tasks) > 10:
        raise PrismFactsError("batch_too_large", str(len(tasks)))
    ordered = sorted(tasks, key=lambda item: str(item.get("task_id", "")))
    results = [
        build_prism_task_facts(
            graph,
            task_id=str(item["task_id"]),
            task_text=str(item.get("task_text", "")),
            declared_write_set=item.get("declared_write_set"),
            declared_read_set=item.get("declared_read_set"),
            declared_dependencies=item.get("declared_dependencies"),
            seed_fact_ids=item.get("seed_fact_ids"),
            budget=budget,
        )
        for item in ordered
    ]
    return sorted(results, key=lambda item: item["task_id"])


__all__ = [
    "TASK_FACTS_SCHEMA",
    "PrismFactsError",
    "build_prism_task_facts",
    "project_task_batch",
    "validate_prism_task_facts",
]
