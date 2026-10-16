"""`task`, `prototype`, `plan`, `prepare`/`arm` and the deprecated `run` redirect: task contracts and run arming.

Split from cli_impl.py (#1818). The code is moved unchanged; see
cli_commands/_base.py for why some names are read through impl().
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional
from typing import Sequence
import argparse
import contextlib
import io
import json
import sys

from ._base import impl

from .. import delivery
from .. import next_step
from ..delivery import DELIVERY_ORDER
from ..evidence import redact_sensitive_text
from ..json_order import stable_first
from ..loop_execution_receipt import publish_loop_execution_for_flow
from ..state_dir import ensure_state_dir
from .execution import (_public_flow_from_status)

def _write_task_contract(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(__import__("json").dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def plan(task_path: str, out_path: str) -> int:
    raw = Path(task_path).read_text(encoding="utf-8")
    payload = impl().compile_many(raw, source_path=task_path)
    out = Path(out_path)
    _write_task_contract(out, payload)
    print(f"simplicio-loop plan wrote {out}")
    for idx, task in enumerate(payload.get("tasks") or [], start=1):
        if idx > 1:
            print("")
        print(f"[task {idx}]")
        print(impl().preview_contract(task))
    return 0


def prepare(repo: str, task_path: str, delivery_arg: str, max_iterations: int) -> int:
    """Arm and preflight a run without executing a task or calling a provider."""
    from ..survey import MISSING_HINT, MISSING_REASON, provenance
    if provenance(Path(repo).resolve()) is None:
        print(json.dumps(stable_first({"schema": "simplicio.prepare-receipt/v1", "status": "blocked",
                          "reason_code": MISSING_REASON, "hint": MISSING_HINT,
                          "execution_started": False, "mutation_attempted": False}),
                         ensure_ascii=False, indent=2))
        next_step.emit(next_step.orient_command(repo))
        return 2
    try:
        ensure_state_dir(Path(repo).resolve())
        delivery_target = delivery.normalize_delivery_target(delivery_arg)
        armed = impl().arm_run(repo, task_path, delivery_target, max_iterations)
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
        if "invalid task contract" in str(exc):
            payload["task_contract"] = next_step.contract_problems(task_path, str(exc))
    print(json.dumps(stable_first(payload), ensure_ascii=False, indent=2))
    if payload["status"] != "prepared":
        next_step.prepare_next(repo, task_path, payload)
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
        from ..extension_handshake import ExtensionHandshakeError, verify_runtime_fingerprint
        try:
            verify_runtime_fingerprint(required_handshake_fingerprint)
        except ExtensionHandshakeError as exc:
            impl().persist_execution_envelope(
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
        impl().persist_execution_envelope(
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
        payload = impl().conduct_run(
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
        impl().persist_execution_envelope(
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
            run_dir=Path(repo).resolve() / ".simplicio-loop" / "loop-runs" / "run-failed",
            flow="run",
            flow_result={"status": "infrastructure_failure"},
        )
        diagnostic["error"] = redact_sensitive_text(str(exc))
        print(json.dumps(diagnostic, ensure_ascii=False, indent=2))
        return 24
    run_id = str((payload.get("manifest") or {}).get("run_id") or "")
    impl().persist_execution_envelope(
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


def _redirect_run_to_wave(argv: Sequence[str]) -> int:
    """Redirect deprecated 'run' invocation to the default 'wave' flow."""
    sys.stderr.write(
        "[simplicio-loop] AVISO: O comando 'run' foi descontinuado. "
        "Redirecionando automaticamente para o fluxo padrão 'wave'...\n"
    )
    from ..delivery import DELIVERY_ORDER
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
    provider_worker = args.provider_worker or impl().os.environ.get("SIMPLICIO_PROVIDER_WORKER")

    armed = None
    if not run_id and args.task:
        delivery_target = delivery.normalize_delivery_target(args.delivery)
        armed = impl().arm_run(repo, args.task, delivery_target, args.max_iterations)
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
            impl().batch(*batch_args, flow="wave")

    if armed_blocked:
        status = armed
    else:
        try:
            status = impl().read_status(repo, run_id)
        except Exception:
            status = armed or {"manifest": {"run_id": run_id}, "state": {}, "run_dir": ""}
    from ..run_outcome import persist_run_outcome
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


def add_task(sub):
    p_task = sub.add_parser("task", help="compile, validate, or preview markdown task contracts")
    p_task.add_argument("task_args", nargs=argparse.REMAINDER,
                        help="pass-through args for `simplicio-loop task`")


def add_prototype(sub):
    p_prototype = sub.add_parser(
        "prototype", help="Prototype-First gate: plan/classify/validate-schema/doctor (#568 P0)"
    )
    p_prototype.add_argument("prototype_args", nargs=argparse.REMAINDER,
                             help="pass-through args for `simplicio-loop prototype`")


def add_plan(sub):
    p_plan = sub.add_parser("plan", help="compile a raw task into a contract and preview it")
    p_plan.add_argument("--task", required=True, help="markdown task file")
    p_plan.add_argument("--out", default=impl().os.path.join(".simplicio-loop/orchestrator", "task-contract.json"),
                        help="where to write the compiled contract")


def add_prepare(sub):
    p_prepare = sub.add_parser(
        "prepare", aliases=["arm"],
        help="arm and preflight a run without executing tasks or calling a provider",
    )
    p_prepare.add_argument("--task", default=None,
                           help="markdown task file (the shape: `simplicio-loop prepare --example`)")
    p_prepare.add_argument("--example", action="store_true",
                           help="print a valid markdown task file to stdout (copy it, edit it, pass it to --task)")
    p_prepare.add_argument("--repo", default=".", help="repository root")
    p_prepare.add_argument(
        "--delivery", default="verified", choices=DELIVERY_ORDER[1:],
        metavar="{" + ",".join(DELIVERY_ORDER[1:]) + "}",
        help="requested delivery target",
    )
    p_prepare.add_argument("--max-iterations", type=int, default=12, help="safety cap")
