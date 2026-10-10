"""Shared primitives of the arm/run state machine: schemas, constants, JSON/command helpers, repo fingerprint, task spec and task dependencies. Leaf module: imports nothing from the other ``runner_*`` modules (#1606)."""
from __future__ import annotations

import json
import hashlib
import os
import random
import re
import shutil
import subprocess
import time
import string
import sys
from pathlib import Path
from typing import (
    Any,
    Collection,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Sequence,
    Set,
    Tuple,
)
from .merge_executor import MergeExecutor, MergeExecutorError
from .authority_boundary import prepare_authorization_handoff
from .store_adapter import StorageRoute, StoreAdapterError, verify_route_receipt
from .stack_lock import StackLock, discover_installed_components, load_stack_lock
from .execution_route import verify_route_hash
try:
    from scripts.agent_identity import ensure_identity
except ImportError:  # pragma: no cover - installed package without scripts namespace
    ensure_identity = None

_PROVIDER_SECRET_ENV = (
    "OPENROUTER_API_KEY", "OPENROUTER_BASE_URL", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
)


def _subprocess_env(base: Optional[Mapping[str, str]] = None) -> Dict[str, str]:
    """Build a diagnostic/operator environment without provider credentials."""
    env = dict(base or os.environ)
    for key in _PROVIDER_SECRET_ENV:
        env.pop(key, None)
    return env
OPERATOR_RECEIPT_SCHEMA = "simplicio.operator-receipt/v0"
MAX_PROVIDER_CURRENT_TARGET_CHARS = 30000
HOST_EDIT_PLAN_SCHEMAS = frozenset({
    "simplicio.dev-cli.edit-plan/v1",
    "simplicio.mechanical-edit/v1",
})
PLAN_REQUIRED = "plan_required"
# #NOWASTE: reason_codes that identify a deterministic operator failure -- retrying
# the exact same task/plan/repo-state cannot change the outcome, so the per-task
# retry loop records it once (dead-letter) instead of burning the whole retry
# budget on a guaranteed repeat. Everything else (subprocess timeout, OSError/lock
# contention, lease lost) is transient and keeps retrying as before.
DETERMINISTIC_OPERATOR_REASON_CODES = frozenset({
    PLAN_REQUIRED,
    "plan_compile_failed",
    "plan_repo_state_stale",
    "plan_validation_failed",
    "plan_path_not_found",
    "plan_path_not_authorized",
    "plan_path_unsafe",
    "plan_find_not_found",
    "plan_find_not_unique",
    "devcli_capabilities_unavailable",
    "operator_capabilities_missing",
    "operator_batch_preflight_failed",
    "find_target_not_unique",
    "find_target_not_found",
})


class BatchPreflightError(RuntimeError):
    """A batch-wide preflight receipt-chain check failed (e.g. "operator receipt
    does not match the mapper receipt"). This exact repeat will fail the exact
    same way every time -- a caller that retries it on a fixed cadence is
    wasting the retry budget on a guaranteed repeat (see #NOWASTE)."""

    def __init__(self, message: str, *, reason_code: str = "operator_batch_preflight_failed") -> None:
        super().__init__(message)
        self.reason_code = reason_code
# Text markers scanned in a failed dev-cli receipt's stdout/stderr when no discrete
# reason_code was persisted (the apply subprocess itself rejected the edit plan's
# find/replace, not the loop's own preflight gates above it).
_DEVCLI_DETERMINISTIC_STDOUT_MARKERS: Tuple[Tuple[str, str], ...] = (
    ("not unique", "find_target_not_unique"),
    ("ambiguous", "find_target_not_unique"),
    ("multiple matches", "find_target_not_unique"),
    ("no match", "find_target_not_found"),
    ("no such find", "find_target_not_found"),
    ("not found", "find_target_not_found"),
)


def _classify_devcli_receipt_failure(payload: Mapping[str, Any]) -> str:
    """Derive a deterministic reason_code from a failed operator receipt.

    Prefers an explicit ``reason_code`` already on the receipt; falls back to
    scanning stdout/stderr text for the dev-cli apply subprocess's own
    find/replace rejection wording.
    """
    reason_code = str(payload.get("reason_code") or "")
    if reason_code:
        return reason_code
    parts = [str(payload.get("stderr") or "")]
    stdout = payload.get("stdout")
    if isinstance(stdout, Mapping):
        parts.append(json.dumps(stdout, ensure_ascii=False))
    elif stdout:
        parts.append(str(stdout))
    blob = " ".join(parts).lower()
    for marker, code in _DEVCLI_DETERMINISTIC_STDOUT_MARKERS:
        if marker in blob:
            return code
    return ""


def _classify_operator_exception_reason_code(exc: BaseException) -> str:
    """Map a raised operator/preflight exception to a typed reason_code.

    Keeps the deterministic-vs-transient split correct even when the failure
    surfaces as a Python exception (plan validation, stale repo state, missing
    capabilities) rather than a receipt the dev-cli subprocess wrote itself.
    """
    reason_code = getattr(exc, "reason_code", "")
    if reason_code:
        return str(reason_code)
    message = str(exc).lower()
    if "repository changed after planning" in message:
        return "plan_repo_state_stale"
    if "plan validation failed" in message:
        return "plan_validation_failed"
    if (
        "missing required capabilities" in message
        or "below minimum version" in message
        or "identity mismatch" in message
    ):
        return "operator_capabilities_missing"
    return "operator_exception"


def _is_deterministic_operator_failure(record: Mapping[str, Any]) -> bool:
    """True when retrying ``record`` cannot change the outcome (repo rule: no
    wasted retries -- classify once, record once, move on)."""
    return str(record.get("reason_code") or "") in DETERMINISTIC_OPERATOR_REASON_CODES
# Real content/schema/hash/freshness/provenance validation, gating `receipt_status` in
# `_operator_dispatch_attempt()` below (issue #288: presence of a file must not imply
# VERIFIED).


def _receipt_max_age_seconds() -> float:
    return float(os.environ.get("SIMPLICIO_RECEIPT_MAX_AGE_SECONDS", "86400"))
PHASES = [
    "intake",
    "awaiting_decision",
    "mapping",
    "planning",
    "executing",
    "validating",
    "watching",
    "delivering",
    "done",
    "partial",
    "blocked",
    "cancelled",
]
# Mapper >=0.19 provides the freshness/artifact receipt contract required for
# authoritative context and plan generation. Older versions can report a stale
# `fresh=true` inspect result and are therefore not safe as a planning source.
MAPPER_MIN_VERSION = (0, 19, 0)
MAPPER_REQUIRED_VERBS = ("scan", "inspect", "handoff", "ask", "sync")
DEVCLI_REQUIRED_TOKENS = (" edit", "--plan", "--apply", "--json")
# Issue #135: the operator bridge validates identity + capability + MIN_VERSION, not
# merely `which`. A dev-cli below this tuple is blocked before any mutation.
DEVCLI_MIN_VERSION = (0, 14, 0)
DEVCLI_REQUIRED_CAPABILITIES = ("edit", "--plan", "--apply", "--dry-run", "--json")
BATCH_SCHEMA = "simplicio.operator-batch/v1"
BATCH_PREFLIGHT_SCHEMA = "simplicio.operator-batch-preflight/v1"
NATIVE_PRISM_SCHEMA = "simplicio.loop.native-prism-dispatch/v1"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _rand_token(n: int = 10) -> str:
    chars = string.ascii_lowercase + string.digits
    return "".join(random.choice(chars) for _ in range(n))


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _default_completion_state() -> Dict[str, Any]:
    return {
        "ready": False,
        "receipt": "",
        "verdict": "DELIVERY_PENDING",
        "reason_code": "oracle_incomplete",
        "tag": "UNVERIFIED",
    }


def _completion_state(run_dir: Path, current: Dict[str, Any] | None = None) -> Dict[str, Any]:
    state = dict(current or _default_completion_state())
    receipt_path = run_dir / "completion-receipt.json"
    if not receipt_path.exists():
        return state
    payload = _load_json(receipt_path)
    state.update({
        "ready": bool(payload.get("ready", False)),
        "receipt": str(receipt_path),
        "verdict": payload.get("verdict", state.get("verdict", "DELIVERY_PENDING")),
        "reason_code": payload.get("reason_code", state.get("reason_code", "oracle_incomplete")),
        "tag": payload.get("tag", state.get("tag", "UNVERIFIED")),
    })
    return state


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _verify_run_stack_lock(run_root: Path) -> StackLock:
    """Reject component or route drift at the mutation boundary."""
    lock = load_stack_lock(run_root / "stack-lock.json")
    route = _execution_profile()
    lock.verify_unchanged(discover_installed_components(), route)
    return lock


STORAGE_ROUTE_RECEIPT = "storage-route-receipt.json"


def _storage_route_requested() -> str:
    """Return the store route; MapperStore is the only writable default."""
    return os.environ.get("SIMPLICIO_STORAGE_ROUTE", StorageRoute.MAPPER.value).strip().lower()


def _verify_storage_route(run_root: Path) -> dict[str, Any]:
    """Verify the immutable store route and current capability before mutation."""
    path = run_root / STORAGE_ROUTE_RECEIPT
    try:
        receipt = _load_json(path)
    except (OSError, TypeError, ValueError) as exc:
        raise StoreAdapterError("STORAGE_ROUTE_RECEIPT_MISSING") from exc
    return verify_route_receipt(receipt, requested=_storage_route_requested())


def _append_jsonl(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _run_cmd(
    argv: List[str], cwd: Path, *, timeout_seconds: int = 180,
) -> subprocess.CompletedProcess:
    if argv and argv[0] == "simplicio-mapper":
        timeout_seconds = _mapper_timeout_seconds()
    # Windows console-script shims can be published as ``.cmd`` files.  The
    # shell-free subprocess API does not reliably append PATHEXT entries when
    # only the bare command name is supplied, so resolve the executable first
    # while retaining the shell-free invocation boundary.
    resolved = shutil.which(argv[0]) if argv else None
    command = [resolved, *argv[1:]] if resolved else argv
    try:
        return subprocess.run(
            command,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            env=_subprocess_env(),
        )
    except subprocess.TimeoutExpired as exc:
        def _text(value: Any) -> str:
            if isinstance(value, bytes):
                return value.decode(errors="replace")
            return str(value or "")

        stderr = _text(exc.stderr)
        timeout_note = f"command timed out after {timeout_seconds}s"
        if timeout_note not in stderr:
            stderr = f"{stderr}\n{timeout_note}".strip()
        return subprocess.CompletedProcess(argv, 124, _text(exc.stdout), stderr)


def _run_repo_path(run_dir: Path) -> Optional[Path]:
    """Best-effort recovery of a run's repo checkout path from its ``manifest.json``,
    for the #285 lifecycle-comment identity/branch projection. Returns ``None``
    instead of raising when the manifest is missing/malformed (e.g. a test fixture
    that writes a bare ``state.json`` with no manifest) -- callers treat that as
    "no repo context available", never a hard failure.
    """
    try:
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        repo = manifest.get("repo")
        return Path(repo).resolve() if repo else None
    except Exception:
        return None


def _git_current_branch(repo_path: Path) -> str:
    """Best-effort current branch name for the #285 lifecycle comment's
    Branch/worktree field. Never raises -- any git failure (detached HEAD, no
    repo, missing git binary) just yields an empty projection rather than a
    fabricated branch name."""
    try:
        result = _run_cmd(["git", "rev-parse", "--abbrev-ref", "HEAD"], repo_path)
    except Exception:
        return ""
    if result.returncode != 0:
        return ""
    branch = (result.stdout or "").strip()
    return branch if branch and branch != "HEAD" else ""


def _dispatch_identity_fields(repo_path: Optional[Path]) -> Dict[str, str]:
    """Best-effort local agent identity for the #285 lifecycle comment's
    Agente/Runtime/Device fields.

    Uses one stable per-repo identity file so every run projects the same genuine
    ``agent_id``/``runtime``/``device_id`` instead of leaving those fields blank.
    Never raises -- an
    unavailable ``scripts.agent_identity`` module (installed package without the
    scripts namespace), a missing repo path, or any I/O failure just yields an
    empty projection rather than fabricated identity.
    """
    if ensure_identity is None or repo_path is None:
        return {}
    try:
        identity = ensure_identity(
            path=os.environ.get("SIMPLICIO_IDENTITY_FILE") or str(repo_path / ".simplicio-loop/orchestrator" / "agent-identity.json"),
            runtime=os.environ.get("SIMPLICIO_RUNTIME", "unknown-runtime"),
        )
    except Exception:
        return {}
    return {
        "agent_id": str(identity.get("agent_id") or ""),
        "runtime": str(identity.get("runtime") or ""),
        "device": str(identity.get("device_id") or ""),
    }


def _operator_env() -> Dict[str, str]:
    env = _subprocess_env()
    env.setdefault(
        "SIMPLICIO_MODEL",
        os.environ.get("SIMPLICIO_LOOP_OPERATOR_MODEL", "codex-cli/gpt-5.4"),
    )
    env.setdefault(
        "SIMPLICIO_CODEX_EFFORT",
        os.environ.get("SIMPLICIO_LOOP_OPERATOR_EFFORT", "medium"),
    )
    loop_test_cmd = os.environ.get("SIMPLICIO_LOOP_TEST_CMD", "").strip()
    if loop_test_cmd and not env.get("SIMPLICIO_TEST_CMD", "").strip():
        env["SIMPLICIO_TEST_CMD"] = loop_test_cmd
    return env


def _operator_timeout(kind: str) -> int:
    default = 60 if kind == "dry_run" else 600
    raw = os.environ.get("SIMPLICIO_LOOP_OPERATOR_TIMEOUT_SEC", "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(30, value)


def _mapper_timeout_seconds() -> int:
    """Return the bounded wait used by every Mapper deep-pass command.

    The same runaway ceiling as the mapper index (300 s). Operators can raise it
    with SIMPLICIO_LOOP_MAPPER_TIMEOUT_SEC. A detached index must not be awaited
    for an hour.
    """
    default = 300
    raw = os.environ.get("SIMPLICIO_LOOP_MAPPER_TIMEOUT_SEC", "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(1, value)


def _mapper_supports_command(preflight: Mapping[str, Any], command: str) -> bool:
    """Detect an optional Mapper command from its measured help surface."""
    help_stdout = str(preflight.get("help_stdout") or "")
    return any(
        line.strip().startswith(command + " ") or line.strip() == command
        for line in help_stdout.splitlines()
    )


def _mapper_inspection_is_fresh(result: subprocess.CompletedProcess[str]) -> bool:
    """Return whether Mapper's persisted inspection proves a usable fresh index."""
    try:
        payload = json.loads(result.stdout or "")
    except (TypeError, ValueError):
        return False
    if not isinstance(payload, Mapping):
        return False
    status = payload.get("status")
    return (
        isinstance(status, Mapping)
        and status.get("artifacts_present") is True
        and status.get("fresh") is True
    )


def _mapper_inspection_reports_stale(result: subprocess.CompletedProcess[str]) -> bool:
    """Return true only when Mapper explicitly reports a stale/incomplete index."""
    try:
        payload = json.loads(result.stdout or "")
    except (TypeError, ValueError):
        return False
    if not isinstance(payload, Mapping):
        return False
    status = payload.get("status")
    return (
        isinstance(status, Mapping)
        and (
            status.get("artifacts_present") is not True
            or status.get("fresh") is not True
        )
    )


def _degraded_mapper_fallback_enabled() -> bool:
    """Allow explicit-target local work to continue when deep mapping is unavailable."""
    raw = os.environ.get("SIMPLICIO_LOOP_ALLOW_DEGRADED_MAPPER", "").strip().lower()
    if raw:
        return raw not in {"0", "false", "no", "off", "disabled"}
    return True


def _degraded_mapper_payload(
    repo_path: Path,
    before: Mapping[str, Any],
    mapper_preflight: Mapping[str, Any],
    scan: Any,
    inspect: Any,
    snapshot: Any,
    handoff: Any,
    target_hint: str,
    ecc_admission: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Build an explicitly UNVERIFIED context for a bounded local retry.

    This is not a substitute for a Mapper receipt: the original command results remain
    persisted, the degraded marker is durable, and only targets resolved inside the
    repository are exposed to planning. Without a target hint, the context remains
    empty and planning fails closed.
    """
    target = str(target_hint or "").strip().replace("\\", "/")
    files: List[Dict[str, Any]] = []
    if target:
        candidate = (repo_path / target).resolve()
        try:
            candidate.relative_to(repo_path.resolve())
        except (OSError, ValueError):
            target = ""
        else:
            if candidate.is_file() or candidate.is_dir():
                files.append({"path": target, "source": "explicit_task_target"})
            else:
                target = ""
    # Without an explicit target, keep the context empty and fail closed;
    # repository-wide inference can authorize an unrelated file.
    pack_seed = {
        "repo_state": dict(before),
        "target": target,
        "files": files,
        "reason": "mapper_deep_pass_unavailable",
    }
    pack_hash = hashlib.sha256(
        json.dumps(pack_seed, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    degraded_handoff = {
        "ready": bool(files),
        "context_pack": {
            "schema": "simplicio.context-pack/v1",
            "pack_hash": pack_hash,
            "files": files,
            "fidelity": {"gate": "degraded_local", "status": "UNVERIFIED"},
            "source": "simplicio-loop-local-fallback",
        },
        "degraded_local": True,
    }
    return {
        "scan": {
            "returncode": scan.returncode,
            "stdout": json.loads(scan.stdout) if scan.stdout.strip() else {},
            "stderr": (scan.stderr or "").strip(),
        },
        "inspect": {
            "returncode": inspect.returncode,
            "stdout": json.loads(inspect.stdout) if inspect.stdout.strip() else {},
            "stderr": (inspect.stderr or "").strip(),
        },
        "snapshot": {
            "returncode": snapshot.returncode,
            "stdout": json.loads(snapshot.stdout) if snapshot.stdout.strip() else {},
            "stderr": (snapshot.stderr or "").strip(),
        },
        "handoff": {
            "returncode": 0,
            "stdout": degraded_handoff,
            "stderr": (handoff.stderr or "").strip(),
        },
        "handoff_original": {
            "returncode": handoff.returncode,
            "stdout": json.loads(handoff.stdout) if handoff.stdout.strip() else {},
            "stderr": (handoff.stderr or "").strip(),
        },
        "generated_at": _now(),
        "repo_state_before": dict(before),
        "repo_state_after": _repo_fingerprint(repo_path),
        "mapper_preflight": dict(mapper_preflight),
        "ecc_admission": dict(ecc_admission or {}),
        "degraded_local": True,
        "degraded_reason_code": "mapper_deep_pass_unavailable",
        "evidence_status": "UNVERIFIED",
    }


def _devcli_env(repo_path: Path, base_env: Dict[str, str] | None = None) -> Dict[str, str]:
    env = dict(base_env or os.environ)
    repo_str = str(repo_path)
    current = env.get("PYTHONPATH", "").strip()
    env["PYTHONPATH"] = repo_str if not current else f"{repo_str}{os.pathsep}{current}"
    selected_devcli = _devcli_command_path()
    if selected_devcli != "simplicio-dev-cli":
        env["PATH"] = f"{Path(selected_devcli).resolve().parent}{os.pathsep}{env.get('PATH', '')}"
    # The external provider worker receives credentials through its own
    # allow-listed in-process boundary. Deterministic Dev CLI must never receive
    # provider credentials, even when the parent shell has them set.
    for key in _PROVIDER_SECRET_ENV:
        env.pop(key, None)
    env["SIMPLICIO_LOCAL_LLM_DISABLED"] = "1"
    if _degraded_mapper_fallback_enabled():
        env["SIMPLICIO_ALLOW_DEGRADED_MAPPER"] = "1"
    # The Loop's standalone operator preflight is a context/target gate;
    # it must not invoke the deterministic Dev CLI provider.
    env["SIMPLICIO_STANDALONE_PREFLIGHT"] = "1"
    model = env.get("SIMPLICIO_MODEL", "").strip().casefold()
    if model.startswith(("local/", "llama", "ollama")):
        env.pop("SIMPLICIO_MODEL", None)
    return env

def _devcli_has_mapper_manifest(command: str) -> bool:
    try:
        executable = Path(command).resolve()
        first_line = executable.read_text(encoding="utf-8", errors="ignore").splitlines()[0]
        interpreter = first_line[2:].strip() if first_line.startswith("#!") else ""
        if interpreter.startswith("/usr/bin/env "):
            interpreter = shutil.which(interpreter.rsplit(" ", 1)[-1]) or ""
        if not interpreter:
            return False
        probe = subprocess.run(
            [interpreter, "-c",
             "import importlib.resources; print(int(importlib.resources.files('simplicio_mapper').joinpath('contracts/context-snapshot/v1/contract-manifest.json').is_file()))"],
            capture_output=True, text=True, timeout=3, check=False,
            env=_subprocess_env(),
        )
        return probe.returncode == 0 and probe.stdout.strip() == "1"
    except (OSError, IndexError, subprocess.SubprocessError):
        return False


def _devcli_command_path() -> str:
    explicit = os.environ.get("SIMPLICIO_DEV_CLI_BIN", "").strip()
    if explicit:
        return explicit
    current = shutil.which("simplicio-dev-cli")
    candidates = []
    if current:
        candidates.append(current)
    pipx_root = Path.home() / ".local" / "pipx" / "venvs"
    if pipx_root.is_dir():
        candidates.extend(str(path) for path in sorted(pipx_root.glob("*/bin/simplicio-dev-cli")))
    compatible = next((path for path in candidates if _devcli_has_mapper_manifest(path)), None)
    return compatible or current or "simplicio-dev-cli"


def _devcli_cmd(repo_path: Path, *args: str) -> List[str]:
    if (repo_path / "simplicio" / "cli.py").exists():
        base = [sys.executable, "-m", "simplicio.cli", *args]
    else:
        base = ["simplicio-dev-cli", *args]
    return base

def _execution_profile() -> str:
    """Return the execution profile. Always ``standalone`` -- there is no
    Runtime/MCP backend in this stack. ``SIMPLICIO_EXECUTION_PROFILE`` may
    only be explicitly set to ``standalone``; any other value fails closed.
    """
    raw = os.environ.get("SIMPLICIO_EXECUTION_PROFILE", "").strip().lower()
    if raw in {"", "standalone", "auto"}:
        return "standalone"
    raise RuntimeError("SIMPLICIO_EXECUTION_PROFILE must be standalone")


def _hookwall_digest(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()



_LOOP_GENERATED_PATH_PREFIXES = (
    ".agents/_generated/",
    ".catalog/_generated/",
    ".skills/_generated/",
)
_LOOP_GENERATED_PATHS = {".catalog/project-capabilities.json"}


def _normalized_repo_path(path: str) -> str:
    """Normalize a Git path without stripping its meaningful leading dot."""
    normalized = str(path).replace("\\", "/").strip()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized.lstrip("/").lower()


def _is_loop_generated_path(path: str) -> bool:
    normalized = _normalized_repo_path(path)
    return normalized in _LOOP_GENERATED_PATHS or any(
        normalized.startswith(prefix) for prefix in _LOOP_GENERATED_PATH_PREFIXES
    )


def _is_loop_owned_status_path(path: str) -> bool:
    normalized = _normalized_repo_path(path)
    return (
        normalized.startswith(".simplicio-loop/orchestrator/")
        or normalized.startswith(".simplicio-loop/")
        or normalized.startswith(".claude/")
        or _is_loop_generated_path(normalized)
    )


def _repo_fingerprint(repo_path: Path, *, ignore_paths: Set[str] | None = None) -> Dict[str, str]:
    """Return a deterministic content fingerprint for mapper freshness gates.

    Git status alone cannot detect two edits to the same path, so the fingerprint includes
    file bytes for the relevant working tree while excluding generated mapper/run artifacts.
    This is intentionally local and model-free; a later mutation can therefore invalidate the
    plan without trusting an LLM's freshness claim.

    ``ignore_paths`` (repo-relative, POSIX-separated) additionally excludes specific files from
    both the content hash and the status filter -- used by ``simplicio_loop.apply`` so the
    ops.json a caller wrote to plan a change never makes that same change's own staleness
    check fail (issue #1318): `.simplicio-loop/` is already excluded unconditionally below, but
    an ops file living at the repo root needs an explicit, caller-supplied exclusion.
    """
    extra_ignored = set(ignore_paths or ())
    digest = hashlib.sha256()
    files = []
    try:
        listed = _run_cmd(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], repo_path)
    except Exception:
        listed = subprocess.CompletedProcess([], 1, "", "")
    if listed.returncode == 0:
        # Respect .gitignore: build outputs and verifier byproducts are not source.
        for rel in sorted({item for item in (listed.stdout or "").split("\0") if item}):
            if (
                _is_loop_generated_path(rel)
                or _is_tool_cache_path(rel)
                or rel.startswith(".simplicio-loop/")
                or rel in extra_ignored
            ):
                continue
            try:
                files.append((rel, (repo_path / rel).read_bytes()))
            except OSError:
                continue
    for root, dirs, names in ([] if listed.returncode == 0 else os.walk(repo_path)):
        relative_root = Path(root).relative_to(repo_path).as_posix()
        if relative_root == ".":
            relative_root = ""
        dirs[:] = [
            d for d in dirs
            if d not in {".git", ".simplicio-loop/orchestrator", ".simplicio-loop", "__pycache__"}
            and not _is_loop_generated_path(
                f"{relative_root}/{d}" if relative_root else d
            )
        ]
        for name in names:
            path = Path(root) / name
            try:
                rel = path.relative_to(repo_path).as_posix()
                if _is_loop_generated_path(rel) or rel in extra_ignored:
                    continue
                data = path.read_bytes()
            except (OSError, ValueError):
                continue
            files.append((rel, data))
    for rel, data in sorted(files, key=lambda item: item[0]):
        digest.update(rel.encode("utf-8", "surrogateescape"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(data).digest())
    head = ""
    status = ""
    try:
        head_result = _run_cmd(["git", "rev-parse", "HEAD"], repo_path)
        head = (head_result.stdout or "").strip() if head_result.returncode == 0 else ""
        status_result = _run_cmd(["git", "status", "--porcelain=v1", "--untracked-files=all"], repo_path)
        if status_result.returncode == 0:
            filtered = []
            for raw_line in (status_result.stdout or "").splitlines():
                line = raw_line.rstrip()
                if len(line) <= 3:
                    continue
                path_text = line[3:].strip()
                parts = [part.strip() for part in path_text.split("->")] if "->" in path_text else [path_text]
                normalized = [_normalized_repo_path(part) for part in parts if part.strip()]
                if normalized and all(
                    _is_loop_owned_status_path(item) or _is_tool_cache_path(item) or item in extra_ignored
                    for item in normalized
                ):
                    continue
                filtered.append(line)
            status = "\n".join(filtered).strip()
    except Exception:
        pass
    return {
        "head": head,
        "dirty_status_hash": hashlib.sha256(status.encode("utf-8")).hexdigest(),
        "tree_hash": digest.hexdigest(),
    }


def _repo_state_equivalent(left: Dict[str, str], right: Dict[str, str]) -> bool:
    """Return True when repo content and base commit are unchanged.

    `dirty_status_hash` is useful telemetry, but it can drift because helper-generated
    `.simplicio-loop/orchestrator`/`.simplicio-loop` state or other non-material status noise changes while the
    tracked working tree bytes remain identical. Freshness gates should therefore key on the
    semantic repository state: commit + tree content hash.
    """
    return (
        (left.get("head") or "") == (right.get("head") or "")
        and (left.get("tree_hash") or "") == (right.get("tree_hash") or "")
    )


def _parse_version_tuple(text: str) -> tuple[int, int, int]:
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", text or "")
    if not m:
        return (0, 0, 0)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def _preflight_override(name: str) -> Dict[str, Any] | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    return json.loads(raw)


def _resolved_identity(command: str, expected_stems: Sequence[str]) -> Dict[str, Any]:
    """Resolve an operator once and fail closed on a PATH identity mismatch."""
    path = shutil.which(command) or ""
    normalized = Path(path).stem.lower() if path else ""
    return {
        "command": command,
        "path": path,
        "identity_ok": bool(path) and any(stem.lower() in normalized for stem in expected_stems),
    }


def _criteria_text(task: Dict[str, Any]) -> str:
    lines = []
    for scenario in task.get("scenarios") or []:
        parts = []
        if scenario.get("then"):
            parts.extend(scenario["then"])
        else:
            parts.append(scenario.get("title") or scenario.get("id") or "scenario")
        lines.append("- " + " ".join(parts))
    return "\n".join(lines)


def _constraints_text(task: Dict[str, Any]) -> str:
    lines = []
    for rule in task.get("rules") or []:
        lines.append(f"- {rule.get('id')}: {rule.get('text')}")
    deps = (task.get("dependencies") or {}).get("items") or []
    for dep in deps:
        lines.append(f"- dependency: {dep}")
    return "\n".join(lines)


def _task_goal(task: Dict[str, Any]) -> str:
    identity = task.get("identity") or {}
    story = task.get("story") or {}
    parts = [
        p
        for p in [
            identity.get("system"),
            identity.get("feature"),
            identity.get("type"),
            story.get("persona"),
            story.get("desire"),
            story.get("value"),
        ]
        if p
    ]
    return " | ".join(parts)


def _task_spec_payload(task: Mapping[str, Any]) -> Dict[str, Any]:
    """Build the lossless Dev CLI TaskSpec handoff from a Loop task contract.

    Loop's contract is intentionally richer than the public TaskSpec.  The full
    contract is retained in an additive field while the canonical fields are
    mapped explicitly, so the operator never has to reconstruct the task from
    flattened goal/criteria/constraint strings.
    """
    original_text = str(task.get("original_text") or "")
    if not original_text.strip():
        raise RuntimeError("typed TaskSpec handoff requires task-contract original_text")
    normalized = original_text.replace("\r\n", "\n").replace("\r", "\n").strip()
    source_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    identity = dict(task.get("identity") or {})
    story = dict(task.get("story") or {})

    acceptance_criteria = []
    for scenario in task.get("scenarios") or []:
        item = dict(scenario)
        item.setdefault("original_text", " ".join(
            str(part).strip()
            for part in (
                item.get("title", ""),
                *[str(value) for value in item.get("given") or []],
                *[str(value) for value in item.get("when") or []],
                *[str(value) for value in item.get("then") or []],
            )
            if str(part).strip()
        ))
        acceptance_criteria.append(item)

    def stateful_items(value: Any, prefix: str) -> list[Dict[str, Any]]:
        if not isinstance(value, Mapping):
            return []
        state = str(value.get("state") or "unknown")
        items = []
        for index, entry in enumerate(value.get("items") or [], start=1):
            if isinstance(entry, Mapping):
                item = dict(entry)
                item.setdefault("id", f"{prefix}{index}")
                item.setdefault("original_text", str(item.get("text") or item.get("summary") or ""))
            else:
                item = {"id": f"{prefix}{index}", "text": str(entry), "original_text": str(entry)}
            item.setdefault("state", state)
            items.append(item)
        return items

    questions = [dict(item) for item in task.get("questions") or [] if isinstance(item, Mapping)]
    assumptions = [dict(item) for item in task.get("assumptions") or [] if isinstance(item, Mapping)]
    blockers = [dict(item) for item in task.get("blockers") or [] if isinstance(item, Mapping)]
    access_path = str(task.get("access_path") or "").strip()
    source = task.get("source") or {}
    task_id = str(identity.get("id") or identity.get("title") or f"TASK-{source_hash[:12].upper()}")
    payload: Dict[str, Any] = {
        "schema": "simplicio.task-spec/v2",
        "task_id": task_id,
        "source": {
            "kind": "simplicio-loop-task-contract",
            "locator": str(source.get("path") or "") or None,
            "encoding": "utf-8",
        },
        "source_hash": source_hash,
        "language": "unknown",
        "system": str(identity.get("system") or "") or None,
        "functionality": str(identity.get("feature") or "") or None,
        "task_type": str(identity.get("type") or "") or None,
        "narrative": {
            "persona": str(story.get("persona") or "") or None,
            "desire": str(story.get("desire") or "") or None,
            "value": str(story.get("value") or "") or None,
        },
        "acceptance_criteria": acceptance_criteria,
        "business_rules": [dict(item) for item in task.get("rules") or [] if isinstance(item, Mapping)],
        "non_functional_requirements": stateful_items(task.get("nfrs"), "NFR"),
        "prototypes": [dict(item) for item in task.get("prototypes") or [] if isinstance(item, Mapping)],
        "attachments": [],
        "navigation": ([{"id": "NAV1", "path": access_path, "original_text": access_path}]
                        if access_path else []),
        "dependencies": stateful_items(task.get("dependencies"), "DEP"),
        "impact_signals": dict(task.get("impact_signals") or {}),
        "additional_information": [
            {"id": f"INFO{index}", "text": str(item), "original_text": str(item)}
            for index, item in enumerate(task.get("additional_information") or [], start=1)
        ],
        "uncertainties": questions + assumptions + blockers,
        "human_gates": [dict(item) for item in questions],
        "verification_commands": ([{"command": test_command, "verifier": "declared"}]
                              if (test_command := os.environ.get("SIMPLICIO_TEST_CMD", "").strip())
                              else []),
        "source_span": {},
        "original_text": original_text,
        # Additive field: preserves every Loop-only field and makes the handoff
        # auditable without teaching the Dev CLI private Loop schema.
        "loop_task_contract": json.loads(json.dumps(dict(task), ensure_ascii=False)),
    }
    return payload


def _task_spec_hash(payload: Mapping[str, Any]) -> str:
    """Return the Dev CLI canonical TaskSpec hash for receipt correlation."""
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _derive_context_handle(snapshot_path: Path, pack_path: Path, execution_path: Path, repo_path: Path) -> str:
    """Derive the canonical Dev CLI handle from Mapper-owned artifacts."""
    try:
        from simplicio.plan_compiler.mapper_context import bind_mapper_context

        binding = bind_mapper_context(
            _load_json(snapshot_path),
            _load_json(pack_path),
            source_root=repo_path,
            execution_context_payload=_load_json(execution_path),
        )
        return str(binding.context_handle.value)
    except Exception:
        # Context derivation is fail-closed; Dev CLI reports the typed gate.
        return ""


def _context_handoff_args(
    repo_path: Path,
    run_root: Path,
    *,
    attempt_id: str = "",
    lease_id: str = "",
    fencing_token: str = "",
) -> Tuple[List[str], Dict[str, Any]]:
    """Project canonical Mapper context artifacts into the Dev CLI argv.

    The compact Mapper handoff is not a ContextSnapshot.  This helper only
    forwards explicitly supplied canonical artifacts and never derives a
    handle from a path or from ``mapper_context_hash``.  Missing artifacts are
    recorded as a diagnostic; the integrated Dev CLI remains the fail-closed
    owner of the final context gate.
    """
    authorization_args, authorization_handoff = prepare_authorization_handoff(run_root)
    mapper_path = run_root / "mapper-context.json"
    if not mapper_path.exists():
        return list(authorization_args), {
            "status": "missing", "reason_code": "CONTEXT_ARTIFACTS_UNAVAILABLE",
            "authorization": authorization_handoff,
        }
    try:
        mapper = _load_json(mapper_path)
    except (OSError, ValueError):
        return list(authorization_args), {
            "status": "invalid", "reason_code": "CONTEXT_ARTIFACTS_INVALID",
            "authorization": authorization_handoff,
        }
    handoff = mapper.get("handoff") if isinstance(mapper.get("handoff"), Mapping) else {}
    stdout = handoff.get("stdout") if isinstance(handoff.get("stdout"), Mapping) else handoff
    if not isinstance(stdout, Mapping):
        stdout = {}

    def first_value(keys: Sequence[str]) -> Any:
        for container in (mapper, stdout):
            for key in keys:
                value = container.get(key) if isinstance(container, Mapping) else None
                if value not in (None, "", {}):
                    return value
        return None

    def persist_artifact(value: Any, filename: str, fallbacks: Sequence[Path] = ()) -> Path | None:
        if isinstance(value, Mapping):
            reference_schema = str(value.get("schema") or "")
            handle = value.get("expansion_handle")
            handle_path = handle.get("path") if isinstance(handle, Mapping) else None
            if reference_schema == "simplicio.context-reference/v1" and isinstance(handle_path, str) and handle_path.strip():
                candidates = [Path(handle_path)]
                if not Path(handle_path).is_absolute():
                    candidates = [repo_path / handle_path, run_root / handle_path]
                for candidate in candidates:
                    try:
                        resolved = candidate.resolve()
                        if resolved.exists():
                            return resolved
                    except OSError:
                        continue
                return None
            path = run_root / filename
            _write_json(path, dict(value))
            return path
        candidates: List[Path] = []
        if isinstance(value, str) and value.strip():
            candidate = Path(value)
            candidates = ([candidate] if candidate.is_absolute()
                          else [base / candidate for base in (repo_path, run_root)])
        candidates.extend(fallbacks)
        for candidate in candidates:
            try:
                resolved = candidate.resolve()
                if resolved.exists():
                    return resolved
            except OSError:
                continue
        return None

    snapshot_path = persist_artifact(
        first_value(("context_snapshot", "canonical_context_snapshot", "context_snapshot_path")),
        "context-snapshot.json",
        (repo_path / ".simplicio-loop" / "context-snapshot.json",),
    )
    pack_path = persist_artifact(
        first_value(("context_pack", "canonical_context_pack", "context_pack_path")),
        "context-pack.json",
    )
    execution_path = persist_artifact(
        first_value(("execution_context", "canonical_execution_context", "execution_context_path")),
        "execution-context.json",
    )
    if mapper.get("degraded_local") and pack_path and _degraded_mapper_fallback_enabled():
        # Standalone Dev CLI can consume the explicit local pack without the
        # Mapper-owned snapshot/execution artifacts that a full handoff provides.
        args = ["--context-pack", str(pack_path)]
        args.extend(authorization_args)
        return args, {
            "status": "degraded_local",
            "context_handle": "",
            "pack_path": str(pack_path),
            "authorization": authorization_handoff,
            "evidence_status": "UNVERIFIED",
        }
    raw_context_handle = first_value(("context_handle", "canonical_context_handle"))
    context_handle = str(raw_context_handle).strip() if raw_context_handle not in (None, "", {}) else ""
    if not context_handle and all((snapshot_path, pack_path, execution_path)):
        context_handle = _derive_context_handle(snapshot_path, pack_path, execution_path, repo_path)
    identity_values = (attempt_id.strip(), lease_id.strip(), fencing_token.strip())
    identity_present = any(identity_values)
    identity_complete = all(identity_values)
    if identity_present and not identity_complete:
        return list(authorization_args), {
            "status": "missing",
            "reason_code": "CONTEXT_AUTHORIZATION_INCOMPLETE",
            "snapshot": bool(snapshot_path),
            "pack": bool(pack_path),
            "execution_context": bool(execution_path),
            "context_handle": bool(context_handle),
            "authorization": authorization_handoff,
        }
    if not all((snapshot_path, pack_path, execution_path)):
        return list(authorization_args), {
            "status": "missing",
            "reason_code": "CONTEXT_ARTIFACTS_INCOMPLETE",
            "snapshot": bool(snapshot_path),
            "pack": bool(pack_path),
            "execution_context": bool(execution_path),
            "context_handle": bool(context_handle),
            "authorization": authorization_handoff,
        }
    args = [
        "--context-snapshot", str(snapshot_path),
        "--context-pack", str(pack_path),
        "--execution-context", str(execution_path),
    ]
    if context_handle:
        args.extend(["--context-handle", context_handle])
    if identity_complete:
        args.extend([
            "--attempt-id", attempt_id,
            "--lease-id", lease_id,
            "--fencing-token", fencing_token,
        ])
    args.extend(authorization_args)
    return args, {
        "status": "propagated",
        "context_handle": context_handle,
        "context_handle_derived_by": "simplicio-dev-cli" if not context_handle else "mapper",
        "snapshot_path": str(snapshot_path),
        "pack_path": str(pack_path),
        "execution_context_path": str(execution_path),
        "authorization": authorization_handoff,
    }


def _auto_fan_out_enabled() -> bool:
    """Return whether batch execution may provision isolated workers automatically.

    Fan-out is the safe default for independent tasks.  Operators can explicitly opt out
    with ``SIMPLICIO_LOOP_AUTO_FAN_OUT=0`` when a repository cannot create worktrees (for
    example, a read-only checkout); the ordinary shared-run serial guard remains active in
    either mode.
    """
    raw = os.environ.get("SIMPLICIO_LOOP_AUTO_FAN_OUT", "1").strip().lower()
    return raw not in {"0", "false", "no", "off", "disabled"}


def _auto_merge_enabled() -> bool:
    """Opt-in gate (issue #288) for calling ``MergeExecutor`` for real once a dispatch
    attempt's receipt pair is ``VERIFIED``.

    Off by default: creating/merging a real PR is a side effect with real consequences (an
    actual GitHub API call, a real merge), so it must be explicitly requested via
    ``SIMPLICIO_AUTO_MERGE_PR=1`` plus a resolvable repo slug
    (``SIMPLICIO_REMOTE_REPO``/``GITHUB_REPOSITORY``) and a worktree branch on the item -- any
    of those missing is reported as ``attempted: False`` rather than silently skipped.
    """
    return str(os.environ.get("SIMPLICIO_AUTO_MERGE_PR") or "").strip().lower() in ("1", "true", "yes")


def _merge_repo_slug() -> str:
    return str(os.environ.get("SIMPLICIO_REMOTE_REPO") or os.environ.get("GITHUB_REPOSITORY") or "").strip()


def _dispatch_merge_pr(item: Mapping[str, Any], *, receipt: str, run_id: str) -> Dict[str, Any]:
    """Create/poll/merge the PR for a claimed item's worktree branch and reconcile the merge
    against the remote (issue #288).

    Formalizes the ad-hoc ``gh pr create`` / ``gh pr merge --squash --delete-branch`` pattern
    this project's own delivery workflow already performs by hand at the end of every task
    (AGENTS.md "Process" section) as a real, reusable call instead of prose an
    operator must remember. Never raises for an ordinary "cannot merge yet/here" outcome --
    those come back as ``attempted: True, merged: False`` with a specific reason so a caller
    can retry or escalate; only a hard `gh` transport failure surfaces as an error field.
    """
    context = item.get("worktree_context") or {}
    branch = str(context.get("branch") or "").strip()
    repo_slug = _merge_repo_slug()
    if not branch or not repo_slug:
        return {"attempted": False, "reason": "missing_branch_or_repo_slug", "merged": False}
    base = str(os.environ.get("SIMPLICIO_MERGE_BASE") or "main").strip()
    task_id = str(item.get("task_id") or "")
    title = ("simplicio-loop: %s" % task_id) if task_id else "simplicio-loop: automated delivery"
    body = ("Automated delivery for work item `%s` (run `%s`).\n\nOperator receipt: `%s`\n"
            % (task_id, run_id, receipt))
    try:
        executor = MergeExecutor(repo=repo_slug)
        pr = executor.ensure_pr(branch=branch, base=base, title=title, body=body)
        pr_number = int(pr.get("number") or 0)
        if not pr_number:
            return {"attempted": True, "merged": False, "reason_code": "NO_PR_NUMBER",
                    "detail": "ensure_pr did not resolve a PR number", "pr": pr}
        result = executor.merge(pr_number)
        return {"attempted": True, "pr": pr, **result.to_dict()}
    except MergeExecutorError as exc:
        return {"attempted": True, "merged": False, "reconciled": False,
                "reason_code": exc.reason_code, "detail": str(exc)}


# One task stays on the shared checkout and is executed with ``tick``.
# Two or more tasks are a wave: disjoint lanes run together and the wave
# returns only after every lane has integrated or failed closed.
WAVE_INLINE_MAX_TASKS = 1


def _auto_worktree_dispatch(
    repo: str,
    run_id: str,
    contract: Mapping[str, Any],
    plan: Mapping[str, Any],
    indices: Sequence[int],
) -> Tuple[Any, Dict[int, Dict[str, Any]], str]:
    """Build an isolated queue for a default batch when task impact is independent.

    This helper intentionally fails closed: missing plan targets, a non-git checkout, an
    overlapping impact key, or a queue allocation error all leave the caller with the
    existing shared-run serial path.  It never claims parallel execution without distinct
    worktree contexts.
    """
    if not _auto_fan_out_enabled() or len(indices) < 2:
        return None, {}, "auto_fan_out_disabled" if not _auto_fan_out_enabled() else "single_task"
    if len(indices) <= WAVE_INLINE_MAX_TASKS:
        return None, {}, "inline_small_batch"
    root = Path(repo).resolve()
    if not (root / ".git").exists():
        return None, {}, "not_git_checkout"
    try:
        from scripts.worktree_queue import TaskSpec, WorktreeQueue
    except ImportError:  # pragma: no cover - installed bundle without optional adapter
        try:
            from worktree_queue import TaskSpec, WorktreeQueue
        except ImportError:
            return None, {}, "worktree_adapter_unavailable"

    tasks = list(contract.get("tasks") or [])
    steps = list(plan.get("steps") or [])
    specs = []
    contexts: Dict[int, Dict[str, Any]] = {}
    for index in indices:
        if index > len(tasks) or index > len(steps):
            return None, {}, "plan_task_mismatch"
        step = steps[index - 1] if isinstance(steps[index - 1], Mapping) else {}
        targets = [str(value) for value in (step.get("candidate_targets") or []) if str(value).strip()]
        # A worktree without an authorized target cannot be executed; serial fallback gives
        # the caller the same clear preflight failure instead of manufacturing a lane.
        if not targets:
            return None, {}, "missing_plan_targets"
        task_id = f"{run_id}-task-{index}"
        specs.append(TaskSpec(id=task_id, goal=_task_goal(tasks[index - 1]), files_affected=targets))
    graph = WorktreeQueue.conflict_graph(specs)
    if any(graph.values()):
        return None, {}, "overlapping_task_impacts"
    try:
        queue = WorktreeQueue(
            repo_root=str(root),
            run_id=run_id,
            state_path=str(root / ".simplicio-loop" / "loop-runs" / run_id / "worktree-queue.json"),
            worktree_root=str(root / ".simplicio-loop" / "loop-worktrees" / run_id),
        )
        # Registration is an explicit preflight gate.  Allocation happens inside the
        # dispatcher, before any worker starts, and is persisted by the queue.
        queue.register_tasks(specs)
    except Exception:
        return None, {}, "worktree_preflight_failed"
    for index, spec in zip(indices, specs):
        contexts[index] = {
            "task_id": spec.id,
            "task_spec": {
                "id": spec.id,
                "goal": spec.goal,
                "files_affected": list(spec.files_affected),
            },
            "isolation": "worktree",
            "isolation_key": spec.id,
        }
    return queue, contexts, ""


_TOOL_CACHE_DIRS = frozenset({"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "htmlcov"})
# pytest-cov/coverage.py rewrites `.coverage` (and, in parallel mode,
# `.coverage.<host>.<pid>.<rand>` siblings) with fresh, non-deterministic
# content on *every* run of the task's own "Coverage verifier" lane -- the
# same non-source, tool-generated-byproduct category as __pycache__/.pyc
# above, and gitignored here for the same reason (see .gitignore). Left
# uncounted, a run's own Coverage verifier lane makes `state["repo_state_chain"]`
# (persisted right after the dev-cli mutation, before that lane runs)
# permanently mismatch a later task's own fresh `_repo_fingerprint` read in a
# separate `tick`/`wave --task-indices` process, misreporting the run's own
# evidence-gathering as external drift ("stale mapper context: repository
# changed after planning" / "plan_repo_state_stale").
_TOOL_CACHE_FILENAMES = frozenset({".coverage"})


def _is_tool_cache_path(rel: str) -> bool:
    """Caches/data files a verifier writes while it runs (pytest, mypy, ruff, bytecode, coverage)."""
    parts = rel.rstrip("/").split("/")
    if any(part in _TOOL_CACHE_DIRS for part in parts):
        return True
    if rel.endswith(".pyc"):
        return True
    name = parts[-1] if parts else rel
    return name in _TOOL_CACHE_FILENAMES or name.startswith(".coverage.")



_DEPENDENCY_PREFIX_RE = re.compile(
    r"^\s*(?:Depends on|Depende de|Depend[êe]ncia|Dependencia)\s*:\s*", re.I,
)
_DEPENDENCY_NOTE_RE = re.compile(r"\s*\([^)]*\)\s*$")
_TASK_NUMBER_RE = re.compile(r"^(?:(?:task|tarefa)\s*#?\s*|#)(\d+)$", re.I)


def _normalize_dependency_reference(item: Any) -> str:
    """Reduce a dependency as an LLM writes it ("Depends on: task 1 (x.html)")
    to the runner's own alias ("task-1"); ids and titles pass through."""
    text = _DEPENDENCY_PREFIX_RE.sub("", str(item)).strip().lstrip("-* ")
    text = _DEPENDENCY_NOTE_RE.sub("", text).strip()
    number = _TASK_NUMBER_RE.match(text)
    return f"task-{number.group(1)}" if number else text


def _dependency_references(value: Any) -> list[str]:
    if isinstance(value, Mapping):
        value = value.get("items") or value.get("depends_on") or ()
    if isinstance(value, str):
        value = [part.strip() for part in value.split(",")]
    if not isinstance(value, (list, tuple, set)):
        return []
    references = (_normalize_dependency_reference(item) for item in value)
    return [reference for reference in references if reference]


def _task_dependency_references(task: Mapping[str, Any], step: Mapping[str, Any] | None = None) -> tuple[str, ...]:
    values: list[str] = []
    for source in (task, step or {}):
        raw = source.get("depends_on") or source.get("dependencies") or ()
        values.extend(_dependency_references(raw))
    return tuple(dict.fromkeys(values))


def _task_aliases(task: Mapping[str, Any], index: int, run_id: str) -> set[str]:
    identity = task.get("identity") if isinstance(task.get("identity"), Mapping) else {}
    return {
        str(value).strip()
        for value in (
            task.get("id"), identity.get("id"), identity.get("system"), identity.get("title"),
            index, f"task-{index}", f"{run_id}-task-{index}",
        )
        if str(value).strip()
    }


def _assert_task_dependencies_ready(
    run_dir: Path,
    tasks: Sequence[Mapping[str, Any]],
    task_index: int,
    run_id: str,
    *,
    step: Mapping[str, Any] | None = None,
    in_batch: Collection[int] = (),
) -> None:
    """Reject a tick that arrives before every declared predecessor completed.

    A predecessor dispatched in the same batch (``in_batch``) is ordered by
    the batch's shared serial run, so it has no result marker yet."""
    aliases: dict[str, int] = {
        alias: index
        for index, task in enumerate(tasks, start=1)
        for alias in _task_aliases(task, index, run_id)
    }
    references = _task_dependency_references(tasks[task_index - 1], step)
    for reference in references:
        dependency_index = aliases.get(reference)
        if dependency_index is None:
            raise RuntimeError(
                f"task dependency is not part of the run: task {task_index}->{reference}"
            )
        if dependency_index == task_index:
            raise RuntimeError(f"task cannot depend on itself: task {task_index}")
        if dependency_index in in_batch:
            continue
        marker = run_dir / f"task-{dependency_index}-result.json"
        if not marker.is_file():
            raise RuntimeError(
                f"task dependency is not completed: task {task_index} requires task {dependency_index}"
            )
        try:
            result = _load_json(marker)
        except (OSError, TypeError, ValueError) as exc:
            raise RuntimeError(
                f"task dependency result is unreadable: task {dependency_index}"
            ) from exc
        if result.get("status") not in {"applied", "no_change", "succeeded", "completed"}:
            raise RuntimeError(
                f"task dependency did not complete successfully: task {dependency_index}"
            )


def _item_dependencies(item: Mapping[str, Any]) -> tuple[str, ...]:
    raw_spec = item.get("task_spec")
    spec: Mapping[str, Any] = raw_spec if isinstance(raw_spec, Mapping) else {}
    raw = spec.get("depends_on") or spec.get("dependencies") or item.get("depends_on") or ()
    return tuple(dict.fromkeys(_dependency_references(raw)))


def _completed_task_aliases(
    run_dir: Path,
    tasks: Sequence[Mapping[str, Any]],
    run_id: str,
) -> set[str]:
    """Aliases of tasks that already finished successfully in this run."""
    aliases: set[str] = set()
    for index, task in enumerate(tasks, start=1):
        marker = run_dir / f"task-{index}-result.json"
        if not marker.is_file():
            continue
        try:
            result = _load_json(marker)
        except (OSError, TypeError, ValueError):
            continue
        if result.get("status") not in {"applied", "no_change", "succeeded", "completed"}:
            continue
        aliases.update(_task_aliases(task, index, run_id))
    return aliases


def _omit_satisfied_dispatch_dependencies(
    items: Iterable[Mapping[str, Any]],
    *,
    satisfied_aliases: Collection[str] = (),
) -> list[Dict[str, Any]]:
    """Drop DAG edges whose predecessor already completed outside this batch."""
    satisfied = {str(alias).strip() for alias in satisfied_aliases if str(alias).strip()}
    filtered: list[Dict[str, Any]] = []
    for item in items:
        row = dict(item)
        spec = dict(row["task_spec"]) if isinstance(row.get("task_spec"), Mapping) else {}
        remaining = [dependency for dependency in _item_dependencies({"task_spec": spec, **row}) if dependency not in satisfied]
        spec["depends_on"] = remaining
        row["task_spec"] = spec
        filtered.append(row)
    return filtered


def _ordered_dispatch_items(items: Iterable[Mapping[str, Any]]) -> list[Dict[str, Any]]:
    """Return a stable topological order and fail closed on unknown/cyclic edges."""
    rows = [dict(item) for item in items]
    by_id: dict[str, Dict[str, Any]] = {}
    by_index: dict[str, Dict[str, Any]] = {}
    for row in rows:
        task_id = str(row.get("task_id") or "").strip()
        if not task_id or task_id in by_id:
            raise ValueError("operator dispatch task ids must be unique and non-empty")
        by_id[task_id] = row
        if row.get("task_index") is not None:
            by_index[str(row["task_index"])] = row
    dependencies: dict[str, set[str]] = {}
    for row in rows:
        task_id = str(row["task_id"])
        resolved: set[str] = set()
        for dependency in _item_dependencies(row):
            candidate = by_id.get(dependency) or by_index.get(dependency.removeprefix("task-"))
            if candidate is None:
                raise ValueError(f"operator dispatch dependency is not in the batch: {task_id}->{dependency}")
            dependency_id = str(candidate["task_id"])
            if dependency_id == task_id:
                raise ValueError(f"operator dispatch task cannot depend on itself: {task_id}")
            resolved.add(dependency_id)
        dependencies[task_id] = resolved
    order = {str(row["task_id"]): index for index, row in enumerate(rows)}
    ready = [
        str(row["task_id"])
        for row in rows
        if not dependencies[str(row["task_id"])]
    ]
    ready.sort(key=order.__getitem__)
    result: list[Dict[str, Any]] = []
    while ready:
        task_id = ready.pop(0)
        result.append(by_id[task_id])
        for candidate in rows:
            candidate_id = str(candidate["task_id"])
            if task_id in dependencies[candidate_id]:
                dependencies[candidate_id].remove(task_id)
                if not dependencies[candidate_id] and candidate_id not in {str(row["task_id"]) for row in result}:
                    ready.append(candidate_id)
        ready.sort(key=order.__getitem__)
    if len(result) != len(rows):
        unresolved = sorted(task_id for task_id, deps in dependencies.items() if deps)
        raise ValueError("operator dispatch dependency cycle: " + ", ".join(unresolved))
    return result


def _mapper_journal_enabled(storage_route: StorageRoute | str | None = None) -> bool:
    raw = _storage_route_requested() if storage_route is None else storage_route
    try:
        return StorageRoute(raw) == StorageRoute.MAPPER
    except ValueError as error:
        raise StoreAdapterError("STORAGE_ROUTE_INVALID") from error


def read_status(repo: str, run_id: str = "") -> Dict[str, Any]:
    repo_path = Path(repo).resolve()
    runs_root = repo_path / ".simplicio-loop" / "loop-runs"
    if not runs_root.exists():
        return {
            "run_dir": None,
            "manifest": None,
            "state": {
                "phase": "no_runs",
                "completion": {"ready": False, "verdict": "NO_RUNS", "tag": "UNVERIFIED"},
                "operator": {"ready": False, "execution_state": "idle"},
                "evidence": {"ready": False, "status": "NO_RUNS"},
                "current_action": "none",
                "next_action": "none",
                "message": "no runs directory found; run simplicio-loop to start",
            },
            "execution_route": None,
            "route_receipt_status": "UNVERIFIED",
        }
    chosen = None
    if run_id:
        chosen = runs_root / run_id
    else:
        candidates = sorted([p for p in runs_root.iterdir() if p.is_dir()], key=lambda p: p.name)
        if not candidates:
            return {
                "run_dir": None,
                "manifest": None,
                "state": {
                    "phase": "no_runs",
                    "completion": {"ready": False, "verdict": "NO_RUNS", "tag": "UNVERIFIED"},
                    "operator": {"ready": False, "execution_state": "idle"},
                    "evidence": {"ready": False, "status": "NO_RUNS"},
                    "current_action": "none",
                    "next_action": "none",
                    "message": "no runs found; run simplicio-loop to start",
                },
                "execution_route": None,
                "route_receipt_status": "UNVERIFIED",
            }
        chosen = candidates[-1]
    manifest = _load_json(chosen / "manifest.json")
    state = _load_json(chosen / "state.json")
    state["completion"] = _completion_state(chosen, state.get("completion"))
    execution_route = None
    route_path = chosen / "execution-route.json"
    if route_path.is_file():
        try:
            candidate = _load_json(route_path)
            if verify_route_hash(candidate):
                execution_route = candidate
                state.setdefault("operator", {})["execution_route"] = candidate
                state["execution_route"] = candidate
        except (OSError, ValueError, TypeError):
            execution_route = None
    return {
        "run_dir": str(chosen),
        "manifest": manifest,
        "state": state,
        "execution_route": execution_route,
        "route_receipt_status": "MEASURED" if execution_route else "UNVERIFIED",
    }
