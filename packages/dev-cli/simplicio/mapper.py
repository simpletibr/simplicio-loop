"""Structured mapper artifact loading for simplicio-dev-cli.

The mapper repo produces optional JSON artifacts. This module keeps their
consumer contract small, deterministic, and backward compatible with projects
that only have source files.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .observability import emit_event, estimate_tokens, record_savings_event
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
    ".simplicio-loop/project-map.json",
    "project-map.json",
    ".mapper/project-map.json",
)
PRECEDENT_INDEX_CANDIDATES = (
    ".simplicio-loop/precedent-index.json",
    "precedent-index.json",
    ".mapper/precedent-index.json",
)

MAPPER_BIN = "simplicio-mapper"
ECC_SOURCE_REPOSITORY = "https://github.com/affaan-m/ECC"
ECC_DEFAULT_REF = "0c1d7be9a750627fb2a6534c78a998cc46d03f9c"
ECC_GUIDANCE_SCHEMA = "simplicio.ecc-guidance/v1"
ECC_GUIDANCE_REF_SCHEMA = "simplicio.ecc-guidance-ref/v1"
ECC_DEFAULT_MANIFEST_HASH = "c5a9a1624f07d822f566c7bac07acb47544359ae6e2a2fb69f504f1201813384"
_ECC_MAX_GUIDANCE_CHARS = 12000
_ECC_MAX_COMPONENTS = 8
_MAPPER_CLI_CACHE: dict[tuple[str, ...], dict[str, Any] | None] = {}


class EccGuidanceValidationError(ValueError):
    """Raised only when explicitly required ECC guidance cannot be verified."""


def _mapper_cli_enabled() -> bool:
    return os.environ.get("SIMPLICIO_MAPPER_CLI", "1") != "0"


def run_mapper_json(
    root: str | os.PathLike[str],
    subcommand: str,
    *,
    extra: tuple[str, ...] = (),
    timeout: int = 30,
    revision: str = "",
    snapshot_id: str = "",
) -> dict[str, Any] | None:
    """Run `simplicio-mapper <subcommand> <root> [extra...] --json` fail-open.

    Returns the parsed JSON dict, or None on ANY failure (binary missing, env
    kill-switch SIMPLICIO_MAPPER_CLI=0, non-zero exit, timeout, bad JSON) —
    callers keep their artifact-file fallback. Results are memoized per
    (root, subcommand, revision, snapshot_id, extra) for the process
    lifetime; the mapper verbs used here (`inspect`, `handoff`, `ask`) are
    read-only and fast (~60ms).

    ``revision``/``snapshot_id`` default to `""` for callers that don't carry
    a `simplicio.plan_compiler.ContextSnapshot` (today's pipeline/CLI call
    sites), which preserves the previous cache behavior for them. Callers
    that DO have a `ContextSnapshot` (or an equivalent revision marker) must
    pass it here: it is always folded into the cache key so a long-lived
    process can never serve context cached under one revision/snapshot_id as
    if it were another (issue #166 AC: "Cache nunca cruza revision/
    snapshot_id").
    """
    if not _mapper_cli_enabled():
        return None
    base = str(Path(root).resolve())
    key = (base, subcommand, revision, snapshot_id, *extra)
    if key in _MAPPER_CLI_CACHE:
        return _MAPPER_CLI_CACHE[key]
    result: dict[str, Any] | None = None
    exe = shutil.which(MAPPER_BIN)
    if exe:
        try:
            proc = subprocess.run(
                [exe, subcommand, base, *extra, "--json"],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            if proc.returncode == 0:
                data = loads(proc.stdout)
                if isinstance(data, dict):
                    result = data
        except (OSError, ValueError, subprocess.SubprocessError):
            result = None
    _MAPPER_CLI_CACHE[key] = result
    return result


def _ecc_enabled() -> bool:
    configured = os.environ.get("SIMPLICIO_ECC_ENABLED")
    if configured is not None:
        return configured.strip().lower() in {"1", "true", "yes", "on", "enabled"}
    return bool(os.environ.get("SIMPLICIO_ECC_ROOT", "").strip())


def run_mapper_ecc_json(
    root: str | os.PathLike[str],
    *,
    stage: str = "planning",
    role_id: str = "mapper-planner",
    timeout: int = 30,
    revision: str = "",
    snapshot_id: str = "",
) -> dict[str, Any] | None:
    """Run the Mapper's separate ECC pack command, fail-open when unconfigured.

    ECC is deliberately not a field in ``simplicio.map-handoff/v1``. This
    command is an opt-in side channel whose output is validated before it can
    enter a prompt or an evidence reference.
    """
    if not _mapper_cli_enabled() or not _ecc_enabled():
        return None
    base = str(Path(root).resolve())
    ecc_config = tuple(
        os.environ.get(name, "")
        for name in (
            "SIMPLICIO_ECC_ROOT",
            "SIMPLICIO_ECC_MANIFEST",
            "SIMPLICIO_ECC_ENABLED",
            "SIMPLICIO_ECC_REQUIRED",
            "SIMPLICIO_ECC_REQUIRE_REF",
            "SIMPLICIO_ECC_MAX_CONTEXT_CHARS",
        )
    )
    key = (
        base,
        "ecc-pack",
        revision,
        snapshot_id,
        stage,
        role_id,
        *ecc_config,
    )
    if key in _MAPPER_CLI_CACHE:
        return _MAPPER_CLI_CACHE[key]
    result: dict[str, Any] | None = None
    exe = shutil.which(MAPPER_BIN)
    if exe:
        try:
            proc = subprocess.run(
                [exe, "ecc", "pack", "--stage", stage, "--role", role_id, "--json"],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            if proc.returncode == 0 or proc.stdout.strip():
                data = loads(proc.stdout)
                if isinstance(data, dict):
                    result = data
        except (OSError, ValueError, subprocess.SubprocessError):
            result = None
    _MAPPER_CLI_CACHE[key] = result
    return result


def map_inspection(
    root: str | os.PathLike[str], *, revision: str = "", snapshot_id: str = ""
) -> dict[str, Any] | None:
    """mapper 0.13 `inspect` — per-artifact on-disk evidence (simplicio.map-inspection/v1)."""
    return run_mapper_json(root, "inspect", revision=revision, snapshot_id=snapshot_id)


def map_handoff(
    root: str | os.PathLike[str], *, revision: str = "", snapshot_id: str = ""
) -> dict[str, Any] | None:
    """mapper 0.13 `handoff` — compact context-pack for downstream agents (simplicio.map-handoff/v1)."""
    return run_mapper_json(root, "handoff", revision=revision, snapshot_id=snapshot_id)


def _canonical_hash(value: dict[str, Any]) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _validated_ecc_guidance(
    guidance: dict[str, Any] | None, root: str | os.PathLike[str]
) -> dict[str, Any] | None:
    if not isinstance(guidance, dict):
        return None

    def reject(reason: str, **details: Any) -> None:
        emit_event("ecc_guidance_rejected", {"reason": reason, **details}, root=str(root))

    if guidance.get("schema") != ECC_GUIDANCE_SCHEMA:
        reject("unsupported_schema", schema=guidance.get("schema"))
        return None
    required = {
        "schema",
        "status",
        "stage",
        "role_id",
        "source",
        "provenance",
        "manifest_hash",
        "pack_hash",
        "authority",
        "execution_policy",
        "hooks",
        "orchestration",
        "prompt",
        "skills",
        "agents",
        "missing",
        "blocked_components",
        "errors",
    }
    allowed = required
    if not required.issubset(guidance):
        reject("missing_fields")
        return None
    unknown = sorted(set(guidance) - allowed)
    if unknown:
        reject("unknown_fields", fields=unknown)
        return None
    if guidance.get("status") != "READY":
        return None
    if (
        not isinstance(guidance.get("stage"), str)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", guidance["stage"])
        or not isinstance(guidance.get("role_id"), str)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", guidance["role_id"])
    ):
        reject("identifier_bounds")
        return None
    for field in ("missing", "blocked_components", "errors"):
        if not isinstance(guidance.get(field), list) or not all(
            isinstance(item, str) for item in guidance[field]
        ):
            reject("diagnostic_shape", field=field)
            return None
    if any(guidance[field] for field in ("missing", "blocked_components", "errors")):
        reject("ready_with_diagnostics")
        return None
    source = guidance.get("source")
    if (
        not isinstance(source, dict)
        or set(source) != {"repository", "ref"}
        or source.get("repository") != ECC_SOURCE_REPOSITORY
    ):
        reject("source_repository_mismatch")
        return None
    if source.get("ref") != ECC_DEFAULT_REF:
        reject("source_ref_mismatch")
        return None
    provenance = guidance.get("provenance")
    if (
        not isinstance(provenance, dict)
        or not {"status", "expected_ref", "observed_ref"}.issubset(provenance)
        or set(provenance) - {"status", "expected_ref", "observed_ref", "reason"}
        or provenance.get("status") != "VERIFIED"
    ):
        reject("provenance_unverified")
        return None
    if provenance.get("expected_ref") != ECC_DEFAULT_REF or provenance.get("observed_ref") != ECC_DEFAULT_REF:
        reject("provenance_ref_mismatch")
        return None
    if (
        guidance.get("authority") != "simplicio-mapper"
        or guidance.get("execution_policy") != "advisory-only"
        or guidance.get("hooks") != "disabled"
        or guidance.get("orchestration") != "disabled"
    ):
        reject("unsafe_policy")
        return None
    prompt = guidance.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > _ECC_MAX_GUIDANCE_CHARS:
        reject("prompt_bounds")
        return None
    if guidance.get("manifest_hash") != ECC_DEFAULT_MANIFEST_HASH:
        reject("manifest_hash_mismatch")
        return None
    if not isinstance(guidance.get("pack_hash"), str) or not re.fullmatch(
        r"[0-9a-f]{64}", guidance["pack_hash"]
    ):
        reject("pack_hash_missing")
        return None
    without_pack_hash = dict(guidance)
    without_pack_hash.pop("pack_hash", None)
    if _canonical_hash(without_pack_hash) != guidance["pack_hash"]:
        reject("pack_hash_mismatch")
        return None
    for kind in ("skills", "agents"):
        components = guidance.get(kind)
        if not isinstance(components, list) or len(components) > _ECC_MAX_COMPONENTS:
            reject("component_bounds", kind=kind)
            return None
        expected_prefix = "skills/" if kind == "skills" else "agents/"
        for component in components:
            if not isinstance(component, dict):
                reject("component_shape", kind=kind)
                return None
            if set(component) != {
                "name",
                "kind",
                "path",
                "sha256",
                "content_sha256",
                "content",
                "truncated",
            }:
                reject("component_unknown_fields", kind=kind)
                return None
            path = component.get("path")
            content = component.get("content")
            content_hash = component.get("content_sha256")
            raw_hash = component.get("sha256")
            if (
                not isinstance(path, str)
                or not path.startswith(expected_prefix)
                or ".." in Path(path).parts
                or not isinstance(content, str)
                or component.get("kind") != kind[:-1]
                or not isinstance(component.get("name"), str)
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", component["name"])
                or not isinstance(content_hash, str)
                or not re.fullmatch(r"[0-9a-f]{64}", content_hash)
                or not isinstance(raw_hash, str)
                or not re.fullmatch(r"[0-9a-f]{64}", raw_hash)
                or not isinstance(component.get("truncated"), bool)
            ):
                reject("component_provenance", kind=kind)
                return None
            if hashlib.sha256(content.encode("utf-8")).hexdigest() != content_hash:
                reject("component_content_hash_mismatch", kind=kind)
                return None
            if not component.get("truncated", False) and content_hash != raw_hash:
                reject("component_hash_mismatch", kind=kind)
                return None
    emit_event(
        "ecc_guidance_bound",
        {
            "status": guidance["status"],
            "pack_hash": guidance["pack_hash"],
            "manifest_hash": guidance["manifest_hash"],
            "source": guidance.get("source"),
            "provenance": guidance.get("provenance"),
        },
        root=str(root),
    )
    return guidance


def map_ecc_guidance(
    root: str | os.PathLike[str], *, revision: str = "", snapshot_id: str = ""
) -> dict[str, Any] | None:
    """Return a validated Mapper-owned ECC advisory block, if opted in."""
    guidance = _validated_ecc_guidance(
        run_mapper_ecc_json(root, revision=revision, snapshot_id=snapshot_id),
        root,
    )
    required = os.environ.get("SIMPLICIO_ECC_REQUIRED", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
        "enabled",
    }
    if required and guidance is None:
        raise EccGuidanceValidationError(
            "SIMPLICIO_ECC_REQUIRED is enabled, but the Mapper returned no verified ECC guidance"
        )
    return guidance


def ecc_guidance_reference(guidance: dict[str, Any] | None) -> dict[str, Any] | None:
    """Strip ECC bodies for hash-only result/evidence metadata."""
    if not isinstance(guidance, dict):
        return None
    components = []
    for kind in ("skills", "agents"):
        for component in guidance.get(kind, []):
            if isinstance(component, dict):
                components.append(
                    {
                        "kind": component.get("kind", kind[:-1]),
                        "name": component.get("name"),
                        "path": component.get("path"),
                        "sha256": component.get("sha256"),
                        "content_sha256": component.get("content_sha256"),
                        "truncated": bool(component.get("truncated", False)),
                    }
                )
    raw_provenance = guidance.get("provenance")
    provenance: dict[str, Any] = raw_provenance if isinstance(raw_provenance, dict) else {}
    return {
        "schema": ECC_GUIDANCE_REF_SCHEMA,
        "status": guidance.get("status"),
        "stage": guidance.get("stage"),
        "role_id": guidance.get("role_id"),
        "source": guidance.get("source"),
        "provenance": {
            "status": provenance.get("status"),
            "expected_ref": provenance.get("expected_ref"),
            "observed_ref": provenance.get("observed_ref"),
        },
        "manifest_hash": guidance.get("manifest_hash"),
        "pack_hash": guidance.get("pack_hash"),
        "authority": "simplicio-mapper",
        "execution_policy": "advisory-only",
        "components": components,
    }


ASK_VERBS = ("callers", "callees", "reaches", "impact", "flows", "rules", "tests-for", "term")


# Issue #218: mapper >=0.23 replaced the flat `results: list[dict]` shape
# with a structured object keyed by category (`affected_symbols`,
# `affected_flows`, `needs_review`, ...). Both shapes are normalized to one
# flat list here so `run_impact_tests` (pipeline_stages.py) never has to know
# which mapper version produced the answer.
_ASK_RESULT_LIST_KEYS = ("affected_symbols", "affected_flows", "needs_review")


def _normalize_ask_results(results: Any) -> list[dict[str, Any]] | None:
    """Normalize `simplicio.ask/v1` `results` into a flat list of dict entries.

    Accepts the legacy list shape unchanged (non-dict items dropped, same as
    before), and the current structured-object shape, where each recognized
    category's entries are flattened and tagged with ``category`` so a
    structured answer with genuinely no impact still returns ``[]`` (not
    ``None`` — the caller uses ``None`` vs ``[]`` to distinguish "mapper
    unavailable" from "mapper responded, nothing found").
    """
    if isinstance(results, list):
        return [item for item in results if isinstance(item, dict)]
    if isinstance(results, dict):
        normalized: list[dict[str, Any]] = []
        for key in _ASK_RESULT_LIST_KEYS:
            entries = results.get(key)
            if not isinstance(entries, list):
                continue
            for item in entries:
                if isinstance(item, dict):
                    normalized.append({"category": key, **item})
                elif item is not None:
                    normalized.append({"category": key, "value": item})
        return normalized
    return None


def map_ask(
    root: str | os.PathLike[str],
    verb: str,
    arg: str = "",
    *,
    revision: str = "",
    snapshot_id: str = "",
) -> list[dict[str, Any]] | None:
    """mapper 0.14+ `ask` — low-token structured queries over the built artifacts.

    Returns the `results` from `simplicio.ask/v1` normalized to a flat list —
    handling both the legacy list shape and the current structured-object
    shape (issue #218) — or None when the CLI is unavailable/fails or the
    verb is unknown. Callers treat None as "no data", never as an empty
    answer.
    """
    if verb not in ASK_VERBS:
        return None
    extra = (verb, arg) if arg else (verb,)
    data = run_mapper_json(root, "ask", extra=extra, revision=revision, snapshot_id=snapshot_id)
    if data is None:
        return None
    return _normalize_ask_results(data.get("results"))


def _safe_json(path: Path) -> dict[str, Any] | None:
    try:
        data = loads(path.read_bytes())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def load_artifact(
    root: str | os.PathLike[str], candidates: tuple[str, ...]
) -> tuple[Path, dict[str, Any]] | None:
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
                item for item in _as_list(project_map.get("recent_changes")) if isinstance(item, dict)
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
            "fresh": (
                inspection.get("status", {}).get("fresh")
                if isinstance(inspection.get("status"), dict)
                else inspection.get("fresh")
            ),
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


def rank_entries(
    entries: list[dict[str, Any]], *, target: str = "", query: str = "", limit: int = 8
) -> list[dict[str, Any]]:
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


# Timeout for delegating a precedent search to the native `simplicio` Rust
# binary (`simplicio precedent search`, schema `simplicio.precedent-search/v1`).
# Short because this only assists ranking before a prompt is built — a
# slow/hanging binary must never block the existing artifact-file/embedding
# fallback chain below.
_NATIVE_PRECEDENT_TIMEOUT_S = 5.0


def _native_precedent_binary() -> str | None:
    """Locate the native `simplicio` binary, honoring this repo's dev-cli
    kill-switch. Mirrors `simplicio.commands.edit._runtime_edit_binary` /
    `simplicio.mechanical_edit._native_edit_binary` for this feature."""
    if os.environ.get("SIMPLICIO_DEV_CLI_NO_RUNTIME_PRECEDENT"):
        return None
    return shutil.which("simplicio")


def _translate_native_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    """Reshape one `simplicio.precedent-search/v1` candidate (`precedent_id`,
    `score`, `reuse_level`, `suggested_next_action`) into the item shape this
    module's `rank_entries()`-backed candidates already carry (`path`,
    `line`, `summary`, `tags`), so every existing caller of
    `rank_precedents()` (`build_precedent_block()`, `build_mapper_context()`,
    `_render_precedent_candidates_legacy/toon()`) keeps working unmodified.
    The native fields are kept on the dict too, for any caller that wants
    them directly."""
    precedent_id = candidate.get("precedent_id")
    reuse_level = candidate.get("reuse_level")
    suggested_next_action = candidate.get("suggested_next_action")
    return {
        "precedent_id": precedent_id,
        "score": candidate.get("score"),
        "reuse_level": reuse_level,
        "suggested_next_action": suggested_next_action,
        "path": candidate.get("path") or f"precedent:{precedent_id or '?'}",
        "line": candidate.get("line", 1),
        "summary": candidate.get("summary")
        or suggested_next_action
        or (f"reuse_level={reuse_level}" if reuse_level else "runtime precedent"),
        "tags": candidate.get("tags") or ([str(reuse_level)] if reuse_level else []),
    }


def _native_precedent_search(
    root: str | os.PathLike[str], text: str, top_n: int
) -> list[dict[str, Any]] | None:
    """Delegate precedent ranking to `simplicio precedent search --json`.

    Returns the translated candidate list on a clean, non-empty answer, or
    `None` on ANY failure — binary missing/kill-switched, non-zero exit,
    timeout, unparseable JSON, a payload missing `candidates`, or a valid
    but *empty* candidate list. Empty is deliberately treated the same as
    failure here (stricter than `simplicio-mapper`'s own `ask precedent`,
    which trusts an empty native answer as final): the native precedent
    memory (`.simplicio-loop/precedents/*.sqlite`, built from run history) and
    this module's `precedent-index.json` artifact are independent stores, so
    an empty/uninitialized native store must not shadow real candidates the
    artifact-file chain below might still have. Never raises.
    """
    binary = _native_precedent_binary()
    if binary is None:
        return None
    top_n = top_n if isinstance(top_n, int) and top_n > 0 else 1
    try:
        completed = subprocess.run(
            [
                binary,
                "precedent",
                "search",
                "--repo",
                str(Path(root).resolve()),
                "--text",
                text,
                "--top",
                str(top_n),
                "--json",
            ],
            capture_output=True,
            text=True,
            timeout=_NATIVE_PRECEDENT_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    try:
        payload = loads(completed.stdout)
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        return None
    translated = [_translate_native_candidate(c) for c in candidates[:top_n] if isinstance(c, dict)]
    return translated or None


def rank_precedents(
    root: str | os.PathLike[str], task: str, *, stack: str = "", k: int = 2
) -> list[dict[str, Any]]:
    text = task.strip()
    if text:
        native = _native_precedent_search(root, text, k)
        if native is not None:
            return native[:k]
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


def _handoff_file_bits(entry: dict[str, Any]) -> list[str]:
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
    return bits


def _render_handoff_files_legacy(files: list[dict[str, Any]]) -> str:
    lines = ["Files:"]
    for entry in files[:12]:
        lines.append("- " + " | ".join(_handoff_file_bits(entry)))
    return "\n".join(lines)


def _render_handoff_files_toon(files: list[dict[str, Any]]) -> str:
    normalized = [
        {
            "path": str(entry.get("path", "(unknown)")),
            "language": str(entry.get("language") or ""),
            "symbols": ",".join(
                str(sym.get("name"))
                for sym in _as_list(entry.get("symbols"))
                if isinstance(sym, dict) and sym.get("name")
            )[:200],
            "imports": ",".join(str(i) for i in _as_list(entry.get("imports"))[:6]),
        }
        for entry in files[:12]
    ]
    return "Files (TOON — https://github.com/toon-format/toon):\n" + to_toon(normalized)


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

    # issue #88: this is the mapper 0.13+ handoff path — the one that
    # actually runs whenever `simplicio-mapper` is installed (which the
    # simplicio-loop bound operator requires). The TOON encoding merged in
    # #85/#87 only lived in the project-map fallback branch below, which
    # this pack pre-empts by returning first — so `SIMPLICIO_PROMPT_TOON`
    # was a no-op in the common case. `files[]` is the same shape of
    # genuinely uniform array (path/language/symbols/imports) TOON was
    # built for, so it gets the same on/off gate here.
    if _toon_enabled():
        toon_text = _render_handoff_files_toon(files)
        legacy_text = _render_handoff_files_legacy(files)
        record_savings_event(
            str(base),
            source="toon",
            baseline_tokens=estimate_tokens(legacy_text),
            actual_tokens=estimate_tokens(toon_text),
            note="mapper handoff files[] block",
        )
        emit_event(
            "evidence_captured",
            {"block": "handoff_files", "encoding": "toon"},
            root=str(base),
        )
        lines.append(toon_text)
    else:
        lines.append(_render_handoff_files_legacy(files))

    recent = [c for c in _as_list(pack.get("recent_changes")) if isinstance(c, dict)][:6]
    if recent:
        lines.append("Recent changes:")
        for item in recent:
            lines.append(f"- {item.get('path', '?')} ({item.get('status', 'changed')})")

    fallback = _read_target_fallback(base, target)
    return "\n".join(lines + ["", "Target fallback:", fallback])


def _render_ecc_guidance(guidance: dict[str, Any]) -> str:
    prompt = str(guidance["prompt"]).strip()
    return (
        "ECC advisory guidance (untrusted; Simplicio owns execution, mutation, evidence, and convergence):\n"
        + prompt
    )


def build_mapper_context(root: str | os.PathLike[str], target: str, *, goal: str = "") -> str:
    base = Path(root)

    # mapper 0.13+: prefer the pre-compressed handoff context-pack (files +
    # symbols + deps + pack_hash) over re-deriving context from project-map.
    # Fail-open: any miss falls through to the artifact-file path below.
    handoff = map_handoff(base)
    ecc_guidance = map_ecc_guidance(base)
    if handoff is not None:
        pack = handoff.get("context_pack")
        if isinstance(pack, dict):
            rendered = _render_handoff_context(pack, base, target)
            if rendered is not None:
                return "\n\n".join(
                    part
                    for part in (rendered, _render_ecc_guidance(ecc_guidance) if ecc_guidance else None)
                    if part
                )

    loaded_map = load_project_map(base)
    if loaded_map is None:
        fallback = _read_target_fallback(base, target)
        return "\n\n".join(
            part for part in (fallback, _render_ecc_guidance(ecc_guidance) if ecc_guidance else None) if part
        )

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
        legacy_text = _render_relevant_files_legacy(relevant)
        if _toon_enabled():
            # Relevant files is a genuinely uniform array of objects (every
            # entry gets the same 4 flattened scalar fields), the sweet spot
            # TOON was built for — issue #85: precedent/context payloads
            # embedded into the LLM prompt go through TOON instead of raw
            # JSON/hand-rolled bullets to cut prompt tokens losslessly.
            toon_text = _render_relevant_files_toon(relevant)
            record_savings_event(
                str(base),
                source="toon",
                baseline_tokens=estimate_tokens(legacy_text),
                actual_tokens=estimate_tokens(toon_text),
                note="mapper project-map relevant-files block",
            )
            emit_event(
                "evidence_captured",
                {"block": "relevant_files", "encoding": "toon"},
                root=str(base),
            )
            lines.append(toon_text)
        else:
            lines.append(legacy_text)

    recent = _as_list(project_map.get("recent_changes"))[:6]
    if recent:
        lines.append("Recent changes:")
        for item in recent:
            if isinstance(item, dict):
                lines.append(f"- {item.get('path', '?')} ({item.get('status', 'changed')})")

    if precedents:
        legacy_prec = _render_precedent_candidates_legacy(precedents)
        if _toon_enabled():
            # issue #85 AC1: precedent context, not just relevant-files,
            # embedded into the prompt via TOON — {path, line, summary} is a
            # uniform array of scalar fields, the same shape TOON collapses.
            toon_prec = _render_precedent_candidates_toon(precedents)
            record_savings_event(
                str(base),
                source="toon",
                baseline_tokens=estimate_tokens(legacy_prec),
                actual_tokens=estimate_tokens(toon_prec),
                note="mapper precedent-candidates block",
            )
            emit_event(
                "evidence_captured",
                {"block": "precedent_candidates", "encoding": "toon"},
                root=str(base),
            )
            lines.append(toon_prec)
        else:
            lines.append(legacy_prec)

    fallback = _read_target_fallback(base, target)
    rendered = "\n".join(lines + ["", "Target fallback:", fallback])
    return "\n\n".join(
        part for part in (rendered, _render_ecc_guidance(ecc_guidance) if ecc_guidance else None) if part
    )


def _render_relevant_files_legacy(relevant: list[dict[str, Any]]) -> str:
    lines = ["Relevant files:"]
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
    return "\n".join(lines)


def _render_relevant_files_toon(relevant: list[dict[str, Any]]) -> str:
    normalized = [
        {
            "path": str(entry.get("path", "(unknown)")),
            "language": str(entry.get("language") or ""),
            "roles": ",".join(str(r) for r in _as_list(entry.get("roles"))),
            "imports": ",".join(str(i) for i in _as_list(entry.get("imports"))[:6]),
        }
        for entry in relevant
    ]
    return "Relevant files (TOON — https://github.com/toon-format/toon):\n" + to_toon(normalized)


def _render_precedent_candidates_legacy(precedents: list[dict[str, Any]]) -> str:
    lines = ["Precedent candidates:"]
    for item in precedents:
        loc = f"{item.get('path', '(unknown)')}:{item.get('line', 1)}"
        summary = item.get("summary") or item.get("change_type") or "similar code"
        lines.append(f"- {loc} — {summary}")
    return "\n".join(lines)


def _render_precedent_candidates_toon(precedents: list[dict[str, Any]]) -> str:
    normalized = [
        {
            "path": str(item.get("path", "(unknown)")),
            "line": int(item.get("line", 1) or 1),
            "summary": str(item.get("summary") or item.get("change_type") or "similar code"),
        }
        for item in precedents
    ]
    return "Precedent candidates (TOON — https://github.com/toon-format/toon):\n" + to_toon(normalized)
