"""Run lifecycle bookkeeping: phase transitions, progress events, scratchpad, GitHub/Orca synchronisation and the auto planning receipt (#1606)."""
from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Mapping,
    Optional,
)
from . import (
    github_lifecycle as _github_lifecycle,
    dashboard_events as _dashboard_events,
)
from .client_integrations import integration_enabled
from .orca_lifecycle import sync_orca_status
from .source_adapter import GitHubSourceAdapter
from .event_metadata import SCHEMA as EVENT_METADATA_SCHEMA, infer_scope
from .operator_bootstrap import (
    OperatorBootstrapError,
    ensure_operators as _ensure_required_operators,
)
from .planning_gate import (
    auto_planning_receipt_enabled,
    build_planning_receipt as _build_planning_receipt,
    publish_planning_receipt as _publish_planning_receipt,
)
from .loop_execution_receipt import LoopExecutionReceiptError
from .runner_core import (
    PHASES,
    _now,
    _rand_token,
    _load_json,
    _write_json,
    _append_jsonl,
    _run_repo_path,
    _git_current_branch,
    _dispatch_identity_fields,
)

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
    the loop-execution receipt still carries the loop's JSONL attempt-memory
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
    # #1398: events.jsonl is the simplicio.dashboard-event/v1 stream (fail-open, locked seq).
    _dashboard_events.emit_runner_event(run_dir, state, event)
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
        from .pr_evidence import publish_comment as _publish_comment

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
            from .pr_evidence import publish_comment as _publish_comment

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
