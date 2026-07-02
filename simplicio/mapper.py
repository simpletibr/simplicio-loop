"""Structured mapper artifact loading for simplicio-dev-cli.

The mapper repo produces optional JSON artifacts. This module keeps their
consumer contract small, deterministic, and backward compatible with projects
that only have source files.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .toon_codec import to_toon
from .utils.serialization import loads


def _toon_enabled() -> bool:
    """Kill switch for TOON-encoded prompt context (issue #85 AC: config flag
    to disable). Default on — TOON is lossless and ~40% cheaper in tokens for
    the uniform arrays this module emits."""
    return os.environ.get("SIMPLICIO_PROMPT_TOON", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


PROJECT_MAP_CANDIDATES = (
    ".simplicio/project-map.json",
    "project-map.json",
    ".mapper/project-map.json",
)
PRECEDENT_INDEX_CANDIDATES = (
    ".simplicio/precedent-index.json",
    "precedent-index.json",
    ".mapper/precedent-index.json",
)

MAPPER_BIN = "simplicio-mapper"
_MAPPER_CLI_CACHE: dict[tuple[str, ...], dict[str, Any] | None] = {}


def _mapper_cli_enabled() -> bool:
    return os.environ.get("SIMPLICIO_MAPPER_CLI", "1") != "0"


def run_mapper_json(
    root: str | os.PathLike[str],
    subcommand: str,
    *,
    extra: tuple[str, ...] = (),
    timeout: int = 30,
) -> dict[str, Any] | None:
    """Run `simplicio-mapper <subcommand> <root> [extra...] --json` fail-open.

    Returns the parsed JSON dict, or None on ANY failure (binary missing, env
    kill-switch SIMPLICIO_MAPPER_CLI=0, non-zero exit, timeout, bad JSON) —
    callers keep their artifact-file fallback. Results are memoized per
    (root, subcommand, extra) for the process lifetime; the mapper verbs used
    here (`inspect`, `handoff`, `ask`) are read-only and fast (~60ms).
    """
    if not _mapper_cli_enabled():
        return None
    base = str(Path(root).resolve())
    key = (base, subcommand, *extra)
    if key in _MAPPER_CLI_CACHE:
        return _MAPPER_CLI_CACHE[key]
    result: dict[str, Any] | None = None
    exe = shutil.which(MAPPER_BIN)
    if exe:
        try:
            proc = subprocess.run(
                [exe, subcommand, base, *extra, "--json"],
                capture_output=True, text=True, timeout=timeout, check=False,
            )
            if proc.returncode == 0:
                data = loads(proc.stdout)
                if isinstance(data, dict):
                    result = data
        except (OSError, ValueError, subprocess.SubprocessError):
            result = None
    _MAPPER_CLI_CACHE[key] = result
    return result


def map_inspection(root: str | os.PathLike[str]) -> dict[str, Any] | None:
    """mapper 0.13 `inspect` — per-artifact on-disk evidence (simplicio.map-inspection/v1)."""
    return run_mapper_json(root, "inspect")


def map_handoff(root: str | os.PathLike[str]) -> dict[str, Any] | None:
    """mapper 0.13 `handoff` — compact context-pack for downstream agents (simplicio.map-handoff/v1)."""
    return run_mapper_json(root, "handoff")


ASK_VERBS = ("callers", "callees", "reaches", "impact", "flows", "rules", "tests-for", "term")


def map_ask(root: str | os.PathLike[str], verb: str, arg: str = "") -> list[dict[str, Any]] | None:
    """mapper 0.14 `ask` — low-token structured queries over the built artifacts.

    Returns the `results` list from `simplicio.ask/v1`, or None when the CLI is
    unavailable/fails or the verb is unknown — callers treat None as "no data",
    never as an empty answer.
    """
    if verb not in ASK_VERBS:
        return None
    extra = (verb, arg) if arg else (verb,)
    data = run_mapper_json(root, "ask", extra=extra)
    if data is None:
        return None
    results = data.get("results")
    return [item for item in results if isinstance(item, dict)] if isinstance(results, list) else None


def _safe_json(path: Path) -> dict[str, Any] | None:
    try:
        data = loads(path.read_bytes())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def load_artifact(root: str | os.PathLike[str], candidates: tuple[str, ...]) -> tuple[Path, dict[str, Any]] | None:
    base = Path(root)
    for rel in candidates:
        path = base / rel
        if not path.exists():
            continue
        data = _safe_json(path)
        if data is not None:
            return path, data
    return None


def load_project_map(root: str | os.PathLike[str]) -> tuple[Path, dict[str, Any]] | None:
    return load_artifact(root, PROJECT_MAP_CANDIDATES)


def load_precedent_index(root: str | os.PathLike[str]) -> tuple[Path, dict[str, Any]] | None:
    return load_artifact(root, PRECEDENT_INDEX_CANDIDATES)


def artifact_status(root: str | os.PathLike[str]) -> dict[str, Any]:
    base = Path(root).resolve()
    project_map_loaded = load_project_map(base)
    precedent_loaded = load_precedent_index(base)

    payload: dict[str, Any] = {
        "root": str(base),
        "project_map": {"present": False, "path": None, "schema": None},
        "precedent_index": {"present": False, "path": None, "schema": None},
    }

    if project_map_loaded is not None:
        map_path, project_map = project_map_loaded
        payload["project_map"] = {
            "present": True,
            "path": str(map_path),
            "schema": project_map.get("schema"),
            "generated_at": project_map.get("generated_at"),
            "entry_points": _as_list(project_map.get("entry_points")),
            "test_files": _as_list(project_map.get("test_files")),
            "config_files": _as_list(project_map.get("config_files")),
            "recent_changes": [
                item
                for item in _as_list(project_map.get("recent_changes"))
                if isinstance(item, dict)
            ],
            "module_names": [
                str(module.get("name"))
                for module in _as_list(project_map.get("modules"))
                if isinstance(module, dict) and module.get("name")
            ],
        }

    if precedent_loaded is not None:
        precedent_path, precedent_index = precedent_loaded
        raw_items = precedent_index.get("items", precedent_index.get("precedents", []))
        payload["precedent_index"] = {
            "present": True,
            "path": str(precedent_path),
            "schema": precedent_index.get("schema"),
            "items": len([item for item in _as_list(raw_items) if isinstance(item, dict)]),
        }

    inspection = map_inspection(base)
    if inspection is not None:
        evidence = inspection.get("evidence")
        payload["inspection"] = {
            "schema": inspection.get("schema"),
            "evidence": evidence.get("artifacts") if isinstance(evidence, dict) else None,
            "warnings": _as_list(inspection.get("warnings")),
        }

    return payload


def inspect_target(
    root: str | os.PathLike[str],
    target: str,
    *,
    goal: str = "",
    limit: int = 8,
    precedent_limit: int = 3,
) -> dict[str, Any]:
    base = Path(root).resolve()
    artifacts = artifact_status(base)
    payload: dict[str, Any] = {
        "root": str(base),
        "target": target,
        "goal": goal,
        "artifacts": artifacts,
        "relevant_files": [],
        "precedents": rank_precedents(base, f"{goal} {target}", k=precedent_limit),
        "context": build_mapper_context(base, target, goal=goal),
    }

    # mapper 0.14+: structured impact + affected-tests for the target, straight
    # from the built artifacts (simplicio.ask/v1). Fail-open: keys are only
    # present when the CLI answered — an absent key means "no data", never
    # "no impact".
    if target:
        impact = map_ask(base, "impact", target)
        if impact is not None:
            payload["impact"] = impact[:limit]
        tests_for = map_ask(base, "tests-for", target)
        if tests_for is not None:
            payload["affected_tests"] = tests_for[:limit]

    loaded_map = load_project_map(base)
    if loaded_map is None:
        return payload

    _map_path, project_map = loaded_map
    entries = _file_entries(project_map)
    payload["relevant_files"] = rank_entries(entries, target=target, query=goal, limit=limit)
    return payload


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _file_entries(project_map: dict[str, Any]) -> list[dict[str, Any]]:
    files = project_map.get("files", [])
    if isinstance(files, dict):
        entries = []
        for path, meta in files.items():
            item = dict(meta or {}) if isinstance(meta, dict) else {}
            item.setdefault("path", path)
            entries.append(item)
        return entries
    return [f for f in files if isinstance(f, dict)]


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-zA-Z0-9_./-]+", text.lower()) if len(t) > 2}


def _entry_text(entry: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("path", "language", "summary", "change_type"):
        value = entry.get(key)
        if value:
            parts.append(str(value))
    for key in ("roles", "tags", "imports", "exports"):
        parts.extend(str(v) for v in _as_list(entry.get(key)))
    return " ".join(parts)


def rank_entries(entries: list[dict[str, Any]], *, target: str = "", query: str = "", limit: int = 8) -> list[dict[str, Any]]:
    query_tokens = _tokens(f"{target} {query}")
    ranked: list[tuple[float, dict[str, Any]]] = []
    for entry in entries:
        path = str(entry.get("path", ""))
        score = float(entry.get("importance", entry.get("score", 0)) or 0)
        if target and path == target:
            score += 5
        if target and (path.endswith(target) or target.endswith(path)):
            score += 2
        overlap = query_tokens & _tokens(_entry_text(entry))
        score += len(overlap) * 0.5
        if any(role in _as_list(entry.get("roles")) for role in ("entrypoint", "test", "config")):
            score += 0.25
        if score > 0:
            ranked.append((score, entry))
    ranked.sort(key=lambda item: (-item[0], str(item[1].get("path", ""))))
    return [entry for _score, entry in ranked[:limit]]


def rank_precedents(root: str | os.PathLike[str], task: str, *, stack: str = "", k: int = 2) -> list[dict[str, Any]]:
    loaded = load_precedent_index(root)
    if loaded is None:
        return []
    _path, index = loaded
    raw_items = index.get("items", index.get("precedents", []))
    items = [item for item in raw_items if isinstance(item, dict)]
    ranked = rank_entries(items, target=stack, query=task, limit=k)
    return ranked[:k]


def _read_target_fallback(root: Path, target: str) -> str:
    try:
        text = (root / target).read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return "(mapper: target not read)"
    deps = [
        line
        for line in text.splitlines()
        if line.strip().startswith(("import", "using", "from", "require(", "const "))
    ][:15]
    return "File: {target}\nDependencies:\n{deps}".format(
        target=target,
        deps="\n".join(deps) if deps else "(none detected)",
    )


def _render_handoff_context(pack: dict[str, Any], base: Path, target: str) -> str | None:
    """Render a mapper 0.13 handoff context_pack into the {{TARGET}} context block.

    Returns None when the pack says it is not enough (`needs_broader_context`)
    or carries no files — the caller then falls back to the project-map render.
    """
    files = [f for f in _as_list(pack.get("files")) if isinstance(f, dict)]
    if not files or pack.get("needs_broader_context"):
        return None

    lines = ["Mapper handoff pack (simplicio.map-handoff/v1)"]
    pack_hash = pack.get("pack_hash")
    if pack_hash:
        lines.append(f"Pack hash: {pack_hash}")

    deps = pack.get("dependencies")
    if isinstance(deps, dict):
        runtime_deps = [str(d) for d in _as_list(deps.get("runtime"))][:10]
        if runtime_deps:
            lines.append("Dependencies: " + ", ".join(runtime_deps))

    lines.append("Files:")
    for entry in files[:12]:
        path = entry.get("path", "(unknown)")
        bits = [f"path={path}"]
        if entry.get("language"):
            bits.append(f"lang={entry['language']}")
        symbols = [
            str(sym.get("name"))
            for sym in _as_list(entry.get("symbols"))
            if isinstance(sym, dict) and sym.get("name")
        ][:8]
        if symbols:
            bits.append("symbols=" + ",".join(symbols))
        imports = [str(i) for i in _as_list(entry.get("imports"))][:6]
        if imports:
            bits.append("imports=" + ",".join(imports))
        lines.append("- " + " | ".join(bits))

    recent = [c for c in _as_list(pack.get("recent_changes")) if isinstance(c, dict)][:6]
    if recent:
        lines.append("Recent changes:")
        for item in recent:
            lines.append(f"- {item.get('path', '?')} ({item.get('status', 'changed')})")

    fallback = _read_target_fallback(base, target)
    return "\n".join(lines + ["", "Target fallback:", fallback])


def build_mapper_context(root: str | os.PathLike[str], target: str, *, goal: str = "") -> str:
    base = Path(root)

    # mapper 0.13+: prefer the pre-compressed handoff context-pack (files +
    # symbols + deps + pack_hash) over re-deriving context from project-map.
    # Fail-open: any miss falls through to the artifact-file path below.
    handoff = map_handoff(base)
    if handoff is not None:
        pack = handoff.get("context_pack")
        if isinstance(pack, dict):
            rendered = _render_handoff_context(pack, base, target)
            if rendered is not None:
                return rendered

    loaded_map = load_project_map(base)
    if loaded_map is None:
        return _read_target_fallback(base, target)

    map_path, project_map = loaded_map
    entries = _file_entries(project_map)
    relevant = rank_entries(entries, target=target, query=goal, limit=8)
    precedents = rank_precedents(base, f"{goal} {target}", k=3)

    lines = [
        f"Mapper artifact: {map_path.relative_to(base)}",
        f"Schema: {project_map.get('schema', 'unknown')}",
    ]
    generated_at = project_map.get("generated_at")
    if generated_at:
        lines.append(f"Generated: {generated_at}")

    arch = project_map.get("architecture", {})
    signals = arch.get("signals") if isinstance(arch, dict) else None
    if signals:
        lines.append("Architecture signals: " + ", ".join(str(s) for s in _as_list(signals)[:10]))

    for key, label in (("entry_points", "Entry points"), ("test_files", "Tests"), ("config_files", "Config")):
        values = _as_list(project_map.get(key))[:8]
        if values:
            lines.append(f"{label}: " + ", ".join(str(v) for v in values))

    modules = _as_list(project_map.get("modules"))[:5]
    if modules:
        lines.append("Modules:")
        for module in modules:
            if isinstance(module, dict):
                name = module.get("name", "(unnamed)")
                files = ", ".join(str(f) for f in _as_list(module.get("files"))[:5])
                lines.append(f"- {name}: {files}".rstrip(": "))

    if relevant:
        if _toon_enabled():
            # Relevant files is a genuinely uniform array of objects (every
            # entry gets the same 4 flattened scalar fields), the sweet spot
            # TOON was built for — issue #85: precedent/context payloads
            # embedded into the LLM prompt go through TOON instead of raw
            # JSON/hand-rolled bullets to cut prompt tokens losslessly.
            normalized = [
                {
                    "path": str(entry.get("path", "(unknown)")),
                    "language": str(entry.get("language") or ""),
                    "roles": ",".join(str(r) for r in _as_list(entry.get("roles"))),
                    "imports": ",".join(str(i) for i in _as_list(entry.get("imports"))[:6]),
                }
                for entry in relevant
            ]
            lines.append("Relevant files (TOON — https://github.com/toon-format/toon):")
            lines.append(to_toon(normalized))
        else:
            lines.append("Relevant files:")
            for entry in relevant:
                path = entry.get("path", "(unknown)")
                roles = ",".join(str(r) for r in _as_list(entry.get("roles")))
                imports = ",".join(str(i) for i in _as_list(entry.get("imports"))[:6])
                bits = [f"path={path}"]
                if entry.get("language"):
                    bits.append(f"lang={entry['language']}")
                if roles:
                    bits.append(f"roles={roles}")
                if imports:
                    bits.append(f"imports={imports}")
                lines.append("- " + " | ".join(bits))

    recent = _as_list(project_map.get("recent_changes"))[:6]
    if recent:
        lines.append("Recent changes:")
        for item in recent:
            if isinstance(item, dict):
                lines.append(f"- {item.get('path', '?')} ({item.get('status', 'changed')})")

    if precedents:
        lines.append("Precedent candidates:")
        for item in precedents:
            loc = f"{item.get('path', '(unknown)')}:{item.get('line', 1)}"
            summary = item.get("summary") or item.get("change_type") or "similar code"
            lines.append(f"- {loc} — {summary}")

    fallback = _read_target_fallback(base, target)
    return "\n".join(lines + ["", "Target fallback:", fallback])
