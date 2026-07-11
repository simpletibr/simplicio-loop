"""Offline deterministic compilation of a raw task into repository context."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from .context_pack import select_context_targets
from .task_intent import TASK_CONTEXT_SCHEMA, canonical_json, parse_task_intent


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _map_fingerprint(project_map: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(project_map).encode("utf-8")).hexdigest()


def _line_evidence(root: Path, path: str, terms: list[str]) -> tuple[int, str]:
    try:
        lines = (root / path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return 1, "file snapshot"
    folded = [line.casefold() for line in lines]
    for term in terms:
        for index, line in enumerate(folded):
            if re.search(rf"(?<![a-z0-9_]){re.escape(term.casefold())}(?![a-z0-9_])", line):
                return index + 1, f"matched task term: {term}"
    return 1, "file selected by deterministic path/index evidence"


def _candidate(path: str, *, kind: str, score: float, reason: str, root: Path, terms: list[str]) -> dict[str, Any]:
    line, evidence_reason = _line_evidence(root, path, terms)
    return {
        "kind": kind,
        "path": path.replace(os.sep, "/"),
        "line": line,
        "score": round(float(score), 6),
        "reason": reason,
        "confidence": round(min(1.0, max(0.0, float(score))), 6),
        "evidence": {"path": path.replace(os.sep, "/"), "line": line, "reason": evidence_reason},
    }


def build_orientation(
    root: str,
    task: str | dict[str, Any],
    *,
    target: str = "",
    limit: int = 8,
    minimum_query_coverage: float = 0.2,
) -> dict[str, Any]:
    """Return a versioned task-context envelope without IO beyond local artifacts."""
    abs_root = Path(root).resolve()
    intent = parse_task_intent(task)
    project_map = _read_json(abs_root / ".simplicio" / "project-map.json")
    selection = select_context_targets(
        str(abs_root), project_map, goal="", task_intent=intent, target=target, limit=limit
    )
    terms = selection["query_terms"]
    candidates: list[dict[str, Any]] = []
    for row in selection["targets"]:
        candidates.append(
            _candidate(
                row["path"],
                kind="file",
                score=row["relevance_score"],
                reason=row["relevance_reason"],
                root=abs_root,
                terms=terms,
            )
        )

    symbol_index = _read_json(abs_root / ".simplicio" / "symbol-index.json")
    selected_paths = {row["path"] for row in selection["targets"]}
    for symbol in symbol_index.get("symbols", []):
        if not isinstance(symbol, dict) or symbol.get("defined_in") not in selected_paths:
            continue
        symbol_name = str(symbol.get("name", ""))
        symbol_matches = [term for term in terms if term.casefold() == symbol_name.casefold()]
        if not symbol_matches:
            continue
        path = str(symbol["defined_in"])
        candidates.append(
            _candidate(
                path,
                kind="symbol",
                score=0.5,
                reason=f"symbol {symbol_name} matches task terms: {', '.join(symbol_matches)}",
                root=abs_root,
                terms=symbol_matches,
            )
        )
    candidates.sort(key=lambda row: (-row["score"], row["kind"], row["path"], row["line"]))
    candidates = candidates[: max(1, limit)] if candidates else []
    gaps: list[str] = []
    if not candidates:
        gaps.append("no relevant repository candidate matched the normalized task vocabulary")
    if selection["coverage"]["ratio"] < minimum_query_coverage:
        gaps.append(
            f"query coverage {selection['coverage']['ratio']:.3f} below minimum {minimum_query_coverage:.3f}"
        )
    map_fingerprint = _map_fingerprint(project_map)
    provisional = {
        "schema": TASK_CONTEXT_SCHEMA,
        "task": {"schema": intent["schema"], "fingerprint": intent["fingerprint"]},
        "map": {"schema": project_map.get("schema", "simplicio.project-map/v1"), "fingerprint": map_fingerprint},
        "candidates": candidates,
        "needs_broader_context": bool(gaps),
        "gaps": gaps,
    }
    result_fingerprint = hashlib.sha256(canonical_json(provisional).encode("utf-8")).hexdigest()
    return {**provisional, "result_fingerprint": result_fingerprint, "selection": selection}


def run_orientation_cli(opts: dict[str, Any]) -> int:
    root = str(opts["root"])
    source = str(opts.get("task_file") or opts.get("task_json") or "")
    try:
        if opts.get("stdin"):
            raw: str | dict[str, Any] = sys.stdin.read()
        elif source:
            raw = Path(source).read_text(encoding="utf-8")
        else:
            raise ValueError("orient requires --task-file, --task-json, or --stdin")
        if opts.get("task_json"):
            raw = json.loads(raw)
        payload = build_orientation(
            root,
            raw,
            target=str(opts.get("target") or ""),
            limit=int(opts.get("limit", 8)),
            minimum_query_coverage=float(opts.get("minimum_query_coverage", 0.2)),
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"orient failed: {error}", file=sys.stderr)
        return 2
    if opts.get("for_llm") == "toon":
        from .cli._index_engine import _print_toon

        _print_toon(payload)
    else:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


__all__ = ["build_orientation", "run_orientation_cli"]
