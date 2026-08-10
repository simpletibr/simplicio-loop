from __future__ import annotations

import json
import os
import subprocess
import sys
import time

from ..mapper import write_architecture_docs
from ..project_capabilities import sync_project_capabilities_after_mapping
from ._index_engine import (
    _acquire_index_lock,
    _artifact_paths,
    _artifacts_exist,
    _emit_index_json,
    _freshness_signature,
    _index_result,
    _inspect_index_lock,
    _lock_path,
    _process_start_token,
    _read_index_state,
    _release_index_lock,
    _run_once,
    _signature,
    _write_index_state,
)
from ._shared import INDEX_STATE_SCHEMA, MAP_JOB_SCHEMA

_MAP_JOB_IDENTITY_ENV = "SIMPLICIO_MAPPER_MAP_JOB_OWNER_TOKEN"
_MAP_JOB_FINALIZE_GRACE_SECONDS = 5.0
_MAP_JOB_FINALIZE_POLL_SECONDS = 0.01
_TERMINAL_JOB_PHASES = {"complete", "failed", "timeout"}

def _map_job_path(root: str, out: str) -> str:
    return os.path.join(os.path.abspath(os.path.join(root, out)), "map-job.json")


def _same_job(deep: dict, identity: dict) -> bool:
    pid = identity.get("pid")
    process_start = identity.get("process_start")
    owner_token = identity.get("owner_token")
    return (
        isinstance(pid, int)
        and pid > 0
        and isinstance(process_start, str)
        and bool(process_start)
        and process_start != "unknown"
        and isinstance(owner_token, str)
        and bool(owner_token)
        and deep.get("pid") == pid
        and deep.get("process_start") == process_start
        and deep.get("owner_token") == owner_token
    )


def _write_terminal_map_job(job_path: str, job: dict, identity: dict) -> bool:
    temporary = f"{job_path}.tmp-{os.getpid()}-{identity['owner_token'][:8]}"
    try:
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(job, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        with open(job_path, encoding="utf-8") as handle:
            current = json.load(handle)
        current_deep = current.get("deep") if isinstance(current.get("deep"), dict) else {}
        if current.get("schema") != MAP_JOB_SCHEMA or not _same_job(current_deep, identity):
            return False
        os.replace(temporary, job_path)
        return True
    except (FileNotFoundError, OSError, json.JSONDecodeError, TypeError, ValueError):
        return False
    finally:
        try:
            os.remove(temporary)
        except FileNotFoundError:
            pass


def _finalize_map_job(
    root: str,
    out: str,
    identity: dict,
    *,
    exit_code: int,
    phase: str,
    failure_reason: str | None,
    wait_for_job: bool,
) -> bool:
    """Atomically finalize only the map job owned by ``identity``.

    The bounded wait closes the spawn-to-receipt race without ever allowing a
    completed worker to overwrite a newer job. PID, process-start identity and
    the per-job owner token must all match immediately before ``os.replace``.
    """
    if phase not in _TERMINAL_JOB_PHASES or not _same_job(identity, identity):
        return False
    deadline = time.monotonic() + (_MAP_JOB_FINALIZE_GRACE_SECONDS if wait_for_job else 0.0)
    job_path = _map_job_path(root, out)
    while True:
        try:
            with open(job_path, encoding="utf-8") as handle:
                job = json.load(handle)
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            job = {}
        deep = job.get("deep") if isinstance(job.get("deep"), dict) else {}
        if job.get("schema") == MAP_JOB_SCHEMA and _same_job(deep, identity):
            if (
                job.get("phase") in _TERMINAL_JOB_PHASES
                and isinstance(deep.get("exit_code"), int)
                and deep.get("finished_at")
            ):
                return True
            deep.update(identity)
            deep["exit_code"] = int(exit_code)
            deep["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            deep["failure_reason"] = failure_reason
            job["deep"] = deep
            job["phase"] = phase
            return _write_terminal_map_job(job_path, job, identity)
        if time.monotonic() >= deadline:
            return False
        time.sleep(_MAP_JOB_FINALIZE_POLL_SECONDS)


def _background_index_is_fresh(root: str, out: str) -> bool:
    state = _read_index_state(root, out)
    return (
        state.get("schema") == INDEX_STATE_SCHEMA
        and state.get("completeness", "complete") == "complete"
        and state.get("signature") == _freshness_signature(root, out)
        and _artifacts_exist(_artifact_paths(root, out))
    )


def _finalize_background_job(opts: dict, exit_code: int) -> bool:
    """Finalize an async scan from inside the durable index worker process."""
    owner_token = os.environ.get(_MAP_JOB_IDENTITY_ENV, "")
    if not owner_token:
        return False
    root = os.path.abspath(opts["root"])
    out = opts["out"]
    identity = {
        "pid": os.getpid(),
        "process_start": _process_start_token(os.getpid()) or "unknown",
        "owner_token": owner_token,
    }
    complete = exit_code == 0 and _background_index_is_fresh(root, out)
    return _finalize_map_job(
        root,
        out,
        identity,
        exit_code=exit_code,
        phase="complete" if complete else "failed",
        failure_reason=None if complete else (
            f"worker_exit_{exit_code}" if exit_code else "worker_exit_0_before_terminal"
        ),
        wait_for_job=True,
    )


def _spawn_index_process(opts: dict) -> tuple[dict, subprocess.Popen]:
    """Spawn an index worker and return its receipt plus live process handle."""
    root = os.path.abspath(opts["root"])
    out = opts["out"]
    abs_out = os.path.abspath(os.path.join(root, out))
    os.makedirs(abs_out, exist_ok=True)
    log_path = os.path.join(abs_out, "background-index.log")
    args = [sys.executable, "-B", "-m", "simplicio_mapper.cli", "index", root, "--out", out]
    if opts["stack"]:
        args.extend(["--stack", opts["stack"]])
    if opts["product_name"]:
        args.extend(["--product-name", opts["product_name"]])
    if opts["docs"]:
        args.append("--docs")
    if opts["incremental"]:
        args.append("--update")
    if opts["verbose"]:
        args.append("--verbose")
    if opts.get("canonical_reuse"):
        args.append("--canonical-reuse")
    args.extend(["--timeout", str(max(0, int(opts.get("timeout", 120))))])
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    owner_token = str(opts.get("_map_job_owner_token") or "")
    if owner_token:
        env[_MAP_JOB_IDENTITY_ENV] = owner_token
    else:
        env.pop(_MAP_JOB_IDENTITY_ENV, None)
    source_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    python_path = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join([source_root, python_path]) if python_path else source_root
    with open(log_path, "ab") as log:
        child = subprocess.Popen(  # noqa: S603 - self-invocation with fixed argv
            args,
            cwd=root,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    payload = {
        "schema": "simplicio.background-index/v1",
        "status": "started",
        "pid": child.pid,
        "process_start": _process_start_token(child.pid) or "unknown",
        "log": log_path.replace(os.sep, "/"),
    }
    if owner_token:
        payload["owner_token"] = owner_token
    return payload, child


def _spawn_background_index(opts: dict) -> dict:
    """Spawn a detached index refresh; the worker owns terminal persistence."""
    payload, _child = _spawn_index_process(opts)
    return payload

def _run_background(opts: dict) -> int:
    try:
        payload = _spawn_background_index(opts)
    except OSError as error:
        # Windows hosts with a closed/captured stdin historically raised
        # WinError 6 here before the child existed. stdin is pinned to
        # DEVNULL in Popen; residual spawn failure still returns a structured
        # reason code so callers never see a bare traceback as the only
        # signal (issue #231).
        payload = {
            "schema": "simplicio.background-index/v1",
            "status": "failed",
            "reason_code": "worker_spawn_failed",
            "error": str(error),
            "winerror": getattr(error, "winerror", None),
        }
        if opts["json"]:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"background index failed: {error}", file=sys.stderr)
        return 1
    if opts["json"]:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(f"background index started pid={payload['pid']} log={payload['log']}")
    return 0


def _run_index(opts: dict) -> int:
    root = os.path.abspath(opts["root"])
    out = opts["out"]
    map_job_owner_token = os.environ.get(_MAP_JOB_IDENTITY_ENV, "")
    lock = _acquire_index_lock(root, out, map_job_owner_token=map_job_owner_token)
    if lock is None:
        # Index callers share one per-worktree lock.  Waiting here lets a
        # foreground caller join the active refresh instead of reporting a
        # misleading successful skip while the owner is still building.
        deadline = time.monotonic() + max(0, int(opts.get("timeout", 120)))
        while time.monotonic() < deadline:
            lock_status = _inspect_index_lock(root, out)
            if lock_status.get("reason_code") != "lock_live_owner":
                lock = _acquire_index_lock(root, out, map_job_owner_token=map_job_owner_token)
                if lock is not None:
                    break
            time.sleep(0.25)
        if lock is not None:
            return _run_index_and_generate(opts, root, out, lock)
        # A live owner still holds the lock (or a reclaim is provably unsafe,
        # e.g. a fresh-but-malformed write). Surface the classification here
        # too -- not just via ``status`` -- so ``index --json`` alone carries
        # owner/age/reason evidence for diagnosis (issue #201).
        lock_status = _inspect_index_lock(root, out)
        result = _index_result(
            root,
            out,
            status="skipped",
            skipped_reason="locked_timeout",
            counts={
                "files": 0,
                "precedents": 0,
                "changed_files": 0,
                "modules": 0,
                "layers": 0,
                "symbols": 0,
                "relationships": 0,
            },
        )
        result["lock_status"] = lock_status
        _emit_index_json(opts, result)
        if not opts["json"]:
            print(
                f"index skipped: lock already exists at {_lock_path(root, out)} "
                f"({lock_status.get('reason_code')})"
            )
        return 0
    return _run_index_and_generate(opts, root, out, lock)


def _run_index_and_generate(opts: dict, root: str, out: str, lock) -> int:
    """Finish the map, release its lock, then compile durable descriptors."""

    try:
        exit_code = _run_index_locked(opts, root, out, lock)
    finally:
        _release_index_lock(lock)
    if exit_code != 0:
        return exit_code
    state = _read_index_state(root, out)
    paths = _artifact_paths(root, out)
    generation = sync_project_capabilities_after_mapping(
        root,
        out,
        complete=state.get("completeness", "unknown") == "complete",
        fresh=state.get("signature") == _freshness_signature(root, out),
        lock_active=bool(_inspect_index_lock(root, out).get("active")),
        artifacts_present=_artifacts_exist(paths),
    )
    return 1 if generation.get("status") == "failed" else exit_code


def _run_index_locked(opts: dict, root: str, out: str, lock) -> int:
    paths = _artifact_paths(root, out)
    state = _read_index_state(root, out)
    current_signature = _freshness_signature(root, out)

    if (
        state.get("schema") == INDEX_STATE_SCHEMA
        and state.get("completeness", "complete") == "complete"
        and state.get("signature") == current_signature
        and _artifacts_exist(paths)
    ):
        payload = _index_result(
            root,
            out,
            status="skipped",
            skipped_reason="already_fresh",
            counts=state.get("counts") if isinstance(state.get("counts"), dict) else None,
        )
        payload["lock_reason_code"] = lock.reason_code
        if opts["docs"]:
            docs_payload = write_architecture_docs(root, output_dir=out)
            payload["paths"]["docs_root"] = docs_payload["docs_root"].replace(os.sep, "/")
            payload["counts"]["docs"] = docs_payload["counts"]["files"]
        _emit_index_json(opts, payload)
        return 0

    run_result = _run_once(
        {
            **opts,
            "root": root,
            "incremental": bool(state),
            "silent": not opts["verbose"],
        }
    )
    refreshed_signature = _freshness_signature(root, out)
    payload = _index_result(root, out, status="updated", run_result=run_result)
    payload["lock_reason_code"] = lock.reason_code
    if opts["docs"]:
        docs_payload = write_architecture_docs(root, output_dir=out)
        payload["paths"]["docs_root"] = docs_payload["docs_root"].replace(os.sep, "/")
        payload["counts"]["docs"] = docs_payload["counts"]["files"]
    _write_index_state(root, out, refreshed_signature, payload["counts"])
    try:
        os.remove(os.path.join(os.path.abspath(os.path.join(root, out)), "partial-scan.json"))
    except FileNotFoundError:
        pass
    _emit_index_json(opts, payload)
    return 0


def _watch(opts: dict) -> None:
    root = os.path.abspath(opts["root"])
    print(f"watching {root} for mapper updates...")
    last = _signature(root, opts["out"])
    try:
        while True:
            time.sleep(0.5)
            current = _signature(root, opts["out"])
            if current != last:
                last = current
                try:
                    _run_once({**opts, "incremental": True})
                except Exception as error:  # noqa: BLE001 - watch loop must not crash
                    print(f"map update failed: {error}", file=sys.stderr)
    except KeyboardInterrupt:
        pass
