"""CLI implementation: install skills/hooks and expose task-contract utilities."""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import webbrowser
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence
try:
    from scripts import release_manifest as _release_manifest
except Exception:  # pragma: no cover - import shim for bundled scripts
    _release_manifest = None
try:
    from scripts import release_train as _release_train
except Exception:  # pragma: no cover - import shim for bundled scripts
    _release_train = None


def _load_release_manifest(repo: str):
    """Load the release manifest helper from an explicit checkout when installed."""
    if _release_manifest is not None:
        return _release_manifest
    script = Path(repo).resolve() / "scripts" / "release_manifest.py"
    if not script.is_file():
        return None
    root = str(script.parent.parent)
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        spec = importlib.util.spec_from_file_location(
            "simplicio_loop_external_release_manifest", script
        )
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception:  # pragma: no cover - target checkout may be incomplete
        return None
try:
    from . import prototype_cli as _prototype_cli
except Exception:  # pragma: no cover - keeps `simplicio-loop` importable if this is missing
    _prototype_cli = None

from . import __version__
from .fast_integration import FastConfig, FastIntegrationError, FastLoopIntegration
from .checkpoint_lifecycle import CheckpointLifecycle, LifecycleError
from . import delivery
from .drain import (
    SCHEMA as DRAIN_SCHEMA,
    DrainReceiptError,
    evaluate_drain,
    load_drain_receipt,
    persist_drain_receipt,
)
from .runner import (
    arm_run,
    conduct_run,
    apply_human_decision,
    change_phase,
    defer_maintenance_backlog_only,
    execute_operator,
    execute_operator_batch,
    read_status,
    reconcile_delivery,
    sync_source_state,
    verify_run,
)
from .loop_execution_receipt import (
    SCHEMA as LOOP_EXECUTION_SCHEMA,
    publish_loop_execution_for_flow,
)
from .execution_adapters import expected_governor_blocked, persist_execution_envelope
from .intake_planner import dispatch_single_task_fast
from .task_contract import compile_many, main as task_contract_main, preview_contract
from .ops_ledger import (
    CONTEXT_SCHEMA,
    HANDSHAKE_SCHEMA,
    REQUIRED_CONTEXT_FIELDS,
    EventLedger,
    LedgerError,
    validate_handshake,
)
from . import inspection_cli as _inspection_cli
from .progress import stream as stream_progress
from .oracle import evaluate_matrix, persist_completion_receipt
from .delivery import DELIVERY_ORDER
from .evidence import redact_sensitive_text
from .economy_profile import (
    llm_max_speed_orientation_contract,
    prism_batches,
    prism_is_eligible,
    resolve_prism_batch_size,
)
from .map_service_cli import configure_commands as configure_map_commands, dispatch as dispatch_map
from .serverless_deploy import build_plan as build_serverless_plan, execute_plan as execute_serverless_plan

BUNDLE = Path(__file__).resolve().parent / "_bundle"
DASHBOARD = BUNDLE / "hooks" / "simplicio_dashboard.py"
# Cross-platform temp dir (Windows has no /tmp) — must match hooks/simplicio_dashboard.py.
PID_FILE = Path(tempfile.gettempdir()) / "simplicio-token-monitor.pid"
DEFAULT_DASH_PORT = int(os.environ.get("SIMPLICIO_MONITOR_PORT", "9090"))


def _gui_available() -> bool:
    """True only when opening a browser is safe + non-blocking. On headless Linux (no DISPLAY),
    webbrowser.open() may launch a text browser that inherits stdin and blocks forever — and a
    blocking wait() is NOT caught by try/except — so we must skip it there."""
    if sys.platform == "darwin" or os.name == "nt":
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def _copy_tree(src: Path, dst: Path) -> int:
    """Copy every file under src into dst, preserving structure. Returns file count."""
    count = 0
    for item in src.rglob("*"):
        if item.is_file():
            out = dst / item.relative_to(src)
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, out)
            count += 1
    return count


def install(target: Path, globally: bool, host: str = "claude",
            dry_run: bool = False, uninstall: bool = False, verify: bool = False) -> int:
    from .install.planner import InstallError, apply_plan, plan_install
    from .install.planner import uninstall as remove_owned
    from .install.planner import verify_plan

    root = Path.home() if globally else target
    if uninstall:
        try:
            payload = remove_owned(root)
        except InstallError as exc:
            print(f"error: {exc}", flush=True)
            return 1
        print(f"simplicio-loop uninstalled {len(payload.get('removed') or [])} owned paths")
        return 0
    try:
        plan = plan_install(root, host=host, globally=globally)
        if verify:
            verify_plan(plan)
            print(f"simplicio-loop install plan ok host={host} digest={plan['digest']}")
            return 0
        result = apply_plan(plan, dry_run=dry_run, bundle=BUNDLE)
    except InstallError as exc:
        print(f"error: {exc}", flush=True)
        return 1
    status = "installed" if result["status"] == "applied" else result["status"]
    print(f"simplicio-loop {__version__} {status}:")
    print(f"  host   -> {host}")
    print(f"  owned  -> {', '.join(result['owned'])}")
    print(f"  files  -> {result['written']}")
    print("")
    print("Use it in your agent runtime (Claude Code, Cursor, ...):")
    print("  /simplicio-loop finish all the open issues")
    return 0


def _port_up(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), 0.5):
            return True
    except OSError:
        return False


def _stop_dashboard() -> int:
    """Best-effort stop: kill the PID the dashboard recorded, then any stray server."""
    killed = False
    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, 15)
        killed = True
    except (OSError, ValueError):
        pass
    if os.name != "nt":  # pkill catches a server started outside this CLI
        try:
            subprocess.run(["pkill", "-f", "simplicio_dashboard.py"], check=False)
            killed = True
        except OSError:
            pass
    try:
        PID_FILE.unlink()
    except OSError:
        pass
    print("⬡ Token Monitor stopped." if killed else "⬡ dashboard was not running.")
    return 0


def dashboard(port: int, open_browser: bool, stop: bool) -> int:
    """Open (or stop) the Simplicio Token Monitor dashboard — works from anywhere after a pip
    install, no repo checkout needed. Starts the bundled server detached if it's not already up,
    then opens the browser. The dashboard is on-demand: nothing keeps it open, close it freely."""
    if stop:
        return _stop_dashboard()
    url = f"http://127.0.0.1:{port}"
    if not DASHBOARD.is_file():
        print("error: bundled dashboard not found in the installed package.", flush=True)
        return 1
    if not _port_up(port):
        logdir = Path.home() / ".simplicio" / "logs"
        logdir.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, "PORT": str(port)}
        # Detach so the server outlives this CLI process (own session / no console window).
        kw = {"start_new_session": True} if os.name != "nt" else {
            "creationflags": 0x00000008 | 0x00000200}  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        with open(logdir / "token-monitor.log", "ab") as logf:
            try:
                subprocess.Popen([sys.executable or "python3", str(DASHBOARD)],
                                 env=env, stdout=logf, stderr=logf, stdin=subprocess.DEVNULL, **kw)
            except OSError as e:
                print(f"error: could not start the dashboard ({e}).", flush=True)
                return 1
        for _ in range(25):  # wait up to ~5s for the port to come up
            if _port_up(port):
                break
            time.sleep(0.2)
    if not _port_up(port):
        print("⬡ failed to start the dashboard — see ~/.simplicio/logs/token-monitor.log", flush=True)
        return 1
    print(f"⬡ Simplicio Token Monitor → {url}")
    if open_browser and _gui_available():
        try:
            webbrowser.open(url)
        except Exception:
            pass
    print("   stop it any time:  simplicio-loop dashboard --stop")
    return 0


def _write_task_contract(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(__import__("json").dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def plan(task_path: str, out_path: str) -> int:
    raw = Path(task_path).read_text(encoding="utf-8")
    payload = compile_many(raw, source_path=task_path)
    out = Path(out_path)
    _write_task_contract(out, payload)
    print(f"simplicio-loop plan wrote {out}")
    for idx, task in enumerate(payload.get("tasks") or [], start=1):
        if idx > 1:
            print("")
        print(f"[task {idx}]")
        print(preview_contract(task))
    return 0


def prepare(repo: str, task_path: str, delivery_arg: str, max_iterations: int) -> int:
    """Arm and preflight a run without executing a task or calling a provider."""
    try:
        delivery_target = delivery.normalize_delivery_target(delivery_arg)
        armed = arm_run(repo, task_path, delivery_target, max_iterations)
        manifest = armed.get("manifest") or {}
        state = armed.get("state") or {}
        phase = str(state.get("phase") or "blocked")
        payload = {
            "schema": "simplicio.prepare-receipt/v1",
            "status": "prepared" if phase != "blocked" else "blocked",
            "run_id": str(manifest.get("run_id") or ""),
            "run_dir": str(armed.get("run_dir") or ""),
            "phase": phase,
            "execution_started": False,
            "mutation_attempted": False,
            "provider_worker_invoked": False,
            "next_action": "tick, batch, wave, or prism with the returned run_id" if phase != "blocked" else "inspect blocker",
        }
        if phase == "blocked":
            payload["blockers"] = list(state.get("blockers") or [])
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        payload = {
            "schema": "simplicio.prepare-receipt/v1",
            "status": "blocked",
            "run_id": "",
            "run_dir": "",
            "phase": "blocked",
            "execution_started": False,
            "mutation_attempted": False,
            "provider_worker_invoked": False,
            "reason_code": "prepare_failed",
            "error": redact_sensitive_text(str(exc)),
        }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["status"] == "prepared" else 2


def run(repo: str, task_path: str, delivery_arg: str, max_iterations: int,
            quality_provider: Optional[str] = None, quality_policy: str = "strict-default",
            result_file: str = "", required_handshake_fingerprint: str = "",
            provider_worker: str | None = None) -> int:
    # Preserve the pre-result-file positional surface used by integrations that
    # passed the fingerprint as the seventh argument.
    if not required_handshake_fingerprint and str(result_file).startswith("sha256:"):
        required_handshake_fingerprint, result_file = str(result_file), ""
    if required_handshake_fingerprint:
        from .extension_handshake import ExtensionHandshakeError, verify_runtime_fingerprint
        try:
            verify_runtime_fingerprint(required_handshake_fingerprint)
        except ExtensionHandshakeError as exc:
            persist_execution_envelope(
                flow="run", repo=repo,
                observed={
                    "status": "error",
                    "result": {"status": "error", "reason_code": exc.reason_code},
                    "error": redact_sensitive_text(str(exc)),
                },
            )
            print(f"error: {exc.reason_code}: {exc.detail}", file=sys.stderr)
            return 2
    try:
        delivery_target = delivery.normalize_delivery_target(delivery_arg)
    except delivery.DeliveryTargetError as exc:
        persist_execution_envelope(
            flow="run", repo=repo,
            observed={
                "status": "error",
                "result": {"status": "error", "reason_code": "invalid_delivery_target"},
                "error": redact_sensitive_text(str(exc)),
            },
        )
        print(f"error: {exc}", file=sys.stderr)
        return 2
    try:
        conduct_kwargs = {
            "quality_provider": quality_provider,
            "quality_policy": quality_policy,
        }
        if provider_worker is not None:
            conduct_kwargs["provider_worker"] = provider_worker
        payload = conduct_run(
            repo, task_path, delivery_target, max_iterations,
            **conduct_kwargs,
        )
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        outcome = {
            "schema": "simplicio.run-outcome/v1", "run_id": "", "phase": "infrastructure_failure",
            "outcome": "INFRASTRUCTURE_FAILURE", "exit_code": 24,
            "source": {"kind": "local", "identity": str(task_path), "digest": ""},
            "oracle": {"verdict": "UNAVAILABLE", "authorized": False},
            "completion_receipt": {"path": "", "sha256": None, "validation": "infrastructure_failure"},
        }
        persist_execution_envelope(
            flow="run", repo=repo, observed={
                "status": "error", "result": outcome, "error": redact_sensitive_text(str(exc)),
            },
        )
        if result_file:
            target = Path(result_file)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(outcome, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        diagnostic = publish_loop_execution_for_flow(
            repo=Path(repo),
            run_dir=Path(repo).resolve() / ".simplicio" / "loop-runs" / "run-failed",
            flow="run",
            flow_result={"status": "infrastructure_failure"},
        )
        diagnostic["error"] = redact_sensitive_text(str(exc))
        print(json.dumps(diagnostic, ensure_ascii=False, indent=2))
        return 24
    run_id = str((payload.get("manifest") or {}).get("run_id") or "")
    persist_execution_envelope(
        flow="run", repo=repo, run_id=run_id,
        observed={**payload, "result": payload.get("outcome") or {}, "status": (payload.get("state") or {}).get("phase")},
    )
    outcome = payload["outcome"]
    if result_file:
        target = Path(result_file)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(outcome, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    public_payload = _public_flow_from_status(payload, "run", payload)
    print(json.dumps(public_payload, ensure_ascii=False, indent=2))
    if public_payload.get("status") == "VERIFIED" and public_payload.get("verified") is True:
        return 0
    return int(outcome["exit_code"]) if int(outcome.get("exit_code") or 0) != 0 else 2


_ORIGINAL_RUN = run

ORIENT_SCHEMA = "simplicio.loop-orient/v1"
ORIENT_RECEIPT_SCHEMA = "simplicio.loop-orient-receipt/v1"


def _orient_hash(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _orient_revision(root: Path) -> str | None:
    if not (root / ".git").exists():
        return None
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(root), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            close_fds=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    revision = (result.stdout or "").strip()
    return revision if result.returncode == 0 and revision else None


def _orient_provider_provenance(payload: Mapping[str, Any]) -> dict[str, Any]:
    provider = str(payload.get("provider") or "")
    provider_payload = payload.get("fast") if provider == "simplicio-fast" else payload.get("mapper")
    provider_payload = provider_payload if isinstance(provider_payload, Mapping) else {}
    ingest = provider_payload.get("ingest") if isinstance(provider_payload.get("ingest"), Mapping) else {}
    mapper_result = provider_payload.get("result") if isinstance(provider_payload.get("result"), Mapping) else {}
    snapshot = mapper_result.get("source_snapshot") if isinstance(mapper_result.get("source_snapshot"), Mapping) else {}
    context_pack = mapper_result.get("context_pack") if isinstance(mapper_result.get("context_pack"), Mapping) else {}
    probe = ingest.get("probe") if isinstance(ingest.get("probe"), Mapping) else {}
    return {
        "operator": provider or None,
        "operator_version": probe.get("version"),
        "generation": provider_payload.get("generation") or ingest.get("generation") or snapshot.get("snapshot_id"),
        "context_hash": provider_payload.get("context_hash") or context_pack.get("pack_hash") or snapshot.get("root_hash"),
        "plan_hash": provider_payload.get("plan_hash"),
        "source_revision": ingest.get("source_commit") or snapshot.get("revision"),
        "provider_payload_hash": _orient_hash(provider_payload),
    }


COMMAND_CARD_SCHEMA = "simplicio.loop-command-card/v1"
COMMAND_CARD_MAX_BYTES = 1_500


def _orient_command_card(root: Path) -> dict[str, Any]:
    """Exact next commands for this repo (< 1.5 KB serialized).

    An LLM host that just ran ``orient`` needs the literal next commands,
    the edit-plan path pattern/minimal format, and the task-file lane +
    waiver lines without re-reading ``SKILL.md`` -- so orient answers it
    directly.
    """
    repo = str(root)
    return {
        "schema": COMMAND_CARD_SCHEMA,
        "prepare": f"simplicio-loop prepare --task tasks.md --repo {repo}",
        "wave": f"simplicio-loop wave <run_id> --repo {repo}",
        "verify": f"simplicio-loop verify <run_id> --repo {repo}",
        "tick": f"simplicio-loop tick <run_id> --repo {repo} --task-index <N>",
        "edit_plan_path": ".simplicio/loop-runs/<run_id>/edit-plan-<N>.json",
        "edit_plan_format": {
            "operations": [{"path": "<repo-relative>", "find": "<exact text>", "replace": "<new text>"}]
        },
        "edit_plan_rule": "find must match exactly once in path",
        "task_file_lanes": [
            "Independent verifier:",
            "Unit verifier:",
            "Integration verifier:",
            "System verifier:",
            "Regression verifier:",
            "Benchmark verifier:",
            "Coverage verifier:",
        ],
        "waiver": {"type_line": "Type: Docs|Chore|Config", "tests_line": "Tests: none"},
    }


def _seal_orient_payload(
    payload: dict[str, Any], *, root: Path, task: str, fast_mode: str,
    fast_engine: str, fast_context_budget: int,
) -> dict[str, Any]:
    contract = llm_max_speed_orientation_contract()
    contract["request_policy"] = {
        "fast_mode": fast_mode,
        "fast_engine": fast_engine,
        "context_budget_bytes": int(fast_context_budget),
        "fallback_allowed": fast_mode != "on" and fast_engine != "rust",
    }
    payload["llm_orientation"] = contract
    payload["commands"] = _orient_command_card(root)
    provenance = _orient_provider_provenance(payload)
    receipt = {
        "schema": ORIENT_RECEIPT_SCHEMA,
        "orient_schema": ORIENT_SCHEMA,
        "status": payload.get("status"),
        "provider": payload.get("provider"),
        "fallback": bool(payload.get("fallback")),
        "fallback_reason": payload.get("fallback_reason"),
        "repo": str(root),
        "source_revision": provenance.get("source_revision") or _orient_revision(root),
        "task_hash": _orient_hash(str(task).strip()),
        "contract_hash": _orient_hash(contract),
        "provenance": provenance,
    }
    receipt["receipt_hash"] = _orient_hash(receipt)
    payload["receipt"] = receipt
    return payload

def _mapper_orient_fallback(root: Path, task: str) -> dict:
    """Use Mapper's read-only orient surface when Fast is unavailable."""
    task_path = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".md",
                                         prefix=".simplicio-loop-orient-",
                                         dir=str(root), delete=False) as handle:
            handle.write(task)
            task_path = Path(handle.name)
        proc = subprocess.run(
            ["simplicio-mapper", "orient", str(root), "--task-file", str(task_path), "--json"],
            cwd=str(root), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, close_fds=True, timeout=180, check=False,
        )
        raw = (proc.stdout or "").strip()
        try:
            result = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            result = {"raw_tail": raw[-4000:]}
        return {"status": "READY" if proc.returncode == 0 else "BLOCKED",
                "returncode": proc.returncode, "result": result,
                "stderr": (proc.stderr or "")[-2000:]}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"status": "BLOCKED", "returncode": None, "reason": str(exc)}
    finally:
        if task_path is not None:
            try:
                task_path.unlink()
            except OSError:
                pass

def _orient_extract_fallback_reason(fast_payload: Mapping[str, Any] | None) -> str:
    """Pull the real cause out of a Fast prepare() FALLBACK payload.

    ``FastLoopIntegration.prepare()`` nests the actual reason under
    ``ingest``/``understanding`` (each stage's own fallback receipt); it is
    never a top-level ``reason`` key except in tests that stub the whole
    integration. Reading only the top level (issue #1288) silently collapsed
    every real cause -- including a missing Mapper handoff with Fast fully
    available -- into the generic ``fast_disabled_or_unavailable``.
    """
    payload = fast_payload or {}
    top_level = payload.get("reason")
    if top_level:
        return str(top_level)
    for stage in ("ingest", "understanding"):
        stage_payload = payload.get(stage)
        if isinstance(stage_payload, Mapping):
            value = stage_payload.get("reason")
            if value:
                return str(value)
    return ""


def _orient_context_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Bounded, task-relevant leading context (issue #1288 AC2/AC3).

    Extracted from whichever provider answered (Fast understanding or the
    Mapper fallback selection) so the top of the payload always carries
    paths/symbols instead of only receipts/policy text.
    """
    provider = payload.get("provider")
    if provider == "simplicio-fast":
        understanding = ((payload.get("fast") or {}).get("understanding")
                          if isinstance(payload.get("fast"), Mapping) else None)
        understanding = understanding if isinstance(understanding, Mapping) else {}
        return {
            "paths": list(understanding.get("files") or []),
            "symbols": list(understanding.get("symbols") or []),
            "snippet_count": len(understanding.get("context") or []),
        }
    mapper = payload.get("mapper") if isinstance(payload.get("mapper"), Mapping) else {}
    result = mapper.get("result") if isinstance(mapper.get("result"), Mapping) else {}
    selection = result.get("selection") if isinstance(result.get("selection"), Mapping) else {}
    candidates = result.get("candidates") if isinstance(result.get("candidates"), list) else []
    targets = selection.get("targets") if isinstance(selection.get("targets"), list) else []
    return {
        "paths": [str(item) for item in targets if isinstance(item, str)],
        "symbols": [],
        "candidate_count": len(candidates),
        "gaps": list(result.get("gaps") or []),
    }


def _orient_trim_verbose_fields(payload: dict[str, Any]) -> dict[str, Any]:
    """Move receipts/probes/policy text out of the default (non-verbose) view.

    Kept fields stay byte-identical; this only removes the bulk of the
    non-task-relevant payload (issue #1288 AC2) so the default response leads
    with ``context`` instead of ~9.5KB of receipts. The full payload remains
    available via ``--verbose`` or the ``--tee`` cache.
    """
    trimmed = dict(payload)
    trimmed.pop("llm_orientation", None)
    fast = trimmed.get("fast")
    if isinstance(fast, Mapping):
        fast = dict(fast)
        for stage in ("ingest", "understanding"):
            stage_payload = fast.get(stage)
            if isinstance(stage_payload, Mapping):
                stage_payload = dict(stage_payload)
                stage_payload.pop("probe", None)
                fast[stage] = stage_payload
        # Raw Fast context/selection/plan nodes can reach hundreds of KB; the
        # default view keeps what the caller decides on (files, terms, hashes).
        for stage, bulky in (("understanding", ("selection", "context")),
                             ("plan", ("nodes", "understanding", "context_handles"))):
            stage_payload = fast.get(stage)
            if isinstance(stage_payload, Mapping):
                fast[stage] = {k: v for k, v in stage_payload.items() if k not in bulky}
        trimmed["fast"] = fast
    mapper = trimmed.get("mapper")
    if isinstance(mapper, Mapping):
        mapper = dict(mapper)
        mapper.pop("stderr", None)
        trimmed["mapper"] = mapper
    return trimmed


def orient(repo: str, task: str, fast_mode: str = "auto",
           fast_context_budget: int = 48000, fast_engine: str = "auto",
           tee: bool = False, targets: list[str] | None = None,
           verbose: bool = False) -> int:
    """Run bounded Fast orient with an explicit Mapper fallback receipt."""
    root = Path(repo).resolve()
    if not root.is_dir() or not str(task).strip():
        payload = {"schema": ORIENT_SCHEMA, "status": "BLOCKED",
                   "provider": None, "fallback": False,
                   "reason": "repo_or_task_invalid", "local_llm": False}
        _seal_orient_payload(payload, root=root, task=str(task), fast_mode=fast_mode,
                             fast_engine=fast_engine,
                             fast_context_budget=fast_context_budget)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 2
    if fast_context_budget < 1:
        payload = {"schema": ORIENT_SCHEMA, "status": "BLOCKED",
                   "provider": None, "fallback": False,
                   "reason": "fast_context_budget_invalid", "local_llm": False}
        _seal_orient_payload(payload, root=root, task=str(task), fast_mode=fast_mode,
                             fast_engine=fast_engine,
                             fast_context_budget=fast_context_budget)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 2
    if fast_engine not in {"auto", "rust", "python", "off"}:
        raise ValueError("fast_engine must be auto, rust, python, or off")
    config_mode = {"auto": "auto", "on": "required", "off": "standalone"}.get(fast_mode)
    if config_mode is None:
        raise ValueError("fast_mode must be auto, on, or off")
    fast_payload = None
    fallback_reason = ""
    try:
        effective_mode = (
            "required" if fast_engine == "rust"
            else ("standalone" if fast_engine == "off" else config_mode)
        )
        integration = FastLoopIntegration(
            root,
            config=FastConfig(mode=effective_mode, engine=fast_engine,
                              max_bytes=int(fast_context_budget)),
            extra_targets=list(targets or []),
        )
        fast_payload = integration.prepare(str(task))
        if fast_mode == "on" and fast_payload.get("status") != "READY":
            fallback_reason = str(fast_payload.get("reason") or "fast_not_ready")
    except (FastIntegrationError, OSError, ValueError) as exc:
        fallback_reason = str(exc)
        fast_payload = {"status": "BLOCKED", "reason": fallback_reason}
    if fast_payload and fast_payload.get("status") == "READY":
        payload = {"schema": ORIENT_SCHEMA, "status": "READY",
                          "provider": "simplicio-fast", "fallback": False,
                          "fast_engine": fast_engine, "fast": fast_payload,
                          "orient_receipt": fast_payload.get("loop_receipt"),
                          "local_llm": False}
        _seal_orient_payload(payload, root=root, task=str(task), fast_mode=fast_mode,
                             fast_engine=fast_engine,
                             fast_context_budget=fast_context_budget)
        payload["context"] = _orient_context_summary(payload)
        if not verbose:
            payload = _orient_trim_verbose_fields(payload)
        if tee:
            from .tee_cache import write
            path = write(root, json.dumps(payload, ensure_ascii=False, indent=2))
            payload["tee_path"] = str(path)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    if fast_mode == "on" or fast_engine == "rust":
        fallback_reason = fallback_reason or _orient_extract_fallback_reason(fast_payload) or "fast_not_ready"
        payload = {"schema": ORIENT_SCHEMA, "status": "BLOCKED",
                          "provider": "simplicio-fast", "fallback": False,
                          "fast_engine": fast_engine,
                          "fallback_reason": fallback_reason,
                           "fast": fast_payload,
                           "orient_receipt": (fast_payload or {}).get("loop_receipt"),
                           "local_llm": False}
        _seal_orient_payload(payload, root=root, task=str(task), fast_mode=fast_mode,
                             fast_engine=fast_engine,
                             fast_context_budget=fast_context_budget)
        if not verbose:
            payload = _orient_trim_verbose_fields(payload)
        if tee:
            from .tee_cache import write
            path = write(root, json.dumps(payload, ensure_ascii=False, indent=2))
            payload["tee_path"] = str(path)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 2
    fallback_reason = (
        fallback_reason
        or _orient_extract_fallback_reason(fast_payload)
        or "fast_disabled_or_unavailable"
    )
    mapper = _mapper_orient_fallback(root, str(task))
    status = "FALLBACK" if mapper.get("status") == "READY" else "BLOCKED"
    payload = {"schema": ORIENT_SCHEMA, "status": status,
                      "provider": "simplicio-mapper", "fallback": True,
                      "fallback_reason": fallback_reason, "fast_engine": fast_engine,
                      "fast": fast_payload,
                      "mapper": mapper, "local_llm": False}
    _seal_orient_payload(payload, root=root, task=str(task), fast_mode=fast_mode,
                         fast_engine=fast_engine,
                         fast_context_budget=fast_context_budget)
    payload["context"] = _orient_context_summary(payload)
    if not verbose:
        payload = _orient_trim_verbose_fields(payload)
    if tee:
        from .tee_cache import write
        path = write(root, json.dumps(payload, ensure_ascii=False, indent=2))
        payload["tee_path"] = str(path)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if status == "FALLBACK" else 2


def extensions_doctor(provider: str, policy: str, schema: str) -> int:
    from .extension_handshake import ExtensionHandshakeError, extension_handshake
    try:
        payload = extension_handshake(provider, policy, requested_schema=schema)
    except ExtensionHandshakeError as exc:
        payload = {"schema": schema, "status": "BLOCKED", "reason_code": exc.reason_code, "detail": exc.detail}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def verify(repo: str, run_id: str) -> int:
    from .runner import verify_run
    payload = verify_run(repo, run_id)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["state"].get("phase") == "done" else 1


def _render_status_text(payload: dict) -> str:
    """Human-readable one-screen summary of a run status payload."""
    state = payload.get("state") or {}
    lines = ["simplicio-loop run status", ""]
    run_dir = payload.get("run_dir", "")
    if run_dir:
        lines.append(f"run_dir: {run_dir}")
    completion = state.get("completion") or {}
    lines.append(f"phase: {state.get('phase', 'UNKNOWN')}")
    lines.append(f"completion_tag: {completion.get('tag', 'UNVERIFIED')}")
    coverage = completion.get("coverage")
    if coverage:
        lines.append(f"coverage: {coverage}")
    delivery = state.get("delivery") or {}
    lines.append(f"delivery_ready: {delivery.get('ready', False)}")
    route = payload.get("execution_route") or state.get("execution_route") or {}
    lines.append(f"execution_route: {route.get('route', 'UNVERIFIED')}")
    lines.append(f"route_receipt_sha: {route.get('receipt_sha', '') or 'UNVERIFIED'}")
    lines.append(f"route_backend: {route.get('backend', 'UNVERIFIED')}")
    return "\n".join(lines) + "\n"


def status(repo: str, run_id: str, as_json: bool = False, as_text: bool = False) -> int:
    try:
        payload = read_status(repo, run_id)
        if (payload.get("state") or {}).get("phase") == "no_runs":
            payload.update({"schema": "simplicio.status/v1", "status": "UNVERIFIED",
                            "reason_code": "run_missing"})
    except (FileNotFoundError, OSError, ValueError, KeyError) as exc:
        payload = {"schema": "simplicio.status/v1", "status": "UNVERIFIED",
                   "reason_code": "run_missing", "error": str(exc)}
    # Default remains JSON (backwards-compatible). --text opts into the human summary.
    if as_text and not as_json:
        print(_render_status_text(payload))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def economy_command(args) -> int:
    """economy status | print | apply — fastest token path + parallel defaults."""
    import json as _json

    from .economy_profile import (
        economy_parallel_env,
        persist_user_profile,
        profile_status,
        render_shell_exports,
    )

    sub = getattr(args, "economy_command", None)
    if sub == "status":
        payload = profile_status()
        if args.json:
            print(_json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(f"economy profile: {payload['profile']} enabled={payload['enabled']}")
            print(
                f"  execution_profile={payload.get('execution_profile')} "
                f"runtime_operational={payload.get('runtime_operational')}"
            )
            if payload.get("note"):
                print(f"  note: {payload['note']}")
            print(f"  cpu={payload['cpu_count']} aligned={payload['aligned']}")
            print(f"  workers={payload['recommended'].get('SIMPLICIO_LOOP_OPERATOR_WORKERS')}")
            print(f"  prism_slots={payload['recommended'].get('SIMPLICIO_PRISM_SLOTS')}")
            print(f"  async={payload['recommended'].get('SIMPLICIO_ASYNC_IO_MAX_CONCURRENCY')}")
            print(f"  fan_out={payload['recommended'].get('SIMPLICIO_LOOP_AUTO_FAN_OUT')}")
            if payload["drift_keys"]:
                print(f"  drift: {', '.join(payload['drift_keys'][:12])}")
                if payload.get("drift_explanation"):
                    print(f"  why: {payload['drift_explanation']}")
                if payload.get("drift_fix"):
                    print(f"  fix: {payload['drift_fix']}")
            print("  backends: Runtime Tokio · Python asyncio · Prism slots")
        return 0 if payload.get("enabled") else 1
    if sub == "print":
        env_map = economy_parallel_env()
        if args.json:
            print(_json.dumps({"schema": "simplicio.economy-parallel-profile/v1", "env": env_map},
                              ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(render_shell_exports(env_map, shell=args.shell), end="")
        return 0
    if sub == "apply":
        no_user = bool(getattr(args, "no_user", False))
        if no_user:
            import os as _os

            applied = economy_parallel_env()
            for key, value in applied.items():
                _os.environ[key] = value
            payload = {
                "schema": "simplicio.economy-parallel-profile/v1",
                "ok": True,
                "scope": "process",
                "env": applied,
            }
        else:
            payload = persist_user_profile(set_windows_user_env=True)
        if args.json:
            print(_json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(f"economy apply ok={payload.get('ok')} profile={payload.get('profile')}")
            paths = payload.get("paths") or {}
            if paths.get("ps1"):
                print(f"  ps1: {paths['ps1']}")
            if paths.get("sh"):
                print(f"  sh:  {paths['sh']}")
            if payload.get("rc_files_changed"):
                print(f"  rc_files_changed: {', '.join(payload['rc_files_changed'])}")
            print(f"  workers={payload.get('env', {}).get('SIMPLICIO_LOOP_OPERATOR_WORKERS')}")
            print(f"  prism_slots={payload.get('env', {}).get('SIMPLICIO_PRISM_SLOTS')}")
        return 0 if payload.get("ok", True) else 1
    print("unknown economy command", file=sys.stderr)
    return 2


def preflight(repo: str, as_json: bool = False, *, strict: bool = False) -> int:
    """Verify bound operators and report Runtime/Fast availability.

    Under ``--strict`` / ``SIMPLICIO_LOOP_STRICT=1``:
    - Runtime is required when operational (auto) or always when forced
    - Fast is required when operational
    - hand-edit is reported as forbidden

    Returns exit 0 when all *required* operators are present, 1 otherwise.
    """
    import os as _os

    from .finding_router import route_finding as _route_finding
    from .strict_mode import preflight_payload, recommended_env

    repo_path = Path(repo).resolve()
    if strict:
        _os.environ["SIMPLICIO_LOOP_STRICT"] = "1"
    payload = preflight_payload(str(repo_path), strict=strict)
    all_present = bool(payload.get("all_present"))
    runtime_available = bool(payload.get("runtime_available"))
    missing = list(payload.get("missing_operators") or [])
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print("simplicio-loop preflight" + (" [STRICT]" if payload.get("strict") else ""))
        required = set(payload.get("required_operators") or [])
        for op in payload.get("operators") or []:
            name = op.get("name", "")
            present = bool(op.get("present"))
            if present:
                mark = "OK "
            elif name in required or name in {"simplicio-mapper", "simplicio-dev-cli"}:
                mark = "MISSING"
            else:
                mark = "OPTIONAL"
            ver = f" ({op['version']})" if op.get("version") else ""
            extra = ""
            if name == "simplicio-dev-cli" and op.get("resolved_as"):
                extra = f" via {op['resolved_as']}"
            print(f"  [{mark}] {name}{ver}{extra}")
        print("  all_present: true" if all_present else "  NOT ALL REQUIRED OPERATORS PRESENT")
        print(f"  execution_profile: {payload.get('execution_profile')}")
        print(f"  hand_edit_forbidden: {payload.get('hand_edit_forbidden')}")
        if runtime_available:
            print("  runtime integration: operational (bound when auto/required)")
        else:
            print("  runtime integration: unavailable (core loop continues unless required)")
        if payload.get("strict"):
            print("  recommended_env:")
            for key, value in (recommended_env() or {}).items():
                print(f"    {key}={value}")
    if not all_present:
        for name in missing:
            _route_finding(
                stage="preflight",
                finding_id=f"missing-operator-{name}",
                severity="high",
                source=f"preflight:{name}",
                confirmed=True,
                item_id=None,
                repo=str(repo_path),
                detail=f"bound operator {name} not present or not operational",
            )
    return 0 if all_present else 1


def resume(repo: str, run_id: str) -> int:
    payload = change_phase(repo, run_id, "awaiting_decision", "resume requested from CLI")
    print(__import__("json").dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _dispatch_failure_payload(schema: str, repo: str, run_id: str, error: Exception,
                              task_indices: Optional[Sequence[int]] = None) -> dict:
    payload = {
        "schema": schema,
        "status": "blocked",
        "reason_code": "operator_dispatch_failed",
        "repo": str(repo),
        "run_id": str(run_id),
        "task_indices": list(task_indices or []),
        "error_type": type(error).__name__,
        "error": redact_sensitive_text(str(error)),
    }
    payload["receipt_hash"] = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return payload


def _dispatch_exit_code(payload: Mapping[str, Any]) -> int:
    """Return non-zero whenever a dispatch receipt is not a verified success."""
    if not payload:
        return 0  # preserve the thin CLI seam used by compatibility callers
    status = str(payload.get("status") or "").lower()
    if status in {"blocked", "held", "failed", "cancelled", "error"}:
        return 2
    if str(payload.get("phase") or "").lower() in {"blocked", "cancelled"}:
        return 2
    if str(payload.get("execution_state") or "").lower() in {"blocked", "uncertain"}:
        return 2
    if str(payload.get("action") or "") in {
        "operator_failed", "operator_batch_blocked", "operator_batch_preflight_blocked",
    }:
        return 2
    if payload.get("failed") or payload.get("blocked") or payload.get("dead_letter") or payload.get("blockers"):
        return 2
    admission = payload.get("capacity") or payload.get("admission")
    if isinstance(admission, Mapping) and admission.get("admitted") is False:
        return 2
    workers = payload.get("workers")
    if isinstance(workers, list) and any(
        not isinstance(worker, Mapping) or worker.get("status") not in {"succeeded", "completed"}
        for worker in workers
    ):
        return 2
    if payload.get("requested_tasks") and isinstance(workers, list) and not workers:
        return 2
    return 0


def _reconcile_prism_wave(task_indices: Sequence[int], result: Mapping[str, Any]) -> dict:
    requested = [int(index) for index in task_indices]
    requested_set = set(requested)
    workers = result.get("workers") if isinstance(result, Mapping) else None
    workers = workers if isinstance(workers, list) else []
    completed = {
        int(index) for index in (result.get("completed_tasks") or [])
        if isinstance(index, (int, str)) and str(index).lstrip("-").isdigit()
    } if isinstance(result, Mapping) else set()
    worker_by_task = {}
    failed = []
    for worker in workers:
        if not isinstance(worker, Mapping):
            failed.append(None)
            continue
        try:
            task_index = int(worker.get("task_index"))
        except (TypeError, ValueError):
            failed.append(None)
            continue
        worker_by_task[task_index] = worker
        if worker.get("status") not in {"succeeded", "completed"}:
            failed.append(task_index)
    missing = sorted(requested_set - set(worker_by_task) - completed)
    if failed:
        reason_code = "wave_worker_failed"
    elif missing:
        reason_code = "wave_receipt_missing"
    elif not workers and not completed:
        reason_code = "wave_receipt_invalid"
    elif isinstance(result, Mapping) and str(result.get("status") or "").lower() not in {"completed", "succeeded", "success"}:
        reason_code = "wave_not_terminal"
    else:
        reason_code = "wave_receipts_reconciled"
    ok = reason_code == "wave_receipts_reconciled"
    return {
        "schema": "simplicio.prism-wave-reconciliation/v1",
        "status": "reconciled" if ok else "held",
        "ok": ok,
        "requested_tasks": requested,
        "missing": missing,
        "failed": sorted(index for index in failed if index is not None),
        "reason_code": reason_code,
    }


def _public_flow_run_dir(repo: str, run_id: str) -> Path:
    """Resolve the run directory without inventing a successful artifact."""
    try:
        status = read_status(repo, run_id)
        candidate = Path(status["run_dir"])
        return candidate
    except (KeyError, OSError, TypeError, ValueError):
        return Path(repo).resolve() / ".simplicio" / "loop-runs" / str(run_id)


def _attach_dispatch(public_payload: Mapping[str, Any], dispatch: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(public_payload)
    payload["dispatch"] = dict(dispatch)
    for key in ("route", "reason_code", "missing_tools", "provider_worker"):
        if key in dispatch and (key not in payload or key == "reason_code"):
            payload[key] = dispatch[key]
    return payload


def _finalize_public_flow(repo: str, run_id: str, flow: str, dispatch: Mapping[str, Any]) -> dict[str, Any]:
    """Return one v1 public result and persist the v2 adapter envelope once."""

    def _done(payload: Mapping[str, Any]) -> dict[str, Any]:
        persist_execution_envelope(
            flow=flow,
            repo=repo,
            run_id=run_id,
            observed={"run_id": run_id, "result": dict(dispatch), **dict(dispatch)},
        )
        return dict(payload)

    raw_status = str(
        dispatch.get("status")
        or dispatch.get("phase")
        or dispatch.get("execution_state")
        or ""
    ).strip().lower()
    nonterminal = {
        "blocked", "partial", "error", "failed", "held", "cancelled", "canceled",
        "unverified", "infrastructure_failure",
    }
    if raw_status in nonterminal or _dispatch_exit_code(dispatch) != 0:
        flow_result = {"status": raw_status or "blocked", "run_id": run_id}
        if isinstance(dispatch.get("state"), Mapping):
            flow_result["state"] = dict(dispatch["state"])
        diagnostic = publish_loop_execution_for_flow(
            repo=Path(repo),
            run_dir=_public_flow_run_dir(repo, run_id),
            flow=flow,
            flow_result=flow_result,
        )
        return _done(_attach_dispatch(diagnostic, dispatch))
    try:
        verified_status = verify_run(repo, run_id, flow=flow)
        state = verified_status.get("state") if isinstance(verified_status, Mapping) else {}
        loop_execution = state.get("loop_execution") if isinstance(state, Mapping) else {}
        if (
            isinstance(state, Mapping)
            and state.get("phase") == "done"
            and isinstance(loop_execution, Mapping)
            and loop_execution.get("status") == "VERIFIED"
        ):
            receipt_path = Path(repo).resolve() / ".simplicio" / "loop-execution.json"
            envelope = json.loads(receipt_path.read_text(encoding="utf-8"))
            if (
                isinstance(envelope, Mapping)
                and envelope.get("schema") == LOOP_EXECUTION_SCHEMA
                and (envelope.get("result") or {}).get("status") == "VERIFIED"
                and (envelope.get("result") or {}).get("verified") is True
            ):
                result = dict(envelope)
                result["status"] = "VERIFIED"
                result["verified"] = True
                return _done(_attach_dispatch(result, dispatch))
        phase = str((state or {}).get("phase") or "blocked")
        flow_result = {"status": phase, "run_id": run_id}
        if isinstance(state, Mapping):
            flow_result["state"] = dict(state)
        diagnostic = publish_loop_execution_for_flow(
            repo=Path(repo),
            run_dir=_public_flow_run_dir(repo, run_id),
            flow=flow,
            flow_result=flow_result,
        )
        return _done(_attach_dispatch(diagnostic, dispatch))
    except Exception as exc:
        diagnostic = publish_loop_execution_for_flow(
            repo=Path(repo),
            run_dir=_public_flow_run_dir(repo, run_id),
            flow=flow,
            flow_result={"status": "blocked", "run_id": run_id},
        )
        diagnostic["reason_code"] = "v1_publication_failed"
        diagnostic["reason"] = f"public flow could not reach a verified v1 receipt: {redact_sensitive_text(str(exc))}"
        return _done(_attach_dispatch(diagnostic, dispatch))


def _public_flow_from_status(status: Mapping[str, Any], flow: str, dispatch: Mapping[str, Any]) -> dict[str, Any]:
    """Project an already-conducted run without invoking publication again."""
    state = status.get("state") if isinstance(status, Mapping) else {}
    loop_execution = state.get("loop_execution") if isinstance(state, Mapping) else {}
    run_id = str(
        (status.get("manifest") or {}).get("run_id")
        or dispatch.get("run_id")
        or ""
    ) if isinstance(status, Mapping) else str(dispatch.get("run_id") or "")
    if (
        isinstance(state, Mapping)
        and state.get("phase") == "done"
        and isinstance(loop_execution, Mapping)
        and loop_execution.get("status") == "VERIFIED"
    ):
        repo = str((status.get("manifest") or {}).get("repo") or dispatch.get("repo") or ".")
        receipt_path = Path(repo).resolve() / ".simplicio" / "loop-execution.json"
        try:
            envelope = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError):
            envelope = {}
        if (
            isinstance(envelope, Mapping)
            and envelope.get("schema") == LOOP_EXECUTION_SCHEMA
            and (envelope.get("result") or {}).get("status") == "VERIFIED"
            and (envelope.get("result") or {}).get("verified") is True
        ):
            result = dict(envelope)
            result["status"] = "VERIFIED"
            result["verified"] = True
            return _attach_dispatch(result, dispatch)
    phase = str((state or {}).get("phase") or "blocked")
    flow_result = {"status": phase, "run_id": run_id}
    if isinstance(state, Mapping):
        flow_result["state"] = dict(state)
    diagnostic = publish_loop_execution_for_flow(
        repo=Path(str((status.get("manifest") or {}).get("repo") or dispatch.get("repo") or ".")),
        run_dir=Path(str(status.get("run_dir") or "")) if status.get("run_dir") else Path("."),
        flow=flow,
        flow_result=flow_result,
    )
    return _attach_dispatch(diagnostic, dispatch)


def _persist_prism_wave_receipt(repo: str, run_id: str, payload: dict) -> str:
    try:
        status = read_status(repo, run_id)
        run_dir = Path(status["run_dir"])
        if not run_dir.is_dir():
            return ""
        path = run_dir / "prism-wave-dispatch.json"
        payload["receipt_path"] = str(path)
        unsigned = dict(payload)
        unsigned.pop("receipt_hash", None)
        payload["receipt_hash"] = hashlib.sha256(
            json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        return str(path)
    except (KeyError, OSError, TypeError, ValueError):
        return ""


def tick(repo: str, run_id: str, task_index: int, provider_worker: str | None = None) -> int:
    try:
        current = read_status(repo, run_id)
    except Exception:
        current = {}
    governor = expected_governor_blocked(current)
    if governor is not None:
        payload = {
            "schema": "simplicio.tick-receipt/v1", "status": "blocked",
            "reason_code": governor["reason_code"], "governor": governor,
            "run_id": run_id, "task_indices": [task_index],
        }
        public_payload = _finalize_public_flow(repo, run_id, "tick", payload)
        print(json.dumps(public_payload, ensure_ascii=False, indent=2))
        return _dispatch_exit_code(public_payload)
    try:
        operator_kwargs = {"task_index": task_index}
        if provider_worker is not None:
            operator_kwargs["provider_worker"] = provider_worker
        payload = execute_operator(repo, run_id, **operator_kwargs)
    except Exception as exc:
        payload = _dispatch_failure_payload("simplicio.tick-receipt/v1", repo, run_id, exc, [task_index])
    public_payload = _finalize_public_flow(repo, run_id, "tick", payload)
    print(json.dumps(public_payload, ensure_ascii=False, indent=2))
    return _dispatch_exit_code(public_payload)


def batch(repo: str, run_id: str, task_indices: str, max_workers: int, retry_budget: int,
          serial: bool = False, batch_size: Optional[int] = None,
          provider_worker: str | None = None, *, flow: str = "batch") -> int:
    """Route up to three tasks directly; dispatch larger work in Prism waves."""
    indices = None
    if task_indices.strip():
        try:
            indices = [int(value.strip()) for value in task_indices.split(",") if value.strip()]
        except ValueError as exc:
            payload = _dispatch_failure_payload(
                "simplicio.operator-batch-receipt/v1", repo, run_id, exc,
            )
            persist_execution_envelope(flow=flow, repo=repo, run_id=run_id,
                                       observed={"run_id": run_id, "result": payload, "error": str(exc)})
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            raise ValueError("--task-indices must be a comma-separated list of integers") from exc

    if indices is None:
        try:
            status = read_status(repo, run_id)
            contract_path = Path(status["run_dir"]) / "task-contract.json"
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            indices = list(range(1, len(contract.get("tasks") or []) + 1))
        except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError):
            indices = None

    try:
        current = read_status(repo, run_id)
    except Exception:
        current = {}
    governor = expected_governor_blocked(current)
    if governor is not None:
        payload = {
            "schema": "simplicio.operator-batch-receipt/v1", "status": "blocked",
            "reason_code": governor["reason_code"], "run_id": run_id,
            "task_indices": list(indices or []), "governor": governor,
        }
        persist_execution_envelope(flow=flow, repo=repo, run_id=run_id,
                                   observed={**current, "result": payload, "governor": governor})
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 2

    eligibility = prism_is_eligible(len(indices or []), explicit_serial=serial)
    if not eligibility["eligible"]:
        try:
            batch_kwargs = {
                "max_workers": max_workers or None,
                "retry_budget": retry_budget,
                "auto_fan_out": not serial,
            }
            if provider_worker is not None:
                batch_kwargs["provider_worker"] = provider_worker
            payload = execute_operator_batch(repo, run_id, indices, **batch_kwargs)
        except Exception as exc:
            payload = _dispatch_failure_payload("simplicio.operator-batch-receipt/v1", repo, run_id, exc, indices)
        payload["prism"] = {**eligibility, "batch_size": None, "waves": 1}
        public_payload = _finalize_public_flow(repo, run_id, flow, payload)
        print(json.dumps(public_payload, ensure_ascii=False, indent=2))
        return _dispatch_exit_code(public_payload)

    width = resolve_prism_batch_size(batch_size)
    waves = prism_batches(indices, width)
    worker_limit = min(max_workers or width, width)
    wave_results = []
    all_reconciled = True
    for wave_number, wave in enumerate(waves, start=1):
        try:
            batch_kwargs = {
                "max_workers": worker_limit,
                "retry_budget": retry_budget,
                "auto_fan_out": True,
            }
            if provider_worker is not None:
                batch_kwargs["provider_worker"] = provider_worker
            result = execute_operator_batch(repo, run_id, wave, **batch_kwargs)
        except Exception as exc:
            result = _dispatch_failure_payload("simplicio.operator-batch-receipt/v1", repo, run_id, exc, wave)
        reconciliation = _reconcile_prism_wave(wave, result)
        wave_results.append({"wave": wave_number, "task_indices": wave, "result": result,
                             "reconciliation": reconciliation})
        if not reconciliation["ok"]:
            all_reconciled = False
            break

    workers = [worker for wave in wave_results for worker in (wave["result"].get("workers") or [])]
    payload = {
        "schema": "simplicio.prism-wave-dispatch/v1",
        "status": "completed" if all_reconciled and len(wave_results) == len(waves) else "held",
        "prism": {
            **eligibility,
            "batch_size": width,
            "wave_barrier": "reconcile-before-next",
            "waves": len(waves),
            "requested_tasks": indices,
        },
        "waves": wave_results,
        "workers": workers,
    }
    _persist_prism_wave_receipt(repo, run_id, payload)
    public_payload = _finalize_public_flow(repo, run_id, flow, payload)
    print(json.dumps(public_payload, ensure_ascii=False, indent=2))
    return _dispatch_exit_code(public_payload)


def cancel(repo: str, run_id: str) -> int:
    payload = change_phase(repo, run_id, "cancelled", "cancel requested from CLI")
    print(__import__("json").dumps(payload, ensure_ascii=False, indent=2))
    return 0


def checkpoint_lifecycle(args) -> int:
    root = Path(args.repo).resolve()
    lifecycle = CheckpointLifecycle(
        root / ".simplicio" / "loop-runs",
        task_id=args.task_id,
        attempt_id=args.attempt_id,
        source_commit=args.source_commit,
        fast_generation=args.fast_generation,
        base_path=args.base_path or root,
    )
    try:
        if args.lifecycle_action == "inspect":
            payload = lifecycle.load(args.candidate_id, args.shard_id)
        elif args.lifecycle_action == "cancel":
            payload = lifecycle.cancel(args.candidate_id, reason=args.reason)
        elif args.lifecycle_action == "gc":
            payload = lifecycle.gc(
                retention_ns=max(0, args.retention_seconds) * 1_000_000_000,
                apply=args.apply,
            )
        else:
            raise LifecycleError("unsupported lifecycle action")
    except (LifecycleError, OSError, ValueError) as exc:
        payload = {"schema": "simplicio.loop.checkpoint-lifecycle/v1",
                   "status": "HELD", "error": str(exc)}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def oracle(loop_dir: str, run_dir: str, response_text: str, flow_gap: str,
           write_receipt: bool) -> int:
    """Evaluate the shared completion oracle and its cross-runtime parity."""
    payload = evaluate_matrix(loop_dir, run_dir, response_text=response_text, flow_gap=flow_gap)
    if write_receipt:
        # Persist the canonical verdict once; the matrix is only the parity proof.
        from .oracle import evaluate_completion
        verdict = evaluate_completion(loop_dir, run_dir, response_text=response_text,
                                      flow_gap=flow_gap)
        payload["receipt_path"] = persist_completion_receipt(verdict, loop_dir, run_dir)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("parity") and payload.get("signature", [False])[0] else 1


def progress(repo: str, run_id: str, fmt: str, once: bool, interval: float,
             no_animation: bool = False, ascii_only: bool = False) -> int:
    """Render a run's portable progress event for an LLM, terminal, or dashboard."""
    try:
        status = read_status(repo, run_id)
    except (FileNotFoundError, OSError, ValueError, KeyError) as exc:
        print(json.dumps({"schema": "simplicio.progress/v1", "status": "UNVERIFIED",
                          "reason_code": "run_missing", "error": str(exc)}, ensure_ascii=False))
        return 2
    if not status or not status.get("run_dir"):
        print(json.dumps({"schema": "simplicio.progress/v1", "status": "UNVERIFIED",
                          "reason_code": "run_missing"}, ensure_ascii=False))
        return 2
    stream_progress(status["run_dir"], fmt=fmt, once=once, interval=interval,
                    no_animation=no_animation, ascii_only=ascii_only)
    return 0


def maintenance_deferred(repo: str, run_id: str, mode: str, disposition: str,
                         correction_summary: str, deferral_reason: str,
                         resume_instructions: list[str], evidence_status: str) -> int:
    if mode != "maintenance_deferred" or disposition != "backlog_only":
        print(json.dumps({
            "ready": False,
            "reason_code": "maintenance_mode_invalid",
            "tag": "UNVERIFIED",
        }, ensure_ascii=False, sort_keys=True))
        return 2
    payload = defer_maintenance_backlog_only(
        repo,
        run_id,
        correction_summary=correction_summary,
        deferral_reason=deferral_reason,
        resume_instructions=resume_instructions,
        evidence_status=evidence_status,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def deliver(repo: str, run_id: str, state: str, source_kind: str, payload_file: str) -> int:
    source_payload = {}
    if payload_file:
        source_payload = json.loads(Path(payload_file).read_text(encoding="utf-8"))
    payload = reconcile_delivery(repo, run_id, state, source_kind=source_kind, source_payload=source_payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def decide(repo: str, run_id: str, decision_id: str, answer: str, impact: str) -> int:
    payload = apply_human_decision(repo, run_id, decision_id, answer, impact=impact)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def sync_source(repo: str, run_id: str, source: str, external_repo: str, pr: int, tag: str) -> int:
    payload = sync_source_state(repo, run_id, source, external_repo=external_repo, pr=pr or None, tag=tag)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _drain_cli_failure(reason_code: str, reason: str, **extra) -> dict:
    """Compatibility wrapper for the focused command helpers."""
    return _inspection_cli.drain_cli_failure(DRAIN_SCHEMA, reason_code, reason, **extra)


def _read_drain_snapshot(path: str):
    return _inspection_cli.read_drain_snapshot(path, _drain_cli_failure)


def _valid_drain_result(payload) -> bool:
    return _inspection_cli.valid_drain_result(DRAIN_SCHEMA, payload)


def drain(action: str, snapshot_path: str, receipt_path: str, polls_required: int) -> int:
    """Compatibility wrapper that preserves CLI-level dependency monkeypatches."""
    return _inspection_cli.drain(
        action, snapshot_path, receipt_path, polls_required,
        evaluator=evaluate_drain, persist=persist_drain_receipt, load=load_drain_receipt,
        receipt_error=DrainReceiptError, failure=_drain_cli_failure,
        snapshot_reader=_read_drain_snapshot, result_validator=_valid_drain_result,
    )
def _load_handshake(handshake_json: str, handshake_file: str):
    """Compatibility wrapper that preserves CLI-level validator monkeypatches."""
    return _inspection_cli._load_handshake(
        handshake_json, handshake_file, validator=validate_handshake,
        ledger_error=LedgerError,
    )


def ledger_replay(path: str, compatibility: bool, recover_trailing: bool,
                  handshake_json: str, handshake_file: str, command: str = "replay") -> int:
    """Compatibility wrapper for the focused read-only ledger surface."""
    return _inspection_cli.ledger_replay(
        path, compatibility, recover_trailing, handshake_json, handshake_file,
        command, handshake_loader=_load_handshake, event_ledger=EventLedger,
        ledger_error=LedgerError, context_schema=CONTEXT_SCHEMA,
        handshake_schema=HANDSHAKE_SCHEMA, required_context_fields=REQUIRED_CONTEXT_FIELDS,
    )


def findings_command(args) -> int:
    """Compatibility wrapper for the focused findings command surface."""
    return _inspection_cli.findings_command(args)


def retrospective_command(args) -> int:
    from .retrospective import retrospective
    result = retrospective(args.repo, args.run_id)
    print(json.dumps(result, ensure_ascii=False))
    return 0


def _load_stack_components(path: str):
    from .stack_lock import load_component_observations

    try:
        return load_component_observations(path)
    except (OSError, ValueError) as exc:
        raise ValueError(f"cannot read component observations: {exc}") from exc


def stack_command(args) -> int:
    from .stack_lock import (
        StackLock,
        StackLockError,
        diagnose_stack,
        load_stack_lock,
        load_stack_registry,
        write_stack_lock,
    )

    try:
        if args.stack_command == "lock":
            components = _load_stack_components(args.components)
            registry_path = getattr(args, "registry", "")
            if registry_path:
                diagnosis = diagnose_stack(
                    components,
                    load_stack_registry(registry_path),
                    args.route,
                )
                if diagnosis.status != "READY":
                    print(json.dumps({
                        "schema": "simplicio.stack-lock-command/v1",
                        "status": "BLOCKED",
                        "reason_code": "stack_compatibility_blocked",
                        "diagnostics": diagnosis.to_dict(),
                    }, ensure_ascii=False, sort_keys=True))
                    return 2
            lock = StackLock.create(components, args.route, run_id=args.run_id)
            path = write_stack_lock(lock, args.output)
            result = {
                "schema": "simplicio.stack-lock-command/v1",
                "status": "LOCKED",
                "path": str(path),
                "lock_hash": lock.lock_hash,
                "route": lock.route,
                "run_id": lock.run_id,
            }
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0

        lock = load_stack_lock(args.lock)
        route = args.route or lock.route
        lock.verify_unchanged(_load_stack_components(args.components), route)
        result = {
            "schema": "simplicio.stack-lock-command/v1",
            "status": "VERIFIED",
            "path": str(args.lock),
            "lock_hash": lock.lock_hash,
            "route": route,
            "run_id": lock.run_id,
        }
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, ValueError, StackLockError) as exc:
        print(json.dumps({
            "schema": "simplicio.stack-lock-command/v1",
            "status": "BLOCKED",
            "reason_code": "stack_lock_invalid",
            "error": str(exc),
        }, ensure_ascii=False, sort_keys=True))
        return 2


def stack_doctor_command(args) -> int:
    """Report installed stack identity and route readiness without side effects."""
    from .stack_lock import discover_installed_components

    try:
        components = discover_installed_components()
        by_name = {component.name: component for component in components}
        required = ("simplicio-loop", "simplicio-mapper")
        missing = [name for name in required if not by_name.get(name, None) or not by_name[name].available]
        runtime = by_name.get("simplicio-runtime")
        routes = {
            "standalone": {
                "available": not missing,
                "missing": missing,
            },
            "runtime-backed": {
                "available": not missing and bool(runtime and runtime.available),
                "missing": missing + ([] if runtime and runtime.available else ["simplicio-runtime"]),
            },
        }
        status = "READY" if routes["standalone"]["available"] else "BLOCKED"
        result = {
            "schema": "simplicio.stack-doctor/v1",
            "status": status,
            "components": [component.to_dict() for component in components],
            "routes": routes,
        }
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if status == "READY" else 2
    except (OSError, ValueError) as exc:
        print(json.dumps({
            "schema": "simplicio.stack-doctor/v1",
            "status": "BLOCKED",
            "reason_code": "stack_observation_invalid",
            "error": str(exc),
        }, ensure_ascii=False, sort_keys=True))
        return 2


def source_doctor_command(args) -> int:
    """Report SourceAdapter v1 contract readiness without contacting a provider."""
    from .source_contract import SourceCapabilities

    profiles = {
        "local": "local-reference",
        "github": "github-reference",
        "azure-devops": "azure-devops-fixture",
        "jira-cloud": "jira-cloud-fixture",
        "asana": "asana-fixture",
        "trello": "trello-fixture",
    }
    provider = str(args.source_provider)
    capabilities = SourceCapabilities(provider, profiles[provider])
    result = {
        "schema": "simplicio.source-doctor/v1",
        "status": "READY",
        "provider": provider,
        "profile": capabilities.profile,
        "capabilities": capabilities.as_dict(),
        "transport": "fixture-or-injected",
        "real_provider_auth": "UNVERIFIED",
        "effects_attempted": False,
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


def resource_doctor_command(args) -> int:
    """Inspect a prior Resource Fabric state file without constructing the fabric."""
    path = Path(args.resource_root).expanduser().absolute() / "resource-fabric.json"
    result = {
        "schema": "simplicio.resource-doctor/v1",
        "path": str(path),
        "effects_attempted": False,
    }
    if not path.exists():
        result.update({
            "status": "UNVERIFIED",
            "reason_code": "RESOURCE_FABRIC_NOT_STARTED",
            "next_action": "start ResourceFabric explicitly before admitting work",
        })
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 2
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("schema") != "simplicio.resource-fabric/v1":
            raise ValueError("resource fabric state schema mismatch")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        result.update({"status": "BLOCKED", "reason_code": "RESOURCE_STATE_INVALID", "error": str(exc)})
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 2
    result.update({"status": "OBSERVED", "state": payload})
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


def _redirect_run_to_wave(argv: Sequence[str]) -> int:
    """Redirect deprecated 'run' invocation to the default 'wave' flow."""
    sys.stderr.write(
        "[simplicio-loop] AVISO: O comando 'run' foi descontinuado. "
        "Redirecionando automaticamente para o fluxo padrão 'wave'...\n"
    )
    from .delivery import DELIVERY_ORDER
    parser = argparse.ArgumentParser(
        prog="simplicio-loop run (redirecionado para wave)",
        description="O comando 'run' foi descontinuado e redireciona automaticamente para o fluxo padrão 'wave'.",
    )
    parser.add_argument("run_id", nargs="?", default=None, help="ID do run a ser despachado via wave")
    parser.add_argument("--task", default=None, help="arquivo markdown de tarefa para armar e despachar")
    parser.add_argument("--repo", default=".", help="diretório raiz do repositório")
    parser.add_argument(
        "--delivery", default="verified", choices=DELIVERY_ORDER[1:],
        metavar="{" + ",".join(DELIVERY_ORDER[1:]) + "}",
        help=(
            "requested delivery target, one of: " + ", ".join(DELIVERY_ORDER[1:])
            + " (use 'implemented' for a local-only run)"
        ),
    )
    parser.add_argument("--max-iterations", type=int, default=12, help="limite de iterações")
    parser.add_argument(
        "--provider-worker", choices=("openrouter",), default=None,
        help="autorizar worker OpenRouter",
    )
    parser.add_argument("--task-indices", default="", help="índices de tarefas")
    parser.add_argument("--max-workers", type=int, default=0, help="máximo de workers")
    parser.add_argument("--retry-budget", type=int, default=3, help="orçamento de retentativas")
    parser.add_argument("--batch-size", type=int, default=None, help="tamanho da onda/batch")
    parser.add_argument("--serial", action="store_true", help="execução serial")
    parser.add_argument("--result-file", default="", help="arquivo de resultado JSON")
    parser.add_argument(
        "--quality-provider", default=None,
        help="optional quality provider name (simplicio_loop.quality_providers.<name>)",
    )
    parser.add_argument(
        "--quality-policy", default="strict-default",
        help="policy string forwarded to the quality provider",
    )
    parser.add_argument(
        "--require-handshake-fingerprint", default="",
        help="fail closed unless this exact extension runtime fingerprint still executes",
    )

    args = parser.parse_args(list(argv))

    import simplicio_loop.cli as _cli_facade
    if getattr(_cli_facade, "run", None) is not _ORIGINAL_RUN and getattr(_cli_facade, "run", None) is not None:
        return _cli_facade.run(args.repo, args.task, args.delivery, args.max_iterations)

    repo = args.repo
    run_id = args.run_id
    provider_worker = args.provider_worker or os.environ.get("SIMPLICIO_PROVIDER_WORKER")

    armed = None
    if not run_id and args.task:
        delivery_target = delivery.normalize_delivery_target(args.delivery)
        armed = arm_run(repo, args.task, delivery_target, args.max_iterations)
        manifest = armed.get("manifest") or {}
        run_id = str(manifest.get("run_id") or "")
        if not run_id:
            sys.stderr.write("[simplicio-loop] Erro: Falha ao preparar o run para wave.\n")
            return 2

    if not run_id:
        sys.stderr.write("[simplicio-loop] Erro: 'run' requer --task <arquivo> ou <run_id> para redirecionar para wave.\n")
        return 2

    # A run blocked already at arm time (e.g. mapper/dev-cli preflight below the
    # required version) has no plan/dispatch receipt for `batch` to consume -- skip
    # straight to the same public run-outcome contract the pre-redirect `run` command
    # gave for this case instead of falling through into a dispatch failure.
    armed_blocked = armed is not None and str((armed.get("state") or {}).get("phase") or "") == "blocked"
    if not armed_blocked:
        batch_args = [repo, run_id, args.task_indices, args.max_workers, args.retry_budget, args.serial, args.batch_size]
        if provider_worker:
            batch_args.append(provider_worker)
        # `batch()` prints its own dispatch-shaped diagnostic and returns a coarse
        # 0/2 exit code; the pre-redirect `run` command's contract is the finer
        # Completion-Oracle-derived `simplicio.run-outcome/v1` exit code (0/20-24)
        # over the *current run state after dispatch*, printed as one single JSON
        # document -- reconstruct that from the persisted run, not from batch()'s
        # own stdout, which is suppressed here.
        with contextlib.redirect_stdout(io.StringIO()):
            batch(*batch_args, flow="wave")

    if armed_blocked:
        status = armed
    else:
        try:
            status = read_status(repo, run_id)
        except Exception:
            status = armed or {"manifest": {"run_id": run_id}, "state": {}, "run_dir": ""}
    from .run_outcome import persist_run_outcome
    outcome = persist_run_outcome(status)
    public_payload = _public_flow_from_status(status, "run", status)
    if args.result_file:
        target = Path(args.result_file)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(outcome, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(public_payload, ensure_ascii=False, indent=2))
    if public_payload.get("status") == "VERIFIED" and public_payload.get("verified") is True:
        return 0
    return int(outcome["exit_code"]) if int(outcome.get("exit_code") or 0) != 0 else 2


def main(argv=None) -> int:
    argv_list = list(argv) if argv is not None else list(sys.argv[1:])
    if argv_list[:1] == ["fast-v3"]:
        from .fast_v3_cli import main as fast_v3_main
        return fast_v3_main(argv_list[1:])
    if argv_list[:1] == ["hub-drain-admit"]:
        from .hub_drain_admission_cli import main as drain_admission_main
        return drain_admission_main(argv_list[1:])
    if argv_list[:1] == ["hub-drain-plan"]:
        from .github_drain_intake_cli import main as drain_intake_main
        forwarded = argv_list[1:]
        return drain_intake_main(forwarded[1:] if forwarded[:1] == ["--"] else forwarded)
    if argv_list[:1] == ["tasks"]:
        from .tasks_cli import main as tasks_main
        return tasks_main(argv_list[1:])
    if argv_list[:1] == ["run"]:
        return _redirect_run_to_wave(argv_list[1:])
    parser = argparse.ArgumentParser(
        prog="simplicio-loop",
        description=(
            "Install the simplicio-loop super-plugin, open the Token Monitor dashboard, "
            "or compile task markdown into a canonical task contract."
        ),
    )
    parser.add_argument("-V", "--version", action="version", version=f"simplicio-loop {__version__}")
    # Bare `simplicio-loop` (no subcommand at all) falls through to `install` below with these
    # defaults — mirror p_install's own defaults here so that fallback doesn't crash with
    # AttributeError when no subparser ever ran to populate args.target/args.globally.
    parser.set_defaults(target=".", globally=False)
    sub = parser.add_subparsers(dest="command")

    p_install = sub.add_parser("install", help="install bundled skills + hooks into a runtime")
    p_install.add_argument("--target", default=".", help="project directory to install into")
    p_install.add_argument("--global", dest="globally", action="store_true",
                           help="install into ~/.claude instead of the project")
    p_install.add_argument("--host", default="claude", help="host id or 'all'")
    p_install.add_argument("--dry-run", action="store_true", help="plan only; write nothing")
    p_install.add_argument("--verify", action="store_true", help="validate plan version/digest")
    p_install.add_argument("--uninstall", action="store_true", help="remove Loop-owned files only")

    p_dashboard = sub.add_parser("dashboard", help="open or stop the Token Monitor dashboard")
    p_dashboard.add_argument("--port", type=int, default=DEFAULT_DASH_PORT,
                             help="dashboard port (default: %(default)s)")
    p_dashboard.add_argument("--no-browser", dest="no_browser", action="store_true",
                             help="start the server but do not open a browser")
    p_dashboard.add_argument("--stop", action="store_true", help="stop a running Token Monitor")

    p_task = sub.add_parser("task", help="compile, validate, or preview markdown task contracts")
    p_task.add_argument("task_args", nargs=argparse.REMAINDER,
                        help="pass-through args for `simplicio-loop task`")

    p_prototype = sub.add_parser(
        "prototype", help="Prototype-First gate: plan/classify/validate-schema/doctor (#568 P0)"
    )
    p_prototype.add_argument("prototype_args", nargs=argparse.REMAINDER,
                             help="pass-through args for `simplicio-loop prototype`")

    p_plan = sub.add_parser("plan", help="compile a raw task into a contract and preview it")
    p_plan.add_argument("--task", required=True, help="markdown task file")
    p_plan.add_argument("--out", default=os.path.join(".simplicio/orchestrator", "task-contract.json"),
                        help="where to write the compiled contract")

    p_prepare = sub.add_parser(
        "prepare", aliases=["arm"],
        help="arm and preflight a run without executing tasks or calling a provider",
    )
    p_prepare.add_argument("--task", required=True, help="markdown task file")
    p_prepare.add_argument("--repo", default=".", help="repository root")
    p_prepare.add_argument(
        "--delivery", default="verified", choices=DELIVERY_ORDER[1:],
        metavar="{" + ",".join(DELIVERY_ORDER[1:]) + "}",
        help="requested delivery target",
    )
    p_prepare.add_argument("--max-iterations", type=int, default=12, help="safety cap")

    p_orient = sub.add_parser("orient", help="orient a task through Fast with Mapper fallback")
    p_orient.add_argument("--repo", default=".", help="repository root")
    p_orient.add_argument("--task", required=True, help="task text or issue objective")
    p_orient.add_argument("--fast", choices=("auto", "on", "off"), default="auto",
                          help="Fast policy: auto fallback, on fail-closed, or off")
    p_orient.add_argument("--fast-context-budget", type=int, default=48000,
                          help="bounded Fast context bytes (default: 48000)")
    p_orient.add_argument("--fast-engine", choices=("auto", "rust", "python", "off"), default="auto",
                          help="Fast engine: Rust-first auto, explicit rust/python, or off")
    p_orient.add_argument("--tee", action="store_true", help="persist full JSON output in the reversible tee cache")
    p_orient.add_argument(
        "--target", dest="targets", action="append", default=[],
        help="repo-relative source file selected by Mapper or the task (repeatable)",
    )
    p_orient.add_argument(
        "--verbose", action="store_true",
        help="include full receipts/probes/policy text (default: leads with bounded context only)",
    )
    p_orient.add_argument(
        "--json", action="store_true",
        help="no-op: orient always emits exactly one JSON document on stdout",
    )

    p_retrieve = sub.add_parser("retrieve", help="retrieve and verify a tee-cache output")
    p_retrieve.add_argument("path")
    p_retrieve.add_argument("--repo", default=".")

    p_extensions = sub.add_parser("extensions", help="negotiate installed Loop extension runtimes")
    extensions_sub = p_extensions.add_subparsers(dest="extensions_command", required=True)
    p_ext_doctor = extensions_sub.add_parser("doctor", help="dry-run an exact provider/runtime handshake")
    p_ext_doctor.add_argument("--provider", required=True)
    p_ext_doctor.add_argument("--policy", default="strict-default")
    p_ext_doctor.add_argument("--schema", default="simplicio.extension-handshake/v1")
    p_ext_doctor.add_argument("--json", action="store_true", help="machine-readable output (always JSON)")

    p_oracle = sub.add_parser("oracle", help="evaluate completion and cross-runtime parity")
    p_oracle.add_argument("--loop-dir", default=os.path.join(".simplicio/orchestrator", "loop"))
    p_oracle.add_argument("--run-dir", default=os.environ.get("SIMPLICIO_RUN_DIR", ""))
    p_oracle.add_argument("--response-text", default="")
    p_oracle.add_argument("--flow-gap", default="")
    p_oracle.add_argument("--write-receipt", action="store_true")

    p_status = sub.add_parser("status", help="show the latest run state or a specific run")
    p_status.add_argument("--repo", default=".", help="repository root")
    p_status.add_argument("--run-id", default="", help="run id to inspect")
    p_status.add_argument("--json", action="store_true",
                          help="emit machine-readable JSON (this is also the default)")
    p_status.add_argument("--text", dest="as_text", action="store_true",
                          help="emit human-readable text instead of JSON")

    p_stack = sub.add_parser("stack", help="create or verify an installed-stack lock")
    stack_sub = p_stack.add_subparsers(dest="stack_command", required=True)
    p_stack_lock = stack_sub.add_parser(
        "lock", help="persist a deterministic lock from JSON component observations"
    )
    p_stack_lock.add_argument("--components", required=True, help="JSON component observations")
    p_stack_lock.add_argument(
        "--registry",
        default="",
        help="optional simplicio.stack-registry/v1 compatibility registry; blocks incompatible locks",
    )
    p_stack_lock.add_argument("--route", choices=("standalone", "runtime-backed"), required=True)
    p_stack_lock.add_argument("--run-id", default="")
    p_stack_lock.add_argument(
        "--output", default=os.path.join(".simplicio", "orchestrator", "stack-lock.json")
    )
    p_stack_verify = stack_sub.add_parser(
        "verify", help="verify current observations against a persisted lock"
    )
    p_stack_verify.add_argument("--lock", required=True, help="persisted stack lock JSON")
    p_stack_verify.add_argument("--components", required=True, help="JSON component observations")
    p_stack_verify.add_argument("--route", choices=("standalone", "runtime-backed"), default=None)

    p_doctor = sub.add_parser("doctor", help="inspect the installed stack or storage routing")
    p_doctor.set_defaults(doctor_command=None, stack_json=False, doctor_json=False)
    p_doctor.add_argument("--storage", action="store_true",
                          help="inspect the Loop storage adapter boundary")
    p_doctor.add_argument("--route", choices=("legacy", "shadow", "mapper"), default="mapper")
    p_doctor.add_argument("--data-dir", default=None)
    p_doctor.add_argument("--repo", default=".", help="repository root for cutover diagnostics")
    p_doctor.add_argument("--require-capability", action="append", default=[])
    p_doctor.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    doctor_sub = p_doctor.add_subparsers(dest="doctor_command")
    p_doctor_stack = doctor_sub.add_parser(
        "stack", help="report installed component identity and route readiness"
    )
    p_doctor_stack.add_argument("--json", dest="stack_json", action="store_true",
                                help="emit machine-readable JSON")
    p_doctor_source = doctor_sub.add_parser(
        "source", help="report SourceAdapter v1 contract readiness"
    )
    p_doctor_source.add_argument(
        "--provider",
        dest="source_provider",
        choices=("local", "github", "azure-devops", "jira-cloud", "asana", "trello"),
        default="local",
    )
    p_doctor_source.add_argument("--json", dest="doctor_json", action="store_true",
                                 help="emit machine-readable JSON")
    p_doctor_resource = doctor_sub.add_parser(
        "resource", help="inspect Resource Fabric state without starting it"
    )
    p_doctor_resource.add_argument(
        "--root", dest="resource_root",
        default=os.path.join(".simplicio", "orchestrator", "resource-fabric"),
    )
    p_doctor_resource.add_argument("--json", dest="doctor_json", action="store_true",
                                   help="emit machine-readable JSON")

    p_inspect = sub.add_parser("inspect", help="inspect storage routing and MapperStore capabilities")
    p_inspect.add_argument("--storage", action="store_true", required=True,
                           help="inspect the Loop storage adapter boundary")
    p_inspect.add_argument("--route", choices=("legacy", "shadow", "mapper"), default="mapper")
    p_inspect.add_argument("--data-dir", default=None)
    p_inspect.add_argument("--repo", default=".", help="repository root for cutover diagnostics")
    p_inspect.add_argument("--require-capability", action="append", default=[])
    p_inspect.add_argument("--json", action="store_true", help="emit machine-readable JSON")

    p_map = sub.add_parser("map", help="map-service cross-module status")
    map_sub = p_map.add_subparsers(dest="map_command", required=True)
    configure_map_commands(map_sub)

    p_preflight = sub.add_parser(
        "preflight", help="verify bound operators (mapper/dev-cli/runtime/fast) are installed")
    p_preflight.add_argument("--repo", default=".", help="repository root")
    p_preflight.add_argument("--json", action="store_true",
                             help="emit machine-readable JSON (default: human-readable text)")
    p_preflight.add_argument(
        "--strict",
        action="store_true",
        help="arm SIMPLICIO_LOOP_STRICT: require operational Runtime/Fast when present, "
             "forbid hand-edit, lock evidence/mutation authority",
    )

    p_economy = sub.add_parser(
        "economy",
        help="fastest + cheapest profile: token economy, bounded CPU/RAM, Prism/asyncio parallel",
    )
    economy_sub = p_economy.add_subparsers(dest="economy_command", required=True)
    p_economy_status = economy_sub.add_parser(
        "status", help="show recommended vs applied economy-parallel env"
    )
    p_economy_status.add_argument("--json", action="store_true")
    p_economy_print = economy_sub.add_parser(
        "print", help="print shell exports (ps1 on Windows, sh elsewhere)"
    )
    p_economy_print.add_argument(
        "--shell", choices=("auto", "ps1", "sh"), default="auto"
    )
    p_economy_print.add_argument("--json", action="store_true")
    p_economy_apply = economy_sub.add_parser(
        "apply",
        help="apply profile to this process + ~/.simplicio + Windows User env",
    )
    p_economy_apply.add_argument(
        "--user",
        action="store_true",
        default=True,
        help="persist to Windows User env / shell files (default)",
    )
    p_economy_apply.add_argument(
        "--no-user",
        action="store_true",
        help="only mutate the current process environ",
    )
    p_economy_apply.add_argument("--json", action="store_true")

    p_ecc = sub.add_parser("ecc", help="inspect the opt-in ECC advisory integration")
    ecc_sub = p_ecc.add_subparsers(dest="ecc_command", required=True)
    p_ecc_doctor = ecc_sub.add_parser("doctor", help="verify ECC provenance and safety policy")
    p_ecc_doctor.add_argument("--repo", default=".", help="repository root")
    p_ecc_doctor.add_argument("--json", action="store_true", help="emit machine-readable JSON")

    p_deploy = sub.add_parser(
        "deploy", help="plan a gated serverless deployment (dry-run unless --apply is explicit)"
    )
    p_deploy.add_argument("--repo", default=".")
    p_deploy.add_argument("--backend", choices=("modal", "daytona"), default="modal")
    p_deploy.add_argument("--environment", default="")
    p_deploy.add_argument("--image", default="")
    p_deploy.add_argument("--apply", action="store_true")
    p_deploy.add_argument("--action-gate", action="store_true")

    p_verify = sub.add_parser("verify", help="run the independent watcher and delivery gates")
    p_verify.add_argument("--repo", default=".", help="repository root")
    p_verify.add_argument("run_id", help="run id to verify")

    p_progress = sub.add_parser("progress", help="render visual progress for a run")
    p_progress.add_argument("--repo", default=".", help="repository root")
    p_progress.add_argument("run_id", nargs="?", help="run id to render (legacy positional form)")
    p_progress.add_argument("--run", dest="run_flag", default="",
                            help="run id to render (explicit form)")
    p_progress.add_argument("--format", choices=("text", "json", "markdown", "ansi"),
                            default="text", dest="fmt", help="output format")
    p_progress.add_argument("--once", action="store_true", help="render one snapshot")
    p_progress.add_argument("--no-animation", action="store_true",
                            help="emit one static snapshot without spinner/ANSI control codes")
    p_progress.add_argument("--ascii", action="store_true", dest="ascii_only",
                            help="use ASCII icons/bar for terminals without Unicode support")
    p_progress.add_argument("--interval", type=float, default=0.25,
                            help="animation polling interval in seconds")

    p_resume = sub.add_parser("resume", help="resume a non-terminal run")
    p_resume.add_argument("--repo", default=".", help="repository root")
    p_resume.add_argument("run_id", help="run id to resume")

    p_tick = sub.add_parser("tick", help="execute one planned task through simplicio-dev-cli")
    p_tick.add_argument("--repo", default=".", help="repository root")
    p_tick.add_argument("run_id", help="run id to tick")
    p_tick.add_argument("--task-index", type=int, default=1, help="1-based task index")
    p_tick.add_argument(
        "--provider-worker", choices=("openrouter",), default=None,
        help="explicitly authorize the external OpenRouter proposal worker",
    )

    def _configure_batch_parser(parser):
        parser.add_argument("--repo", default=".", help="repository root")
        parser.add_argument("run_id", help="run id to dispatch")
        parser.add_argument(
            "--task-indices",
            default="",
            help="comma-separated 1-based task indices (default: every task in the contract)",
        )
        parser.add_argument(
            "--max-workers",
            type=int,
            default=0,
            help="worker demand (default/0: automatic; live CPU/RAM/disk admission governs concurrency; positive values set an explicit ceiling)",
        )
        parser.add_argument("--retry-budget", type=int, default=3, help="retries after the first attempt")
        parser.add_argument(
            "--provider-worker", choices=("openrouter",), default=None,
            help="explicitly authorize the external OpenRouter proposal worker",
        )
        parser.add_argument(
            "--batch-size", type=int, default=None,
            help="Prism wave width (default/minimum: 10; no logical upper bound, e.g. 30)",
        )
        parser.add_argument(
            "--serial", action="store_true",
            help="disable the default isolated fan-out and force the shared-run serial lane",
        )

    p_batch = sub.add_parser("batch", help="continuously dispatch ready tasks through simplicio-dev-cli")
    _configure_batch_parser(p_batch)
    p_wave = sub.add_parser("wave", help="dispatch a governed wave with reconciliation barriers")
    _configure_batch_parser(p_wave)
    p_prism = sub.add_parser("prism", help="dispatch work through the governed Prism route")
    _configure_batch_parser(p_prism)

    p_cancel = sub.add_parser("cancel", help="cancel a non-terminal run")
    p_cancel.add_argument("--repo", default=".", help="repository root")
    p_cancel.add_argument("run_id", help="run id to cancel")

    p_checkpoint = sub.add_parser(
        "checkpoint", help="inspect, cancel, or garbage-collect Fast V3 checkpoints")
    p_checkpoint.add_argument("lifecycle_action", choices=("inspect", "cancel", "gc"))
    p_checkpoint.add_argument("--repo", default=".")
    p_checkpoint.add_argument("--task-id", required=True)
    p_checkpoint.add_argument("--attempt-id", required=True)
    p_checkpoint.add_argument("--source-commit", required=True)
    p_checkpoint.add_argument("--fast-generation", required=True)
    p_checkpoint.add_argument("--base-path", default="")
    p_checkpoint.add_argument("--candidate-id", action="append", default=[])
    p_checkpoint.add_argument("--shard-id", default="candidate")
    p_checkpoint.add_argument("--reason", default="operator_cancelled")
    p_checkpoint.add_argument("--retention-seconds", type=int, default=86400)
    p_checkpoint.add_argument("--apply", action="store_true")

    p_maintenance = sub.add_parser(
        "maintenance-deferred",
        aliases=["defer-maintenance"],
        help="record a maintenance-deferred backlog-only transition",
    )
    p_maintenance.add_argument("--repo", default=".", help="repository root")
    p_maintenance.add_argument("run_id", help="run id to update")
    p_maintenance.add_argument(
        "--mode", choices=("active", "maintenance_deferred"), required=True,
        help="explicit runner mode",
    )
    p_maintenance.add_argument(
        "--disposition", choices=("operator", "backlog_only"), required=True,
        help="explicit runner disposition",
    )
    p_maintenance.add_argument("--correction-summary", required=True)
    p_maintenance.add_argument("--deferral-reason", required=True)
    p_maintenance.add_argument("--resume-instruction", action="append", default=[])
    p_maintenance.add_argument("--evidence-status", default="UNVERIFIED")

    p_deliver = sub.add_parser("deliver", help="reconcile delivery state against local/external source evidence")
    p_deliver.add_argument("--repo", default=".", help="repository root")
    p_deliver.add_argument("run_id", help="run id to reconcile")
    p_deliver.add_argument("--state", required=True, help="delivery state reached")
    p_deliver.add_argument("--source-kind", default="local", help="source kind for this reconciliation")
    p_deliver.add_argument("--payload-file", default="", help="JSON file with source evidence payload")

    p_decide = sub.add_parser("decide", help="apply a human decision and invalidate dependent artifacts")
    p_decide.add_argument("--repo", default=".", help="repository root")
    p_decide.add_argument("run_id", help="run id to update")
    p_decide.add_argument("--decision-id", required=True, help="decision/question identifier")
    p_decide.add_argument("--answer", required=True, help="human answer")
    p_decide.add_argument("--impact", default="behavior-change", help="impact classification")

    p_sync = sub.add_parser("sync-source", help="requery external source state and reconcile delivery")
    p_sync.add_argument("--repo", default=".", help="repository root")
    p_sync.add_argument("run_id", help="run id to update")
    p_sync.add_argument("--source", required=True, help="external source kind")
    p_sync.add_argument("--external-repo", default="", help="external repo identifier, ex owner/name")
    p_sync.add_argument("--pr", type=int, default=0, help="pull request number")
    p_sync.add_argument("--tag", default="", help="release tag")

    p_drain = sub.add_parser("drain", help="evaluate, persist, or load a queue-drain receipt")
    p_drain.add_argument("action", nargs="?", default="",
                          help="operation to perform: evaluate, persist, or load")
    p_drain.add_argument("--snapshot", "--snapshot-file", dest="snapshot_path", default="",
                         help="JSON scheduler/source snapshot (evaluate and persist)")
    p_drain.add_argument("--receipt", "--receipt-file", dest="receipt_path", default="",
                         help="receipt JSON path (persist and load)")
    p_drain.add_argument("--polls-required", type=int, default=2,
                         help="identical empty polls required (default: %(default)s)")
    p_slots = sub.add_parser("agent-slots", help="inspect and reclaim Loop-owned agent capacity")
    p_slots.add_argument("slot_args", nargs=argparse.REMAINDER,
                         help="pass-through args for the JSON-first agent slot registry")
    p_generation_broker = sub.add_parser(
        "generation-broker", help="operate persisted generation bindings")
    p_generation_broker.add_argument("broker_args", nargs=argparse.REMAINDER)
    p_queue = sub.add_parser("queue", help="operate the durable local task queue")
    p_queue.add_argument("--repo", default=".")
    p_queue.add_argument(
        "--route", choices=("legacy", "mapper"), default="mapper",
        help="storage route (default: mapper; use legacy only for compatibility actions)",
    )
    p_queue.add_argument("--mapper-db", default=None)
    p_queue.add_argument("--mapper-init", action="store_true")
    queue_sub = p_queue.add_subparsers(dest="queue_action", required=True)
    queue_help = {
        "status": "show queue health and pending work",
        "resume": "resume a legacy queue task",
        "doctor": "check queue storage and MapperStore readiness",
        "reclaim": "reclaim abandoned queue work",
    }
    for queue_action in ("status", "resume", "doctor", "reclaim"):
        queue_sub.add_parser(queue_action, help=queue_help[queue_action])
    queue_migrate = queue_sub.add_parser("migrate", help="migrate legacy queue state into MapperStore")
    queue_migrate.add_argument("--apply", action="store_true")
    queue_top = queue_sub.add_parser("top", help="list the highest-priority ready queue tasks")
    queue_top.add_argument("--limit", type=int, default=20)
    queue_drain = queue_sub.add_parser("drain", help="wait for active queue work to finish")
    queue_drain.add_argument("--timeout", type=float, default=0.0)
    queue_gc = queue_sub.add_parser("gc", help="garbage-collect retained queue state")
    queue_gc.add_argument("--apply", action="store_true")
    for queue_action in ("inspect", "cancel"):
        queue_help_text = {
            "inspect": "inspect one task by id",
            "cancel": "cancel one task by id",
        }
        queue_command = queue_sub.add_parser(queue_action, help=queue_help_text[queue_action])
        queue_command.add_argument("task_id")
    p_single_fast = sub.add_parser(
        "single-task-fast",
        help=("execute one bounded JSON task locally, or exactly two dependent "
              "Markdown tasks through the provider-backed Loop route"),
        description=("One JSON task uses the local-first Mapper/Fast/Dev CLI route. "
                     "Exactly two dependent Markdown tasks use required Fast preparation "
                     "and the ordered Loop provider route (configured provider worker; "
                     "default: openrouter)."),
    )
    p_single_fast.add_argument(
        "--task-file", required=True,
        help="JSON task for local-first execution, or a two-task Markdown collection",
    )
    p_single_fast.add_argument("--repo", default=".", help="repository root for the two-task provider route")
    sub.add_parser(
        "hub-drain-plan",
        help="read-only PT-BR/EN GitHub drain intake; never executes the plan",
    )
    sub.add_parser(
        "hub-drain-admit",
        help="admit a final #627 checkpoint as held; never dispatches or executes it",
    )
    p_ledger = sub.add_parser("ledger", help="validate/replay the operational event ledger")
    p_findings = sub.add_parser("findings", help="WI-466: inspect and reconcile continuous findings")
    findings_sub = p_findings.add_subparsers(dest="findings_command", required=True)
    p_f_list = findings_sub.add_parser("list", help="list all routed findings (JSONL)")
    p_f_list.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    p_f_report = findings_sub.add_parser("report", help="show aggregated finding counts by stage/severity")
    p_f_report.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    p_f_reconcile = findings_sub.add_parser("reconcile", help="show dedup state and untracked findings")
    p_f_reconcile.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    p_f_doctor = findings_sub.add_parser("doctor", help="health-check the findings store and router state")
    p_f_doctor.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    p_f_import = findings_sub.add_parser("import", help="create one GitHub issue for each JSON finding")
    p_f_import.add_argument("path", help="JSON array of findings or object with findings array")
    p_f_import.add_argument("--repo-map", default="", help="JSON map from source parent to owner/repo")
    p_f_import.add_argument("--label", action="append", default=[], help="label to add to each issue (repeatable)")
    p_f_import.add_argument("--dry-run", action="store_true", help="resolve repositories without creating issues")
    p_f_import.add_argument("--receipt", default="", help="persistent batch receipt path for safe retries")
    p_learn = sub.add_parser("learn", help="derive durable lessons from completed runs")
    learn_sub = p_learn.add_subparsers(dest="learn_command", required=True)
    p_ret = learn_sub.add_parser("retrospective", help="deduplicate trajectory lessons and write a receipt")
    p_ret.add_argument("--repo", default=".")
    p_ret.add_argument("--run", dest="run_id", default=None)
    ledger_sub = p_ledger.add_subparsers(dest="ledger_command", required=True)
    for ledger_command in ("replay", "validate"):
        p_ledger_action = ledger_sub.add_parser(
            ledger_command,
            help="%s events with hash-chain and context validation" % ledger_command,
        )
        p_ledger_action.add_argument("--path", required=True, help="JSONL EventLedger path")
        p_ledger_action.add_argument(
            "--compatibility",
            action="store_true",
            help="explicitly allow legacy v1 rows without context/handshake",
        )
        p_ledger_action.add_argument(
            "--recover-trailing",
            action="store_true",
            help="drop one corrupt trailing JSONL row under the ledger lock",
        )
        handshake = p_ledger_action.add_mutually_exclusive_group()
        handshake.add_argument(
            "--handshake-json",
            default="",
            help="inline executor handshake JSON (strict mode requires it)",
        )
        handshake.add_argument(
            "--handshake-file",
            default="",
            help="file containing executor handshake JSON (strict mode requires it)",
        )

    p_release_train = sub.add_parser(
        "release-train", help="release train continuous verification (#558)"
    )
    rt_sub = p_release_train.add_subparsers(
        dest="release_train_command", required=True
    )
    p_rt_check = rt_sub.add_parser(
        "check", help="validate component/ecosystem release schemas + local drift"
    )
    p_rt_check.add_argument("--repo", default=".", help="repository root")
    if _release_train is not None:
        # The check command remains owned by release_manifest for backwards compatibility;
        # composition/promotion/rollback are the effect-gated #558 release-train operations.
        _release_train.configure_subparsers(rt_sub)

    if argv_list:
        from .github_drain_intake_cli import looks_like_natural_request, main as drain_intake_main
        if looks_like_natural_request(argv_list) and (
            argv_list[0] not in sub.choices or argv_list[0].lower() == "drain"
        ):
            return drain_intake_main(argv_list)
    args = parser.parse_args(argv_list)
    command = args.command or "install"
    if command == "dashboard":
        return dashboard(args.port, not args.no_browser, args.stop)
    if command == "task":
        forwarded = list(args.task_args or [])
        if forwarded and forwarded[0] == "--":
            forwarded = forwarded[1:]
        return task_contract_main(forwarded)
    if command == "prototype":
        if _prototype_cli is None:
            parser.error("prototype_cli module not importable")
        forwarded = list(args.prototype_args or [])
        if forwarded and forwarded[0] == "--":
            forwarded = forwarded[1:]
        return _prototype_cli.main(forwarded)
    if command == "plan":
        return plan(args.task, args.out)
    if command in {"prepare", "arm"}:
        return prepare(args.repo, args.task, args.delivery, args.max_iterations)
    if command == "orient":
        return orient(args.repo, args.task, args.fast, args.fast_context_budget, args.fast_engine, args.tee,
                      args.targets, args.verbose)
    if command == "retrieve":
        from .tee_cache import retrieve
        try:
            print(retrieve(args.path, args.repo), end="")
            return 0
        except (OSError, ValueError) as exc:
            print(json.dumps({"status": "BLOCKED", "reason": str(exc)}))
            return 2
    if command == "extensions":
        return extensions_doctor(args.provider, args.policy, args.schema)
    if command == "oracle":
        return oracle(args.loop_dir, args.run_dir, args.response_text, args.flow_gap,
                      args.write_receipt)
    if command == "status":
        return status(args.repo, args.run_id, args.json, args.as_text)
    if command == "stack":
        return stack_command(args)
    if command == "doctor" and getattr(args, "doctor_command", None) == "stack":
        return stack_doctor_command(args)
    if command == "doctor" and getattr(args, "doctor_command", None) == "source":
        return source_doctor_command(args)
    if command == "doctor" and getattr(args, "doctor_command", None) == "resource":
        return resource_doctor_command(args)
    if command in {"doctor", "inspect"}:
        if command == "doctor" and not args.storage:
            parser.error("doctor requires --storage or the stack subcommand")
        from .store_adapter import storage_cli
        forwarded = ["--route", args.route]
        if args.data_dir:
            forwarded += ["--data-dir", args.data_dir]
        if getattr(args, "repo", None):
            forwarded += ["--repo", args.repo]
        for capability in args.require_capability:
            forwarded += ["--require-capability", capability]
        return storage_cli(forwarded)
    if command == "map":
        return dispatch_map(args)
    if command == "preflight":
        return preflight(args.repo, args.json, strict=bool(getattr(args, "strict", False)))
    if command == "ecc":
        from .ecc_guidance import doctor_command
        return doctor_command(args.repo, as_json=bool(args.json))
    if command == "deploy":
        try:
            deploy_plan = build_serverless_plan(args.repo, backend=args.backend,
                                                environment=args.environment, image=args.image)
            result = execute_serverless_plan(deploy_plan, apply=args.apply,
                                             action_gate=args.action_gate)
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0 if not args.apply or result.get("status") == "PLAN_READY" else 2
        except (ValueError, RuntimeError) as exc:
            print(json.dumps({"schema": "simplicio.loop-serverless-deploy/v1",
                              "status": "BLOCKED", "reason_code": type(exc).__name__,
                              "error": str(exc), "effects_attempted": False}, sort_keys=True))
            return 2
    if command == "findings":
        return findings_command(args)
    if command == "learn":
        if args.learn_command == "retrospective":
            return retrospective_command(args)
        parser.error("unknown learn command")
    if command == "economy":
        return economy_command(args)
    if command == "verify":
        return verify(args.repo, args.run_id)
    if command == "progress":
        run_id = args.run_id or args.run_flag
        # An omitted run id means the latest run in --repo, matching the
        # status command and keeping the public zero-config progress command
        # useful immediately after `run`.
        return progress(args.repo, run_id, args.fmt, args.once, args.interval,
                        args.no_animation, args.ascii_only)
    if command == "resume":
        return resume(args.repo, args.run_id)
    if command == "tick":
        return tick(args.repo, args.run_id, args.task_index, args.provider_worker)
    if command == "batch":
        batch_args = [args.repo, args.run_id, args.task_indices, args.max_workers,
                      args.retry_budget, args.serial, args.batch_size]
        if args.provider_worker is not None:
            batch_args.append(args.provider_worker)
        return batch(*batch_args)
    if command in {"wave", "prism"}:
        batch_args = [args.repo, args.run_id, args.task_indices, args.max_workers,
                      args.retry_budget, args.serial, args.batch_size]
        if args.provider_worker is not None:
            batch_args.append(args.provider_worker)
        return batch(*batch_args, flow=command)
    if command == "cancel":
        return cancel(args.repo, args.run_id)
    if command == "checkpoint":
        if args.lifecycle_action == "inspect":
            if len(args.candidate_id) != 1:
                parser.error("checkpoint inspect requires exactly one --candidate-id")
            args.candidate_id = args.candidate_id[0]
        return checkpoint_lifecycle(args)
    if command in {"maintenance-deferred", "defer-maintenance"}:
        return maintenance_deferred(
            args.repo, args.run_id, args.mode, args.disposition,
            args.correction_summary, args.deferral_reason,
            args.resume_instruction, args.evidence_status,
        )
    if command == "deliver":
        return deliver(args.repo, args.run_id, args.state, args.source_kind, args.payload_file)
    if command == "decide":
        return decide(args.repo, args.run_id, args.decision_id, args.answer, args.impact)
    if command == "sync-source":
        return sync_source(args.repo, args.run_id, args.source, args.external_repo, args.pr, args.tag)
    if command == "drain":
        return drain(args.action, args.snapshot_path, args.receipt_path, args.polls_required)
    if command == "agent-slots":
        from .agent_slots import cli_main as agent_slots_main
        forwarded = list(args.slot_args or [])
        if forwarded and forwarded[0] == "--":
            forwarded = forwarded[1:]
        return agent_slots_main(forwarded)
    if command == "generation-broker":
        from .generation_broker_cli import cli_main as generation_broker_main
        return generation_broker_main(list(args.broker_args or []))
    if command == "queue":
        from .local_task_queue_cli import cli_main as local_queue_main
        forwarded = ["--repo", args.repo, "--route", args.route]
        if args.mapper_db:
            forwarded += ["--mapper-db", args.mapper_db]
        if args.mapper_init:
            forwarded.append("--mapper-init")
        forwarded.append(args.queue_action)
        if args.queue_action == "top":
            forwarded += ["--limit", str(args.limit)]
        elif args.queue_action == "drain":
            forwarded += ["--timeout", str(args.timeout)]
        elif args.queue_action in {"gc", "migrate"} and args.apply:
            forwarded.append("--apply")
        elif args.queue_action in {"inspect", "cancel"}:
            forwarded.append(args.task_id)
        return local_queue_main(forwarded)
    if command == "single-task-fast":
        task_file = Path(args.task_file)
        try:
            task_path = Path(args.task_file)
            raw = task_path.read_text(encoding="utf-8")
            task_file_for_collection = ""
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                if task_path.suffix.lower() not in {".md", ".markdown"}:
                    raise
                compiled = compile_many(raw, source_path=str(task_path.resolve()))
                tasks = list(compiled.get("tasks") or [])
                task_file_for_collection = str(task_path)
            else:
                is_collection = (
                    isinstance(payload, Mapping)
                    and str(payload.get("schema") or "") == "simplicio.task-contract/v1.collection"
                    and isinstance(payload.get("tasks"), list)
                )
                if is_collection:
                    tasks = list(payload["tasks"])
                else:
                    tasks = payload if isinstance(payload, list) else [payload]
                if len(tasks) == 2 and is_collection:
                    task_file_for_collection = str(task_path)
            first_task = tasks[0] if tasks and isinstance(tasks[0], Mapping) else {}
            governor = expected_governor_blocked({"task": first_task})
            if governor is not None:
                result = {
                    "schema": "simplicio.single-task-fast-receipt/v1",
                    "status": "BLOCKED",
                    "reason_code": governor["reason_code"],
                    "governor": governor,
                    "route": "single-task-fast",
                }
                repo = str(first_task.get("repo") or task_path.parent)
                persist_execution_envelope(
                    flow="single-task-fast",
                    repo=repo,
                    observed={"task": first_task, "tasks": tasks, "result": result, "governor": governor},
                )
                print(json.dumps(result, sort_keys=True))
                return 2
            result = dispatch_single_task_fast(
                tasks, task_file=task_file_for_collection, repo=args.repo,
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            diagnostic = publish_loop_execution_for_flow(
                repo=Path("."),
                run_dir=Path(".") / ".simplicio" / "loop-runs" / "single-task-fast-invalid",
                flow="single-task-fast",
                flow_result={"status": "blocked"},
            )
            diagnostic.update({"reason_code": "invalid_task_file", "error": redact_sensitive_text(str(exc))})
            persist_execution_envelope(flow="single-task-fast", repo=".", observed={"result": diagnostic, "status": "blocked"})
            print(json.dumps(diagnostic, sort_keys=True))
            return 2
        task = tasks[0] if tasks and isinstance(tasks[0], Mapping) else {}
        repo = str(result.get("repo") or task.get("repo") or ".")
        run_id = str(result.get("run_id") or task.get("run_id") or "")
        raw_run_dir = result.get("run_dir") or task.get("run_dir")
        if raw_run_dir:
            run_dir = Path(str(raw_run_dir))
            if not run_dir.is_absolute():
                run_dir = Path(repo).resolve() / run_dir
        else:
            run_dir = Path(repo).resolve() / ".simplicio" / "loop-runs" / (run_id or "single-task-fast-unbound")
        public_payload = publish_loop_execution_for_flow(
            repo=Path(repo),
            run_dir=run_dir,
            flow="single-task-fast",
            flow_result={**dict(result), "run_id": run_id},
        )
        public_payload = _attach_dispatch(public_payload, result)
        persist_execution_envelope(
            flow="single-task-fast",
            repo=repo,
            run_id=run_id,
            observed={"task": task, "tasks": tasks, "result": result, "run_id": run_id},
        )
        print(json.dumps(public_payload, sort_keys=True))
        return 0 if public_payload.get("status") == "VERIFIED" and public_payload.get("verified") is True else 2
    if command == "ledger":
        return ledger_replay(
            args.path,
            args.compatibility,
            args.recover_trailing,
            args.handshake_json,
            args.handshake_file,
            args.ledger_command,
        )
    if command == "release-train":
        if args.release_train_command == "check":
            manifest_module = _load_release_manifest(args.repo)
            if manifest_module is None:
                parser.error("release_manifest script not importable")
            return manifest_module.release_train_check(args.repo)
        if _release_train is None:
            parser.error("release_train script not importable")
        return _release_train.run_namespace(args)
    return install(
        Path(args.target).resolve(),
        args.globally,
        getattr(args, "host", "claude"),
        getattr(args, "dry_run", False),
        getattr(args, "uninstall", False),
        getattr(args, "verify", False),
    )


if __name__ == "__main__":
    raise SystemExit(main())
