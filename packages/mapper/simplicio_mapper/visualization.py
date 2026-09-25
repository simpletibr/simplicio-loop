"""Versioned, renderer-neutral visualization bundle (issues #185-#190).

This is intentionally a thin projection of existing mapper artifacts.  It does
not invent semantic facts: relationships and flow steps retain their source
evidence and heuristic confidence, while gaps are reported as diagnostics.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any

from . import __version__
from .clustering import build_clustering_metrics
from .flows import build_flow_inventory

VISUALIZATION_SCHEMA = "simplicio.visualization-bundle/v1"
VISUALIZATION_VERSION = 1
PREVIEW_SCHEMA = "simplicio.visualization-preview/v1"
PREVIEW_VERSION = 1
DEFAULT_PREVIEW_BYTES = 16 * 1024
DEFAULT_PREVIEW_LINES = 200
_DENIED_PARTS = {".git", ".simplicio", "node_modules", "vendor", "vendors", "generated", "gen"}
_SECRET_NAMES = re.compile(r"(^|[._-])(env|secret|secrets|credential|credentials|token|password|passwd|private|id_rsa)([._-]|$)", re.I)
_DENIED_EXTENSIONS = {".pem", ".key", ".p12", ".pfx", ".crt", ".der", ".db", ".sqlite", ".sqlite3"}


def _redacted_path(path: str) -> bool:
    parts = path.replace("\\", "/").split("/")
    return (
        any(part in _DENIED_PARTS for part in parts)
        or bool(_SECRET_NAMES.search(parts[-1]))
        or os.path.splitext(parts[-1])[1].lower() in _DENIED_EXTENSIONS
    )


def _stable_id(kind: str, value: str) -> str:
    digest = hashlib.sha256(f"{kind}\0{value}".encode()).hexdigest()[:16]
    return f"{kind}:{digest}"


def _git(root: str, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", root, *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _safe_remote(value: str) -> str:
    value = value.strip().split()[0] if value.strip() else ""
    if value.startswith("git@") and ":" in value:
        host, path = value[4:].split(":", 1)
        value = f"https://{host}/{path}"
    value = re.sub(r"^(?:ssh|git\+ssh)://(?:[^@/]+@)?", "https://", value)
    value = re.sub(r"^(https?://)(?:[^/@]+@)?", r"\1", value)
    value = value.split("?", 1)[0].split("#", 1)[0].rstrip("/")
    return value


def _provenance(root: str) -> dict[str, Any]:
    # `git -C <root> ...` discovers the nearest ancestor `.git` unless `root`
    # itself owns one -- so a fixture/subdirectory with no `.git` of its own
    # (e.g. contracts/*/fixtures/*/source nested inside this very repo) would
    # otherwise silently inherit the enclosing repo's remote/branch/commit as
    # if it were the fixture's own provenance. Only query git when `root` is
    # actually a git worktree root, so a genuine plain-folder clone reports
    # `remote_url`/`branch`/`commit_sha` as null instead of leaking ambient
    # ancestor-repo state.
    git_dir = os.path.join(root, ".git")
    is_git = os.path.exists(git_dir)
    remotes: list[dict[str, str]] = []
    primary = None
    head = ""
    default_ref = ""
    commit_sha = ""
    dirty = False
    if is_git:
        for line in _git(root, "remote", "-v").splitlines():
            parts = line.split()
            if len(parts) >= 2:
                url = _safe_remote(parts[1])
                if url and url not in [item["url"] for item in remotes]:
                    remotes.append({"name": parts[0], "url": url})
        primary = remotes[0]["url"] if remotes else None
        head = _git(root, "symbolic-ref", "--short", "HEAD")
        default_ref = _git(root, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
        commit_sha = _git(root, "rev-parse", "HEAD")
        dirty = bool(_git(root, "status", "--porcelain"))
    match = re.match(r"https?://([^/]+)/([^/]+)/([^/]+?)(?:\.git)?$", primary or "")
    default_branch = default_ref.split("/", 1)[1] if "/" in default_ref else None
    submodules = []
    gitmodules = os.path.join(root, ".gitmodules")
    if os.path.isfile(gitmodules):
        with open(gitmodules, encoding="utf-8", errors="replace") as handle:
            text = handle.read()
        submodules = sorted(re.findall(r"^\s*path\s*=\s*(\S+)", text, re.MULTILINE))
    monorepo_roots = []
    for parent in ("apps", "packages", "services", "projects"):
        base = os.path.join(root, parent)
        if os.path.isdir(base):
            for name in sorted(os.listdir(base)):
                if os.path.isfile(os.path.join(base, name, "package.json")) or os.path.isfile(os.path.join(base, name, "pyproject.toml")):
                    monorepo_roots.append(f"{parent}/{name}")
    return {
        "remote_url": primary,
        "remotes": remotes,
        "host": match.group(1) if match else None,
        "owner": match.group(2) if match else None,
        "repository": match.group(3) if match else None,
        "branch": head or None,
        "commit_sha": commit_sha or None,
        "default_branch": default_branch,
        "dirty": dirty,
        "scan_root": ".",
        "clone_type": "git-worktree" if os.path.isfile(git_dir) else ("git-clone" if is_git else "plain-folder"),
        "submodules": submodules,
        "monorepo_roots": monorepo_roots,
    }


def _node(nodes: list[dict], kind: str, key: str, name: str, path: str | None = None, **extra: Any) -> str:
    node_id = _stable_id(kind, key)
    nodes.append({"id": node_id, "kind": kind, "name": name, "canonical": key, "path": path, "metrics": {}, **extra})
    return node_id


def _edge(edges: list[dict], edge_type: str, source: str, target: str, confidence: float | None, evidence: dict | None = None, language: str | None = None) -> None:
    edges.append({
        "type": edge_type,
        "source": source,
        "target": target,
        "direction": "forward",
        "language": language,
        "confidence": confidence,
        "provenance": "static-mapper",
        "source_location": evidence,
    })


def _language_diagnostic(root: str, file_entry: dict[str, Any]) -> dict[str, Any]:
    """Report only capabilities the mapper actually has for a file."""
    path = file_entry["path"]
    absolute = os.path.join(root, path.replace("/", os.sep))
    line_count = 0
    errors: list[str] = []
    try:
        with open(absolute, "rb") as handle:
            raw = handle.read()
        line_count = raw.count(b"\n") + (1 if raw and not raw.endswith(b"\n") else 0)
        raw.decode("utf-8")
    except UnicodeDecodeError:
        errors.append("non-utf8")
    except OSError as error:
        errors.append(type(error).__name__)
    language = file_entry.get("language") or "text"
    parser = "builtin-regex" if language not in {"json", "yaml", "toml", "markdown", "text"} else "builtin-text"
    return {
        "path": path,
        "language": language,
        "line_count": line_count,
        "parser_used": parser,
        "parser_version": "1",
        "confidence": 0.0 if errors else (0.7 if parser == "builtin-regex" else 1.0),
        "errors": errors,
        "skipped": bool(errors),
        "unsupported_constructs": [],
    }


def _safe_relative_path(root: str, requested: str) -> tuple[str, str]:
    if not requested or "\x00" in requested:
        raise ValueError("path is required")
    root_real = os.path.realpath(root)
    candidate = os.path.abspath(os.path.join(root, requested.replace("/", os.sep)))
    # Compare resolved paths on both sides: on macOS `root` is commonly
    # itself a symlink (e.g. tmp dirs under `/var/folders` -> `/private/var/
    # folders`), and `os.path.realpath(root)` resolves that while `candidate`
    # (built from the unresolved `root`) does not -- an unresolved `candidate`
    # can never share `root_real`'s resolved prefix, so every request was
    # incorrectly rejected as "outside mapped root" on those platforms.
    candidate_real = os.path.realpath(candidate)
    if os.path.commonpath([root_real, candidate_real]) != root_real:
        raise ValueError("path is outside mapped root")
    relative = os.path.relpath(candidate_real, root_real)
    parts = relative.replace(os.sep, "/").split("/")
    if any(part in {"", ".", ".."} for part in parts) or any(part in _DENIED_PARTS for part in parts[:-1]):
        raise ValueError("path is denied by preview policy")
    if _SECRET_NAMES.search(parts[-1]) or os.path.splitext(parts[-1])[1].lower() in _DENIED_EXTENSIONS:
        raise ValueError("path is denied by preview policy")
    try:
        ignored = subprocess.run(
            ["git", "-C", root, "check-ignore", "--no-index", "--quiet", "--", relative],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=2,
        ).returncode == 0
    except (OSError, subprocess.SubprocessError):
        ignored = False
    if ignored:
        raise ValueError("path is denied by preview policy")
    current = root_real
    for part in parts:
        current = os.path.join(current, part)
        if os.path.islink(current):
            raise ValueError("symlink traversal is denied")
    if not os.path.isfile(candidate):
        raise ValueError("path is not a regular file")
    return candidate, relative.replace(os.sep, "/")


def preview_source(
    root: str,
    *,
    path: str | None = None,
    entity_id: str | None = None,
    line_start: int = 1,
    line_end: int | None = None,
    max_bytes: int = DEFAULT_PREVIEW_BYTES,
    max_lines: int = DEFAULT_PREVIEW_LINES,
    allow_full_content: bool = False,
) -> dict[str, Any]:
    """Return bounded, read-only source evidence for a file or mapped symbol."""
    if max_bytes < 1 or max_lines < 1 or line_start < 1 or (line_end is not None and line_end < line_start):
        raise ValueError("preview limits and line range must be positive")
    symbol_name = None
    if entity_id:
        bundle = build_visualization_bundle(root, generated_at="1970-01-01T00:00:00.000Z")
        matches = [node for node in bundle["nodes"] if node["id"] == entity_id]
        if len(matches) != 1 or matches[0]["kind"] not in {"file", "symbol"}:
            raise ValueError("entity id is not a previewable file or symbol")
        node = matches[0]
        path = node.get("path")
        if node["kind"] == "symbol":
            symbol_name = node.get("name")
            line_start = max(1, int(node.get("metrics", {}).get("line", 1)))
    candidate, relative = _safe_relative_path(os.path.abspath(root), path or "")
    with open(candidate, "rb") as handle:
        raw = handle.read()
    if b"\x00" in raw[:4096]:
        raise ValueError("binary files are denied")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("only utf-8 text files are previewable") from error
    lines = text.splitlines()
    if allow_full_content and line_end is None:
        requested_end = len(lines)
        max_lines = max(max_lines, len(lines))
        max_bytes = max(max_bytes, len(raw))
    else:
        requested_end = line_end if line_end is not None else line_start + max_lines - 1
    selected = lines[line_start - 1 : requested_end]
    encoded = "\n".join(selected).encode("utf-8")
    truncated = len(selected) < max(0, requested_end - line_start + 1) or len(encoded) > max_bytes
    if len(encoded) > max_bytes:
        encoded = encoded[:max_bytes]
        selected_text = encoded.decode("utf-8", errors="ignore")
    else:
        selected_text = encoded.decode("utf-8")
    if not allow_full_content:
        selected_text = "\n".join(selected_text.splitlines()[:max_lines])
    return {
        "schema": PREVIEW_SCHEMA,
        "version": PREVIEW_VERSION,
        "path": relative,
        "entity_id": entity_id,
        "symbol": symbol_name,
        "language": _canonical_language(relative),
        "encoding": "utf-8",
        "line_start": line_start,
        "line_end": min(requested_end, len(lines)),
        "content": selected_text,
        "truncated": truncated,
        "revision_fingerprint": hashlib.sha256(raw).hexdigest(),
        "sensitivity_warning": "full-content export was explicitly requested" if allow_full_content else None,
        "read_only": True,
    }


def _canonical_language(path: str) -> str:
    from .mapper import _language_for

    return _language_for(path)


def _stable_project_name(root: str, project: dict[str, Any]) -> str:
    """Prefer a manifest identity when a plain clone has no Git remote."""
    name = project.get("product", {}).get("name") or ""
    if name and name != os.path.basename(root):
        return name
    pyproject = os.path.join(root, "pyproject.toml")
    try:
        with open(pyproject, encoding="utf-8") as handle:
            for line in handle:
                match = re.match(r"\s*name\s*=\s*['\"]([^'\"]+)['\"]", line)
                if match:
                    return match.group(1)
    except OSError:
        pass
    return name or os.path.basename(root)


def run_preview_cli(opts: dict[str, Any]) -> int:
    try:
        payload = preview_source(
            opts["root"],
            path=opts.get("path") or None,
            entity_id=opts.get("entity_id") or None,
            line_start=opts.get("line", 1),
            max_lines=opts.get("max_lines", DEFAULT_PREVIEW_LINES),
            max_bytes=opts.get("max_bytes", DEFAULT_PREVIEW_BYTES),
            allow_full_content=opts.get("allow_full_content", False),
        )
    except (OSError, ValueError) as error:
        if opts.get("json"):
            print(json.dumps({"schema": PREVIEW_SCHEMA, "error": str(error)}, sort_keys=True))
        else:
            print(f"preview denied: {error}", file=sys.stderr)
        return 1
    if opts.get("json"):
        print(json.dumps(payload, sort_keys=True))
    else:
        print(f"path={payload['path']} lines={payload['line_start']}-{payload['line_end']} truncated={payload['truncated']}")
    return 0


def build_visualization_bundle(
    root: str,
    artifacts: dict[str, Any] | None = None,
    generated_at: str | None = None,
    clustering_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a stable bundle from mapper artifacts without changing old outputs."""
    from .mapper import build_artifacts

    root = os.path.abspath(root or os.getcwd())
    artifacts = artifacts or build_artifacts(root)
    project = artifacts["project_map"]
    architecture = artifacts["architecture_inventory"]
    symbols = artifacts["symbol_index"].get("symbols") or []
    call_graph = artifacts["call_graph"].get("edges") or []
    flows = build_flow_inventory(root, artifacts)
    bundle_time = generated_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    flows["generated_at"] = bundle_time
    for flow in flows.get("flows") or []:
        flow["generated_at"] = bundle_time
    nodes: list[dict] = []
    edges: list[dict] = []
    provenance = _provenance(root)
    # A plain-folder clone name is ephemeral. Prefer the mapper's stable
    # product identity so Canvas IDs survive clone-to-clone imports.
    project_name = _stable_project_name(root, project)
    repo_key = provenance.get("remote_url") or project_name
    repo_id = _node(nodes, "repository", repo_key, provenance.get("repository") or project_name, **{"parent_id": None})
    module_ids: dict[str, str] = {}
    file_ids: dict[str, str] = {}
    symbol_ids: dict[tuple[str, str], str] = {}
    for module in architecture.get("modules") or project.get("modules") or []:
        name = module.get("name") if isinstance(module, dict) else str(module)
        module_ids[name] = _node(nodes, "module", name, name, parent_id=repo_id)
        _edge(edges, "contains", repo_id, module_ids[name], 1.0)
    for layer in architecture.get("layers") or []:
        layer_name = layer.get("name", "unclassified")
        layer_id = _node(nodes, "layer", layer_name, layer_name, parent_id=repo_id, confidence=0.7, rule_id="mapper.layer-path")
        _edge(edges, "groups", repo_id, layer_id, 0.7)
    for file_entry in project.get("files") or []:
        path = file_entry["path"]
        if _redacted_path(path):
            continue
        module = file_entry.get("module") or (path.split("/", 1)[0] if "/" in path else ".")
        file_ids[path] = _node(nodes, "file", path, PurePosixPath(path).name, path=path, parent_id=module_ids.get(module, repo_id), language=file_entry.get("language", "text"), metrics={"size_bytes": file_entry.get("size_bytes", 0)})
        _edge(edges, "contains", module_ids.get(module, repo_id), file_ids[path], 1.0, {"path": path})
    for symbol in symbols:
        key = (symbol.get("defined_in", ""), symbol.get("qualified_name") or symbol.get("name", ""))
        symbol_ids[key] = _node(nodes, "symbol", "\0".join(key), symbol.get("name", key[1]), path=key[0], parent_id=file_ids.get(key[0], repo_id), metrics={"line": symbol.get("line", 0)})
        _edge(edges, "contains", file_ids.get(key[0], repo_id), symbol_ids[key], 1.0, {"path": key[0], "line": symbol.get("line", 0)})
    for relation in call_graph:
        source = file_ids.get(relation.get("source_file", ""), repo_id)
        target = file_ids.get(relation.get("target_file", ""))
        if relation.get("source_symbol"):
            source = symbol_ids.get((relation.get("source_file", ""), relation["source_symbol"]), source)
        if relation.get("target_symbol"):
            target = symbol_ids.get((relation.get("target_file", ""), relation["target_symbol"]), target)
        if target is None:
            unknown_key = relation.get("relation_id") or relation.get("target_symbol") or "unknown"
            target = _node(nodes, "external", f"unknown:{unknown_key}", "unknown target")
        relation_evidence = {
            "path": relation.get("source_file"),
            **({"line": relation.get("line")} if relation.get("line") else {}),
            **({"relation_id": relation.get("relation_id")} if relation.get("relation_id") else {}),
            **({"evidence_class": relation.get("evidence_class")} if relation.get("evidence_class") else {}),
        }
        _edge(edges, relation.get("type", "depends-on"), source, target, relation.get("confidence"), relation_evidence)
    for flow in flows.get("flows") or []:
        flow_id = _node(nodes, "flow", flow["id"], flow["id"], parent_id=repo_id, confidence=1.0 if flow.get("confidence") == "observed" else 0.5)
        _edge(edges, "contains", repo_id, flow_id, 1.0)
        previous = flow_id
        for step in flow.get("steps") or []:
            target = file_ids.get(step.get("path"), repo_id)
            _edge(edges, "transitions-to", previous, target, 1.0 if flow.get("confidence") == "observed" else 0.5, {"path": step.get("path"), "line": step.get("line", 0)})
            previous = target
    nodes.sort(key=lambda item: (item["kind"], item["canonical"]))
    edges.sort(key=lambda item: (item["type"], item["source"], item["target"], json.dumps(item.get("source_location"), sort_keys=True)))
    clustering_artifacts = dict(artifacts)
    clustering_artifacts["flows"] = flows
    clustering = build_clustering_metrics(root, clustering_artifacts, clustering_config, generated_at=bundle_time)
    provenance["clustering"] = clustering["provenance"]
    language_diagnostics = [
        _language_diagnostic(root, entry)
        for entry in project.get("files") or []
        if not _redacted_path(entry["path"])
    ]
    return {
        "schema": VISUALIZATION_SCHEMA,
        "version": VISUALIZATION_VERSION,
        "mapper_version": __version__,
        "schema_version": "v1",
        "capabilities": ["hierarchy", "typed-edges", "flows", "provenance", "source-preview", "language-diagnostics", "clustering-metrics", "layout-hints"],
        "generated_at": bundle_time,
        "provenance": provenance,
        "project": {"id": repo_id, "name": project_name, "root": "."},
        "nodes": nodes,
        "edges": edges,
        "clustering": clustering,
        "layout_hints": clustering["layout_hints"],
        "flows": flows.get("flows") or [],
        "language_diagnostics": language_diagnostics,
        "diagnostics": [{"code": "heuristic-edge", "count": sum(1 for edge in edges if edge["confidence"] is None or edge["confidence"] < 1.0)}, {"code": "unresolved-relation", "count": sum(1 for node in nodes if node["kind"] == "external")}],
    }


__all__ = ["PREVIEW_SCHEMA", "PREVIEW_VERSION", "VISUALIZATION_SCHEMA", "VISUALIZATION_VERSION", "build_visualization_bundle", "preview_source"]
