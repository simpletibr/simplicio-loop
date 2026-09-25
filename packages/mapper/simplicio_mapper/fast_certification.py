"""Shadow certification, observability and canary gates for Simplicio Fast."""

from __future__ import annotations

import argparse
import json
import os
import time
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

try:
    import resource as _resource  # Unix-only; optional on Windows
except ImportError:  # pragma: no cover - Windows hosts
    _resource = None  # type: ignore[assignment]

CERTIFICATION_SCHEMA = "simplicio.mapper-fast-certification/v1"
SUPPORTED_FAST_SCHEMAS = {"simplicio.fast-context/v1"}
DEFAULT_GATES = {"precision": 0.98, "recall": 0.95}


def _read(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _relation(item: Mapping[str, Any]) -> str:
    return str(item.get("kind") or item.get("type") or item.get("relation") or "unknown")


def _language(item: Mapping[str, Any], symbols: Mapping[str, str]) -> str:
    return str(
        item.get("language")
        or symbols.get(str(item.get("source") or item.get("from") or ""))
        or "unknown"
    )


def _edge_key(item: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        _relation(item),
        str(item.get("source") or item.get("from") or ""),
        str(item.get("target") or item.get("to") or ""),
    )


def _metrics(reference: set[tuple], candidate: set[tuple]) -> dict[str, Any]:
    matched = len(reference & candidate)
    precision = matched / len(candidate) if candidate else (1.0 if not reference else 0.0)
    recall = matched / len(reference) if reference else 1.0
    return {
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "matched": matched,
        "reference": len(reference),
        "candidate": len(candidate),
    }


def compare_shadow(
    mapper: Mapping[str, Any],
    fast: Mapping[str, Any],
    *,
    gates: Mapping[str, float] = DEFAULT_GATES,
) -> dict[str, Any]:
    """Compare Fast to Mapper without changing Mapper's decisions."""
    mapper_symbols = list(mapper.get("symbols") or [])
    mapper_edges = list(mapper.get("edges") or [])
    projections = fast.get("projections")
    projections = projections if isinstance(projections, Mapping) else {}
    fast_symbols = list(projections.get("symbols") or [])
    fast_edges = list(projections.get("edges") or [])
    mapper_languages = {
        str(item.get("id") or item.get("qualified_name") or item.get("name")): str(
            item.get("language") or "unknown"
        )
        for item in mapper_symbols
        if isinstance(item, Mapping)
    }
    fast_languages = {
        str(item.get("id") or item.get("qualified_name") or item.get("name")): str(
            item.get("language") or "unknown"
        )
        for item in fast_symbols
        if isinstance(item, Mapping)
    }
    buckets: dict[tuple[str, str], dict[str, set[tuple]]] = defaultdict(
        lambda: {"mapper": set(), "fast": set()}
    )
    for edge in mapper_edges:
        if isinstance(edge, Mapping):
            buckets[(_relation(edge), _language(edge, mapper_languages))]["mapper"].add(
                _edge_key(edge)
            )
    for edge in fast_edges:
        if isinstance(edge, Mapping):
            buckets[(_relation(edge), _language(edge, fast_languages))]["fast"].add(_edge_key(edge))

    by_relation_language = {}
    divergences = []
    for (relation, language), values in sorted(buckets.items()):
        result = _metrics(values["mapper"], values["fast"])
        key = f"{relation}:{language}"
        by_relation_language[key] = result
        missing = sorted(values["mapper"] - values["fast"])
        extra = sorted(values["fast"] - values["mapper"])
        for direction, samples in (("missing_in_fast", missing), ("extra_in_fast", extra)):
            for sample in samples:
                divergences.append(
                    {
                        "classification": "known_limitation",
                        "direction": direction,
                        "relation": relation,
                        "language": language,
                        "reproducer": {
                            "edge": list(sample),
                            "mapper_schema": mapper.get("schema"),
                            "fast_schema": fast.get("schema"),
                        },
                    }
                )
    eligible = bool(by_relation_language) and all(
        value["precision"] >= gates["precision"] and value["recall"] >= gates["recall"]
        for value in by_relation_language.values()
    )
    return {
        "mode": "shadow",
        "decision_backend": "mapper",
        "metrics": by_relation_language,
        "divergences": divergences,
        "canary": {
            "eligible": eligible,
            "gates": dict(gates),
            "reason": "quality_gates_passed" if eligible else "quality_gates_not_met",
        },
    }


def _rusage_self() -> Any:
    """Best-effort process rusage; None on platforms without resource module."""
    if _resource is None:
        return None
    return _resource.getrusage(_resource.RUSAGE_SELF)


def certify_fast(
    mapper_path: str,
    fast_path: str,
    *,
    requested_backend: str = "shadow",
) -> dict[str, Any]:
    started = time.perf_counter()
    before = _rusage_self()
    receipt = {"parsed": 0, "reused": 0, "fallback": 0, "degraded": 0}
    try:
        mapper = _read(mapper_path)
        fast = _read(fast_path)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        receipt.update({"fallback": 1, "degraded": 1})
        return {
            "schema": CERTIFICATION_SCHEMA,
            "status": "degraded",
            "reason": f"input_unavailable:{error}",
            "requested_backend": requested_backend,
            "selected_backend": "mapper",
            "receipt": receipt,
        }
    if fast.get("schema") not in SUPPORTED_FAST_SCHEMAS:
        receipt["fallback"] = 1
        return {
            "schema": CERTIFICATION_SCHEMA,
            "status": "fallback",
            "reason": f"unsupported_fast_schema:{fast.get('schema')}",
            "requested_backend": requested_backend,
            "selected_backend": "mapper",
            "compatibility": {
                "mapper": mapper.get("schema"),
                "fast": fast.get("schema"),
                "supported_fast": sorted(SUPPORTED_FAST_SCHEMAS),
                "downgrade": "set SIMPLICIO_MAPPER_CONTEXT_BACKEND=mapper",
            },
            "receipt": receipt,
        }
    shadow = compare_shadow(mapper, fast)
    after = _rusage_self()
    receipt["parsed"] = 1
    selected = "mapper"
    configured = os.environ.get("SIMPLICIO_MAPPER_CONTEXT_BACKEND", requested_backend).casefold()
    if configured == "fast" and shadow["canary"]["eligible"]:
        selected = "fast"
    elapsed = time.perf_counter() - started
    if before is not None and after is not None:
        observability: dict[str, Any] = {
            "query_seconds": elapsed,
            "cpu_user_seconds": after.ru_utime - before.ru_utime,
            "cpu_system_seconds": after.ru_stime - before.ru_stime,
            "rss_max_bytes": after.ru_maxrss * 1024,
            "page_faults": {
                "major": after.ru_majflt - before.ru_majflt,
                "minor": after.ru_minflt - before.ru_minflt,
            },
            "bytes_read": {
                "value": None,
                "reason": "not_observable_portably_for_process_subrange",
            },
        }
    else:
        observability = {
            "query_seconds": elapsed,
            "cpu_user_seconds": None,
            "cpu_system_seconds": None,
            "rss_max_bytes": None,
            "page_faults": {"major": None, "minor": None},
            "bytes_read": {
                "value": None,
                "reason": "resource_module_unavailable_on_this_platform",
            },
        }
    return {
        "schema": CERTIFICATION_SCHEMA,
        "status": "ok",
        "reason": "shadow_comparison_complete",
        "requested_backend": configured,
        "selected_backend": selected,
        "shadow": shadow,
        "receipt": receipt,
        "observability": observability,
        "compatibility": {
            "mapper": mapper.get("schema"),
            "fast": fast.get("schema"),
            "supported_fast": sorted(SUPPORTED_FAST_SCHEMAS),
            "downgrade": "set SIMPLICIO_MAPPER_CONTEXT_BACKEND=mapper",
        },
    }


def run_fast_certify_cli(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="simplicio-mapper fast-certify",
        description="Compare Mapper and Fast in shadow mode and evaluate canary gates.",
    )
    parser.add_argument("--mapper", required=True, help="Mapper golden/canonical projection JSON")
    parser.add_argument("--fast", required=True, help="Simplicio Fast manifest JSON")
    parser.add_argument("--backend", choices=("shadow", "mapper", "fast"), default="shadow")
    parser.add_argument("--out")
    args = parser.parse_args(list(argv))
    payload = certify_fast(args.mapper, args.fast, requested_backend=args.backend)
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.out:
        Path(args.out).write_text(rendered, encoding="utf-8")
    print(json.dumps(payload, sort_keys=True))
    return 0 if payload["status"] == "ok" else 2


__all__ = ["CERTIFICATION_SCHEMA", "certify_fast", "compare_shadow", "run_fast_certify_cli"]
