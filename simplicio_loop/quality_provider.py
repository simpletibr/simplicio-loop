"""Quality provider boundary for the Simplicio Loop.

Issue #613: a versioned, awaitable, fail-closed provider that runs the full
quality layer AFTER execution completes and BEFORE the watcher, delivery, and
Completion Oracle. The Loop remains the owner of resources, retry, cancellation,
and terminality -- the provider receives a cancel token and must never spawn its
own scheduler / queue / process pool.

Lifecycle:
  load_quality_provider(name, policy) -> QualityProviderSpec (negotiated)
  run_quality_gate(repo, run_id, spec, cancel_event) -> QualityResult
    writes .simplicio-loop/.../quality-matrix.json (simplicio.quality-matrix/v1)
    returns {"status": "PASS"|"FAIL"|"BLOCKED", ...}

Fail-closed: a missing, version-incompatible, crashing, or timed-out mandatory
provider transitions the run to BLOCKED -- never a silent fallback.
"""
from __future__ import annotations

import importlib
import importlib.metadata
import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

QUALITY_MATRIX_SCHEMA = "simplicio.quality-matrix/v1"
PROVIDER_MODULE_TEMPLATE = "simplicio_loop.quality_providers.{name}"
EXTENSION_ENTRY_POINT_GROUP = "simplicio.loop_extension"
PROVIDER_TIMEOUT_SECONDS = 30.0
# Only this shipped builtin route may exceed the historical provider default.
# 930s = the existing 900s core-gate deadline + 30s bounded cleanup grace.
BUILTIN_QUALITY_PROVIDER_MODULE = "simplicio_loop.quality_providers.simplicio_loop_quality"
BUILTIN_PROVIDER_TIMEOUT_SECONDS = 930.0
MIN_PROVIDER_PROTOCOL_VERSION = (1, 0, 0)


class QualityProviderError(RuntimeError):
    """Raised when a provider cannot be loaded or negotiated."""

    def __init__(self, reason: str, *, kind: str = "error"):
        super().__init__(reason)
        self.reason = reason
        self.kind = kind  # "absent" | "version" | "crash" | "error"


@dataclass
class QualityProviderSpec:
    """A negotiated provider contract."""

    name: str
    policy: str
    version: str
    capabilities: Dict[str, Any] = field(default_factory=dict)
    module_path: str = ""

    def supports(self, capability: str) -> bool:
        return bool(self.capabilities.get(capability, False))


@dataclass
class QualityResult:
    """Structured return from a provider run."""

    status: str  # "PASS" | "FAIL" | "BLOCKED"
    provider: str = ""
    version: str = ""
    policy: str = ""
    findings: List[Dict[str, Any]] = field(default_factory=list)
    receipts: List[str] = field(default_factory=list)
    detail: str = ""

    def to_matrix(self, run_id: str, repo: str, head: str, diff_hash: str, attempt: int) -> Dict[str, Any]:
        return {
            "schema": QUALITY_MATRIX_SCHEMA,
            "run_id": run_id,
            "repo": repo,
            "head": head,
            "diff_hash": diff_hash,
            "attempt": attempt,
            "provider": self.provider,
            "version": self.version,
            "policy": self.policy,
            "status": self.status,
            "findings": self.findings,
            "receipts": self.receipts,
            "detail": self.detail,
            "generated_at": _now(),
        }


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _parse_version(version: str) -> tuple:
    parts = []
    for chunk in version.split("."):
        num = ""
        for ch in chunk:
            if ch.isdigit():
                num += ch
            else:
                break
        parts.append(int(num) if num else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def _quality_extension_entry(name: str) -> Any:
    """Return an explicitly selected external quality entry point, if installed."""

    try:
        candidates = importlib.metadata.entry_points(group=EXTENSION_ENTRY_POINT_GROUP)
    except TypeError:  # pragma: no cover - Python 3.9 compatibility
        candidates = importlib.metadata.entry_points().get(EXTENSION_ENTRY_POINT_GROUP, [])
    return next((item for item in candidates if str(getattr(item, "name", "")) == name), None)


def _load_entry_point_module(name: str, entry: Any) -> tuple[Any, str]:
    loaded = entry.load()
    runtime = loaded() if callable(loaded) else loaded
    manifest = getattr(runtime, "manifest", None)
    if not isinstance(manifest, Mapping) or manifest.get("extension_id") != name:
        raise ValueError("extension entry point manifest identity is invalid")
    module_name = str(getattr(entry, "value", "")).split(":", 1)[0]
    return importlib.import_module(module_name), module_name


def load_quality_provider(name: str, policy: str, *, repo: str = ".") -> QualityProviderSpec:
    """Import and negotiate a quality provider. Fail-closed on any problem."""
    module_name = PROVIDER_MODULE_TEMPLATE.format(name=name)
    # Prefer a selected extension entry point over a legacy same-named builtin.
    # This prevents the core compatibility shim from shadowing a real external
    # provider that owns the Hub-backed execution contract.
    selected_entry = _quality_extension_entry(name)
    if selected_entry is not None:
        # External quality distributions are opt-in extensions. Resolve only
        # an explicitly requested entry point; the Loop core never imports or
        # depends on a particular quality package.
        try:
            module, module_name = _load_entry_point_module(name, selected_entry)
        except Exception as entry_exc:
            raise QualityProviderError(
                f"quality provider '{name}' extension entry point failed: {entry_exc}",
                kind="crash",
            ) from entry_exc
    else:
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            raise QualityProviderError(
                f"quality provider '{name}' not found (module {module_name}: {exc})",
                kind="absent",
            ) from exc
        except Exception as exc:  # pragma: no cover - import side effects
            raise QualityProviderError(
                f"quality provider '{name}' failed to import: {exc}", kind="crash"
            ) from exc

    negotiate = getattr(module, "capability_negotiate", None)
    if not callable(negotiate):
        raise QualityProviderError(
            f"quality provider '{name}' missing callable capability_negotiate()",
            kind="crash",
        )
    try:
        caps = negotiate()
    except Exception as exc:
        raise QualityProviderError(
            f"quality provider '{name}' capability_negotiate() raised: {exc}",
            kind="crash",
        )
    if not isinstance(caps, dict):
        raise QualityProviderError(
            f"quality provider '{name}' capability_negotiate() returned non-dict",
            kind="crash",
        )

    version = str(caps.get("version", "0.0.0"))
    if _parse_version(version) < MIN_PROVIDER_PROTOCOL_VERSION:
        raise QualityProviderError(
            f"quality provider '{name}' version {version} < required "
            f"{'.'.join(map(str, MIN_PROVIDER_PROTOCOL_VERSION))}",
            kind="version",
        )

    run_fn = getattr(module, "run", None)
    if not callable(run_fn):
        raise QualityProviderError(
            f"quality provider '{name}' missing callable run()", kind="crash"
        )

    return QualityProviderSpec(
        name=name,
        policy=policy,
        version=version,
        capabilities=(caps.get("capabilities", caps) if isinstance(caps.get("capabilities", caps), dict) else {}),
        module_path=module_name,
    )


def _run_provider_sync(
    spec: QualityProviderSpec,
    *, run_id: str, tasks: List[Any], attempt: int, repo: str,
    worktree: str, head: str, diff_hash: str, cancel_event: threading.Event,
    result_box: List[Any], error_box: List[Exception],
) -> None:
    try:
        module = importlib.import_module(spec.module_path)
        outcome = module.run(
            run_id=run_id,
            tasks=tasks,
            attempt=attempt,
            repo=repo,
            worktree=worktree,
            head=head,
            diff_hash=diff_hash,
            policy=spec.policy,
            cancel_token=cancel_event,
        )
        result_box.append(outcome)
    except Exception as exc:  # pragma: no cover - runtime provider crash
        error_box.append(exc)


def _provider_timeout_seconds(spec: QualityProviderSpec) -> float:
    """Return the finite deadline for an identified builtin route only."""
    if (spec.name == "simplicio_loop_quality"
            and spec.module_path == BUILTIN_QUALITY_PROVIDER_MODULE):
        return BUILTIN_PROVIDER_TIMEOUT_SECONDS
    return PROVIDER_TIMEOUT_SECONDS


def run_quality_gate(
    repo: str,
    run_id: str,
    spec: QualityProviderSpec,
    *,
    tasks: Optional[List[Any]] = None,
    attempt: int = 1,
    worktree: str = "",
    head: str = "",
    diff_hash: str = "",
    cancel_event: Optional[threading.Event] = None,
) -> QualityResult:
    """Execute the provider fail-closed and persist quality-matrix.json."""
    if cancel_event is None:
        cancel_event = threading.Event()
    tasks = tasks or []

    result_box: List[Any] = []
    error_box: List[Exception] = []
    worker = threading.Thread(
        target=_run_provider_sync,
        kwargs=dict(
            spec=spec, run_id=run_id, tasks=tasks, attempt=attempt, repo=repo,
            worktree=worktree, head=head, diff_hash=diff_hash,
            cancel_event=cancel_event, result_box=result_box, error_box=error_box,
        ),
        daemon=True,
    )
    worker.start()
    worker.join(timeout=_provider_timeout_seconds(spec))
    if worker.is_alive():
        cancel_event.set()
        return QualityResult(
            status="BLOCKED", provider=spec.name, version=spec.version,
            policy=spec.policy, detail="quality provider timed out",
        )
    if error_box:
        return QualityResult(
            status="BLOCKED", provider=spec.name, version=spec.version,
            policy=spec.policy,
            detail=f"quality provider crashed: {error_box[0]}",
        )
    if not result_box:
        return QualityResult(
            status="BLOCKED", provider=spec.name, version=spec.version,
            policy=spec.policy, detail="quality provider returned nothing",
        )

    raw = result_box[0]
    status = str(raw.get("status") if isinstance(raw, dict) else getattr(raw, "status", "")).upper()
    if status not in ("PASS", "FAIL"):
        status = "BLOCKED"
    findings = raw.get("findings", []) if isinstance(raw, dict) else getattr(raw, "findings", [])
    receipts = raw.get("receipts", []) if isinstance(raw, dict) else getattr(raw, "receipts", [])
    detail = raw.get("detail", "") if isinstance(raw, dict) else getattr(raw, "detail", "")
    result = QualityResult(
        status=status, provider=spec.name, version=spec.version,
        policy=spec.policy, findings=list(findings), receipts=list(receipts),
        detail=detail,
    )

    matrix = result.to_matrix(run_id, repo, head, diff_hash, attempt)
    run_dir = _resolve_run_dir(repo, run_id)
    if run_dir:
        (Path(run_dir) / "quality-matrix.json").write_text(
            json.dumps(matrix, indent=2), encoding="utf-8"
        )
    return result


def _resolve_run_dir(repo: str, run_id: str) -> Optional[str]:
    """Best-effort discovery of the run directory under .simplicio-loop/runs."""
    root = Path(repo).resolve()
    candidate = root / ".simplicio-loop" / "runs" / run_id
    if candidate.exists():
        return str(candidate)
    runs_root = root / ".simplicio-loop" / "runs"
    if runs_root.exists():
        for child in runs_root.iterdir():
            status_file = child / "state.json"
            if status_file.exists():
                try:
                    data = json.loads(status_file.read_text(encoding="utf-8"))
                    if data.get("run_id") == run_id or run_id in str(child):
                        return str(child)
                except Exception:
                    pass
    return None


def conduct_quality(
    repo: str,
    run_id: str,
    *,
    quality_provider: Optional[str] = None,
    quality_policy: str = "strict-default",
    tasks: Optional[List[Any]] = None,
    attempt: int = 1,
    worktree: str = "",
    head: str = "",
    diff_hash: str = "",
    cancel_event: Optional[threading.Event] = None,
) -> Dict[str, Any]:
    """High-level entry used by conduct_run(). Returns a gate dict."""
    if not quality_provider:
        return {"status": "SKIPPED", "provider": None, "reason": "no quality provider configured"}
    try:
        spec = load_quality_provider(quality_provider, quality_policy, repo=repo)
    except QualityProviderError as exc:
        return {
            "status": "BLOCKED", "provider": quality_provider, "kind": exc.kind,
            "reason": exc.reason,
        }
    result = run_quality_gate(
        repo, run_id, spec, tasks=tasks, attempt=attempt, worktree=worktree,
        head=head, diff_hash=diff_hash, cancel_event=cancel_event,
    )
    return {
        "status": result.status, "provider": result.provider,
        "version": result.version, "policy": result.policy,
        "findings": result.findings, "receipts": result.receipts,
        "detail": result.detail,
    }
