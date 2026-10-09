"""Host mode of the 24/7 watcher (epic #1429): an exec CLI plans, dev-cli applies.

The default executor is ``exec``. For each work item:

1. ``exec_planner.run_planner_with_fallback`` runs a plan-only CLI (claude, codex, grok, gemini, ...) with the model and
   effort of the current role (``model_roles.resolve``), prompted with turbo's request. The CLI never edits a file.
2. The watcher pipes the plan to ``simplicio-loop turbo --apply - --run-id ID [--verify V]`` inside ``sandbox.wrap``,
   continuing the run of step 1 (``turbo --task T``: Mapper orient, the request the planner gets, the run id). One
   run_id then covers the intake, map, plan, apply, verify, pr and done events and the execution-report. dev-cli is the only writer.
3. On a failed apply or verify, the escalation ladder (execution -> coordination -> planning) picks the next role and the
   planner retries with the failure output, until the attempt or token ceilings stop it.

A new issue starts at ``planning`` (a squad worker starts at the role squad_routing picks); a PR review fix starts at ``coordination`` and pushes to the PR branch. Every step is
written to a ``simplicio.execution-report/v1`` with its role, model and effort. ``openrouter`` is used only when
``SIMPLICIO_EXECUTOR=openrouter`` is set and ``OPENROUTER_API_KEY`` exists (executor_select).
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import escalation, exec_auth, exec_planner, execution_report, executor_select
from . import budget, config, proc, sandbox, verify
from . import convergence  # the failed-verify path asks it: retry, escalate or stop (a module, not a point)

PLAN_ROLE = "planning"
FIX_ROLE = "coordination"
FAILURE_CAP = 1500  # the failure output handed back to the planner
RETRYABLE = "bad_plan"  # the only planner failure a better role can fix; the others wait for the next tick


@dataclass(frozen=True)
class Executor:
    """The executor the tick runs with; ``blocked`` is the reason_code when it must process nothing."""

    mode: str
    families: tuple[str, ...] = ()
    blocked: str = ""
    detail: str = ""


_LAST_AUTH: list[exec_auth.AuthCheckResult] = []  # auth results of the last choose() in exec mode


def last_auth() -> list[exec_auth.AuthCheckResult]:
    """What choose() probed this tick, for the model_preflight point; empty before the first choose()."""
    return list(_LAST_AUTH)


async def choose(environ: dict[str, str] | None = None) -> Executor:
    """SIMPLICIO_EXECUTOR picks the mode (default exec). In exec mode a preflight checks every enabled family."""
    environ = os.environ if environ is None else environ
    try:
        resolved = executor_select.resolve(environ)
    except executor_select.ExecutorSelectError as exc:
        return Executor(executor_select.DEFAULT_MODE, blocked="executor_invalid", detail=str(exc))
    if resolved["mode"] == "host":  # the invoking model would have to run turbo; the service has none
        return Executor("host", blocked="executor_host_not_headless",
                        detail="SIMPLICIO_EXECUTOR=host spawns nothing; use exec or openrouter")
    if resolved["mode"] != "exec":
        return Executor(resolved["mode"])
    results = await exec_auth.check_all(resolved["families"])
    _LAST_AUTH[:] = results  # read by the model_preflight point, so it never probes again
    usable = tuple(r.family for r in results if r.status == "ok")
    if usable:
        return Executor("exec", usable)
    first = results[0]
    return Executor("exec", blocked=f"{first.status}:{first.family}", detail="; ".join(str(r) for r in results))


# The only variables besides the sandbox allowlist that a planner CLI may see: its own provider key (OAuth logins live in
# HOME). OPENROUTER_API_KEY and every other secret of the service env never reach a planner.
FAMILY_ENV = {
    "claude": ("ANTHROPIC_API_KEY",),
    "codex": ("OPENAI_API_KEY",),
    "grok": ("XAI_API_KEY",),
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
}


def _planner_env(family: str) -> dict[str, str]:
    return sandbox.scrubbed_env(os.environ, home=Path.home(), keep=FAMILY_ENV.get(family, ()))


def plan_prompt(request: str, failure: str = "") -> str:
    """The planner prompt: turbo's request (it already holds the task, map slice, files and format) plus the failure."""
    text = (f"{request}\n\nReply with the plan only: one JSON object in the `format` above, nothing else. "
            "The watcher applies it with dev-cli; do not run the `apply` command.")
    if failure:
        text += ("\n\nThe previous plan was applied and failed. Write a corrected plan for the original task. "
                 f"Failure output:\n{failure[-FAILURE_CAP:]}")
    return text


def _int_env(name: str) -> int | None:
    try:
        return int(os.environ[name])
    except (KeyError, ValueError):
        return None


def ceilings() -> dict[str, int]:
    """Escalation ceilings from the env; unset ones keep the escalation module's defaults."""
    names = {
        "token_ceiling_per_issue": "SIMPLICIO_247_TOKEN_CEILING_ISSUE",
        "token_ceiling_per_day": "SIMPLICIO_247_TOKEN_CEILING_DAY",
        "attempt_ceiling_per_issue": "SIMPLICIO_247_ATTEMPT_CEILING_ISSUE",
        "attempt_ceiling_per_day": "SIMPLICIO_247_ATTEMPT_CEILING_DAY",
    }
    found = {key: _int_env(var) for key, var in names.items()}
    return {key: value for key, value in found.items() if value is not None}


_STATUS_CODE = re.compile(r"[a-z_]{1,32}")


def _failure_reason(planned: exec_planner.PlannerResult, label: str, status: str) -> str:
    """Why a step failed, as a short code: the planner's reason_code, a red verify, or turbo's apply status.

    The status is turbo's output, so only a short lowercase word is kept; anything else (text, a path, a list) is `unknown`.
    Turbo said `ok` but no passing verify came back: that is not an apply failure.
    """
    if not planned.is_ok():
        return planned.reason_code
    if label.startswith("MEASURED|verify_failed"):
        return "verify_failed"
    if status == "ok":
        return "verify_not_reported"
    return f"apply_{status if isinstance(status, str) and _STATUS_CODE.fullmatch(status) else 'unknown'}"


def next_role(ladder: escalation.EscalationState) -> None:
    """execution repeats once, then the ladder climbs; at planning it stays and retries with the failure output."""
    if ladder.current_role() == "execution" and ladder.attempts_in_step < 2:
        return
    ladder.next_step()


async def _reset_tree(dest: Path) -> None:
    """Drop the edits of a failed apply, so the next plan is written against the branch head."""
    await proc.run(["git", "reset", "-q", "--hard", "HEAD"], cwd=dest, timeout=60)
    await proc.run(["git", "clean", "-fdq", "-e", ".simplicio-loop"], cwd=dest, timeout=60)


async def _request(dest: Path, task: str, run_id: str | None = None) -> tuple[str, str]:
    """Step 1, ``turbo --task T`` in the sandbox: the compact request for the planner and the run id turbo continued
    (``run_id``: the run the watcher opened at intake) or started."""
    argv = sandbox.wrap(verify.turbo_request_argv(dest, task, run_id), clone=dest, state_dir=config.ROOT)
    env = sandbox.scrubbed_env(os.environ, home=Path.home())
    result = await proc.run(argv, timeout=config.TURBO_TIMEOUT_S, cwd=dest, env=env)
    document = verify.parse_turbo(result.stdout or "")
    run_id = document.get("run_id")
    if document.get("status") != "needs_plan" or not isinstance(run_id, str):
        reason = document.get("detail") or document.get("reason_code") or (result.stderr or "")[-300:] or "no request"
        raise RuntimeError(f"turbo request {document.get('status') or 'failed'}: {reason}"[:500])
    return json.dumps(document, ensure_ascii=False, separators=(",", ":")), run_id


async def _apply(dest: Path, plan: dict, test_cmd: str | None, run_id: str, attempts: int,
                 log_path: Path, leave_open: bool = False) -> tuple[proc.Result, dict, str, verify.Decision]:
    """Step 2, ``turbo --apply - --run-id`` with the plan on stdin, in the sandbox; no provider key is in the env."""
    argv = sandbox.wrap(verify.turbo_apply_argv(dest, test_cmd, run_id, leave_open), clone=dest, state_dir=config.ROOT)
    env = sandbox.scrubbed_env(os.environ, home=Path.home())
    result = await proc.run(argv, timeout=config.TURBO_TIMEOUT_S, cwd=dest, env=env, stdin=json.dumps(plan))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text((result.stdout or "") + "\n--- stderr ---\n" + (result.stderr or ""))
    document = verify.parse_turbo(result.stdout or "")
    status = document.get("status") or ("ok" if result.returncode == 0 else "failed")
    decision = verify.decide({**document, "status": status}, test_cmd, attempts, config.MAX_ATTEMPTS)
    return result, document, status, decision


def _turbo_report(dest: Path, document: dict) -> dict | None:
    """The execution-report turbo wrote for the apply (its path is run-relative), or None."""
    relative = document.get("execution_report")
    if not isinstance(relative, str):
        return None
    try:
        return json.loads((dest / relative).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _merge_turbo_tasks(report: dict[str, Any], turbo_report: dict) -> None:
    """Turbo's own task for the apply joins the watcher's report: one report, one run_id, the role steps beside it."""
    report["tasks"].extend(turbo_report.get("tasks") or [])
    for operator in turbo_report.get("operators_used") or []:
        if operator not in report["operators_used"]:
            report["operators_used"].append(operator)


def _note_step(report: dict[str, Any], *, repo: str, issue: dict, step: int, planned: exec_planner.PlannerResult,
               outcome: str, wall_ms: int) -> None:
    """One task of the role receipt: the role, model and effort the step ran with. Tokens stay UNVERIFIED."""
    execution_report.record_task(
        report, task_id=f"{repo}#{issue['number']}-step{step}", title=f"watcher exec step {step}: {planned.role}",
        issue=str(issue["number"]), wall_ms=wall_ms, outcome=outcome, operators=["exec-planner", "dev-cli"])
    report["tasks"][-1].update(
        {"step": step, "role": planned.role, "family": planned.family, "model": planned.model,
         "effort": planned.effort, "planner": planned.reason_code})


async def run_exec(dest: Path, repo: str, issue: dict, task: str, test_cmd: str | None, executor: Executor,
                   attempts: int, fix: bool = False, role: str = "", run_id: str | None = None) -> dict[str, Any]:
    """Plan with the exec CLI, apply with turbo, escalate on failure. Returns the claim fields; raises when it failed.

    ``run_id``: the run the watcher opened at intake. Turbo continues it and leaves it open after a good apply, so the
    watcher writes the pr stage and closes it (``events.close_run``).
    """
    number = int(issue["number"])
    ladder = escalation.load_escalation_state(dest, number, executor.families[0], **ceilings())
    ladder.current_step = escalation.ESCALATION_LADDER.index(role or (FIX_ROLE if fix else PLAN_ROLE))
    ladder.attempts_in_step = 0  # the records (the ceilings) persist across ticks; the starting role does not
    report = execution_report.new_report(dest)
    steps: list[dict[str, str]] = []
    failure = ""
    try:
        leave_open = run_id is not None  # the watcher opened the run: it closes it after the pr stage
        request, run_id = await _request(dest, task, run_id)  # step 1, once: every retry reuses this request and run
        report["run_id"] = run_id  # the watcher's role receipt lands in the report turbo writes for this run
        for step in range(1, config.MAX_STEPS + 1):
            if not ladder.can_escalate():
                raise RuntimeError(f"escalation ceiling reached: {failure or 'no budget left'}"[:500])
            await budget.record("model_calls")
            started = time.monotonic()
            planned = await exec_planner.run_planner_with_fallback(
                ladder.current_role(), plan_prompt(request, failure), cwd=str(dest),
                timeout_sec=config.PLAN_TIMEOUT_S, families=list(executor.families),
                wrap=lambda argv: sandbox.wrap(argv, clone=dest, state_dir=config.ROOT), env_for=_planner_env,
                config_dir=config.ROOT / "opencode")  # inside the bound state dir: /tmp is a tmpfs in the sandbox
            ladder.family = planned.family or ladder.family
            ok, failure, tokens_report, label, result, status = False, "", None, "", None, "failed"
            if planned.is_ok():
                log_path = config.LOGS / f"{repo}-{number}-{attempts}-s{step}.log"
                result, document, status, decision = await _apply(dest, planned.plan, test_cmd, run_id, attempts, log_path, leave_open)
                tokens_report = _turbo_report(dest, document)
                if tokens_report:
                    _merge_turbo_tasks(report, tokens_report)
                ok, label, failure = decision.action == "pr", decision.label, decision.reason
            else:
                failure = f"planner {planned.reason_code}: {planned.error or ''}"
            wall_ms = int((time.monotonic() - started) * 1000)
            ladder.record_attempt("ok" if ok else "failed", error=failure or None, execution_ms=wall_ms,
                                  report=tokens_report)
            _note_step(report, repo=repo, issue=issue, step=step, planned=planned,
                       outcome="COMPLETE" if ok else "FAIL", wall_ms=wall_ms)
            steps.append({"role": planned.role, "family": planned.family, "model": planned.model,
                          "effort": planned.effort, "outcome": "ok" if ok else "failed",
                          **({} if ok else {"reason": _failure_reason(planned, label, status)})})
            if ok:
                report["status"] = "COMPLETE"
                return {"turbo_status": status, "exit_code": result.returncode, "verify": label,
                        "executor": "exec", "steps": steps}
            if not planned.is_ok() and planned.reason_code != RETRYABLE:
                raise RuntimeError(failure[:500])  # cli missing, quota, timeout: a better role does not help
            verdict = convergence.assess(ladder, failed=True)  # the failed attempt is already in the ladder
            if verdict["action"] == "stop":
                raise RuntimeError(f"convergence stop ({verdict['reason']}): {failure}"[:500])
            await _reset_tree(dest)
            if verdict["action"] == "escalate":
                ladder.next_step()
            else:
                next_role(ladder)
        raise RuntimeError(f"no verified plan after {config.MAX_STEPS} steps: {failure}"[:500])
    except BaseException:
        report["status"] = "FAILED"
        raise
    finally:
        report["finished_at_unix"] = int(time.time())
        execution_report.write_report(dest, report)
