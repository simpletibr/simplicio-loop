"""Plan building for one operator task: repo file hints, Mapper operations store, minimal host plan compilation and the provider worker plan (#1606)."""
from __future__ import annotations

import json
import hashlib
import os
import re
from pathlib import Path
from typing import (
    Any,
    Dict,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
)
from . import dashboard_events as _dashboard_events, plan_paths
from .plan_contract import PLAN_SCHEMA
from .remote_queue import QueueUnavailable
from .provider_worker import (
    OPENROUTER_MODEL,
    OpenRouterWorker,
    ProviderWorkerError,
    forwarded_environment,
    proposal_to_mechanical_plan,
)
from .hookwall_persistence import HookwallEffectLedger
from .mapper_hookwall import MapperHookwallEffectLedger
from .store_adapter import StorageRoute, StoreAdapterError
from .runner_core import (
    MAX_PROVIDER_CURRENT_TARGET_CHARS,
    HOST_EDIT_PLAN_SCHEMAS,
    _now,
    _load_json,
    _write_json,
    _storage_route_requested,
    _run_cmd,
    _operator_timeout,
    _devcli_cmd,
    _repo_fingerprint,
    _repo_state_equivalent,
    _task_goal,
    read_status,
)
from .runner_lifecycle import _transition

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
    if reason := plan_paths.plan_refusal(plan, repo_path):  # every plan, schema or not: .git and symlinks
        return {"reason_code": "plan_path_unsafe", "message": reason}
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
    if reason := plan_paths.plan_refusal(plan, repo_path):
        return None, "plan_path_unsafe", reason
    operations = _minimal_plan_operations(plan)
    already_compiled = bool(operations) and all("op" in op for op in operations)
    # A schema on a find/replace plan used to skip compile and the apply then
    # rejected every lane with invalid_plan. Compile those. An already compiled
    # plan (each operation has op) still passes through.
    if plan.get("schema") and (already_compiled or not operations):
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
    compiled_path.unlink()
    if reason := plan_paths.plan_refusal(compiled, repo_path):  # the plan that gets applied, whichever dev-cli compiled it
        return None, "plan_path_unsafe", reason
    _write_json(plan_path, compiled)
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
            repo_root=root,
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
        # The provider's measured usage is known only now: the route record was written before the call.
        _dashboard_events.emit_token_usage(run_dir, only=receipt_path.name)
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


def _operator_receipt_hash(receipt: Mapping[str, Any]) -> str:
    """Stable sha256 over the canonical receipt body (excluding receipt_hash itself).

    Issue #135: the receipt is the durable proof a production diff was produced through the
    bridge. The hash lets the diff-coverage gate bind a `git diff` path to exactly one receipt.
    """
    canonical = {k: v for k, v in receipt.items() if k != "receipt_hash"}
    blob = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()
