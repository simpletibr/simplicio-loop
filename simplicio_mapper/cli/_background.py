from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time

from ..mapper import write_architecture_docs
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
from ._shared import INDEX_STATE_SCHEMA


def _spawn_index_process(opts: dict) -> tuple[dict, subprocess.Popen]:
    """Spawn an index worker and return its receipt plus live process handle.

    Keeping the process handle available lets ``scan --sync`` enforce its
    timeout instead of running the deep pass in the CLI process forever. The
    background entrypoint below deliberately discards the handle after
    installing a reaper thread.
    """
    root = os.path.abspath(opts["root"])
    out = opts["out"]
    abs_out = os.path.abspath(os.path.join(root, out))
    os.makedirs(abs_out, exist_ok=True)
    log_path = os.path.join(abs_out, "background-index.log")
    args = [sys.executable, "-m", "simplicio_mapper.cli", "index", root, "--out", out]
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
    env = os.environ.copy()
    source_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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
    # Keep the Popen object alive until the detached child exits. Besides
    # reaping it, this prevents Python's Windows ResourceWarning from closing
    # a still-active process handle during object finalization.
    payload = {
        "schema": "simplicio.background-index/v1",
        "status": "started",
        "pid": child.pid,
        "process_start": _process_start_token(child.pid) or "unknown",
        "log": log_path.replace(os.sep, "/"),
    }
    return payload, child


def _spawn_background_index(opts: dict) -> dict:
    """Spawn a detached ``index`` refresh; return its ``pid``/``log`` payload."""
    payload, child = _spawn_index_process(opts)
    # Keep the Popen object alive until the detached child exits. Besides
    # reaping it, this prevents Python's Windows ResourceWarning from closing
    # a still-active process handle during object finalization.
    threading.Thread(target=child.wait, name=f"simplicio-index-{child.pid}", daemon=True).start()
    return payload


def _run_background(opts: dict) -> int:
    payload = _spawn_background_index(opts)
    if opts["json"]:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(f"background index started pid={payload['pid']} log={payload['log']}")
    return 0


def _run_index(opts: dict) -> int:
    root = os.path.abspath(opts["root"])
    out = opts["out"]
    lock = _acquire_index_lock(root, out)
    if lock is None:
        # Index callers share one per-worktree lock.  Waiting here lets a
        # foreground caller join the active refresh instead of reporting a
        # misleading successful skip while the owner is still building.
        deadline = time.monotonic() + max(0, int(opts.get("timeout", 120)))
        while time.monotonic() < deadline:
            lock_status = _inspect_index_lock(root, out)
            if lock_status.get("reason_code") != "lock_live_owner":
                lock = _acquire_index_lock(root, out)
                if lock is not None:
                    break
            time.sleep(0.25)
        if lock is not None:
            try:
                return _run_index_locked(opts, root, out, lock)
            finally:
                _release_index_lock(lock)
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
    try:
        return _run_index_locked(opts, root, out, lock)
    finally:
        _release_index_lock(lock)


def _run_index_locked(opts: dict, root: str, out: str, lock) -> int:
    paths = _artifact_paths(root, out)
    state = _read_index_state(root, out)
    current_signature = _freshness_signature(root, out)

    if (
        state.get("schema") == INDEX_STATE_SCHEMA
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
