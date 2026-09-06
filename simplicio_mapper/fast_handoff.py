"""Canonical, machine-first Mapper -> Simplicio Fast handoff."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import threading
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .context_graph_contract import CONTRACT_SCHEMA as CONTEXT_GRAPH_CONTRACT_SCHEMA
from .context_graph_contract import canonical_digest

HANDOFF_SCHEMA = "simplicio.mapper-fast-handoff/v1"
RECEIPT_SCHEMA = "simplicio.mapper-fast-handoff-receipt/v1"
ARTIFACT_NAMES = (
    "context-snapshot.json",
    "project-map.json",
    "symbol-index.json",
    "call-graph.json",
    "architecture-inventory.json",
)

_ATOMIC_JSON_LOCK = threading.Lock()
def _hash_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _stable_hash(value: Any) -> str:
    return _hash_bytes(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    )


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return payload


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    with _ATOMIC_JSON_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f"{path.name}.tmp-{os.getpid()}-{threading.get_ident()}")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        for attempt in range(5):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.01 * (attempt + 1))


def _git(root: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=10,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _default_branch(root: Path) -> str:
    remote_head = _git(root, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if remote_head:
        return remote_head.rsplit("/", 1)[-1]
    configured = _git(root, "config", "--get", "init.defaultBranch")
    return configured or "main"


def _source_path(item: Mapping[str, Any]) -> str:
    source = item.get("source")
    if isinstance(source, Mapping):
        return str(source.get("file") or source.get("path") or "")
    return str(item.get("defined_in") or item.get("path") or "")


def _graph_projection(snapshot: Mapping[str, Any], changed_paths: Sequence[str]) -> dict[str, Any]:
    graph = snapshot.get("graph")
    graph = graph if isinstance(graph, Mapping) else {}
    nodes = list(graph.get("nodes") or [])
    edges = list(graph.get("edges") or [])
    changed = {path.replace("\\", "/").lstrip("./") for path in changed_paths}
    if changed:
        selected_nodes = [
            node
            for node in nodes
            if isinstance(node, Mapping) and _source_path(node).replace("\\", "/").lstrip("./") in changed
        ]
        ids = {str(node.get("id") or "") for node in selected_nodes}
        selected_edges = [
            edge
            for edge in edges
            if isinstance(edge, Mapping)
            and (str(edge.get("source") or "") in ids or str(edge.get("target") or "") in ids)
        ]
    else:
        selected_nodes, selected_edges = nodes, edges
    return {
        "node_ids": sorted(str(node.get("id")) for node in selected_nodes if node.get("id")),
        "edge_ids": sorted(
            str(edge.get("id") or _stable_hash(edge)) for edge in selected_edges if isinstance(edge, Mapping)
        ),
        "affected": {"nodes": len(selected_nodes), "edges": len(selected_edges)},
    }


def _receipt(*, status: str, reason: str, counters: Mapping[str, int]) -> dict[str, Any]:
    return {
        "schema": RECEIPT_SCHEMA,
        "status": status,
        "reason": reason,
        "counters": dict(counters),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def build_fast_handoff(
    root: str,
    *,
    out: str = ".simplicio",
    changed_paths: Sequence[str] = (),
    base_commit: str = "",
    expected_schema: str = HANDOFF_SCHEMA,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build a deterministic handoff and its consumption receipt."""
    repo = Path(root).resolve()
    artifact_dir = (repo / out).resolve()
    receipt_path = artifact_dir / "fast-handoff-receipt.json"
    if expected_schema != HANDOFF_SCHEMA:
        receipt = _receipt(
            status="fallback",
            reason=f"incompatible_schema: expected {HANDOFF_SCHEMA}, received {expected_schema}",
            counters={"parsed": 0, "reused": 0, "degraded": 0, "fallback": 1},
        )
        _atomic_json(receipt_path, receipt)
        return {}, receipt

    try:
        snapshot = _read_json(artifact_dir / "context-snapshot.json")
        if snapshot.get("schema") != "simplicio.context-snapshot/v1":
            raise ValueError(f"unsupported snapshot schema: {snapshot.get('schema')!r}")
        artifacts = []
        for name in ARTIFACT_NAMES:
            path = artifact_dir / name
            raw = path.read_bytes()
            artifacts.append(
                {
                    "name": name.removesuffix(".json").replace("-", "_"),
                    "path": str(path.relative_to(repo)).replace("\\", "/"),
                    "sha256": _hash_bytes(raw),
                    "bytes": len(raw),
                }
            )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        receipt = _receipt(
            status="degraded",
            reason=f"canonical_artifact_unavailable: {error}; run `simplicio-mapper snapshot build --root {repo}`",
            counters={"parsed": 0, "reused": 0, "degraded": 1, "fallback": 1},
        )
        _atomic_json(receipt_path, receipt)
        return {}, receipt

    projection = _graph_projection(snapshot, changed_paths)
    languages = sorted(
        {
            str(node.get("language"))
            for node in snapshot.get("graph", {}).get("nodes", [])
            if isinstance(node, Mapping) and node.get("language")
        }
    )
    edge_kinds = sorted(
        {
            str(edge.get("kind") or edge.get("type"))
            for edge in snapshot.get("graph", {}).get("edges", [])
            if isinstance(edge, Mapping) and (edge.get("kind") or edge.get("type"))
        }
    )
    graph = snapshot.get("graph", {})
    graph = graph if isinstance(graph, Mapping) else {}
    relation_evidence_classes = sorted(
        {
            str(edge.get("evidence_class"))
            for edge in graph.get("edges", [])
            if isinstance(edge, Mapping) and edge.get("evidence_class")
        }
    )
    revision = str(snapshot.get("revision") or _git(repo, "rev-parse", "HEAD"))
    generation = str(snapshot.get("snapshot_id") or _stable_hash(snapshot))
    normalized_paths = sorted({path.replace("\\", "/").lstrip("./") for path in changed_paths})
    canonical_map_body = {
        "schema": CONTEXT_GRAPH_CONTRACT_SCHEMA,
        "version": 1,
        "repository_id": snapshot.get("repository_id"),
        "generation": generation,
        "id": _stable_hash({
            "repository_id": snapshot.get("repository_id"),
            "default_branch": _default_branch(repo),
            "snapshot_schema": snapshot.get("schema"),
        }),
        "default_branch": _default_branch(repo),
    }
    handoff: dict[str, Any] = {
        "schema": HANDOFF_SCHEMA,
        "generation": generation,
        "repository_id": snapshot.get("repository_id"),
        "revision": revision,
        "canonical_map": {**canonical_map_body, "digest": canonical_digest(canonical_map_body)},
        "capabilities": {
            "snapshot_schemas": ["simplicio.context-snapshot/v1"],
            "handoff_schemas": [HANDOFF_SCHEMA],
            "languages": languages,
            "edge_kinds": edge_kinds,
            "fields": [
                "symbols",
                "imports",
                "references",
                "calls",
                "tests",
                "language",
                "confidence",
                "relation_id",
                "evidence_class",
                "provenance",
                "relation_coverage",
            ],
            "relation_evidence_classes": relation_evidence_classes,
            "relation_coverage": dict(graph.get("relation_coverage", {})),
        },
        "artifacts": artifacts,
        "delta": {
            "base_commit": base_commit or revision,
            "changed_paths": normalized_paths,
            **projection,
        },
    }
    previous = {}
    try:
        previous = _read_json(artifact_dir / "fast-handoff.json")
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    reused = int(
        previous.get("generation") == generation
        and previous.get("delta") == handoff["delta"]
        and previous.get("artifacts") == artifacts
    )
    receipt = _receipt(
        status="reused" if reused else "parsed",
        reason="canonical_map_reused" if reused else "canonical_map_parsed",
        counters={"parsed": 1 - reused, "reused": reused, "degraded": 0, "fallback": 0},
    )
    receipt.update(
        {
            "generation": generation,
            "canonical_map_id": handoff["canonical_map"]["id"],
            "handoff_sha256": _stable_hash(handoff),
        }
    )
    _atomic_json(artifact_dir / "fast-handoff.json", handoff)
    _atomic_json(receipt_path, receipt)
    return handoff, receipt


def verify_fast_handoff(root: str, *, out: str = ".simplicio") -> tuple[bool, str]:
    repo = Path(root).resolve()
    try:
        handoff = _read_json(repo / out / "fast-handoff.json")
        if handoff.get("schema") != HANDOFF_SCHEMA:
            return False, "incompatible_schema"
        for artifact in handoff.get("artifacts") or []:
            path = repo / str(artifact["path"])
            if _hash_bytes(path.read_bytes()) != artifact.get("sha256"):
                return False, f"checksum_mismatch:{artifact.get('path')}"
    except (OSError, KeyError, ValueError, json.JSONDecodeError) as error:
        return False, f"handoff_unreadable:{error}"
    return True, "verified"


def run_fast_handoff_cli(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="simplicio-mapper fast-handoff",
        description="Emit the canonical machine-readable Mapper -> Fast handoff.",
    )
    parser.add_argument("root", nargs="?", default=os.getcwd())
    parser.add_argument("--out", default=".simplicio")
    parser.add_argument("--changed-path", action="append", default=[])
    parser.add_argument("--base-commit", default="")
    parser.add_argument("--expect-schema", default=HANDOFF_SCHEMA)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args(list(argv))
    if args.verify:
        valid, reason = verify_fast_handoff(args.root, out=args.out)
        print(json.dumps({"schema": HANDOFF_SCHEMA, "valid": valid, "reason": reason}, sort_keys=True))
        return 0 if valid else 1
    handoff, receipt = build_fast_handoff(
        args.root,
        out=args.out,
        changed_paths=args.changed_path,
        base_commit=args.base_commit,
        expected_schema=args.expect_schema,
    )
    print(json.dumps({"handoff": handoff or None, "receipt": receipt}, sort_keys=True))
    return 0 if handoff else 2


__all__ = [
    "HANDOFF_SCHEMA",
    "build_fast_handoff",
    "run_fast_handoff_cli",
    "verify_fast_handoff",
]
