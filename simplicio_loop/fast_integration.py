"""Bounded Simplicio Fast v2 integration for Loop convergence (issue #748).

Fast owns ingest, bounded context and PlanDAG receipts. Loop owns the attempt and
candidate fence; Runtime may authorize effects, while Fast delegates source writes
to simplicio-dev-cli. Mapper remains the explicit fallback when Fast is unavailable.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .wave_worktree import ArtifactCache, default_branch_commit

SCHEMA = "simplicio.loop-fast-integration/v1"
PROBE_SCHEMA = "simplicio.fast.integration-status/v1"
RECEIPT_SCHEMA = "simplicio.loop-fast-receipt/v1"
APPLY_RECEIPT_SCHEMA = "simplicio.loop-fast-apply-receipt/v1"
FAST_INGEST_SCHEMA = "simplicio.fast.ingest/v2"
FAST_UNDERSTANDING_SCHEMA = "simplicio.fast.understanding/v2"
FAST_PLAN_SCHEMA = "simplicio.fast.plandag/v2"
FAST_CHANGESET_SCHEMA = "simplicio.fast.changeset/v2"
# v2.0.14 is the current Fast release validated for the Loop flow.  Keep the
# floor aligned with the release that contains the integrated-ready contract;
# accepting an arbitrary 2.x binary would silently re-enable older operators
# that predate the Loop ingest/understand/plan/apply flow.
FAST_MINIMUM = (2, 0, 14)
FAST_CAPABILITIES = ("ingest", "understand", "plan", "apply", "refresh")


class FastIntegrationError(RuntimeError):
    """Fast could not provide a valid bounded result."""


class FastUnavailable(FastIntegrationError):
    """Fast is unavailable and the configured fallback must be used."""


class FastStaleChangeset(FastIntegrationError):
    """A candidate does not match the pinned generation/context."""


class MapperHandoffUnavailable(FastIntegrationError):
    """Mapper could not produce the canonical handoff Fast requires to ingest."""


MAPPER_HANDOFF_SCHEMA = "simplicio.map-handoff/v1"
FAST_INGEST_HANDOFF_TOKEN_BUDGET = 2_000_000


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _version(value: str) -> tuple[int, int, int]:
    parts: list[int] = []
    for token in str(value).split(".")[:3]:
        digits = "".join(char for char in token if char.isdigit())
        parts.append(int(digits or 0))
    return tuple((parts + [0, 0, 0])[:3])


def _json_output(stdout: str) -> dict[str, Any]:
    text = (stdout or "").strip()
    if not text:
        raise FastIntegrationError("Fast returned no JSON")
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        lines = [line for line in text.splitlines() if line.strip()]
        for line in reversed(lines):
            try:
                value = json.loads(line)
                break
            except json.JSONDecodeError:
                continue
        else:
            raise FastIntegrationError("Fast returned invalid JSON")
    if not isinstance(value, dict):
        raise FastIntegrationError("Fast returned a non-object JSON payload")
    return value


def _relative(path: Path, root: Path) -> str:
    """Repo-relative path when possible; the absolute path otherwise.

    The shared survey cache (issue: shared survey cache) can live outside
    ``root`` for a linked worktree, so a plain ``relative_to`` would raise.
    """
    resolved = path.resolve()
    try:
        return resolved.relative_to(root.resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


_READ_ONLY_MARKERS = (
    "read-only",
    "read only",
    "sem editar",
    "inspect-only",
    "inspection only",
    "do not modify",
    "without editing",
)
_MUTATION_NODE_KINDS = {
    "structured_patch",
    "structured-patch",
    "source_edit",
    "source-edit",
}
_PATH_TOKEN = re.compile(
    r"(?<![\w.-])(?:[A-Za-z]:)?[\\/]?(?:[A-Za-z0-9_.-]+[\\/])+"
    r"[A-Za-z0-9_.-]*[\\/]?"
)
_BARE_CODE_TOKEN = re.compile(
    r"(?<![\w/\\])(?P<name>[A-Za-z0-9_-]+\.(?:py|tsx?|js|rs))(?![A-Za-z0-9_/\\-])"
)
_TECH_FILE_HINTS = frozenset({
    "node.js", "next.js", "vue.js", "react.js", "express.js", "deno.js",
    "bun.js", "alpine.js", "ember.js", "gatsby.js", "nuxt.js", "svelte.js",
    "backbone.js", "jquery.js",
})
_CODE_SUFFIXES = (".py", ".ts", ".tsx", ".js", ".rs")
INTENT_POLICY_SCHEMA = "simplicio.loop-fast-intent-policy/v1"
_CREATION_TYPES = frozenset({"creation", "create", "new", "criação", "criacao"})
_CREATION_TYPE_RE = re.compile(r"(?im)^\s*(?:type|tipo)\s*:\s*(?P<value>[^\r\n]+?)\s*$")
_DOCUMENTED_COMMAND_EXECUTABLES = frozenset({
    "bash", "cargo", "deno", "go", "java", "make", "node", "nodejs", "npm",
    "npx", "pnpm", "pytest", "python", "python3", "ruby", "sh", "yarn", "zsh",
})
_INLINE_CODE_RE = re.compile(r"`(?P<code>[^`\r\n]+)`")


def _read_only_intent(task: str) -> bool:
    normalized = " ".join(str(task).lower().split())
    return any(marker in normalized for marker in _READ_ONLY_MARKERS)


def _creation_intent(task: str) -> bool:
    """Mirror Markdown contract task types without inferring from prose verbs."""
    return any(
        match.group("value").strip().casefold() in _CREATION_TYPES
        for match in _CREATION_TYPE_RE.finditer(str(task))
    )


def _mask_documented_command_code(task: str) -> str:
    """Exclude command arguments from mutation-target harvesting."""
    def replace(match: re.Match[str]) -> str:
        tokens = match.group("code").strip().split()
        if len(tokens) < 2:
            return match.group(0)
        executable = tokens[0].rsplit("/", 1)[-1].casefold()
        if executable in _DOCUMENTED_COMMAND_EXECUTABLES:
            return " "
        return match.group(0)

    return _INLINE_CODE_RE.sub(replace, str(task))


def _creation_target_missing(
    root: Path,
    path: str,
    targets: Sequence[tuple[str, bool]],
    creation_intent: bool,
    pending_creation_targets: Sequence[str] = (),
) -> bool:
    if not creation_intent and path not in pending_creation_targets:
        return False
    return any(
        path == target
        and not is_dir
        and not (root / Path(target)).exists()
        and not (root / Path(target)).is_symlink()
        for target, is_dir in targets
    )


def _creation_support_exempt(
    root: Path,
    path: str,
    targets: Sequence[tuple[str, bool]],
    creation_intent: bool,
    pending_creation_targets: Sequence[str] = (),
) -> bool:
    pending_creation = any(
        target in pending_creation_targets
        and not is_dir
        and not (root / Path(target)).exists()
        and not (root / Path(target)).is_symlink()
        for target, is_dir in targets
    )
    return (creation_intent or pending_creation) and _existing_repo_file(root, path) and not any(
        _corridor_contains(path, target) for target in targets
    )


def _normalize_repo_path(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    raw = value.strip().replace("\\", "/")
    if not raw or raw.startswith("/") or re.match(r"^[A-Za-z]:/", raw):
        return None
    parts = [part for part in raw.split("/") if part not in {"", "."}]
    if not parts or any(part == ".." for part in parts):
        return None
    return "/".join(parts)


def _path_within_root(root: Path, relative: str) -> bool:
    try:
        (root / Path(relative)).resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return True


def _is_code_target(path: str) -> bool:
    return path.lower().endswith(_CODE_SUFFIXES)


def _existing_repo_file(root: Path, relative: str) -> bool:
    candidate = root / Path(relative)
    return candidate.is_file() and _path_within_root(root, relative)


def _bare_existing_targets(task: str, root: Path) -> list[str]:
    found: list[str] = []
    without_urls = re.sub(r"\b[A-Za-z][A-Za-z0-9+.-]*://\S+", "", str(task))
    for match in _BARE_CODE_TOKEN.finditer(without_urls):
        raw = match.group("name").strip()
        if raw.lower() in _TECH_FILE_HINTS:
            continue
        normalized = _normalize_repo_path(raw)
        if normalized is None or not _is_code_target(normalized):
            continue
        if _existing_repo_file(root, normalized) and normalized not in found:
            found.append(normalized)
    return found


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _pack_selected_targets(payload: Mapping[str, Any], root: Path) -> list[str]:
    found: list[str] = []

    def add(raw: Any) -> None:
        if not isinstance(raw, str):
            return
        normalized = _normalize_repo_path(raw.replace("\\", "/"))
        if (
            normalized
            and _is_code_target(normalized)
            and normalized.lower() not in _TECH_FILE_HINTS
            and _existing_repo_file(root, normalized)
            and normalized not in found
        ):
            found.append(normalized)

    add(payload.get("explicit_target_added"))
    add(payload.get("target"))
    for key in ("targets", "selected_targets"):
        values = payload.get(key)
        if isinstance(values, str):
            add(values)
        elif isinstance(values, Sequence) and not isinstance(values, (str, bytes)):
            for item in values:
                add(item if isinstance(item, str) else (item.get("path") if isinstance(item, Mapping) else None))

    files = payload.get("files")
    if isinstance(files, Sequence) and not isinstance(files, (str, bytes)):
        explicit_files: list[str] = []
        code_files: list[str] = []
        for item in files:
            path = ""
            reason = ""
            if isinstance(item, Mapping):
                path = str(item.get("path") or "")
                reason = str(item.get("selection_reason") or "")
            elif isinstance(item, str):
                path = item
            if reason == "explicit_task_target":
                explicit_files.append(path)
            if _is_code_target(path.replace("\\", "/")):
                code_files.append(path)
        for path in explicit_files:
            add(path)
        if not found and 1 <= len(code_files) <= 3:
            for path in code_files:
                add(path)
    return found


def _unwrap_context_pack(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    handoff = payload.get("handoff") if isinstance(payload.get("handoff"), Mapping) else {}
    stdout = handoff.get("stdout") if isinstance(handoff.get("stdout"), Mapping) else payload
    pack = stdout.get("context_pack") if isinstance(stdout, Mapping) and isinstance(stdout.get("context_pack"), Mapping) else payload
    return pack if isinstance(pack, Mapping) else payload


def mapper_selected_targets(root: Path) -> list[str]:
    """Read the newest Mapper handoff / run context for an existing code target."""
    found: list[str] = []
    simplicio = root / ".simplicio"
    if not simplicio.is_dir():
        return found

    def absorb(payload: Mapping[str, Any]) -> None:
        for path in _pack_selected_targets(_unwrap_context_pack(payload), root):
            if path not in found:
                found.append(path)
        for path in _pack_selected_targets(payload, root):
            if path not in found:
                found.append(path)

    objects = simplicio / "handoff-objects"
    if objects.is_dir():
        packs = sorted(
            objects.glob("context_pack-*.json"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        for pack_path in packs[:4]:
            absorb(_load_json_object(pack_path))
            if found:
                return found

    runs = simplicio / "loop-runs"
    if runs.is_dir():
        run_dirs = sorted(
            (item for item in runs.iterdir() if item.is_dir()),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        for run_dir in run_dirs[:4]:
            for name in ("mapper-context.json", "context-pack.json"):
                candidate = run_dir / name
                if candidate.is_file():
                    absorb(_load_json_object(candidate))
                    if found:
                        return found

    anchor = simplicio / "orchestrator" / "loop" / "anchor.json"
    if anchor.is_file():
        payload = _load_json_object(anchor)
        blob = " ".join(
            [
                str(payload.get("goal") or ""),
                *(str(item.get("text") or item.get("title") or "")
                  for item in (payload.get("criteria") or [])
                  if isinstance(item, Mapping)),
            ]
        )
        for path in _bare_existing_targets(blob, root):
            if path not in found:
                found.append(path)
    return found


def _explicit_targets(task: str, root: Path | None = None) -> tuple[list[tuple[str, bool]], list[str]]:
    targets: dict[str, bool] = {}
    invalid: list[str] = []
    without_urls = re.sub(
        r"\b[A-Za-z][A-Za-z0-9+.-]*://\S+",
        "",
        _mask_documented_command_code(task),
    )
    for match in _PATH_TOKEN.findall(without_urls):
        raw = match.strip("`'\".,;:()[]{}")
        is_dir = raw.endswith("/") or raw.endswith("\\")
        normalized = _normalize_repo_path(raw.rstrip("/\\"))
        if normalized is None:
            invalid.append(raw)
            continue
        targets[normalized] = targets.get(normalized, False) or is_dir
    if root is not None:
        for path in _bare_existing_targets(task, root):
            targets.setdefault(path, False)
    return sorted(targets.items()), sorted(set(invalid))


def _merge_targets(
    targets: dict[str, bool], extras: Sequence[str],
) -> dict[str, bool]:
    merged = dict(targets)
    for raw in extras:
        normalized = _normalize_repo_path(str(raw).replace("\\", "/"))
        if normalized:
            merged.setdefault(normalized, False)
    return merged


def _next_orient_command(root: Path, task: str, suggested: str) -> str:
    return (
        "simplicio-loop orient --repo "
        + str(root)
        + " --task "
        + json.dumps(task)
        + " --fast auto --target "
        + suggested
    )


def _context_paths(value: Any) -> list[str]:
    if isinstance(value, Mapping):
        found: list[str] = []
        for key in ("file", "path", "relative_path"):
            normalized = _normalize_repo_path(value.get(key))
            if normalized:
                found.append(normalized)
        return found
    if isinstance(value, str) and ("/" in value or "\\" in value):
        normalized = _normalize_repo_path(value)
        return [normalized] if normalized else []
    if isinstance(value, (list, tuple)):
        found: list[str] = []
        for item in value:
            found.extend(_context_paths(item))
        return found
    return []


def _corridor_contains(candidate: str, target: tuple[str, bool]) -> bool:
    path, is_dir = target
    return candidate == path or (
        is_dir and candidate.startswith(path.rstrip("/") + "/")
    )


def _is_mutation_node(node: Mapping[str, Any]) -> bool:
    kind = str(node.get("kind") or node.get("capability") or "").strip().lower()
    inputs = node.get("inputs") if isinstance(node.get("inputs"), Mapping) else {}
    return kind in _MUTATION_NODE_KINDS or inputs.get("format") == FAST_CHANGESET_SCHEMA


def _plan_hash(plan: Mapping[str, Any]) -> str:
    return _hash(
        {
            key: value
            for key, value in plan.items()
            if key not in {"plan_hash", "loop_receipt"}
        }
    )


def _blocker(reason: str, message: str, next_surface: str) -> dict[str, Any]:
    return {
        "code": reason,
        "reason": reason,
        "message": message,
        "next_surface": next_surface,
        "retryable": True,
    }


def _validate_plan_policy(
    root: Path,
    task: str,
    understanding: Mapping[str, Any],
    plan: Mapping[str, Any],
    extra_targets: Sequence[str] = (),
    pending_creation_targets: Sequence[str] = (),
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    read_only = _read_only_intent(task)
    creation_intent = _creation_intent(task)
    extracted, invalid_targets = _explicit_targets(task, root)
    selected = mapper_selected_targets(root)
    merged = _merge_targets({path: is_dir for path, is_dir in extracted}, extra_targets)
    # Paths written in the task or passed with --target are an authority corridor;
    # bare-word matches and Mapper's selection are guesses and never block alone.
    written_paths, _ = _explicit_targets(task, None)
    explicit = (bool(written_paths) or bool(_bare_existing_targets(task, root))
                or any(str(item).strip() for item in extra_targets))
    if not merged:
        merged = _merge_targets(merged, selected)
    targets = sorted(merged.items())
    target_names = [path + ("/" if is_dir else "") for path, is_dir in targets]
    policy = {
        "schema": INTENT_POLICY_SCHEMA,
        "intent_mode": "read_only" if read_only else "mutable",
        "mutable_authority": not read_only,
        "explicit_targets": target_names,
        "target_corridor": target_names,
        "corridor_source": "explicit" if explicit else "mapper_selected",
        "validated": False,
    }
    blockers: list[dict[str, Any]] = []
    nodes = [node for node in plan.get("nodes", []) if isinstance(node, Mapping)]
    mutation_nodes = [node for node in nodes if _is_mutation_node(node)]
    if plan.get("schema") != FAST_PLAN_SCHEMA:
        blockers.append(
            _blocker(
                "PLAN_SCHEMA_UNSUPPORTED",
                "versioned Fast PlanDAG schema is required",
                "fast-plan",
            )
        )
    if read_only and mutation_nodes:
        blockers.append(
            _blocker(
                "READ_ONLY_MUTATION_AUTHORITY",
                "read-only intent cannot produce mutation authority",
                "orient",
            )
        )
    if invalid_targets:
        blockers.append(
            _blocker(
                "TARGET_PATH_INVALID",
                "explicit targets must be repository-relative paths: "
                + ", ".join(invalid_targets),
                "target",
            )
        )

    allowed_files: list[str] = []
    invalid_allowed: list[str] = []
    for node in mutation_nodes:
        inputs = node.get("inputs") if isinstance(node.get("inputs"), Mapping) else {}
        raw_allowed = inputs.get("allowed_files")
        if not isinstance(raw_allowed, list) or not raw_allowed:
            blockers.append(
                _blocker(
                    "MUTATION_POLICY_MISSING",
                    "mutable PlanDAG nodes require a versioned changeset and non-empty allowed_files",
                    "plan-policy",
                )
            )
            continue
        if inputs.get("format") != FAST_CHANGESET_SCHEMA:
            blockers.append(
                _blocker(
                    "MUTATION_POLICY_MISSING",
                    "mutable PlanDAG nodes must declare simplicio.fast.changeset/v2",
                    "plan-policy",
                )
            )
        for item in raw_allowed:
            normalized = _normalize_repo_path(item)
            if normalized is None or not _path_within_root(root, normalized):
                invalid_allowed.append(str(item))
            else:
                allowed_files.append(normalized)
    allowed_files = sorted(set(allowed_files))
    policy["allowed_files"] = allowed_files
    if invalid_allowed:
        blockers.append(
            _blocker(
                "MUTATION_TARGET_INVALID",
                "mutable allowed_files must stay repository-relative: "
                + ", ".join(sorted(set(invalid_allowed))),
                "plan-policy",
            )
        )

    observed = sorted(
        set(
            _context_paths(understanding.get("context"))
            + _context_paths(understanding.get("files"))
        )
    )
    policy["context_path_count"] = len(observed)
    if targets and explicit:
        escaped = [path for path, _ in targets if not _path_within_root(root, path)]
        if escaped:
            blockers.append(
                _blocker(
                    "TARGET_PATH_INVALID",
                    "explicit targets resolve outside the orientation repository: "
                    + ", ".join(escaped),
                    "target",
                )
            )
        unresolved = []
        for path, is_dir in targets:
            if path in escaped:
                continue
            candidate = root / Path(path)
            if not (candidate.is_dir() if is_dir else candidate.is_file()):
                if _creation_target_missing(root, path, targets, creation_intent, pending_creation_targets):
                    continue
                unresolved.append(path + ("/" if is_dir else ""))
        if unresolved:
            suggested = next((path for path in (*extra_targets, *selected) if _existing_repo_file(root, path)), "")
            if not suggested:
                suggested = next(iter(_bare_existing_targets(task, root)), "plugin.js")
            blocker = _blocker(
                "TARGET_PATH_UNRESOLVED",
                "explicit target paths must resolve under the orientation repository: "
                + ", ".join(unresolved)
                + ". Use a repo-relative file that exists, e.g. --target "
                + suggested,
                "target",
            )
            blocker["next_command"] = _next_orient_command(root, task, suggested)
            blocker["accepted_target_form"] = "repo-relative existing file, e.g. plugin.js"
            blockers.append(blocker)
        if mutation_nodes and not allowed_files:
            blockers.append(
                _blocker(
                    "TARGET_CORRIDOR_MISSING",
                    "explicit targets must define the mutable target corridor",
                    "target",
                )
            )
        off_target = sorted(
            {
                path
                for path in allowed_files
                if not any(_corridor_contains(path, target) for target in targets)
                and not _creation_support_exempt(root, path, targets, creation_intent, pending_creation_targets)
            }
        )
        if off_target:
            blockers.append(
                _blocker(
                    "TARGET_CORRIDOR_MISMATCH",
                    "mutable allowed_files fall outside explicit targets: "
                    + ", ".join(off_target),
                    "target",
                )
            )
        if (
            mutation_nodes
            and not any(
                _corridor_contains(path, target)
                for path in observed
                for target in targets
            )
            and not any(
                _creation_target_missing(root, path, targets, creation_intent, pending_creation_targets)
                for path, _ in targets
            )
        ):
            blockers.append(
                _blocker(
                    "TARGET_RELEVANCE_INSUFFICIENT",
                    "Fast context contains no span in the explicit target corridor",
                    "fast-understand",
                )
            )
    elif mutation_nodes and not observed:
        blockers.append(
            _blocker(
                "CONTEXT_RELEVANCE_INSUFFICIENT",
                "mutable PlanDAG authority requires at least one bounded Fast context span",
                "fast-understand",
            )
        )

    unobserved_allowed = sorted(
        path
        for path in allowed_files
        if path not in observed
        and not _creation_target_missing(root, path, targets, creation_intent, pending_creation_targets)
        and not _creation_support_exempt(root, path, targets, creation_intent, pending_creation_targets)
    )
    if mutation_nodes and unobserved_allowed:
        reason = (
            "TARGET_RELEVANCE_INSUFFICIENT"
            if targets
            else "CONTEXT_RELEVANCE_INSUFFICIENT"
        )
        blockers.append(
            _blocker(
                reason,
                "mutable allowed_files lack bounded Fast context spans: "
                + ", ".join(unobserved_allowed),
                "fast-understand",
            )
        )

    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in blockers:
        if item["reason"] not in seen:
            seen.add(item["reason"])
            unique.append(item)
    policy["validated"] = not unique
    return policy, unique


def _redact_blocked_plan(
    plan: Mapping[str, Any],
    policy: Mapping[str, Any],
    blockers: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    nodes = [node for node in plan.get("nodes", []) if isinstance(node, Mapping)]
    redacted_ids = {
        str(node.get("id"))
        for node in nodes
        if _is_mutation_node(node) and node.get("id") is not None
    }
    changed = True
    while changed:
        changed = False
        for node in nodes:
            node_id = str(node.get("id")) if node.get("id") is not None else ""
            depends_on = node.get("depends_on")
            dependencies = depends_on if isinstance(depends_on, list) else []
            if node_id and node_id not in redacted_ids and any(
                str(dependency) in redacted_ids for dependency in dependencies
            ):
                redacted_ids.add(node_id)
                changed = True

    safe = dict(plan)
    safe.pop("loop_receipt", None)
    safe.pop("plan_hash", None)
    safe["nodes"] = [
        dict(node)
        for node in nodes
        if not _is_mutation_node(node)
        and str(node.get("id") or "") not in redacted_ids
    ]
    safe["status"] = "BLOCKED"
    safe["intent_policy"] = dict(policy)
    safe["blocked_preconditions"] = [dict(item) for item in blockers]
    safe["redacted_node_ids"] = sorted(redacted_ids)
    return safe


@dataclass(frozen=True)
class FastConfig:
    """Explicit, environment-configurable Fast policy."""

    mode: str = "auto"
    command: tuple[str, ...] = ("simplicio-fast",)
    mapper_command: tuple[str, ...] = ("simplicio-mapper",)
    snapshot: str = ".simplicio/fast/project.sfast"
    state: str = ".simplicio/fast/loop-ingest.json"
    max_bytes: int = 48_000
    timeout_seconds: int = 180
    require_binding: bool = True
    # Engine selection is independent from Loop's availability policy.  In
    # ``auto`` Fast itself performs Rust-first health/capability negotiation;
    # ``rust`` is fail-closed and ``python`` is an explicit compatibility path.
    engine: str = "auto"

    @classmethod
    def from_env(cls) -> "FastConfig":
        mode = os.environ.get("SIMPLICIO_FAST_MODE", "required").strip().lower()
        if mode not in {"auto", "required", "standalone"}:
            raise ValueError("SIMPLICIO_FAST_MODE must be auto, required, or standalone")
        engine = os.environ.get("SIMPLICIO_FAST_ENGINE", "auto").strip().lower()
        if engine not in {"auto", "rust", "python", "off"}:
            raise ValueError("SIMPLICIO_FAST_ENGINE must be auto, rust, python, or off")
        command = tuple(shlex.split(os.environ.get("SIMPLICIO_FAST_COMMAND", "simplicio-fast")))
        if not command:
            raise ValueError("SIMPLICIO_FAST_COMMAND must not be empty")
        return cls(
            mode=mode,
            engine=engine,
            command=command,
            snapshot=os.environ.get("SIMPLICIO_FAST_SNAPSHOT", cls.snapshot),
            state=os.environ.get("SIMPLICIO_FAST_STATE", cls.state),
            max_bytes=max(1, int(os.environ.get("SIMPLICIO_FAST_MAX_BYTES", str(cls.max_bytes)))),
            timeout_seconds=max(1, int(os.environ.get("SIMPLICIO_FAST_TIMEOUT", str(cls.timeout_seconds)))),
            require_binding=os.environ.get("SIMPLICIO_FAST_REQUIRE_BINDING", "1").strip().lower()
            not in {"0", "false", "no", "off"},
        )

    def digest(self) -> str:
        return _hash({"mode": self.mode, "engine": self.engine, "command": self.command,
                      "mapper_command": self.mapper_command, "snapshot": self.snapshot,
                      "max_bytes": self.max_bytes, "require_binding": self.require_binding})


@dataclass(frozen=True)
class FastProbe:
    version: str
    integrated_ready: bool
    fallback: bool
    reason: str | None
    command: tuple[str, ...]
    capabilities: tuple[str, ...] = FAST_CAPABILITIES
    requested_engine: str = "auto"
    selected_engine: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "schema": PROBE_SCHEMA,
            "name": "simplicio-fast",
            "command": list(self.command),
            "version": self.version,
            "minimum_version": ".".join(map(str, FAST_MINIMUM)),
            "required_capabilities": list(self.capabilities),
            "missing_capabilities": [],
            "integrated_ready": self.integrated_ready,
            "fallback": self.fallback,
            "status": "ready" if self.integrated_ready else "fallback",
            "reason": self.reason,
            "requested_engine": self.requested_engine,
            "selected_engine": self.selected_engine,
        }
        payload["receipt_hash"] = _hash(payload)
        return payload


def validate_changeset(changeset: Mapping[str, Any], *, generation: str = "",
                       context_hash: str = "", require_binding: bool = True) -> dict[str, Any]:
    """Validate the LLM candidate and bind it to the pinned Fast receipt."""
    if not isinstance(changeset, Mapping):
        raise FastIntegrationError("changeset must be an object")
    envelope = dict(changeset)
    raw = envelope.get("changeset") if isinstance(envelope.get("changeset"), Mapping) else envelope
    if raw.get("schema") != FAST_CHANGESET_SCHEMA:
        raise FastIntegrationError("unsupported changeset schema")
    if not isinstance(raw.get("changes"), list) or not raw["changes"]:
        raise FastIntegrationError("changeset must contain at least one change")
    metadata = envelope.get("fast_receipt") or envelope.get("receipt") or {}
    metadata = metadata if isinstance(metadata, Mapping) else {}
    candidate_generation = str(envelope.get("generation") or metadata.get("generation") or "")
    candidate_context = str(envelope.get("context_hash") or metadata.get("context_hash") or "")
    if require_binding and generation and candidate_generation != generation:
        raise FastStaleChangeset("changeset generation does not match the pinned generation")
    if require_binding and context_hash and candidate_context != context_hash:
        raise FastStaleChangeset("changeset context hash does not match the pinned context")
    if require_binding and generation and not candidate_generation:
        raise FastStaleChangeset("changeset is missing the pinned generation")
    if require_binding and context_hash and not candidate_context:
        raise FastStaleChangeset("changeset is missing the pinned context hash")
    return dict(raw)


class FastLoopIntegration:
    """One bounded ingest/context/plan/apply/refresh pipeline for a Loop attempt."""

    def __init__(self, root: str | Path, *, config: FastConfig | None = None,
                 runtime_apply: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
                 fallback_apply: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
                 runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
                 extra_targets: Sequence[str] = (),
                 pending_creation_targets: Sequence[str] = ()) -> None:
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise ValueError("Fast root must be a directory")
        self.config = config or FastConfig.from_env()
        self.runtime_apply = runtime_apply
        self.fallback_apply = fallback_apply
        self.extra_targets = tuple(str(item).strip() for item in extra_targets if str(item).strip())
        self.pending_creation_targets = tuple(
            normalized
            for item in pending_creation_targets
            if (normalized := _normalize_repo_path(str(item).replace("\\", "/")))
        )
        self._runner = runner or subprocess.run
        self._probe_cache: FastProbe | None = None
        self._ingest_receipt: dict[str, Any] | None = None
        self._generation = ""
        self._context_hash = ""
        # Set by a successful ingest(): the shared survey cache directory
        # (issue: shared survey cache) that this attempt's snapshot/handoff
        # actually live in, which may be outside ``root`` for a linked
        # worktree. None until ingest() runs at least once.
        self._active_snapshot_path: Path | None = None
        self._active_handoff_path: Path | None = None

    def _runner_env(self) -> dict[str, str]:
        env = dict(os.environ)
        if self.config.engine != "auto":
            env["SIMPLICIO_FAST_ENGINE"] = self.config.engine
        return env

    @property
    def generation(self) -> str:
        return self._generation

    @property
    def context_hash(self) -> str:
        return self._context_hash

    @property
    def snapshot_path(self) -> Path:
        if self._active_snapshot_path is not None:
            return self._active_snapshot_path
        return (self.root / self.config.snapshot).resolve()

    def _state_path(self) -> Path:
        return (self.root / self.config.state).resolve()

    def _git_common_dir(self) -> Path:
        """The main repo's shared ``.git`` dir, even from a linked worktree.

        ``git rev-parse --git-common-dir`` returns the one common git
        directory every worktree of a repository shares; its parent is the
        repository root that owns the shared ``.simplicio/`` survey cache
        (issue: shared survey cache). Falls back to this root's own
        ``.git`` when git is unavailable or this is not a repository.
        """
        try:
            completed = subprocess.run(
                ["git", "rev-parse", "--git-common-dir"], cwd=str(self.root),
                capture_output=True, text=True, timeout=10, check=False,
            )
            if completed.returncode == 0:
                value = (completed.stdout or "").strip()
                if value:
                    candidate = Path(value)
                    if not candidate.is_absolute():
                        candidate = self.root / candidate
                    return candidate.resolve()
        except (OSError, subprocess.SubprocessError):
            pass
        return (self.root / ".git").resolve()

    def _shared_cache_root(self) -> Path:
        """Survey-cache root shared by every worktree of this repository."""
        return self._git_common_dir().parent / ".simplicio" / "fast" / "survey-cache"

    def _survey_key(self) -> str:
        """Cache key: the default branch's commit + this worktree's own diff.

        Keying on the default-branch commit (rather than this worktree's
        HEAD) is what lets every linked worktree share one build; keying on
        ``_worktree_digest`` (uncommitted changes + untracked file content)
        is what still invalidates it the moment a file is edited locally.
        """
        return _hash({
            "branch_commit": default_branch_commit(self.root),
            "worktree": self._worktree_digest(),
            "config": self.config.digest(),
        })

    def _run(self, args: Sequence[str]) -> dict[str, Any]:
        command = [*self.config.command, *args]
        try:
            result = self._runner(
                command, cwd=str(self.root), capture_output=True, text=True,
                timeout=self.config.timeout_seconds, check=False, env=self._runner_env(),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise FastUnavailable(str(exc)) from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "Fast command failed").strip()
            raise FastIntegrationError(f"Fast command failed ({result.returncode}): {detail}")
        return _json_output(result.stdout)

    def probe(self, *, force: bool = False) -> dict[str, Any]:
        if self._probe_cache is not None and not force:
            return self._probe_cache.to_dict()
        if self.config.mode == "standalone":
            probe = FastProbe("0.0.0", False, True, "disabled_by_configuration", self.config.command,
                              requested_engine=self.config.engine)
            self._probe_cache = probe
            return probe.to_dict()
        if self.config.engine == "off":
            probe = FastProbe("0.0.0", False, True, "disabled_by_engine", self.config.command,
                              requested_engine="off")
            self._probe_cache = probe
            return probe.to_dict()
        try:
            version_result = self._run(["--version"])
            version_text = str(version_result.get("version") or version_result.get("fast_version") or "")
        except FastIntegrationError:
            try:
                completed = self._runner(
                    [*self.config.command, "--version"], cwd=str(self.root), capture_output=True,
                    text=True, timeout=self.config.timeout_seconds, check=False, env=self._runner_env(),
                )
                if completed.returncode != 0:
                    raise FastUnavailable((completed.stderr or "command unavailable").strip())
                version_text = (completed.stdout or completed.stderr or "").strip().split()[-1]
            except (OSError, subprocess.SubprocessError, FastUnavailable) as exc:
                probe = FastProbe("0.0.0", False, True, "missing_operator", self.config.command,
                                  requested_engine=self.config.engine)
                self._probe_cache = probe
                if self.config.mode == "required":
                    raise FastUnavailable(str(exc)) from exc
                return probe.to_dict()
        try:
            completed = self._runner(
                [*self.config.command, "doctor", "--json"], cwd=str(self.root), capture_output=True,
                text=True, timeout=self.config.timeout_seconds, check=False, env=self._runner_env(),
            )
            doctor = _json_output(completed.stdout or completed.stderr)
            integration = doctor.get("integration") if isinstance(doctor.get("integration"), Mapping) else {}
            integrated = bool(doctor.get("integrated_ready") or integration.get("integrated_ready"))
            ready = integrated and _version(version_text) >= FAST_MINIMUM
            reason = None if ready else "incompatible_operator"
            selected_engine = str(
                doctor.get("selected_engine") or doctor.get("engine")
                or integration.get("selected_engine") or ""
            ).strip().lower() or None
            if self.config.engine == "rust" and selected_engine not in {"rust"}:
                ready, reason = False, "rust_not_verified"
            elif self.config.engine == "python" and selected_engine not in {None, "python"}:
                ready, reason = False, "python_not_selected"
        except (OSError, subprocess.SubprocessError, FastIntegrationError):
            ready, reason, selected_engine = False, "doctor_failed", None
        if self.config.engine == "auto" and selected_engine is None and ready:
            selected_engine = "rust" if bool(doctor.get("rust_ready")) else "python"
        if self.config.engine == "python" and selected_engine is None and ready:
            selected_engine = "python"
        probe = FastProbe(version_text or "0.0.0", ready, not ready, reason, self.config.command,
                          requested_engine=self.config.engine, selected_engine=selected_engine)
        self._probe_cache = probe
        if not ready and self.config.mode == "required":
            raise FastUnavailable(reason or "Fast is not integrated-ready")
        return probe.to_dict()

    def _fallback(self, stage: str, reason: str) -> dict[str, Any]:
        probe = self.probe()
        payload = {
            "schema": RECEIPT_SCHEMA,
            "status": "FALLBACK",
            "stage": stage,
            "fallback": True,
            "fallback_mode": "mapper-dev-cli",
            "reason": reason,
            "probe": probe,
            "generation": self._generation or None,
            "context_hash": self._context_hash or None,
            "requested_engine": self.config.engine,
            "selected_engine": probe.get("selected_engine"),
        }
        payload["receipt_hash"] = _hash(payload)
        return payload

    def _source_commit(self) -> str:
        try:
            completed = self._runner(["git", "rev-parse", "HEAD"], cwd=str(self.root), capture_output=True,
                                    text=True, timeout=15, check=False)
            return (completed.stdout or "").strip() if completed.returncode == 0 else ""
        except (OSError, subprocess.SubprocessError):
            return ""

    def _worktree_digest(self) -> str:
        """Uncommitted content: a snapshot of HEAD is stale once a file is edited."""
        parts = []
        for argv in (["git", "diff", "HEAD", "--no-ext-diff"],
                     ["git", "ls-files", "--others", "--exclude-standard"]):
            try:
                completed = self._runner(argv, cwd=str(self.root), capture_output=True,
                                         text=True, timeout=30, check=False)
                parts.append(completed.stdout or "")
            except (OSError, subprocess.SubprocessError):
                parts.append("")
        # Untracked files are listed by name only; hash their bytes too.
        for name in parts[-1].splitlines():
            try:
                parts.append(hashlib.sha256((self.root / name).read_bytes()).hexdigest())
            except OSError:
                parts.append("")
        return _hash(parts)

    def _mapper_call(self, verb: str, *extra: str) -> Mapping[str, Any]:
        """Run one public Mapper verb with ``--json`` and return its JSON object."""
        try:
            result = self._runner(
                [*self.config.mapper_command, verb, str(self.root), "--json", *extra],
                cwd=str(self.root), capture_output=True, text=True,
                timeout=self.config.timeout_seconds, check=False, env=self._runner_env(),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise MapperHandoffUnavailable(f"mapper_handoff_unavailable: {exc}") from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or f"Mapper {verb} failed").strip()[:400]
            raise MapperHandoffUnavailable(f"mapper_handoff_unavailable: {detail}")
        try:
            payload = json.loads((result.stdout or "").strip())
        except json.JSONDecodeError as exc:
            raise MapperHandoffUnavailable(f"mapper_handoff_invalid_json: {exc}") from exc
        if not isinstance(payload, Mapping):
            raise MapperHandoffUnavailable("mapper_handoff_schema_unsupported")
        return payload

    def _mapper_handoff(self, dest_dir: Path | None = None) -> Path:
        """Obtain the canonical Mapper -> Fast handoff Fast requires to ingest.

        Fast's default ``--mapper-mode integrated`` fails closed
        (``mapper_missing``) without an explicit Mapper handoff file (issue
        #1288). Loop is the caller, so it asks the ``simplicio-mapper handoff``
        public verb for the bounded ``simplicio.map-handoff/v1`` envelope and
        pins it to a file Fast can read, instead of silently never passing one.
        """
        # Fast indexes the whole repository, so this handoff is never task-scoped
        # (a --goal pack prunes symbol nodes and Fast fails mapper_id_missing).
        # It goes to a file for Fast, not to the LLM, so the budget is only a cap.
        handoff_args = ("--token-budget", str(FAST_INGEST_HANDOFF_TOKEN_BUDGET))
        envelope = self._mapper_call("handoff", *handoff_args)
        status = envelope.get("status") if isinstance(envelope.get("status"), Mapping) else {}
        if envelope.get("ready") is not True or status.get("fresh") is False:
            # Stale or never-built map: refresh it once (scan --sync blocks on the
            # deep pass), then ask again. Same order the skill documents.
            self._mapper_call("scan", "--sync")
            envelope = self._mapper_call("handoff", *handoff_args)
        if envelope.get("schema") != MAPPER_HANDOFF_SCHEMA:
            raise MapperHandoffUnavailable("mapper_handoff_schema_unsupported")
        if envelope.get("ready") is not True:
            raise MapperHandoffUnavailable(
                f"mapper_handoff_not_ready: {envelope.get('reason') or 'unknown'}"
            )
        handoff_dir = dest_dir if dest_dir is not None else self._state_path().parent
        handoff_dir.mkdir(parents=True, exist_ok=True)
        handoff_path = handoff_dir / "mapper-handoff.json"
        handoff_path.write_text(json.dumps(envelope, ensure_ascii=False), encoding="utf-8")
        return handoff_path

    def _mapper_args(self, *, refresh: bool = False) -> list[str]:
        """Integrated-mode flags every Mapper-backed Fast command requires.

        ingest/refresh rebuild the handoff (the tree may have changed);
        understand/plan reuse the one this attempt's ingest() already pinned
        (the shared cache's handoff when ingest() ran, else the per-root one).
        """
        if not refresh and self._active_handoff_path is not None and self._active_handoff_path.is_file():
            return ["--mapper-mode", "integrated", "--mapper-handoff", str(self._active_handoff_path)]
        dest_dir = self._active_handoff_path.parent if self._active_handoff_path is not None else None
        path = dest_dir / "mapper-handoff.json" if dest_dir is not None else self._state_path().parent / "mapper-handoff.json"
        if refresh or not path.is_file():
            path = self._mapper_handoff(dest_dir)
        return ["--mapper-mode", "integrated", "--mapper-handoff", str(path)]

    def ingest(self) -> dict[str, Any]:
        """Ingest once per (default-branch commit, worktree diff), shared repo-wide.

        The Mapper handoff + Fast ingest survey is expensive and identical
        for every worktree sitting on the same default-branch commit with
        no local edits, so it is cached under the shared ``.simplicio/``
        (issue: shared survey cache) instead of once per worktree: a second
        ``orient``/``prepare`` on an unchanged tree -- in this worktree or
        any other linked one -- reuses the build and spawns neither
        ``simplicio-mapper scan``/``handoff`` nor ``simplicio-fast ingest``.
        """
        probe = self.probe()
        if not probe["integrated_ready"]:
            return self._fallback("ingest", str(probe.get("reason") or "Fast unavailable"))
        key = self._survey_key()
        cache = ArtifactCache(self._shared_cache_root())

        def build(key_dir: Path) -> None:
            handoff_path = self._mapper_handoff(key_dir)
            self._active_handoff_path = handoff_path
            snapshot_path = key_dir / "project.sfast"
            payload = self._run([
                "ingest", str(self.root), "--output", str(snapshot_path),
                "--mapper-mode", "integrated", "--mapper-handoff", str(handoff_path), "--json",
            ])
            metrics = payload.get("metrics") if isinstance(payload.get("metrics"), Mapping) else {}
            generation = str(payload.get("generation") or metrics.get("generation") or _hash(payload))
            receipt = {
                "schema": RECEIPT_SCHEMA,
                "status": "MEASURED",
                "stage": "ingest",
                "fallback": False,
                "cache_key": key,
                "snapshot": _relative(snapshot_path, self.root),
                "source_commit": self._source_commit(),
                "generation": generation,
                "fast_receipt": payload,
                "config_hash": self.config.digest(),
                "requested_engine": self.config.engine,
                "selected_engine": probe.get("selected_engine"),
            }
            receipt["receipt_hash"] = _hash(receipt)
            (key_dir / "receipt.json").write_text(
                json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
            )

        try:
            key_dir, _cache_hit = cache.get_or_build(key, build)
        except FastIntegrationError as exc:
            if self.config.mode == "required":
                raise
            return self._fallback("ingest", str(exc))
        try:
            receipt = json.loads((key_dir / "receipt.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            if self.config.mode == "required":
                raise FastIntegrationError(f"survey cache receipt unreadable: {exc}") from exc
            return self._fallback("ingest", f"survey_cache_receipt_unreadable: {exc}")
        self._generation = str(receipt.get("generation") or "")
        self._ingest_receipt = receipt
        self._active_snapshot_path = key_dir / "project.sfast"
        self._active_handoff_path = key_dir / "mapper-handoff.json"
        return dict(receipt)

    def understand(self, task: str) -> dict[str, Any]:
        if not isinstance(task, str) or not task.strip():
            raise ValueError("Fast task must be non-empty")
        ingest = self.ingest()
        if ingest.get("fallback"):
            return self._fallback("understand", str(ingest.get("reason") or "Fast unavailable"))
        payload = self._run(["understand", task, "--root", str(self.root), "--snapshot", str(self.snapshot_path),
                             "--max-bytes", str(self.config.max_bytes), *self._mapper_args()])
        context = payload.get("context") if isinstance(payload.get("context"), list) else []
        self._context_hash = _hash({"generation": self._generation, "context": context})
        result = dict(payload)
        result["loop_receipt"] = {
            "schema": RECEIPT_SCHEMA, "status": "MEASURED", "stage": "understand",
            "fallback": False, "generation": self._generation, "context_hash": self._context_hash,
            "context_count": len(context), "context_sha256": _hash(context),
        }
        result["loop_receipt"]["receipt_hash"] = _hash(result["loop_receipt"])
        return result

    def plan(self, task: str) -> dict[str, Any]:
        understanding = self.understand(task)
        if understanding.get("fallback"):
            return understanding
        payload = self._run(["plan", task, "--root", str(self.root), "--snapshot", str(self.snapshot_path),
                             "--max-bytes", str(self.config.max_bytes), *self._mapper_args()])
        if payload.get("schema") != FAST_PLAN_SCHEMA:
            raise FastIntegrationError("Fast plan schema is not v2")
        policy, blockers = _validate_plan_policy(
            self.root, task, understanding, payload, extra_targets=self.extra_targets,
            pending_creation_targets=self.pending_creation_targets,
        )
        if blockers:
            payload = _redact_blocked_plan(payload, policy, blockers)
        result = dict(payload)
        result["intent_policy"] = policy
        result["plan_hash"] = _plan_hash(result)
        result["loop_receipt"] = {
            "schema": RECEIPT_SCHEMA,
            "status": "BLOCKED" if blockers else "MEASURED",
            "stage": "plan",
            "fallback": False,
            "generation": self._generation,
            "context_hash": self._context_hash,
            "plan_hash": result["plan_hash"],
            "intent_policy_hash": _hash(policy),
            "understanding_receipt_hash": understanding.get("loop_receipt", {}).get(
                "receipt_hash", ""
            ),
        }
        result["loop_receipt"]["receipt_hash"] = _hash(result["loop_receipt"])
        return result

    def prepare(self, task: str) -> dict[str, Any]:
        """Run ingest -> understand -> plan once and return bounded agent context."""
        ingest = self.ingest()
        if ingest.get("fallback"):
            return {
                "schema": SCHEMA,
                "status": "FALLBACK",
                "ingest": ingest,
                "understanding": self._fallback(
                    "understand", str(ingest.get("reason") or "Fast unavailable")
                ),
            }
        understanding = self.understand(task)
        if understanding.get("fallback"):
            return {
                "schema": SCHEMA,
                "status": "FALLBACK",
                "ingest": ingest,
                "understanding": understanding,
            }
        plan = self.plan(task)
        blockers = list(plan.get("blocked_preconditions") or [])
        status = "BLOCKED" if plan.get("status") == "BLOCKED" else "READY"
        result = {
            "schema": SCHEMA,
            "status": status,
            "ingest": ingest,
            "understanding": understanding,
            "plan": plan,
            "intent_policy": plan.get("intent_policy"),
            "generation": self._generation,
            "context_hash": self._context_hash,
            "plan_hash": plan["plan_hash"],
        }
        if blockers:
            result["blocked_preconditions"] = blockers
            result["reason"] = blockers[0].get("reason") or "plan_policy_blocked"
        result["loop_receipt"] = {
            "schema": RECEIPT_SCHEMA,
            "status": "BLOCKED" if blockers else "MEASURED",
            "stage": "prepare",
            "fallback": False,
            "generation": self._generation,
            "context_hash": self._context_hash,
            "plan_hash": plan["plan_hash"],
            "task_hash": _hash({"task": task}),
            "intent_policy_hash": _hash(plan.get("intent_policy") or {}),
            "ingest_receipt_hash": ingest.get("receipt_hash", ""),
            "understanding_receipt_hash": understanding.get("loop_receipt", {}).get(
                "receipt_hash", ""
            ),
            "plan_receipt_hash": plan.get("loop_receipt", {}).get("receipt_hash", ""),
        }
        result["loop_receipt"]["receipt_hash"] = _hash(result["loop_receipt"])
        return result

    def apply(self, changeset: Mapping[str, Any], *, winner: bool = True,
              generation: str | None = None, context_hash: str | None = None) -> dict[str, Any]:
        if not winner:
            payload = {"schema": APPLY_RECEIPT_SCHEMA, "status": "SKIPPED", "fallback": False,
                       "reason": "speculative_candidate_not_winner", "applied": False}
            payload["receipt_hash"] = _hash(payload)
            return payload
        generation = generation or self._generation
        context_hash = context_hash or self._context_hash
        probe = self.probe()
        if not probe["integrated_ready"]:
            if self.fallback_apply is None:
                return self._fallback("apply", str(probe.get("reason") or "Fast unavailable"))
            result = dict(self.fallback_apply(changeset))
            payload = {"schema": APPLY_RECEIPT_SCHEMA, "status": "FALLBACK", "fallback": True,
                       "fallback_mode": "mapper-dev-cli", "applied": bool(result.get("applied")),
                       "dev_cli": result, "generation": generation or None, "context_hash": context_hash or None}
            payload["receipt_hash"] = _hash(payload)
            return payload
        raw = validate_changeset(changeset, generation=generation, context_hash=context_hash,
                                 require_binding=self.config.require_binding)
        runtime_receipt: Mapping[str, Any]
        operation = {"schema": SCHEMA, "kind": "apply", "generation": generation,
                     "context_hash": context_hash, "changeset": raw}
        if self.runtime_apply is None:
            runtime_receipt = {"status": "UNAVAILABLE", "reason": "runtime_not_bound"}
        else:
            try:
                runtime_receipt = dict(self.runtime_apply(operation))
            except Exception as exc:
                runtime_receipt = {"status": "BLOCKED", "reason": str(exc)}
        if str(runtime_receipt.get("status")) in {"BLOCKED", "UNAVAILABLE", "UNCERTAIN"}:
            payload = {"schema": APPLY_RECEIPT_SCHEMA, "status": "BLOCKED", "fallback": False,
                       "applied": False, "runtime": runtime_receipt, "generation": generation,
                       "context_hash": context_hash}
            payload["receipt_hash"] = _hash(payload)
            return payload
        temp_path: Path | None = None
        try:
            self.snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".changeset.json", delete=False,
                                             dir=str(self.snapshot_path.parent)) as handle:
                json.dump(raw, handle, ensure_ascii=False, sort_keys=True)
                handle.write("\n")
                temp_path = Path(handle.name)
            fast_receipt = self._run(["apply", str(temp_path), "--root", str(self.root), "--write"])
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
        payload = {"schema": APPLY_RECEIPT_SCHEMA, "status": "READY", "fallback": False,
                   "applied": True, "runtime": dict(runtime_receipt), "fast": fast_receipt,
                   "generation": generation, "context_hash": context_hash}
        payload["receipt_hash"] = _hash(payload)
        return payload

    def refresh(self) -> dict[str, Any]:
        probe = self.probe()
        if not probe["integrated_ready"]:
            return self._fallback("refresh", str(probe.get("reason") or "Fast unavailable"))
        try:
            payload = self._run(["refresh", str(self.root), "--output", str(self.snapshot_path),
                                 *self._mapper_args(refresh=True), "--json"])
        except MapperHandoffUnavailable as exc:
            if self.config.mode == "required":
                raise
            return self._fallback("refresh", str(exc))
        metrics = payload.get("metrics") if isinstance(payload.get("metrics"), Mapping) else {}
        self._generation = str(payload.get("generation") or metrics.get("generation") or _hash(payload))
        self._ingest_receipt = None
        receipt = {"schema": RECEIPT_SCHEMA, "status": "MEASURED", "stage": "refresh",
                   "fallback": False, "generation": self._generation, "fast_receipt": payload,
                   "no_full_remap": True}
        receipt["receipt_hash"] = _hash(receipt)
        return receipt

    def rollout(self, mode: str, *, generation: str | None = None,
                reason: str | None = None, state: str | Path | None = None) -> dict[str, Any]:
        """Persist an atomic Fast rollout transition for this Loop root."""
        if mode not in {"shadow", "canary", "integrated", "fallback", "rollback"}:
            raise ValueError("unsupported Fast rollout mode")
        state_path = Path(state) if state is not None else self.root / ".simplicio/fast" / "rollout.json"
        command = ["rollout", mode, "--state", str(state_path)]
        if generation:
            command.extend(["--generation", str(generation)])
        if reason:
            command.extend(["--reason", str(reason)])
        try:
            return self._run(command)
        except FastIntegrationError:
            if self.config.mode == "required":
                raise
            raise


__all__ = ["APPLY_RECEIPT_SCHEMA", "FAST_CHANGESET_SCHEMA", "FAST_PLAN_SCHEMA", "FastConfig",
           "FastIntegrationError", "FastLoopIntegration", "FastProbe", "FastStaleChangeset",
           "FastUnavailable", "SCHEMA", "mapper_selected_targets", "validate_changeset"]
