#!/usr/bin/env python3
"""Fail-closed parity gate for every published simplicio-loop surface."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

SCHEMA = "simplicio.release-manifest/v1"
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")


def _pyproject_version(path: Path) -> str:
    match = re.search(r"(?m)^version\s*=\s*[\"']([^\"']+)[\"']", path.read_text())
    if not match:
        raise ValueError("pyproject.toml has no project version")
    return match.group(1)


def _json_version(path: Path) -> str:
    try:
        value = json.loads(path.read_text()).get("version")
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, str) or not value:
        raise ValueError(f"{path} has no version")
    return value


def _fallback_versions(path: Path) -> List[str]:
    return re.findall(r"__version__\s*=\s*[\"']([^\"']+)[\"']", path.read_text())


def build_manifest(repo: Path, *, tag: Optional[str] = None) -> Dict[str, Any]:
    sources = {
        "pyproject": (repo / "pyproject.toml", _pyproject_version),
        "cursor_plugin": (repo / ".cursor-plugin" / "plugin.json", _json_version),
    }
    rows: List[Dict[str, Any]] = []
    errors: List[str] = []
    for name, (path, reader) in sources.items():
        try:
            version = reader(path)
        except (OSError, ValueError) as exc:
            version = ""
            errors.append(str(exc))
        rows.append({"name": name, "path": str(path.relative_to(repo)), "version": version})
    fallback_path = repo / "simplicio_loop" / "__init__.py"
    try:
        fallbacks = _fallback_versions(fallback_path)
    except OSError as exc:
        fallbacks = []
        errors.append(str(exc))
    rows.append({"name": "source_fallback", "path": str(fallback_path.relative_to(repo)),
                 "versions": fallbacks, "version": fallbacks[0] if fallbacks else ""})
    canonical = rows[0]["version"]
    versions = [row["version"] for row in rows if row.get("version")]
    mismatches = [row["name"] for row in rows if row.get("version") != canonical]
    if any(not VERSION_RE.match(version) for version in versions):
        errors.append("all release versions must be semantic MAJOR.MINOR.PATCH")
    if len(set(fallbacks)) != 1 or (fallbacks and fallbacks[0] != canonical):
        mismatches.append("source_fallback")
    tag_version = tag[1:] if tag and tag.startswith("v") else tag
    if tag and (not tag.startswith("v") or tag_version != canonical):
        errors.append(f"tag {tag!r} does not match v{canonical}")
    return {"schema": SCHEMA, "canonical_version": canonical, "tag": tag or "",
            "sources": rows, "mismatches": sorted(set(mismatches)), "errors": errors,
            "ready": bool(canonical) and not mismatches and not errors}


# --- Release-train schema validators (simplicio.component-release/v1,
#     simplicio.ecosystem-release/v1) — fail-closed per #558 ---------------

COMPONENT_REQUIRED = (
    "component", "repository", "package", "version", "artifacts",
    "compatibility_range", "breaking_change", "changelog",
)


def validate_component_release(schema: Dict[str, Any]) -> "tuple[bool, List[str]]":
    """Fail-closed validation of a simplicio.component-release/v1 manifest."""
    errors: List[str] = []
    if not isinstance(schema, dict):
        return False, ["component-release schema must be an object"]
    missing = [k for k in COMPONENT_REQUIRED if k not in schema]
    if missing:
        errors.append(f"component-release missing required keys: {sorted(missing)}")
    version = schema.get("version", "")
    if not isinstance(version, str) or not VERSION_RE.match(version or ""):
        errors.append(f"component-release.version must be semantic, got {version!r}")
    artifacts = schema.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        errors.append("component-release.artifacts must be a non-empty list")
    else:
        for i, art in enumerate(artifacts):
            if not isinstance(art, dict):
                errors.append(f"component-release.artifacts[{i}] must be an object")
                continue
            for req in ("digest", "size", "signature"):
                val = art.get(req)
                if req == "size":
                    if not isinstance(val, int) or isinstance(val, bool) or val < 0:
                        errors.append(f"component-release.artifacts[{i}].{req} must be int>=0")
                elif not isinstance(val, str) or not val:
                    errors.append(f"component-release.artifacts[{i}].{req} must be a non-empty str")
    if not isinstance(schema.get("compatibility_range"), str) or not schema.get("compatibility_range"):
        errors.append("component-release.compatibility_range must be a non-empty str")
    if not isinstance(schema.get("breaking_change"), bool):
        errors.append("component-release.breaking_change must be a bool")
    if not isinstance(schema.get("changelog"), str) or not schema.get("changelog"):
        errors.append("component-release.changelog must be a non-empty str")
    return (not errors), errors


ECOSYSTEM_REQUIRED = (
    "release_id", "components", "graph_hash", "contract_hashes",
    "status", "evidence", "rollout",
)


def validate_ecosystem_release(schema: Dict[str, Any]) -> "tuple[bool, List[str]]":
    """Fail-closed validation of a simplicio.ecosystem-release/v1 composition."""
    errors: List[str] = []
    if not isinstance(schema, dict):
        return False, ["ecosystem-release schema must be an object"]
    missing = [k for k in ECOSYSTEM_REQUIRED if k not in schema]
    if missing:
        errors.append(f"ecosystem-release missing required keys: {sorted(missing)}")
    if not isinstance(schema.get("release_id"), str) or not schema.get("release_id"):
        errors.append("ecosystem-release.release_id must be a non-empty str")
    components = schema.get("components")
    if not isinstance(components, dict) or not components:
        errors.append("ecosystem-release.components must be a non-empty dict")
    if not isinstance(schema.get("graph_hash"), str) or not schema.get("graph_hash"):
        errors.append("ecosystem-release.graph_hash must be a non-empty str")
    if not isinstance(schema.get("contract_hashes"), dict):
        errors.append("ecosystem-release.contract_hashes must be a dict")
    if not isinstance(schema.get("status"), dict):
        errors.append("ecosystem-release.status must be a dict")
    if not isinstance(schema.get("evidence"), list):
        errors.append("ecosystem-release.evidence must be a list")
    if not isinstance(schema.get("rollout"), dict):
        errors.append("ecosystem-release.rollout must be a dict")
    return (not errors), errors


def release_train_check(repo: str = ".") -> int:
    """Validate component/ecosystem release schemas + local manifest drift.

    Also attaches the ecosystem dependency graph derived from this package's
    pyproject.toml (graph_hash) when ``scripts.component_release`` is importable
    (#558 slice: real-source graph, not a manual permanent list).

    Returns 0 when every fixture validates and the local manifest is ready,
    non-zero otherwise (fail-closed).
    """
    root = Path(repo).resolve()
    schema_errors: List[str] = []
    fixtures_dir = root / "tests" / "fixtures" / "release_train"
    component_fixture = fixtures_dir / "component_release_ok.json"
    ecosystem_fixture = fixtures_dir / "ecosystem_release_ok.json"
    for path, validator in (
        (component_fixture, validate_component_release),
        (ecosystem_fixture, validate_ecosystem_release),
    ):
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            schema_errors.append(f"{path.name}: cannot read ({exc})")
            continue
        ok, errs = validator(data)
        if not ok:
            schema_errors.extend(f"{path.name}: {e}" for e in errs)
    manifest = build_manifest(root)
    graph: Dict[str, Any] = {}
    try:
        # Prefer in-repo scripts.component_release graph builder (real pyproject edges).
        from component_release import build_ecosystem_graph  # type: ignore

        graph = build_ecosystem_graph(root)
    except Exception:
        try:
            from scripts.component_release import build_ecosystem_graph  # type: ignore

            graph = build_ecosystem_graph(root)
        except Exception as exc:
            graph = {"error": f"graph_unavailable: {exc}"}
    ready = (not schema_errors) and bool(manifest.get("ready"))
    summary = {
        "ready": ready,
        "schema_errors": schema_errors,
        "manifest": {
            "schema": manifest.get("schema"),
            "ready": manifest.get("ready"),
            "mismatches": manifest.get("mismatches"),
            "errors": manifest.get("errors"),
        },
        "ecosystem_graph": {
            "schema": graph.get("schema"),
            "graph_hash": graph.get("graph_hash"),
            "edge_count": graph.get("edge_count"),
            "train_edge_count": graph.get("train_edge_count"),
            "error": graph.get("error"),
        },
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if ready else 1


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="release_manifest")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--tag", default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    report = build_manifest(Path(args.repo).resolve(), tag=args.tag)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        print(f"release manifest: {'READY' if report['ready'] else 'BLOCKED'}")
        for item in report["sources"]:
            print(f"- {item['name']}: {item.get('version') or 'missing'}")
        for error in report["errors"] + report["mismatches"]:
            print(f"- error: {error}")
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())