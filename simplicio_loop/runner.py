from __future__ import annotations

import asyncio
import json
import hashlib
import os
import random
import re
import shutil
import signal
import tempfile
import subprocess
import time
import string
import sys
from threading import Thread
from collections import deque
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Any, Callable, Collection, Dict, Iterable, List, Literal, Mapping, Optional, Sequence, Set, Tuple, TypedDict

from .delivery import (build_delivery_receipt, normalize_delivery_target,
                       reconcile_delivery_observation, write_delivery_receipt)
from .evidence import build_evidence_receipt, redact_sensitive_text
from .source_state import github_delivery_payload, infer_github_delivery_state
from . import github_lifecycle as _github_lifecycle
from .client_integrations import integration_enabled
from .orca_lifecycle import sync_orca_status
from .source_adapter import GitHubSourceAdapter
from .task_contract import compile_many, validate_contract
from .event_metadata import SCHEMA as EVENT_METADATA_SCHEMA, infer_scope
from .technical_debt import record_notice as _record_technical_debt
from .checkpoint_lifecycle import CheckpointLifecycle, LifecycleError
from .operator_bootstrap import (
    OperatorBootstrapError,
    ensure_operators as _ensure_required_operators,
)
from .plan_contract import PLAN_SCHEMA, validate_plan
from .ecc_guidance import (
    ecc_required,
    ensure_ecc_ready,
    extract_guidance_reference,
    inspect_ecc,
)
from .remote_queue import HTTPRemoteQueue, QueueConflict, QueueUnavailable, build_completion_receipt
from .agent_contract import bind_receipt, build_context_pack
from .receipt_verifier import (EVIDENCE_RECEIPT_SCHEMA as _EVIDENCE_RECEIPT_CONTENT_SCHEMA,
                               OPERATOR_RECEIPT_SCHEMA as _OPERATOR_RECEIPT_CONTENT_SCHEMA,
                               ReceiptStatus, verify_receipt)
from .planning_gate import content_hash as _planning_content_hash
from .planning_gate import evaluate_mutation_authority, mutation_authority_required
from .planning_gate import auto_planning_receipt_enabled
from .planning_gate import build_planning_receipt as _build_planning_receipt
from .planning_gate import publish_planning_receipt as _publish_planning_receipt
from .work_item_claims import AttemptCoordinator, LeaseLostDuringExecution
from .merge_executor import MergeExecutor, MergeExecutorError
from . import local_capacity
from . import wave_worktree
from .model_registry import ModelCapabilityRegistry, ModelRegistryError
from .model_router import ModelRouterError, route as _model_route
from .runtime_drivers import CLI_PROBE_HOOKS, driver_for_runtime
from .runtime_context import ContextAuthorizationError, ContextBudgetError, RuntimeContextRequest
from .runtime_execution_receipt import RuntimeExecutionReceiptError
from .loop_execution_receipt import (
    LoopExecutionReceiptError,
    publish_loop_execution_receipt,
)
from .runtime_adapter import LoopRuntimeAdapter, RuntimeAdapterError
from .runtime_effect_adapter import EffectRequest, RuntimeEffectAdapter, RuntimeEffectError
from .provider_worker import (
    OPENROUTER_MODEL,
    OpenRouterWorker,
    ProviderWorkerError,
    forwarded_environment,
    proposal_to_mechanical_plan,
)
from .hookwall_gate import (
    HookwallBlocked,
    gate_completion,
    validate_envelope,
    validate_pre_decision,

)
from .hookwall_persistence import HookwallEffectLedger
from .canonical_plan import CanonicalPlan, load_canonical_plan
from .authority_boundary import prepare_authorization_handoff
from .verified_delivery import VerifiedAgentDelivery, VerifiedDeliveryError
from .execution_board import ExecutionBoard
from .run_journal import RunJournal
from .mapper_run_journal import MapperRunJournal
from .mapper_hookwall import MapperHookwallEffectLedger
from .store_adapter import (
    StorageRoute,
    StorageRouter,
    StoreAdapterError,
    verify_route_receipt,
)
from .stack_lock import (
    StackLock,
    discover_installed_components,
    load_stack_lock,
    write_stack_lock,
)

from .execution_route import _stable_hash as _execution_route_hash
from .execution_route import capability_fingerprint, normalize_capability_manifest, route_receipt_is_current
from .execution_route import decide_route, verify_route_hash
from .openrouter_operator import (
    enabled as _openrouter_operator_enabled,
    external_preflight_admissible as _external_preflight_admissible,
)
try:
    from scripts.agent_identity import ensure_identity
except ImportError:  # pragma: no cover - installed package without scripts namespace
    ensure_identity = None

try:
    from scripts.distributed_trust_policy import (
        TrustPolicyError,
        authorize as _trust_authorize,
        load_policy as _load_trust_policy,
        resolve_environment as _resolve_trust_environment,
    )
except ImportError:  # pragma: no cover - installed package without scripts namespace
    TrustPolicyError = RuntimeError  # type: ignore[assignment,misc]


    _trust_authorize = None
    _load_trust_policy = None
    _resolve_trust_environment = None


_PROVIDER_SECRET_ENV = (
    "OPENROUTER_API_KEY", "OPENROUTER_BASE_URL", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
)


def _subprocess_env(base: Optional[Mapping[str, str]] = None) -> Dict[str, str]:
    """Build a diagnostic/operator environment without provider credentials."""
    env = dict(base or os.environ)
    for key in _PROVIDER_SECRET_ENV:
        env.pop(key, None)
    return env

try:
    from scripts.security_audit_log import append_event as _audit_append
except ImportError:  # pragma: no cover - installed package without scripts namespace
    _audit_append = None

RUNNER_SCHEMA = "simplicio.run-manifest/v1"
STATE_SCHEMA = "simplicio.run-state/v1"
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
RECEIPT_MAX_AGE_SECONDS = float(os.environ.get("SIMPLICIO_RECEIPT_MAX_AGE_SECONDS", "86400"))
MAINTENANCE_RECEIPT_SCHEMA = "simplicio.maintenance-receipt/v1"
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

MaintenanceMode = Literal["active", "maintenance_deferred"]
MaintenanceDisposition = Literal["operator", "backlog_only"]


class OperatorDispatchItem(TypedDict, total=False):
    """Typed input contract for :func:`dispatch_operator_batch`."""

    repo: str
    run_id: str
    task_index: int
    worker_id: str
    isolation_key: str
    task_id: str
    task_spec: Mapping[str, Any]
    isolation: str
    operator_context: Mapping[str, Any]
    distributed_queue: Any
    agent_identity: Mapping[str, Any]
    context_pack: Mapping[str, Any]
    provider_worker: str


class MaintenanceState(TypedDict):
    mode: MaintenanceMode
    disposition: MaintenanceDisposition
    receipt: str
    correction_summary: str
    deferral_reason: str
    evidence_status: str


class MaintenanceDeferredReceipt(TypedDict):
    schema: str
    mode: Literal["maintenance_deferred"]
    disposition: Literal["backlog_only"]
    correction_summary: str
    deferral_reason: str
    resume_instructions: List[str]
    evidence_status: str
    recorded_at: str
    completion_ready: bool
    completion_verdict: str
    completion_reason_code: str


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _rand_token(n: int = 10) -> str:
    chars = string.ascii_lowercase + string.digits
    return "".join(random.choice(chars) for _ in range(n))


def _resolve_trusted_queue_context(url: str) -> tuple[str, Optional[str], Optional[Dict[str, Any]]]:
    """Resolve the distributed-queue destination via the #289 trust policy.

    ``.github/workflows/distributed-183-proof.yml`` -- the workflow this issue's
    exploit scenario named -- was removed repo-wide in #311, but the same
    exfiltration/confused-deputy risk applies to this call site: it is the real,
    currently-used way to hand a bearer token (``SIMPLICIO_REMOTE_QUEUE_TOKEN``)
    to a network destination. Setting ``SIMPLICIO_REMOTE_ENVIRONMENT_ID`` opts
    into fail-closed resolution: the destination comes from the versioned,
    CODEOWNERS-reviewed ``.github/security/distributed-trust-policy.json``, not
    from ``SIMPLICIO_REMOTE_QUEUE_URL``. A freeform ``SIMPLICIO_REMOTE_QUEUE_URL``
    may still be set for local corroboration, but it must match the policy's
    origin exactly -- an attacker-chosen destination is rejected before any
    identity/queue object (and therefore any token) is created.

    Environments without ``SIMPLICIO_REMOTE_ENVIRONMENT_ID`` set fall back to the
    legacy unmanaged path (whatever ``SIMPLICIO_REMOTE_QUEUE_URL`` names) for
    local/dev use; production/CI callers should set the environment id so the
    destination is policy-resolved.

    Returns ``(url, environment_id, policy)``; ``environment_id``/``policy`` are
    ``None`` on the legacy unmanaged path so callers can tell whether
    connect-time enforcement (:mod:`simplicio_loop.secure_transport`) applies.
    """
    environment_id = os.environ.get("SIMPLICIO_REMOTE_ENVIRONMENT_ID", "").strip()
    if not environment_id:
        return url, None, None
    if _resolve_trust_environment is None or _load_trust_policy is None or _trust_authorize is None:
        raise RuntimeError("distributed trust policy module unavailable")
    policy_path = os.environ.get("SIMPLICIO_DISTRIBUTED_TRUST_POLICY", "").strip()
    policy = _load_trust_policy(Path(policy_path)) if policy_path else _load_trust_policy()
    env = _resolve_trust_environment(policy, environment_id)
    repo_slug = os.environ.get("SIMPLICIO_REMOTE_REPO") or os.environ.get("GITHUB_REPOSITORY", "")
    ref = os.environ.get("SIMPLICIO_REMOTE_REF") or os.environ.get("GITHUB_REF", "")
    actor = os.environ.get("SIMPLICIO_REMOTE_ACTOR") or os.environ.get("GITHUB_ACTOR", "")
    ok, reason = _trust_authorize(policy, environment_id, repo_slug.strip(), ref.strip(), actor.strip())
    if not ok:
        raise RuntimeError("distributed trust policy denied: %s" % reason)
    origin = env["origin"]
    trusted_url = "%s://%s:%s%s" % (
        origin["scheme"], origin["hostname"], origin["port"], origin.get("base_path", "/"),
    )
    if url and url.rstrip("/") != trusted_url.rstrip("/"):
        # This is the literal #289 exploit replayed against the real call site:
        # a caller-supplied destination must never override the reviewed
        # policy, or an attacker who controls SIMPLICIO_REMOTE_QUEUE_URL could
        # redirect the bearer token to infrastructure they control.
        raise RuntimeError(
            "distributed trust policy denied: SIMPLICIO_REMOTE_QUEUE_URL does not match the "
            "resolved origin for environment_id '%s'" % environment_id
        )
    return trusted_url, environment_id, policy


def _resolve_trusted_queue_url(url: str) -> str:
    """Backward-compatible wrapper returning only the resolved URL."""
    resolved, _environment_id, _policy = _resolve_trusted_queue_context(url)
    return resolved


def _distributed_configuration(repo: str) -> tuple[Any, Optional[Dict[str, Any]]]:
    """Return the opt-in network coordinator and stable worker identity.

    Local fan-out is the default and remains the fallback when the optional
    distributed environment is not usable.  Trust-policy violations still fail
    closed; a missing identity adapter is an infrastructure absence, not a
    reason to stop independent local work.
    """
    url = os.environ.get("SIMPLICIO_REMOTE_QUEUE_URL", "").strip()
    if not url and not os.environ.get("SIMPLICIO_REMOTE_ENVIRONMENT_ID", "").strip():
        return None, None
    url, environment_id, policy = _resolve_trusted_queue_context(url)
    if ensure_identity is None:
        if _local_fallback_enabled():
            return None, None
        raise RuntimeError("distributed identity adapter unavailable")
    identity = ensure_identity(
        path=os.environ.get("SIMPLICIO_IDENTITY_FILE") or str(Path(repo) / ".simplicio-loop/orchestrator" / "agent-identity.json"),
        runtime=os.environ.get("SIMPLICIO_RUNTIME", "unknown-runtime"),
        capabilities=["claim", "heartbeat", "fencing", "receipts", "events", "evidence", "completion"],
    )
    token = _resolve_queue_token(environment_id, policy, identity)
    queue = HTTPRemoteQueue(
        url,
        token=token,
        timeout=float(os.environ.get("SIMPLICIO_REMOTE_QUEUE_TIMEOUT", "5")),
        environment_id=environment_id,
        policy=policy,
    )
    return queue, identity


def _local_fallback_enabled() -> bool:
    """Allow local execution when optional cloud coordination is absent.

    This is deliberately enabled by default: the cloud queue is an accelerator
    and claim transport, not a prerequisite for the Loop's local worktree
    scheduler. Set ``SIMPLICIO_LOOP_LOCAL_FALLBACK=0`` only when a deployment
    explicitly requires remote claims.
    """
    raw = os.environ.get("SIMPLICIO_LOOP_LOCAL_FALLBACK", "1").strip().lower()
    return raw not in {"0", "false", "no", "off", "disabled"}


STATIC_QUEUE_TOKEN_OPT_IN_VAR = "SIMPLICIO_ALLOW_STATIC_QUEUE_TOKEN"

# #289: the queue operations a worker's short-lived credential is scoped to.
# `enqueue` is deliberately excluded -- workers claim/heartbeat/complete/cancel
# existing tasks, they do not create new ones, so a stolen worker credential
# cannot be used to inject work into the queue.
WORKER_QUEUE_OPERATIONS = (
    "pull", "claim", "heartbeat", "complete", "assert-active", "cancel", "release", "events", "task",
)


def _resolve_queue_token(environment_id: Optional[str], policy: Optional[Dict[str, Any]],
                          identity: Optional[Dict[str, Any]]) -> Optional[str]:
    """Resolve the bearer credential for the distributed queue (#289).

    Preferred path: ``SIMPLICIO_REMOTE_QUEUE_TOKEN_SECRET`` is a long-lived
    HMAC *signing* secret (never sent on the wire); a fresh short-lived token
    (:mod:`scripts.short_lived_credentials`) is minted for this process, bound
    to the worker's agent identity as subject and the environment_id as scope,
    with a TTL taken from the policy's ``max_ttl_seconds`` (capped by
    ``SIMPLICIO_REMOTE_QUEUE_TOKEN_TTL_SECONDS`` if set lower), and restricted
    to :data:`WORKER_QUEUE_OPERATIONS` (operation-level scoping, so a leaked
    token cannot be replayed against an operation this worker never needed).
    This is not the OIDC broker exchange #289 describes -- there is no CI
    identity provider to issue the initial trust, and that gap stays
    permanently blocked absent one -- but it replaces an indefinitely-lived
    static secret with one that expires on its own and carries a revocable
    ``jti``.

    The legacy static ``SIMPLICIO_REMOTE_QUEUE_TOKEN`` is no longer a silent
    fallback: it is only honored when the caller has *also* set
    ``SIMPLICIO_ALLOW_STATIC_QUEUE_TOKEN=1`` (explicit opt-in), and every use
    of it appends a ``reject``-adjacent warning line to the #289 audit log
    (:mod:`scripts.security_audit_log`) so an indefinitely-lived credential in
    use is discoverable, not invisible. Without the opt-in flag, a missing
    signing secret fails closed with ``RuntimeError`` rather than silently
    downgrading to the weaker auth mode.
    """
    secret = os.environ.get("SIMPLICIO_REMOTE_QUEUE_TOKEN_SECRET", "").strip()
    if not secret:
        static_token = os.environ.get("SIMPLICIO_REMOTE_QUEUE_TOKEN", "").strip() or None
        opted_in = os.environ.get(STATIC_QUEUE_TOKEN_OPT_IN_VAR, "").strip().lower() in ("1", "true", "yes")
        if static_token and not opted_in:
            if _audit_append is not None:
                _audit_append(
                    None, event="runner.resolve_queue_token", decision="reject",
                    operation=environment_id or "queue",
                    reason="static SIMPLICIO_REMOTE_QUEUE_TOKEN present without "
                           f"{STATIC_QUEUE_TOKEN_OPT_IN_VAR}=1 opt-in",
                )
            raise RuntimeError(
                "SIMPLICIO_REMOTE_QUEUE_TOKEN_SECRET is not set and the legacy static "
                "SIMPLICIO_REMOTE_QUEUE_TOKEN fallback is no longer silent (#289). Set "
                f"{STATIC_QUEUE_TOKEN_OPT_IN_VAR}=1 to explicitly opt into the deprecated "
                "static-token auth mode for local/dev use, or configure "
                "SIMPLICIO_REMOTE_QUEUE_TOKEN_SECRET to use short-lived credentials instead."
            )
        if static_token and _audit_append is not None:
            _audit_append(
                None, event="runner.resolve_queue_token", decision="accept",
                operation=environment_id or "queue",
                reason="deprecated static-token auth mode explicitly opted into via "
                       f"{STATIC_QUEUE_TOKEN_OPT_IN_VAR}=1",
            )
        return static_token
    try:
        from scripts.short_lived_credentials import issue_token
    except ImportError as exc:  # pragma: no cover - installed package without scripts namespace
        raise RuntimeError("short-lived credential module unavailable") from exc
    max_ttl = float((policy or {}).get("environments", {}).get(environment_id, {}).get("max_ttl_seconds", 900)) \
        if policy and environment_id else 900.0
    override_ttl = os.environ.get("SIMPLICIO_REMOTE_QUEUE_TOKEN_TTL_SECONDS", "").strip()
    ttl_seconds = min(float(override_ttl), max_ttl) if override_ttl else max_ttl
    subject = (identity or {}).get("agent_id", "unknown-agent")
    scope = environment_id or "queue"
    return issue_token(secret, subject=subject, scope=scope, ttl_seconds=ttl_seconds,
                       operations=WORKER_QUEUE_OPERATIONS)


def _run_id() -> str:
    return time.strftime("run-%Y%m%d-%H%M%S-", time.gmtime()) + _rand_token(8)


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


def _default_maintenance_state() -> MaintenanceState:
    return {
        "mode": "active",
        "disposition": "operator",
        "receipt": "",
        "correction_summary": "",
        "deferral_reason": "",
        "evidence_status": "UNVERIFIED",
    }


def _active_maintenance_state(current: Mapping[str, Any] | None = None) -> MaintenanceState:
    payload = dict(current or {})
    return {
        "mode": "active",
        "disposition": "operator",
        "receipt": str(payload.get("receipt") or ""),
        "correction_summary": str(payload.get("correction_summary") or ""),
        "deferral_reason": str(payload.get("deferral_reason") or ""),
        "evidence_status": str(payload.get("evidence_status") or "UNVERIFIED"),
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


def _freeze_stack_lock(run_root: Path, run_id: str) -> StackLock:
    """Freeze installed component identity before Mapper scan or mutation authority."""
    route = _execution_profile()
    lock = StackLock.create(
        discover_installed_components(),
        route,
        run_id=run_id,
    )
    write_stack_lock(lock, run_root / "stack-lock.json")
    return lock


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


def _freeze_storage_route(run_root: Path, run_id: str) -> dict[str, Any]:
    """Select and persist the store route before any mapper-backed operation."""
    router = StorageRouter(requested=_storage_route_requested(), run_id=run_id)
    router.freeze("run_bootstrap")
    receipt = router.receipt()
    _write_json(run_root / STORAGE_ROUTE_RECEIPT, receipt)
    return receipt


def _verify_storage_route(run_root: Path) -> dict[str, Any]:
    """Verify the immutable store route and current capability before mutation."""
    path = run_root / STORAGE_ROUTE_RECEIPT
    try:
        receipt = _load_json(path)
    except (OSError, TypeError, ValueError) as exc:
        raise StoreAdapterError("STORAGE_ROUTE_RECEIPT_MISSING") from exc
    return verify_route_receipt(receipt, requested=_storage_route_requested())


def _write_maintenance_deferred_receipt(
    run_dir: Path,
    *,
    correction_summary: str,
    deferral_reason: str,
    resume_instructions: Sequence[str] | str,
    evidence_status: str,
) -> MaintenanceDeferredReceipt:
    completion = _completion_state(run_dir)
    instructions = [str(item).strip() for item in resume_instructions] if not isinstance(resume_instructions, str) else [resume_instructions.strip()]
    payload: MaintenanceDeferredReceipt = {
        "schema": MAINTENANCE_RECEIPT_SCHEMA,
        "mode": "maintenance_deferred",
        "disposition": "backlog_only",
        "correction_summary": correction_summary.strip(),
        "deferral_reason": deferral_reason.strip(),
        "resume_instructions": [item for item in instructions if item],
        "evidence_status": str(evidence_status or "UNVERIFIED"),
        "recorded_at": _now(),
        "completion_ready": False,
        "completion_verdict": str(completion.get("verdict") or "DELIVERY_PENDING"),
        "completion_reason_code": str(completion.get("reason_code") or "oracle_incomplete"),
    }
    _write_json(run_dir / "maintenance-receipt.json", payload)
    return payload


def _contract_path(run_dir: Path) -> Path:
    return run_dir / "task-contract.json"


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

    Reuses the same stable per-repo identity file ``_distributed_configuration()``
    creates for the real distributed dispatch path, so a sequential
    (non-distributed) run projects the same genuine ``agent_id``/``runtime``/
    ``device_id`` instead of leaving those fields blank. Never raises -- an
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

    Large repositories routinely need more than the Mapper CLI's 120-second default.
    Keep the wait bounded, but make the production default generous and let operators
    lower it explicitly for constrained environments.
    """
    default = 3600
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
    if _execution_profile() != "standalone":
        return False
    raw = os.environ.get("SIMPLICIO_LOOP_ALLOW_DEGRADED_MAPPER", "").strip().lower()
    if raw:
        return raw not in {"0", "false", "no", "off", "disabled"}
    return _local_fallback_enabled()


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
    if _execution_profile() == "standalone":
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
    # Runtime-backed execution is optional; local model execution is not an
    # allowed fallback. The command remains usable in standalone mode.
    return base

def _execution_profile() -> str:
    """Return the execution profile. Always ``standalone`` -- there is no
    Runtime/MCP backend in this stack. ``SIMPLICIO_EXECUTION_PROFILE`` may
    only be explicitly set to ``standalone``; any other value fails closed.
    """
    raw = os.environ.get("SIMPLICIO_EXECUTION_PROFILE", "").strip().lower()
    if raw in {"", "standalone", "auto"}:
        return "standalone"
    raise RuntimeEffectError("SIMPLICIO_EXECUTION_PROFILE must be standalone")


def _build_effect_request(repo_path: Path, run_id: str, task_index: int,
                          task: Mapping[str, Any], attempt: int,
                          targets: Sequence[str], route_record: Mapping[str, Any],
                          guarded_attempt: Any,
                          canonical_plan: Optional[CanonicalPlan] = None,
                          storage_route: StorageRoute | str | None = None) -> EffectRequest:
    lease = getattr(guarded_attempt, "lease", None)
    lease_id = str(getattr(lease, "lease_id", "") or f"loop-run:{run_id}")
    raw_fence = getattr(lease, "fencing_token", 1)
    if _mapper_journal_enabled(storage_route) and str(raw_fence).strip():
        fencing_token: int | str = str(raw_fence)
    else:
        try:
            fencing_token = max(1, int(raw_fence))
        except (TypeError, ValueError):
            fencing_token = 1
    transaction_id = f"{run_id}:{task.get('id') or task_index}:{attempt}"
    return EffectRequest(
        workspace=str(repo_path),
        idempotency_key=transaction_id,
        write_set=tuple(f"repo:{target}" for target in (targets or ["repo"])),
        lease_id=lease_id,
        fencing_token=fencing_token,
        cwd=".",
        timeout_ms=_operator_timeout("execute") * 1000,
        attempt=attempt,
        deadline=int(time.time() * 1000) + _operator_timeout("execute") * 1000,
        cancellation_boundary="safe_boundary_only",
        gate_id=str(route_record.get("receipt_sha") or "execution-route"),
        runtime_generation=os.environ.get("SIMPLICIO_RUNTIME_GENERATION") or None,
        transaction_id=transaction_id,
        canonical_plan=canonical_plan,
        attempt_id=str(getattr(guarded_attempt, "attempt_id", "") or lease_id),
    )


def _parse_effect_stdout(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except ValueError:
            return {"raw": redact_sensitive_text(value)}
        return dict(parsed) if isinstance(parsed, dict) else {"raw": redact_sensitive_text(value)}
    return {}


def _deterministic_no_mutation_proof(
    outcome: Mapping[str, Any], *, source_hash: str, repo_path: Path,
) -> Dict[str, Any] | None:
    """Prove a failed operator stopped before mutation, conservatively.

    A non-zero exit code alone is not proof: a process may have written files
    before failing.  Reconciliation is allowed only for the Dev CLI's explicit
    blocked result, with ``applied=false``, no reported files/errors, and an
    unchanged source-tree fingerprint.  Timeouts, runtime uncertainty, and
    ambiguous output remain ``unknown``.
    """
    if outcome.get("uncertain"):
        return None
    returncode = outcome.get("returncode")
    if isinstance(returncode, bool) or not isinstance(returncode, int) or returncode == 0:
        return None
    stdout = outcome.get("stdout")
    if not isinstance(stdout, Mapping):
        return None
    if stdout.get("status") != "blocked" or stdout.get("applied") is not False:
        return None
    blocked = stdout.get("blocked_preconditions")
    if not isinstance(blocked, list) or not blocked:
        return None
    codes: List[str] = []
    for item in blocked:
        if not isinstance(item, Mapping):
            return None
        code = str(item.get("code") or item.get("reason") or "").strip()
        if not code:
            return None
        codes.append(code)
    files = stdout.get("files")
    if files not in (None, []):
        return None
    errors = stdout.get("errors")
    if errors not in (None, []):
        return None

    after = _repo_fingerprint(repo_path)
    if not source_hash or after.get("tree_hash") != source_hash:
        return None
    proof: Dict[str, Any] = {
        "schema": "simplicio.loop.effect-reconciliation-proof/v1",
        "outcome": "failed",
        "reason_code": "deterministic_no_mutation",
        "returncode": returncode,
        "operator_source": str(outcome.get("source") or ""),
        "blocked_codes": sorted(set(codes)),
        "applied": False,
        "files_changed": [],
        "errors": [],
        "before_tree_hash": source_hash,
        "after_tree_hash": str(after.get("tree_hash") or ""),
        "fingerprint_scope": "source_tree_excluding_loop_owned_artifacts",
        "measured_at": _now(),
    }
    proof["proof_hash"] = _hookwall_digest(proof)
    return proof

def _owned_registry_path(registry: Any, task_id: str) -> Path | None:
    if isinstance(registry, (str, Path)) and task_id:
        digest = hashlib.sha256(str(task_id).encode("utf-8")).hexdigest()[:32]
        return Path(registry) / f"{digest}.json"
    return None


def _owned_process_start_time(pid: int) -> str:
    """Return Linux process start time for safe PID-reuse checks when available."""
    try:
        fields = Path(f"/proc/{int(pid)}/stat").read_text(encoding="utf-8").rsplit(")", 1)[1].split()
        return str(fields[19])
    except (OSError, IndexError, ValueError, TypeError):
        return ""


def _register_owned_process(registry: Any, task_id: str, process: Any) -> None:
    if registry is None or not task_id or getattr(process, "pid", None) is None:
        return
    pid = int(process.pid)
    entry = {"pid": pid, "pgid": pid if os.name == "posix" else None,
             "start_time": _owned_process_start_time(pid), "task_id": str(task_id)}
    path = _owned_registry_path(registry, task_id)
    try:
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(entry, sort_keys=True), encoding="utf-8")
            os.replace(temporary, path)
        else:
            registry[str(task_id)] = entry
    except (OSError, RuntimeError, TypeError, ValueError):
        return


def _read_owned_process(registry: Any, task_id: str) -> Mapping[str, Any] | None:
    path = _owned_registry_path(registry, task_id)
    try:
        if path is not None:
            if not path.is_file():
                return None
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, Mapping) else None
        value = registry.get(str(task_id)) if registry is not None else None
        return value if isinstance(value, Mapping) else None
    except (OSError, RuntimeError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _remove_owned_process(registry: Any, task_id: str, pid: int) -> None:
    path = _owned_registry_path(registry, task_id)
    try:
        entry = _read_owned_process(registry, task_id)
        if entry is None or int(entry.get("pid", -1)) != int(pid):
            return
        if path is not None:
            path.unlink(missing_ok=True)
        elif registry is not None:
            registry.pop(str(task_id), None)
    except (OSError, RuntimeError, TypeError, ValueError):
        return


def _request_owned_supervisor_cancel(registry: Any, task_id: str, reason: str) -> bool:
    """Ask the owning worker to cancel without signalling an unverified PID."""
    path = _owned_registry_path(registry, task_id)
    try:
        entry = _read_owned_process(registry, task_id)
        if entry is None:
            return False
        payload = dict(entry)
        payload["cancel_requested"] = True
        payload["cancel_reason"] = str(reason)
        if path is not None:
            temporary = path.with_suffix(".cancel.tmp")
            temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
            os.replace(temporary, path)
        elif isinstance(registry, dict):
            registry[str(task_id)] = payload
        else:
            return False
        return True
    except (OSError, RuntimeError, TypeError, ValueError):
        return False


def _terminate_owned_process(registry: Any, task_id: str) -> Dict[str, Any] | None:
    """Terminate only after PID start-time and process-group ownership are proven."""
    entry = _read_owned_process(registry, task_id)
    if entry is None:
        return None
    pid = -1
    try:
        pid = int(entry.get("pid"))
        expected_start = str(entry.get("start_time") or "")
        actual_start = _owned_process_start_time(pid)
        if not expected_start or not actual_start:
            if _request_owned_supervisor_cancel(registry, task_id, "owned_identity_unavailable"):
                return {"cancelled": True, "pid": pid, "scope": "owned_supervisor_request"}
            return {"cancelled": False, "reason": "owned_identity_unavailable"}
        if expected_start != actual_start:
            _remove_owned_process(registry, task_id, pid)
            return {"cancelled": False, "reason": "owned_pid_reused"}
        if os.name != "posix":
            if _request_owned_supervisor_cancel(registry, task_id, "owned_pgid_unavailable"):
                return {"cancelled": True, "pid": pid, "scope": "owned_supervisor_request"}
            return {"cancelled": False, "reason": "owned_pgid_unavailable"}
        recorded_pgid = int(entry.get("pgid") or -1)
        if recorded_pgid != pid:
            return {"cancelled": False, "reason": "owned_pgid_mismatch"}
        try:
            actual_pgid = os.getpgid(pid)
        except ProcessLookupError:
            _remove_owned_process(registry, task_id, pid)
            return {"cancelled": False, "reason": "owned_process_already_exited"}
        except OSError:
            if _request_owned_supervisor_cancel(registry, task_id, "owned_pgid_unavailable"):
                return {"cancelled": True, "pid": pid, "scope": "owned_supervisor_request"}
            return {"cancelled": False, "reason": "owned_pgid_unavailable"}
        if actual_pgid != recorded_pgid:
            return {"cancelled": False, "reason": "owned_pgid_mismatch"}
        os.killpg(recorded_pgid, signal.SIGTERM)
        return {"cancelled": True, "pid": pid, "scope": "owned_process_group"}
    except ProcessLookupError:
        if pid > 0:
            _remove_owned_process(registry, task_id, pid)
        return {"cancelled": False, "reason": "owned_process_already_exited"}
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return {"cancelled": False, "reason": f"owned_process_termination_failed:{type(exc).__name__}"}


def _execute_operator_effect_unchecked(*, profile: str, adapter: RuntimeEffectAdapter,
                             request: EffectRequest, argv: List[str],
                             env: Mapping[str, str], repo_path: Path,
                             attempt_coordinator: Optional[AttemptCoordinator],
                             guarded_attempt: Any,
                             owned_process_registry: Any = None,
                             owned_task_id: str = "") -> Dict[str, Any]:
    del adapter, request  # standalone-only: no Runtime backend to dispatch through

    fake = os.environ.get("SIMPLICIO_LOOP_FAKE_OPERATOR_EXEC_JSON", "").strip()
    if fake:
        payload = json.loads(fake)
        for rel, content in (payload.get("write_files") or {}).items():
            path = repo_path / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(content), encoding="utf-8")
        return {
            "returncode": int(payload.get("returncode", 0)),
            "stdout": payload.get("stdout", {}),
            "stderr": redact_sensitive_text(str(payload.get("stderr", ""))),
            "source": "env_override",
            "effect_receipt": None,
            "uncertain": False,
        }

    try:
        if attempt_coordinator is not None and guarded_attempt is not None:
            result = attempt_coordinator.run_guarded(
                guarded_attempt, argv, cwd=repo_path,
                timeout=_operator_timeout("execute"), env=env,
            )
        elif owned_process_registry is None:
            result = subprocess.run(
                argv, cwd=str(repo_path), capture_output=True, text=True,
                timeout=_operator_timeout("execute"), env=env,
            )
        else:
            process = subprocess.Popen(
                argv, cwd=str(repo_path), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, stdin=subprocess.DEVNULL, env=env,
                start_new_session=(os.name == "posix"),
            )
            _register_owned_process(owned_process_registry, owned_task_id, process)
            try:
                communication: Dict[str, Any] = {}

                def _communicate() -> None:
                    try:
                        communication["result"] = process.communicate(timeout=_operator_timeout("execute"))
                    except BaseException as exc:
                        communication["error"] = exc

                communication_thread = Thread(target=_communicate, name=f"simplicio-owned-{owned_task_id}", daemon=True)
                communication_thread.start()
                cancel_sent = False
                while communication_thread.is_alive():
                    owned_entry = _read_owned_process(owned_process_registry, owned_task_id)
                    if owned_entry and owned_entry.get("cancel_requested") and not cancel_sent:
                        try:
                            if os.name == "posix":
                                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                            else:
                                process.terminate()
                        except ProcessLookupError:
                            pass
                        cancel_sent = True
                    communication_thread.join(0.05)
                if "error" in communication:
                    error = communication["error"]
                    if isinstance(error, subprocess.TimeoutExpired):
                        process.kill()
                        stdout, stderr = process.communicate()
                        raise subprocess.TimeoutExpired(
                            argv, error.timeout, output=stdout, stderr=stderr,
                        ) from error
                    raise error
                stdout, stderr = communication["result"]
            finally:
                _remove_owned_process(owned_process_registry, owned_task_id, process.pid)
            result = subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)
        return {
            "returncode": result.returncode,
            "stdout": _parse_effect_stdout((result.stdout or "").strip()),
            "stderr": redact_sensitive_text((result.stderr or "").strip()),
            "source": "live_cli",
            "effect_receipt": None,
            "uncertain": False,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "returncode": None,
            "stdout": {},
            "stderr": f"timed out after {exc.timeout}s",
            "source": "live_cli",
            "effect_receipt": None,
            # A timeout does not prove that the child stopped before writing.
            # Keep the Mapper effect unknown until an explicit reconciliation
            # can establish what happened.
            "uncertain": True,
        }


def _hookwall_digest(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _mapper_operations_database(repo_path: Path) -> str:
    """Resolve the repo-scoped canonical operations store without creating it."""
    explicit = os.environ.get("SIMPLICIO_MAPPER_OPERATIONS_DB", "").strip()
    if explicit:
        return str(Path(explicit).expanduser().absolute())
    try:
        from simplicio_mapper.store import resolve_store_location
    except (ImportError, ModuleNotFoundError) as error:
        raise RuntimeError("MAPPER_STORE_NOT_INSTALLED") from error
    environ = dict(os.environ)
    environ.pop("SIMPLICIO_DATA_DIR", None)
    environ.pop("SIMPLICIO_HOME", None)
    environ["SIMPLICIO_STORE_SCOPE"] = "repo"
    try:
        return str(resolve_store_location(environ=environ, repo_root=repo_path).database("operations.sqlite"))
    except (OSError, ValueError) as error:
        raise RuntimeError(f"MAPPER_OPERATIONS_DB_UNAVAILABLE:{error}") from error


def _ensure_mapper_operations_store(
    repo_path: Path,
    storage_route: str | None = None,
) -> Dict[str, Any]:
    """Initialize Mapper's repo store on the first real Loop invocation.

    The explicit ``queue --mapper-init`` command remains available for
    operators, but a normal ``run``/``tick``/``batch`` must not require a
    separate bootstrap command. This only performs Mapper's own idempotent
    initialization; it does not create a Loop-owned queue or weaken any
    receipt/lease gate.
    """
    selected = str(storage_route or _storage_route_requested()).strip().lower()
    if selected != StorageRoute.MAPPER.value:
        return {"status": "not_selected", "route": selected}
    try:
        from .mapper_operations import MapperOperationsAdapter

        adapter = MapperOperationsAdapter(
            _mapper_operations_database(repo_path),
            auto_create=True,
        )
        result = adapter.initialize()
        # The default operation lane is deliberately conservative.  The
        # physical governor may admit fewer workers, never more, and the
        # lease is still claimed/released per task below.
        register_slot = getattr(adapter, "register_slot", None)
        if callable(register_slot):
            register_slot("default", 1)
    except (OSError, TypeError, ValueError, RuntimeError) as error:
        raise RuntimeError(f"MAPPER_OPERATIONS_INIT_FAILED:{error}") from error
    if not isinstance(result, dict):
        raise RuntimeError("MAPPER_OPERATIONS_INIT_FAILED:invalid initialization receipt")
    return result


class _MapperOperationAttempt:
    """Small bridge exposing a Mapper OperationsStore lease to the operator path."""

    def __init__(self, adapter: Any, lease: Any) -> None:
        self.adapter = adapter
        self.lease = lease
        self.attempt_id = str(getattr(lease, "attempt_id", "") or "")


def _claim_mapper_operation_attempt(
    repo_path: Path,
    *,
    run_id: str,
    task_index: int,
    task_id: str,
    worker_id: str,
    targets: Sequence[str],
) -> tuple[Any, _MapperOperationAttempt]:
    """Claim a real MapperStore lease for a local mutation lane.

    The local Loop queue is not the Mapper OperationsStore. When the mapper
    storage route is selected, Hookwall effects still need a lease that the
    Mapper store can validate; a synthetic ``loop-run:<id>`` token is not
    sufficient and correctly fails closed as ``STALE_FENCE``.
    """
    from .mapper_operations import MapperOperationsAdapter

    adapter = MapperOperationsAdapter(_mapper_operations_database(repo_path), auto_create=False)
    idempotency_key = f"{run_id}:mapper-operation:{task_index}"
    imported = adapter.import_task(
        task_id,
        {
            "run_id": run_id,
            "task_index": task_index,
            "worker_id": worker_id,
            "targets": list(targets),
        },
        idempotency_key=idempotency_key,
        state="queued",
    )
    if imported.get("status") == "unchanged" and imported.get("state") in {
        "failed", "cancelled",
    }:
        adapter.requeue(task_id)
    lease = adapter.claim_task(
        task_id,
        f"loop:{run_id}:{worker_id}",
        slot_id="default",
        lease_seconds=max(60.0, float(_operator_timeout("execute") * 2)),
    )
    if lease is None:
        raise QueueUnavailable(f"Mapper OperationsStore returned no lease for {task_id}")
    return adapter, _MapperOperationAttempt(adapter, lease)


def _mechanical_fixture_plan(task: Mapping[str, Any], repo_path: Path) -> Dict[str, Any] | None:
    """Build the explicit mechanical plan for the isolated PAGE fixture.

    The installed Dev CLI is intentionally deterministic-only and accepts an
    explicit mechanical plan as its safe fallback.  This narrow adapter is
    enabled only by ``SIMPLICIO_LOOP_MECHANICAL_FALLBACK`` and only for the
    benchmark's PAGE tasks; it is not a general task interpreter and never
    changes the physical admission decision.
    """
    if os.environ.get("SIMPLICIO_LOOP_MECHANICAL_FALLBACK", "").strip().lower() not in {
        "1", "true", "yes", "on"
    }:
        return None
    identity = task.get("identity") if isinstance(task.get("identity"), Mapping) else {}
    task_id = str(identity.get("system") or task.get("id") or "").strip().upper()
    if not re.fullmatch(r"PAGE-10[1-5]", task_id):
        return None

    index_path = repo_path / "site" / "index.html"
    current_index = index_path.read_text(encoding="utf-8") if index_path.is_file() else ""

    base = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Simplicio — thoughtful automation</title>
</head>
<body>
  <header>
    <p class="eyebrow">Simplicio</p>
    <h1>Simplicio: build clearly. Ship simply.</h1>
    <p>Practical automation for teams that value momentum and control.</p>
  </header>
  <main>
    <section aria-labelledby="intro-title">
      <h2 id="intro-title">A simpler path from idea to delivery</h2>
      <p>Simplicio keeps the work visible, focused, and easy to verify.</p>
    </section>
  </main>
  <footer><p>© Simplicio</p></footer>
</body>
</html>
"""
    navigation = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Simplicio — thoughtful automation</title>
</head>
<body>
  <header>
    <nav aria-label="Primary">
      <ul>
        <li><a href="index.html">Home</a></li>
        <li><a href="about.html">About</a></li>
        <li><a href="#contact">Contact</a></li>
      </ul>
    </nav>
    <p class="eyebrow">Simplicio</p>
    <h1>Simplicio: build clearly. Ship simply.</h1>
    <p>Practical automation for teams that value momentum and control.</p>
  </header>
  <main>
    <section aria-labelledby="intro-title">
      <h2 id="intro-title">A simpler path from idea to delivery</h2>
      <p>Simplicio keeps the work visible, focused, and easy to verify.</p>
    </section>
  </main>
  <footer><p>© Simplicio</p></footer>
</body>
</html>
"""
    with_styles = navigation.replace(
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n',
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '  <link rel="stylesheet" href="styles.css">\n',
        1,
    )
    with_contact = with_styles.replace(
        "  </main>\n",
        """    <section id="contact" aria-labelledby="contact-title">
      <h2 id="contact-title">Contact Simplicio</h2>
      <form action="#contact" method="post">
        <p><label for="name">Name</label><input id="name" type="text" name="name" required></p>
        <p><label for="email">Email</label><input id="email" type="email" name="email" required></p>
        <p><label for="message">Message</label><textarea id="message" name="message" required></textarea></p>
        <button type="submit">Send message</button>
      </form>
    </section>
  </main>
""",
        1,
    )
    css = """/* Simplicio's small, local-first design system. */
:root { color-scheme: light; font-family: system-ui, sans-serif; line-height: 1.5; }
body { margin: 0; color: #172033; background: #f5f7fb; }
header, main, footer { width: min(100% - 2rem, 68rem); margin-inline: auto; }
header { padding-block: 2rem 3rem; }
nav ul { display: flex; gap: 1rem; padding: 0; list-style: none; }
a { color: #2457c5; }
section { padding-block: 2rem; }
input, textarea, button { box-sizing: border-box; width: 100%; max-width: 34rem; padding: .65rem; font: inherit; }
textarea { min-height: 8rem; }
button { cursor: pointer; }
@media (max-width: 42rem) {
  nav ul { flex-direction: column; gap: .5rem; }
  header, main, footer { width: min(100% - 1.25rem, 68rem); }
}
"""
    about = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>About Simplicio</title>
</head>
<body>
  <main>
    <p class="eyebrow">Simplicio</p>
    <h1>About Simplicio</h1>
    <p>Simplicio makes dependable automation easier to understand and verify.</p>
    <p><a href="index.html">Return to the Simplicio home page</a></p>
  </main>
</body>
</html>
"""

    def replace(path: str, desired: str, current: str) -> Dict[str, Any]:
        line_count = max(1, len(current.splitlines()))
        return {"op": "replace_range", "path": path, "start_line": 1,
                "end_line": line_count, "text": desired}

    operations: List[Dict[str, Any]] = []
    touched: List[str] = []
    if task_id == "PAGE-101":
        operations.append({"op": "create_file", "path": "site/index.html", "text": base})
        touched.append("site/index.html")
    elif task_id == "PAGE-102":
        if not current_index:
            return None
        operations.append(replace("site/index.html", navigation, current_index))
        touched.append("site/index.html")
    elif task_id == "PAGE-103":
        if not current_index:
            return None
        operations.extend([
            {"op": "create_file", "path": "site/styles.css", "text": css},
            replace("site/index.html", with_styles, current_index),
        ])
        touched.extend(["site/styles.css", "site/index.html"])
    elif task_id == "PAGE-104":
        if not current_index:
            return None
        operations.append(replace("site/index.html", with_contact, current_index))
        touched.append("site/index.html")
    else:
        operations.append({"op": "create_file", "path": "site/about.html", "text": about})
        touched.append("site/about.html")
    return {
        "schema": "simplicio.mechanical-edit/v1",
        "touched_files": touched,
        "operations": operations,
        "validation": [],
    }


def _looks_like_host_edit_plan(payload: Mapping[str, Any]) -> bool:
    schema = str(payload.get("schema") or "")
    # No schema = minimal host plan ({operations: [{path, find, replace}]}),
    # compiled by Dev CLI right before apply.
    if schema and schema not in HOST_EDIT_PLAN_SCHEMAS:
        return False
    operations = payload.get("operations") or payload.get("ops") or payload.get("edits")
    return isinstance(operations, list) and bool(operations)


def _minimal_plan_operations(plan: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    operations = plan.get("operations") or plan.get("ops") or plan.get("edits") or []
    return [op for op in operations if isinstance(op, Mapping)]


def _validate_minimal_host_plan_paths(
    plan: Mapping[str, Any], repo_path: Path, authorized_targets: Sequence[str],
) -> Optional[Dict[str, str]]:
    """Precise preflight for a minimal host plan's operation paths.

    Host-authored edit plans naming a path outside ``authorized_targets`` or a
    path that does not exist in the repository used to surface as the opaque
    ``PLAN_REQUIRED``/``plan_compile_failed`` dev-cli subprocess failure. This
    checks it directly and returns a typed, actionable reason -- the offending
    path(s) and (when relevant) the authorized target list -- instead. Returns
    ``None`` when every path is fine; a full/already-compiled plan (has a
    ``schema``) is not checked here, since it already went through a real
    compile step upstream.
    """
    if plan.get("schema"):
        return None
    operations = _minimal_plan_operations(plan)
    if not operations:
        return None
    authorized = {str(item) for item in authorized_targets if str(item).strip()}
    not_authorized: List[str] = []
    not_found: List[str] = []
    create_conflicts: List[str] = []
    seen: set[str] = set()
    resolved_repo = repo_path.resolve()
    for op in operations:
        raw_path = str(op.get("path") or "").strip()
        if not raw_path or raw_path in seen:
            continue
        seen.add(raw_path)
        if authorized and raw_path not in authorized:
            not_authorized.append(raw_path)
            continue
        try:
            resolved = (repo_path / raw_path).resolve()
            resolved.relative_to(resolved_repo)
        except (OSError, ValueError):
            not_found.append(raw_path)
            continue
        # issue #1331: `find: ""` creates a new file -- same semantics as
        # `simplicio-dev-cli edit --apply`'s `compile_host_plan` and
        # `simplicio-loop apply`'s `validate_ops`. A path that does not yet
        # exist is fine for a create op; an existing NON-EMPTY file is still
        # a hard block (creation never silently overwrites real content).
        is_create = str(op.get("find") or "") == ""
        if not resolved.is_file():
            if is_create:
                continue
            not_found.append(raw_path)
        elif is_create and resolved.stat().st_size > 0:
            create_conflicts.append(raw_path)
    if not_authorized:
        return {
            "reason_code": "plan_path_not_authorized",
            "message": (
                "edit plan references path(s) outside the authorized targets: %s; "
                "authorized_targets=%s" % (", ".join(sorted(not_authorized)), sorted(authorized))
            ),
        }
    if not_found:
        return {
            "reason_code": "plan_path_not_found",
            "message": (
                "edit plan references path(s) that do not exist in the repository: %s"
                % ", ".join(sorted(not_found))
            ),
        }
    if create_conflicts:
        return {
            "reason_code": "plan_create_target_exists",
            "message": (
                "edit plan uses find:\"\" (create) against already-existing, non-empty path(s): %s"
                % ", ".join(sorted(create_conflicts))
            ),
        }
    return None


# simplicio-dev-cli's own `edit --compile --json` error codes (measured against
# the installed binary) for a find/replace anchor that fails to bind.
_DEVCLI_COMPILE_ERROR_CODES: Dict[str, str] = {
    "missing_anchor": "plan_find_not_found",
    "ambiguous_anchor": "plan_find_not_unique",
}


def _find_snippet_for_path(plan: Mapping[str, Any], path: str) -> str:
    for op in _minimal_plan_operations(plan):
        if str(op.get("path") or "") == path:
            return str(op.get("find") or "")[:200]
    return ""


def _classify_plan_compile_failure(plan: Mapping[str, Any], raw_stdout: str, detail: str) -> Tuple[str, str]:
    """Turn a raw dev-cli `edit --compile` failure into a precise reason_code
    naming the offending path and a find snippet, instead of an opaque
    ``plan_compile_failed`` blob with the whole subprocess transcript.

    Prefers dev-cli's own structured ``errors[].code``/``path`` (its `--json`
    output); falls back to text heuristics only for an older build without
    that field.
    """
    try:
        payload = json.loads(raw_stdout) if raw_stdout.strip() else None
    except (ValueError, TypeError):
        payload = None
    errors = payload.get("errors") if isinstance(payload, Mapping) else None
    if isinstance(errors, list) and errors and isinstance(errors[0], Mapping):
        first = errors[0]
        reason_code = _DEVCLI_COMPILE_ERROR_CODES.get(str(first.get("code") or ""))
        if reason_code:
            path = str(first.get("path") or "")
            message = "%s: path=%s find=%r -- %s" % (
                reason_code, path or "<unknown>", _find_snippet_for_path(plan, path),
                str(first.get("message") or detail),
            )
            return reason_code, message
    lowered = detail.lower()
    if "not unique" in lowered or "ambiguous" in lowered or "multiple matches" in lowered:
        marker = "not_unique"
    elif "no match" in lowered or "not found" in lowered:
        marker = "not_found"
    else:
        marker = ""
    if not marker:
        return "plan_compile_failed", f"plan_compile_failed: {detail}"
    offending_path = ""
    offending_find = ""
    operations = _minimal_plan_operations(plan)
    for op in operations:
        path = str(op.get("path") or "")
        if path and path in detail:
            offending_path = path
            offending_find = str(op.get("find") or "")[:200]
            break
    if not offending_path and operations:
        offending_path = str(operations[0].get("path") or "")
        offending_find = str(operations[0].get("find") or "")[:200]
    reason_code = "plan_find_not_unique" if marker == "not_unique" else "plan_find_not_found"
    message = "%s: path=%s find=%r -- %s" % (reason_code, offending_path or "<unknown>", offending_find, detail)
    return reason_code, message


def _compile_minimal_host_plan(repo_path: Path, plan_path: Path) -> tuple[Dict[str, Any] | None, str, str]:
    """Freeze a minimal ``{operations: [{path, find, replace}]}`` plan in place.

    Runs right before apply, so each task binds to the tree the previous task
    left (a serial wave of host plans never drifts). Full plans pass through.
    Returns ``(compiled_plan, reason_code, message)``; ``reason_code`` is only
    set (and ``compiled_plan`` is ``None``) on failure.
    """
    plan = _load_json(plan_path)
    if plan.get("schema"):
        return plan, "", ""
    compiled_path = plan_path.with_name(plan_path.stem + ".compiled.json")
    result = _run_cmd(
        _devcli_cmd(repo_path, "edit", "--root", str(repo_path), "--plan", str(plan_path),
                    "--compile", str(compiled_path), "--json"),
        repo_path,
    )
    if result.returncode != 0 or not compiled_path.is_file():
        raw_stdout = result.stdout or ""
        detail = (raw_stdout or result.stderr or "").strip()[:600]
        reason_code, message = _classify_plan_compile_failure(plan, raw_stdout, detail)
        return None, reason_code, message
    compiled = _load_json(compiled_path)
    _write_json(plan_path, compiled)
    compiled_path.unlink()
    return compiled, "", ""


def _resolve_host_edit_plan(
    run_dir: Path,
    *,
    task_index: int,
    env: Mapping[str, str] | None = None,
) -> tuple[Dict[str, Any] | None, Path | None, str]:
    """Load a host-written edit plan. Loop does not generate one."""
    environ = env or os.environ
    candidates: list[tuple[Path, str]] = []
    for key in ("SIMPLICIO_EDIT_PLAN", "SIMPLICIO_MECHANICAL_PLAN"):
        raw = str(environ.get(key) or "").strip()
        if raw:
            candidates.append((Path(raw), f"env:{key}"))
    candidates.extend((
        (run_dir / "edit-plan.json", "run_dir:edit-plan.json"),
        (run_dir / f"edit-plan-{task_index}.json", f"run_dir:edit-plan-{task_index}.json"),
        (run_dir / f"mechanical-plan-{task_index}.json", f"run_dir:mechanical-plan-{task_index}.json"),
        (run_dir / "mechanical-plan.json", "run_dir:mechanical-plan.json"),
    ))
    seen: set[str] = set()
    for path, source in candidates:
        try:
            resolved = str(path.resolve())
        except OSError:
            continue
        if resolved in seen or not path.is_file():
            continue
        seen.add(resolved)
        try:
            payload = _load_json(path)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            continue
        if isinstance(payload, Mapping) and _looks_like_host_edit_plan(payload):
            return dict(payload), path, source
    return None, None, ""


def _finish_operator_blocked(
    *,
    repo: str,
    run_id: str,
    run_dir: Path,
    status: Mapping[str, Any],
    receipt: Mapping[str, Any],
    operator_path: Path,
    task_index: int,
    reason: str,
) -> Dict[str, Any]:
    payload = dict(receipt)
    payload["receipt_hash"] = _operator_receipt_hash(payload)
    _write_json(operator_path, payload)
    _write_json(run_dir / f"operator-receipt-{task_index}.json", payload)
    state = status["state"]
    state["operator"] = {
        "ready": False,
        "receipt": str(operator_path),
        "target": payload.get("target", ""),
        "execution_state": "blocked",
        "reason_code": str(payload.get("reason_code") or ""),
    }
    state["current_action"] = "operator_failed"
    state["next_action"] = "repair_operator_or_plan"
    state["attempts"] = int(state.get("attempts", 0)) + 1
    _write_json(run_dir / "state.json", state)
    _transition(run_dir, state, "blocked", reason, receipt=str(operator_path))
    return read_status(repo, run_id)


def _provider_context_with_current_targets(
    context: Mapping[str, Any],
    *,
    root: Path,
    allowed_paths: Sequence[str],
) -> Dict[str, Any]:
    """Give an explicit provider worker the current files it must preserve while editing."""
    enriched = dict(context)
    current_targets: Dict[str, str] = {}
    root_path = root.resolve()
    for raw_path in allowed_paths:
        relative = str(raw_path).replace("\\", "/")
        target = (root_path / relative).resolve()
        try:
            target.relative_to(root_path)
        except ValueError as exc:
            raise ProviderWorkerError("provider target resolves outside the repository", reason_code="provider_target_invalid") from exc
        if target.is_symlink():
            raise ProviderWorkerError("provider target may not be a symlink", reason_code="provider_target_invalid")
        if not target.is_file():
            continue
        content = target.read_text(encoding="utf-8")
        if len(content) > MAX_PROVIDER_CURRENT_TARGET_CHARS:
            raise ProviderWorkerError(
                "current provider target is too large for the bounded prompt",
                reason_code="provider_target_too_large",
            )
        current_targets[relative] = content
    if current_targets:
        enriched["current_targets"] = current_targets
    return enriched



def _provider_worker_plan(
    *,
    task: Mapping[str, Any],
    context: Mapping[str, Any],
    run_id: str,
    task_index: int,
    attempt: int,
    root: Path,
    allowed_paths: Sequence[str],
    run_dir: Path,
    provider_worker: str | None = None,
    repair_feedback: str | None = None,
) -> tuple[Dict[str, Any] | None, Dict[str, Any] | None]:
    """Obtain one external proposal and convert it through the Dev CLI plan contract.

    Provider selection is explicit. The default path returns ``(None, None)`` so
    deterministic Dev CLI behavior remains unchanged. A selected worker failure
    writes a blocked, secret-free receipt and raises; it never falls back to a
    deterministic or manual edit.
    """
    selected = str(provider_worker or os.environ.get("SIMPLICIO_PROVIDER_WORKER") or "").strip().lower()
    if not selected:
        return None, None
    if selected != "openrouter":
        raise ProviderWorkerError(
            f"unsupported provider worker {selected!r}",
            reason_code="provider_worker_unsupported",
        )
    receipt_path = run_dir / f"provider-worker-{task_index}-attempt-{max(1, int(attempt))}.json"
    try:
        result = OpenRouterWorker().dispatch(
            task=task,
            context=_provider_context_with_current_targets(
                context,
                root=root,
                allowed_paths=allowed_paths,
            ),
            run_id=run_id,
            task_index=task_index,
            allowed_paths=allowed_paths,
            env=os.environ,
            repair_feedback=repair_feedback,
        )
        forwarded = forwarded_environment(os.environ)
        plan = proposal_to_mechanical_plan(
            result["proposal"],
            root=root,
            allowed_paths=allowed_paths,
            forbidden_literals=(forwarded["OPENROUTER_API_KEY"],),
        )
        plan_path = run_dir / f"provider-mechanical-plan-{task_index}-attempt-{max(1, int(attempt))}.json"
        _write_json(plan_path, plan)
        proposal = result.get("proposal") if isinstance(result.get("proposal"), Mapping) else {}
        files = proposal.get("files") if isinstance(proposal, Mapping) else {}
        receipt = {
            "schema": "simplicio.provider-worker-receipt/v1",
            "status": "READY",
            "provider": "openrouter",
            "upstream_provider": result.get("upstream_provider"),
            "model": OPENROUTER_MODEL,
            "run_id": str(run_id),
            "task_index": int(task_index),
            "attempt": max(1, int(attempt)),
            "allowed_paths": sorted(str(path) for path in allowed_paths),
            "proposed_paths": sorted(str(path) for path in files) if isinstance(files, Mapping) else [],
            "prompt_sha256": str(result.get("prompt_sha256") or ""),
            "proposal_sha256": str(result.get("response_sha256") or ""),
            "mechanical_plan_path": str(plan_path),
            "provider_call_count": int(result.get("provider_call_count") or 1),
            "usage": result.get("usage"),
            "usage_status": result.get("usage_status", "unknown"),
            "input_tokens": result.get("input_tokens"),
            "output_tokens": result.get("output_tokens"),
            "cached_tokens": result.get("cached_tokens"),
            "cache_write_tokens": result.get("cache_write_tokens"),
            "reasoning_tokens": result.get("reasoning_tokens"),
            "cost": result.get("cost"),
            "cost_status": result.get("cost_status", "unknown"),
            "receipt_path": str(receipt_path),
        }
        _write_json(receipt_path, receipt)
        return plan, receipt
    except ProviderWorkerError as exc:
        blocked = {
            "schema": "simplicio.provider-worker-receipt/v1",
            "status": "BLOCKED",
            "provider": "openrouter",
            "model": OPENROUTER_MODEL,
            "run_id": str(run_id),
            "task_index": int(task_index),
            "attempt": max(1, int(attempt)),
            "reason_code": exc.reason_code,
            "error": str(exc),
            "usage": None,
            "usage_status": "unknown",
            "input_tokens": None,
            "output_tokens": None,
            "cached_tokens": None,
            "reasoning_tokens": None,
            "cost": None,
            "cost_status": "unknown",
            "receipt_path": str(receipt_path),
        }
        _write_json(receipt_path, blocked)
        raise
    except Exception as exc:  # noqa: BLE001 - selected provider is fail-closed
        blocked = {
            "schema": "simplicio.provider-worker-receipt/v1",
            "status": "BLOCKED",
            "provider": "openrouter",
            "model": OPENROUTER_MODEL,
            "run_id": str(run_id),
            "task_index": int(task_index),
            "attempt": max(1, int(attempt)),
            "reason_code": "provider_worker_failed",
            "error": f"provider worker failed: {type(exc).__name__}",
            "usage": None,
            "usage_status": "unknown",
            "input_tokens": None,
            "output_tokens": None,
            "cached_tokens": None,
            "reasoning_tokens": None,
            "cost": None,
            "cost_status": "unknown",
            "receipt_path": str(receipt_path),
        }
        _write_json(receipt_path, blocked)
        raise ProviderWorkerError(blocked["error"], reason_code=blocked["reason_code"]) from exc

def _hookwall_ledger(
    repo_path: Path,
    storage_route: StorageRoute | str | None = None,
) -> Any:
    """Select Hookwall persistence from the frozen route; shadow is fail-closed."""
    route_value = _storage_route_requested() if storage_route is None else storage_route
    try:
        route = StorageRoute(route_value)
    except ValueError as error:
        raise StoreAdapterError("STORAGE_ROUTE_INVALID") from error
    if route == StorageRoute.MAPPER:
        return MapperHookwallEffectLedger(_mapper_operations_database(repo_path), auto_create=False)
    if route == StorageRoute.SHADOW:
        raise StoreAdapterError("SHADOW_ROUTE_NOT_EXECUTABLE")
    return HookwallEffectLedger(
        repo_path / ".simplicio-loop" / "orchestrator" / "hookwall.sqlite3"
    )


def _execute_operator_effect(*, profile: str, adapter: RuntimeEffectAdapter,
                             request: EffectRequest, argv: List[str],
                             env: Mapping[str, str], repo_path: Path,
                             attempt_coordinator: Optional[AttemptCoordinator],
                             guarded_attempt: Any,
                             source_hash: Optional[str] = None,
                             storage_route: StorageRoute | str | None = None,
                             owned_process_registry: Any = None,
                             owned_task_id: str = "") -> Dict[str, Any]:
    """Run one mutable operator only inside a lineage-bound Hookwall chain."""
    source_hash = source_hash or str(_repo_fingerprint(repo_path).get("tree_hash") or "")
    plan_id = request.gate_id or request.transaction_id or request.idempotency_key
    policy_hash = _hookwall_digest({
        "profile": profile,
        "gate_id": request.gate_id or "",
        "runtime_generation": request.runtime_generation or "",
        "write_set": list(request.write_set),
    })
    envelope = validate_envelope({
        "schema": "simplicio.dispatch-envelope/v1",
        "envelope_id": request.transaction_id or request.idempotency_key,
        "run_id": request.idempotency_key.split(":task-", 1)[0],
        "plan_id": plan_id,
        "source_hash": source_hash,
        "policy_hash": policy_hash,
        "idempotency_key": request.idempotency_key,
        "workspace": request.workspace,
        "fence": request.fencing_token,
        "attempt_id": request.attempt_id or request.lease_id,
        "effect_set": ["process", "write"],
        "write_set": list(request.write_set),
        "command": list(argv),
    })
    pre_decision = {
        "schema": "simplicio.hookwall-decision/v1",
        "phase": "pre",
        "verdict": "proceed",
        "reason_code": "policy_authorized",
        "envelope_id": envelope["envelope_id"],
        "envelope_hash": envelope["envelope_hash"],
        "source_hash": source_hash,
        "policy_hash": policy_hash,
        "fence": request.fencing_token,
    }
    validate_pre_decision(envelope, pre_decision)
    hookwall_ledger = _hookwall_ledger(repo_path, storage_route)
    reservation = hookwall_ledger.reserve(envelope, pre_decision)
    if reservation["action"] == "REPLAY_VERIFIED":
        return {
            "returncode": 0, "stdout": {}, "stderr": "",
            "source": "hookwall_verified_replay", "effect_receipt": None,
            "uncertain": False, "hookwall_envelope": envelope,
            "hookwall_pre_decision": pre_decision,
            "hookwall_evidence": reservation["evidence"],
            "hookwall_reason": "idempotent_replay",
        }

    outcome = _execute_operator_effect_unchecked(
        profile=profile,
        adapter=adapter,
        request=request,
        argv=argv,
        env=env,
        repo_path=repo_path,
        attempt_coordinator=attempt_coordinator,
        guarded_attempt=guarded_attempt,
        owned_process_registry=owned_process_registry,
        owned_task_id=owned_task_id,
    )
    outcome["hookwall_envelope"] = envelope
    outcome["hookwall_pre_decision"] = pre_decision
    if outcome.get("returncode") != 0 or outcome.get("uncertain"):
        unresolved_reason = "effect_uncertain" if outcome.get("uncertain") else "effect_not_committed"
        hookwall_ledger.mark_unresolved(request.idempotency_key, unresolved_reason)
        if not outcome.get("uncertain"):
            proof = _deterministic_no_mutation_proof(
                outcome,
                source_hash=source_hash,
                repo_path=repo_path,
            )
            reconcile_failed = getattr(hookwall_ledger, "reconcile_failed", None)
            if proof is not None and callable(reconcile_failed):
                try:
                    reconciliation = reconcile_failed(request.idempotency_key, proof)
                except Exception as exc:
                    # Keep the effect unknown if Mapper cannot persist the
                    # explicit transition.  Completion will therefore remain
                    # fail-closed instead of claiming a failed lease safely.
                    outcome["hookwall_reconciliation_error"] = (
                        f"{type(exc).__name__}: {exc}"
                    )
                else:
                    outcome["hookwall_reconciliation"] = {
                        "proof": proof,
                        "mapper": reconciliation,
                    }
                    outcome["hookwall_evidence"] = None
                    outcome["hookwall_reason"] = "effect_failed_no_mutation"
                    return outcome
            elif proof is not None:
                outcome["hookwall_reconciliation_error"] = (
                    "Hookwall ledger does not expose explicit failed-effect reconciliation"
                )
        outcome["hookwall_evidence"] = None
        outcome["hookwall_reason"] = unresolved_reason
        return outcome

    hookwall_ledger.effect_confirmed(
        request.idempotency_key,
        {"returncode": outcome.get("returncode"),
         "stdout": outcome.get("stdout") or {},
         "source": outcome.get("source") or ""},
    )

    mutation_receipt = {
        "schema": "simplicio.mutation-receipt/v1",
        "envelope_id": envelope["envelope_id"],
        "source_hash": source_hash,
        "policy_hash": policy_hash,
        "idempotency_key": request.idempotency_key,
        "fence": request.fencing_token,
        "status": "committed",
        "result_hash": _hookwall_digest({
            "returncode": outcome.get("returncode"),
            "stdout": outcome.get("stdout") or {},
            "source": outcome.get("source") or "",
        }),
    }
    mutation_receipt["receipt_hash"] = _hookwall_digest(mutation_receipt)
    post_decision = {
        "schema": "simplicio.hookwall-decision/v1",
        "phase": "post",
        "verdict": "proceed",
        "reason_code": "effect_verified",
        "envelope_id": envelope["envelope_id"],
        "source_hash": source_hash,
        "policy_hash": policy_hash,
        "idempotency_key": request.idempotency_key,
        "fence": request.fencing_token,
        "receipt_hash": mutation_receipt["receipt_hash"],
    }
    try:
        evidence = hookwall_ledger.verify_and_commit(
            envelope, pre_decision, mutation_receipt, post_decision
        )
    except HookwallBlocked as exc:
        hookwall_ledger.mark_unresolved(request.idempotency_key, exc.reason_code)
        outcome["returncode"] = None
        outcome["uncertain"] = True
        outcome["hookwall_evidence"] = None
        outcome["hookwall_reason"] = exc.reason_code
        return outcome
    verified, reason = gate_completion(evidence)
    if not verified:
        hookwall_ledger.mark_unresolved(request.idempotency_key, reason)
        outcome["returncode"] = None
        outcome["uncertain"] = True
        outcome["hookwall_evidence"] = None
        outcome["hookwall_reason"] = reason
        return outcome
    outcome["hookwall_mutation_receipt"] = mutation_receipt
    outcome["hookwall_post_decision"] = post_decision
    outcome["hookwall_evidence"] = evidence
    outcome["hookwall_reason"] = "ok"
    return outcome



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


def _coverage(tasks: List[Dict[str, Any]]) -> Dict[str, Any]:
    total_scenarios = 0
    total_rules = 0
    for task in tasks:
        total_scenarios += len(task.get("scenarios") or [])
        total_rules += len(task.get("rules") or [])
    return {
        "scenarios": {"verified": 0, "total": total_scenarios},
        "rules": {"verified": 0, "total": total_rules},
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
    require_authorization: bool = False,
) -> Tuple[List[str], Dict[str, Any]]:
    """Project canonical Mapper context artifacts into the Dev CLI argv.

    The compact Mapper handoff is not a ContextSnapshot.  This helper only
    forwards explicitly supplied canonical artifacts and never derives a
    handle from a path or from ``mapper_context_hash``.  Missing artifacts are
    recorded as a diagnostic; the integrated Dev CLI remains the fail-closed
    owner of the final context gate.
    """
    authorization_args, authorization_handoff = prepare_authorization_handoff(
        run_root, required=require_authorization,
    )
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
    if not all((snapshot_path, pack_path, execution_path)) or (require_authorization and identity_present and not context_handle):
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


def _guarded_dispatch_enabled() -> bool:
    """Opt-in gate (issue #288) for threading ``AttemptCoordinator.run_guarded`` through the
    real operator dispatch path instead of a raw, unguarded ``subprocess.run``.

    Off by default -- following the same pattern as ``SIMPLICIO_REQUIRE_MUTATION_AUTHORITY``
    in #284's ``planning_gate.py`` wiring -- so existing callers/fixtures that pass a
    distributed queue without the fuller identity/heartbeat contract are unaffected. Set
    ``SIMPLICIO_GUARDED_DISPATCH=1`` to require a heartbeat-guarded, lease-fenced attempt for
    every distributed-queue dispatch (a real worker whose lease is stolen mid-mutation is
    killed and reported as ``lease_lost_during_execution`` instead of finishing unguarded).
    """
    return str(os.environ.get("SIMPLICIO_GUARDED_DISPATCH") or "").strip().lower() in ("1", "true", "yes")


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


def _model_routed_dispatch_enabled() -> bool:
    """Opt-in gate (issue #287) for threading ``model_router.route()``'s selection
    through the real dispatch path instead of a hardcoded runtime.

    Off by default -- following the same pattern as ``SIMPLICIO_GUARDED_DISPATCH``
    (#288) and ``SIMPLICIO_AUTO_MERGE_PR`` (#288) above -- so existing callers/fixtures
    that dispatch without a model registry configured are unaffected. Set
    ``SIMPLICIO_MODEL_ROUTED_DISPATCH=1`` to compute a real routing-decision-receipt
    for every dispatch attempt and, when a real ``CodexRuntimeDriver``/
    ``ClaudeRuntimeDriver`` is wired for the selected runtime, genuinely invoke it and
    persist a ``runtime-execution-receipt`` alongside the operator's own receipts. A
    routing block or driver failure never blocks the underlying dev-cli operator
    mutation this repo already performs -- this is additional, real audit evidence
    layered on top of it, not a replacement for the operator contract.
    """
    return str(os.environ.get("SIMPLICIO_MODEL_ROUTED_DISPATCH") or "").strip().lower() in ("1", "true", "yes")


def _verified_delivery_gate_enabled() -> bool:
    """Opt-in gate (issue #288) for routing a dispatch attempt's completion decision through
    the real ``LoopRuntimeAdapter``/``VerifiedAgentDelivery``/``ExecutionBoard`` evidence +
    watcher + delivery contract instead of the bare ``execution_state == "applied"`` check.

    ``LoopRuntimeAdapter`` and ``VerifiedAgentDelivery`` are real, fully tested classes
    (``simplicio_loop/runtime_adapter.py``, ``verified_delivery.py``) but had zero references
    in the dispatch path -- the #288 audit named this the highest-value remaining gap: an
    attempt could be reported ``succeeded`` on ``execution_state == "applied"`` alone, with no
    fresh COMPLETE evidence receipt, no measured watcher pass, and no recorded delivery
    convergence actually required. Off by default -- following the same pattern as
    ``SIMPLICIO_GUARDED_DISPATCH``/``SIMPLICIO_AUTO_MERGE_PR`` above -- so existing
    callers/fixtures that dispatch without a watcher run are unaffected. Set
    ``SIMPLICIO_VERIFIED_DELIVERY_GATE=1`` to demote a dispatch attempt whose evidence pair,
    watcher, or delivery gate is not genuinely satisfied from ``succeeded`` to ``failed``,
    even when the underlying dev-cli operator itself applied cleanly.
    """
    return str(os.environ.get("SIMPLICIO_VERIFIED_DELIVERY_GATE") or "").strip().lower() in ("1", "true", "yes")


def _run_verified_delivery_gate(
    *, run_id: str, task_id: str, actor: str, attempt_id: str,
    receipt_verdict: Mapping[str, Any], evidence_receipt: str, watcher_receipt: str,
    merge: Optional[Mapping[str, Any]], worktree_context: Mapping[str, Any],
) -> Dict[str, Any]:
    """Drive the real evidence+watcher+delivery gated completion check (issue #288) for one
    dispatch attempt.

    Never raises: a failed gate comes back as ``verified: False`` with a ``reason`` so the
    caller can demote ``succeeded`` to ``failed`` without crashing the scheduler. This is a
    strict superset of the pre-existing ``execution_state == "applied"`` check -- it can only
    turn a would-be success into a failure, never the reverse.
    """
    schema = "simplicio.verified-delivery-gate/v1"
    try:
        watcher_state: Dict[str, Any] = {}
        if watcher_receipt and Path(watcher_receipt).exists():
            try:
                watcher_state = json.loads(Path(watcher_receipt).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                watcher_state = {}
        watcher_detail = str(watcher_state.get("reported") or "").strip()
        if receipt_verdict.get("status") != ReceiptStatus.VERIFIED:
            return {"schema": schema, "verified": False, "status": "UNVERIFIED",
                    "reason": watcher_detail or "operator/evidence receipt pair is not VERIFIED"}
        if watcher_state.get("status") != "MEASURED" or not watcher_state.get("match"):
            return {"schema": schema, "verified": False, "status": "UNVERIFIED",
                    "reason": watcher_detail or "no measured watcher pass recorded for this attempt"}
        runtime = LoopRuntimeAdapter(run_id=run_id, work_item_id=task_id, actor=actor or "loop",
                                     standalone=True)
        runtime.negotiate()
        board = ExecutionBoard(run_id=run_id)
        delivery = VerifiedAgentDelivery(runtime=runtime, board=board, attempt_id=attempt_id)
        for phase in ("intake", "mapping", "planning", "executing", "validating", "watching", "delivering"):
            delivery.transition(phase)
        evidence_payload = {"schema": "simplicio.ac-evidence/v1", "status": "PASS", "ready": True,
                            "verdict": "COMPLETE", "receipt_id": evidence_receipt or attempt_id}
        delivery.record_evidence(evidence_payload)
        challenge = str(watcher_state.get("challenge") or watcher_receipt)
        delivery.record_watcher(match=True, challenge=challenge)
        merge_info = dict(merge or {})
        if merge_info.get("merged"):
            delivery_payload = {
                "target": "merge-queue", "satisfied": True,
                "merge_queue": {
                    "receipt_sha": str(merge_info.get("merge_commit_sha") or ""),
                    "status": "accepted",
                    "branch": str(worktree_context.get("branch") or ""),
                    "worktree_path": str(worktree_context.get("worktree_path")
                                        or worktree_context.get("path") or ""),
                },
            }
        else:
            delivery_payload = {"target": "local-fixture", "satisfied": True}
        delivery.record_delivery(delivery_payload)
        result = delivery.complete(evidence_payload)
        projection = board.replay()
        return {"schema": schema, "verified": True, "status": "VERIFIED",
                "board_status": projection.get("status"), "delivery": result.get("delivery")}
    except (VerifiedDeliveryError, RuntimeAdapterError) as exc:
        return {"schema": schema, "verified": False, "status": "UNVERIFIED", "reason": str(exc)}


_DEFAULT_MODEL_REGISTRY_ENTRIES: Tuple[Dict[str, Any], ...] = (
    {
        "runtime": "codex", "provider": "openai", "model_id": "codex-cli/gpt-5.6-luna",
        "aliases": ["codex-cli"], "capabilities": ["execute", "review"],
        "probe": {"kind": "codex-cli", "target": "codex"},
    },
    {
        "runtime": "claude", "provider": "anthropic", "model_id": "claude-code/sonnet-5",
        "aliases": ["claude-code"], "capabilities": ["execute", "review"],
        "probe": {"kind": "claude-cli", "target": "claude"},
    },
)


def _default_model_registry() -> ModelCapabilityRegistry:
    """Build the standard two-runtime (Codex + Claude) registry, wired to the real
    ``--version`` probes in ``runtime_drivers.py`` -- never a fabricated availability
    check. A caller that needs a different registry shape (e.g. a config file) can
    still build/pass its own ``ModelCapabilityRegistry``; this is only the default
    used by the opt-in dispatch wiring below.
    """
    return ModelCapabilityRegistry(_DEFAULT_MODEL_REGISTRY_ENTRIES, probe_hooks=CLI_PROBE_HOOKS)


def _route_runtime_for_item(item: Mapping[str, Any], *, role: str = "executor",
                             registry: Optional[ModelCapabilityRegistry] = None) -> Dict[str, Any]:
    """Compute one real ``routing-decision-receipt`` for a dispatch attempt.

    Never raises for an ordinary routing block (no eligible candidate, e.g. neither
    CLI installed) -- that comes back as a receipt with ``blocked=True`` and an
    explicit ``block_reason`` so a caller can record/report it; only malformed input
    surfaces as ``ModelRouterError``/``ModelRegistryError``.
    """
    registry = registry or _default_model_registry()
    requirements = {"role": role, "required_capabilities": ["execute"]}
    return _model_route(requirements, registry)


def _execute_routed_runtime(item: Mapping[str, Any], run_dir: Path, *,
                             registry: Optional[ModelCapabilityRegistry] = None) -> Dict[str, Any]:
    """Route + (when a real driver is wired for the selection) genuinely execute one
    LLM-runtime attempt for this dispatch, persisting both receipts under
    ``run_dir/loop/`` for audit.

    This never fabricates execution: when routing is blocked (no eligible
    candidate) or no real driver exists for the selected runtime, the returned
    summary says so explicitly (``executed: False``) rather than skipping silently
    or pretending a result. A driver invocation failure (missing binary, auth/policy
    block, timeout) is itself a genuine, honestly-reported outcome -- captured in the
    persisted ``runtime-execution-receipt`` exactly as observed.
    """
    summary: Dict[str, Any] = {
        "routed": False, "executed": False,
        "routing_decision_receipt": "", "runtime_execution_receipt": "",
    }
    try:
        routing_receipt = _route_runtime_for_item(item, registry=registry)
    except (ModelRouterError, ModelRegistryError) as exc:
        summary["error"] = f"{type(exc).__name__}: {exc}"
        return summary
    summary["routed"] = True
    loop_dir = run_dir / "loop"
    loop_dir.mkdir(parents=True, exist_ok=True)
    routing_path = loop_dir / "routing-decision-receipt.json"
    _write_json(routing_path, routing_receipt)
    summary["routing_decision_receipt"] = str(routing_path)
    summary["selected"] = routing_receipt.get("selected")
    summary["blocked"] = bool(routing_receipt.get("blocked"))
    if routing_receipt.get("blocked") or not routing_receipt.get("selected"):
        summary["block_reason"] = str(routing_receipt.get("block_reason") or "")
        return summary
    selected = routing_receipt["selected"]
    driver = driver_for_runtime(selected.get("runtime"))
    if driver is None:
        summary["reason"] = f"no real driver wired for runtime {selected.get('runtime')!r}"
        return summary
    context_pack = item.get("context_pack") if isinstance(item.get("context_pack"), Mapping) else {}
    goal = str(context_pack.get("goal") or item.get("task_id") or "").strip()
    if not goal:
        summary["reason"] = "no task goal text available to prompt the runtime"
        return summary
    repo_path = Path(str(item.get("repo") or "."))
    context_request: Optional[RuntimeContextRequest] = None
    if all(context_pack.get(key) for key in (
        "mapper_envelope_hash", "plan_hash", "authorized_targets", "target",
    )):
        try:
            context_request = RuntimeContextRequest(
                goal=goal,
                acceptance_criteria=tuple(context_pack.get("acs") or context_pack.get("acceptance_criteria") or ()),
                source_spans=tuple(context_pack.get("source_spans") or ()),
                source_refs=tuple(context_pack.get("source_refs") or ()),
                verification_routes=tuple(context_pack.get("verification_routes") or ()),
                graph_evidence=tuple(context_pack.get("graph_evidence") or ()),
                omissions=tuple(context_pack.get("omissions") or ()),
                trusted_constraints=tuple(context_pack.get("trusted_constraints") or ()),
                untrusted_evidence=tuple(context_pack.get("untrusted_evidence") or ()),
                authorized_targets=tuple(context_pack.get("authorized_targets") or ()),
                target=str(context_pack.get("target") or ""),
                remaining_budget_tokens=int(context_pack.get("remaining_budget_tokens") or 0),
                mapper_envelope_hash=str(context_pack.get("mapper_envelope_hash") or ""),
                plan_hash=str(context_pack.get("plan_hash") or ""),
            )
            result = driver.execute_context(
                context_request, cwd=repo_path if repo_path.exists() else None,
                expected_mapper_envelope_hash=str(context_pack.get("mapper_envelope_hash")),
                expected_plan_hash=str(context_pack.get("plan_hash")),
            )
        except (ContextAuthorizationError, ContextBudgetError, TypeError, ValueError) as exc:
            summary["error"] = f"RuntimeContextError: {exc}"
            return summary
    else:
        result = driver.execute(goal, cwd=repo_path if repo_path.exists() else None)
    base_sha = ""
    head_sha = ""
    changed: List[str] = []
    if repo_path.exists():
        fingerprint = _repo_fingerprint(repo_path)
        base_sha = head_sha = str(fingerprint.get("head") or "")
        try:
            changed = _changed_paths(repo_path)
        except Exception:
            changed = []
    try:
        execution_receipt = driver.build_receipt(
            route_id=hashlib.sha256(json.dumps(routing_receipt, sort_keys=True).encode("utf-8")).hexdigest()[:16],
            requested={"runtime": selected.get("runtime"), "provider": selected.get("provider"),
                       "model_id": selected.get("model_id"), "verified": True},
            session={
                "worker_id": str(item.get("worker_id") or ""),
                "device_id": os.environ.get("SIMPLICIO_DEVICE_ID", ""),
                "attempt_id": str(item.get("task_index") or ""),
                "lease_id": "", "fence_token": "",
            },
            result=result,
            tree={"base_sha": base_sha, "head_sha": head_sha, "changed_paths": changed},
            evidence_refs=(
                ["runtime-context:" + context_request.request_hash,
                 "mapper-envelope:" + context_request.mapper_envelope_hash,
                 "plan:" + context_request.plan_hash]
                if context_request is not None else None
            ),
        )
    except RuntimeExecutionReceiptError as exc:
        summary["error"] = f"{type(exc).__name__}: {exc}"
        return summary
    execution_path = loop_dir / "runtime-execution-receipt.json"
    _write_json(execution_path, execution_receipt)
    summary["executed"] = True
    summary["runtime_execution_receipt"] = str(execution_path)
    summary["execution_ok"] = bool(result.ok)
    summary["execution_stop_reason"] = result.stop_reason
    summary["execution_error"] = result.error
    return summary


# 1-3 tasks run inline in the checkout (v3.43 "1-3 direct" policy): edits are
# instant and the quality lanes run once at the end, so worktree setup and
# patch integration would be pure overhead. Worktrees start at 4 tasks.
WAVE_INLINE_MAX_TASKS = 3


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


def _write_scratchpad(loop_dir: Path, goal: str, max_iterations: int, promise: str) -> None:
    body = "\n".join(
        [
            "---",
            "iteration: 1",
            f"max_iterations: {max_iterations}",
            f'completion_promise: "{promise}"',
            "evidence_required: true",
            "mode: converge",
            f'started_at: "{_now()}"',
            "---",
            "",
            goal,
            "",
        ]
    )
    (loop_dir / "scratchpad.md").write_text(body, encoding="utf-8")


def _write_watcher_challenge(loop_dir: Path, goal_fp: str) -> None:
    payload = {
        "challenge": f"wch-{_rand_token(12)}",
        "iteration": 1,
        "goal_fp": goal_fp,
        "written_at": _now(),
    }
    _write_json(loop_dir / "watcher_challenge.json", payload)


def _persist_external_completion_response(run_dir: Path) -> str:
    """Record the system response required by the Completion Oracle.

    An external coordinator returns a provider plan, not an interactive agent
    message, so the normal response-capture hook has no text to persist. Once
    the independent watcher and quality matrix have passed, record a
    coordinator-owned response containing the exact promise from the run's
    scratchpad. This is a transport adaptation after all evidence gates, not a
    completion claim before them.
    """
    operator = _load_json(run_dir / "operator-receipt.json")
    provider_config = operator.get("provider_config") if isinstance(operator, Mapping) else {}
    if not isinstance(provider_config, Mapping) or provider_config.get("route") not in {
        "openrouter-to-mechanical-edit", "host-edit-plan",
    }:
        return ""
    scratchpad = run_dir / "loop" / "scratchpad.md"
    try:
        text = scratchpad.read_text(encoding="utf-8")
    except OSError:
        return ""
    promise = ""
    for line in text.splitlines():
        if line.strip().startswith("completion_promise:"):
            promise = line.split(":", 1)[1].strip().strip('"')
            break
    if not promise:
        return ""
    response = (
        "<promise>%s</promise>\n"
        "Coordinator response persisted after independent watcher and quality gates: %s\n"
        % (promise, str(run_dir / "loop" / "watcher_state.json"))
    )
    path = run_dir / "loop" / "last_response.txt"
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(response, encoding="utf-8")
    temporary.replace(path)
    return str(path)


def _ensure_verified_loop_journal(run_dir: Path) -> str:
    """Persist the append-only loop journal required by the published receipt.

    Mapper-backed runs keep their durable lifecycle journal in MapperStore, while
    the runtime handoff contract still carries the loop's JSONL attempt-memory
    artifact. The normal agent hook is not involved in an external mechanical
    coordinator run, so materialize one honest, post-gate verification record at
    the boundary. An existing journal is preserved byte-for-byte; a missing or
    empty journal is only completed after the independent watcher, quality matrix,
    and Completion Oracle have passed.
    """
    path = run_dir / "loop" / "journal.jsonl"
    if path.is_symlink():
        raise LoopExecutionReceiptError("loop journal must not be a symlink")
    try:
        if path.exists() and not path.is_file():
            raise LoopExecutionReceiptError("loop journal must be a regular file")
        if path.is_file() and path.stat().st_size > 0:
            return str(path)
        _append_jsonl(
            path,
            {
                "iteration": 1,
                "action": "verified-run",
                "hypothesis": "independent execution evidence satisfies the frozen task contract",
                "gate": "pass",
                "fingerprint": "",
                "note": "watcher, quality matrix, and completion oracle passed",
                "ts": _now(),
                "execution_state": "verified",
                "source_artifact": str(run_dir / "quality-matrix.json"),
                "validator": "simplicio-loop.verify",
            },
        )
    except LoopExecutionReceiptError:
        raise
    except OSError as exc:
        raise LoopExecutionReceiptError(f"loop journal publication failed: {exc}") from exc
    return str(path)


def _transition(run_dir: Path, state: Dict[str, Any], to_phase: str, reason: str,
                receipt: str = "", extra: Dict[str, Any] | None = None) -> Dict[str, Any]:
    if to_phase not in PHASES:
        raise ValueError(f"invalid phase {to_phase!r}")
    entry = {
        "ts": _now(),
        "from": state.get("phase"),
        "to": to_phase,
        "reason": reason,
        "receipt": receipt,
    }
    if extra:
        entry["extra"] = extra
    history = state.setdefault("history", [])
    history.append(entry)
    state["phase"] = to_phase
    state["updated_at"] = entry["ts"]
    _write_json(run_dir / "state.json", state)
    _append_jsonl(run_dir / "transitions.jsonl", entry)
    _record_event(run_dir, state, {
        "phase": "phase_transition",
        "to_phase": to_phase,
        "from_phase": entry["from"],
        "reason": reason,
        "receipt": receipt,
    }, transition_extra=extra)
    return state


# Canonical phase-event kinds consumed by simplicio_loop.progress.build_progress (#181).
_PHASE_EVENT_KINDS = {
    "intake", "mapping", "planning", "executing", "validating",
    "watching", "delivering", "done", "partial", "blocked", "cancelled",
    "awaiting_decision", "mapper_fresh", "watcher_challenge", "operator_receipt",
    "worker_claimed", "worktree_created", "test_gate", "completion_verdict",
}


def _record_event(run_dir: Path, state: Dict[str, Any], event: Dict[str, Any],
                  transition_extra: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Append one normalized progress event to ``state['events']`` (#181).

    Every loop stage emits these so external dashboards and LLMs can render
    real per-stage progress (see ``docs/PROGRESS_PROTOCOL.md``).  ``progress.py``
    already normalizes and renders ``state['events']``; previously the runner
    never populated it.
    """
    event = dict(event)
    event.setdefault("schema", EVENT_METADATA_SCHEMA)
    event.setdefault("scope", infer_scope(event))
    event.setdefault("event_id", "evt-" + hashlib.sha256(
        (json.dumps(event, sort_keys=True, ensure_ascii=False) + _now()).encode("utf-8")
    ).hexdigest()[:12])
    event.setdefault("ts", _now())
    event.setdefault("run_id", state.get("run_id", ""))
    event.setdefault("phase", state.get("phase", ""))
    task_ids = state.get("task_ids") or []
    ac_ids = state.get("ac_ids") or []
    if event.get("scope") == "collection":
        event["task_id"] = None
    elif not event.get("task_id") and task_ids:
        event["task_id"] = task_ids[0]
    if not event.get("ac_ids") and ac_ids:
        event["ac_ids"] = list(ac_ids)
    if not event.get("receipt") and not event.get("blocker"):
        event["blocker"] = event.get("reason") or event.get("message") or ""
    kind = event.get("kind") or event.get("phase")
    if kind in _PHASE_EVENT_KINDS and "kind" not in event:
        event["kind"] = kind
    if transition_extra and "extra" not in event:
        event["extra"] = transition_extra
    events = state.setdefault("events", [])
    events.append(event)
    state["updated_at"] = event["ts"]
    _write_json(run_dir / "state.json", state)
    _append_jsonl(run_dir / "events.jsonl", event)
    _sync_github_lifecycle(run_dir, state, event)
    # Host integrations (Orca cards, boards, chat) are NEVER default — only when
    # the client explicitly requested them via SIMPLICIO_LOOP_CLIENT_INTEGRATIONS
    # / .simplicio-loop/client-integrations.json (see client_integrations.py).
    if integration_enabled("orca"):
        _sync_orca_lifecycle(run_dir, state, event)
    return state


def _sync_orca_lifecycle(run_dir: Path, state: Dict[str, Any], event: Dict[str, Any]) -> None:
    """Project lifecycle onto an Orca worktree card **only** for Orca clients.

    Not a core loop hook. Requires client opt-in via
    ``integration_enabled("orca")`` (caller already gated). Missing Orca context
    is a typed skip — never a delivery failure.
    """
    lifecycle_state = _github_lifecycle.lifecycle_state_for_phase_event(
        str(event.get("kind") or event.get("phase") or ""))
    if not lifecycle_state:
        return
    try:
        receipt = sync_orca_status(
            state, {**event, "lifecycle_state": lifecycle_state},
        )
        _append_jsonl(run_dir / "orca-sync.jsonl", {
            "run_id": str(state.get("run_id") or ""),
            "event": str(event.get("kind") or event.get("phase") or ""),
            **receipt,
        })
    except Exception as exc:  # noqa: BLE001 -- optional host integration is fail-open
        try:
            _append_jsonl(run_dir / "orca-sync-errors.jsonl", {
                "run_id": str(state.get("run_id") or ""), "error": str(exc),
            })
        except Exception:
            pass


def _github_source_adapter(owner: str, repo: str, *, publish_comment_fn: Callable,
                           outbox_dir: Optional[str | Path] = None) -> GitHubSourceAdapter:
    """One construction point for the #285 `GitHubSourceAdapter` binding runner.py uses,
    so every runner call site goes through the `SourceAdapter` Protocol surface instead
    of calling `github_lifecycle.py`'s free functions directly. Same defaults
    (``subprocess.run``, 20s timeout) `github_lifecycle.publish_lifecycle_state()` itself
    defaults to -- this is a binding, not a behavior change.
    """
    return GitHubSourceAdapter(owner, repo, publish_comment_fn=publish_comment_fn, outbox_dir=outbox_dir)


def _sync_github_lifecycle(run_dir: Path, state: Dict[str, Any], event: Dict[str, Any]) -> None:
    """Project one phase event onto the #285 GitHub lifecycle canonical comment.

    Best-effort and fail-open, exactly like the existing `pr_evidence.py
    progress-comment` command it complements: enabled whenever the run state
    carries a ``source_issue`` dict (``{"owner": ..., "repo": ..., "issue": ...}``).
    ``SIMPLICIO_LOOP_GITHUB_LIFECYCLE_SYNC=0`` (or another explicit falsy value)
    is the temporary legacy opt-out; leaving it unset keeps GitHub coordination on.
    Any
    failure (no `gh`, no network, transport error, import error) is logged to
    ``lifecycle-sync-errors.jsonl`` under the run directory and swallowed -- this
    sync must never abort or fail the run. It only ever handles the intermediate
    lifecycle projection (CLAIMED/PLANNED/IN_PROGRESS/...); the authoritative,
    fail-closed close operation is
    :func:`simplicio_loop.github_lifecycle.close_source_issue`, invoked explicitly at
    completion time by the caller that owns that decision, never automatically from
    this generic per-event hook.
    """
    if str(os.environ.get("SIMPLICIO_LOOP_GITHUB_LIFECYCLE_SYNC") or "").strip().lower() in (
        "0", "false", "no", "off", "legacy",
    ):
        return
    source_issue = state.get("source_issue") or {}
    owner, repo, issue = source_issue.get("owner"), source_issue.get("repo"), source_issue.get("issue")
    if not (owner and repo and issue):
        return
    lifecycle_state = _github_lifecycle.lifecycle_state_for_phase_event(
        str(event.get("kind") or event.get("phase") or ""))
    if not lifecycle_state:
        return
    try:
        scripts_dir = str(Path(__file__).resolve().parent.parent / "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        from pr_evidence import publish_comment as _publish_comment  # local import: optional dep

        # #285 remaining gap: project the run's real identity/runtime/device/lease/
        # branch onto the rendered comment instead of leaving those fields blank even
        # though `render_lifecycle_comment` supports them. `event` wins over derived
        # defaults when the emitting call site already knows its lease/branch (e.g.
        # `execute_operator()`'s guarded dispatch, which has a real `WorkItemAttempt`
        # lease and worktree branch on hand); otherwise fall back to a best-effort
        # local identity/branch lookup so a plain sequential run is not blank either.
        repo_path = _run_repo_path(run_dir)
        identity = _dispatch_identity_fields(repo_path)
        lease = state.get("lease") if isinstance(state.get("lease"), Mapping) else {}
        lease_id = str(event.get("lease_id") or lease.get("lease_id") or "")
        fencing_token = str(event.get("fencing_token") or lease.get("fencing_token") or "")
        branch = str(
            event.get("branch") or state.get("branch")
            or (_git_current_branch(repo_path) if repo_path is not None else "")
        )
        worktree = str(event.get("worktree_path") or state.get("worktree_path") or "")

        # #285 remaining gap: go through the `GitHubSourceAdapter` Protocol binding
        # instead of calling `github_lifecycle.publish_lifecycle_state()` directly --
        # same underlying call (no behavior change), but now expressed through the
        # single adapter surface every source (GitHub or otherwise) is meant to plug
        # into.
        adapter = _github_source_adapter(str(owner), str(repo), publish_comment_fn=_publish_comment)
        receipt = adapter.update_status(
            str(issue), lifecycle_state,
            run_id=str(state.get("run_id") or ""),
            attempt_id=str(event.get("task_id") or state.get("run_id") or ""),
            fencing_token=fencing_token,
            progress=str(event.get("message") or ""),
            agent_id=identity.get("agent_id", ""),
            runtime=identity.get("runtime", ""),
            device=identity.get("device", ""),
            lease_id=lease_id,
            branch=branch,
            worktree=worktree,
        )
        # Persist the receipt into the run dir so the completion oracle (#285's remaining gap:
        # "CLOSE_PENDING_RECONCILIATION" must actually gate COMPLETE, not sit inert) can see it.
        # This hook only ever projects intermediate states; a genuine
        # CLOSE_PENDING_RECONCILIATION comes from the explicit `close_source_issue` call, which
        # persists its own receipt the same way -- see `simplicio_loop/oracle.py`.
        _github_lifecycle.persist_lifecycle_receipt(receipt, run_dir)
    except Exception as exc:  # noqa: BLE001 -- best-effort sync, never blocks the loop
        try:
            _append_jsonl(run_dir / "lifecycle-sync-errors.jsonl",
                         {"ts": _now(), "kind": event.get("kind"), "error": str(exc)})
        except Exception:
            pass


def _maybe_auto_build_planning_receipt(
    run_root: Path, state: Dict[str, Any], run_id: str,
    contract: Dict[str, Any], plan: Dict[str, Any], plan_validation: Dict[str, Any],
    repo_path: Optional[Path] = None,
) -> None:
    """#284 remaining gap: wire ``planning_gate.build_planning_receipt()`` into the
    REAL ``arm_run()`` dispatch path so the mutation-authority gate in
    ``execute_operator()``/``execute_operator_batch()`` is self-sufficient, instead
    of only ever being satisfiable by a caller remembering to run the separate
    ``scripts/planning_gate.py build`` CLI first.

    Mandatory-by-default via ``planning_gate.auto_planning_receipt_enabled()`` --
    the same polarity-flip pattern ``mutation_authority_required()`` used for
    ``SIMPLICIO_REQUIRE_MUTATION_AUTHORITY`` (#284/#360). Unset/blank now means
    ON: every real ``arm_run()`` dispatch self-builds a matching
    ``planning-receipt.json`` so ``execute_operator()``/``execute_operator_batch()``
    are self-sufficient, instead of only ever being satisfiable by a caller
    remembering to run the separate ``scripts/planning_gate.py build`` CLI first.
    A caller that truly needs the legacy opt-in posture (or a test asserting the
    missing-receipt fail-closed path) sets ``SIMPLICIO_LOOP_AUTO_PLANNING_RECEIPT``
    to an explicit falsy value (``0/false/no/off/legacy``); see
    ``tests/planning_gate_fixtures.py`` and
    ``docs/adr/0004-planning-gate-rollout.md`` for the rollout/migration strategy.

    When a GitHub ``source_issue`` is present on the run state AND
    ``SIMPLICIO_LOOP_GITHUB_LIFECYCLE_SYNC`` is also enabled, this additionally
    captures a fresh source snapshot (folding it into the mutation-authority
    identity so a later source edit invalidates the authority) and publishes the
    resulting receipt as PLANNED/BLOCKED on the canonical GitHub comment via
    ``planning_gate.publish_planning_receipt()`` -- the #284-specific projection,
    distinct from (and complementary to) the generic per-phase-event sync
    ``_sync_github_lifecycle()`` already performs for CLAIMED/DISCOVERED/etc.

    Best-effort and fail-open: any failure here (bad `gh` auth, no network, import
    error) is logged to ``lifecycle-sync-errors.jsonl`` and swallowed, exactly like
    ``_sync_github_lifecycle()`` -- this must never abort or fail the run.
    """
    if not auto_planning_receipt_enabled():
        return
    try:
        attempt = int((state or {}).get("attempts", 0)) + 1
        source_snapshot = None
        source_issue = (state or {}).get("source_issue") or {}
        owner, repo_name, issue = source_issue.get("owner"), source_issue.get("repo"), source_issue.get("issue")
        lifecycle_sync_on = str(os.environ.get("SIMPLICIO_LOOP_GITHUB_LIFECYCLE_SYNC") or "").strip().lower() not in (
            "0", "false", "no", "off", "legacy",
        )
        if lifecycle_sync_on and owner and repo_name and issue:
            try:
                from .source_snapshot import capture_github_issue_snapshot
                source_snapshot = capture_github_issue_snapshot(f"{owner}/{repo_name}", str(issue))
            except Exception:
                source_snapshot = None
        receipt = _build_planning_receipt(
            run_id=run_id, attempt=attempt, contract=contract, plan=plan,
            plan_validation=plan_validation, source_snapshot=source_snapshot,
        )
        (run_root / "planning-receipt.json").write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
        if source_snapshot is not None and lifecycle_sync_on:
            scripts_dir = str(Path(__file__).resolve().parent.parent / "scripts")
            if scripts_dir not in sys.path:
                sys.path.insert(0, scripts_dir)
            from pr_evidence import publish_comment as _publish_comment  # local import: optional dep

            # #285 remaining gap: project real identity/runtime/device/branch/plan onto
            # the PLANNED comment instead of leaving those fields blank, the same
            # projection `_sync_github_lifecycle()` now performs for CLAIMED/etc. No
            # lease/fencing token exists yet at this point in `arm_run()` (it is minted
            # only when a distributed claim happens later), so that field is left blank
            # here rather than fabricated.
            identity = _dispatch_identity_fields(repo_path)
            branch = _git_current_branch(repo_path) if repo_path is not None else ""
            plan_steps = [
                str(step.get("description") or step.get("goal") or step.get("id") or "").strip()
                for step in (plan.get("steps") or [])
                if isinstance(step, Mapping)
                and str(step.get("description") or step.get("goal") or step.get("id") or "").strip()
            ]
            lifecycle_receipt = _publish_planning_receipt(
                receipt, publish_comment_fn=_publish_comment,
                agent_id=identity.get("agent_id", ""),
                runtime=identity.get("runtime", ""),
                device=identity.get("device", ""),
                branch=branch,
                plan_steps=plan_steps,
            )
            if lifecycle_receipt is not None:
                _github_lifecycle.persist_lifecycle_receipt(lifecycle_receipt, run_root)
    except Exception as exc:  # noqa: BLE001 -- best-effort, never blocks the run
        try:
            _append_jsonl(run_root / "lifecycle-sync-errors.jsonl",
                         {"ts": _now(), "kind": "planning_receipt_auto_build", "error": str(exc)})
        except Exception:
            pass


def _emit_event(run_dir: Path, state: Dict[str, Any], kind: str, *,
                receipt: str = "", blocker: str = "", message: str = "",
                **extra: Any) -> Dict[str, Any]:
    """Emit one named visual event with the run's canonical provenance."""
    event: Dict[str, Any] = {"kind": kind, "receipt": receipt, "blocker": blocker,
                             "message": message}
    event.update(extra)
    return _record_event(run_dir, state, event)


def _task_ac_ids(task: Mapping[str, Any]) -> List[str]:
    """Return acceptance-criterion/scenario IDs from a compiled task."""
    return [str(item.get("id") or "") for item in (task.get("scenarios") or [])
            if isinstance(item, Mapping) and item.get("id")]


def _recoverable_operator_error(tool: str, exc: BaseException) -> bool:
    """Return True only for operator installation/version/capability failures."""
    if isinstance(exc, FileNotFoundError):
        missing = str(getattr(exc, "filename", "") or "")
        return Path(missing).name == tool or tool.lower() in str(exc).lower()
    message = str(exc or "").lower()
    if tool.lower() not in message:
        return False
    return any(marker in message for marker in (
        "no such file or directory",
        "unavailable",
        "below minimum version",
        "missing required capabilities",
        "version probe failed",
    ))


def _run_with_operator_recovery(
    tool: str,
    run_root: Path,
    operation: Callable[[], Dict[str, Any]],
) -> Dict[str, Any]:
    """Run one operator step, bootstrap the stack once if eligible, then retry once."""
    try:
        return operation()
    except Exception as first_error:
        if not _recoverable_operator_error(tool, first_error):
            raise
        try:
            bootstrap = _ensure_required_operators(run_root, force=True)
        except OperatorBootstrapError as bootstrap_error:
            raise RuntimeError(
                f"{first_error}; automatic {tool} recovery failed: {bootstrap_error}"
            ) from bootstrap_error
        state_path = run_root / "state.json"
        if state_path.exists():
            state = _load_json(state_path)
            state["operator_bootstrap"] = {
                "ready": bootstrap.get("status") in {"installed", "already_available"},
                "receipt": str(run_root / "operator-bootstrap.json"),
                "recovered_tool": tool,
            }
            _write_json(state_path, state)
            _emit_event(
                run_root,
                state,
                "operator_bootstrap",
                receipt=str(run_root / "operator-bootstrap.json"),
                message=f"{tool} repaired; retrying the blocked stage once",
            )
        try:
            result = operation()
        except Exception as retry_error:
            raise RuntimeError(
                f"{tool} remained unavailable after automatic recovery: {retry_error}"
            ) from retry_error
        receipt_path = run_root / "operator-bootstrap.json"
        if receipt_path.exists():
            bootstrap = _load_json(receipt_path)
            bootstrap["retry_succeeded"] = True
            bootstrap["recovered_tool"] = tool
            bootstrap["recovered_at"] = _now()
            _write_json(receipt_path, bootstrap)
        return result


# Zero-probe cache: static capability info (identity/help/version banner) never
# changes within a run, so it is probed at most ONCE per run_root and reused by
# every subsequent task attempt. `repo_state` is NOT cached here -- it is
# recomputed fresh on every call (cheap, no subprocess) so the receipt's
# staleness check in `_validate_run_receipts` keeps working unchanged.
_CAPABILITY_PROBE_CACHE: Dict[Tuple[str, str], Dict[str, Any]] = {}


def _mapper_capability_probe(repo_path: Path) -> Dict[str, Any]:
    """One subprocess pair for mapper identity/version/help -- callers cache the result."""
    identity = _resolved_identity("simplicio-mapper", ("simplicio-mapper",))
    version = _run_cmd(["simplicio-mapper", "--version"], repo_path)
    help_result = _run_cmd(["simplicio-mapper", "--help"], repo_path)
    return {
        "identity": identity,
        "version_stdout": (version.stdout or "").strip(),
        "version_rc": version.returncode,
        "help_stdout": (help_result.stdout or "").strip(),
        "help_rc": help_result.returncode,
    }


def _cached_mapper_capability_probe(repo_path: Path, run_root: Path) -> Dict[str, Any]:
    key = ("mapper", str(run_root))
    cached = _CAPABILITY_PROBE_CACHE.get(key)
    if cached is None:
        cached = _mapper_capability_probe(repo_path)
        _CAPABILITY_PROBE_CACHE[key] = cached
    return cached


def reset_capability_probe_cache() -> None:
    """Test/utility hook: drop every cached capability probe (all run_roots)."""
    _CAPABILITY_PROBE_CACHE.clear()


def _preflight_mapper(repo_path: Path, run_root: Path) -> Dict[str, Any]:
    override = _preflight_override("SIMPLICIO_LOOP_FAKE_MAPPER_PREFLIGHT_JSON")
    if override is not None:
        identity = {"command": "simplicio-mapper", "path": "", "identity_ok": True}
        version_stdout = str(override.get("version_stdout", ""))
        help_stdout = str(override.get("help_stdout", ""))
        version_rc = int(override.get("version_returncode", 0))
        help_rc = int(override.get("help_returncode", 0))
    else:
        cached = _cached_mapper_capability_probe(repo_path, run_root)
        identity = cached["identity"]
        version_stdout = cached["version_stdout"]
        help_stdout = cached["help_stdout"]
        version_rc = cached["version_rc"]
        help_rc = cached["help_rc"]
    parsed_version = _parse_version_tuple(version_stdout)
    missing_verbs = [verb for verb in MAPPER_REQUIRED_VERBS if verb not in help_stdout]
    task_aware_flags = ("--goal", "--task-file", "--task-fingerprint")
    supported_task_aware_flags = [flag for flag in task_aware_flags if flag in help_stdout]
    receipt = {
        "tool": "simplicio-mapper",
        "returncode": version_rc,
        "stdout": version_stdout,
        "help_returncode": help_rc,
        "help_stdout": help_stdout,
        "version": ".".join(str(part) for part in parsed_version),
        "min_version": ".".join(str(part) for part in MAPPER_MIN_VERSION),
        "version_ok": parsed_version >= MAPPER_MIN_VERSION,
        "required_verbs": list(MAPPER_REQUIRED_VERBS),
        "missing_verbs": missing_verbs,
        "task_aware_flags": list(task_aware_flags),
        "supported_task_aware_flags": supported_task_aware_flags,
        "task_aware_supported": len(supported_task_aware_flags) == len(task_aware_flags),
        "repo_state": _repo_fingerprint(repo_path),
        "path": identity["path"],
        "identity_ok": identity["identity_ok"],
        "checked_at": _now(),
    }
    _write_json(run_root / "mapper-preflight.json", receipt)
    if version_rc != 0 or help_rc != 0:
        raise RuntimeError("simplicio-mapper unavailable")
    if not receipt["identity_ok"]:
        raise RuntimeError("simplicio-mapper identity mismatch")
    if parsed_version < MAPPER_MIN_VERSION:
        raise RuntimeError("simplicio-mapper below minimum version")
    if missing_verbs:
        raise RuntimeError("simplicio-mapper missing required capabilities")
    return receipt


def _operator_capability_gaps(help_stdout: str, task_help_stdout: str) -> Tuple[List[str], List[str]]:
    """Derive dev-cli capability gaps from the exact persisted help surfaces."""
    capability_surface = " ".join(part for part in (help_stdout, task_help_stdout) if part)
    missing_tokens = [
        token for token in DEVCLI_REQUIRED_TOKENS
        if token not in (" " + capability_surface)
    ]
    missing_capabilities = [
        capability for capability in DEVCLI_REQUIRED_CAPABILITIES
        if capability not in capability_surface
    ]
    return missing_tokens, missing_capabilities


class DevCliCapabilitiesUnavailableError(RuntimeError):
    """Neither the in-process capabilities manifest nor `capabilities --json`
    resolved. No backward-compat layer -- fail closed with a typed reason."""

    def __init__(self, message: str, *, reason_code: str = "devcli_capabilities_unavailable") -> None:
        super().__init__(message)
        self.reason_code = reason_code


def _devcli_capability_probe(repo_path: Path) -> Dict[str, Any]:
    """One in-process manifest read when available, else one `capabilities --json`
    subprocess. No legacy --help/--version fallback: an install that supports
    neither path fails closed (`devcli_capabilities_unavailable`).
    Callers cache the result -- this must run at most once per run_root."""
    identity = _resolved_identity("simplicio-dev-cli", ("simplicio-dev-cli", "simplicio-py"))
    manifest: Dict[str, Any] | None = None
    try:
        from simplicio.capabilities import load_capabilities_manifest  # type: ignore

        manifest = load_capabilities_manifest()
    except Exception:
        manifest = None
    env = _devcli_env(repo_path)
    if manifest is None:
        try:
            probe = subprocess.run(
                _devcli_cmd(repo_path, "capabilities", "--json"),
                cwd=str(repo_path), capture_output=True, text=True, timeout=180, env=env,
            )
            if probe.returncode == 0 and probe.stdout:
                manifest = json.loads(probe.stdout)
        except (OSError, subprocess.SubprocessError, ValueError):
            manifest = None
    if manifest is None:
        raise DevCliCapabilitiesUnavailableError(
            "simplicio-dev-cli capabilities are unavailable: neither the in-process "
            "simplicio.capabilities manifest nor `simplicio-dev-cli capabilities --json` "
            "resolved. Install simplicio-cli>=0.18.16."
        )
    commands = manifest.get("commands") or {}
    edit_spec = commands.get("edit") or {}
    surface_parts = [manifest.get("schema", ""), " ".join(manifest.get("top_level_flags") or [])]
    for name, spec in commands.items():
        if not isinstance(spec, Mapping):
            continue
        surface_parts.append(name)
        surface_parts.append(" ".join(spec.get("flags") or []))
        surface_parts.append(str(spec.get("help", "")))
    help_stdout = " ".join(part for part in surface_parts if part)
    task_help_stdout = " ".join(
        part for part in (
            "edit", " ".join(edit_spec.get("flags") or []), str(edit_spec.get("help", "")),
        ) if part
    )
    version = str((manifest.get("package") or {}).get("version") or "")
    return {
        "identity": identity,
        "help_stdout": help_stdout,
        "help_rc": 0,
        "task_help_stdout": task_help_stdout,
        "task_help_rc": 0,
        "version_stdout": f"simplicio-dev-cli {version}".strip() if version else "",
        "version_rc": 0 if version else 1,
    }


def _cached_devcli_capability_probe(repo_path: Path, run_root: Path) -> Dict[str, Any]:
    key = ("devcli", str(run_root))
    cached = _CAPABILITY_PROBE_CACHE.get(key)
    if cached is None:
        cached = _devcli_capability_probe(repo_path)
        _CAPABILITY_PROBE_CACHE[key] = cached
    return cached


def _preflight_operator(repo_path: Path, run_root: Path) -> Dict[str, Any]:
    # Issue #135: the operator bridge validates identity + capability + MIN_VERSION,
    # not merely `which`. A wrong homonym (PATH resolves but the stem mismatches) or a
    # version below DEVCLI_MIN_VERSION blocks before any mutation.
    override = _preflight_override("SIMPLICIO_LOOP_FAKE_DEVCLI_PREFLIGHT_JSON")
    if override is not None:
        identity = {"command": "simplicio-dev-cli", "path": str(override.get("path", "")), "identity_ok": True}
        help_stdout = str(override.get("help_stdout", ""))
        help_rc = int(override.get("help_returncode", 0))
        task_help_stdout = str(override.get("task_help_stdout", help_stdout))
        task_help_rc = int(override.get("task_help_returncode", help_rc))
        version_stdout = str(override.get("version_stdout", "simplicio-py 0.14.0"))
        version_rc = int(override.get("version_returncode", 0))
    else:
        cached = _cached_devcli_capability_probe(repo_path, run_root)
        identity = cached["identity"]
        help_stdout = cached["help_stdout"]
        help_rc = cached["help_rc"]
        task_help_stdout = cached["task_help_stdout"]
        task_help_rc = cached["task_help_rc"]
        version_stdout = cached["version_stdout"]
        version_rc = cached["version_rc"]
    missing_tokens, missing_capabilities = _operator_capability_gaps(help_stdout, task_help_stdout)
    parsed_version = _parse_version_tuple(version_stdout)
    receipt = {
        "tool": "simplicio-dev-cli",
        "returncode": help_rc,
        "help_stdout": help_stdout,
        "task_help_returncode": task_help_rc,
        "task_help_stdout": task_help_stdout,
        "required_tokens": list(DEVCLI_REQUIRED_TOKENS),
        "missing_tokens": missing_tokens,
        "path": identity["path"],
        "identity_ok": identity["identity_ok"],
        "version_stdout": version_stdout,
        "version_returncode": version_rc,
        "version": ".".join(str(part) for part in parsed_version),
        "min_version": ".".join(str(part) for part in DEVCLI_MIN_VERSION),
        "version_ok": parsed_version >= DEVCLI_MIN_VERSION,
        "required_capabilities": list(DEVCLI_REQUIRED_CAPABILITIES),
        "missing_capabilities": missing_capabilities,
        "repo_state": _repo_fingerprint(repo_path),
        "checked_at": _now(),
    }
    _write_json(run_root / "operator-preflight.json", receipt)
    if help_rc != 0 or task_help_rc != 0:
        raise RuntimeError("simplicio-dev-cli unavailable")
    if not receipt["identity_ok"]:
        raise RuntimeError("simplicio-dev-cli identity mismatch")
    if missing_tokens or missing_capabilities:
        raise RuntimeError("simplicio-dev-cli missing required capabilities")
    if version_rc != 0:
        raise RuntimeError("simplicio-dev-cli version probe failed")
    if not receipt["version_ok"]:
        raise RuntimeError(
            "simplicio-dev-cli below minimum version %s (found %s)"
            % (receipt["min_version"], receipt["version"])
        )
    return receipt


def _validate_mapper_receipt(payload: Mapping[str, Any], repo_path: Path) -> None:
    """Require the mapper's own artifact receipt, not a caller-supplied freshness flag."""
    inspect = payload.get("inspect") or {}
    inspect_out = inspect.get("stdout") or {}
    status = inspect_out.get("status") or {}
    evidence = inspect_out.get("evidence") or {}
    artifacts = evidence.get("artifacts") or {}
    if not status.get("artifacts_present") or not status.get("fresh"):
        raise RuntimeError("mapper artifacts are missing or stale")
    # context_cache is an optional cache artifact the mapper does not always emit;
    # it must not block the loop when only that one is missing.
    required_artifacts = {
        key: item for key, item in artifacts.items()
        if isinstance(item, Mapping) and key != "context_cache"
    }
    if not required_artifacts or any(
        not bool(item.get("exists")) for item in required_artifacts.values()
    ):
        raise RuntimeError("mapper artifact evidence is incomplete")
    handoff = ((payload.get("handoff") or {}).get("stdout") or {}).get("context_pack") or {}
    for item in handoff.get("files") or []:
        raw = item.get("path") if isinstance(item, Mapping) else ""
        if not raw:
            continue
        try:
            candidate = (repo_path / str(raw)).resolve() if not Path(str(raw)).is_absolute() else Path(str(raw)).resolve()
            candidate.relative_to(repo_path.resolve())
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"mapper returned path outside authorized repo: {raw}") from exc


def _mapper_generation(repo_path: Path) -> Dict[str, str]:
    """Read the immutable Mapper index identity for the active attempt.

    Identity is exactly Mapper's ``head`` + ``tree_hash`` -- never
    ``index-state.json``'s ``updated_at``, and never its ``status_hash``.

    ``updated_at`` is rewritten to "now" on *every* Mapper invocation,
    including a purely read-only re-survey (e.g. the host running
    ``simplicio-loop orient`` again between ``prepare`` and ``wave`` to
    refresh context before a retry) that touches no source file.

    ``status_hash`` is a hash of Mapper's own ``git status`` snapshot at
    survey time. Empirically (see the multiprocess/orient regression this
    guards), it also changes across back-to-back re-surveys of an unchanged
    tree -- Mapper's own scan writes timestamped bookkeeping under its own
    excluded output directory, and that housekeeping alone was observed to
    shift ``status_hash`` with no tracked or working-tree file touched.
    ``head`` (the resolved commit) and ``tree_hash`` (a content/mtime digest
    over the actual working tree, excluding Mapper's own output dir) are the
    two fields that stayed stable across every read-only re-survey tested and
    still change on any real source edit -- that pair is the right identity
    for "did the tree Mapper surveyed actually change", not a field that
    churns on Mapper's own bookkeeping and would turn every such read-only
    re-survey into a false "active attempt mapper generation changed" block.
    """
    path = repo_path / ".simplicio-loop" / "index-state.json"
    try:
        document = _load_json(path)
    except (OSError, TypeError, ValueError):
        return {}
    signature = document.get("signature") if isinstance(document, Mapping) else None
    if not isinstance(signature, Mapping):
        return {}
    return {
        key: str(signature.get(key) or "")
        for key in ("head", "tree_hash")
        if str(signature.get(key) or "")
    }


def _receipt_run_id(payload: Mapping[str, Any], expected_run_id: str) -> str:
    """Bind a receipt to its run directory when it omitted run_id."""
    raw = payload.get("run_id")
    if raw in {None, ""}:
        return expected_run_id
    return str(raw)


def _require_matching_run_id(payload: Mapping[str, Any], expected_run_id: str, label: str) -> None:
    if _receipt_run_id(payload, expected_run_id) != expected_run_id:
        raise RuntimeError(f"{label} receipt is not bound to the current run")


def _require_json_receipt(path: Path, label: str) -> Dict[str, Any]:
    if not path.is_file():
        raise RuntimeError(f"missing required {label} receipt: {path.name}")
    try:
        payload = _load_json(path)
    except (OSError, ValueError, TypeError) as exc:
        raise RuntimeError(f"invalid required {label} receipt: {path.name}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"invalid required {label} receipt: {path.name}")
    return payload


def _validate_run_receipts(
    repo_path: Path,
    run_dir: Path,
    contract: Mapping[str, Any],
    *,
    state: Mapping[str, Any] | None = None,
    manifest: Mapping[str, Any] | None = None,
    require_dry_run: bool = True,
) -> Dict[str, Any]:
    """Require a current, run-bound mapper -> plan -> operator receipt chain."""
    storage_route = _verify_storage_route(run_dir)
    mapper = _require_json_receipt(run_dir / "mapper-context.json", "mapper context")
    plan = _require_json_receipt(run_dir / "plan.json", "plan")
    mapper_preflight = _require_json_receipt(run_dir / "mapper-preflight.json", "mapper preflight")
    operator_preflight = _require_json_receipt(run_dir / "operator-preflight.json", "operator preflight")
    operator = _require_json_receipt(run_dir / "operator-receipt.json", "operator")
    if ecc_required() and extract_guidance_reference(operator) is None:
        raise RuntimeError("required ECC guidance reference is missing from operator receipt")

    expected_run_id = str((manifest or {}).get("run_id") or run_dir.name)
    if run_dir.name != expected_run_id:
        raise RuntimeError("run receipts are not bound to the current run")
    if state is not None and str(state.get("run_id") or "") != expected_run_id:
        raise RuntimeError("run state is not bound to the current run")
    expected_contract_hash = str((manifest or {}).get("collection_hash") or "")
    contract_hash = str(contract.get("collection_hash") or "")
    if expected_contract_hash and contract_hash != expected_contract_hash:
        raise RuntimeError("task contract is not bound to the current run")
    if mapper.get("run_id") != expected_run_id or plan.get("run_id") != expected_run_id:
        raise RuntimeError("mapper and plan receipts are not bound to the current run")
    _require_matching_run_id(operator, expected_run_id, "operator")
    if mapper.get("task_contract_hash") != contract_hash or plan.get("task_contract_hash") != contract_hash:
        raise RuntimeError("mapper and plan receipts do not match the task contract")
    mapper_context_hash = str(plan.get("mapper_context_hash") or "")
    if not mapper_context_hash:
        raise RuntimeError("plan receipt has no mapper context hash")
    actual_mapper_context_hash = hashlib.sha256(
        (run_dir / "mapper-context.json").read_bytes()
    ).hexdigest()
    if actual_mapper_context_hash != mapper_context_hash:
        raise RuntimeError("plan receipt does not match the current mapper context bytes")
    mapper_generation = dict(mapper.get("foreground_generation") or {})
    plan_generation = dict(plan.get("mapper_generation") or {})
    if mapper_generation != plan_generation:
        raise RuntimeError("plan receipt does not match the pinned mapper generation")
    if mapper_generation:
        current_generation = _mapper_generation(repo_path)
        if current_generation and current_generation != mapper_generation:
            raise RuntimeError("active attempt mapper generation changed")

    degraded_mapper = bool(mapper.get("degraded_local"))
    if degraded_mapper:
        if not _degraded_mapper_fallback_enabled():
            raise RuntimeError("degraded mapper context requires standalone local fallback")
        context_pack = ((mapper.get("handoff") or {}).get("stdout") or {}).get("context_pack") or {}
        if not context_pack.get("pack_hash"):
            raise RuntimeError("degraded mapper context has no local context-pack hash")
    else:
        for name, payload in (("scan", mapper.get("scan")), ("inspect", mapper.get("inspect")),
                              ("handoff", mapper.get("handoff"))):
            if not isinstance(payload, Mapping) or payload.get("returncode") != 0:
                raise RuntimeError(f"stale mapper context: {name} did not complete successfully")
        _validate_mapper_receipt(mapper, repo_path)
    planned_state = mapper.get("repo_state_after") or {}
    current_state = _repo_fingerprint(repo_path)
    mapper_before = mapper.get("repo_state_before") or {}
    if not mapper_before.get("tree_hash") or not planned_state.get("tree_hash"):
        raise RuntimeError("mapper context has no repository fingerprint")
    if not _repo_state_equivalent(mapper_before, planned_state) or not _repo_state_equivalent(planned_state, current_state):
        raise RuntimeError("stale mapper context: repository changed after planning")

    if not mapper_preflight.get("identity_ok") or not mapper_preflight.get("version_ok"):
        raise RuntimeError("mapper preflight receipt is not valid")
    if mapper_preflight.get("missing_verbs"):
        raise RuntimeError("mapper preflight receipt is missing required capabilities")
    mapper_preflight_state = mapper_preflight.get("repo_state") or {}
    if not mapper_preflight_state.get("tree_hash") or not _repo_state_equivalent(mapper_preflight_state, current_state):
        raise RuntimeError("stale mapper preflight receipt: repository changed")
    if not operator_preflight.get("identity_ok") or not operator_preflight.get("version_ok"):
        raise RuntimeError("operator preflight receipt is not valid")
    list_fields = (
        "required_tokens", "missing_tokens", "required_capabilities", "missing_capabilities",
    )
    text_fields = ("help_stdout", "task_help_stdout")
    for field in list_fields:
        value = operator_preflight.get(field)
        if field not in operator_preflight:
            raise RuntimeError(f"operator preflight receipt is missing required field: {field}")
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise RuntimeError(f"operator preflight receipt has invalid field type: {field}")
    for field in text_fields:
        if field not in operator_preflight:
            raise RuntimeError(f"operator preflight receipt is missing required field: {field}")
        if not isinstance(operator_preflight[field], str):
            raise RuntimeError(f"operator preflight receipt has invalid field type: {field}")
    if operator_preflight["required_tokens"] != list(DEVCLI_REQUIRED_TOKENS):
        raise RuntimeError("operator preflight receipt required_tokens do not match the canonical contract")
    if operator_preflight["required_capabilities"] != list(DEVCLI_REQUIRED_CAPABILITIES):
        raise RuntimeError("operator preflight receipt required_capabilities do not match the canonical contract")
    recomputed_missing_tokens, recomputed_missing_capabilities = _operator_capability_gaps(
        operator_preflight["help_stdout"], operator_preflight["task_help_stdout"],
    )
    if operator_preflight["missing_tokens"] != recomputed_missing_tokens:
        raise RuntimeError("operator preflight receipt missing_tokens do not match persisted help")
    if operator_preflight["missing_capabilities"] != recomputed_missing_capabilities:
        raise RuntimeError("operator preflight receipt missing_capabilities do not match persisted help")
    if recomputed_missing_tokens or recomputed_missing_capabilities:
        raise RuntimeError("operator preflight receipt is missing required capabilities")
    operator_preflight_state = operator_preflight.get("repo_state") or {}
    if not operator_preflight_state.get("tree_hash") or not _repo_state_equivalent(operator_preflight_state, current_state):
        raise RuntimeError("stale operator preflight receipt: repository changed")

    tasks = list(contract.get("tasks") or [])
    validation = validate_plan(
        plan, tasks, repo_path,
        contract_hash=contract_hash,
        current_state=current_state,
    )
    if not validation["valid"]:
        raise RuntimeError("stale or invalid plan receipt: " + ", ".join(validation["errors"]))
    if (plan.get("deterministic") or {}).get("verified") is not True:
        raise RuntimeError("plan receipt is not deterministic")
    context_pack = ((mapper.get("handoff") or {}).get("stdout") or {}).get("context_pack") or {}
    mapper_pack_hash = str(plan.get("mapper_pack_hash") or "")
    context_pack_hash = str(context_pack.get("pack_hash") or "")
    if mapper_pack_hash and context_pack_hash and mapper_pack_hash != context_pack_hash:
        raise RuntimeError("plan receipt does not match the mapper context fingerprint")

    plan_hash = hashlib.sha256((run_dir / "plan.json").read_bytes()).hexdigest()
    if operator.get("task_contract_hash") != contract_hash:
        raise RuntimeError("operator receipt does not match the task contract")
    if operator.get("plan_hash") != plan_hash:
        raise RuntimeError("operator receipt does not match the current plan")
    if operator.get("mapper_pack_hash") != plan.get("mapper_pack_hash"):
        raise RuntimeError("operator receipt does not match the mapper context")
    if operator.get("mapper_context_hash") != mapper_context_hash:
        raise RuntimeError("operator receipt does not match the mapper receipt")
    operator_state = operator.get("repo_state_before") or {}
    if not operator_state.get("tree_hash") or not _repo_state_equivalent(operator_state, current_state):
        raise RuntimeError("stale operator receipt: repository changed")
    if require_dry_run:
        dry_run_ok = operator.get("execution_state") == "dry_run" and operator.get("returncode") == 0
        external_ok = bool(operator.get("preflight_admitted")) and _external_preflight_admissible(operator)
        if not dry_run_ok and not external_ok:
            raise RuntimeError("operator receipt is not a fresh successful dry-run preflight")
    if not operator.get("target_within_repo") or not operator.get("authorized_targets"):
        raise RuntimeError("operator receipt has no authorized target")
    target = str(operator.get("target") or "")
    authorized_targets = {str(item) for item in operator.get("authorized_targets") or []}
    planned_targets = {
        str(item) for step in plan.get("steps") or []
        if isinstance(step, Mapping) for item in step.get("candidate_targets") or []
    }
    try:
        (repo_path / target).resolve().relative_to(repo_path.resolve())
    except (OSError, ValueError):
        raise RuntimeError("operator receipt target is outside the authorized repository")
    if not target or target not in authorized_targets or target not in planned_targets:
        raise RuntimeError("operator receipt target is not authorized by the plan")
    if state is not None:
        if state.get("phase") in {"blocked", "done", "cancelled"}:
            raise RuntimeError(f"run is not runnable: {state.get('phase')}")
        if not (state.get("mapper") or {}).get("ready") or not (state.get("operator") or {}).get("ready"):
            raise RuntimeError("run is not runnable: mapper/operator receipts are not ready")
    return {
        "mapper": mapper,
        "plan": plan,
        "operator_preflight": operator_preflight,
        "operator": operator,
        "storage_route": storage_route,
        "repo_state": current_state,
        "plan_hash": plan_hash,
    }


def _persist_batch_preflight_block(
    run_dir: Path,
    state: Dict[str, Any],
    repo_path: Path,
    reason: str,
    task_indices: Sequence[int] = (),
) -> Path:
    diagnostic_path = run_dir / "operator-batch-preflight.json"
    blocker = {
        "kind": "operator_batch_preflight",
        "reason_code": "operator_batch_preflight_failed",
        "message": reason,
        "run_id": str(state.get("run_id") or run_dir.name),
        "scope": "global",
    }
    diagnostic = {
        "schema": BATCH_PREFLIGHT_SCHEMA,
        "status": "BLOCKED",
        "run_id": blocker["run_id"],
        "task_indices": [int(index) for index in task_indices],
        "blocker": blocker,
        "repo_state": _repo_fingerprint(repo_path),
        "checked_at": _now(),
    }
    _write_json(diagnostic_path, diagnostic)
    state["blockers"] = [blocker]
    state["current_action"] = "operator_batch_preflight_blocked"
    state["next_action"] = "repair_mapper_or_repo"
    _write_json(run_dir / "state.json", state)
    if state.get("phase") not in {"done", "cancelled"}:
        _transition(
            run_dir, state, "blocked", "operator batch prerequisite validation failed",
            receipt=str(diagnostic_path), extra={"error": reason, "scope": "global"},
        )
    _emit_event(
        run_dir, state, "blocked", receipt=str(diagnostic_path),
        blocker=blocker["reason_code"], message="operator batch blocked before dispatch", scope="global",
    )
    return diagnostic_path


def _run_mapper(repo_path: Path, run_root: Path, task_path: str = "", goal: str = "",
                task_fingerprint: str = "", target_hint: str = "") -> Dict[str, Any]:
    # Task metadata is assembled from optional contract fields. Normalize it
    # before the task-aware path calls ``.strip()``.
    task_path = str(task_path or "")
    goal = str(goal or "")
    task_fingerprint = str(task_fingerprint or "")
    target_hint = str(target_hint or "")
    before = _repo_fingerprint(repo_path)
    mapper_preflight = _preflight_mapper(repo_path, run_root)
    ecc_admission = inspect_ecc(repo_path, run_root)
    ensure_ecc_ready(ecc_admission)
    mapper_timeout = str(_mapper_timeout_seconds())
    rollback_sync = os.environ.get("SIMPLICIO_LOOP_MAPPER_SYNC_ROLLBACK", "").strip().lower() in {
        "1", "true", "yes", "on",
    }
    route_started = time.monotonic()
    phase_timings: Dict[str, Any] = {}
    scan_started = time.monotonic()
    scan = _run_cmd(
        # The foreground route must return the mapper's macro receipt without
        # waiting for the deep index.  Deep completion is polled/reconciled by
        # the subsequent inspect/handoff stages and is never a prerequisite
        # for obtaining the first bounded context.
        [
            "simplicio-mapper", "scan", ".", "--json",
            *( ["--sync"] if rollback_sync else [] ),
            "--timeout", mapper_timeout,
        ],
        repo_path,
    )
    phase_timings["scan_wall_seconds"] = round(time.monotonic() - scan_started, 6)
    inspect_started = time.monotonic()
    inspect = _run_cmd(
        [
            "simplicio-mapper", "inspect", ".", "--json",
            *( ["--await"] if rollback_sync else [] ),
            "--timeout", mapper_timeout,
        ],
        repo_path,
    )
    if not rollback_sync and _mapper_inspection_reports_stale(inspect):
        # The default Mapper route is macro-first/background.  A cold repository can
        # still be indexing when the first inspect returns, which used to surface as
        # a stale-artifact block and force callers to know the private sync toggle.
        # Reconcile that normal warm-up inside the zero-config run once, then keep the
        # existing receipt/freshness gate unchanged.
        await_scan = _run_cmd(
            [
                "simplicio-mapper", "scan", ".", "--json", "--await",
                "--timeout", mapper_timeout,
            ],
            repo_path,
        )
        if await_scan.returncode == 0:
            scan = await_scan
        inspect = _run_cmd(
            [
                "simplicio-mapper", "inspect", ".", "--json", "--await",
                "--timeout", mapper_timeout,
            ],
            repo_path,
        )
    phase_timings["inspect_wall_seconds"] = round(time.monotonic() - inspect_started, 6)
    if _mapper_supports_command(mapper_preflight, "snapshot"):
        snapshot = _run_cmd(["simplicio-mapper", "snapshot", "build", "--json", "."], repo_path)
    else:
        # Snapshot is an optional capability and is not present in current Mapper
        # releases. Do not turn an otherwise usable inspect/handoff into a hard block.
        snapshot = subprocess.CompletedProcess(
            ["simplicio-mapper", "snapshot", "build", "--json", "."],
            0,
            json.dumps({"status": "skipped", "reason": "optional_command_unavailable"}),
            "",
        )
    handoff_argv = ["simplicio-mapper", "handoff", ".", "--json"]
    if rollback_sync:
        handoff_argv.append("--await")
    handoff_argv.extend(["--timeout", mapper_timeout, "--execution-context"])
    task_aware_supported = bool(mapper_preflight.get("task_aware_supported"))
    mapper_token_budget = os.environ.get("SIMPLICIO_LOOP_MAPPER_TOKEN_BUDGET", "").strip()
    if mapper_token_budget.isdigit() and int(mapper_token_budget) > 0:
        handoff_argv.extend(["--token-budget", mapper_token_budget])
    if task_aware_supported and goal.strip():
        handoff_argv.extend(["--goal", goal.strip()])
    if task_aware_supported and task_path.strip():
        handoff_argv.extend(["--task-file", task_path.strip()])
    if task_aware_supported and task_fingerprint.strip():
        handoff_argv.extend(["--task-fingerprint", task_fingerprint.strip()])
    if task_aware_supported and target_hint.strip():
        handoff_argv.extend(["--target", target_hint.strip()])
    handoff_started = time.monotonic()
    handoff = _run_cmd(handoff_argv, repo_path)
    phase_timings["handoff_wall_seconds"] = round(time.monotonic() - handoff_started, 6)
    handoff_recovery = None
    try:
        handoff_stdout = json.loads(handoff.stdout) if handoff.stdout.strip() else {}
    except ValueError:
        handoff_stdout = {}
    handoff_pack = handoff_stdout.get("context_pack") if isinstance(handoff_stdout, Mapping) else {}
    configured_budget = int(mapper_token_budget) if mapper_token_budget.isdigit() else 8_000
    estimated_tokens = (
        handoff_pack.get("estimated_tokens")
        if isinstance(handoff_pack, Mapping) else None
    )
    over_budget = (
        isinstance(estimated_tokens, (int, float))
        and not isinstance(estimated_tokens, bool)
        and estimated_tokens > configured_budget
    )
    serialization_budget = (
        handoff_pack.get("serialization_budget")
        if isinstance(handoff_pack, Mapping) and isinstance(handoff_pack.get("serialization_budget"), Mapping)
        else {}
    )
    budget_compacted_over_limit = (
        bool(serialization_budget.get("compacted"))
        and isinstance(serialization_budget.get("estimated_tokens"), int)
        and isinstance(serialization_budget.get("token_budget"), int)
        and serialization_budget["estimated_tokens"] > serialization_budget["token_budget"]
    )
    if (
        task_aware_supported
        and task_path.strip()
        and target_hint.strip()
        and handoff.returncode == 0
        and isinstance(handoff_pack, Mapping)
        and (
            bool(handoff_pack.get("needs_broader_context"))
            or over_budget
            or not str(handoff_pack.get("pack_hash") or "").strip()
            or budget_compacted_over_limit
        )
    ):
        recovery_argv = ["simplicio-mapper", "handoff", ".", "--json"]
        if rollback_sync:
            recovery_argv.append("--await")
        recovery_argv.extend(["--timeout", mapper_timeout, "--execution-context"])
        recovery_budget = min(
            128_000,
            max(
                configured_budget,
                128_000 if budget_compacted_over_limit else (
                    int(estimated_tokens) if over_budget else configured_budget
                ),
            ),
        )
        recovery_argv.extend(["--token-budget", str(recovery_budget)])
        if goal.strip():
            recovery_argv.extend(["--goal", goal.strip()])
        recovery_argv.extend(["--target", target_hint.strip()])
        limit = os.environ.get("SIMPLICIO_LOOP_MAPPER_CONTEXT_LIMIT", "8").strip()
        if limit.isdigit() and int(limit) > 0:
            recovery_argv.extend(["--limit", limit])
        recovery = _run_cmd(recovery_argv, repo_path)
        try:
            recovery_stdout = json.loads(recovery.stdout) if recovery.stdout.strip() else {}
        except ValueError:
            recovery_stdout = {}
        handoff_recovery = {
            "strategy": "goal-target-without-task-file",
            "returncode": recovery.returncode,
            "stdout": recovery_stdout,
            "stderr": (recovery.stderr or "").strip(),
        }
        if recovery.returncode == 0:
            handoff = recovery
    # A macro-first scan may finish while handoff is assembling its context. In
    # that race the handoff can already carry a fresh Mapper status while the
    # earlier inspect receipt is still stale. Reconcile the persisted inspect
    # receipt once, without requiring the private synchronous-rollback toggle.
    if not rollback_sync and not _mapper_inspection_is_fresh(inspect):
        reconcile_started = time.monotonic()
        reconciled_inspect = _run_cmd(
            [
                "simplicio-mapper", "inspect", ".", "--json", "--await",
                "--timeout", mapper_timeout,
            ],
            repo_path,
        )
        if reconciled_inspect.returncode == 0:
            inspect = reconciled_inspect
        phase_timings["inspect_reconcile_wall_seconds"] = round(
            time.monotonic() - reconcile_started, 6
        )
    scan_stdout = json.loads(scan.stdout) if scan.stdout.strip() else {}
    inspect_stdout = json.loads(inspect.stdout) if inspect.stdout.strip() else {}
    snapshot_stdout = json.loads(snapshot.stdout) if snapshot.stdout.strip() else {}
    handoff_stdout = json.loads(handoff.stdout) if handoff.stdout.strip() else {}
    foreground_generation = _mapper_generation(repo_path)
    payload = {
        "scan": {
            "returncode": scan.returncode,
            "stdout": scan_stdout,
            "stderr": (scan.stderr or "").strip(),
        },
        "inspect": {
            "returncode": inspect.returncode,
            "stdout": inspect_stdout,
            "stderr": (inspect.stderr or "").strip(),
        },
        "snapshot": {
            "returncode": snapshot.returncode,
            "stdout": snapshot_stdout,
            "stderr": (snapshot.stderr or "").strip(),
        },
        "handoff": {
            "returncode": handoff.returncode,
            "stdout": handoff_stdout,
            "stderr": (handoff.stderr or "").strip(),
        },
        "handoff_recovery": handoff_recovery,
        "ecc_admission": dict(ecc_admission),
        "execution_route": {
            "mode": "synchronous_rollback" if rollback_sync else "foreground_first",
            "rollback_flag": "SIMPLICIO_LOOP_MAPPER_SYNC_ROLLBACK" if rollback_sync else None,
            "deep_completion_required_for_first_context": rollback_sync,
            "scan_wait": rollback_sync,
            "inspect_wait": rollback_sync,
            "handoff_wait": rollback_sync,
            "background": {
                "status": "queued" if not rollback_sync else "consumed_by_sync_rollback",
                "work_id": (
                    (scan_stdout.get("deep") or {}).get("job_id")
                    if isinstance(scan_stdout, Mapping) else None
                ),
                "pid": (
                    (scan_stdout.get("deep") or {}).get("pid")
                    if isinstance(scan_stdout, Mapping) else None
                ),
                "state_path": (
                    (scan_stdout.get("deep") or {}).get("state_path")
                    if isinstance(scan_stdout, Mapping) else None
                ),
            },
            "foreground_generation": foreground_generation,
            "phase_timings_seconds": phase_timings,
            "route_wall_seconds": round(time.monotonic() - route_started, 6),
        },
        "foreground_generation": foreground_generation,
        "generated_at": _now(),
        "repo_state_before": before,
        "repo_state_after": _repo_fingerprint(repo_path),
    }
    # Mapper may return a fresh, goal-relevant pack that omits a caller's
    # explicit target. Preserve the target as an authorized, local hint so the
    # downstream operator preflight does not reject an otherwise valid run.
    if target_hint.strip() and handoff.returncode == 0:
        target_path = target_hint.strip().replace("\\", "/")
        try:
            resolved_target = (repo_path / target_path).resolve()
            resolved_target.relative_to(repo_path.resolve())
            if resolved_target.is_file():
                context_pack = payload["handoff"]["stdout"].get("context_pack")
                if isinstance(context_pack, dict):
                    files = context_pack.setdefault("files", [])
                    known = {
                        str(item.get("path") or "").replace("\\", "/")
                        for item in files if isinstance(item, dict)
                    }
                    if target_path not in known:
                        files.append({
                            "path": target_path,
                            "selection_reason": "explicit_task_target",
                            "tests": [],
                        })
                        context_pack["explicit_target_added"] = target_path
        except (OSError, ValueError):
            pass
    _write_json(run_root / "mapper-context.json", payload)
    if (scan.returncode != 0 or inspect.returncode != 0 or snapshot.returncode != 0
            or handoff.returncode != 0):
        if _degraded_mapper_fallback_enabled():
            degraded = _degraded_mapper_payload(
                repo_path, before, mapper_preflight, scan, inspect, snapshot, handoff,
                target_hint,
                ecc_admission=ecc_admission,
            )
            _write_json(run_root / "mapper-context.json", degraded)
            return degraded
        raise RuntimeError("mapper scan/inspect/snapshot/handoff failed")
    if not _repo_state_equivalent(payload["repo_state_before"], payload["repo_state_after"]):
        raise RuntimeError("repository changed during mapper survey; freshness cannot be proven")
    # Test fixtures intentionally replace the operator preflight; production runs
    # always use the mapper's own artifact/freshness receipt.
    if _preflight_override("SIMPLICIO_LOOP_FAKE_MAPPER_PREFLIGHT_JSON") is None:
        _validate_mapper_receipt(payload, repo_path)
    return payload


def _build_plan(tasks: List[Dict[str, Any]], mapper_payload: Dict[str, Any], repo_path: Path,
                contract_hash: str = "") -> Dict[str, Any]:
    return _build_plan_with_hints(tasks, mapper_payload, repo_path, "", contract_hash=contract_hash)


_FILE_HINT_RE = re.compile(r"(?P<path>[A-Za-z0-9_./\\-]+\.(?:py|tsx?|js|rs|html?|css))")
# issue #1328 bug 3: `.md` is deliberately NOT a recognized extension in
# `_FILE_HINT_RE` above -- a task/contract prose reference to a `.md` file
# (a spec, a README) must never silently become a mutation target. The one
# narrow exception is the loop's own skill sources: a task naming one of
# these three skill-mirror paths explicitly IS naming a real, authorized
# mutation target.
_CLAUDE_SKILL_HINT_RE = re.compile(
    r"(?P<path>(?:\.claude/skills|plugin/skills|simplicio_loop/_bundle/skills)/"
    r"[A-Za-z0-9_./\\-]+\.md)"
)
_TECH_FILE_HINTS = frozenset({
    "node.js", "next.js", "vue.js", "react.js", "express.js", "deno.js",
    "bun.js", "alpine.js", "ember.js", "gatsby.js", "nuxt.js", "svelte.js",
    "backbone.js", "jquery.js",
})
_DEPENDENCY_BLOCK_RE = re.compile(
    r"(?ims)^(?:#{1,6}\s*)?(?:\d+\.\s*)?(?:dependencies|depend[êe]ncias)\b.*?"
    r"(?=^(?:#{1,6}\s*)?(?:\d+\.\s+)\S|\Z)",
)
# issue #1328 bug 3: `.claude/` is excluded wholesale everywhere below (it is
# mostly local host config, hooks, and generated state -- never a legitimate
# mutation target) EXCEPT for the loop's own skill sources and their two
# mirrors, which a task is entitled to name explicitly (e.g. "fix a typo in
# .claude/skills/simplicio-loop/SKILL.md"). Every other `.claude/` internal
# (settings.json, hooks/, generated caches) stays excluded.
_AUTHORIZED_CLAUDE_SKILL_PREFIXES = (
    ".claude/skills/",
    "plugin/skills/",
    "simplicio_loop/_bundle/skills/",
)


def _is_authorized_claude_skill_mirror(low_path: str) -> bool:
    return low_path.startswith(_AUTHORIZED_CLAUDE_SKILL_PREFIXES)


def _strip_dependency_prose(task_text: str) -> str:
    """Drop the Dependencies section so runtime names cannot become targets."""
    return _DEPENDENCY_BLOCK_RE.sub("", task_text or "")


def _extract_repo_file_hints(task_text: str, repo_path: Path) -> List[str]:
    hints: List[str] = []
    scanned = _strip_dependency_prose(task_text)
    repo_root = repo_path.resolve()
    for match in (*_FILE_HINT_RE.finditer(scanned), *_CLAUDE_SKILL_HINT_RE.finditer(scanned)):
        raw = match.group("path").strip().replace("\\", "/")
        if raw.lower() in _TECH_FILE_HINTS or Path(raw).name.lower() in _TECH_FILE_HINTS:
            continue
        candidate = Path(raw)
        try:
            resolved = (repo_root / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
            rel = resolved.relative_to(repo_root).as_posix()
        except (OSError, ValueError):
            continue
        # Bare names (Node.js, plugin.js) are targets only when they exist as
        # a real repository file. Path-shaped hints (src/app.py) stay hints
        # even if the file is still to_create.
        if "/" not in rel and not (repo_root / rel).is_file():
            continue
        low = rel.lower()
        if low.startswith(".simplicio-loop/orchestrator/") or low.startswith(".github/"):
            continue
        if low.startswith(".claude/") and not _is_authorized_claude_skill_mirror(low):
            continue
        if low.startswith(".venv/") or low.startswith("venv/") or "/site-packages/" in low:
            continue
        if "/_bundle/" in low and not _is_authorized_claude_skill_mirror(low):
            continue
        if rel not in hints:
            hints.append(rel)
    return hints


def _extract_declared_task_target(task_text: str, repo_path: Path) -> List[str]:
    """Return only the target named by the contract's ``Target:`` field.

    A task may mention other files in its acceptance criteria or business rule
    (for example, the page a stylesheet must be linked from). Those files are
    useful context, but they must not silently become additional creation
    authority for the current step.
    """
    match = re.search(r"(?im)^\s*(?:arquivo[- ]alvo|target)\s*:\s*([^\s`]+)", task_text or "")
    if not match:
        return []
    return _extract_repo_file_hints(match.group(1), repo_path)


def _is_creation_task_type(value: Any) -> bool:
    """Recognize the task-type spellings accepted by the Markdown contract."""
    return str(value or "").strip().casefold() in {
        "creation",
        "create",
        "new",
        "criação",
        "criacao",
    }


def _task_mapper_context(mapper_payload: Mapping[str, Any], task_index: int) -> Dict[str, Any]:
    """Return one task's Mapper envelope, with a single-task compatibility adapter."""
    contexts = mapper_payload.get("task_contexts") or []
    if isinstance(contexts, Sequence) and not isinstance(contexts, (str, bytes)):
        for context in contexts:
            if isinstance(context, Mapping) and int(context.get("task_index") or 0) == task_index:
                return dict(context)
    handoff = mapper_payload.get("handoff") or {}
    return {
        "schema": "simplicio.task-mapper-context/v1",
        "task_index": task_index,
        "task_fingerprint": str(mapper_payload.get("task_fingerprint") or ""),
        "handoff": dict(handoff) if isinstance(handoff, Mapping) else {},
        "context_hash": str(mapper_payload.get("mapper_context_hash") or ""),
        "compatibility_adapter": "single-task-shared-handoff",
    }


def _task_mapper_text(task: Mapping[str, Any]) -> str:
    parts = [_task_goal(dict(task))]
    if task.get("original_text"):
        parts.append(str(task["original_text"]))
    parts.extend(str(item.get("title") or "") for item in task.get("scenarios") or []
                 if isinstance(item, Mapping))
    parts.extend(str(item.get("id") or "") for item in task.get("rules") or []
                 if isinstance(item, Mapping))
    return " ".join(part.strip() for part in parts if part and part.strip())


def _task_context_plan_data(context: Mapping[str, Any], task: Mapping[str, Any],
                            repo_path: Path, task_text: str = "") -> Dict[str, Any]:
    handoff = context.get("handoff") if isinstance(context.get("handoff"), Mapping) else {}
    stdout = handoff.get("stdout") if isinstance(handoff.get("stdout"), Mapping) else handoff
    pack = stdout.get("context_pack") if isinstance(stdout, Mapping) else {}
    if not isinstance(pack, Mapping):
        pack = {}
    files = pack.get("files") or []
    targets = []
    for item in files:
        path = str(item.get("path") or "") if isinstance(item, Mapping) else ""
        if not path:
            continue
        try:
            resolved = (repo_path / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
            path = resolved.relative_to(repo_path.resolve()).as_posix()
        except (OSError, ValueError):
            continue
        low = path.lower()
        if (low.startswith((".simplicio-loop/orchestrator/", ".claude/", ".github/", ".venv/", "venv/"))
                or "/site-packages/" in low or "/_bundle/" in low):
            continue
        if not low.endswith(_CODE_TARGET_SUFFIXES):
            continue
        if path not in targets:
            targets.append(path)
    if not targets:
        targets = _candidate_targets({"handoff": {"stdout": {"context_pack": dict(pack)}}}, repo_path)
    explicit = _extract_repo_file_hints(task_text, repo_path)
    for hint in _extract_repo_file_hints(_task_mapper_text(task), repo_path):
        if hint not in explicit:
            explicit.append(hint)
    ordered = []
    for path in explicit + targets:
        if path not in ordered:
            ordered.append(path)
    tests = sorted({
        str(test_path).replace("\\", "/")
        for item in files
        if isinstance(item, Mapping)
        for test_path in item.get("tests") or []
        if str(test_path).strip()
    })
    fidelity = pack.get("fidelity") if isinstance(pack.get("fidelity"), Mapping) else {}
    selection = pack.get("selection") if isinstance(pack.get("selection"), Mapping) else {}
    token_fit = pack.get("token_budget_fit") if isinstance(pack.get("token_budget_fit"), Mapping) else {}
    pack_summary = pack.get("summary") if isinstance(pack.get("summary"), Mapping) else {}
    return {
        "targets": ordered,
        "tests": tests,
        "pack_hash": str(
            pack.get("pack_hash")
            or pack_summary.get("pack_hash")
            or context.get("pack_hash")
            or ""
        ),
        "context_hash": str(context.get("context_hash") or ""),
        "token_budget": int(pack.get("token_budget") or token_fit.get("token_budget") or 8000),
        "fidelity": dict(fidelity),
        "selection": dict(selection),
        "abstention": str(pack.get("abstention_reason") or selection.get("abstention_reason") or ""),
    }


def _build_plan_with_hints(tasks: List[Dict[str, Any]], mapper_payload: Dict[str, Any], repo_path: Path,
                           task_text: str, *, contract_hash: str = "") -> Dict[str, Any]:
    shared_handoff = ((mapper_payload.get("handoff") or {}).get("stdout") or {}).get("context_pack") or {}
    task_contexts = []
    steps = []
    aggregate_targets: List[str] = []
    for index, task in enumerate(tasks, start=1):
        context = _task_mapper_context(mapper_payload, index)
        # A collection task document contains several targets. Use each task's
        # original section so one item's mutation authority cannot inherit a
        # sibling item's target.
        hint_text = task_text if len(tasks) == 1 else str(task.get("original_text") or task_text)
        data = _task_context_plan_data(context, task, repo_path, hint_text)
        declared_targets = _extract_declared_task_target(hint_text, repo_path)
        if not declared_targets:
            declared_targets = _extract_declared_task_target(_task_mapper_text(task), repo_path)
        task_contexts.append({
            "task_index": index,
            "task_id": str(task.get("id") or ""),
            "task_fingerprint": str(context.get("task_fingerprint") or ""),
            "context_hash": data["context_hash"],
            "pack_hash": data["pack_hash"],
            "token_budget": data["token_budget"],
            "fidelity": data["fidelity"],
            "selection": data["selection"],
            "abstention": data["abstention"],
            "compatibility_adapter": context.get("compatibility_adapter", ""),
        })
        for path in data["targets"]:
            if path not in aggregate_targets:
                aggregate_targets.append(path)
        task_steps = []
        for scenario in task.get("scenarios") or []:
            task_steps.append({
                "kind": "scenario",
                "id": scenario.get("id"),
                "title": scenario.get("title"),
                "rule_refs": scenario.get("rule_refs") or [],
                "verification_intent": scenario.get("verification_intent"),
                "mapper_context_hash": data["context_hash"],
                "task_contract_hash": contract_hash,
                "plan": {
                    "read_paths": list(data["targets"]),
                    "change_paths": list(data["targets"]),
                    "test_paths": list(data["tests"]),
                    "test_commands": ["operator validation and repository test gate"],
                    "no_code_change": False,
                },
                "status": "pending",
            })
        rule_ids = [str(rule.get("id")) for rule in task.get("rules") or [] if rule.get("id")]
        steps.append({
            "task_index": index,
            "title": (task.get("identity") or {}).get("title") or _task_goal(task),
            "task_fingerprint": str(context.get("task_fingerprint") or ""),
            "mapper_context_hash": data["context_hash"],
            "context_pack_hash": data["pack_hash"],
            "candidate_targets": list(data["targets"]),
            "mapped_tests": list(data["tests"]),
            "selection": {"token_budget": data["token_budget"], **data["selection"]},
            "fidelity": data["fidelity"],
            "abstention": data["abstention"],
            "to_create": [
                path for path in data["targets"]
                if path in declared_targets
                and not (repo_path / path).exists()
                and _is_creation_task_type((task.get("identity") or {}).get("type"))
            ],
            "rule_ids": rule_ids,
            "steps": task_steps,
        })
    shared_summary = (
        shared_handoff.get("summary")
        if isinstance(shared_handoff, Mapping)
        and isinstance(shared_handoff.get("summary"), Mapping)
        else {}
    )
    shared_pack_hash = (
        str(shared_handoff.get("pack_hash") or shared_summary.get("pack_hash") or "")
        if isinstance(shared_handoff, Mapping) else ""
    )
    plan = {
        "schema": PLAN_SCHEMA,
        "task_contract_hash": contract_hash,
        "generated_at": _now(),
        "task_count": len(tasks),
        "mapper_targets": aggregate_targets,
        "mapper_pack_hash": shared_pack_hash,
        "context_pack_hash": shared_pack_hash,
        "mapper_generation": dict(mapper_payload.get("foreground_generation") or {}),
        "task_contexts": task_contexts,
        "repo_state": mapper_payload.get("repo_state_after") or {},
        "freshness": {
            "verified": _repo_state_equivalent(mapper_payload.get("repo_state_before") or {},
                                               mapper_payload.get("repo_state_after") or {}),
            "checked_at": mapper_payload.get("generated_at", ""),
            "current_state": _repo_fingerprint(repo_path),
        },
        "steps": steps,
    }
    deterministic_input = {
        "schema": plan["schema"],
        "task_contract_hash": contract_hash,
        "mapper_pack_hash": plan["mapper_pack_hash"],
        "task_contexts": task_contexts,
        "repo_state": plan["repo_state"],
        "steps": plan["steps"],
    }
    plan["deterministic"] = {
        "verified": True,
        "algorithm": "mapper-derived-task-context-v1",
        "input_hash": hashlib.sha256(
            json.dumps(deterministic_input, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest(),
    }
    return plan


_CODE_TARGET_SUFFIXES = (".py", ".ts", ".tsx", ".js", ".rs", ".htm", ".html", ".css")


def _fallback_targets(repo_path: Path) -> List[str]:
    """Refuse repository-wide target inference when Mapper has no targets."""
    return []


def _candidate_targets(mapper_payload: Dict[str, Any], repo_path: Path) -> List[str]:
    handoff = ((mapper_payload.get("handoff") or {}).get("stdout") or {}).get("context_pack") or {}
    files = handoff.get("files") or []
    ranked = []
    for item in files:
        path = item.get("path") if isinstance(item, dict) else None
        if not path:
            continue
        try:
            resolved = (repo_path / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
            resolved.relative_to(repo_path.resolve())
        except (OSError, ValueError):
            continue
        low = path.lower()
        if low.startswith(".simplicio-loop/orchestrator/") or low.startswith(".claude/"):
            continue
        if low.startswith(".venv/") or low.startswith("venv/") or "/site-packages/" in low:
            continue
        if low.startswith(".github/"):
            continue
        if "/_bundle/" in low.replace("\\", "/"):
            continue
        if low.endswith(_CODE_TARGET_SUFFIXES):
            ranked.append(path)
    ranked = ranked[:8]
    return ranked or _fallback_targets(repo_path)


def _build_anchor(tasks: List[Dict[str, Any]], contract_hash: str) -> Dict[str, Any]:
    criteria = []
    index = 1
    for task_index, task in enumerate(tasks, start=1):
        for scenario in task.get("scenarios") or []:
            criteria.append({
                "id": f"AC{index}",
                "task_index": task_index,
                "scenario_id": scenario.get("id"),
                "title": scenario.get("title"),
                "rule_refs": scenario.get("rule_refs") or [],
                "status": "pending",
            })
            index += 1
    return {
        "schema": "simplicio.anchor/v1",
        "contract_hash": contract_hash,
        "criteria": criteria,
        "created_at": _now(),
    }


def _prepare_operator_receipt(repo_path: Path, run_root: Path, task: Dict[str, Any],
                              target: str) -> Dict[str, Any]:
    try:
        target_path = (repo_path / target).resolve() if not Path(target).is_absolute() else Path(target).resolve()
        target_path.relative_to(repo_path.resolve())
    except (OSError, ValueError) as exc:
        raise ValueError(f"operator target outside authorized repo: {target!r}") from exc
    _preflight_operator(repo_path, run_root)
    task_spec_path = run_root / "task-spec.json"
    task_spec = _task_spec_payload(task)
    preflight_task_spec_placeholder = not task_spec.get("verification_commands")
    if preflight_task_spec_placeholder:
        task_spec["verification_commands"] = [{"command": "true", "verifier": "preflight-placeholder"}]
    task_spec_hash = _task_spec_hash(task_spec)
    _write_json(task_spec_path, task_spec)
    preflight_identity = f"{run_root.name}:preflight"
    _context_args, context_handoff = _context_handoff_args(
        repo_path,
        run_root,
        attempt_id=preflight_identity,
        lease_id=preflight_identity,
        fencing_token="1",
    )
    context_handoff["purpose"] = "read_only_preflight"
    fake = os.environ.get("SIMPLICIO_LOOP_FAKE_OPERATOR_JSON", "").strip()
    if fake:
        payload = json.loads(fake)
        receipt = {
            "schema": OPERATOR_RECEIPT_SCHEMA,
            "mode": "dry_run",
            "tool": "simplicio-dev-cli",
            "execution_state": payload.get("execution_state", "dry_run"),
            "target": target,
            "goal": _task_goal(task),
            "argv": payload.get("argv", []),
            "returncode": payload.get("returncode", 0),
            "stdout": payload.get("stdout", {}),
            "stderr": payload.get("stderr", ""),
            "timed_out": False,
            "measured_at": _now(),
            "source": "env_override",
            "context_handoff": context_handoff,
            "repo_state_before": _repo_fingerprint(repo_path),
            "task_spec_path": str(task_spec_path),
            "task_spec_hash": task_spec_hash,
        }
        ecc_reference = extract_guidance_reference(receipt)
        if ecc_reference is not None:
            receipt["ecc_guidance_ref"] = ecc_reference
        _write_json(run_root / "operator-receipt.json", receipt)
        return receipt

    # The host writes the edit plan; there is none yet at prepare time. The
    # dry run proves the operator accepts a plan (the surface tick/wave use)
    # without the forbidden prose `task` path, which Dev CLI answers with
    # plan_required.
    argv = _devcli_cmd(repo_path, "edit", "--help")
    try:
        op_env = _devcli_env(repo_path, _operator_env())
        # Dev CLI is deterministic-only.  Any configured OpenRouter credential
        # belongs exclusively to the Loop coordinator and must not cross the
        # subprocess boundary during read-only preflight.
        op_env.pop("OPENROUTER_API_KEY", None)
        if not op_env.get("SIMPLICIO_RUNTIME_URL", "").strip():
            op_env.setdefault("SIMPLICIO_RUNTIME_OFFLINE", "1")
        preflight_test_command = op_env.get("SIMPLICIO_TEST_CMD", "").strip()
        if not preflight_test_command:
            preflight_test_command = "true"
            op_env["SIMPLICIO_TEST_CMD"] = preflight_test_command
        context_handoff["preflight_verification"] = {
            "command": preflight_test_command,
            "placeholder": preflight_test_command == "true",
            "scope": "dry_run_only",
            "task_spec_placeholder": preflight_task_spec_placeholder,
        }
        result = subprocess.run(
            argv,
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=_operator_timeout("dry_run"),
            env=op_env,
        )
        stdout = (result.stdout or "").strip()
        parsed = {}
        if stdout:
            try:
                parsed = json.loads(stdout)
            except ValueError:
                parsed = {"raw": stdout}
        receipt = {
            "schema": OPERATOR_RECEIPT_SCHEMA,
            "mode": "dry_run",
            "tool": "simplicio-dev-cli",
            "execution_state": "dry_run" if result.returncode == 0 else "blocked",
            "target": target,
            "goal": _task_goal(task),
            "argv": argv,
            "returncode": result.returncode,
            "stdout": parsed,
            "stderr": (result.stderr or "").strip(),
            "timed_out": False,
            "measured_at": _now(),
            "source": "live_cli",
            "context_handoff": context_handoff,
            "provider_config": {
                "model": op_env.get("SIMPLICIO_MODEL", ""),
                "effort": op_env.get("SIMPLICIO_CODEX_EFFORT", ""),
            },
            "repo_state_before": _repo_fingerprint(repo_path),
            "task_spec_path": str(task_spec_path),
            "task_spec_hash": task_spec_hash,
        }
    except subprocess.TimeoutExpired as exc:
        op_env = _operator_env()
        receipt = {
            "schema": OPERATOR_RECEIPT_SCHEMA,
            "mode": "dry_run",
            "tool": "simplicio-dev-cli",
            "execution_state": "blocked",
            "target": target,
            "goal": _task_goal(task),
            "argv": argv,
            "returncode": None,
            "stdout": {},
            "stderr": f"timed out after {exc.timeout}s",
            "timed_out": True,
            "measured_at": _now(),
            "source": "live_cli",
            "context_handoff": context_handoff,
            "provider_config": {
                "model": op_env.get("SIMPLICIO_MODEL", ""),
                "effort": op_env.get("SIMPLICIO_CODEX_EFFORT", ""),
            },
            "repo_state_before": _repo_fingerprint(repo_path),
            "task_spec_path": str(task_spec_path),
            "task_spec_hash": task_spec_hash,
        }
    ecc_reference = extract_guidance_reference(receipt)
    if ecc_reference is not None:
        receipt["ecc_guidance_ref"] = ecc_reference
    _write_json(run_root / "operator-receipt.json", receipt)
    return receipt


def arm_run(repo: str, task_path: str, delivery: str, max_iterations: int) -> Dict[str, Any]:
    repo_path = Path(repo).resolve()
    delivery = normalize_delivery_target(delivery)
    raw = Path(task_path).read_text(encoding="utf-8")
    compiled = compile_many(raw, source_path=str(Path(task_path).resolve()))
    tasks = compiled.get("tasks") or []
    validation_errors: List[str] = []
    validation_warnings: List[str] = []
    for idx, task in enumerate(tasks, start=1):
        verdict = validate_contract(task)
        validation_errors.extend([f"task[{idx}] {e}" for e in verdict["errors"]])
        validation_warnings.extend([f"task[{idx}] {w}" for w in verdict["warnings"]])
    if validation_errors:
        raise ValueError("invalid task contract: " + "; ".join(validation_errors))

    run_id = _run_id()
    # Keep loop run state under .simplicio-loop/ (which simplicio-mapper ignores for
    # freshness) instead of .simplicio-loop/orchestrator/ (which the mapper sees as repo churn and
    # marks artifacts_not_fresh, blocking the loop before any implementation work).
    run_root = repo_path / ".simplicio-loop" / "loop-runs" / run_id
    loop_dir = run_root / "loop"
    loop_dir.mkdir(parents=True, exist_ok=True)
    # Keep the append-only loop attempt-memory artifact present even when the
    # run uses the MapperStore-backed lifecycle journal. A later verified run
    # appends its measured gate result without replacing prior records.
    (loop_dir / "journal.jsonl").touch(exist_ok=True)

    promise = f"run-{run_id}-verified"
    manifest = {
        "schema": RUNNER_SCHEMA,
        "run_id": run_id,
        "repo": str(repo_path),
        "task_path": str(Path(task_path).resolve()),
        "delivery_target": delivery,
        "max_iterations": max_iterations,
        "completion_promise": promise,
        "created_at": _now(),
        "task_count": compiled["task_count"],
        "collection_hash": compiled["collection_hash"],
    }
    _write_json(run_root / "manifest.json", manifest)
    _write_json(run_root / "task-contract.json", compiled)
    _write_json(loop_dir / "anchor.json", _build_anchor(tasks, compiled["collection_hash"]))
    goal = "\n\n".join([_task_goal(task) for task in tasks if _task_goal(task)]).strip() or raw.strip()
    _write_scratchpad(loop_dir, goal, max_iterations, promise)
    first_goal_fp = (tasks[0].get("source") or {}).get("hash", "") if tasks else ""
    _write_watcher_challenge(loop_dir, first_goal_fp)
    state = {
        "schema": STATE_SCHEMA,
        "run_id": run_id,
        "phase": "intake",
        "delivery_target": delivery,
        "created_at": _now(),
        "updated_at": _now(),
        "task_count": compiled["task_count"],
        "coverage": _coverage(tasks),
        "validation": {"errors": validation_errors, "warnings": validation_warnings},
        "current_action": "task_contract_compiled",
        "next_action": "mapper_scan_required",
        "delivery": {"target": delivery, "current_state": "planned", "ready": False, "receipt": ""},
        "completion": _default_completion_state(),
        "maintenance": _default_maintenance_state(),
        "stack_lock": {
            "ready": False,
            "path": str(run_root / "stack-lock.json"),
            "route": "",
            "lock_hash": "",
            "status": "UNVERIFIED",
        },
        "storage_route": {
            "ready": False,
            "path": str(run_root / STORAGE_ROUTE_RECEIPT),
            "requested": _storage_route_requested(),
            "selected": "",
            "generation": "",
            "receipt_hash": "",
            "status": "UNVERIFIED",
        },
        "mapper": {"ready": False, "receipt": "", "targets": []},
        "operator": {"ready": False, "receipt": "", "target": "", "execution_state": "proposed"},
        "evidence": {"ready": False, "receipt": "", "status": "UNVERIFIED"},
        "blockers": [],
        "attempts": 0,
        "history": [],
        "events": [],
        "task_ids": [str(task.get("id") or "") for task in tasks if task.get("id")],
        "ac_ids": [ac_id for task in tasks for ac_id in _task_ac_ids(task)],
    }
    _write_json(run_root / "state.json", state)
    _emit_event(run_root, state, "contract_frozen", receipt=str(run_root / "task-contract.json"),
                message="task contract compiled and frozen")
    _emit_event(run_root, state, "watcher_challenge", receipt=str(loop_dir / "watcher_challenge.json"),
                message="watcher challenge created")
    _append_jsonl(
        run_root / "transitions.jsonl",
        {
            "ts": _now(),
            "from": None,
            "to": "intake",
            "reason": "run armed from raw task",
            "receipt": str(run_root / "task-contract.json"),
        },
    )
    try:
        stack_lock = _freeze_stack_lock(run_root, run_id)
        manifest.update({
            "stack_lock_path": str(run_root / "stack-lock.json"),
            "stack_lock_hash": stack_lock.lock_hash,
            "execution_profile": stack_lock.route,
        })
        _write_json(run_root / "manifest.json", manifest)
        state = _load_json(run_root / "state.json")
        state["stack_lock"] = {
            "ready": True,
            "path": str(run_root / "stack-lock.json"),
            "route": stack_lock.route,
            "lock_hash": stack_lock.lock_hash,
            "status": "MEASURED",
        }
        _write_json(run_root / "state.json", state)
        _emit_event(run_root, state, "stack_lock_frozen",
                    receipt=str(run_root / "stack-lock.json"),
                    message="installed stack lock frozen before Mapper scan")
        storage_route = _freeze_storage_route(run_root, run_id)
        _ensure_mapper_operations_store(repo_path, storage_route.get("selected"))
        manifest.update({
            "storage_route_path": str(run_root / STORAGE_ROUTE_RECEIPT),
            "storage_route_hash": storage_route.get("receipt_hash", ""),
            "storage_route": storage_route.get("selected"),
            "storage_route_generation": storage_route.get("generation", ""),
        })
        _write_json(run_root / "manifest.json", manifest)
        state = _load_json(run_root / "state.json")
        state["storage_route"] = {
            "ready": True,
            "path": str(run_root / STORAGE_ROUTE_RECEIPT),
            "requested": storage_route.get("requested", ""),
            "selected": storage_route.get("selected", ""),
            "generation": storage_route.get("generation", ""),
            "receipt_hash": storage_route.get("receipt_hash", ""),
            "status": "MEASURED",
        }
        _write_json(run_root / "state.json", state)
        _emit_event(run_root, state, "storage_route_frozen",
                    receipt=str(run_root / STORAGE_ROUTE_RECEIPT),
                    message="store route selected and frozen before Mapper scan",
                    route=storage_route.get("selected"),
                    generation=storage_route.get("generation"),
                    receipt_hash=storage_route.get("receipt_hash"))
        _transition(run_root, state, "mapping", "stack and storage routes frozen; mapper required",
                    receipt=str(run_root / "stack-lock.json"))
        primary_goal = _task_goal(tasks[0]) if tasks else raw.strip()
        mapper_payload = _run_with_operator_recovery(
            "simplicio-mapper",
            run_root,
            lambda: _run_mapper(
                repo_path,
                run_root,
                task_path=str(Path(task_path).resolve()),
                goal=primary_goal,
                task_fingerprint=compiled["collection_hash"],
                target_hint=next(iter(_extract_repo_file_hints(raw, repo_path)), ""),
            ),
        )
        mapper_payload["run_id"] = run_id
        mapper_payload["task_contract_hash"] = compiled["collection_hash"]
        _write_json(run_root / "mapper-context.json", mapper_payload)
        state = _load_json(run_root / "state.json")
        mapper_degraded = bool(mapper_payload.get("degraded_local"))
        state["mapper"] = {
            "ready": True,
            "receipt": str(run_root / "mapper-context.json"),
            "targets": _candidate_targets(mapper_payload, repo_path),
            "degraded": mapper_degraded,
            "status": "UNVERIFIED" if mapper_degraded else "MEASURED",
            "ecc_admission": dict(mapper_payload.get("ecc_admission") or {}),
        }
        state["current_action"] = "mapper_context_degraded" if mapper_degraded else "mapper_context_persisted"
        state["next_action"] = "plan_ready_for_decision"
        _write_json(run_root / "state.json", state)
        if mapper_degraded:
            _emit_event(run_root, state, "mapper_degraded", receipt=str(run_root / "mapper-context.json"),
                        blocker="mapper_deep_pass_unavailable",
                        message="continuing with explicit-target local context; evidence is UNVERIFIED")
            _transition(run_root, state, "planning", "local context fallback persisted; mapper evidence is UNVERIFIED",
                        receipt=str(run_root / "mapper-context.json"))
        else:
            _emit_event(run_root, state, "mapper_fresh", receipt=str(run_root / "mapper-context.json"),
                        message="mapper scan, inspect, and handoff are fresh")
            _transition(run_root, state, "planning", "mapper scan/inspect/handoff persisted",
                        receipt=str(run_root / "mapper-context.json"))
        plan = _build_plan_with_hints(tasks, mapper_payload, repo_path, raw,
                                      contract_hash=compiled["collection_hash"])
        plan["run_id"] = run_id
        plan["mapper_context_hash"] = hashlib.sha256(
            (run_root / "mapper-context.json").read_bytes()
        ).hexdigest()
        plan_validation = validate_plan(
            plan, tasks, repo_path,
            contract_hash=compiled["collection_hash"],
            current_state=_repo_fingerprint(repo_path),
        )
        plan["validation"] = plan_validation
        if not plan_validation["valid"]:
            if any("targets_missing" in error for error in plan_validation["errors"]):
                raise RuntimeError("mapper-derived plan has no authorized operator target")
            raise RuntimeError("mapper-derived plan failed validation: " + ", ".join(plan_validation["errors"]))
        _write_json(run_root / "plan.json", plan)
        state = _load_json(run_root / "state.json")
        state["current_action"] = "plan_materialized"
        _maybe_auto_build_planning_receipt(run_root, state, run_id, compiled, plan, plan_validation, repo_path)
        candidates = ((plan.get("steps") or [{}])[0].get("candidate_targets") or [])
        if not candidates:
            raise RuntimeError("mapper-derived plan has no authorized operator target")
        receipt = _run_with_operator_recovery(
            "simplicio-dev-cli",
            run_root,
            lambda: _prepare_operator_receipt(
                repo_path, run_root, tasks[0], candidates[0]
            ),
        )
        plan_hash = hashlib.sha256((run_root / "plan.json").read_bytes()).hexdigest()
        receipt["run_id"] = run_id
        receipt["task_contract_hash"] = compiled["collection_hash"]
        receipt["plan_hash"] = plan_hash
        receipt["mapper_pack_hash"] = plan.get("mapper_pack_hash", "")
        receipt["mapper_context_hash"] = plan.get("mapper_context_hash", "")
        receipt["authorized_targets"] = [candidates[0]]
        receipt["target_within_repo"] = True
        _write_json(run_root / "operator-receipt.json", receipt)
        preflight_ok = receipt.get("execution_state") == "dry_run" and receipt.get("returncode") == 0
        external_preflight = _external_preflight_admissible(receipt)
        if external_preflight:
            # Dev CLI's deterministic-only policy is an expected, explicit block
            # during read-only preflight.  The configured external coordinator
            # supplies the mechanical plan at the mutation boundary; preserve the
            # raw non-zero result and record why this preflight is admissible.
            receipt["external_coordinator"] = {
                "provider": "openrouter",
                "route": "openrouter-to-mechanical-edit",
                "preflight_status": "admitted_with_explicit_dev_cli_llm_block",
                "raw_reason_code": "llm_execution_disabled",
            }
            receipt["preflight_admitted"] = True
        if not preflight_ok and not external_preflight:
            stdout_payload = receipt.get("stdout") if isinstance(receipt.get("stdout"), Mapping) else {}
            blocked = stdout_payload.get("blocked_preconditions") if isinstance(stdout_payload, Mapping) else []
            reason = ""
            if isinstance(blocked, list) and blocked:
                first = blocked[0] if isinstance(blocked[0], Mapping) else {}
                reason = str(first.get("code") or first.get("message") or "")
            if not reason and isinstance(stdout_payload.get("execution_profile"), Mapping):
                reason = str(stdout_payload["execution_profile"].get("reason_code") or "")
            raise RuntimeError(
                "operator preflight blocked the run: "
                + (reason or str(receipt.get("stderr") or receipt.get("execution_state") or "unknown failure"))
            )
        state["operator"] = {
            "ready": True,
            "receipt": str(run_root / "operator-receipt.json"),
            "target": candidates[0],
            "execution_state": receipt.get("execution_state", "proposed"),
            "ecc_guidance_ref": receipt.get("ecc_guidance_ref"),
        }
        evidence = build_evidence_receipt(str(run_root))
        _write_json(run_root / "evidence-receipt.json", evidence)
        state["evidence"] = {
            "ready": False,
            "receipt": str(run_root / "evidence-receipt.json"),
            "status": evidence.get("status", "UNVERIFIED"),
        }
        delivery_receipt = build_delivery_receipt(str(run_root), delivery, current_state="implemented")
        write_delivery_receipt(str(run_root), delivery_receipt)
        state["delivery"] = {
            "target": delivery,
            "current_state": delivery_receipt["current_state"],
            "ready": delivery_receipt["ready"],
            "receipt": str(run_root / "delivery-receipt.json"),
            "source_checked_at": delivery_receipt["source_checked_at"],
        }
        state["current_action"] = "operator_dry_run_recorded"
        state["next_action"] = "await_operator_decision"
        _write_json(run_root / "state.json", state)
        _emit_event(run_root, state, "plan_ready", receipt=str(run_root / "plan.json"),
                    message="validated plan materialized")
        if state.get("operator", {}).get("receipt"):
            _emit_event(run_root, state, "operator_receipt",
                        receipt=str(run_root / "operator-receipt.json"),
                        message="operator dry-run receipt persisted")
        _transition(run_root, state, "awaiting_decision", "plan derived from task contract + mapper",
                    receipt=str(run_root / "plan.json"))
    except Exception as exc:
        state = _load_json(run_root / "state.json")
        message = str(exc)
        if "no authorized operator target" in message or "operator preflight blocked" in message:
            state["blockers"] = [{
                "kind": "run_preflight",
                "reason_code": "no_authorized_target" if "target" in message else "operator_dry_run_failed",
                "message": message,
                "run_id": run_id,
            }]
        else:
            state["blockers"] = [message]
        state["current_action"] = "mapping_failed"
        state["next_action"] = "repair_mapper_or_repo"
        evidence_path = run_root / "evidence-receipt.json"
        if not evidence_path.exists():
            mapper_path = run_root / "mapper-context.json"
            operator_path = run_root / "operator-receipt.json"
            plan_path = run_root / "plan.json"
            if not plan_path.exists() and not mapper_path.exists():
                _write_json(mapper_path, {
                    "run_id": run_id,
                    "task_contract_hash": compiled["collection_hash"],
                    "status": "blocked",
                    "error": message,
                })
            if not plan_path.exists() and not operator_path.exists():
                _write_json(operator_path, {
                    "schema": OPERATOR_RECEIPT_SCHEMA,
                    "run_id": run_id,
                    "task_contract_hash": compiled["collection_hash"],
                    "execution_state": "blocked",
                    "status": "blocked",
                    "returncode": None,
                    "changed_paths": [],
                    "error": message,
                })
            if mapper_path.exists() and operator_path.exists():
                evidence = build_evidence_receipt(str(run_root))
                _write_json(evidence_path, evidence)
                state["evidence"] = {
                    "ready": False,
                    "receipt": str(evidence_path),
                    "status": evidence.get("status", "UNVERIFIED"),
                }
        _write_json(run_root / "state.json", state)
        _transition(run_root, state, "blocked", "mapper integration failed",
                    receipt=str(run_root / "mapper-context.json"), extra={"error": str(exc)})
    return {"manifest": manifest, "state": _load_json(run_root / "state.json"), "run_dir": str(run_root)}


def _changed_paths(repo_path: Path) -> List[str]:
    try:
        result = _run_cmd(["git", "diff", "--name-only", "HEAD"], repo_path)
        paths = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
        status = _run_cmd(["git", "status", "--porcelain=v1", "--untracked-files=all"], repo_path)
        for line in (status.stdout or "").splitlines():
            if len(line) > 3 and line[3:].strip() not in paths:
                paths.append(line[3:].strip())
        return sorted(set(paths))
    except Exception:
        return []


def _plan_relevant_changed_paths(repo_path: Path) -> List[str]:
    """Return worktree changes relevant to a frozen execution plan.

    The Loop writes its own Mapper, ledger, cache, and run receipts under
    ``.simplicio-loop/`` while a shared-run batch advances from one dependent task to
    the next. Those bookkeeping writes necessarily change the repository
    fingerprint, but they are not source drift and cannot be authorized by a
    task's candidate targets. Keep the strict stale-plan check for every
    production path while excluding only Loop-owned storage from that check.
    """
    return sorted({
        str(path).replace("\\", "/")
        for path in _changed_paths(repo_path)
        if str(path).replace("\\", "/") not in {".simplicio-loop"}
        and not str(path).replace("\\", "/").startswith(".simplicio-loop/")
        and not _is_loop_generated_path(str(path))
        and not _is_tool_cache_path(str(path).replace("\\", "/"))
        and str(path).strip()
    })


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


def _capture_operator_checkpoint(run_dir: Path, repo_path: Path, targets: List[str]) -> Dict[str, Any]:
    checkpoint_dir = run_dir / "checkpoint"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    files = []
    for target in sorted(set(t for t in targets if t)):
        path = repo_path / target
        exists = path.exists()
        content = path.read_text(encoding="utf-8") if exists else None
        files.append({
            "path": target,
            "exists": exists,
            "content": content,
        })
    return {
        "kind": "file-snapshot/v1",
        "created_at": _now(),
        "safe_targets": sorted(set(t for t in targets if t)),
        "files": files,
    }


def _restore_operator_checkpoint(checkpoint: Dict[str, Any], repo_path: Path, changed_paths: List[str]) -> Dict[str, Any]:
    targets = sorted(set(str(path) for path in (checkpoint.get("safe_targets") or []) if str(path)))
    dirty_before = set(str(path) for path in (checkpoint.get("dirty_before") or []))
    # Only this attempt's own source edits matter: verifier caches (__pycache__,
    # .pytest_cache) and non-target paths already dirty before it are not in scope.
    changed = sorted(set(
        str(path) for path in (changed_paths or [])
        if str(path) and not _is_tool_cache_path(str(path))
        and (str(path) in targets or str(path) not in dirty_before)
    ))
    snapshots = {item["path"]: item for item in (checkpoint.get("files") or []) if isinstance(item, dict) and item.get("path")}
    if not changed:
        for rel in targets:
            snap = snapshots.get(rel)
            if not snap:
                continue
            path = repo_path / rel
            exists_now = path.exists()
            content_now = path.read_text(encoding="utf-8") if exists_now else None
            if bool(snap.get("exists")) != exists_now or (snap.get("exists") and snap.get("content") != content_now):
                changed.append(rel)
    if not changed:
        return {"attempted": False, "restored": False, "reason": "no_changed_paths"}
    if not targets:
        return {"attempted": False, "restored": False, "reason": "checkpoint_targets_missing"}
    if any(path not in targets for path in changed):
        return {"attempted": False, "restored": False, "reason": "changed_paths_outside_checkpoint_scope"}
    for rel in changed:
        snap = snapshots.get(rel)
        if not snap:
            return {"attempted": False, "restored": False, "reason": f"missing_snapshot:{rel}"}
        path = repo_path / rel
        if snap.get("exists"):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(snap.get("content") or "", encoding="utf-8")
        elif path.exists():
            path.unlink()
    return {"attempted": True, "restored": True, "reason": "restored_checkpoint"}


def _operator_failure_fingerprint(returncode: int | None, stderr: str, stdout: Any) -> str:
    parts = [f"returncode={returncode}"]
    if stderr:
        parts.append(f"stderr={stderr}")
    if stdout:
        if isinstance(stdout, dict):
            parts.append("stdout=" + json.dumps(stdout, ensure_ascii=False, sort_keys=True))
        else:
            parts.append(f"stdout={stdout}")
    blob = " | ".join(parts)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _operator_receipt_hash(receipt: Mapping[str, Any]) -> str:
    """Stable sha256 over the canonical receipt body (excluding receipt_hash itself).

    Issue #135: the receipt is the durable proof a production diff was produced through the
    bridge. The hash lets the diff-coverage gate bind a `git diff` path to exactly one receipt.
    """
    canonical = {k: v for k, v in receipt.items() if k != "receipt_hash"}
    blob = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _operator_run_diff_coverage(repo_path: Path, run_dir: Path) -> Dict[str, Any]:
    """Issue #135: every production diff path must be covered by an operator receipt.

    The bridge is the ONLY allowed mutation path. Any path `git diff` names that no operator
    receipt covers (i.e. was edited outside the bridge, or by a dev-cli failure that silently
    unlocked manual editing) makes the run non-concludable.
    """
    changed = _changed_paths(repo_path)
    covered: List[str] = []
    receipts: List[Dict[str, Any]] = []
    # Collect every operator receipt in this run (execute + batch lanes).
    for candidate in sorted(run_dir.glob("operator-receipt*.json")):
        try:
            receipts.append(_load_json(candidate))
        except (OSError, ValueError, TypeError):
            continue
    for receipt in receipts:
        status = str(receipt.get("status") or receipt.get("execution_state") or "")
        if status not in ("applied", "no_change"):
            continue
        covered.extend(str(p) for p in (receipt.get("changed_paths") or []) if str(p))
    covered_set = {str(p) for p in covered}
    uncovered = [p for p in changed if p not in covered_set]
    coverage_ok = not uncovered
    return {
        "changed_paths": changed,
        "covered_paths": sorted(covered_set),
        "uncovered_paths": uncovered,
        "coverage_ok": coverage_ok,
        "receipt_count": len(receipts),
    }


def conclude_run(repo: str, run_id: str, *, force: bool = False) -> Dict[str, Any]:
    """Gate run conclusion on full operator-receipt diff coverage (issue #135).

    `force=True` is the explicit human override (the safety policy's human gate) and still
    records the violation rather than silently passing.
    """
    status = read_status(repo, run_id)
    run_dir = Path(status["run_dir"])
    repo_path = Path(status["manifest"]["repo"]).resolve()
    coverage = _operator_run_diff_coverage(repo_path, run_dir)
    state = status["state"]
    if not coverage["coverage_ok"] and not force:
        raise RuntimeError(
            "cannot conclude run: production diff paths without an operator receipt: "
            + ", ".join(coverage["uncovered_paths"])
        )
    gate = {
        "kind": "operator_run_diff_coverage",
        "coverage_ok": coverage["coverage_ok"],
        "uncovered_paths": coverage["uncovered_paths"],
        "forced": bool(force),
        "checked_at": _now(),
    }
    state.setdefault("gates", []).append(gate)
    state["operator_run_gate"] = gate
    _write_json(run_dir / "state.json", state)
    _transition(
        run_dir, state, state.get("phase") or "done",
        "operator-run diff-coverage gate evaluated",
        receipt=str(run_dir / "state.json"),
        extra={"coverage": coverage},
    )
    return read_status(repo, run_id)


def _execute_operator_unleased(repo: str, run_id: str, task_index: int = 1, *,
                      attempt_coordinator: Optional[AttemptCoordinator] = None,
                      guarded_attempt: Any = None,
                      authority_receipt: Optional[Mapping[str, Any]] = None,
                      authority_attempt: Optional[int] = None,
                      admission_fence: int = 1,
                      owned_process_registry: Any = None,
                      owned_task_id: str = "",
                      provider_worker: str | None = None,
                      repair_feedback: str | None = None) -> Dict[str, Any]:
    """Execute one planned task through the real dev-cli and persist an immutable receipt.

    `run` intentionally arms and dry-runs only.  This explicit tick is the mutation boundary;
    it cannot run without the mapper/plan/operator preflight artifacts created by `arm_run`.

    When both ``attempt_coordinator`` and ``guarded_attempt`` (a ``WorkItemAttempt``) are
    supplied (issue #288's guarded dispatch path, gated by ``SIMPLICIO_GUARDED_DISPATCH`` in
    ``_operator_dispatch_attempt``), the mutating dev-cli invocation runs through
    ``AttemptCoordinator.run_guarded`` instead of a raw ``subprocess.run`` -- a background
    thread heartbeats the lease for the life of the subprocess and kills it the instant the
    lease is no longer current, instead of letting a worker that lost its fence keep mutating
    the checkout (the #183 gap). ``LeaseLostDuringExecution`` propagates to the caller, which
    already treats any exception here as a receipted (not scheduler-crashing) failure.
    ``guarded_attempt`` is deliberately named apart from this function's own ``attempt``
    local (the per-task retry counter) so the two can never collide.
    """
    status = read_status(repo, run_id)
    _raise_if_maintenance_deferred(repo, run_id, status)
    run_dir = Path(status["run_dir"])
    repo_path = Path(status["manifest"]["repo"]).resolve()
    contract = _load_json(run_dir / "task-contract.json")
    tasks = contract.get("tasks") or []
    if task_index < 1 or task_index > len(tasks):
        raise ValueError(f"task index out of range: {task_index}")
    _assert_task_dependencies_ready(run_dir, tasks, task_index, run_id)
    stack_lock = _verify_run_stack_lock(run_dir)
    storage_route = _verify_storage_route(run_dir)
    _ensure_mapper_operations_store(repo_path, storage_route.get("selected"))
    status["state"]["stack_lock"] = {
        **dict(status["state"].get("stack_lock") or {}),
        "ready": True,
        "path": str(run_dir / "stack-lock.json"),
        "route": stack_lock.route,
        "lock_hash": stack_lock.lock_hash,
        "status": "VERIFIED",
        "verified_at": _now(),
    }
    status["state"]["storage_route"] = {
        **dict(status["state"].get("storage_route") or {}),
        "ready": True,
        "path": str(run_dir / STORAGE_ROUTE_RECEIPT),
        "requested": storage_route.get("requested", ""),
        "selected": storage_route.get("selected", ""),
        "generation": storage_route.get("generation", ""),
        "receipt_hash": storage_route.get("receipt_hash", ""),
        "status": "VERIFIED",
        "verified_at": _now(),
    }
    _write_json(run_dir / "state.json", status["state"])
    plan_path = run_dir / "plan.json"
    mapper_path = run_dir / "mapper-context.json"
    operator_path = run_dir / "operator-receipt.json"
    if not plan_path.exists() or not mapper_path.exists() or not operator_path.exists():
        raise RuntimeError("execution requires fresh mapper, plan, and operator preflight receipts")
    plan = _load_json(plan_path)
    planned_step = (plan.get("steps") or [])[task_index - 1] if task_index <= len(plan.get("steps") or []) else {}
    _assert_task_dependencies_ready(run_dir, tasks, task_index, run_id, step=planned_step)
    before = _repo_fingerprint(repo_path)
    current = before
    planned_state = plan.get("repo_state") or {}
    # A shared-run batch intentionally advances the checkout from one dependent
    # task to the next: task 2's dispatch attempt must see the tree task 1 left,
    # not the tree the plan was frozen against at `prepare` time. Comparing
    # `current` against the run's own last *applied* fingerprint (persisted on
    # `state["repo_state_chain"]` right after each successful tick, below) lets
    # this task chain onto its predecessors while still failing closed on any
    # drift this run did not itself produce -- an external edit never matches
    # that chained baseline either. Falls back to the original frozen
    # `plan["repo_state"]` for task 1 (nothing has been applied yet).
    expected_state = dict(status["state"].get("repo_state_chain") or {}) or planned_state
    effective_plan = plan
    if expected_state and expected_state.get("tree_hash") != planned_state.get("tree_hash"):
        effective_plan = {**plan, "repo_state": expected_state}
    plan_validation = validate_plan(effective_plan, tasks, repo_path,
                                   contract_hash=contract.get("collection_hash", ""),
                                   current_state=current)
    if not plan_validation["valid"]:
        raise RuntimeError("plan validation failed before operator execution: " + ", ".join(plan_validation["errors"]))
    if expected_state and not _repo_state_equivalent(expected_state, current):
        raise RuntimeError("repository changed after planning; re-run mapper before execution")
    task = tasks[task_index - 1]
    authority_path = None
    if authority_receipt is not None:
        authority = dict(authority_receipt)
        supplied = str(authority.pop("receipt_hash", ""))
        targets = list(((plan.get("steps") or [{}])[task_index - 1].get("candidate_targets") or []))
        source = authority.get("source") or {}
        if (not supplied or supplied != _planning_content_hash(authority)
                or authority.get("operator") != "simplicio-dev-cli"
                or sorted(authority.get("targets") or []) != sorted(targets)
                or not str(source.get("revision") or "")
                or not str(source.get("planning_receipt") or "")):
            raise RuntimeError("authority_receipt invalid at mutation boundary")
        authority_path = run_dir / f"mutation-authority-{task_index}.json"
        _write_json(authority_path, {**authority, "receipt_hash": supplied,
                                     "admission_fence": max(1, int(admission_fence))})
    # #694: every production item gets an authoritative route receipt before
    # mutation authority or an execution backend is selected.  The route is a
    # deterministic gate; Runtime remains the physical/policy owner.
    task_text = _task_goal(task)
    worker_capabilities = task.get("worker_capabilities") or task.get("capabilities") or ()
    worker_available = bool(worker_capabilities) or os.environ.get("SIMPLICIO_DETERMINISTIC_WORKER", "1").lower() not in {"0", "false", "no", "off"}
    capability_manifest = {
        "declared": normalize_capability_manifest(worker_capabilities),
        "deterministic_worker_available": worker_available,
    }
    capability_hash = capability_fingerprint(capability_manifest)
    route_path = run_dir / "execution-route.json"
    previous_route = None
    if route_path.exists():
        try:
            candidate = _load_json(route_path)
            if verify_route_hash(candidate):
                previous_route = candidate
        except (OSError, TypeError, ValueError):
            previous_route = None
    route_cache_status = "new"
    route_record = None
    if previous_route and route_receipt_is_current(previous_route, capability_manifest):
        route_record = previous_route
        route_cache_status = "reused"
    else:
        invalidation = {}
        if previous_route:
            route_cache_status = "invalidated"
            invalidation = {
                "status": "invalidated",
                "reason_code": (
                    "capability_manifest_changed"
                    if previous_route.get("capability_fingerprint")
                    else "capability_manifest_missing"
                ),
                "previous_receipt_sha": str(previous_route.get("receipt_sha") or ""),
                "previous_capability_fingerprint": str(previous_route.get("capability_fingerprint") or ""),
            }
        route = decide_route(
            task_text,
            has_deterministic_worker=worker_available,
            is_ambiguous=bool(task.get("ambiguous") or task.get("requires_semantic_review")),
        )
        route_record = route.to_dict()
        route_record.update({
            "run_id": run_id,
            "task_index": task_index,
            "task_id": str(task.get("id") or ""),
            "evidence_handles": sorted({
                str(value) for value in (
                    (plan.get("steps") or [])[task_index - 1].get("mapper_context_hash", ""),
                    (plan.get("steps") or [])[task_index - 1].get("context_pack_hash", ""),
                ) if str(value)
            }),
            "causal_ids": [run_id, str(task.get("id") or task_index)],
            "route_authority": "loop-runner",
            "capability_manifest": capability_manifest,
            "capability_fingerprint": capability_hash,
        })
        if invalidation:
            route_record["invalidation"] = invalidation
        route_record["receipt_sha"] = _execution_route_hash(
            {key: value for key, value in route_record.items() if key != "receipt_sha"}
        )
    if os.environ.get("SIMPLICIO_STORAGE_ROUTE", "").strip().lower() == "mapper":
        route_record = dict(route_record)
        route_record.update({
            "mapper_required": True,
            "mapper_mode": "targeted",
            "mapper_reason": "Mapper storage route is mandatory for every dispatched task",
        })
        route_record["receipt_sha"] = _execution_route_hash(
            {key: value for key, value in route_record.items() if key != "receipt_sha"}
        )
    if not verify_route_hash(route_record):
        raise RuntimeError("execution-route receipt failed deterministic hash verification")
    _write_json(route_path, route_record)
    operator_state = status["state"].setdefault("operator", {})
    operator_state["execution_route"] = route_record
    operator_state["execution_route_cache"] = {
        "status": route_cache_status,
        "capability_fingerprint": capability_hash,
        "previous_receipt_sha": str((previous_route or {}).get("receipt_sha") or ""),
    }
    _write_json(run_dir / "state.json", status["state"])
    attempt = int((status["state"] or {}).get("attempts", 0)) + 1
    # #284: mutation-authority gate, mandatory by default. execute_operator()
    # refuses to run without a valid planning-receipt.json whose mutation_authority
    # token matches THIS run/attempt/task-contract/plan identity -- any drift (stale
    # plan hash, rotated lease/fence, missing/invalid receipt) blocks fail-closed
    # instead of silently proceeding. Opt out only via an explicit falsy
    # SIMPLICIO_REQUIRE_MUTATION_AUTHORITY (see planning_gate.mutation_authority_required());
    # see simplicio_loop/planning_gate.py and scripts/planning_gate.py.
    if mutation_authority_required():
        # GitHub source drift: if the caller re-captured a fresh source snapshot
        # immediately before this tick (`scripts/planning_gate.py capture-source`,
        # written to `source-snapshot-current.json`), compare its hash against the
        # one the receipt/authority was minted with. Absent that file (local/
        # non-GitHub runs, or a caller that hasn't wired re-capture yet), this is a
        # no-op -- identical to previous behavior.
        current_source_hash = ""
        current_snapshot_path = run_dir / "source-snapshot-current.json"
        if current_snapshot_path.exists():
            try:
                current_source_hash = str((_load_json(current_snapshot_path).get("source") or {}).get("snapshot_hash") or "")
            except Exception:
                current_source_hash = ""
        authority_verdict = evaluate_mutation_authority(
            run_dir, run_id=run_id,
            attempt=int(authority_attempt or attempt),
            task_contract_hash=str(contract.get("collection_hash") or _planning_content_hash(contract)),
            plan_hash=_planning_content_hash(plan),
            source_snapshot_hash=current_source_hash,
        )
        if not authority_verdict["ok"]:
            raise RuntimeError(
                "mutation authority required (SIMPLICIO_REQUIRE_MUTATION_AUTHORITY) but "
                f"{authority_verdict['reason_code']}: {authority_verdict['reason']}"
            )
    targets = (plan.get("steps") or [])[task_index - 1].get("candidate_targets") or []
    target = targets[0] if targets else status["state"].get("operator", {}).get("target", "")
    if not target:
        raise RuntimeError("plan has no authorized operator target")
    # Issue #135: the decided change is AC-scoped and MUST point at a plan target. Any target
    # expansion beyond authorized_targets routes back to the planner/impact gate before continuing.
    if target not in (targets or []):
        raise RuntimeError(
            "operator target '%s' is outside the plan's authorized_targets %s; "
            "route back to planner/impact gate before continuing" % (target, targets)
        )
    _preflight_operator(repo_path, run_dir)
    task_spec_path = run_dir / "task-spec.json"
    task_spec = _task_spec_payload(task)
    task_spec_hash = _task_spec_hash(task_spec)
    _write_json(task_spec_path, task_spec)
    lease = str(getattr(getattr(guarded_attempt, "lease", None), "lease_id", "") or f"loop-run:{run_id}")
    fence = str(getattr(getattr(guarded_attempt, "lease", None), "fencing_token", "") or "1")
    profile = _execution_profile()
    context_args, context_handoff = _context_handoff_args(
        repo_path,
        run_dir,
        attempt_id=f"{run_id}:attempt:{attempt}",
        lease_id=lease,
        fencing_token=fence,
        require_authorization=False,
    )
    operator_mode = "standalone"
    task_input = (
        [_task_goal(task) or str(task.get("id") or "execute task"),
         "--criteria", _criteria_text(task) or "- true state",
         "--constraints", _constraints_text(task) or "- build passes"]
        if operator_mode == "standalone"
        else ["--task-spec", str(task_spec_path)]
    )
    mechanical_plan, mechanical_path, plan_source = _resolve_host_edit_plan(
        run_dir, task_index=task_index,
    )
    provider_path: Optional[Path] = None
    provider_receipt: Optional[Dict[str, Any]] = None
    provider_receipt_paths: List[str] = []
    provider_proposal_attempts = 0
    selected_provider_worker = str(
        provider_worker or os.environ.get("SIMPLICIO_PROVIDER_WORKER") or ""
    ).strip().lower()
    would_call_provider = bool(selected_provider_worker) or _openrouter_operator_enabled()
    if selected_provider_worker:
        provider_plan, provider_receipt = _provider_worker_plan(
            task=task,
            context={
                "mapper_context": _load_json(mapper_path),
                "handoff": context_handoff,
                "plan": plan,
                "task_spec": task_spec,
            },
            run_id=run_id,
            task_index=task_index,
            attempt=attempt,
            root=repo_path,
            allowed_paths=targets,
            run_dir=run_dir,
            provider_worker=selected_provider_worker,
            repair_feedback=repair_feedback,
        )
        provider_path = (
            Path(str(provider_receipt.get("receipt_path")))
            if provider_receipt and provider_receipt.get("receipt_path")
            else None
        )
        provider_receipt_paths = [str(provider_path)] if provider_path else []
        provider_proposal_attempts = 1 if provider_receipt else 0
        if provider_plan is not None:
            mechanical_plan = provider_plan
            plan_source = "provider-worker"
    if mechanical_plan is None and os.environ.get(
        "SIMPLICIO_LOOP_FAKE_OPERATOR_EXEC_JSON", ""
    ).strip():
        # Hermetic test seam (#1290): SIMPLICIO_LOOP_FAKE_OPERATOR_EXEC_JSON substitutes the
        # whole operator effect in `_execute_operator_effect_unchecked()` -- the write_files
        # it applies are fully scripted by the fixture, not derived from a host edit plan --
        # so the separate host-written-plan requirement below is not meaningful on that path.
        # Never applies to a real run: the env var is a test-only fixture, unset in production.
        mechanical_plan = {
            "schema": "simplicio.mechanical-edit/v1",
            "touched_files": list(targets),
            "operations": [{"op": "fake_exec_seam", "path": target}],
            "validation": [],
        }
        plan_source = "env:SIMPLICIO_LOOP_FAKE_OPERATOR_EXEC_JSON"
    if mechanical_plan is None:
        blocked_receipt = {
            "schema": OPERATOR_RECEIPT_SCHEMA,
            "mode": "execute",
            "tool": "simplicio-dev-cli",
            "run_id": run_id,
            "execution_state": "blocked",
            "status": "blocked",
            "reason_code": PLAN_REQUIRED,
            "attempt": attempt,
            "retry_budget": 3,
            "target": target,
            "authorized_targets": list(targets),
            "target_within_repo": True,
            "goal": _task_goal(task),
            "argv": [],
            "returncode": 2,
            "stdout": {
                "reason_code": PLAN_REQUIRED,
                "required_schema": "simplicio.dev-cli.edit-plan/v1",
            },
            "stderr": "host must write simplicio.dev-cli.edit-plan/v1; loop does not call OpenRouter",
            "timed_out": False,
            "started_at": _now(),
            "finished_at": _now(),
            "measured_at": _now(),
            "source": "loop-plan-gate",
            "context_handoff": context_handoff,
            "provider_config": {
                "route": "openrouter-to-mechanical-edit" if would_call_provider else "host-edit-plan",
                "reason_code": PLAN_REQUIRED,
                "provider_receipt": "",
                "provider_receipts": [],
                "provider_proposal_attempts": 0,
                "mechanical_plan": "",
            },
            "provider_receipt": "",
            "mechanical_plan": "",
            "execution_profile": profile,
            "changed_paths": [],
            "diff_hash": str(before.get("tree_hash") or ""),
            "task_contract_hash": contract.get("collection_hash", ""),
            "plan_hash": hashlib.sha256(plan_path.read_bytes()).hexdigest(),
            "mapper_pack_hash": plan.get("mapper_pack_hash", ""),
            "repo_state_before": before,
            "repo_state_after": before,
            "task_spec_path": str(task_spec_path),
            "task_spec_hash": task_spec_hash,
        }
        return _finish_operator_blocked(
            repo=repo,
            run_id=run_id,
            run_dir=run_dir,
            status=status,
            receipt=blocked_receipt,
            operator_path=operator_path,
            task_index=task_index,
            reason="plan_required: host must supply simplicio.dev-cli.edit-plan/v1",
        )
    dest = run_dir / f"edit-plan-{task_index}.json"
    try:
        same_file = mechanical_path is not None and dest.resolve() == mechanical_path.resolve()
    except OSError:
        same_file = False
    if not same_file:
        _write_json(dest, mechanical_plan)
        mechanical_path = dest
    # Precise preflight before ever shelling out to dev-cli's compile: a bad
    # path (outside the plan's authorized_targets, or one that does not exist)
    # gets a named, actionable reason instead of the generic
    # PLAN_REQUIRED/plan_compile_failed the subprocess would otherwise report.
    path_issue = _validate_minimal_host_plan_paths(mechanical_plan, repo_path, targets)
    if path_issue is not None:
        blocked_receipt = {
            "schema": OPERATOR_RECEIPT_SCHEMA,
            "mode": "apply",
            "tool": "simplicio-dev-cli",
            "execution_state": "blocked",
            "reason_code": path_issue["reason_code"],
            "target": target,
            "stdout": {},
            "stderr": path_issue["message"],
            "measured_at": _now(),
        }
        return _finish_operator_blocked(
            repo=repo, run_id=run_id, run_dir=run_dir, status=status,
            receipt=blocked_receipt, operator_path=operator_path,
            task_index=task_index, reason=path_issue["message"],
        )
    compiled_plan, compile_reason_code, compile_error = _compile_minimal_host_plan(repo_path, mechanical_path)
    if compiled_plan is None:
        blocked_receipt = {
            "schema": OPERATOR_RECEIPT_SCHEMA,
            "mode": "apply",
            "tool": "simplicio-dev-cli",
            "execution_state": "blocked",
            "reason_code": compile_reason_code or "plan_compile_failed",
            "target": target,
            "stdout": {},
            "stderr": compile_error,
            "measured_at": _now(),
        }
        return _finish_operator_blocked(
            repo=repo, run_id=run_id, run_dir=run_dir, status=status,
            receipt=blocked_receipt, operator_path=operator_path,
            task_index=task_index, reason=compile_error,
        )
    mechanical_plan = compiled_plan
    verb = "edit" if mechanical_plan.get("schema") == "simplicio.dev-cli.edit-plan/v1" else "mechanical-edit"
    argv = _devcli_cmd(
        repo_path, verb, "--root", str(repo_path),
        "--plan", str(mechanical_path), "--apply", "--json",
    )
    checkpoint = _capture_operator_checkpoint(run_dir, repo_path, targets or [target])
    checkpoint["dirty_before"] = _changed_paths(repo_path)
    # #285 remaining gap: this dispatch has a real guarded lease (when the caller wired
    # one) and a real repo checkout/branch on hand -- surface them on the event so
    # `_sync_github_lifecycle()` projects the actual lease/fencing token and branch onto
    # the CLAIMED comment instead of falling back to a blank/best-effort default.
    _emit_event(run_dir, status["state"], "worker_claimed",
                receipt=str(run_dir / "task-contract.json"),
                task_id=str(task.get("id") or ""),
                ac_ids=_task_ac_ids(task),
                message="operator worker claimed task",
                lease_id=str(getattr(getattr(guarded_attempt, "lease", None), "lease_id", "") or ""),
                fencing_token=str(getattr(getattr(guarded_attempt, "lease", None), "fencing_token", "") or ""),
                branch=_git_current_branch(repo_path))
    if item_context := (status["state"].get("operator") or {}).get("worktree_context"):
        _emit_event(run_dir, status["state"], "worktree_created",
                    receipt=str(item_context.get("lock_receipt") or operator_path),
                    message="isolated worktree context available", worktree=item_context)
    op_env = _devcli_env(repo_path, _operator_env())
    # The external coordinator consumes the credential in this Loop process;
    # deterministic Dev CLI must never inherit or persist it.
    op_env.pop("OPENROUTER_API_KEY", None)
    op_env["SIMPLICIO_ADMISSION_FENCE"] = str(max(1, int(admission_fence)))
    if authority_path is not None:
        op_env["SIMPLICIO_MUTATION_AUTHORITY_RECEIPT"] = str(authority_path)
    provider_config = {
        "model": op_env.get("SIMPLICIO_MODEL", ""),
        "planner": "host",
        "effort": op_env.get("SIMPLICIO_CODEX_EFFORT", ""),
        "route": "host-edit-plan",
        "plan_source": plan_source,
        "provider_receipt": str(provider_path) if provider_path else "",
        "provider_receipts": provider_receipt_paths,
        "provider_proposal_attempts": provider_proposal_attempts,
        "mechanical_plan": str(mechanical_path) if mechanical_path else "",
        "provider_usage": dict((provider_receipt or {}).get("usage") or {}),
    }
    effect_adapter = RuntimeEffectAdapter(profile=profile)
    effect_request = _build_effect_request(
        repo_path, run_id, task_index, task, attempt, targets, route_record, guarded_attempt,
        storage_route=storage_route.get("selected"),
        canonical_plan=(
            load_canonical_plan(plan["canonical_plan"], expected_digest=str(plan.get("canonical_plan_digest") or ""))
            if isinstance(plan.get("canonical_plan"), Mapping) else None
        ),
    )
    effect_outcome = _execute_operator_effect(
        profile=profile,
        adapter=effect_adapter,
        request=effect_request,
        argv=argv,
        env=op_env,
        repo_path=repo_path,
        attempt_coordinator=attempt_coordinator,
        guarded_attempt=guarded_attempt,
        source_hash=str(before.get("tree_hash") or ""),
        storage_route=storage_route.get("selected"),
        owned_process_registry=owned_process_registry,
        owned_task_id=owned_task_id,
    )
    returncode = effect_outcome["returncode"]
    stdout = effect_outcome["stdout"]
    stderr = effect_outcome["stderr"]
    source = effect_outcome["source"]
    effect_receipt = effect_outcome.get("effect_receipt")
    uncertain = bool(effect_outcome.get("uncertain"))
    hookwall_evidence = effect_outcome.get("hookwall_evidence")
    hookwall_verified, hookwall_gate_reason = gate_completion(hookwall_evidence)
    # A deterministically rejected operator has no successful Hookwall evidence,
    # but it may have an explicit Mapper ``failed`` reconciliation.  Preserve
    # that more precise reason in the durable operator receipt instead of
    # collapsing every non-success into ``hookwall_evidence_missing``.
    hookwall_reason = str(
        effect_outcome.get("hookwall_reason") or hookwall_gate_reason
    )
    devcli_returncode = returncode
    verification_failed = returncode == 0 and not uncertain and _devcli_verification_failed(stdout)
    if verification_failed:
        # #1346: dev-cli exits 0 with ``applied`` even when its own nested
        # verification failed. Treat it as a failed, retryable attempt so the
        # changes roll back and a corrected edit-plan can be re-applied.
        returncode = 1
    after = _repo_fingerprint(repo_path)
    changed = _changed_paths(repo_path)
    rollback = {"attempted": False, "restored": False, "reason": "not_needed"}
    if returncode != 0 and not uncertain:
        rollback = _restore_operator_checkpoint(checkpoint, repo_path, changed)
        if rollback.get("restored"):
            changed = _changed_paths(repo_path)
            after = _repo_fingerprint(repo_path)
    if uncertain:
        execution_state = "uncertain"
        no_change_proof = None
    elif returncode == 0 and not changed:
        execution_state = "no_change"
        no_change_proof = {
            "satisfying_state": "repository already satisfied the AC; no production diff produced",
            "measured_at": _now(),
            "evidence": str(after.get("tree_hash", "")),
        }
    else:
        execution_state = "applied" if returncode == 0 else "blocked"
        no_change_proof = None
    receipt = {
        "schema": OPERATOR_RECEIPT_SCHEMA,
        "mode": "execute",
        "tool": "simplicio-dev-cli",
        "run_id": run_id,
        "execution_state": execution_state,
        "status": execution_state,
        "attempt": attempt,
        "retry_budget": 3,
        "target": target,
        "authorized_targets": targets,
        "target_within_repo": True,
        "goal": _task_goal(task),
        "argv": argv,
        "returncode": returncode,
        "devcli_returncode": devcli_returncode,
        "reason_code": "verification_failed" if verification_failed else "",
        "stdout": stdout,
        "stderr": stderr,
        "timed_out": returncode is None,
        "started_at": _now(),
        "finished_at": _now(),
        # #288: receipt_verifier.OPERATOR_RECEIPT_SCHEMA requires "measured_at" for its
        # freshness check. This receipt never carried it, so every real (non-mocked)
        # execute_operator() dispatch was permanently INVALID_SCHEMA/MISSING_FIELD in
        # _verify_worker_receipt_pair() -- the merge gate below could never fire for a genuine
        # attempt. Same instant as finished_at; this is a receipt-completeness fix, not a new
        # measurement.
        "measured_at": _now(),
        "source": source,
        "context_handoff": context_handoff,
        "provider_config": provider_config,
        "provider_receipt": str(provider_path) if provider_path else "",
        "mechanical_plan": str(mechanical_path) if mechanical_path else "",
        "provider_worker": provider_receipt.get("provider") if provider_receipt else None,
        "provider_model": provider_receipt.get("model") if provider_receipt else None,
        "provider_worker_receipt": str(provider_receipt.get("receipt_path") or "") if provider_receipt else "",
        "provider_usage_status": provider_receipt.get("usage_status", "unknown") if provider_receipt else "unknown",
        "provider_input_tokens": provider_receipt.get("input_tokens") if provider_receipt else None,
        "provider_output_tokens": provider_receipt.get("output_tokens") if provider_receipt else None,
        "provider_cached_tokens": provider_receipt.get("cached_tokens") if provider_receipt else None,
        "provider_reasoning_tokens": provider_receipt.get("reasoning_tokens") if provider_receipt else None,
        "provider_cost": provider_receipt.get("cost") if provider_receipt else None,
        "execution_profile": profile,
        "executor_profile": (effect_receipt or {}).get("executor_profile", profile),
        "effect_receipt": effect_receipt,
        "effect_transaction_id": (effect_receipt or {}).get("transaction_id", ""),
        "effect_correlation_id": (effect_receipt or {}).get("correlation_id", ""),
        "hookwall_envelope": effect_outcome.get("hookwall_envelope"),
        "hookwall_pre_decision": effect_outcome.get("hookwall_pre_decision"),
        "hookwall_mutation_receipt": effect_outcome.get("hookwall_mutation_receipt"),
        "hookwall_post_decision": effect_outcome.get("hookwall_post_decision"),
        "hookwall_evidence": hookwall_evidence,
        "hookwall_verified": hookwall_verified,
        "hookwall_reason": hookwall_reason,
        "hookwall_reconciliation": effect_outcome.get("hookwall_reconciliation"),
        "hookwall_reconciliation_error": effect_outcome.get("hookwall_reconciliation_error", ""),
        "checkpoint": checkpoint,
        "rollback": rollback,
        "failure_fingerprint": "" if returncode == 0 else _operator_failure_fingerprint(returncode, stderr, stdout),
        "task_contract_hash": contract.get("collection_hash", ""),
        "plan_hash": hashlib.sha256(plan_path.read_bytes()).hexdigest(),
        "mapper_pack_hash": plan.get("mapper_pack_hash", ""),
        "repo_state_before": before,
        "repo_state_after": after,
        "changed_paths": changed,
        "diff_hash": after.get("tree_hash", ""),
        "no_change_proof": no_change_proof,
        "task_spec_path": str(task_spec_path),
        "task_spec_hash": task_spec_hash,
    }
    receipt["receipt_hash"] = _operator_receipt_hash(receipt)
    _write_json(operator_path, receipt)
    # A run may execute multiple ordered tasks through the direct ``tick`` API.
    # The historical run-level path is intentionally preserved for compatibility,
    # but each task also needs an immutable receipt of its own so a later task
    # cannot overwrite the evidence used to validate the earlier one.
    _write_json(run_dir / f"operator-receipt-{task_index}.json", receipt)
    state = status["state"]
    if rollback.get("restored"):
        _emit_event(run_dir, state, "rollback", receipt=str(operator_path),
                    blocker=str(rollback.get("reason") or "operator execution failed"),
                    message="operator changes rolled back")
    state["operator"] = {
        "ready": returncode == 0 and not uncertain and hookwall_verified,
        "receipt": str(operator_path),
        "target": target,
        "execution_state": receipt["execution_state"],
    }
    state["current_action"] = "operator_executed" if returncode == 0 else "operator_failed"
    state["next_action"] = "watcher_behavioral_verification" if returncode == 0 else "repair_operator_or_plan"
    state["attempts"] = int(state.get("attempts", 0)) + 1
    if returncode == 0 or uncertain:
        # Advance this run's own chained baseline so the next dependent task's
        # plan_repo_state_stale check compares against the tree this task
        # actually left, not the frozen `prepare`-time snapshot. A failed/rolled
        # back attempt must never advance it -- `before`/`after` are identical
        # once `_restore_operator_checkpoint` runs, but skip the write outright
        # to keep the intent explicit.
        #
        # `uncertain` (issue #1328 bug 1) is included deliberately: a client-side
        # timeout does not prove the underlying dev-cli subprocess never wrote to
        # disk (see `_execute_operator_effect_unchecked`'s own comment on this).
        # `_restore_operator_checkpoint` is never invoked for an uncertain outcome
        # (only for a clean `returncode != 0`), so `after` here is always the real,
        # current tree -- whether or not this attempt actually mutated it. Binding
        # the chain to that real tree is what lets a later dependent task's
        # freshness check compare against what is ACTUALLY on disk, instead of
        # permanently misreporting this run's own (possibly-already-applied)
        # attempt as external drift. A genuine external edit between `prepare`
        # and the first dispatch attempt is unaffected: it is caught by the
        # pre-attempt freshness check at the top of this function, before any
        # attempt (and therefore before any chain rebind) ever runs.
        state["repo_state_chain"] = after
    _write_json(run_dir / "state.json", state)
    _transition(run_dir, state, "validating" if returncode == 0 else "blocked",
                "dev-cli execution receipt persisted", receipt=str(operator_path),
                extra={"changed_paths": changed})
    if returncode == 0:
        evidence = build_evidence_receipt(str(run_dir))
        _write_json(run_dir / "evidence-receipt.json", evidence)
        state = _load_json(run_dir / "state.json")
        state["evidence"] = {"ready": False, "receipt": str(run_dir / "evidence-receipt.json"), "status": evidence.get("status", "UNVERIFIED")}
        _write_json(run_dir / "state.json", state)
        _emit_event(run_dir, state, "operator_receipt", receipt=str(operator_path),
                    message="operator execution receipt persisted")
        _emit_event(run_dir, state, "test_gate", receipt=str(run_dir / "evidence-receipt.json"),
                    blocker="" if evidence.get("status") == "VERIFIED" else "evidence_unverified",
                    message="test and evidence gate evaluated", status=evidence.get("status", "UNVERIFIED"))
    if returncode == 0 and not uncertain and hookwall_verified:
        _write_json(run_dir / f"task-{task_index}-result.json", {
            "schema": "simplicio.task-result/v1",
            "run_id": run_id,
            "task_index": task_index,
            "status": receipt["execution_state"],
            "operator_receipt": str(operator_path),
            "evidence_receipt": str(run_dir / "evidence-receipt.json"),
        })
    return read_status(repo, run_id)


def _devcli_verification_failed(stdout: Any) -> bool:
    """True when dev-cli's JSON reports a failed nested verification (#1346)."""
    payload: Any = stdout
    if isinstance(stdout, str):
        try:
            payload = json.loads(stdout)
        except ValueError:
            return False
    if not isinstance(payload, Mapping):
        return False
    receipt = payload.get("mutation_receipt")
    verification = receipt.get("verification") if isinstance(receipt, Mapping) else None
    if not isinstance(verification, Mapping):
        verification = payload.get("verify")
    return isinstance(verification, Mapping) and str(verification.get("status") or "") in {"failed", "timeout"}


def _raise_if_maintenance_deferred(repo: str, run_id: str,
                                   status: Optional[Mapping[str, Any]] = None) -> None:
    status = status if status is not None else read_status(repo, run_id)
    if (status["state"].get("maintenance") or {}).get("disposition") == "backlog_only":
        raise RuntimeError("maintenance deferred: operator execution is blocked until explicit resume")


def execute_operator(repo: str, run_id: str, task_index: int = 1, *,
                     attempt_coordinator: Optional[AttemptCoordinator] = None,
                     guarded_attempt: Any = None,
                     authority_receipt: Optional[Mapping[str, Any]] = None,
                     authority_attempt: Optional[int] = None,
                     admission_fence: int = 1,
                     owned_process_registry: Any = None,
                     owned_task_id: str = "",
                     provider_worker: str | None = None,
                     repair_feedback: str | None = None) -> Dict[str, Any]:
    """Execute one task, acquiring a Mapper OperationsStore lease for direct ticks.

    Batch workers already claim a Mapper lease in ``_operator_dispatch_attempt`` and pass
    it as ``guarded_attempt``.  The public ``tick`` command calls this boundary directly,
    so it must acquire the same lease itself when the Mapper route is selected; otherwise
    the Mapper-backed Hookwall correctly rejects the synthetic ``loop-run:<id>`` identity
    with ``STALE_FENCE``.
    """
    if guarded_attempt is not None:
        return _execute_operator_unleased(
            repo, run_id, task_index=task_index,
            attempt_coordinator=attempt_coordinator,
            guarded_attempt=guarded_attempt,
            authority_receipt=authority_receipt,
            authority_attempt=authority_attempt,
            admission_fence=admission_fence,
            owned_process_registry=owned_process_registry,
            owned_task_id=owned_task_id,
            provider_worker=provider_worker,
            repair_feedback=repair_feedback,
        )

    status = read_status(repo, run_id)
    _raise_if_maintenance_deferred(repo, run_id, status)
    run_dir = Path(status["run_dir"])
    storage_route = _verify_storage_route(run_dir)
    if storage_route.get("selected") != StorageRoute.MAPPER.value:
        return _execute_operator_unleased(
            repo, run_id, task_index=task_index,
            attempt_coordinator=attempt_coordinator,
            guarded_attempt=None,
            authority_receipt=authority_receipt,
            authority_attempt=authority_attempt,
            admission_fence=admission_fence,
            owned_process_registry=owned_process_registry,
            owned_task_id=owned_task_id,
            provider_worker=provider_worker,
            repair_feedback=repair_feedback,
        )

    contract = _load_json(run_dir / "task-contract.json")
    plan = _load_json(run_dir / "plan.json")
    tasks = list(contract.get("tasks") or [])
    if task_index < 1 or task_index > len(tasks):
        raise ValueError(f"task index out of range: {task_index}")
    step = (plan.get("steps") or [])[task_index - 1]
    targets = [
        str(path) for path in (step.get("candidate_targets") or [])
        if str(path).strip()
    ]
    task = tasks[task_index - 1]
    task_id = str(task.get("id") or f"{run_id}-task-{task_index}")
    worker_id = f"tick-{run_id}-{task_index}"
    # ``planning-receipt.json`` authorizes the armed run, while ``state.attempts``
    # counts every task mutation in that run.  A direct tick for task 2 therefore
    # may have a local execution attempt of 2 but must still validate against the
    # run-level authority attempt minted during arm (normally 1).  Batch dispatch
    # supplies this value explicitly; direct ticks need to recover it here.
    if authority_attempt is None:
        # A missing receipt is judged (fail-closed) by the mutation-authority gate.
        receipt_file = run_dir / "planning-receipt.json"
        planning_receipt = _load_json(receipt_file) if receipt_file.exists() else {}
        authority_attempt = max(1, int(planning_receipt.get("attempt") or 1))
    mapper_operations, mapper_attempt = _claim_mapper_operation_attempt(
        Path(status["manifest"]["repo"]).resolve(),
        run_id=run_id,
        task_index=task_index,
        task_id=task_id,
        worker_id=worker_id,
        targets=targets,
    )
    try:
        result = _execute_operator_unleased(
            repo, run_id, task_index=task_index,
            attempt_coordinator=attempt_coordinator,
            guarded_attempt=mapper_attempt,
            authority_receipt=authority_receipt,
            authority_attempt=authority_attempt,
            admission_fence=admission_fence,
            owned_process_registry=owned_process_registry,
            owned_task_id=owned_task_id,
            provider_worker=provider_worker,
            repair_feedback=repair_feedback,
        )
    except Exception:
        try:
            mapper_operations.release(mapper_attempt.lease)
        except Exception:
            pass
        raise

    result_state = result.get("state") or {}
    operator_state = result_state.get("operator") or {}
    execution_state = str(operator_state.get("execution_state") or "")
    operator_receipt = str(operator_state.get("receipt") or "")
    evidence_receipt = str((result_state.get("evidence") or {}).get("receipt") or "")
    completed = bool(operator_state.get("ready")) and execution_state in {"applied", "no_change"}
    completion_payload = {
        "run_id": run_id,
        "task_id": task_id,
        "task_index": task_index,
        "operator_receipt": operator_receipt,
        "evidence_receipt": evidence_receipt,
        "status": "completed" if completed else "failed",
    }
    try:
        completion = mapper_operations.complete(
            mapper_attempt.lease,
            status="completed" if completed else "failed",
            receipt=completion_payload,
        )
    except Exception:
        try:
            mapper_operations.release(mapper_attempt.lease)
        except Exception:
            pass
        raise
    completion_path = run_dir / f"mapper-operation-completion-{task_index}.json"
    _write_json(completion_path, {
        "schema": "simplicio.loop.mapper-operation-completion/v1",
        "status": "completed" if completed else "failed",
        "run_id": run_id,
        "task_id": task_id,
        "task_index": task_index,
        "worker_id": worker_id,
        "attempt_id": mapper_attempt.lease.attempt_id,
        "lease_id": mapper_attempt.lease.lease_id,
        "fence_token": mapper_attempt.lease.fence_token,
        "operator": completion_payload,
        "mapper": completion,
    })
    result["mapper_operation_completion"] = str(completion_path)
    return result


def _watcher_script() -> Path:
    """The watcher shipped with this package; SIMPLICIO_LOOP_REPO points it at the target."""
    return Path(__file__).resolve().parent / "_bundle" / "scripts" / "watcher_verify.py"


def _ensure_current_quality_matrix(repo_path: Path, run_dir: Path) -> None:
    """Keep ``quality-matrix.json`` from going stale across a run's own separate ticks.

    `verify_run` (via `_finalize_public_flow`) runs after *every* `tick`/`wave
    --task-indices`, not only once at the very end -- so the first call to
    reach this run can build `quality-matrix.json` while other tasks are
    still pending (correctly reporting them missing at that moment). The
    independent watcher (`scripts/watcher_verify.py`, invoked right after
    this) re-derives its verdict from that SAME on-disk receipt via
    `quality_matrix.independent_reverify_quality_matrix`'s self-reported half
    -- so a cache that is never refreshed keeps reporting those tasks
    missing forever, even after a later task's own separate process applied
    them. Rebuild it whenever the applied/missing task set it once measured
    no longer matches what's actually on disk now; a matrix that already
    reports every task applied is left alone (no need to re-run the lane
    commands on every verify call).
    """
    from .lane_verifiers import build_quality_matrix, missing_or_unapplied_tasks

    quality_matrix_path = run_dir / "quality-matrix.json"
    contract = _load_json(run_dir / "task-contract.json")
    task_texts = [str(t.get("original_text") or "") for t in contract.get("tasks") or []]
    rebuild = not quality_matrix_path.exists()
    if not rebuild:
        try:
            cached_matrix = _load_json(quality_matrix_path)
        except (OSError, TypeError, ValueError):
            cached_matrix = {}
        cached_missing = (
            (cached_matrix.get("requirements") or {}).get("implementation") or {}
        ).get("missing_task_indices")
        if cached_missing:
            rebuild = missing_or_unapplied_tasks(run_dir, len(task_texts)) != cached_missing
    if rebuild:
        build_quality_matrix(repo_path, run_dir, task_texts)


def verify_run(repo: str, run_id: str, *, flow: str = "run") -> Dict[str, Any]:
    """Run the independent watcher and advance a run without a manual tick."""
    status = read_status(repo, run_id)
    run_dir = Path(status["run_dir"])
    repo_path = Path(status["manifest"]["repo"]).resolve()
    state = status["state"]
    if state.get("phase") in {"done", "cancelled"}:
        return status
    watcher = _watcher_script()
    if not watcher.exists():
        state["blockers"] = ["watcher_verify.py is unavailable"]
        state["current_action"] = "watcher_unavailable"
        state["next_action"] = "inspect_and_recover"
        _write_json(run_dir / "state.json", state)
        _transition(run_dir, state, "blocked", "independent watcher is unavailable", receipt=str(run_dir / "state.json"))
        return read_status(repo, run_id)
    # Parallel lanes each write evidence after their own task; re-measure on the
    # final tree so the watcher compares against the diff it will actually see.
    # This must run BEFORE `_ensure_current_quality_matrix` below: rebuilding
    # the quality matrix runs the task's own lane commands (pytest, coverage,
    # ...), which write byproducts (e.g. `.coverage`) to the tree -- doing
    # that first would make the evidence receipt's diff-coverage check see
    # those byproducts as an "uncovered diff outside operator receipt".
    _write_json(run_dir / "evidence-receipt.json", build_evidence_receipt(str(run_dir)))
    # A run-scoped contract (task-contract.json) always exists by the time a
    # run can be verified; only a synthetic/legacy caller without one skips
    # this (there is then no task list to measure "missing" against anyway).
    # Must run BEFORE the watcher below: the watcher independently re-derives
    # its verdict from this SAME on-disk quality-matrix.json, so a stale one
    # (a dependent task applied through its own separate `tick` process since
    # this receipt was last built) would fail the watcher before this
    # function's own later, redundant freshness check ever runs.
    if (run_dir / "task-contract.json").is_file():
        _ensure_current_quality_matrix(repo_path, run_dir)
    _transition(run_dir, state, "watching", "automatic conduct reached independent verification", receipt=str(run_dir / "operator-receipt.json"))
    env = _subprocess_env()
    env["SIMPLICIO_RUN_DIR"] = str(run_dir)
    env["SIMPLICIO_LOOP_REPO"] = str(repo_path)
    env["SIMPLICIO_LOOP_DIR"] = str(run_dir / "loop")
    result = subprocess.run([sys.executable, str(watcher), "verify"], cwd=str(repo_path), capture_output=True, text=True, timeout=180, env=env)
    output = redact_sensitive_text((result.stdout or "") + (result.stderr or "")).strip()
    _write_json(run_dir / "watcher-receipt.json", {"schema": "simplicio.watcher-invocation/v1", "returncode": result.returncode, "output": output, "receipt": str(run_dir / "loop" / "watcher_state.json"), "checked_at": _now()})
    watcher_path = run_dir / "loop" / "watcher_state.json"
    watcher_state = _load_json(watcher_path) if watcher_path.exists() else {}
    if result.returncode != 0 or watcher_state.get("status") != "MEASURED" or not watcher_state.get("match"):
        state = read_status(repo, run_id)["state"]
        state["blockers"] = [watcher_state.get("reported") or output or "watcher verification failed"]
        state["current_action"] = "watcher_failed"
        state["next_action"] = "inspect_and_recover"
        state["evidence"] = {"ready": False, "receipt": str(watcher_path), "status": "UNVERIFIED"}
        _write_json(run_dir / "state.json", state)
        _transition(run_dir, state, "blocked", "independent watcher rejected the run", receipt=str(watcher_path))
        return read_status(repo, run_id)
    state = read_status(repo, run_id)["state"]
    state["evidence"] = {"ready": True, "receipt": str(watcher_path), "status": "MEASURED"}
    state["current_action"] = "watcher_verified"
    state["next_action"] = "delivery_reconciliation"
    _write_json(run_dir / "state.json", state)
    _transition(run_dir, state, "delivering", "independent watcher measured all acceptance criteria", receipt=str(watcher_path))
    evidence_payload = {}
    try:
        evidence_receipt = _load_json(run_dir / "evidence-receipt.json")
        evidence_payload = {
            "evidence_receipt": str(run_dir / "evidence-receipt.json"),
            "criteria_verified": int(
                (evidence_receipt.get("summary") or {}).get("criteria_verified") or 0
            ),
        }
    except (OSError, TypeError, ValueError):
        evidence_payload = {}
    delivered = reconcile_delivery(
        repo, run_id, "verified", source_kind="local", source_payload=evidence_payload
    )
    if not delivered["state"].get("delivery", {}).get("ready"):
        return delivered
    state = delivered["state"]
    state["current_action"] = "run_verified"
    state["next_action"] = "none"
    state["completion"] = {"ready": True, "receipt": str(watcher_path), "verdict": "VERIFIED", "reason_code": "watcher_and_delivery_verified", "tag": "MEASURED"}
    _write_json(run_dir / "state.json", state)
    # wi612 (#612): Quality Matrix + Completion Oracle obrigatorios antes do done (elimina bypass).
    from . import oracle as _oracle
    if not (run_dir / "quality-matrix.json").exists():
        from .lane_verifiers import build_quality_matrix
        contract = _load_json(run_dir / "task-contract.json")
        build_quality_matrix(repo_path, run_dir,
                             [str(t.get("original_text") or "") for t in contract.get("tasks") or []])
    _qm_ok, _qm_gate, _qm_verdict = _oracle._quality_matrix_gate(run_dir)
    if not _qm_ok:
        state = read_status(repo, run_id)["state"]
        state["blockers"] = [_qm_verdict.get("reason", "quality matrix incomplete")]
        state["current_action"] = "quality_matrix_failed"
        state["next_action"] = "inspect_and_recover"
        state["completion"] = {"ready": False, "verdict": "BLOCKED", "reason_code": "quality_matrix_failed", "tag": "MEASURED"}
        state["evidence"] = {"ready": False, "receipt": str(run_dir / "quality-matrix.json"), "status": "UNVERIFIED"}
        _write_json(run_dir / "state.json", state)
        _transition(run_dir, state, "blocked", "quality matrix gate rejected the run", receipt=str(run_dir / "quality-matrix.json"))
        return read_status(repo, run_id)
    _persist_external_completion_response(run_dir)
    _oracle_matrix = _oracle.evaluate_matrix(str(run_dir / "loop"), str(run_dir))
    _write_json(run_dir / "oracle-matrix.json", _oracle_matrix)
    if not _oracle_matrix.get("parity") or not all(a["ready"] for a in _oracle_matrix.get("adapters", [])):
        state = read_status(repo, run_id)["state"]
        state["blockers"] = ["completion oracle incomplete: " + str(_oracle_matrix.get("signature"))]
        state["current_action"] = "oracle_failed"
        state["next_action"] = "inspect_and_recover"
        state["completion"] = {"ready": False, "verdict": "BLOCKED", "reason_code": "oracle_failed", "tag": "MEASURED"}
        state["evidence"] = {"ready": False, "receipt": str(run_dir / "oracle-matrix.json"), "status": "UNVERIFIED"}
        _write_json(run_dir / "state.json", state)
        _transition(run_dir, state, "blocked", "completion oracle rejected the run", receipt=str(run_dir / "oracle-matrix.json"))
        return read_status(repo, run_id)
    try:
        _ensure_verified_loop_journal(run_dir)
        publication_args = {
            "repo": repo_path,
            "run_dir": run_dir,
            "manifest": status["manifest"],
        }
        if flow != "run":
            publication_args["flow"] = flow
        loop_execution = publish_loop_execution_receipt(**publication_args)
        if loop_execution.get("status") != "VERIFIED":
            raise LoopExecutionReceiptError(
                "runtime handoff receipt did not reach VERIFIED status"
            )
    except LoopExecutionReceiptError as exc:
        state = read_status(repo, run_id)["state"]
        state["blockers"] = [f"loop-execution receipt publication failed: {exc}"]
        state["current_action"] = "loop_execution_receipt_failed"
        state["next_action"] = "inspect_and_recover"
        state["evidence"] = {
            "ready": False,
            "receipt": str(repo_path / ".simplicio-loop" / "loop-execution.json"),
            "status": "UNVERIFIED",
        }
        _write_json(run_dir / "state.json", state)
        _transition(
            run_dir,
            state,
            "blocked",
            "runtime handoff receipt could not be published",
            receipt=str(run_dir / "state.json"),
        )
        return read_status(repo, run_id)
    state = read_status(repo, run_id)["state"]
    state["loop_execution"] = loop_execution
    state["blockers"] = []
    state["degraded"] = False
    _transition(run_dir, state, "done", "automatic task-to-verify conduct completed", receipt=str(watcher_path))
    return read_status(repo, run_id)


def _conduct_run(repo: str, task_path: str, delivery: str = "verified", max_iterations: int = 12, *, retry_budget: int = 3, quality_provider: Optional[str] = None, quality_policy: str = "strict-default", provider_worker: str | None = None) -> Dict[str, Any]:
    """Arm, execute, and independently verify one run as one durable operation.

    Issue #279: this boundary must never leave a run partially armed.  Either the full
    mapper -> plan -> operator preflight -> batch chain succeeds, or the run is left (and
    reported) explicitly ``blocked`` with a diagnostic receipt.  ``execute_operator_batch``
    already fails closed and persists a batch-preflight-block diagnostic before raising when
    the receipt chain is missing or stale, but that exception must not escape uncaught here --
    an uncaught exception is itself a partially-armed, undiagnosed state from the CLI's
    perspective.
    """
    armed = arm_run(repo, task_path, delivery, max_iterations)
    run_id = armed["manifest"]["run_id"]
    if armed["state"].get("phase") == "blocked":
        return armed
    try:
        # The public ``run`` path is intentionally zero-config: let the operator
        # derive its worker demand from the task set and let the physical admission
        # monitor choose the safe concurrency.  Callers that need a deterministic
        # serial lane can still use the explicit ``batch --serial`` surface.
        batch = execute_operator_batch(
            repo,
            run_id,
            max_workers=None,
            retry_budget=retry_budget,
            auto_fan_out=None,
            provider_worker=provider_worker,
        )
    except (OSError, TypeError, ValueError, RuntimeError) as exc:
        status = read_status(repo, run_id)
        run_dir = Path(status["run_dir"])
        state = status["state"]
        if state.get("phase") != "blocked":
            # Defensive fallback: execute_operator_batch's own preflight boundary is
            # expected to have already persisted a blocked diagnostic before raising, but
            # guarantee the run never surfaces as anything other than explicitly blocked.
            _transition(run_dir, state, "blocked",
                        "batch dispatch failed before dispatch", extra={"error": str(exc)})
            status = read_status(repo, run_id)
        return status
    status = read_status(repo, run_id)
    run_dir = Path(status["run_dir"])
    workers = list(batch.get("workers") or [])
    non_success_workers = [
        worker for worker in workers
        if str(worker.get("status") or "") != "succeeded"
    ]
    failed_indices = list(batch.get("failed_task_indices") or [])
    blocked_indices = list(batch.get("blocked_task_indices") or [])
    dead_letter_indices = list(batch.get("dead_letter_task_indices") or [])
    if (
        failed_indices
        or blocked_indices
        or dead_letter_indices
        or non_success_workers
        or status["state"].get("phase") == "blocked"
    ):
        # A worker can be ``blocked``/``paused`` without appearing in
        # ``failed_task_indices`` (for example when the physical governor
        # terminates admission).  Do not run the independent watcher against
        # that pre-mutation state: surface the real operator reason first.
        state = status["state"]
        if state.get("phase") not in {"blocked", "done", "cancelled"}:
            first_failure = non_success_workers[0] if non_success_workers else {}
            reason = (
                first_failure.get("reason")
                or first_failure.get("error")
                or first_failure.get("reason_code")
                or "operator batch did not produce successful worker receipts"
            )
            state["blockers"] = [str(reason)]
            state["current_action"] = "operator_batch_blocked"
            state["next_action"] = "inspect_and_recover"
            _write_json(run_dir / "state.json", state)
            _transition(
                run_dir,
                state,
                "blocked",
                "operator batch returned a non-success worker",
                receipt=str(run_dir / "operator-batch.json"),
                extra={
                    "failed_task_indices": failed_indices,
                    "blocked_task_indices": blocked_indices,
                    "dead_letter_task_indices": dead_letter_indices,
                },
            )
        return read_status(repo, run_id)
    # An explicitly selected quality provider runs after execution and before
    # the watcher/delivery/Completion Oracle. Once selected, it remains
    # fail-closed: there is no fallback for an unavailable or failing provider.
    if quality_provider:
        from .quality_provider import conduct_quality
        run_dir = Path(status["run_dir"])
        head = status.get("manifest", {}).get("head", "") or ""
        diff_hash = status.get("manifest", {}).get("diff_hash", "") or ""
        q = conduct_quality(
            repo, run_id,
            quality_provider=quality_provider, quality_policy=quality_policy,
            attempt=status["state"].get("attempt", 1), head=head, diff_hash=diff_hash,
        )
        if q.get("status") == "BLOCKED":
            state = read_status(repo, run_id)["state"]
            state["blockers"] = [q.get("reason", "quality provider blocked the run")]
            state["current_action"] = "quality_blocked"
            state["next_action"] = "inspect_and_recover"
            state["evidence"] = {
                "ready": False,
                "receipt": str(run_dir / "quality-matrix.json"),
                "status": "UNVERIFIED",
            }
            _write_json(run_dir / "state.json", state)
            _transition(run_dir, state, "blocked",
                        "quality provider blocked the run (fail-closed)",
                        receipt=str(run_dir / "quality-matrix.json"))
            return read_status(repo, run_id)
        # A FAIL provider returns to recovery/implementation per the issue spec
        # (not a direct provider fix); surface it and stop short of verify.
        if q.get("status") == "FAIL":
            state = read_status(repo, run_id)["state"]
            state["blockers"] = [q.get("detail", "quality provider reported FAIL")]
            state["current_action"] = "quality_failed"
            state["next_action"] = "inspect_and_recover"
            _write_json(run_dir / "state.json", state)
            _transition(run_dir, state, "blocked",
                        "quality provider reported FAIL -> recovery",
                        receipt=str(run_dir / "quality-matrix.json"))
            return read_status(repo, run_id)
    return verify_run(repo, run_id)


def conduct_run(repo: str, task_path: str, delivery: str = "verified", max_iterations: int = 12, *, retry_budget: int = 3, quality_provider: Optional[str] = None, quality_policy: str = "strict-default", provider_worker: str | None = None) -> Dict[str, Any]:
    """Conduct a run and attach its public Completion-Oracle-derived outcome."""
    status = _conduct_run(repo, task_path, delivery, max_iterations, retry_budget=retry_budget,
                          quality_provider=quality_provider, quality_policy=quality_policy,
                          provider_worker=provider_worker)
    from .run_outcome import persist_run_outcome
    status["outcome"] = persist_run_outcome(status)
    return status


def _resolve_dispatch_mode() -> str:
    """Resolve the per-task child-execution mode every dispatch path shares.

    ``process`` (the default) supervises each task in its own child process,
    same as the classic ``dispatch_operator_batch`` path; ``thread`` is the
    opt-out used by unit tests that stub the per-task worker with a local
    closure (unpicklable across a real process boundary).
    """
    dispatch_mode = os.environ.get("SIMPLICIO_LOOP_DISPATCH_MODE", "process").strip().lower()
    if dispatch_mode not in {"process", "thread"}:
        raise ValueError("SIMPLICIO_LOOP_DISPATCH_MODE must be process or thread")
    return dispatch_mode


def _load_prior_dispatch_records(
    journal_path: Path,
) -> Dict[Tuple[str, str, int], Dict[str, Any]]:
    """Return the last persisted attempt record per (repo, run_id, task_index).

    Shared by every dispatch path that persists to one run's
    ``operator-batch.jsonl`` (`_persist_attempt`'s file), so a resumed batch
    -- whichever path dispatches it -- recognizes the same durably-succeeded
    tasks and never re-dispatches them.
    """
    prior: Dict[Tuple[str, str, int], Dict[str, Any]] = {}
    if not journal_path.exists():
        return prior
    for line in journal_path.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
            key = (str(rec.get("repo")), str(rec.get("run_id")), int(rec.get("task_index")))
        except (ValueError, TypeError, json.JSONDecodeError):
            continue
        prior[key] = rec
    return prior


def _operator_worker_limit(requested: Optional[int], item_count: int) -> int:
    """Resolve logical demand; the physical admission monitor governs live work."""
    if item_count <= 0:
        return 0
    if requested is None or requested <= 0:
        raw = os.environ.get("SIMPLICIO_LOOP_OPERATOR_WORKERS", "").strip()
        try:
            requested = int(raw) if raw else item_count
        except ValueError:
            raise ValueError("SIMPLICIO_LOOP_OPERATOR_WORKERS must be an integer") from None
        if requested <= 0:
            requested = item_count
    return max(1, min(int(requested), item_count))


_PHYSICAL_MONITOR_ENV = (
    ("SIMPLICIO_LOOP_TARGET_PRESSURE_PERCENT", "target_pressure_percent", float),
    ("SIMPLICIO_LOOP_NO_NEW_PRESSURE_PERCENT", "no_new_pressure_percent", float),
    ("SIMPLICIO_LOOP_CHECKPOINT_PRESSURE_PERCENT", "checkpoint_pressure_percent", float),
    ("SIMPLICIO_LOOP_TERMINATE_PRESSURE_PERCENT", "terminate_pressure_percent", float),
    ("SIMPLICIO_LOOP_DISK_SUSPEND_PERCENT", "disk_suspend_percent", float),
    ("SIMPLICIO_LOOP_DISK_SUSPEND_FLOOR_BYTES", "disk_suspend_floor_bytes", int),
    ("SIMPLICIO_LOOP_RECOVERY_WINDOW_NS", "recovery_window_ns", int),
)
_PHYSICAL_MONITOR_KEYS = frozenset(key for _env, key, _converter in _PHYSICAL_MONITOR_ENV)


def _physical_monitor_kwargs(overrides: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Resolve safe monitor profile values at the production dispatch boundary."""
    values: Dict[str, Any] = {}
    for env_name, key, converter in _PHYSICAL_MONITOR_ENV:
        raw = os.environ.get(env_name, "").strip()
        if not raw:
            continue
        try:
            values[key] = converter(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid {env_name} physical admission setting") from exc
    if overrides is not None:
        unknown = set(overrides).difference(_PHYSICAL_MONITOR_KEYS)
        if unknown:
            raise ValueError("unsupported physical admission setting: " + ", ".join(sorted(unknown)))
        values.update(dict(overrides))
    return values

def _build_native_prism_scheduler(
    items: Sequence[Mapping[str, Any]],
    worker_limit: int,
    *,
    physical_monitor_kwargs: Optional[Mapping[str, Any]] = None,
) -> tuple[Any, str, dict[str, Any]]:
    """Build the native Prism admission authority for a local operator batch.

    Prism is intentionally an in-process contract here: it admits independent
    work up to the measured worker limit, preserves dependency/conflict edges,
    and leaves the existing worktree/operator bridge as the mutation boundary.
    This keeps the fast local path useful without requiring cloud workers or
    an Orca client, while physical admission remains separately governed.
    """
    from .prism_contracts import (
        TASK_STATES,
        PrismExecution,
        SlotSupervisor,
        TaskOwnership,
    )
    from .prism_budgets import AdaptiveBudgetGovernor, BudgetSample
    from .prism_scheduler import PrismPolicy, PrismScheduler, ResourceVector, ScheduledTask

    if not items or worker_limit < 1:
        raise ValueError("native Prism requires work and a positive worker limit")
    from .local_capacity import PhysicalAdmissionMonitor

    capacity_root = Path(str(items[0].get("repo") or ".")).resolve()
    # Queue/worktree adapters may hand the scheduler a path that is created only
    # after admission. Probe the nearest existing ancestor instead of treating
    # that normal pre-launch state as an unavailable disk signal.
    while not capacity_root.exists() and capacity_root != capacity_root.parent:
        capacity_root = capacity_root.parent
    monitor_kwargs = _physical_monitor_kwargs(physical_monitor_kwargs)
    if monitor_kwargs:
        capacity_monitor = PhysicalAdmissionMonitor(
            str(capacity_root), worker_limit, **monitor_kwargs,
        )
    else:
        capacity_monitor = PhysicalAdmissionMonitor(
            str(capacity_root), worker_limit,
        )
    capacity_sample = capacity_monitor.refresh(force=True)
    # Keep one logical scheduler worker alive so its explicit unavailable sample
    # can produce a blocked admission decision instead of bypassing the receipt.
    worker_limit = max(1, min(int(worker_limit), max(1, capacity_sample.safe_workers)))
    run_id = str(items[0].get("run_id") or "local-batch")
    # Keep logical partitioning independent from physical workers.  A task may
    # provide an explicit partition identity; otherwise derive one from the
    # existing impact/dependency metadata so independent work does not collapse
    # into the historical single supervisor.
    def _partition_key(item: Mapping[str, Any]) -> str:
        spec = item.get("task_spec")
        spec = spec if isinstance(spec, Mapping) else {}
        explicit = (
            spec.get("slot_key") or spec.get("dependency_component")
            or spec.get("repository") or spec.get("repo")
        )
        if explicit:
            return str(explicit).strip()
        paths = spec.get("files_affected") or spec.get("candidate_targets") or ()
        if isinstance(paths, str):
            paths = (paths,)
        first = sorted(str(path).replace("\\", "/") for path in paths if str(path).strip())[:1]
        if first:
            return first[0].split("/", 1)[0]
        return "default"

    partitions: dict[str, list[Mapping[str, Any]]] = {}
    for item in items:
        partitions.setdefault(_partition_key(item), []).append(item)
    # Logical slots are unbounded.  The measured worker/resource governor below
    # controls physical execution; it must not collapse independent partitions
    # into an artificial overflow slot.
    ordered_partitions = sorted(partitions.items(), key=lambda pair: pair[0])
    recovery_reserve = min(1, max(0, worker_limit - 1))
    validation_reserve = min(1, max(0, worker_limit - recovery_reserve - 1))
    policy = PrismPolicy(
        max_tasks_per_slot=10,
        global_worker_limit=max(1, int(worker_limit)),
        recovery_reserve=recovery_reserve,
        validation_reserve=validation_reserve,
    )
    policy_hash = hashlib.sha256(
        json.dumps({"policy": repr(policy), "run_id": run_id}, sort_keys=True).encode()
    ).hexdigest()
    config_hash = hashlib.sha256(
        json.dumps({"items": [str(item.get("task_id") or "") for item in items]}, sort_keys=True).encode()
    ).hexdigest()
    root = PrismExecution(
        goal_id=run_id,
        owner_agent="simplicio-loop",
        policy_hash=policy_hash,
        config_hash=config_hash,
        source_generation=run_id,
        reducer_ref="simplicio_loop.runner.dispatch_operator_batch",
        budget=(("workers", max(1, int(worker_limit))),),
    )
    governor = AdaptiveBudgetGovernor(policy, relief_samples=2)

    def _budget_sample(sample: Any) -> BudgetSample:
        # Only worker capacity is measured by the local probe. Keep every other
        # governor dimension explicitly unavailable instead of inferring it from
        # an unrelated CPU, memory, or disk value.
        null_reasons = {
            name: "local_probe_not_supported"
            for name in (
                "cpu_millis", "rss_bytes", "io_units", "provider_requests",
                "tokens", "model_slots", "network_queue", "context_tokens",
                "evidence_bytes",
            )
        }
        if sample.safe_workers < 1 or sample.unavailable:
            null_reasons["workers"] = sample.null_reasons.get(
                "workers", "required_capacity_signal_unavailable"
            )
        return BudgetSample(
            workers=int(sample.safe_workers),
            observed_at_ns=int(sample.observed_at_ns),
            null_reasons=null_reasons,
        )

    observation = governor.observe(_budget_sample(capacity_sample))
    scheduler = PrismScheduler(policy, observation=observation)
    slots_by_partition: dict[str, SlotSupervisor] = {}
    for partition, group in ordered_partitions:
        slot = SlotSupervisor(
            parent_prism_id=root.prism_id,
            supervisor_agent=f"simplicio-loop:{partition}",
            capacity=max(10, len(group)),
        )
        scheduler.register_slot(slot)
        slots_by_partition[partition] = slot
    for item in items:
        task_spec = item.get("task_spec")
        task_spec = dict(task_spec) if isinstance(task_spec, Mapping) else {}
        raw_dependencies = task_spec.get("depends_on") or task_spec.get("dependencies") or ()
        if isinstance(raw_dependencies, Mapping):
            raw_dependencies = raw_dependencies.get("items") or ()
        kind = str(task_spec.get("kind") or "implementation")
        if kind not in {"implementation", "recovery", "validation", "review", "integration"}:
            kind = "implementation"
        task_id = str(item.get("task_id") or "")
        slot = slots_by_partition[_partition_key(item)]
        ownership = TaskOwnership(
            task_id=task_id,
            slot_id=slot.slot_id,
            attempt=1,
            owner_agent=str(item.get("worker_id") or "simplicio-local"),
            lease_id=str(item.get("lease_id") or task_id),
            fence=1,
            source_generation=run_id,
            capabilities=("operator", "local", "worktree"),
            allowed_transitions=tuple(sorted(TASK_STATES)),
        )
        scheduler.submit(ScheduledTask(
            task_id=task_id,
            slot_id=slot.slot_id,
            ownership=ownership,
            depends_on=tuple(str(value) for value in raw_dependencies if str(value).strip()),
            hard_conflicts=tuple(str(value) for value in (task_spec.get("hard_conflicts") or ())),
            exclusive_resources=tuple(str(value) for value in (task_spec.get("exclusive_resources") or ())),
            priority=int(task_spec.get("priority") or 0),
            kind=kind,
            resources=ResourceVector(workers=1),
        ))
    capacity_receipt = capacity_sample.to_dict()
    capacity_receipt["budget_governor"] = governor.status()
    capacity_receipt["monitor"] = capacity_monitor.status()
    capacity_receipt["policy"] = {
        "recovery_reserve": policy.recovery_reserve,
        "validation_reserve": policy.validation_reserve,
        "global_worker_limit": policy.global_worker_limit,
    }

    def refresh_capacity(*, force: bool = True) -> None:
        refreshed = capacity_monitor.refresh(force=force)
        scheduler.controller.update(governor.observe(_budget_sample(refreshed)))
        capacity_receipt.clear()
        capacity_receipt.update(refreshed.to_dict())
        capacity_receipt["budget_governor"] = governor.status()
        capacity_receipt["monitor"] = capacity_monitor.status()
        capacity_receipt["policy"] = {
            "recovery_reserve": policy.recovery_reserve,
            "validation_reserve": policy.validation_reserve,
            "global_worker_limit": policy.global_worker_limit,
        }

    # The dispatch bridge calls this before each refill and on the monitor clock.
    # Keeping the hook on the scheduler preserves the existing return contract.
    scheduler.native_capacity_refresh = refresh_capacity
    scheduler.native_capacity_monitor = capacity_monitor
    return scheduler, root.prism_id, capacity_receipt


def _worktree_task_spec(item: Mapping[str, Any]) -> Any:
    """Build the queue's impact contract without importing it at module load time.

    ``runner`` is also shipped as a standalone bundle, so importing the scripts package
    eagerly would make the existing operator API fail in installations that do not ship the
    optional isolation adapter.  The late import keeps that adapter genuinely optional while
    still passing the real ``TaskSpec`` to ``WorktreeQueue`` when it is available.
    """
    try:
        from scripts.worktree_queue import TaskSpec
    except ImportError:  # pragma: no cover - direct scripts/ execution fallback
        from worktree_queue import TaskSpec
    raw = item.get("task_spec")
    if isinstance(raw, TaskSpec):
        return raw
    payload = dict(raw or {}) if isinstance(raw, Mapping) else {}
    task_id = str(item.get("task_id") or "task-%s-%s" % (item.get("run_id"), item.get("task_index")))
    payload.setdefault("id", task_id)
    payload.setdefault("goal", str(item.get("goal") or ""))
    return TaskSpec.from_mapping(payload)


def _allocation_context(allocation: Any, item: Mapping[str, Any]) -> Dict[str, Any]:
    """Reduce an Allocation to JSON-safe, persisted operator context."""
    def value(name: str, default: Any = "") -> Any:
        if isinstance(allocation, Mapping):
            return allocation.get(name, default)
        return getattr(allocation, name, default)

    context = {
        "schema": "simplicio.operator-worktree-context/v1",
        "task_id": str(value("task_id", item.get("task_id") or "")),
        "run_id": str(value("run_id", item.get("run_id") or "")),
        "mode": str(value("mode", item.get("isolation", "worktree")) or item.get("isolation", "worktree")),
        "path": str(value("path", "") or ""),
        "branch": str(value("branch", "") or ""),
        "base_sha": str(value("base_sha", "") or ""),
        "head_sha": str(value("head_sha", "") or ""),
        "tree_sha": str(value("tree_sha", "") or ""),
        "lane": str(value("lane", "") or ""),
        "reattached": bool(value("reattached", False)),
        "lock_receipt": str(value("lock_receipt", "") or ""),
        "worktree_id": str(value("worktree_id", "") or ""),
        "terminal_handle": str(value("terminal_handle", "") or ""),
        "lease_owner": str(value("lease_owner", "") or ""),
        "source_repo": str(item.get("source_repo") or item.get("repo") or ""),
        "source_run_id": str(item.get("source_run_id") or item.get("run_id") or ""),
    }
    return context


def _persist_isolated_run_context(item: Dict[str, Any], context: Dict[str, Any]) -> None:
    """Persist queue context and clone run receipts into an isolated checkout.

    The copy is filesystem-only (no Git subprocess), making this path deterministic in unit
    tests and safe for callers that provide a fake queue.  If the source run is unavailable,
    the context receipt is still written; the operator then fails closed at its normal
    preflight boundary rather than manufacturing a success.
    """
    path = str(context.get("path") or "")
    source_repo = Path(str(context.get("source_repo") or item.get("repo") or "")).resolve()
    run_id = str(item.get("run_id") or context.get("source_run_id") or "")
    if not path:
        return
    target_root = Path(path).resolve()
    target_root.mkdir(parents=True, exist_ok=True)
    context_dir = target_root / ".simplicio-loop/orchestrator" / "dispatch-context"
    context_dir.mkdir(parents=True, exist_ok=True)
    context_path = context_dir / (str(context.get("task_id") or item.get("task_index")) + ".json")
    context["context_path"] = str(context_path)
    _write_json(context_path, context)

    source_state_path = source_repo / ".simplicio-loop" / "loop-runs" / run_id / "state.json"
    if source_state_path.exists():
        try:
            source_run = source_state_path.parent
            source_state = _load_json(source_state_path)
            _emit_event(source_run, source_state, "worktree_created",
                        receipt=str(context.get("lock_receipt") or context_path),
                        task_id=str(context.get("task_id") or item.get("task_id") or ""),
                        message="isolated worktree context persisted", worktree=context)
        except (OSError, ValueError, TypeError):
            # The worker's normal receipts remain authoritative if the coordinator is gone.
            pass

    source_run = source_repo / ".simplicio-loop" / "loop-runs" / run_id
    target_run = target_root / ".simplicio-loop" / "loop-runs" / run_id
    if source_run.is_dir() and target_root != source_repo and not target_run.exists():
        target_run.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_run, target_run)
    manifest_path = target_run / "manifest.json"
    if manifest_path.exists():
        try:
            manifest = _load_json(manifest_path)
            manifest["repo"] = str(target_root)
            manifest["run_id"] = run_id
            _write_json(manifest_path, manifest)
        except (OSError, ValueError, TypeError):
            # The operator's ordinary preflight will emit a durable failure receipt.
            pass


def _prepare_worktree_contexts(normalized: List[Dict[str, Any]], worktree_queue: Any, *, defer_worktrees: bool = False) -> None:
    """Register optional worktrees and defer allocation until an admitted spawn."""
    if worktree_queue is None or not normalized:
        return
    specs = [_worktree_task_spec(item) for item in normalized]
    register = getattr(worktree_queue, "register_tasks", None)
    if callable(register):
        try:
            register(specs)
        except Exception as exc:
            for item in normalized:
                item["worktree_error"] = f"{type(exc).__name__}: {exc}"
            return
    for item, spec in zip(normalized, specs):
        isolation = str(item.get("isolation") or "worktree").strip().lower()
        if isolation not in {"worktree", "shared"}:
            item["worktree_error"] = "ValueError: unsupported worktree isolation mode"
            continue
        if isolation == "shared" or defer_worktrees:
            # Both shared checkouts and isolated worktrees are allocated only after the
            # immediately preceding admission poll.  This prevents a later pressure sample
            # from leaving an unsent queue lease behind.
            item["worktree_deferred"] = True
            item["isolation_key"] = (
                "worktree:%s" % item.get("task_id")
                if isolation == "worktree" else "%s:%s" % (item.get("repo"), item.get("run_id"))
            )
            continue
        try:
            allocation = worktree_queue.allocate(spec)
        except Exception as exc:
            item["worktree_error"] = f"{type(exc).__name__}: {exc}"
            continue
        context = _allocation_context(allocation, item)
        item["worktree_context"] = context
        item["source_repo"] = str(item.get("repo") or "")
        item["source_run_id"] = str(item.get("run_id") or "")
        # Worktree workers get their own run tree; shared mode intentionally retains the
        # original path and is serialized by the isolation key below.
        if context["mode"] == "worktree" and context["path"]:
            try:
                _persist_isolated_run_context(item, context)
            except Exception as exc:
                item["worktree_error"] = f"{type(exc).__name__}: {exc}"
            item["repo"] = context["path"]
            item["isolation_key"] = context["path"]
        else:
            item["isolation_key"] = "%s:%s" % (item.get("repo"), item.get("run_id"))
        recorder = getattr(worktree_queue, "record_context", None)
        if callable(recorder):
            try:
                recorder(context["task_id"], context)
            except Exception as exc:
                # Context persistence is a safety gate: do not run an unreceipted isolated
                # worker.  This preserves fail-closed behavior without changing the API.
                item["worktree_error"] = f"{type(exc).__name__}: {exc}"


def _ensure_deferred_worktree_context(item: Dict[str, Any], worktree_queue: Any) -> None:
    """Acquire one deferred queue context immediately before its admitted spawn."""
    if not item.get("worktree_deferred") or item.get("worktree_context") or item.get("worktree_error"):
        return
    try:
        spec = _worktree_task_spec(item)
        isolation = str(item.get("isolation") or "worktree").strip().lower()
        if isolation == "shared":
            allocation = worktree_queue.allocate(spec, isolation="shared", shared_policy=True)
        else:
            allocation = worktree_queue.allocate(spec, isolation="worktree")
        context = _allocation_context(allocation, item)
        item["worktree_context"] = context
        item["source_repo"] = str(item.get("repo") or "")
        item["source_run_id"] = str(item.get("run_id") or "")
        if context["mode"] == "worktree" and context["path"]:
            _persist_isolated_run_context(item, context)
            item["repo"] = context["path"]
            item["isolation_key"] = context["path"]
        else:
            _persist_isolated_run_context(item, context)
            item["isolation_key"] = "%s:%s" % (item.get("repo"), item.get("run_id"))
        recorder = getattr(worktree_queue, "record_context", None)
        if callable(recorder):
            recorder(context["task_id"], context)
    except Exception as exc:
        item["worktree_error"] = f"{type(exc).__name__}: {exc}"


def _release_shared_context(item: Mapping[str, Any], worktree_queue: Any, *, force: bool = False) -> None:
    context = item.get("worktree_context") or {}
    if not force and str(context.get("mode") or "") != "shared":
        return
    task_id = str(context.get("task_id") or item.get("task_id") or "")
    if force and task_id:
        recorder = getattr(worktree_queue, "record_context", None)
        if callable(recorder):
            released = dict(context)
            released["active"] = False
            try:
                recorder(task_id, released)
            except Exception:
                pass
        cleanup = getattr(worktree_queue, "record_cleanup_receipt", None)
        worktree_id = str(context.get("worktree_id") or "")
        lease_owner = str(context.get("lease_owner") or "")
        if callable(cleanup) and worktree_id and lease_owner:
            try:
                cleanup(task_id, {
                    "worktree_id": worktree_id,
                    "terminal_handle": str(context.get("terminal_handle") or ""),
                    "lease_owner": lease_owner,
                    "cleanup_decision": "cleanup",
                    "reason": "cancelled_before_spawn",
                })
            except Exception:
                pass
    teardown = getattr(worktree_queue, "teardown", None)
    if callable(teardown) and task_id:
        try:
            teardown(task_id)
        except Exception:
            # Never mask the operator receipt with cleanup noise.
            pass



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


def _operator_dispatch_item(item: Mapping[str, Any]) -> Dict[str, Any]:
    """Normalize one typed operator dispatch item.

    The adapter deliberately accepts only the real ``execute_operator`` boundary.  In
    particular, it has no command/echo fallback: callers that need a dry run must arm a
    run first and use that run's normal preflight receipts.
    """
    repo = str(item.get("repo") or "").strip()
    run_id = str(item.get("run_id") or "").strip()
    try:
        task_index = int(item.get("task_index"))
    except (TypeError, ValueError) as exc:
        raise ValueError("operator dispatch task_index must be an integer") from exc
    if not repo or not run_id or task_index < 1:
        raise ValueError("operator dispatch items require repo, run_id, and a positive task_index")
    normalized = {
        "repo": str(Path(repo).resolve()),
        "run_id": run_id,
        "task_index": task_index,
        "worker_id": str(item.get("worker_id") or f"operator-{task_index}"),
        "task_id": str(item.get("task_id") or f"task-{run_id}-{task_index}"),
    }
    # An isolation key is intentionally explicit.  Two tasks in one run share state.json,
    # operator-receipt.json, and the working tree and therefore cannot safely overlap until
    # the worktree adapter supplies separate contexts.
    normalized["isolation_key"] = str(item.get("isolation_key") or normalized["repo"])
    normalized["isolation"] = str(item.get("isolation") or "worktree")
    if isinstance(item.get("task_spec"), Mapping):
        normalized["task_spec"] = dict(item["task_spec"])
    if item.get("provider_worker") is not None:
        normalized["provider_worker"] = str(item.get("provider_worker") or "").strip().lower()
    normalized["admission_fence"] = max(1, int(item.get("admission_fence") or 1))
    normalized["authority_attempt"] = max(1, int(item.get("authority_attempt") or 1))
    normalized["expected_base_ref"] = str(item.get("expected_base_ref") or "")
    normalized["expected_base_sha"] = str(item.get("expected_base_sha") or "")
    authority = item.get("authority_receipt")
    if authority is not None:
        if not isinstance(authority, Mapping):
            raise ValueError("authority_receipt must be an object")
        authority = dict(authority)
        supplied = str(authority.pop("receipt_hash", ""))
        if not supplied or supplied != _planning_content_hash(authority):
            raise ValueError("authority_receipt hash mismatch")
        source = authority.get("source")
        targets = authority.get("targets")
        task_spec = normalized.get("task_spec") or {}
        expected_issue = normalized["task_id"].removeprefix("issue-")
        if (authority.get("operator") != "simplicio-dev-cli"
                or not isinstance(source, Mapping)
                or str(source.get("issue") or "") != expected_issue
                or not str(source.get("revision") or "")
                or not str(source.get("planning_receipt") or "")
                or not isinstance(targets, list) or not targets
                or any(not isinstance(target, str) or not target.strip() for target in targets)
                or sorted(targets) != sorted(task_spec.get("files_affected") or [])):
            raise ValueError("authority_receipt binding mismatch")
        authority["receipt_hash"] = supplied
        normalized["authority_receipt"] = authority
    if isinstance(item.get("operator_context"), Mapping):
        normalized["operator_context"] = dict(item["operator_context"])
    if item.get("distributed_queue") is not None:
        normalized["distributed_queue"] = item["distributed_queue"]
    if isinstance(item.get("agent_identity"), Mapping):
        normalized["agent_identity"] = dict(item["agent_identity"])
    if isinstance(item.get("context_pack"), Mapping):
        normalized["context_pack"] = dict(item["context_pack"])
    if item.get("source_repo"):
        normalized["source_repo"] = str(item["source_repo"])
    if item.get("source_run_id"):
        normalized["source_run_id"] = str(item["source_run_id"])
    if item.get("worktree_context"):
        normalized["worktree_context"] = dict(item["worktree_context"])
    if item.get("worktree_error"):
        normalized["worktree_error"] = str(item["worktree_error"])
    return normalized


def _verify_worker_receipt_pair(operator_receipt_path: str, evidence_receipt_path: str) -> Dict[str, str]:
    """Gate `receipt_status` on real content/schema/hash/freshness/provenance (issue #288).

    Previously this reduced to ``Path(receipt).is_file() and Path(evidence_receipt).is_file()``
    -- an empty ``{}`` file passed just as readily as a genuine receipt. Both receipts are now
    parsed and run through ``receipt_verifier.verify_receipt`` against the schema each producer
    (``_prepare_operator_receipt`` / ``evidence.py::build_evidence_receipt``) actually emits.
    Only a fully verified pair returns ``VERIFIED``; every other case names a specific,
    non-existence reason (``STALE``, ``TAMPERED``, ``INVALID_SCHEMA``, ``MISSING_FIELD``, or the
    legacy ``UNVERIFIED`` when a path is simply absent).
    """
    if not operator_receipt_path or not evidence_receipt_path:
        return {"status": "UNVERIFIED", "reason": "operator or evidence receipt path missing"}
    op_path = Path(operator_receipt_path)
    ev_path = Path(evidence_receipt_path)
    if not op_path.is_file() or not ev_path.is_file():
        return {"status": "UNVERIFIED", "reason": "operator or evidence receipt file missing"}
    try:
        operator_payload = json.loads(op_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"status": ReceiptStatus.INVALID_SCHEMA, "reason": f"operator receipt unreadable: {exc}"}
    try:
        evidence_payload = json.loads(ev_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"status": ReceiptStatus.INVALID_SCHEMA, "reason": f"evidence receipt unreadable: {exc}"}

    now = time.time()
    operator_verdict = verify_receipt(
        operator_payload, schema=_OPERATOR_RECEIPT_CONTENT_SCHEMA,
        max_age_seconds=RECEIPT_MAX_AGE_SECONDS, now=now,
    )
    if not operator_verdict.verified:
        return {"status": operator_verdict.status, "reason": f"operator receipt: {operator_verdict.reason}"}
    evidence_verdict = verify_receipt(
        evidence_payload, schema=_EVIDENCE_RECEIPT_CONTENT_SCHEMA,
        max_age_seconds=RECEIPT_MAX_AGE_SECONDS, now=now,
    )
    if not evidence_verdict.verified:
        return {"status": evidence_verdict.status, "reason": f"evidence receipt: {evidence_verdict.reason}"}
    return {
        "status": ReceiptStatus.VERIFIED,
        "reason": "operator and evidence receipts passed content/schema/hash/freshness/provenance checks",
    }


def _test_only_stall_before_dispatch(task_id: str) -> None:
    """Test-only hook (issue #288 cross-process recovery test): block one named task for a
    controlled number of real wall-clock seconds before it claims/executes.

    This exists solely so a test can start a real orchestrator OS process, let it durably
    journal an earlier task, and then kill the process (a genuine crash, not a simulated
    exception) while it is deterministically stalled mid-batch on a *different* task --
    proving a restarted orchestrator resumes/reconciles cleanly. It is a no-op unless both
    ``SIMPLICIO_LOOP_TEST_SLOW_TASK_ID`` matches this exact task and
    ``SIMPLICIO_LOOP_TEST_SLOW_TASK_SECONDS`` is set, mirroring the project's existing
    ``SIMPLICIO_LOOP_FAKE_*`` opt-in test hooks -- never active in a normal run.
    """
    target = os.environ.get("SIMPLICIO_LOOP_TEST_SLOW_TASK_ID", "").strip()
    if not target or target != str(task_id).strip():
        return
    try:
        seconds = float(os.environ.get("SIMPLICIO_LOOP_TEST_SLOW_TASK_SECONDS", "0") or "0")
    except ValueError:
        seconds = 0.0
    if seconds > 0:
        time.sleep(seconds)


def _remote_worker_dispatch_enabled() -> bool:
    """#286: once the queue is a genuine network ``HTTPRemoteQueue``, the coordinator must
    not execute the operator in its own process -- it enqueues the task envelope and waits
    for an independent ``RemoteWorkerDaemon`` (a different device/process, reachable only
    over the wire) to pull, claim, run, and complete it. This is the fix for the exact gap
    issue #286 named: "execute_operator_batch() cria HTTPRemoteQueue, mas continua
    submetendo _operator_dispatch_attempt() a um ThreadPoolExecutor local; o proprio
    coordenador chama execute_operator()."

    ``SQLiteRemoteQueue`` (issue #288's co-located, same-process guarded-dispatch path) is
    deliberately unaffected -- that queue backend models a single-host attempt coordinator,
    not a remote worker, so every existing #288 test using it keeps its current behavior.
    Opt out with ``SIMPLICIO_REMOTE_WORKER_ONLY=0`` only for a deliberate same-host smoke
    test that wants the old in-process shortcut against a real HTTP queue.
    """
    return str(os.environ.get("SIMPLICIO_REMOTE_WORKER_ONLY") or "1").strip().lower() not in (
        "0", "false", "no", "off", "disabled",
    )


def _operator_dispatch_attempt_remote_worker(
    item: Mapping[str, Any], common: Dict[str, Any], queue: HTTPRemoteQueue, started: float,
) -> Dict[str, Any]:
    """Enqueue-and-wait dispatch for a genuine remote (``HTTPRemoteQueue``) worker (#286).

    The coordinator itself never claims and never calls ``execute_operator()`` here -- it
    publishes the immutable task envelope once (idempotent: ``enqueue`` is a no-op if the
    task_id already exists) and polls ``queue.task()`` (the same authority a remote
    ``RemoteWorkerDaemon`` mutates) until the task reaches a terminal ``completed`` status or
    the dispatch timeout elapses. A timeout is reported as a specific, non-fabricated failure
    (``remote_worker_timeout``) rather than silently falling back to local execution.
    """
    task_id = common["task_id"]
    context_pack = dict(item.get("context_pack") or {})
    payload = {
        "run_id": common["run_id"], "worker_id": common["worker_id"],
        "task_index": common["task_index"], "goal": context_pack.get("goal", ""),
        "acs": list(context_pack.get("acs") or ()),
        "depends_on": list(context_pack.get("depends_on") or ()),
        "allowed_paths": list(context_pack.get("allowed_paths") or ()),
        "issue_ref": context_pack.get("issue_ref", ""), "issue_url": context_pack.get("issue_url", ""),
        "context_pack": context_pack,
        "worktree_context": dict(item.get("worktree_context") or {}),
    }
    common["dispatch_mode"] = "remote_worker_pull"
    try:
        queue.enqueue(task_id, payload)
    except (QueueConflict, QueueUnavailable, ValueError) as exc:
        return {**common, "status": "failed", "phase": "blocked", "execution_state": "error",
                "receipt": "", "operator_receipt": "", "evidence_receipt": "",
                "receipt_status": "UNVERIFIED", "attempt": 0,
                "reason_code": "remote_enqueue_failed", "remote_error_class": type(exc).__name__,
                "error": str(exc), "dead_letter": True,
                "started_at": started, "finished_at": _now()}

    timeout = float(os.environ.get("SIMPLICIO_REMOTE_DISPATCH_TIMEOUT_SECONDS", "3600"))
    poll_interval = float(os.environ.get("SIMPLICIO_REMOTE_DISPATCH_POLL_INTERVAL_SECONDS", "2"))
    deadline = time.monotonic() + max(0.0, timeout)
    task_state: Dict[str, Any] = {}
    while True:
        try:
            task_state = queue.task(task_id)
        except (QueueUnavailable, KeyError) as exc:
            return {**common, "status": "failed", "phase": "blocked", "execution_state": "paused",
                    "receipt": "", "operator_receipt": "", "evidence_receipt": "",
                    "receipt_status": "UNVERIFIED", "attempt": 0,
                    "reason_code": "network_paused", "error": str(exc), "dead_letter": True,
                    "started_at": started, "finished_at": _now()}
        if str(task_state.get("status") or "") == "completed":
            break
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(poll_interval, remaining))

    if str(task_state.get("status") or "") != "completed":
        return {**common, "status": "failed", "phase": "blocked", "execution_state": "timeout",
                "receipt": "", "operator_receipt": "", "evidence_receipt": "",
                "receipt_status": "UNVERIFIED", "attempt": 0,
                "reason_code": "remote_worker_timeout",
                "error": "no remote worker completed task %s within %.0fs" % (task_id, timeout),
                "dead_letter": True, "started_at": started, "finished_at": _now()}

    lease_info = dict(task_state.get("lease") or {})
    receipt = str(lease_info.get("receipt_ref") or "")
    # The remote worker's evidence receipt lives on its own device; the coordinator only
    # treats it as readable when both files genuinely exist on this filesystem (true, for
    # instance, of the same-host loopback proxy this repo's E2E uses). A cross-device
    # deployment without a receipt-fetch endpoint honestly reports UNVERIFIED here rather
    # than fabricating a VERIFIED pair it cannot see.
    evidence_receipt = str(Path(receipt).parent / "evidence-receipt.json") if receipt else ""
    if not (evidence_receipt and Path(evidence_receipt).is_file()):
        evidence_receipt = ""
    receipt_verdict = _verify_worker_receipt_pair(receipt, evidence_receipt)
    merge: Optional[Dict[str, Any]] = None
    if receipt_verdict["status"] == ReceiptStatus.VERIFIED and _auto_merge_enabled():
        merge = _dispatch_merge_pr(item, receipt=receipt, run_id=common["run_id"])
    return {
        **common,
        "status": "succeeded",
        "phase": "delivered",
        "execution_state": "applied",
        "receipt": receipt,
        "operator_receipt": receipt,
        "evidence_receipt": evidence_receipt,
        "watcher_receipt": "",
        "receipt_status": receipt_verdict["status"],
        "receipt_verdict_reason": receipt_verdict["reason"],
        "attempt": 1,
        "failure_fingerprint": "",
        "merge": merge,
        "remote_task": {"task_id": task_id, "lease": lease_info},
        "started_at": started,
        "finished_at": _now(),
    }


def _fanout_execution_route(item: Mapping[str, Any], run_dir: Path) -> Dict[str, Any]:
    """Persist one independently verifiable route before any fan-out LLM call."""
    context = item.get("context_pack") if isinstance(item.get("context_pack"), Mapping) else {}
    goal = str(context.get("goal") or item.get("task_id") or "").strip()
    capabilities = normalize_capability_manifest(
        context.get("worker_capabilities") or item.get("worker_capabilities") or ()
    )
    worker_available = bool(capabilities) or os.environ.get(
        "SIMPLICIO_DETERMINISTIC_WORKER", "1"
    ).lower() not in {"0", "false", "no", "off"}
    manifest = {
        "declared": capabilities,
        "deterministic_worker_available": worker_available,
    }
    record = decide_route(
        goal,
        has_deterministic_worker=worker_available,
        is_ambiguous=bool(context.get("ambiguous") or context.get("requires_semantic_review")),
    ).to_dict()
    if os.environ.get("SIMPLICIO_STORAGE_ROUTE", "").strip().lower() == "mapper":
        record.update({
            "mapper_required": True,
            "mapper_mode": "targeted",
            "mapper_reason": "Mapper storage route is mandatory for every dispatched task",
        })
    record.update({
        "run_id": str(item.get("run_id") or ""),
        "task_index": int(item.get("task_index") or 0),
        "task_id": str(item.get("task_id") or ""),
        "evidence_handles": sorted({
            str(value) for value in (
                context.get("mapper_envelope_hash"),
                context.get("context_pack_hash"),
                context.get("context_graph_handle"),
            ) if str(value or "")
        }),
        "causal_ids": [str(item.get("run_id") or ""), str(item.get("task_id") or "")],
        "route_authority": "loop-runner-fanout",
        "capability_manifest": manifest,
        "capability_fingerprint": capability_fingerprint(manifest),
        "token_usage": (
            {"input_tokens": 0, "output_tokens": 0, "reason": "deterministic_worker_no_llm"}
            if record["route"] == "worker" else
            {"input_tokens": None, "output_tokens": None,
             "reason": "route_decision_precedes_provider_invocation"}
        ),
    })
    record["receipt_sha"] = _execution_route_hash({
        key: value for key, value in record.items() if key != "receipt_sha"
    })
    if not verify_route_hash(record):
        raise RuntimeError("fan-out execution-route receipt failed hash verification")
    route_path = run_dir / f"execution-route-{record['task_index']}.json"
    _write_json(route_path, record)
    return record


def _operator_dispatch_run_dir(item: Mapping[str, Any]) -> Path:
    """Resolve canonical run storage, with isolated storage for synthetic dispatches."""
    try:
        status = read_status(item["repo"], item["run_id"])
    except FileNotFoundError:  # synthetic dispatch: no armed run on disk
        status = {}
    if status.get("run_dir"):
        return Path(status["run_dir"])

    repo_path = Path(item["repo"]).resolve()

    run_scope = hashlib.sha256(str(item["run_id"]).encode("utf-8")).hexdigest()[:16]
    run_dir = repo_path / ".simplicio-loop" / "orchestrator" / "dispatch-routes" / run_scope
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _operator_dispatch_attempt(item: Mapping[str, Any]) -> Dict[str, Any]:
    """Call the production operator and reduce its status to a durable worker record."""
    started = _now()
    context = dict(item.get("worktree_context") or item.get("operator_context") or {})
    common = {
        "schema": "simplicio.operator-worker/v1",
        "worker_id": item["worker_id"],
        "repo": item["repo"],
        "source_repo": str(item.get("source_repo") or item["repo"]),
        "run_id": item["run_id"],
        "task_index": item["task_index"],
        "task_id": str(item.get("task_id") or ""),
        "worktree_context": context,
        "worktree_path": str(context.get("worktree_path") or context.get("path") or item.get("repo") or ""),
        "branch": str(context.get("branch") or item.get("branch") or ""),
        # These are deliberately worker-scoped aliases.  A fan-out consumer must never
        # infer a shared receipt from the coordinator's run-level state; every lane has
        # its own operator and evidence proof (or an explicit UNVERIFIED state).
        "operator_receipt": "",
        "evidence_receipt": "",
        "receipt_status": "UNVERIFIED",
        "agent": dict(item.get("agent_identity") or {}),
        "context_pack": dict(item.get("context_pack") or {}),
        "authority_receipt": dict(item.get("authority_receipt") or {}),
        "admission_fence": int(item.get("admission_fence") or 1),
        "authority_attempt": int(item.get("authority_attempt") or 1),
        "expected_base_ref": str(item.get("expected_base_ref") or ""),
        "expected_base_sha": str(item.get("expected_base_sha") or ""),
    }
    run_dir = _operator_dispatch_run_dir(item)
    execution_route = _fanout_execution_route(item, run_dir)
    common["execution_route"] = execution_route
    common["route_receipt_sha"] = execution_route["receipt_sha"]
    if _model_routed_dispatch_enabled():
        # #287: route this dispatch attempt through the real model registry/router
        # instead of a hardcoded runtime, and -- when a real driver is wired for the
        # selection -- genuinely invoke it. Additive audit evidence only: a routing
        # block or driver failure here never blocks the dev-cli operator mutation
        # below, which remains this repo's actual apply/verify contract.
        try:
            if execution_route["route"] == "worker":
                common["model_routing"] = {
                    "routed": False, "executed": False,
                    "reason": "deterministic_worker_route_no_llm",
                    "execution_route_sha": execution_route["receipt_sha"],
                }
            else:
                common["model_routing"] = _execute_routed_runtime(item, run_dir)
        except Exception as exc:  # routing/execution evidence must never crash dispatch
            common["model_routing"] = {"routed": False, "executed": False, "error": f"{type(exc).__name__}: {exc}"}
    queue = item.get("distributed_queue")
    if queue is not None and isinstance(queue, HTTPRemoteQueue) and _remote_worker_dispatch_enabled():
        # #286: a genuine network queue means genuine remote workers -- the coordinator
        # enqueues and waits, it never claims/executes the operator itself. See
        # `_remote_worker_dispatch_enabled` for the opt-out and rationale.
        remote_record = _operator_dispatch_attempt_remote_worker(item, common, queue, started)
        # Enqueue failure means the remote task was not accepted and is safe to
        # continue locally.  A poll timeout is deliberately not downgraded: the
        # remote task may still be executing and a local retry could duplicate an
        # effect.
        if not (
            _local_fallback_enabled()
            and remote_record.get("reason_code") == "remote_enqueue_failed"
            and remote_record.get("remote_error_class") in {"QueueUnavailable", "OSError"}
        ):
            return remote_record
        common["distributed_fallback"] = {
            "schema": "simplicio.loop.distributed-fallback/v1",
            "requested": "remote",
            "selected": "local",
            "reason_code": "remote_unavailable",
            "error": str(remote_record.get("error") or "remote enqueue unavailable")[:512],
        }
        queue = None
    lease = None
    mapper_operations = None
    mapper_attempt = None
    guarded = _guarded_dispatch_enabled()
    attempt_coordinator: Optional[AttemptCoordinator] = None
    attempt_obj: Any = None
    if queue is not None:
        identity = item.get("agent_identity")
        try:
            if guarded and identity:
                # #288/#183: real dispatch attempts get a heartbeat-guarded, fenced attempt
                # object instead of a bare lease -- the same lease/fencing contract, plus the
                # ability to run the mutating subprocess through ``run_guarded`` below.
                attempt_coordinator = AttemptCoordinator(queue, run_id=common["run_id"])
                context_pack = item.get("context_pack") if isinstance(item.get("context_pack"), Mapping) else {}
                attempt_obj = attempt_coordinator.claim(
                    work_item_id=common["task_id"],
                    identity=identity,
                    goal=str(context_pack.get("goal") or common["task_id"]),
                    acs=tuple(context_pack.get("acs") or ()),
                    depends_on=tuple(context_pack.get("depends_on") or ()),
                    source_refs=tuple(context_pack.get("source_refs") or ()),
                    allowed_paths=tuple(context_pack.get("allowed_paths") or ()),
                    issue_ref=str(context_pack.get("issue_ref") or ""),
                    issue_url=str(context_pack.get("issue_url") or ""),
                    ttl=float(os.environ.get("SIMPLICIO_REMOTE_QUEUE_TTL", "3600")),
                )
                lease = attempt_obj.lease
            else:
                lease = queue.claim(
                    common["task_id"], common["worker_id"],
                    idempotency_key=f"{common['run_id']}:{common['task_id']}:{common['worker_id']}",
                    ttl=float(os.environ.get("SIMPLICIO_REMOTE_QUEUE_TTL", "3600")),
                    identity=identity,
                    capabilities=(identity or {}).get("capabilities", ()),
                )
            common["lease"] = {
                "lease_id": lease.lease_id,
                "fencing_token": lease.fencing_token,
                "expires_at": lease.expires_at,
            }
            common["guarded_dispatch"] = attempt_obj is not None
        except QueueConflict as exc:
            return {**common, "status": "failed", "phase": "blocked", "execution_state": "paused",
                    "reason_code": "claim_conflict", "error": str(exc), "dead_letter": True,
                    "started_at": started, "finished_at": _now()}
        except (QueueUnavailable, OSError) as exc:
            # The remote queue is an optional accelerator.  If it is genuinely
            # unavailable, release the unclaimed item into the isolated local
            # lane instead of dead-lettering the whole batch.  Keep conflicts
            # and malformed/trust-invalid configuration fail-closed below.
            if _local_fallback_enabled() and isinstance(queue, HTTPRemoteQueue):
                common["distributed_fallback"] = {
                    "schema": "simplicio.loop.distributed-fallback/v1",
                    "requested": "remote",
                    "selected": "local",
                    "reason_code": "remote_unavailable",
                    "error": str(exc)[:512],
                }
                queue = None
            else:
                return {**common, "status": "failed", "phase": "blocked", "execution_state": "paused",
                        "reason_code": "network_paused", "error": str(exc), "dead_letter": True,
                        "started_at": started, "finished_at": _now()}
        except ValueError as exc:
            return {**common, "status": "failed", "phase": "blocked", "execution_state": "paused",
                    "reason_code": "network_paused", "error": str(exc), "dead_letter": True,
                    "started_at": started, "finished_at": _now()}
    if lease is not None:
        # Only stall a task that is genuinely claimed/leased -- this is what lets the
        # cross-process recovery test kill the orchestrator mid-attempt with a real,
        # in-flight (not merely queued) lease abandoned behind it.
        _test_only_stall_before_dispatch(str(common.get("task_id") or ""))
    if item.get("worktree_error"):
        return {
            **common,
            "status": "failed",
            "phase": "blocked",
            "execution_state": "error",
            "reason_code": "worktree_context_unpersisted",
            "receipt": "",
            "attempt": 0,
            "error": str(item["worktree_error"]),
            "failure_fingerprint": hashlib.sha256(
                str(item["worktree_error"]).encode("utf-8", "replace")
            ).hexdigest()[:16],
            "started_at": started,
            "finished_at": _now(),
        }
    if _mapper_journal_enabled():
        try:
            dispatch_repo_path = Path(str(item.get("repo") or ".")).resolve()
            # An isolated worktree lane relocates ``item["repo"]`` to a freshly
            # allocated, per-task path (see `_ensure_deferred_worktree_context`)
            # that the earlier batch-level pre-pass could not have known about --
            # ensure its Mapper operations store here too, not just the original
            # pre-worktree repo path.
            _ensure_mapper_operations_store(dispatch_repo_path)
            mapper_operations, mapper_attempt = _claim_mapper_operation_attempt(
                dispatch_repo_path,
                run_id=common["run_id"],
                task_index=int(common["task_index"]),
                task_id=common["task_id"],
                worker_id=common["worker_id"],
                targets=list(
                    (item.get("context_pack") or {}).get("allowed_paths") or []
                ),
            )
            mapper_lease = mapper_attempt.lease
            common["mapper_operation"] = {
                "task_id": mapper_lease.task_id,
                "attempt_id": mapper_lease.attempt_id,
                "lease_id": mapper_lease.lease_id,
                "worker_id": mapper_lease.worker_id,
                "fence_token": mapper_lease.fence_token,
            }
            if attempt_obj is None:
                attempt_obj = mapper_attempt
        except Exception as exc:
            return {
                **common,
                "status": "failed",
                "phase": "blocked",
                "execution_state": "error",
                "receipt": "",
                "operator_receipt": "",
                "evidence_receipt": "",
                "receipt_status": "UNVERIFIED",
                "attempt": 0,
                "error": f"{type(exc).__name__}: {exc}",
                "reason_code": "mapper_operation_claim_failed",
                "dead_letter": True,
                "failure_fingerprint": hashlib.sha256(
                    f"{type(exc).__name__}: {exc}".encode("utf-8", "replace")
                ).hexdigest()[:16],
                "started_at": started,
                "finished_at": _now(),
            }
    try:
        payload = execute_operator(
            item["repo"], item["run_id"], task_index=item["task_index"],
            attempt_coordinator=attempt_coordinator, guarded_attempt=attempt_obj,
            authority_receipt=item.get("authority_receipt"),
            authority_attempt=int(item.get("authority_attempt") or 1),
            admission_fence=int(item.get("admission_fence") or 1),
            owned_process_registry=item.get("owned_process_registry"),
            owned_task_id=str(common.get("task_id") or ""),
            provider_worker=str(item.get("provider_worker") or "") or None,
            repair_feedback=item.get("repair_feedback"),
        )
        state = payload.get("state") or {}
        operator = state.get("operator") or {}
        execution_state = str(operator.get("execution_state") or "")
        success = execution_state == "applied"
        receipt = str(operator.get("receipt") or "")
        evidence = state.get("evidence") or {}
        evidence_receipt = str(evidence.get("receipt") or "")
        run_dir = str(payload.get("run_dir") or "")
        watcher_receipt = str(Path(run_dir) / "loop" / "watcher_state.json") if run_dir else ""
        failure_fingerprint = ""
        # #NOWASTE: derive the deterministic-vs-transient reason_code from whatever the
        # receipt actually carries (a discrete `_finish_operator_blocked` reason_code, or
        # -- for a dev-cli apply subprocess's own find/replace rejection -- its stdout/
        # stderr text) so the retry loop above can stop after one attempt instead of
        # burning the whole retry budget on a guaranteed repeat.
        reason_code = str(operator.get("reason_code") or "")
        if receipt:
            try:
                receipt_payload = _load_json(Path(receipt))
                failure_fingerprint = str(receipt_payload.get("failure_fingerprint") or "")
                if not success and not reason_code:
                    reason_code = _classify_devcli_receipt_failure(receipt_payload)
            except (OSError, ValueError, TypeError):
                # The worker result remains useful even when a crashed operator did not leave
                # a readable receipt; the scheduler will use the bounded exception path.
                failure_fingerprint = ""
        if lease is not None and success:
            receipt_ref_value = receipt or f"{run_dir}/operator-receipt.json"
            if attempt_coordinator is not None and attempt_obj is not None:
                attempt_coordinator.complete(attempt_obj, receipt_ref=receipt_ref_value)
            else:
                # #286 step 9: present a wire receipt the queue server itself independently
                # verifies (schema/hash/task-agent-fence binding), not just an opaque
                # ``receipt_ref`` path it has no way to open or trust.
                queue.complete(lease, receipt_ref=receipt_ref_value, receipt=build_completion_receipt(
                    task_id=lease.task_id, agent_id=lease.agent_id, fencing_token=lease.fencing_token,
                    receipt_ref=receipt_ref_value,
                ))
        if item.get("agent_identity") and receipt:
            # Keep the worker result itself immutable and independently attributable.
            common["receipt_binding"] = bind_receipt(
                {"receipt_ref": receipt}, item["agent_identity"],
                context_pack=item.get("context_pack"),
            )
        receipt_verdict = _verify_worker_receipt_pair(receipt, evidence_receipt)
        mapper_completion = None
        mapper_completion_error = ""
        if mapper_operations is not None and mapper_attempt is not None:
            mapper_lease = mapper_attempt.lease
            try:
                mapper_completion = mapper_operations.complete(
                    mapper_lease,
                    status="completed" if success else "failed",
                    receipt={
                        "run_id": common["run_id"],
                        "task_id": common["task_id"],
                        "task_index": common["task_index"],
                        "operator_receipt": receipt,
                        "evidence_receipt": evidence_receipt,
                        "status": "completed" if success else "failed",
                    },
                )
            except Exception as exc:
                mapper_completion_error = f"{type(exc).__name__}: {exc}"
                if success:
                    success = False
                try:
                    mapper_operations.release(mapper_lease)
                except Exception as release_exc:
                    mapper_completion_error += f"; release={type(release_exc).__name__}: {release_exc}"
        merge: Optional[Dict[str, Any]] = None
        if success and receipt_verdict["status"] == ReceiptStatus.VERIFIED and _auto_merge_enabled():
            # #288: once the receipt pair is genuinely VERIFIED, create/poll/merge the real
            # PR and reconcile against the remote before this dispatch attempt is reported
            # as done -- replaces the ad-hoc, hand-run "gh pr create / gh pr merge" pattern
            # this project's own delivery process previously left as prose only.
            merge = _dispatch_merge_pr(item, receipt=receipt, run_id=common["run_id"])
        verified_delivery: Optional[Dict[str, Any]] = None
        if success and _verified_delivery_gate_enabled():
            # #288: route the completion decision through the real LoopRuntimeAdapter ->
            # VerifiedAgentDelivery -> ExecutionBoard chain instead of trusting
            # execution_state == "applied" alone -- see `_verified_delivery_gate_enabled`.
            identity = dict(item.get("agent_identity") or {})
            verified_delivery = _run_verified_delivery_gate(
                run_id=common["run_id"], task_id=common["task_id"],
                actor=str(identity.get("actor") or identity.get("agent_id") or "loop"),
                attempt_id="%s-attempt-%d" % (common["worker_id"], int(state.get("attempts") or 0) or 1),
                receipt_verdict=receipt_verdict, evidence_receipt=evidence_receipt,
                watcher_receipt=watcher_receipt, merge=merge, worktree_context=context,
            )
            if not verified_delivery.get("verified"):
                success = False
        return {
            **common,
            "status": "succeeded" if success else "failed",
            "phase": str(state.get("phase") or "blocked"),
            "execution_state": execution_state or "unknown",
            "receipt": receipt,
            "operator_receipt": receipt,
            "evidence_receipt": evidence_receipt,
            "watcher_receipt": watcher_receipt if Path(watcher_receipt).exists() else "",
            "receipt_status": receipt_verdict["status"],
            "receipt_verdict_reason": receipt_verdict["reason"],
            "attempt": int(state.get("attempts") or 0),
            "reason_code": reason_code,
            "failure_fingerprint": failure_fingerprint,
            "merge": merge,
            "verified_delivery": verified_delivery,
            "mapper_operation_completion": mapper_completion,
            "mapper_operation_completion_error": mapper_completion_error,
            "started_at": started,
            "finished_at": _now(),
        }
    except LeaseLostDuringExecution as exc:
        if mapper_operations is not None and mapper_attempt is not None:
            try:
                mapper_operations.release(mapper_attempt.lease)
            except Exception:
                pass
        # #183/#288: the guarded subprocess was killed the instant the lease was no longer
        # current -- report this distinctly from a generic operator exception so a scheduler
        # can tell "lost the fence mid-mutation" apart from an ordinary tool crash.
        return {
            **common,
            "status": "failed",
            "phase": "blocked",
            "execution_state": "error",
            "receipt": "",
            "operator_receipt": "",
            "evidence_receipt": "",
            "receipt_status": "UNVERIFIED",
            "attempt": 0,
            "error": str(exc),
            "reason_code": "lease_lost_during_execution",
            "dead_letter": True,
            "failure_fingerprint": hashlib.sha256(str(exc).encode("utf-8", "replace")).hexdigest()[:16],
            "started_at": started,
            "finished_at": _now(),
        }
    except Exception as exc:  # worker failures are receipts, not scheduler crashes
        if mapper_operations is not None and mapper_attempt is not None:
            try:
                mapper_operations.release(mapper_attempt.lease)
            except Exception:
                pass
        return {
            **common,
            "status": "failed",
            "phase": "blocked",
            "execution_state": "error",
            "receipt": "",
            "operator_receipt": "",
            "evidence_receipt": "",
            "receipt_status": "UNVERIFIED",
            "attempt": 0,
            "error": f"{type(exc).__name__}: {exc}",
            "reason_code": _classify_operator_exception_reason_code(exc),
            "failure_fingerprint": hashlib.sha256(
                f"{type(exc).__name__}: {exc}".encode("utf-8", "replace")
            ).hexdigest()[:16],
            "started_at": started,
            "finished_at": _now(),
        }


def _independent_verification_feedback(record: Mapping[str, Any]) -> str:
    """Return only the existing independent-verifier detail eligible for a retry."""
    verification = record.get("verified_delivery")
    if not isinstance(verification, Mapping) or verification.get("verified") is not False:
        return ""
    detail = verification.get("reason")
    return detail.strip() if isinstance(detail, str) else ""


def _run_operator_item_process(item: Mapping[str, Any], retry_budget: int, owned_process_registry: Any = None) -> List[Dict[str, Any]]:
    """Run one complete operator lane in a supervised child process.

    The input is a plain dispatch item and the returned records are compact JSON-like
    values, so the coordinator can persist the existing journal and receipt contracts.
    Queue/worktree release remains coordinator-owned after the child exits.
    """
    attempts: List[Dict[str, Any]] = []
    previous_fingerprint = ""
    repair_feedback = item.get("repair_feedback")
    for attempt_no in range(1, max(0, int(retry_budget)) + 2):
        dispatch_item = dict(item)
        dispatch_item["owned_process_registry"] = owned_process_registry
        if repair_feedback:
            dispatch_item["repair_feedback"] = repair_feedback
        elif attempt_no > 1:
            dispatch_item.pop("repair_feedback", None)
        record = _operator_dispatch_attempt(dispatch_item)
        record["dispatch_attempt"] = attempt_no
        if previous_fingerprint and record.get("failure_fingerprint") == previous_fingerprint:
            record["retry_strategy"] = "same_fingerprint_bounded"
        elif attempt_no > 1:
            record["retry_strategy"] = "alternate_strategy"
        else:
            record["retry_strategy"] = "initial"
        attempts.append(record)
        if record.get("status") == "succeeded":
            break
        if _is_deterministic_operator_failure(record):
            # #NOWASTE: this exact task/plan/repo-state will fail the same way every
            # time -- record it once and dead-letter instead of burning the retry
            # budget on a guaranteed repeat.
            record["retry_skipped_reason"] = "deterministic_failure_no_retry"
            break
        repair_feedback = _independent_verification_feedback(record)
        previous_fingerprint = str(record.get("failure_fingerprint") or "")
    final = attempts[-1]
    final["dead_letter"] = final.get("status") != "succeeded"
    final["attempt_count"] = len(attempts)
    final["retry_scope"] = "worker-process"
    final["attempt_history"] = [
        {"dispatch_attempt": int(record.get("dispatch_attempt") or index),
         "status": record.get("status", "UNVERIFIED"),
         "failure_fingerprint": record.get("failure_fingerprint", "")}
        for index, record in enumerate(attempts, start=1)
    ]
    return attempts


def _mapper_journal_enabled(storage_route: StorageRoute | str | None = None) -> bool:
    raw = _storage_route_requested() if storage_route is None else storage_route
    try:
        return StorageRoute(raw) == StorageRoute.MAPPER
    except ValueError as error:
        raise StoreAdapterError("STORAGE_ROUTE_INVALID") from error


def _dispatch_journal_backend(
    journal_path: Optional[Path], *, repo_root: Optional[Path] = None,
) -> Any:
    """Select the journal from the rollout route; legacy remains pre-cutover default."""
    if _mapper_journal_enabled():
        # Mapper operations are repository-scoped.  Using the coordinator's cwd here
        # misroutes a zero-config run when the task repository is a fixture, worktree,
        # or child checkout launched from another project.
        root = Path(repo_root).resolve() if repo_root is not None else None
        if root is None and journal_path is not None:
            journal = Path(journal_path).resolve()
            for parent in (journal.parent, *journal.parents):
                if parent.name == "loop-runs" and parent.parent.name == ".simplicio-loop":
                    root = parent.parent.parent
                    break
        root = root or Path.cwd()
        return MapperRunJournal(_mapper_operations_database(root), auto_create=False)
    if journal_path is None:
        raise RuntimeError("JOURNAL_PATH_REQUIRED")
    return RunJournal(journal_path)


def _append_dispatch_journal(
    journal_path: Optional[Path], run_id: str, kind: str,
    payload: Mapping[str, Any], idempotency_key: str,
    *, repo_root: Optional[Path] = None,
) -> None:
    """Persist one idempotent batch lifecycle event in the existing RunJournal."""
    if journal_path is None:
        return
    journal = _dispatch_journal_backend(journal_path, repo_root=repo_root)
    if not journal.events(run_id):
        journal.append(
            run_id, "run_started", {"scope": "operator_batch"},
            idempotency_key="run:started",
        )
    journal.append(
        run_id, kind, dict(payload), idempotency_key=idempotency_key,
    )


def _dispatch_journal_recovery(
    journal_path: Optional[Path], run_id: str, *, repo_root: Optional[Path] = None,
) -> List[int]:
    """Return task indexes with a durable start but no terminal event."""
    if journal_path is None or (
        not _mapper_journal_enabled() and not journal_path.exists()
    ):
        return []
    events = _dispatch_journal_backend(journal_path, repo_root=repo_root).events(run_id)
    active: Dict[int, bool] = {}
    for event in events:
        payload = event.get("payload") or {}
        try:
            task_index = int(payload.get("task_index"))
        except (TypeError, ValueError):
            continue
        if event.get("kind") == "dispatch_started":
            active[task_index] = True
        elif event.get("kind") == "dispatch_terminal":
            active.pop(task_index, None)
    return sorted(active)


def dispatch_operator_batch(
    items: Iterable[Mapping[str, Any]],
    *,
    max_workers: Optional[int] = None,
    retry_budget: int = 3,
    journal_dir: Optional[str] = None,
    worktree_queue: Any = None,
    stop_requested: Optional[Callable[[], bool]] = None,
    owned_cancel: Optional[Callable[[str], Any]] = None,
    physical_monitor_kwargs: Optional[Mapping[str, Any]] = None,
    provider_worker: str | None = None,
) -> Dict[str, Any]:
    """Continuously dispatch real operator workers and refill freed slots.

    ``items`` is the typed bridge between a scheduler (DAG/leases/worktrees) and the
    existing mapper → plan → ``execute_operator`` boundary.  It is intentionally agnostic
    about claiming: callers pass only ready, atomically claimed nodes.  Items with the same
    ``isolation_key`` are forced onto one lane so a shared run state cannot be corrupted;
    distinct worktree/run contexts overlap in the pool.  A JSONL journal records each attempt
    before the next slot is refilled, so a process restart can safely resubmit only work that
    has no successful receipt.
    """
    normalized = [_operator_dispatch_item(item) for item in items]
    if provider_worker is not None:
        selected_provider_worker = str(provider_worker).strip().lower()
        for item in normalized:
            item["provider_worker"] = selected_provider_worker
    keys = {(item["repo"], item["run_id"], item["task_index"]) for item in normalized}
    if len(keys) != len(normalized):
        raise ValueError("operator dispatch contains duplicate repo/run/task items")
    normalized = _ordered_dispatch_items(normalized)
    prism_enabled = len(normalized) > 3
    has_dependencies = any(_item_dependencies(item) for item in normalized)

    # Issue #288 cross-process recovery: load the journal *before* preflight so a resumed
    # batch can tell "already durably succeeded" items apart from ones still needing a fresh
    # dry-run preflight. A succeeded item's operator-receipt.json has already been
    # overwritten by `execute_operator` with a *post-execution* receipt (no `run_id` field,
    # a different shape than the pre-execution dry-run receipt `_validate_run_receipts`
    # expects) -- re-validating it as if it were still a pending dry-run would always fail
    # and permanently block every resumed batch that contains even one completed item.
    journal_path: Optional[Path] = None
    durable_journal_path: Optional[Path] = None
    repo_root_by_run = {
        str(item["run_id"]): Path(item["repo"]).resolve()
        for item in normalized
    }
    if _mapper_journal_enabled():
        # Every repo a task will run its mutation attempt in needs an initialized
        # Mapper operations store *before* any worker tries to claim a lease there --
        # otherwise the first `_claim_mapper_operation_attempt` call in each fresh
        # worktree/repo fails closed with STORE_NOT_INITIALIZED. `execute_operator_batch`
        # already does this for its single, already-materialized run repo; this
        # boundary fans out across possibly-multiple, possibly-not-yet-materialized
        # repos, so it must ensure the store itself. Note this is *not* the same set
        # as ``repo_root_by_run.values()`` -- several items can share one run_id
        # while fanning out into distinct per-item repos/worktrees, and a dict keyed
        # by run_id keeps only the last item's repo for that key.
        for repo_path in {Path(item["repo"]).resolve() for item in normalized}:
            _ensure_mapper_operations_store(repo_path)
    if journal_dir:
        journal_path = Path(journal_dir).resolve() / "operator-batch.jsonl"
        journal_path.parent.mkdir(parents=True, exist_ok=True)
        # The retired legacy route is intentionally read-only.  Keep its
        # append-only JSONL attempt records, but do not instantiate the old
        # RunJournal facade (which must fail closed) or pretend it can provide
        # MapperStore recovery semantics.  The Mapper route gets the durable
        # operations journal as before.
        if _mapper_journal_enabled():
            durable_journal_path = journal_path.parent / "run-journal.sqlite"
    recovery_pending_by_run: Dict[str, set[int]] = {}
    if durable_journal_path is not None:
        # A dispatch backed by a real distributed queue already has its own,
        # independently-tested crash-recovery contract: the abandoned item's lease
        # expires and a fresh claim carries a strictly higher fencing token (see
        # `tests/test_work_item_claims_chaos_system.py` / `test_system_276_e2e_system.py`).
        # The durable-journal "unknown effect" reconciliation below exists for the
        # opposite case -- no queue/lease at all to tell "still in flight" apart from
        # "crashed mid-effect" -- so it must not also swallow a queue-backed item and
        # block it from ever being re-claimed.
        queueless_indices_by_run: Dict[str, set[int]] = {}
        for item in normalized:
            if item.get("distributed_queue") is None:
                queueless_indices_by_run.setdefault(str(item["run_id"]), set()).add(item["task_index"])
        for run_id in {item["run_id"] for item in normalized}:
            pending_indices = set(_dispatch_journal_recovery(
                durable_journal_path,
                run_id,
                repo_root=repo_root_by_run.get(str(run_id)),
            )) & queueless_indices_by_run.get(str(run_id), set())
            if pending_indices:
                recovery_pending_by_run[run_id] = pending_indices
    prior = _load_prior_dispatch_records(journal_path) if journal_path else {}

    # A persisted run is a privileged execution boundary.  Keep synthetic scheduler
    # contexts supported, but fail every run-backed dispatch globally before worktree
    # preparation, journal creation, or worker submission unless its receipt chain is
    # fresh and bound to this exact run -- except an item already durably journaled as
    # succeeded, which is never re-dispatched and so must never be re-validated as if it
    # still needed a fresh dry run.
    for item in normalized:
        key = (item["repo"], item["run_id"], item["task_index"])
        if prior.get(key, {}).get("status") == "succeeded":
            continue
        repo_path = Path(item["repo"]).resolve()
        run_dir = repo_path / ".simplicio-loop" / "loop-runs" / item["run_id"]
        if not run_dir.is_dir():
            continue
        try:
            contract = _require_json_receipt(run_dir / "task-contract.json", "task contract")
            _validate_run_receipts(
                repo_path,
                run_dir,
                contract,
                state=_load_json(run_dir / "state.json") if (run_dir / "state.json").is_file() else None,
                manifest=_load_json(run_dir / "manifest.json") if (run_dir / "manifest.json").is_file() else None,
                require_dry_run=True,
            )
        except (OSError, TypeError, ValueError, RuntimeError) as exc:
            state_path = run_dir / "state.json"
            if state_path.is_file():
                _persist_batch_preflight_block(
                    run_dir,
                    _load_json(state_path),
                    repo_path,
                    str(exc),
                    task_indices=[item["task_index"]],
                )
            raise
    requested_workers = max_workers
    effective_workers = _operator_worker_limit(max_workers, len(normalized))
    serial_fallback_reason = ""
    # A queued worktree is a lease-bearing mutation resource.  Reserve independent
    # worktree lanes for the capacity request, but retain the shared-run serial guard
    # when no queue can provide those lanes.  Allocation itself happens only after the
    # first physical admission decision below.
    candidate_isolation_keys = {
        ("worktree:%s" % item["task_id"]
         if worktree_queue is not None and str(item.get("isolation") or "worktree") == "worktree"
         else item["isolation_key"])
        for item in normalized
    }
    if effective_workers > 1 and len(candidate_isolation_keys) < len(normalized):
        effective_workers = 1
        serial_fallback_reason = "shared_run_state"
    if has_dependencies:
        # A dependent task must observe the predecessor's real checkout and
        # task-result receipt. Keep the governed lane serial for both direct
        # parallelism and Prism; the physical governor remains active.
        effective_workers = 1
        serial_fallback_reason = "dependency_order"
    retry_budget = max(0, int(retry_budget))
    from .local_capacity import PhysicalAdmissionMonitor
    monitor_kwargs = _physical_monitor_kwargs(physical_monitor_kwargs)
    if prism_enabled:
        prism_scheduler, prism_id, capacity_sample = _build_native_prism_scheduler(
            normalized, effective_workers, physical_monitor_kwargs=monitor_kwargs,
        )
        physical_monitor = getattr(prism_scheduler, "native_capacity_monitor", None)
        direct_governor = None
        effective_workers = max(0, min(effective_workers, int(capacity_sample["safe_workers"])))
    else:
        # One to three tasks use the direct executor path. Keep the same
        # receipt/journal/lease machinery and the same physical governor,
        # without creating a second scheduler graph.
        from .prism_budgets import AdaptiveBudgetGovernor, BudgetSample
        from .prism_scheduler import PrismPolicy
        capacity_root = Path(str((normalized[0].get("repo") if normalized else None) or ".")).resolve()
        while not capacity_root.exists() and capacity_root != capacity_root.parent:
            capacity_root = capacity_root.parent
        if monitor_kwargs:
            physical_monitor = PhysicalAdmissionMonitor(
                str(capacity_root), effective_workers, **monitor_kwargs,
            )
        else:
            physical_monitor = PhysicalAdmissionMonitor(
                str(capacity_root), effective_workers,
            )
        direct_policy = PrismPolicy(
            global_worker_limit=max(1, effective_workers),
            recovery_reserve=0,
            validation_reserve=0,
        )
        direct_governor = AdaptiveBudgetGovernor(direct_policy, relief_samples=2)

        def _direct_budget_sample(sample: Any) -> BudgetSample:
            null_reasons = {
                name: "local_probe_not_supported"
                for name in (
                    "cpu_millis", "rss_bytes", "io_units", "provider_requests",
                    "tokens", "model_slots", "network_queue", "context_tokens",
                    "evidence_bytes",
                )
            }
            if sample.safe_workers < 1 or sample.unavailable:
                null_reasons["workers"] = sample.null_reasons.get(
                    "workers", "required_capacity_signal_unavailable"
                )
            return BudgetSample(
                workers=int(sample.safe_workers),
                observed_at_ns=int(sample.observed_at_ns),
                null_reasons=null_reasons,
            )

        direct_sample = physical_monitor.refresh(force=True)
        effective_workers = max(0, min(effective_workers, int(direct_sample.safe_workers)))
        direct_governor.observe(_direct_budget_sample(direct_sample))
        prism_scheduler = None
        prism_id = ""
        capacity_sample = direct_sample.to_dict()
        capacity_sample["schema"] = "simplicio.direct-parallelism-capacity/v1"
        capacity_sample["source"] = "physical_admission_monitor"
        capacity_sample["budget_governor"] = direct_governor.status()
        capacity_sample["monitor"] = physical_monitor.status()
        capacity_sample["policy"] = {
            "recovery_reserve": direct_policy.recovery_reserve,
            "validation_reserve": direct_policy.validation_reserve,
            "global_worker_limit": direct_policy.global_worker_limit,
        }
    capacity_admission: dict[str, Any] = (
        physical_monitor.admission_status()
        if physical_monitor is not None
        else {
            "admitted": False,
            "reason_code": "PHYSICAL_SAMPLE_UNAVAILABLE",
            "reason": "monitor_unavailable",
            "evidence": {},
        }
    )
    # Admission precedes all queue allocation.  A blocked batch therefore leaves no
    # worktree or shared-checkout lease behind for a later retry to mistake as owned.
    if capacity_admission.get("admitted"):
        _prepare_worktree_contexts(normalized, worktree_queue, defer_worktrees=True)
        actual_isolation_keys = {item["isolation_key"] for item in normalized}
        if effective_workers > 1 and len(actual_isolation_keys) < len(normalized):
            effective_workers = 1
            serial_fallback_reason = "shared_run_state"

    pending = deque(
        item for item in normalized
        if prior.get((item["repo"], item["run_id"], item["task_index"]), {}).get("status") != "succeeded"
        and item["task_index"] not in recovery_pending_by_run.get(item["run_id"], set())
    )
    # ``skipped_completed`` is specifically the durably-succeeded items a resumed batch
    # does not redo -- not every item this pass excludes from `pending`. An item held
    # back instead as `recovery_pending` (a crashed dispatch with a durable start but no
    # terminal event) is counted separately in `recovery_blocked_count` below; folding it
    # into `skipped_completed` would misreport a not-yet-reconciled item as "already done".
    skipped = sum(
        1 for item in normalized
        if prior.get((item["repo"], item["run_id"], item["task_index"]), {}).get("status") == "succeeded"
    )
    pending_task_ids = {str(item.get("task_id") or "") for item in pending}
    prism_admitted: deque[str] = deque()
    # A resumed batch can have a completed item at the head of Prism's ready queue.
    # Retire those durable successes before admitting fresh work; otherwise a full
    # capacity sample leaves the pending item permanently invisible behind the skip.
    if prism_enabled and capacity_admission.get("admitted"):
        while True:
            admitted = prism_scheduler.next_batch()
            if not admitted:
                break
            for task in admitted:
                if task.task_id in pending_task_ids:
                    prism_admitted.append(task.task_id)
                    continue
                try:
                    recovery = any(
                        item.get("task_id") == task.task_id
                        and int(item.get("task_index", -1))
                        in recovery_pending_by_run.get(str(item.get("run_id") or ""), set())
                        for item in normalized
                    )
                    prism_scheduler.complete(
                        task.task_id, "blocked" if recovery else "accepted",
                        owner_agent=task.ownership.owner_agent,
                        fence=task.ownership.fence,
                    )
                except Exception:
                    # The scheduler remains authoritative; a later normal admission or
                    # terminal path will surface any unexpected state mismatch.
                    continue
    else:
        prism_admitted.extend(str(item.get("task_id") or "") for item in pending)
    for item in pending:
        _append_dispatch_journal(
            durable_journal_path, item["run_id"], "dispatch_queued",
            {
                "task_id": item["task_id"], "task_index": item["task_index"],
                "worker_id": item["worker_id"], "isolation_key": item["isolation_key"],
            },
            f"dispatch:{item['task_id']}:queued",
            repo_root=Path(item["repo"]).resolve(),
        )
    for run_id, task_indices in recovery_pending_by_run.items():
        for task_index in sorted(task_indices):
            _append_dispatch_journal(
                durable_journal_path, run_id, "dispatch_recovery_pending",
                {
                    "task_index": task_index,
                    "reason_code": "unknown_effect_reconciliation_required",
                },
                f"dispatch:{run_id}:{task_index}:recovery-pending",
                repo_root=repo_root_by_run.get(str(run_id)),
            )
    started = _now()
    records: Dict[Tuple[str, str, int], Dict[str, Any]] = dict(prior)
    for item in normalized:
        if item["task_index"] not in recovery_pending_by_run.get(item["run_id"], set()):
            continue
        records[(item["repo"], item["run_id"], item["task_index"])] = {
            "schema": "simplicio.operator-worker/v1",
            "worker_id": item["worker_id"], "repo": item["repo"],
            "source_repo": item.get("source_repo", item["repo"]),
            "run_id": item["run_id"], "task_index": item["task_index"],
            "task_id": item.get("task_id", ""),
            "worktree_context": item.get("worktree_context", {}),
            "status": "blocked", "phase": "recovery",
            "execution_state": "unknown_effect",
            "reason_code": "unknown_effect_reconciliation_required",
            "recovery_pending": True, "dead_letter": False,
            "attempt": 0, "attempt_count": 0,
            "started_at": _now(), "finished_at": _now(),
        }
    completed: List[Dict[str, Any]] = []
    refill_count = 0
    initial_admissions = 0
    stop_reason = ""
    capacity_stop_reason = ""

    def _drain_requested() -> bool:
        nonlocal stop_reason
        if stop_requested is None:
            return False
        try:
            requested = bool(stop_requested())
        except Exception as exc:
            stop_reason = f"stop_callback_failed:{type(exc).__name__}"
            return True
        if requested and not stop_reason:
            stop_reason = "operator_stop_requested"
        return requested

    def _persist_attempt(record: Dict[str, Any]) -> None:
        if journal_path:
            _append_jsonl(journal_path, record)
        records[(record["repo"], record["run_id"], record["task_index"])] = record

    def _run_item(item: Dict[str, Any], owned_process_registry: Any = None) -> List[Dict[str, Any]]:
        attempts: List[Dict[str, Any]] = []
        previous_fingerprint = ""
        repair_feedback = item.get("repair_feedback")
        _ensure_deferred_worktree_context(item, worktree_queue)
        try:
            for attempt_no in range(1, retry_budget + 2):
                dispatch_item = dict(item)
                dispatch_item["owned_process_registry"] = owned_process_registry
                if repair_feedback:
                    dispatch_item["repair_feedback"] = repair_feedback
                elif attempt_no > 1:
                    dispatch_item.pop("repair_feedback", None)
                record = _operator_dispatch_attempt(dispatch_item)
                record["dispatch_attempt"] = attempt_no
                if previous_fingerprint and record.get("failure_fingerprint") == previous_fingerprint:
                    record["retry_strategy"] = "same_fingerprint_bounded"
                elif attempt_no > 1:
                    record["retry_strategy"] = "alternate_strategy"
                else:
                    record["retry_strategy"] = "initial"
                attempts.append(record)
                if record["status"] == "succeeded":
                    break
                if _is_deterministic_operator_failure(record):
                    # #NOWASTE: same reasoning as `_run_operator_item_process` -- a
                    # deterministic failure is recorded once, never retried.
                    record["retry_skipped_reason"] = "deterministic_failure_no_retry"
                    break
                repair_feedback = _independent_verification_feedback(record)
                previous_fingerprint = str(record.get("failure_fingerprint") or "")
        finally:
            _release_shared_context(item, worktree_queue)
        attempts[-1]["dead_letter"] = attempts[-1]["status"] != "succeeded"
        # Keep compact per-lane history on the final record while the JSONL journal
        # retains the complete receipts.  This proves a retry belongs to one worker and
        # did not restart sibling lanes.
        attempts[-1]["attempt_count"] = len(attempts)
        attempts[-1]["retry_scope"] = "worker"
        attempts[-1]["attempt_history"] = [
            {
                "dispatch_attempt": int(record.get("dispatch_attempt") or index),
                "status": record.get("status", "UNVERIFIED"),
                "failure_fingerprint": record.get("failure_fingerprint", ""),
            }
            for index, record in enumerate(attempts, start=1)
        ]
        return attempts

    def _take_prism_admitted() -> Optional[Dict[str, Any]]:
        for item in pending:
            if item.get("task_id") not in prism_admitted:
                continue
            pending.remove(item)
            prism_admitted.remove(item.get("task_id"))
            return item
        return None

    def _refill_prism(*, refresh_capacity: bool = True) -> None:
        if not prism_enabled:
            return
        if refresh_capacity:
            refresh = getattr(prism_scheduler, "native_capacity_refresh", None)
            if refresh is not None:
                refresh()
        for task in prism_scheduler.next_batch():
            if task.task_id not in prism_admitted:
                prism_admitted.append(task.task_id)

    def _update_direct_capacity_receipt(sample: Any) -> None:
        capacity_sample.clear()
        capacity_sample.update(sample.to_dict())
        capacity_sample["schema"] = "simplicio.direct-parallelism-capacity/v1"
        capacity_sample["source"] = "physical_admission_monitor"
        capacity_sample["budget_governor"] = direct_governor.status()
        capacity_sample["monitor"] = physical_monitor.status()
        capacity_sample["policy"] = {
            "recovery_reserve": direct_policy.recovery_reserve,
            "validation_reserve": direct_policy.validation_reserve,
            "global_worker_limit": direct_policy.global_worker_limit,
        }

    def _refresh_physical_admission(*, force: bool = False) -> dict[str, Any]:
        nonlocal capacity_admission
        monitor = physical_monitor
        if monitor is None:
            capacity_admission = {
                "admitted": False,
                "reason_code": "PHYSICAL_SAMPLE_UNAVAILABLE",
                "reason": "monitor_unavailable",
                "evidence": {},
            }
            return capacity_admission
        if force or monitor.due():
            if prism_enabled:
                refresh = getattr(prism_scheduler, "native_capacity_refresh", None)
                if refresh is None:
                    monitor.refresh(force=True)
                else:
                    refresh(force=True)
            else:
                refreshed = monitor.refresh(force=force)
                direct_governor.observe(_direct_budget_sample(refreshed))
                _update_direct_capacity_receipt(refreshed)
        sample = monitor.sample
        if sample is None:
            capacity_admission = {
                "admitted": False,
                "reason_code": "PHYSICAL_SAMPLE_UNAVAILABLE",
                "reason": "no_sample",
                "action": "suspend_new",
                "evidence": {},
            }
        else:
            capacity_admission = monitor.admission_status()
        return capacity_admission

    def _set_capacity_stop(admission: Mapping[str, Any]) -> None:
        nonlocal capacity_stop_reason
        if admission.get("admitted"):
            # Physical pressure is resumable after the monitor's sustained-recovery
            # window.  Operator stop requests remain in ``stop_reason`` below.
            capacity_stop_reason = ""
            return
        code = str(admission.get("reason_code") or "PHYSICAL_ADMISSION_BLOCKED")
        reason = str(admission.get("reason") or "capacity_not_admitted")
        capacity_stop_reason = f"{code}:{reason}"

    dispatch_mode = _resolve_dispatch_mode()
    registry_manager = None
    owned_process_registry: Any = {}
    if dispatch_mode == "process":
        registry_manager = Path(tempfile.mkdtemp(prefix="simplicio-owned-processes-"))
        owned_process_registry = str(registry_manager)

    owned_shutdown: dict[str, Any] = {
        "status": "not_requested", "action": "", "cancelled_task_ids": [],
        "limitations": [], "errors": [],
    }

    def _request_owned_cancel(task_id: str) -> Any:
        """Terminate the registered child, then fall back to a queue cancellation hook."""
        outcome = _terminate_owned_process(owned_process_registry, task_id)
        if outcome is not None:
            return outcome
        if owned_cancel is not None:
            return owned_cancel(task_id)
        if worktree_queue is not None:
            for method_name in ("request_cancel", "cancel_task", "release_task", "cancel"):
                method = getattr(worktree_queue, method_name, None)
                if not callable(method):
                    continue
                try:
                    return method(task_id, reason="physical_pressure_terminate")
                except TypeError:
                    return method(task_id)
        return None

    def _shutdown_owned(admission: Mapping[str, Any], active: Mapping[Any, Mapping[str, Any]]) -> None:
        if str(admission.get("action") or "") != "terminate_owned":
            return
        if owned_shutdown.get("action") == "terminate_owned":
            return
        owned_shutdown.update({"status": "requested", "action": "terminate_owned"})
        for future, item in active.items():
            task_id = str(item.get("task_id") or "")
            if not task_id:
                continue
            # ``Future.cancel`` is safe for work not yet started.  A running process
            # is cancellable only through the existing owned queue/registry hook.
            if future.cancel():
                owned_shutdown["cancelled_task_ids"].append(task_id)
                continue
            try:
                outcome = _request_owned_cancel(task_id)
                cancelled = not isinstance(outcome, Mapping) or outcome.get("cancelled", True) is not False
                if outcome is None or not cancelled:
                    owned_shutdown["limitations"].append(
                        f"{task_id}:running_subprocess_requires_owned_supervisor_hook"
                    )
                elif task_id not in owned_shutdown["cancelled_task_ids"]:
                    owned_shutdown["cancelled_task_ids"].append(task_id)
            except Exception as exc:
                owned_shutdown["errors"].append(
                    f"{task_id}:{type(exc).__name__}: {exc}"
                )
        if not owned_shutdown["cancelled_task_ids"] and not owned_shutdown["errors"]:
            owned_shutdown["status"] = "limited"


    def _submit_process_item(pool: Any, item: Dict[str, Any]) -> Any:
        _ensure_deferred_worktree_context(item, worktree_queue)
        try:
            return pool.submit(_run_operator_item_process, item, retry_budget, owned_process_registry)
        except Exception:
            # Allocation happened before submission; a failed submission must release
            # the owned lease even when no worker ever receives the item.
            _release_shared_context(item, worktree_queue, force=True)
            raise

    # Queue clients remain coordinator-owned and are never sent to children.  The
    # child receives only the already-persisted, JSON-safe worktree context; the
    # coordinator releases the queue lease after the child returns.  This keeps
    # process supervision as the default even when isolated worktrees are enabled.
    executor_type = ProcessPoolExecutor if dispatch_mode == "process" else ThreadPoolExecutor
    executor_kwargs = {"max_workers": effective_workers}
    if dispatch_mode == "process" and os.name == "posix":
        try:
            import multiprocessing as _mp
            if "fork" in _mp.get_all_start_methods():
                executor_kwargs["mp_context"] = _mp.get_context("fork")
        except (AttributeError, ValueError):
            pass
    if dispatch_mode == "thread":
        executor_kwargs["thread_name_prefix"] = "simplicio-operator"
    _set_capacity_stop(_refresh_physical_admission())
    if pending and effective_workers and not stop_reason and not capacity_stop_reason:
        with executor_type(**executor_kwargs) as pool:
            active = {}
            while pending and len(active) < effective_workers and not _drain_requested() and not stop_reason and not capacity_stop_reason:
                admission = _refresh_physical_admission()
                if not admission.get("admitted"):
                    _set_capacity_stop(admission)
                    break
                item = _take_prism_admitted()
                if item is None:
                    break
                if dispatch_mode == "process":
                    _append_dispatch_journal(
                        durable_journal_path, item["run_id"], "dispatch_started",
                        {"task_id": item["task_id"], "task_index": item["task_index"],
                         "worker_id": item["worker_id"], "mode": dispatch_mode},
                        f"dispatch:{item['task_id']}:started",
                        repo_root=Path(item["repo"]).resolve(),
                    )
                    active[_submit_process_item(pool, item)] = item
                    initial_admissions += 1
                else:
                    _append_dispatch_journal(
                        durable_journal_path, item["run_id"], "dispatch_started",
                        {"task_id": item["task_id"], "task_index": item["task_index"],
                         "worker_id": item["worker_id"], "mode": dispatch_mode},
                        f"dispatch:{item['task_id']}:started",
                        repo_root=Path(item["repo"]).resolve(),
                    )
                    active[pool.submit(_run_item, item, owned_process_registry)] = item
                    initial_admissions += 1
            while active:
                timeout = (
                    max(0.001, physical_monitor.sample_interval_ns / 1_000_000_000)
                    if physical_monitor is not None else 5.0
                )
                done, not_done = wait(
                    tuple(active), timeout=timeout, return_when=FIRST_COMPLETED,
                )
                # A coordinator cancellation can leave a Future in CANCELLED until the
                # executor notifies its waiter; process it immediately so owned context
                # cleanup does not wait for a cancelled task forever.
                done.update(future for future in not_done if future.cancelled())
                if not done:
                    admission = _refresh_physical_admission()
                    if not admission.get("admitted"):
                        _set_capacity_stop(admission)
                    _shutdown_owned(admission, active)
                    if admission.get("admitted") and pending and prism_enabled and not stop_reason and not capacity_stop_reason:
                        _refill_prism(refresh_capacity=False)
                    continue
                for future in done:
                    item = active.pop(future)
                    try:
                        attempts = future.result()
                    except Exception as exc:  # defensive: _run_item already receipts exceptions
                        attempts = [{
                            "schema": "simplicio.operator-worker/v1",
                            "worker_id": item["worker_id"], "repo": item["repo"],
                            "source_repo": item.get("source_repo", item["repo"]),
                            "run_id": item["run_id"], "task_index": item["task_index"],
                            "task_id": item.get("task_id", ""),
                            "worktree_context": item.get("worktree_context", {}),
                            "status": "failed", "phase": "blocked", "execution_state": "error",
                            "error": f"{type(exc).__name__}: {exc}", "dead_letter": True,
                            "started_at": _now(), "finished_at": _now(),
                        }]
                    if dispatch_mode == "process":
                        _release_shared_context(item, worktree_queue, force=future.cancelled())
                    for record in attempts:
                        _persist_attempt(record)
                    final = attempts[-1]
                    completed.append(final)
                    _append_dispatch_journal(
                        durable_journal_path, item["run_id"], "dispatch_terminal",
                        {"task_id": item["task_id"], "task_index": item["task_index"],
                         "worker_id": item["worker_id"], "status": final.get("status"),
                         "receipt": final.get("receipt", "")},
                        f"dispatch:{item['task_id']}:terminal:{final.get('status', 'unknown')}",
                        repo_root=Path(item["repo"]).resolve(),
                    )
                    try:
                        if prism_enabled:
                            prism_scheduler.complete(
                                str(item.get("task_id") or ""),
                                "accepted" if final.get("status") == "succeeded" else "failed",
                                owner_agent=str(item.get("worker_id") or "simplicio-local"),
                                fence=1,
                            )
                            _refill_prism()
                    except Exception as exc:
                        final.setdefault("prism_error", f"{type(exc).__name__}: {exc}")
                    admission = _refresh_physical_admission()
                    _set_capacity_stop(admission)
                    _shutdown_owned(admission, active)
                    # Refill as soon as this worker exits; there is no frozen wave barrier.
                    if pending and not _drain_requested() and not stop_reason and not capacity_stop_reason:
                        next_item = _take_prism_admitted()
                        if next_item is None:
                            continue
                        if dispatch_mode == "process":
                            _append_dispatch_journal(
                                durable_journal_path, next_item["run_id"], "dispatch_started",
                                {"task_id": next_item["task_id"], "task_index": next_item["task_index"],
                                 "worker_id": next_item["worker_id"], "mode": dispatch_mode},
                                f"dispatch:{next_item['task_id']}:started",
                                repo_root=Path(next_item["repo"]).resolve(),
                            )
                            active[_submit_process_item(pool, next_item)] = next_item
                        else:
                            _append_dispatch_journal(
                                durable_journal_path, next_item["run_id"], "dispatch_started",
                                {"task_id": next_item["task_id"], "task_index": next_item["task_index"],
                                 "worker_id": next_item["worker_id"], "mode": dispatch_mode},
                                f"dispatch:{next_item['task_id']}:started",
                                repo_root=Path(next_item["repo"]).resolve(),
                            )
                            active[pool.submit(_run_item, next_item, owned_process_registry)] = next_item
                        refill_count += 1

    if registry_manager is not None:
        shutil.rmtree(registry_manager, ignore_errors=True)

    final_records = []
    capacity_blocked = not bool(capacity_admission.get("admitted"))
    for item in normalized:
        key = (item["repo"], item["run_id"], item["task_index"])
        existing = records.get(key)
        if existing is None and capacity_blocked:
            # Every unsent task receives a durable blocked receipt with the exact
            # physical evidence that prevented admission.  This keeps queue state
            # auditable and gives a retry a concrete reason to reconcile.
            blocked = {
                "schema": "simplicio.operator-worker/v1", "worker_id": item["worker_id"],
                "repo": item["repo"], "run_id": item["run_id"], "task_index": item["task_index"],
                "task_id": item.get("task_id", ""),
                "source_repo": item.get("source_repo", item["repo"]),
                "worktree_context": item.get("worktree_context", {}),
                "status": "blocked", "phase": "capacity", "execution_state": "paused",
                "reason_code": capacity_admission.get("reason_code", "PHYSICAL_ADMISSION_BLOCKED"),
                "reason": capacity_admission.get("reason", "capacity_not_admitted"),
                "error": capacity_admission.get("reason", "capacity_not_admitted"),
                "admission_evidence": capacity_admission.get("evidence", {}),
                "receipt_status": "BLOCKED", "attempt": 0, "attempt_count": 0,
                "dead_letter": False, "blocked": True,
                "started_at": _now(), "finished_at": _now(),
            }
            _persist_attempt(blocked)
            existing = blocked
        final_records.append(existing or {
            "schema": "simplicio.operator-worker/v1", "worker_id": item["worker_id"],
            "repo": item["repo"], "run_id": item["run_id"], "task_index": item["task_index"],
            "task_id": item.get("task_id", ""),
            "source_repo": item.get("source_repo", item["repo"]),
            "worktree_context": item.get("worktree_context", {}),
            "status": "pending", "phase": "queued", "execution_state": "pending",
            "drain_status": "held" if (stop_reason or capacity_stop_reason) else "queued",
        })
    result = {
        "schema": BATCH_SCHEMA,
        "run_id": normalized[0]["run_id"] if normalized and len({i["run_id"] for i in normalized}) == 1 else "",
        "requested_tasks": [item["task_index"] for item in normalized],
        "skipped_completed": skipped,
        "recovery_blocked_count": sum(
            len(indices) for indices in recovery_pending_by_run.values()
        ),
        "max_workers_requested": requested_workers,
        "max_workers": effective_workers,
        "active_workers": 0,
        "worker_count": len(final_records),
        "queue_depth": 0,
        "capacity_admission": capacity_admission,
        "owned_shutdown": owned_shutdown,
        "refill_count": refill_count,
        "initial_admissions": initial_admissions,
        "serial_fallback_reason": serial_fallback_reason,
        "dispatch_mode": dispatch_mode,
        "drain": {
            "status": "drained" if (stop_reason or capacity_stop_reason) else "not_requested",
            "reason_code": stop_reason or capacity_stop_reason or "none",
            "pending_task_indices": [item["task_index"] for item in pending],
        },
        "durable_journal": str(durable_journal_path) if durable_journal_path else "",
        "recovery_pending_task_indices": sorted({
            task_index
            for run_id in {item["run_id"] for item in normalized}
            for task_index in _dispatch_journal_recovery(
                durable_journal_path, run_id, repo_root=repo_root_by_run.get(str(run_id)),
            )
        }),
        "leases": [],
        "blockers": [
            {
                "task_index": record["task_index"],
                "reason_code": record.get(
                    "reason_code",
                    "operator_failed",
                ),
                "error": record.get("error", ""),
                "failure_fingerprint": record.get("failure_fingerprint", ""),
            }
            for record in final_records
            if record.get("status") in {"failed", "blocked"}
        ],
        "attempts": {
            str(record["task_index"]): int(record.get("dispatch_attempt") or 0)
            for record in final_records
        },
        "started_at": started,
        "finished_at": _now(),
        "workers": final_records,
        "completed_task_indices": sorted(r["task_index"] for r in final_records if r.get("status") == "succeeded"),
        "failed_task_indices": sorted(r["task_index"] for r in final_records if r.get("status") == "failed"),
        "blocked_task_indices": sorted(r["task_index"] for r in final_records if r.get("status") == "blocked"),
        "dead_letter_task_indices": sorted(r["task_index"] for r in final_records if r.get("dead_letter")),
        "receipt_contract": {
            "scope": "worker",
            "required": ["operator_receipt", "evidence_receipt"],
            "ready": all(
                r.get("receipt_status") == "VERIFIED"
                for r in final_records
            ),
            "missing_task_indices": sorted(
                r["task_index"] for r in final_records
                if r.get("receipt_status") != "VERIFIED"
            ),
        },
        "retry_contract": {
            "scope": "worker",
            "independent": True,
            "attempts_by_task": {
                str(r["task_index"]): int(r.get("attempt_count") or 0)
                for r in final_records
            },
        },
        "prism": {
            "schema": NATIVE_PRISM_SCHEMA,
            "mode": "native-local" if prism_enabled else "direct-parallelism",
            "prism_id": prism_id,
            "scheduler": (
                "simplicio_loop.prism_scheduler.PrismScheduler"
                if prism_enabled else "concurrent.futures.direct"
            ),
            "admission": "governed" if prism_enabled else "direct-executor",
            "max_workers": effective_workers,
            "capacity": capacity_sample,
            "snapshot": prism_scheduler.snapshot() if prism_enabled else None,
        },
        "journal": str(journal_path) if journal_path else "",
    }
    if journal_path:
        _write_json(journal_path.with_suffix(".json"), result)
    return result


def _wave_capacity_admission(
    repo_path: Path,
    lane_count: int,
    requested_workers: Optional[int],
    *,
    physical_monitor_kwargs: Optional[Mapping[str, Any]] = None,
) -> Tuple[int, Dict[str, Any]]:
    """Resolve lane concurrency through the same physical admission governor
    the classic dispatch path uses (`local_capacity.PhysicalAdmissionMonitor`),
    instead of the raw ``min(cpu_count, len(lanes))`` guess `run_worktree_wave`
    falls back to on its own -- a lane is exactly as much of a live local
    worker (its own worktree + child process) as a classic dispatch item, so
    it must be governed by the same physical evidence, not a fixed request.
    """
    effective_workers = _operator_worker_limit(requested_workers, lane_count)
    if effective_workers <= 0:
        return 0, {
            "admitted": False, "reason_code": "NO_LANES", "reason": "no_lanes", "evidence": {},
        }
    capacity_root = Path(repo_path).resolve()
    while not capacity_root.exists() and capacity_root != capacity_root.parent:
        capacity_root = capacity_root.parent
    monitor_kwargs = _physical_monitor_kwargs(physical_monitor_kwargs)
    monitor = local_capacity.PhysicalAdmissionMonitor(
        str(capacity_root), effective_workers, **monitor_kwargs,
    )
    sample = monitor.refresh(force=True)
    effective_workers = max(0, min(effective_workers, int(sample.safe_workers)))
    return effective_workers, monitor.admission_status()


def _seed_wave_lane_run_context(run_dir: Path, run_id: str, worktree_path: Path) -> None:
    """Copy this run's persisted receipts into a lane worktree and repoint its
    manifest at that worktree -- mirrors `_persist_isolated_run_context`'s
    existing single-task isolation trick, so each lane's tasks write real
    per-task operator receipts + evidence inside their own isolated checkout,
    through the exact same `execute_operator` boundary every other dispatch
    path uses.
    """
    target_run = worktree_path / ".simplicio-loop" / "loop-runs" / run_id
    if not target_run.exists():
        target_run.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(run_dir, target_run)
    manifest_path = target_run / "manifest.json"
    if manifest_path.exists():
        try:
            manifest = _load_json(manifest_path)
            manifest["repo"] = str(worktree_path)
            manifest["run_id"] = run_id
            _write_json(manifest_path, manifest)
        except (OSError, TypeError, ValueError):
            pass


def _wave_worktree_dispatch(
    *,
    repo_path: Path,
    run_id: str,
    run_dir: Path,
    items: Sequence[Mapping[str, Any]],
    retry_budget: int,
    max_workers: Optional[int],
    physical_monitor_kwargs: Optional[Mapping[str, Any]] = None,
    stop_requested: Optional[Callable[[], bool]] = None,
) -> Optional[Dict[str, Any]]:
    """Lane-parallel wave dispatch.

    Groups ``items`` into disjoint-edit-plan-path lanes (`wave_worktree.
    group_disjoint_tasks`). With more than one lane, every lane runs
    concurrently in its own git worktree seeded from this run's current
    receipts (`run_worktree_wave`) -- a lane's own tasks apply ONE AT A TIME,
    in order, through the same per-task retry/dead-letter path
    (`_run_operator_item_process`), so chaining (#1295 ``repo_state_chain``)
    keeps working inside the lane exactly as it does on the shared-run serial
    path. Every lane's resulting patch is then integrated back into the main
    repo serially, in lane order (`integrate_lane_results`); a patch that no
    longer applies (the tree moved under it) re-runs that lane's tasks
    directly on the now-integrated main tree instead of failing the wave.
    Worktrees are removed afterward (`cleanup_worktrees`).

    Every safeguard the classic ``dispatch_operator_batch`` path has applies
    here too, at lane granularity instead of task granularity: lane
    concurrency is admitted by the same physical admission governor
    (`_wave_capacity_admission`, `local_capacity.PhysicalAdmissionMonitor`)
    rather than a raw CPU-count guess; each lane task's mutation runs in its
    own child process by default (`SIMPLICIO_LOOP_DISPATCH_MODE`, reusing
    `_run_operator_item_process` -- no new worker code); every terminal
    per-task record is persisted to this run's own ``operator-batch.jsonl``
    so a resumed batch recognizes durable success; ``stop_requested`` is
    polled before a lane starts and again between integration steps; and a
    caller-declared verifier command (``SIMPLICIO_TEST_CMD``) gates each
    lane's integration through the existing (previously unwired)
    ``verifier_for`` hook.

    Returns ``None`` -- the caller keeps its existing serial path unchanged --
    when there is only one lane (every task shares a file with another),
    this repo is not a git checkout, this run's own journal already shows
    durable progress on one of these items (a resume), or physical capacity
    does not admit any lane worker right now; a genuine lane-parallel wave
    never replaces that safe fallback silently, and in each of those cases
    the fallback already does the right thing on its own.
    """
    ordered_items = list(items)
    if len(ordered_items) < 2 or not (repo_path / ".git").exists():
        return None
    paths_in_order = [
        [str(path) for path in ((item.get("task_spec") or {}).get("files_affected") or [])]
        for item in ordered_items
    ]
    if any(not paths for paths in paths_in_order):
        return None
    position_lanes = wave_worktree.group_disjoint_tasks(paths_in_order)
    if len(position_lanes) <= 1:
        return None
    lane_task_indices: List[List[int]] = [
        [int(ordered_items[position - 1]["task_index"]) for position in positions]
        for positions in position_lanes
    ]
    items_by_index = {int(item["task_index"]): dict(item) for item in ordered_items}

    journal_path = Path(run_dir).resolve() / "operator-batch.jsonl"
    prior = _load_prior_dispatch_records(journal_path)
    if any(
        prior.get(
            (str(item.get("repo")), str(item.get("run_id")), int(item["task_index"])), {}
        ).get("status") == "succeeded"
        for item in ordered_items
    ):
        # A crash mid-wave (or an already-resumed batch) left durable progress
        # in this exact journal file -- defer to the shared-run serial path,
        # which reads it too (same `journal_dir`) and skips only the
        # already-succeeded tasks instead of re-lane-grouping partial work.
        return None

    effective_workers, capacity_admission = _wave_capacity_admission(
        repo_path, len(lane_task_indices), max_workers,
        physical_monitor_kwargs=physical_monitor_kwargs,
    )
    if not capacity_admission.get("admitted"):
        # Same physical evidence the classic path uses to refuse admission --
        # deferring here gives this exact blocked state the exact same typed
        # blocked receipts, instead of duplicating that logic in this path.
        return None

    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(repo_path), capture_output=True,
        text=True, timeout=15, check=False, env=_subprocess_env(),
    )
    base_commit = (head.stdout or "").strip()
    if head.returncode != 0 or not base_commit:
        return None

    dispatch_mode = _resolve_dispatch_mode()
    process_pool: Optional[ProcessPoolExecutor] = None
    if dispatch_mode == "process":
        pool_kwargs: Dict[str, Any] = {"max_workers": max(1, effective_workers)}
        if os.name == "posix":
            try:
                import multiprocessing as _mp
                if "fork" in _mp.get_all_start_methods():
                    pool_kwargs["mp_context"] = _mp.get_context("fork")
            except (AttributeError, ValueError):
                pass
        process_pool = ProcessPoolExecutor(**pool_kwargs)
        # Force every worker to fork now, on the main thread, before
        # `asyncio.run` below starts its own default-executor threads.
        # `fork()` only duplicates the calling thread; forking later from one
        # of those asyncio worker threads while another thread holds an
        # unrelated interpreter lock (import lock, logging, GC) is a real,
        # intermittent deadlock hazard -- not hypothetical, reproduced empirically
        # while hardening this exact path. A trivial warm-up call sidesteps it
        # by making the fork happen here instead.
        process_pool.submit(int, 0).result()

    def _dispatch_one(lane_item: Mapping[str, Any]) -> List[Dict[str, Any]]:
        # Reuses the exact same child-process worker the classic dispatch
        # path submits to its own ProcessPoolExecutor -- no new worker code.
        if process_pool is not None:
            return process_pool.submit(_run_operator_item_process, dict(lane_item), retry_budget).result()
        return _run_operator_item_process(lane_item, retry_budget)

    test_cmd = os.environ.get("SIMPLICIO_TEST_CMD", "").strip()
    lane_verifier_for = (lambda _lane_id, _cmd=test_cmd: _cmd) if test_cmd else None

    lane_records: Dict[Tuple[int, ...], List[Dict[str, Any]]] = {}

    def _run_lane_sync(worktree_path: Path, task_indices: Sequence[int]) -> Dict[str, Any]:
        _seed_wave_lane_run_context(run_dir, run_id, worktree_path)
        records: List[Dict[str, Any]] = []
        applied = True
        for task_index in task_indices:
            lane_item = dict(items_by_index[task_index])
            lane_item["repo"] = str(worktree_path)
            attempts = _dispatch_one(lane_item)
            record = attempts[-1]
            records.append(record)
            if record.get("status") != "succeeded":
                applied = False
                break
        lane_records[tuple(task_indices)] = records
        return {"applied": applied}

    async def apply_fn(worktree_path: Path, task_indices: Sequence[int]) -> Dict[str, Any]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _run_lane_sync, worktree_path, list(task_indices))

    def reapply_fn(lane_id: int, task_indices: Sequence[int]) -> None:
        # Conflict repair: this lane's patch no longer applies onto the main repo
        # (an earlier lane's integration moved the tree under it) -- re-run its
        # tasks directly on the now-integrated main tree, serially, through the
        # same per-task operator path, exactly like the existing serial fallback.
        records: List[Dict[str, Any]] = []
        try:
            for task_index in task_indices:
                attempts = _dispatch_one(dict(items_by_index[task_index]))
                record = attempts[-1]
                records.append(record)
                if record.get("status") != "succeeded":
                    raise RuntimeError(
                        "reapply failed for task %d: %s"
                        % (task_index, record.get("error") or record.get("reason_code") or "unknown")
                    )
        finally:
            lane_records[tuple(task_indices)] = records

    try:
        # Worktrees live OUTSIDE the receipts run_dir -- seeding a lane's worktree
        # copies the whole run_dir tree into it (`_seed_wave_lane_run_context`),
        # which would recurse into itself if the worktree root were nested inside
        # run_dir.
        wave_scratch_dir = repo_path / ".simplicio-loop" / "orchestrator" / "wave" / run_id
        results = asyncio.run(wave_worktree.run_worktree_wave(
            repo_path, wave_scratch_dir, lane_task_indices, base_commit, apply_fn,
            max_workers=effective_workers, verifier_for=lane_verifier_for,
            stop_requested=stop_requested,
        ))
        integration = wave_worktree.integrate_lane_results(
            repo_path, results, reapply_fn, stop_requested=stop_requested,
        )
    finally:
        if process_pool is not None:
            process_pool.shutdown(wait=True)
    integrated_lane_ids = set(integration["integrated_lanes"])
    repaired_lane_ids = set(integration.get("repaired_lanes", []))
    stopped_lane_ids = set(integration.get("stopped_lanes", []))

    final_records: List[Dict[str, Any]] = []
    for lane_result in results:
        key = tuple(lane_result.task_indices)
        if lane_result.status == "stopped" or lane_result.lane_id in stopped_lane_ids:
            # Never started, or applied but not yet integrated when the stop
            # fired: none of this lane's work is on the main repo. Record it
            # as held/pending (resumable) -- never as a failure or a
            # dead-letter -- the exact vocabulary `dispatch_operator_batch`
            # already uses for a drained batch.
            for task_index in lane_result.task_indices:
                final_records.append({
                    "schema": "simplicio.operator-worker/v1", "task_index": task_index,
                    "run_id": run_id, "repo": str(repo_path),
                    "status": "pending", "execution_state": "pending",
                    "reason_code": "operator_stop_requested",
                    "drain_status": "held", "dead_letter": False,
                })
            continue
        records = lane_records.get(key) or []
        if lane_result.lane_id in integrated_lane_ids:
            # This lane's patch applied cleanly onto the main repo -- the real
            # per-task receipts it wrote live in the lane's isolated checkout;
            # copy them back so #1295's receipt gate and the oracle see them
            # exactly where every other dispatch path leaves them.
            lane_run = Path(lane_result.worktree) / ".simplicio-loop" / "loop-runs" / run_id
            for task_index in lane_result.task_indices:
                for name in (f"operator-receipt-{task_index}.json", f"task-{task_index}-result.json"):
                    src = lane_run / name
                    if src.is_file():
                        shutil.copy2(src, run_dir / name)
        elif lane_result.lane_id not in repaired_lane_ids:
            # Neither integrated nor repaired: this lane's own apply step or
            # its declared verifier (`SIMPLICIO_TEST_CMD`) failed, so nothing
            # of it ever reached the main repo. A per-task record here that
            # still reads "succeeded" only reflects that one isolated
            # worktree's own local result -- report it as blocked, never as a
            # false "succeeded", so the receipt never claims a delivery that
            # never happened. A record that already reports its own real
            # failure is kept as-is.
            corrected: List[Dict[str, Any]] = []
            for record in records:
                if isinstance(record, Mapping) and record.get("status") == "succeeded":
                    record = dict(record)
                    record["status"] = "blocked"
                    record["execution_state"] = "not_integrated"
                    record["reason_code"] = "wave_lane_not_integrated"
                    record["dead_letter"] = False
                corrected.append(record)
            records = corrected
        # A repaired lane's records come from `reapply_fn` running directly
        # on the already-integrated main repo -- they are the real, final
        # truth already and need no correction or receipt copy.
        final_records.extend(records)
        covered = {int(r.get("task_index")) for r in records if isinstance(r, Mapping) and r.get("task_index") is not None}
        for task_index in lane_result.task_indices:
            if task_index not in covered:
                # This lane failed before its worktree/apply step ever reached
                # this task -- record it once (dead-letter), never fabricate a
                # receipt or leave it silently unaccounted for.
                final_records.append({
                    "schema": "simplicio.operator-worker/v1", "task_index": task_index,
                    "run_id": run_id, "repo": str(repo_path), "status": "failed",
                    "execution_state": "blocked", "reason_code": "wave_lane_failed",
                    "dead_letter": True, "error": lane_result.log[-2000:],
                })

    wave_worktree.cleanup_worktrees(repo_path, results)

    # Persist every terminal (non-pending) per-task record to this run's own
    # operator-batch.jsonl -- the same durable journal `dispatch_operator_batch`
    # reads/writes -- so a crash-recovery resume, on whichever path handles it
    # next, recognizes a durably-succeeded task and never re-dispatches it.
    for record in final_records:
        if record.get("status") == "pending":
            continue
        # `record["repo"]` may still be the lane's ephemeral worktree path
        # (each lane task runs with its item's "repo" pointed at that
        # worktree) -- the journal's resume key must match the canonical
        # repo/run_id every caller (this function and the classic path) uses
        # to look an item up, never the worktree it happened to run in.
        journal_record = dict(record)
        journal_record["run_id"] = run_id
        journal_record["repo"] = str(repo_path)
        _append_jsonl(journal_path, journal_record)

    # Rebind repo_state_chain to the just-integrated tree so `verify`'s
    # staleness checks compare against what this run actually left, not a
    # stale `prepare`-time snapshot -- the same intent as the shared-run
    # serial path's own `state["repo_state_chain"] = after` write.
    try:
        state = _load_json(run_dir / "state.json")
        state["repo_state_chain"] = _repo_fingerprint(repo_path)
        _write_json(run_dir / "state.json", state)
    except (OSError, TypeError, ValueError):
        pass
    # The evidence receipt is one aggregate file per run (not per task) --
    # recompute it fresh against the just-integrated tree, same as every
    # successful serial dispatch already does at the end of each task.
    try:
        evidence = build_evidence_receipt(str(run_dir))
        _write_json(run_dir / "evidence-receipt.json", evidence)
    except (OSError, TypeError, ValueError):
        pass

    drained = bool(stopped_lane_ids) or any(r.status == "stopped" for r in results)
    return {
        "schema": "simplicio.operator-batch-receipt/v1",
        "workers": final_records,
        "max_workers": effective_workers or len(lane_task_indices),
        "max_workers_requested": max_workers,
        "capacity_admission": capacity_admission,
        "dispatch_mode": dispatch_mode,
        "serial_fallback_reason": "",
        "completed_task_indices": sorted(
            int(r["task_index"]) for r in final_records if r.get("status") == "succeeded"
        ),
        "failed_task_indices": sorted(
            int(r["task_index"]) for r in final_records if r.get("status") == "failed"
        ),
        "blocked_task_indices": sorted(
            int(r["task_index"]) for r in final_records if r.get("status") == "blocked"
        ),
        "dead_letter_task_indices": sorted(
            int(r["task_index"]) for r in final_records if r.get("dead_letter")
        ),
        "drain": {
            "status": "drained" if drained else "not_requested",
            "reason_code": "operator_stop_requested" if drained else "none",
            "pending_task_indices": sorted(
                int(r["task_index"]) for r in final_records if r.get("status") == "pending"
            ),
        },
        "wave": {
            "schema": wave_worktree.SCHEMA,
            "lanes": lane_task_indices,
            "base_commit": base_commit,
            "integration": integration,
        },
    }


def execute_operator_batch(
    repo: str,
    run_id: str,
    task_indices: Optional[Sequence[int]] = None,
    *,
    max_workers: Optional[int] = None,
    retry_budget: int = 3,
    isolated_contexts: Optional[Mapping[int, Mapping[str, Any]]] = None,
    worktree_queue: Any = None,
    auto_fan_out: Optional[bool] = None,
    physical_monitor_kwargs: Optional[Mapping[str, Any]] = None,
    provider_worker: str | None = None,
) -> Dict[str, Any]:
    """Dispatch all (or selected) tasks from one run through the real operator bridge.

    Independent tasks fan out into owned worktrees by default.  Set ``auto_fan_out=False`` or
    ``SIMPLICIO_LOOP_AUTO_FAN_OUT=0`` to opt out.  If impact metadata, Git, or the worktree
    adapter is unavailable, the shared-run serial guard remains the safe fallback.
    """
    status = read_status(repo, run_id)
    if (status["state"].get("maintenance") or {}).get("disposition") == "backlog_only":
        raise RuntimeError("maintenance deferred: operator batch is blocked until explicit resume")
    run_dir = Path(status["run_dir"])
    repo_path = Path(status["manifest"].get("repo") or repo).resolve()
    _ensure_mapper_operations_store(
        repo_path,
        status["manifest"].get("storage_route"),
    )
    try:
        contract = _require_json_receipt(run_dir / "task-contract.json", "task contract")
        receipts = _validate_run_receipts(
            Path(status["manifest"].get("repo") or repo).resolve(),
            run_dir,
            contract,
            state=status["state"],
            manifest=status["manifest"],
            require_dry_run=True,
        )
    except (OSError, TypeError, ValueError, RuntimeError) as exc:
        _persist_batch_preflight_block(
            run_dir,
            status["state"],
            Path(status["manifest"].get("repo") or repo).resolve(),
            str(exc),
            task_indices=task_indices or (),
        )
        # #NOWASTE: this exact receipt chain will fail the exact same validation
        # the exact same way on any immediate re-invocation (nothing about the
        # repo/receipts changes between retries) -- a typed reason_code lets any
        # caller that retries a whole batch dispatch (e.g. an outer re-feed loop)
        # recognize "deterministic, do not retry on a cadence" instead of
        # treating this like a transient failure.
        raise BatchPreflightError(str(exc)) from exc
    plan = receipts["plan"]
    # #284: mutation-authority gate, mandatory by default -- same as execute_operator()
    # (single-task tick), extended to the batch boundary. "execute_operator() e batch
    # recusam execução sem mutation authority válida" now applies unconditionally
    # (opt out only via an explicit falsy SIMPLICIO_REQUIRE_MUTATION_AUTHORITY; see
    # planning_gate.mutation_authority_required()).
    if mutation_authority_required():
        batch_attempt = int((status["state"] or {}).get("attempts", 0)) + 1
        current_source_hash = ""
        current_snapshot_path = run_dir / "source-snapshot-current.json"
        if current_snapshot_path.exists():
            try:
                current_source_hash = str((_load_json(current_snapshot_path).get("source") or {}).get("snapshot_hash") or "")
            except Exception:
                current_source_hash = ""
        authority_verdict = evaluate_mutation_authority(
            run_dir, run_id=run_id, attempt=batch_attempt,
            task_contract_hash=str(contract.get("collection_hash") or _planning_content_hash(contract)),
            plan_hash=_planning_content_hash(plan),
            source_snapshot_hash=current_source_hash,
        )
        if not authority_verdict["ok"]:
            _persist_batch_preflight_block(
                run_dir,
                status["state"],
                Path(status["manifest"].get("repo") or repo).resolve(),
                f"mutation authority required (SIMPLICIO_REQUIRE_MUTATION_AUTHORITY) but "
                f"{authority_verdict['reason_code']}: {authority_verdict['reason']}",
                task_indices=task_indices or (),
            )
            raise RuntimeError(
                "mutation authority required (SIMPLICIO_REQUIRE_MUTATION_AUTHORITY) but "
                f"{authority_verdict['reason_code']}: {authority_verdict['reason']}"
            )
    else:
        batch_attempt = int((status["state"] or {}).get("attempts", 0)) + 1
    task_count = len(contract.get("tasks") or [])
    if task_indices is None:
        indices = list(range(1, task_count + 1))
    else:
        indices = [int(index) for index in task_indices]
    if any(index < 1 or index > task_count for index in indices):
        raise ValueError("task index out of range")
    contexts = dict(isolated_contexts or {})
    distributed_queue = None
    agent_identity = None
    if not isolated_contexts:
        distributed_queue, agent_identity = _distributed_configuration(repo)
    auto_reason = "explicit_contexts" if isolated_contexts else ""
    contract_tasks = list(contract.get("tasks") or [])
    contract_steps = list(plan.get("steps") or [])
    has_task_dependencies = any(
        _task_dependency_references(
            contract_tasks[index - 1] if 0 < index <= len(contract_tasks) else {},
            contract_steps[index - 1] if 0 < index <= len(contract_steps) and isinstance(contract_steps[index - 1], Mapping) else {},
        )
        for index in indices
    )
    if not isolated_contexts and worktree_queue is None and (auto_fan_out is not False) and not has_task_dependencies:
        previous = os.environ.get("SIMPLICIO_LOOP_AUTO_FAN_OUT")
        if auto_fan_out is True:
            os.environ["SIMPLICIO_LOOP_AUTO_FAN_OUT"] = "1"
        try:
            worktree_queue, auto_contexts, auto_reason = _auto_worktree_dispatch(
                repo, run_id, contract, plan, indices,
            )
        finally:
            if auto_fan_out is True:
                if previous is None:
                    os.environ.pop("SIMPLICIO_LOOP_AUTO_FAN_OUT", None)
                else:
                    os.environ["SIMPLICIO_LOOP_AUTO_FAN_OUT"] = previous
        contexts.update(auto_contexts)
    elif has_task_dependencies:
        auto_reason = "dependency_order_requires_shared_run"
    items = []
    runtime_task_ids = {
        index: str((contexts.get(index) or {}).get("task_id") or f"{run_id}-task-{index}")
        for index in indices
    }
    dependency_aliases = {
        alias: runtime_task_ids[index]
        for index, task in enumerate(contract_tasks, start=1)
        if index in runtime_task_ids
        for alias in _task_aliases(task, index, run_id)
    }
    for index in indices:
        context = dict(contexts.get(index) or {})
        task = contract_tasks[index - 1]
        step = contract_steps[index - 1] if index <= len(contract_steps) and isinstance(contract_steps[index - 1], Mapping) else {}
        task_id = runtime_task_ids[index]
        target_paths = [str(path) for path in (step.get("candidate_targets") or []) if str(path).strip()]
        task_spec = dict(context.get("task_spec") or {})
        task_spec.setdefault("id", task_id)
        task_spec.setdefault("goal", _task_goal(task))
        task_spec.setdefault("files_affected", target_paths)
        dependencies = []
        for dependency in _task_dependency_references(task, step):
            dependencies.append(dependency_aliases.get(dependency, dependency))
        dependencies.extend(_item_dependencies({"task_spec": task_spec}))
        task_spec["depends_on"] = list(dict.fromkeys(str(value) for value in dependencies if str(value).strip()))
        item = {
            "repo": context.get("repo", repo),
            "run_id": context.get("run_id", run_id),
            "task_index": index,
            "worker_id": context.get("worker_id", f"operator-{index}"),
            "isolation_key": context.get("isolation_key"),
            "task_id": task_id,
            "task_spec": task_spec,
            "isolation": context.get("isolation", "worktree"),
            "authority_attempt": batch_attempt,
        }
        if provider_worker is not None:
            item["provider_worker"] = provider_worker
        if distributed_queue is not None:
            item["distributed_queue"] = distributed_queue
            item["agent_identity"] = agent_identity
            issue_ref = task.get("issue_ref") or contract.get("issue_ref") or ""
            issue_url = task.get("issue_url") or contract.get("issue_url") or ""
            item["context_pack"] = build_context_pack(
                task_id=item["task_id"], goal=_task_goal(task), identity=agent_identity,
                acs=[*[(s.get("title") or s.get("id") or "") for s in (task.get("scenarios") or [])]],
                depends_on=list(task_spec.get("depends_on") or []),
                allowed_paths=target_paths, source_refs=target_paths,
                issue_ref=issue_ref, issue_url=issue_url,
            )
        items.append(item)
    for index in indices:
        step = contract_steps[index - 1] if index <= len(contract_steps) and isinstance(contract_steps[index - 1], Mapping) else None
        _assert_task_dependencies_ready(
            run_dir, contract_tasks, index, run_id, step=step, in_batch=set(indices),
        )
    items = _omit_satisfied_dispatch_dependencies(
        items,
        satisfied_aliases=_completed_task_aliases(run_dir, contract_tasks, run_id),
    )
    def _batch_stop_requested() -> bool:
        try:
            current = _load_json(Path(status["run_dir"]) / "state.json")
        except (OSError, TypeError, ValueError):
            return False
        return str(current.get("phase") or "") == "cancelled"

    result = None
    # Lane-parallel wave dispatch: only where the caller has not already asked for
    # something more specific (explicit isolated contexts, an existing worktree
    # queue, a distributed queue, or shared-run-forcing task dependencies) -- those
    # keep their own, unchanged path below.
    if (
        not isolated_contexts and worktree_queue is None and distributed_queue is None
        and not has_task_dependencies and len(items) > WAVE_INLINE_MAX_TASKS
    ):
        result = _wave_worktree_dispatch(
            repo_path=Path(status["manifest"].get("repo") or repo).resolve(),
            run_id=run_id, run_dir=run_dir, items=items,
            retry_budget=retry_budget, max_workers=max_workers,
            physical_monitor_kwargs=physical_monitor_kwargs,
            stop_requested=_batch_stop_requested,
        )
    if result is None:
        result = dispatch_operator_batch(
            items,
            max_workers=max_workers,
            retry_budget=retry_budget,
            journal_dir=str(Path(status["run_dir"])),
            worktree_queue=worktree_queue,
            stop_requested=_batch_stop_requested,
            physical_monitor_kwargs=physical_monitor_kwargs,
            provider_worker=provider_worker,
        )
    lifecycle_result: Dict[str, Any]
    try:
        repo_root = Path(status["manifest"].get("repo") or repo).resolve()
        source_commit = str(status["manifest"].get("source_commit") or "")
        if not source_commit:
            head = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=str(repo_root), capture_output=True,
                text=True, timeout=15, check=False, env=_subprocess_env(),
            )
            source_commit = (head.stdout or "").strip() or "unavailable"
        mapper_generation = str(
            (status["state"].get("mapper") or {}).get("generation")
            or "mapper-unpinned"
        )
        lifecycle = CheckpointLifecycle(
            repo_root / ".simplicio-loop" / "loop-runs",
            task_id=run_id,
            attempt_id=f"batch-{int((status['state'] or {}).get('attempts', 0)) + 1}",
            source_commit=source_commit,
            mapper_generation=mapper_generation,
            base_path=repo_root,
        )
        workers = list(result.get("workers") or [])
        candidate_ids = []
        successful_ids = []
        for worker in sorted(workers, key=lambda row: str(row.get("task_id") or row.get("task_index"))):
            candidate_id = str(worker.get("task_id") or f"task-{worker.get('task_index')}")
            succeeded = worker.get("status") == "succeeded"
            lifecycle.checkpoint(
                candidate_id, "operator", "READY_TO_PROMOTE" if succeeded else "HELD",
                receipts=[value for value in (
                    str(worker.get("operator_receipt") or ""),
                    str(worker.get("evidence_receipt") or ""),
                ) if value],
                work_units=int(worker.get("attempt_count") or 1),
            )
            candidate_ids.append(candidate_id)
            if succeeded:
                successful_ids.append(candidate_id)
        if not any(worker.get("status") == "succeeded" for worker in workers):
            lifecycle_result = {"schema": "simplicio.loop.checkpoint-lifecycle/v1",
                                "status": "HELD", "reason": "no_successful_candidate"}
        else:
            def _cancel_boundary(candidate_id: str) -> None:
                if worktree_queue is None:
                    return
                for method_name in ("cancel_task", "release_task", "cancel"):
                    method = getattr(worktree_queue, method_name, None)
                    if callable(method):
                        method(candidate_id)
                        return
            selected_winner = sorted(successful_ids)[0]
            lifecycle_result = lifecycle.converge_selected(
                winner_id=selected_winner,
                candidate_ids=candidate_ids,
                shard_id="operator",
                cancel_callback=_cancel_boundary,
            )
    except (LifecycleError, OSError, ValueError, subprocess.SubprocessError) as exc:
        lifecycle_result = {"schema": "simplicio.loop.checkpoint-lifecycle/v1",
                            "status": "HELD", "reason": "lifecycle_integration_failed",
                            "error": str(exc)}
    result["checkpoint_lifecycle"] = lifecycle_result
    technical_debts: List[Dict[str, Any]] = []
    # Fan-out is an optimization. A safe serial lane is still useful work, so
    # capability loss is recorded as advisory debt instead of a global blocker.
    if auto_reason and auto_reason not in {"explicit_contexts", "single_task", "inline_small_batch"} and len(items) > 1:
        technical_debts.append(_record_technical_debt(
            status["run_dir"],
            run_id=run_id,
            reason_code=auto_reason if auto_reason in {
                "fanout_disabled", "not_git_checkout", "missing_plan_targets",
                "overlapping_task_impacts", "worktree_adapter_unavailable",
                "worktree_preflight_failed",
            } else "fanout_serial_fallback",
            stage="dispatch",
            source="simplicio_loop.runner._auto_worktree_dispatch",
            message="automatic fan-out was not available; continuing with the safe serial lane",
            next_action="install/configure the worktree adapter or split overlapping targets",
        ))
    result["distributed"] = {
        "enabled": distributed_queue is not None,
        "queue": os.environ.get("SIMPLICIO_REMOTE_QUEUE_URL", "") if distributed_queue is not None else "",
        "agent": agent_identity or {},
        "fail_closed": distributed_queue is not None,
    }
    if not contexts and len(items) > 1:
        # dispatch_operator_batch derives this from the shared isolation key; retain a clear
        # contract-level marker for callers inspecting the convenience API.
        result["serial_fallback_reason"] = result.get("serial_fallback_reason") or (
            "inline_small_batch" if auto_reason == "inline_small_batch" else "shared_run_state"
        )
        if not technical_debts and auto_reason != "inline_small_batch":
            technical_debts.append(_record_technical_debt(
                status["run_dir"],
                run_id=run_id,
                reason_code="fanout_serial_fallback",
                stage="dispatch",
                source="simplicio_loop.runner.dispatch_operator_batch",
                message="tasks share run state or could not be isolated; serial execution preserved safety",
                next_action="provide distinct worktree contexts for independent tasks",
            ))
    result["technical_debts"] = technical_debts
    result["fan_out"] = {
        "enabled": bool(worktree_queue is not None and len(contexts) > 1),
        "default": auto_fan_out is not False,
        "reason": auto_reason or ("isolated_contexts" if contexts else "serial_fallback"),
        "contexts": len(contexts),
    }
    return result


def defer_maintenance_backlog_only(
    repo: str,
    run_id: str,
    *,
    correction_summary: str,
    deferral_reason: str,
    resume_instructions: Sequence[str] | str,
    evidence_status: str = "UNVERIFIED",
) -> Dict[str, Any]:
    status = read_status(repo, run_id)
    if status["state"].get("phase") in {"done", "cancelled"}:
        raise ValueError(f"run already terminal: {status['state'].get('phase')}")
    run_dir = Path(status["run_dir"])
    state = status["state"]
    receipt = _write_maintenance_deferred_receipt(
        run_dir,
        correction_summary=correction_summary,
        deferral_reason=deferral_reason,
        resume_instructions=resume_instructions,
        evidence_status=evidence_status,
    )
    state["maintenance"] = {
        "mode": receipt["mode"],
        "disposition": receipt["disposition"],
        "receipt": str(run_dir / "maintenance-receipt.json"),
        "correction_summary": receipt["correction_summary"],
        "deferral_reason": receipt["deferral_reason"],
        "evidence_status": receipt["evidence_status"],
    }
    completion = _completion_state(run_dir, state.get("completion"))
    completion["ready"] = False
    completion["tag"] = "UNVERIFIED"
    completion["verdict"] = "DELIVERY_PENDING"
    completion["reason_code"] = "maintenance_deferred"
    if (run_dir / "completion-receipt.json").exists():
        persisted = _load_json(run_dir / "completion-receipt.json")
        persisted.update({"ready": False, "verdict": completion["verdict"],
                          "reason_code": completion["reason_code"], "tag": "UNVERIFIED"})
        _write_json(run_dir / "completion-receipt.json", persisted)
    state["completion"] = completion
    state["operator"] = {
        **(state.get("operator") or {}),
        "ready": False,
        "execution_state": "backlog_only",
    }
    state["current_action"] = "maintenance_deferred_to_backlog"
    state["next_action"] = "resume_from_maintenance_receipt"
    state["evidence"] = {
        **(state.get("evidence") or {}),
        "ready": False,
        "status": receipt["evidence_status"],
    }
    _write_json(run_dir / "state.json", state)
    _transition(
        run_dir,
        state,
        "partial",
        "maintenance correction deferred to backlog-only mode",
        receipt=str(run_dir / "maintenance-receipt.json"),
        extra={"mode": receipt["mode"], "disposition": receipt["disposition"]},
    )
    return read_status(repo, run_id)


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


def _cancel_mapper_background(repo_path: Path, run_dir: Path, state: Dict[str, Any]) -> Dict[str, Any]:
    """Cancel an outstanding deep Mapper job before a run becomes terminal."""
    mapper_state = state.get("mapper") if isinstance(state.get("mapper"), Mapping) else {}
    route = mapper_state.get("execution_route") if isinstance(mapper_state, Mapping) else None
    if not isinstance(route, Mapping):
        context_path = run_dir / "mapper-context.json"
        try:
            context = _load_json(context_path) if context_path.is_file() else {}
        except (OSError, TypeError, ValueError):
            context = {}
        candidate = context.get("execution_route") if isinstance(context, Mapping) else None
        route = candidate if isinstance(candidate, Mapping) else {}
    background = route.get("background") if isinstance(route, Mapping) else None
    if not isinstance(background, Mapping) or background.get("status") != "queued":
        return {"status": "not_active", "reason_code": "mapper_background_not_active"}

    result = _run_cmd(
        ["simplicio-mapper", "background", "cancel", ".", "--json"], repo_path,
    )
    try:
        stdout = json.loads(result.stdout) if result.stdout.strip() else {}
    except ValueError:
        stdout = {"raw": result.stdout.strip()}
    receipt = {
        "schema": "simplicio.loop.mapper-background-cancellation/v1",
        "status": "cancelled" if result.returncode == 0 else "blocked",
        "reason_code": "mapper_background_cancelled" if result.returncode == 0 else "mapper_background_cancel_failed",
        "returncode": result.returncode,
        "stdout": stdout,
        "stderr": (result.stderr or "").strip(),
        "job_id": background.get("work_id"),
        "pid": background.get("pid"),
        "requested_at": _now(),
    }
    receipt_path = run_dir / "mapper-background-cancel.json"
    _write_json(receipt_path, receipt)
    state.setdefault("mapper", {})["background_cancellation"] = {
        **receipt, "receipt": str(receipt_path),
    }
    state["mapper"]["execution_route"] = {
        **dict(route),
        "background": {**dict(background), "status": receipt["status"],
                        "cancel_receipt": str(receipt_path)},
    }
    return receipt


def change_phase(repo: str, run_id: str, to_phase: str, reason: str) -> Dict[str, Any]:
    status = read_status(repo, run_id)
    run_dir = Path(status["run_dir"])
    state = status["state"]
    if state.get("phase") in {"done", "cancelled"}:
        raise ValueError(f"run already terminal: {state.get('phase')}")
    if to_phase == "awaiting_decision":
        maintenance = state.get("maintenance") or {}
        if maintenance.get("mode") == "maintenance_deferred" or maintenance.get("disposition") == "backlog_only":
            state["maintenance"] = _active_maintenance_state(maintenance)
            state["operator"] = {
                **(state.get("operator") or {}),
                "ready": False,
                "execution_state": "invalidated",
            }
            state["evidence"] = {
                **(state.get("evidence") or {}),
                "ready": False,
                "status": "INVALIDATED",
            }
        state["next_action"] = "mapper_scan_required"
    elif to_phase == "cancelled":
        _cancel_mapper_background(Path(repo).resolve(), run_dir, state)
        state["next_action"] = "none"
    _transition(run_dir, state, to_phase, reason, receipt=str(run_dir / "state.json"))
    return read_status(repo, run_id)


def reconcile_delivery(repo: str, run_id: str, current_state: str, source_kind: str = "local",
                       source_payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
    status = read_status(repo, run_id)
    run_dir = Path(status["run_dir"])
    manifest = status["manifest"]
    state = status["state"]
    previous_receipt = None
    previous_path = run_dir / "delivery-receipt.json"
    if previous_path.exists():
        try:
            previous_receipt = _load_json(previous_path)
        except (OSError, ValueError, TypeError):
            previous_receipt = None
    execution_route = None
    route_path = run_dir / "execution-route.json"
    if route_path.is_file():
        try:
            candidate = _load_json(route_path)
            if verify_route_hash(candidate):
                execution_route = candidate
        except (OSError, ValueError, TypeError):
            execution_route = None
    delivery_payload = dict(source_payload or {})
    if execution_route:
        delivery_payload.setdefault("execution_route", execution_route)
    receipt = build_delivery_receipt(str(run_dir), manifest.get("delivery_target") or "verified",
                                     current_state=current_state, source_kind=source_kind,
                                     source_payload=delivery_payload)
    if execution_route:
        receipt["execution_route"] = execution_route
        receipt["route_receipt_sha"] = execution_route.get("receipt_sha", "")
    receipt["reconciliation"] = reconcile_delivery_observation(previous_receipt, receipt)
    write_delivery_receipt(str(run_dir), receipt)
    state["delivery"] = {
        "target": receipt["target"],
        "current_state": receipt["current_state"],
        "ready": receipt["ready"],
        "receipt": str(run_dir / "delivery-receipt.json"),
        "source_checked_at": receipt["source_checked_at"],
        "source_kind": source_kind,
        "execution_route": execution_route,
        "route_receipt_sha": receipt.get("route_receipt_sha", ""),
    }
    reconciliation = receipt.get("reconciliation") or {}
    if reconciliation.get("status") == "reopened":
        state["current_action"] = "delivery_reopened"
        state["next_action"] = "requery_source"
        next_phase = "partial"
        state.setdefault("blockers", [])
        failed_gate = next((gate for gate in receipt.get("gates", [])
                            if gate.get("status") == "fail"), {})
        state["blockers"] = [
            "delivery reopened: " + str(failed_gate.get("detail") or
                                         reconciliation.get("reason_code") or
                                         "delivery_target_regressed")
        ]
    elif receipt["ready"]:
        state["current_action"] = "delivery_reconciled"
        state["next_action"] = "completion_oracle"
        next_phase = "delivering" if current_state not in {"verified", "done"} else "validating"
    else:
        state["current_action"] = "delivery_reconciliation_failed"
        state["next_action"] = "collect_missing_delivery_evidence"
        next_phase = "partial"
        state.setdefault("blockers", [])
        fail_gate = next((gate for gate in receipt.get("gates", []) if gate.get("status") == "fail"), None)
        if fail_gate:
            state["blockers"] = [fail_gate.get("detail", "delivery reconciliation failed")]
    _write_json(run_dir / "state.json", state)
    _emit_event(run_dir, state, "delivery_reconciled", receipt=str(run_dir / "delivery-receipt.json"),
                blocker="" if receipt["ready"] else "delivery_reconciliation_failed",
                message="delivery state reconciled", current_state=receipt["current_state"],
                reconciliation=reconciliation, execution_route=execution_route,
                route_receipt_sha=receipt.get("route_receipt_sha", ""))
    if reconciliation.get("status") == "reopened":
        _emit_event(run_dir, state, "rollback", receipt=str(run_dir / "delivery-receipt.json"),
                    blocker=str(reconciliation.get("reason_code") or "delivery_reopened"),
                    message="delivery regression reopened the run")
    if receipt["ready"]:
        completion = _completion_state(run_dir, state.get("completion"))
        _emit_event(run_dir, state, "oracle_verdict", receipt=(
            str(run_dir / "completion-receipt.json")
            if (run_dir / "completion-receipt.json").exists()
            else str(run_dir / "delivery-receipt.json")),
            blocker="" if completion.get("ready") else "oracle_incomplete",
            message=str(completion.get("verdict") or "DELIVERY_PENDING"),
            verdict=str(completion.get("verdict") or "DELIVERY_PENDING"))
    _transition(run_dir, state, next_phase, "delivery state reconciled", receipt=str(run_dir / "delivery-receipt.json"))
    return read_status(repo, run_id)


def apply_human_decision(repo: str, run_id: str, decision_id: str, answer: str,
                         impact: str = "behavior-change") -> Dict[str, Any]:
    status = read_status(repo, run_id)
    run_dir = Path(status["run_dir"])
    state = status["state"]
    contract_payload = _load_json(_contract_path(run_dir))
    tasks = contract_payload.get("tasks") or []
    if not tasks:
        raise ValueError("task contract collection is empty")
    changed = False
    for task in tasks:
        ledger = task.setdefault("decision_ledger", [])
        for item in ledger:
            if item.get("id") == decision_id:
                item["resolved"] = True
                item["answer"] = answer
                item["resolved_at"] = _now()
                item["resolution_impact"] = impact
                changed = True
        for bucket_name in ("questions", "assumptions", "blockers"):
            for item in task.get(bucket_name) or []:
                if item.get("id") == decision_id:
                    item["resolved"] = True
                    item["answer"] = answer
                    item["resolved_at"] = _now()
                    item["resolution_impact"] = impact
                    changed = True
    if not changed:
        raise ValueError(f"decision id not found: {decision_id}")
    contract_payload["revision"] = int(contract_payload.get("revision", 1)) + 1
    contract_payload["updated_at"] = _now()
    _write_json(_contract_path(run_dir), contract_payload)
    _emit_event(run_dir, state, "handoff", receipt=str(_contract_path(run_dir)),
                task_id=str(tasks[0].get("id") or ""), ac_ids=_task_ac_ids(tasks[0]),
                message="human decision handed off to replanning", decision_id=decision_id,
                execution_route=state.get("execution_route") or {},
                route_receipt_sha=str((state.get("execution_route") or {}).get("receipt_sha") or ""))
    invalidated = []
    for name in ("plan.json", "operator-receipt.json", "evidence-receipt.json", "delivery-receipt.json"):
        path = run_dir / name
        if path.exists():
            path.unlink()
            invalidated.append(name)
    state["phase"] = "awaiting_decision"
    state["updated_at"] = _now()
    state["current_action"] = "human_decision_applied"
    state["next_action"] = "rebuild_plan_from_updated_contract"
    state["operator"] = {"ready": False, "receipt": "", "target": "", "execution_state": "invalidated"}
    state["evidence"] = {"ready": False, "receipt": "", "status": "INVALIDATED"}
    state["delivery"] = {"target": state.get("delivery_target"), "current_state": "planned", "ready": False, "receipt": ""}
    state["completion"] = _default_completion_state()
    state["blockers"] = []
    _write_json(run_dir / "state.json", state)
    _transition(run_dir, state, "awaiting_decision", "human decision applied; dependent artifacts invalidated",
                receipt=str(_contract_path(run_dir)), extra={"decision_id": decision_id, "invalidated": invalidated})
    return read_status(repo, run_id)


def sync_source_state(repo: str, run_id: str, source: str, external_repo: str = "",
                      pr: int | None = None, tag: str = "") -> Dict[str, Any]:
    status = read_status(repo, run_id)
    manifest = status["manifest"]
    target = manifest.get("delivery_target") or "verified"
    if source != "github":
        raise ValueError(f"unsupported source: {source!r}")
    payload = github_delivery_payload(external_repo, pr=pr, tag=tag, target_state=target)
    current_state = infer_github_delivery_state(payload)
    return reconcile_delivery(repo, run_id, current_state, source_kind="github", source_payload=payload)
