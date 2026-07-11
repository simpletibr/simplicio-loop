"""Deterministic clustering metrics and renderer-neutral layout hints.

The output is a projection of mapper artifacts.  Clusters are intentionally
strategy-scoped and may overlap; no renderer coordinates are emitted.
"""

from __future__ import annotations

import hashlib
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any

from . import __version__

CLUSTERING_SCHEMA = "simplicio.clustering-metrics/v1"
CLUSTERING_VERSION = 1
DEFAULT_CLUSTERING_CONFIG: dict[str, Any] = {
    "min_cluster_size": 1,
    "community_min_size": 2,
    "max_clusters_per_strategy": 100,
    "layout_hints": {
        "enabled": True,
        "lane_order": [
            "workspace",
            "package",
            "directory",
            "namespace",
            "domain",
            "layer",
            "flow",
            "graph-community",
        ],
    },
}
STRATEGIES = ("workspace", "directory", "package", "namespace", "domain", "layer", "flow", "graph-community")


def _merge_config(config: dict[str, Any] | None) -> dict[str, Any]:
    result = dict(DEFAULT_CLUSTERING_CONFIG)
    result["layout_hints"] = dict(DEFAULT_CLUSTERING_CONFIG["layout_hints"])
    if config:
        result.update({key: value for key, value in config.items() if key != "layout_hints"})
        result["layout_hints"].update(config.get("layout_hints") or {})
    result["min_cluster_size"] = max(1, int(result["min_cluster_size"]))
    result["community_min_size"] = max(2, int(result["community_min_size"]))
    result["max_clusters_per_strategy"] = max(1, int(result["max_clusters_per_strategy"]))
    return result


def _stable_id(strategy: str, key: str) -> str:
    seed = f"{strategy}\0{key}"
    return f"cluster:{strategy}:{hashlib.sha256(seed.encode()).hexdigest()[:16]}"


def _file_nodes(artifacts: dict[str, Any]) -> tuple[dict[str, dict], dict[str, str]]:
    nodes: dict[str, dict] = {}
    paths: dict[str, str] = {}
    for entry in artifacts.get("project_map", {}).get("files", []):
        path = entry.get("path")
        if path:
            node_id = _stable_id("file", path)
            nodes[path] = {**entry, "id": node_id}
            paths[node_id] = path
    return nodes, paths


def _package_for(path: str, files: dict[str, dict]) -> str:
    parts = path.split("/")
    for index in range(len(parts) - 1, -1, -1):
        candidate = "/".join(parts[: index + 1])
        if any(p.startswith(candidate + "/") for p in files) and parts[index] in {
            "apps",
            "packages",
            "services",
            "projects",
        }:
            return "/".join(parts[: min(index + 2, len(parts) - 1)]) or "."
    return files[path].get("module") or (parts[0] if len(parts) > 1 else ".")


def _namespace_for(path: str) -> str:
    if "/" in path:
        return path.split("/", 1)[0]
    stem = os.path.splitext(path.rsplit("/", 1)[-1])[0]
    return stem.rsplit(".", 1)[0] if "." in stem else stem


def _groups(artifacts: dict[str, Any], config: dict[str, Any]) -> dict[str, dict[str, set[str]]]:
    files, _ = _file_nodes(artifacts)
    architecture_files = {
        entry.get("path"): entry for entry in artifacts.get("architecture_inventory", {}).get("files", [])
    }
    groups: dict[str, dict[str, set[str]]] = {strategy: {} for strategy in STRATEGIES}
    for path, entry in files.items():
        directory = path.rsplit("/", 1)[0] if "/" in path else "."
        values = {
            "workspace": ".",
            "directory": directory,
            "package": _package_for(path, files),
            "namespace": _namespace_for(path),
            "domain": "domain" if "domain" in entry.get("roles", []) else next(
                (
                    part
                    for part in path.split("/")[:-1]
                    if part.lower()
                    in {
                        "api",
                        "backend",
                        "cli",
                        "core",
                        "domain",
                        "frontend",
                        "infra",
                        "services",
                        "shared",
                        "ui",
                        "web",
                    }
                ),
                "unclassified",
            ),
        }
        layers = (
            architecture_files.get(path, {}).get("layers")
            or entry.get("layers")
            or entry.get("roles")
            or ["unclassified"]
        )
        for strategy, value in values.items():
            groups[strategy].setdefault(str(value), set()).add(path)
        for layer in layers:
            groups["layer"].setdefault(str(layer), set()).add(path)
    flow_files: dict[str, set[str]] = defaultdict(set)
    for flow in (
        artifacts.get("flows", {}).get("flows", []) if isinstance(artifacts.get("flows"), dict) else []
    ):
        for step in flow.get("steps", []):
            if step.get("path") in files:
                flow_files[flow.get("id", "unclassified")].add(step["path"])
    for key, members in flow_files.items():
        groups["flow"][str(key)] = members
    graph: dict[str, set[str]] = {path: set() for path in files}
    for edge in artifacts.get("call_graph", {}).get("edges", []):
        source, target = edge.get("source_file"), edge.get("target_file")
        if source in files and target in files and source != target:
            graph[source].add(target)
            graph[target].add(source)
    seen: set[str] = set()
    for start in sorted(graph):
        if start in seen:
            continue
        stack, component = [start], set()
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            component.add(current)
            stack.extend(sorted(graph[current] - seen, reverse=True))
        if len(component) >= config["community_min_size"]:
            groups["graph-community"]["|".join(sorted(component))] = component
    return {
        strategy: {
            key: members for key, members in values.items() if len(members) >= config["min_cluster_size"]
        }
        for strategy, values in groups.items()
    }


def _edge_metrics(members: set[str], edges: list[dict]) -> dict[str, Any]:
    internal = external = 0
    for edge in edges:
        source, target = edge.get("source_file"), edge.get("target_file")
        if source not in members:
            continue
        if target in members:
            internal += 1
        else:
            external += 1
    total = internal + external
    possible = max(1, len(members) * max(1, len(members) - 1))
    return {
        "dependency_density": round(internal / possible, 6),
        "cohesion": round(internal / total, 6) if total else 0.0,
        "coupling": round(external / total, 6) if total else 0.0,
        "internal_edge_count": internal,
        "external_edge_count": external,
        "edge_count": total,
    }


def _recommended_collapse(size: int, importance: float) -> str:
    if size >= 20 or importance >= 0.8:
        return "summary"
    if size >= 8 or importance >= 0.5:
        return "members"
    return "expanded"


def build_clustering_metrics(
    root: str,
    artifacts: dict[str, Any],
    config: dict[str, Any] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    settings = _merge_config(config)
    files, _ = _file_nodes(artifacts)
    edges = list(artifacts.get("call_graph", {}).get("edges", []))
    groups = _groups(artifacts, settings)
    clusters: list[dict[str, Any]] = []
    for strategy in STRATEGIES:
        for key, members in sorted(groups[strategy].items())[: settings["max_clusters_per_strategy"]]:
            member_paths = sorted(members)
            metrics = _edge_metrics(members, edges)
            language_mix = dict(
                sorted(Counter(files[path].get("language", "text") for path in member_paths).items())
            )
            importance = round(
                sum(float(files[path].get("importance", 0.0)) for path in member_paths) / len(member_paths), 6
            )
            clusters.append(
                {
                    "id": _stable_id(strategy, key),
                    "kind": strategy,
                    "name": key,
                    "member_ids": [_stable_id("file", path) for path in member_paths],
                    "member_paths": member_paths,
                    "member_count": len(member_paths),
                    "language_mix": language_mix,
                    "importance": importance,
                    "overlapping": any(
                        path in other and other != members
                        for other in groups[strategy].values()
                        for path in members
                    ),
                    "recommended_collapse_level": _recommended_collapse(len(member_paths), importance),
                    **metrics,
                }
            )
    cluster_members = [set(cluster["member_paths"]) for cluster in clusters]
    for index, cluster in enumerate(clusters):
        cluster["overlapping"] = any(
            index != other_index and bool(cluster_members[index] & other_members)
            for other_index, other_members in enumerate(cluster_members)
        )
    clusters.sort(key=lambda item: (STRATEGIES.index(item["kind"]), item["name"], item["id"]))
    hints: list[dict[str, Any]] = []
    if settings["layout_hints"].get("enabled", True):
        lane_order = settings["layout_hints"].get("lane_order") or list(STRATEGIES)
        for index, cluster in enumerate(clusters):
            hints.append(
                {
                    "cluster_id": cluster["id"],
                    "lane": cluster["kind"],
                    "lane_index": lane_order.index(cluster["kind"])
                    if cluster["kind"] in lane_order
                    else len(lane_order),
                    "order": index,
                    "importance": cluster["importance"],
                    "collapse_level": cluster["recommended_collapse_level"],
                    "rationale": "stable strategy order; renderer chooses coordinates",
                }
            )
    timestamp = generated_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "schema": CLUSTERING_SCHEMA,
        "version": CLUSTERING_VERSION,
        "mapper_version": __version__,
        "schema_version": "v1",
        "generated_at": timestamp,
        "project": {"root": ".", "file_count": len(files)},
        "config": settings,
        "clusters": clusters,
        "layout_hints": hints,
        "provenance": {
            "config": settings,
            "strategies": list(STRATEGIES),
            "metrics": "directed call/import edges; cohesion=internal/incident; coupling=external/incident",
        },
    }


__all__ = [
    "CLUSTERING_SCHEMA",
    "CLUSTERING_VERSION",
    "DEFAULT_CLUSTERING_CONFIG",
    "STRATEGIES",
    "build_clustering_metrics",
]
