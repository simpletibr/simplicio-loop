#!/usr/bin/env python3
"""Transactional executor for the simplicio-loop installer (#293, "separar planner e executor"
part 2: the executor half, plus rollback).

`scripts/install_plan.py` is the pure planner: given `(runtime, mode, scope, target)` it returns
a deterministic `simplicio.install-transaction/v1` plan with NO side effects. This module is the
executor that actually APPLIES that plan's file effects (skills, hooks, worker scripts, the
runtime entry file, and — for Claude — `.claude/settings.json`) using the same idempotent
primitives already in `scripts/install_lib.py` (`copy_skills`, `copy_hooks`, `copy_scripts`,
`ensure_entry`, `merge_claude_hooks`), but wraps each one with:

- a backup of whatever already exists at that path, taken BEFORE the mutation runs;
- a before/after content hash, so the receipt records exactly what changed;
- automatic rollback (restore-from-backup for pre-existing paths, remove for freshly-created
  ones) if any later step in the same transaction raises — so a mid-install failure never leaves
  partial state behind, only either a clean APPLIED transaction or a clean ROLLED_BACK one;
- a persisted receipt (`<target>/.simplicio-loop/receipts/<transaction_id>.json`) so the same
  transaction can be rolled back LATER too, via `rollback()` / `install_lib.py rollback <id>`.

Rollback only ever touches paths this module itself recorded backing up for that specific
transaction id — it never guesses at or deletes anything it doesn't hold a receipt for
("remove somente recursos de ownership comprovado", issue #293 step 5).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import install_lib as _lib  # noqa: E402
from install_plan import build_plan  # noqa: E402

# Deterministic order: reconcile (drop stale N-1 leftovers) runs FIRST — before anything from
# the current version is (re)written — then skills/hooks/scripts (pure copies), then the
# generated files that reference them (entry block, Claude settings.json hook-wiring), so a
# failure never wires a hook to a skill tree that didn't make it in. `full_stack` runs LAST-1: it
# only ever applies in full-stack mode (#293 modes) and is purely additive on top of the other
# steps, so ordering it late keeps the minimal/runtime/ci step sequence byte-identical to before.
# `service` runs absolutely last: OS-level service registration (#293 gap 1, "wire OS-level
# service registration into apply() for full-stack mode") only ever makes sense once the file
# surface it depends on (the `full_stack` engine/app copy, when present) is already on disk.
STEP_ORDER = ("reconcile", "skills", "hooks", "scripts", "entry", "claude_settings", "full_stack",
              "service")

# Steps that ONLY apply to `full-stack` mode — every other mode (minimal/runtime/ci) gets exactly
# the same file surface as before this mode support was added, proven by
# tests/test_install_transaction_unit.py::test_non_full_stack_modes_never_touch_engine_or_app.
FULL_STACK_ONLY_STEPS = ("full_stack",)

# The install_services.py worker this module drives for the "service" step. Imported
# in-process (not shelled out) so `apply()` stays a single fast Python call with no extra
# subprocess-spawn overhead/flakiness — `install_services.service_paths()`/`.linux_install()`/
# `.windows_install()` all read HOME/APPDATA/XDG_CONFIG_HOME from `os.environ` FRESH at call
# time (never a value cached from whenever the module happened to first import), so a caller
# that redirects those vars for a test/CI run governs both (a) the paths this module computes
# to back up and (b) the paths actually written — a single source of truth, current environment,
# every time.
def _install_services():
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    import install_services
    return install_services


def _service_paths() -> List[str]:
    """What `install_services.py install` would create/update on THIS OS, in the CURRENT
    environment — empty list (no-op step) on macOS/other, where OS-level service registration
    remains the separate, explicit `bash scripts/setup_simplicio.sh` (launchd) path documented in
    `docs/INSTALL_MUTATIONS.md`."""
    try:
        return _install_services().service_paths()
    except Exception:
        return []


def _service_install() -> None:
    """Actually register the service for THIS OS (best-effort — never raises; mirrors the
    `check=False` best-effort discipline `install_lib.setup_monitor()` already uses for the
    same call)."""
    try:
        svc = _install_services()
        osname = svc.platform.system()
        if osname == "Linux":
            svc.linux_install()
        elif osname == "Windows":
            svc.windows_install()
        elif osname == "Darwin":
            svc.macos_note()
    except Exception as e:
        print("! service step failed (best-effort, no partial OS state expected): %s" % e)


def _service_uninstall() -> None:
    try:
        svc = _install_services()
        osname = svc.platform.system()
        if osname == "Linux":
            svc.linux_uninstall()
        elif osname == "Windows":
            svc.windows_uninstall()
    except Exception:
        pass

MANIFEST_SCHEMA = "simplicio.install-manifest/v1"


def _manifest_path(target: str) -> str:
    return os.path.join(target, ".simplicio-loop", "manifest.json")


def _read_manifest(target: str) -> Optional[Dict[str, Any]]:
    path = _manifest_path(target)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None  # corrupt/unreadable manifest is treated as "no prior manifest known"


def _write_manifest(target: str, manifest: Dict[str, Any]) -> str:
    path = _manifest_path(target)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, sort_keys=True, default=str)
    return path


def resolved_installer_version() -> str:
    """Best-effort resolved version of the simplicio-loop package driving this install, for the
    manifest's `version` field (#293 §4, "resolver versões a partir do release manifest único").
    Falls back through importlib.metadata -> the package's own __version__ constant -> "unknown"
    so a dev checkout without the package installed still produces a usable (if generic) manifest
    instead of raising."""
    try:
        import importlib.metadata as _im
        return _im.version("simplicio-loop")
    except Exception:
        pass
    try:
        sys.path.insert(0, os.path.dirname(HERE))
        import simplicio_loop  # noqa: E402
        return getattr(simplicio_loop, "__version__", "unknown")
    except Exception:
        return "unknown"


def _stale_skills(target: str, current_skills: List[str]) -> List[str]:
    """Skills recorded in a PRIOR manifest that are no longer part of the currently-declared
    skill set — leftovers from an older release (N-1) that a plain re-copy would never remove,
    since `copy_skills()` only ever ADDS/UPDATES paths it knows about (#293 §4: "eliminar extras
    inexistentes"). Only ever returns names the prior manifest itself claims IT installed —
    never anything the manifest doesn't know about (no guessing at foreign directories)."""
    manifest = _read_manifest(target)
    if not manifest:
        return []
    old_skills = set(manifest.get("skills", []))
    return sorted(old_skills - set(current_skills))


class InstallTransactionError(RuntimeError):
    """Raised when an applied transaction had to be rolled back. `.receipt` carries the full
    ROLLED_BACK receipt (already persisted to disk) for the caller to inspect/print."""

    def __init__(self, message: str, receipt: Dict[str, Any]):
        super().__init__(message)
        self.receipt = receipt


def _receipts_dir(target: str) -> str:
    return os.path.join(target, ".simplicio-loop", "receipts")


def _backups_dir(target: str, transaction_id: str) -> str:
    return os.path.join(target, ".simplicio-loop", "backups", transaction_id)


def _hash_path(path: str) -> Optional[str]:
    """Deterministic content hash of a file or directory tree; None if the path doesn't exist."""
    if not os.path.exists(path):
        return None
    h = hashlib.sha256()
    if os.path.isdir(path):
        for root, dirs, files in os.walk(path):
            dirs.sort()
            for fn in sorted(files):
                fp = os.path.join(root, fn)
                rel = os.path.relpath(fp, path).replace(os.sep, "/")
                h.update(rel.encode("utf-8"))
                try:
                    with open(fp, "rb") as f:
                        h.update(f.read())
                except OSError:
                    pass  # unreadable file (permissions/symlink race) — hash what we can
    else:
        with open(path, "rb") as f:
            h.update(f.read())
    return h.hexdigest()


def _backup(path: str, backup_root: str, key: str) -> Optional[str]:
    """Copy `path` into `backup_root/key` before it is mutated. No-op (returns None) if `path`
    doesn't exist yet — there is nothing to preserve for a path this transaction is about to
    CREATE (rollback of a create is `_remove`, not a restore)."""
    if not os.path.exists(path):
        return None
    dst = os.path.join(backup_root, key)
    os.makedirs(os.path.dirname(dst) or backup_root, exist_ok=True)
    if os.path.isdir(path):
        shutil.copytree(path, dst, dirs_exist_ok=True)
    else:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(path, dst)
    return dst


def _remove(path: str) -> None:
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path, ignore_errors=True)
    elif os.path.exists(path) or os.path.islink(path):
        try:
            os.remove(path)
        except OSError:
            pass


def _remove_and_prune(path: str, target: str) -> None:
    """Remove `path` (a freshly-created effect being rolled back) and then prune any now-empty
    parent directories up to (but never including) `target` itself — e.g. an empty
    `.claude/skills/` and `.claude/` left behind after every skill under it is removed. Never
    touches a directory that still has content (another effect may still live there)."""
    _remove(path)
    target_norm = os.path.normpath(target)
    d = os.path.normpath(os.path.dirname(path))
    while d != target_norm and len(d) > len(target_norm) and d.startswith(target_norm):
        try:
            if not os.path.isdir(d) or os.listdir(d):
                break
            os.rmdir(d)
        except OSError:
            break
        d = os.path.normpath(os.path.dirname(d))


def _restore(path: str, backup_path: Optional[str]) -> None:
    """Put `path` back to exactly what it was before the transaction: remove whatever is there
    now, then copy the backup back (if one was taken — a path with no backup simply didn't exist
    before, so restoring it means leaving it absent)."""
    _remove(path)
    if backup_path and os.path.exists(backup_path):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        if os.path.isdir(backup_path):
            shutil.copytree(backup_path, path)
        else:
            shutil.copy2(backup_path, path)


def _write_receipt(target: str, transaction_id: str, receipt: Dict[str, Any]) -> str:
    d = _receipts_dir(target)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, transaction_id + ".json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(receipt, f, indent=2, sort_keys=True, default=str)
    return path


def _step_paths(target: str, is_global: bool, runtime: str, mode: str,
                stale_skills: Optional[List[str]] = None,
                with_service: bool = False) -> "Dict[str, List[str]]":
    cfg = _lib.RUNTIMES[runtime]
    paths: Dict[str, List[str]] = {
        "skills": [os.path.join(target, ".claude", "skills", s) for s in _lib.SKILLS],
        "hooks": [_lib.hooks_dir(target, is_global)],
        "scripts": [_lib.scripts_dir(target, is_global)],
    }
    if stale_skills:
        paths["reconcile"] = [os.path.join(target, ".claude", "skills", s) for s in stale_skills]
    if cfg["entry"]:
        paths["entry"] = [os.path.join(target, cfg["entry"])]
    if cfg["hooks"] == "claude":
        paths["claude_settings"] = [os.path.join(target, ".claude", "settings.json")]
    if mode == "full-stack":
        full_stack_root = _lib.full_stack_dir(target, is_global)
        paths["full_stack"] = [os.path.join(full_stack_root, name) for name in ("engine", "app")]
    if with_service:
        # #293 gap 1: OS-level service registration wired into the SAME transactional
        # backup/rollback flow — instead of requiring a separate, easy-to-forget manual
        # `python3 scripts/install_services.py install` step after apply() returns. Only ever
        # runs when the SAME explicit `--with-service` consent the planner already requires is
        # given (see build_plan's permissions_required/blocked_reasons gate above this call);
        # [] on macOS/other (see _service_paths()) makes this a documented no-op there, not a
        # silent skip.
        paths["service"] = _service_paths()
    return paths


def _run_step(step: str, target: str, is_global: bool, runtime: str,
             stale_skills: Optional[List[str]] = None) -> None:
    cfg = _lib.RUNTIMES[runtime]
    if step == "reconcile":
        # Version reconciliation (#293 §4): remove skill directories the PRIOR manifest recorded
        # as installed but that the current release no longer declares. Backup/rollback of these
        # paths is handled generically by apply()'s _backup()/_restore() — same as any other
        # step — so an upgrade that fails partway restores the stale N-1 content exactly.
        for name in (stale_skills or []):
            _remove_and_prune(os.path.join(target, ".claude", "skills", name), target)
    elif step == "skills":
        _lib.copy_skills(target)
    elif step == "hooks":
        _lib.copy_hooks(target, is_global)
    elif step == "scripts":
        _lib.copy_scripts(target, is_global)
    elif step == "entry":
        _lib.ensure_entry(target, cfg["entry"], runtime)
    elif step == "claude_settings":
        _lib.merge_claude_hooks(target, is_global)
    elif step == "full_stack":
        # File-surface only: operator/capture-proxy/dashboard CODE lands on disk here, reversibly,
        # under the same backup/rollback discipline as every other step. Actually registering it
        # as an OS-level auto-start service is the separate "service" step below.
        _lib.copy_full_stack(target, is_global)
    elif step == "service":
        # #293 gap 1: actually REGISTER the OS-level auto-start service (systemd --user unit on
        # Linux, Startup-folder shim on Windows; macOS stays the documented separate
        # `setup_simplicio.sh` launchd path — install_services.py itself is a no-op there).
        _service_install()
    else:
        raise ValueError("unknown install step: %r" % step)


def apply(runtime: str, *, target: str, is_global: bool = False, mode: str = "minimal",
         with_service: bool = False, with_proxy: bool = False,
         fail_step: Optional[str] = None) -> Dict[str, Any]:
    """Apply the plan for `runtime` into `target`, transactionally — file effects (skills/hooks/
    scripts/entry/settings, + `engine`/`app` in full-stack mode) AND, when `with_service=True`,
    the real OS-level service registration too (#293 gap 1: systemd `--user` unit on Linux,
    Startup-folder shim on Windows — see the `"service"` step; macOS stays the separate, documented
    `bash scripts/setup_simplicio.sh` path).

    Returns the persisted receipt (status APPLIED) on success. On any failure — including the
    planner itself returning BLOCKED (e.g. an ungated break-system-packages permission, or
    mode="full-stack" without the explicit `with_service`/`with_proxy` consent it requires) — no
    partial state is left: either nothing ran yet (BLOCKED, returned as-is, never persisted as a
    transaction) or every step that DID commit is undone (including uninstalling any service that
    was registered) and `InstallTransactionError` is raised with the ROLLED_BACK receipt attached.

    `with_service`: explicit consent that ALSO governs the real service registration step in
    every mode (not just full-stack) — the SAME flag `install_plan.build_plan` already reports
    under `permissions_required`. `with_proxy`: together with `with_service`, the explicit consent
    required to move mode="full-stack" out of BLOCKED (see `build_plan`'s `full_stack_confirmation`
    gate — the mode name alone is never treated as consent).

    `fail_step`: test-only. Raise a synthetic failure right before the named step would run, to
    prove rollback undoes every step that already committed. Never set this in a real install —
    it exists so tests can simulate "the process died mid-install" without needing to actually
    crash the interpreter.
    """
    scope = "user" if is_global else "project"
    plan = build_plan(runtime, mode=mode, scope=scope, target=target,
                      with_service=with_service, with_proxy=with_proxy)
    if plan["status"] == "BLOCKED":
        return plan  # planner refused before any mutation — nothing to roll back

    transaction_id = plan["transaction_id"]
    backup_root = _backups_dir(target, transaction_id)
    prior_manifest = _read_manifest(target)
    stale = _stale_skills(target, _lib.SKILLS)
    step_paths = _step_paths(target, is_global, runtime, mode, stale_skills=stale,
                             with_service=with_service)
    order = [s for s in STEP_ORDER if s in step_paths]

    applied: List[Tuple[str, str, Optional[str], Optional[str]]] = []
    receipt: Dict[str, Any] = dict(plan)
    receipt["backup_path"] = backup_root
    receipt["steps"] = []
    resolved_version = resolved_installer_version()
    receipt["resolved_version"] = resolved_version
    receipt["previous_version"] = (prior_manifest or {}).get("version")
    receipt["reconciled_stale_skills"] = stale

    try:
        for step in order:
            if fail_step == step:
                raise RuntimeError("injected failure before step=%r (test hook)" % step)
            for path in step_paths[step]:
                hash_before = _hash_path(path)
                key = os.path.join(step, os.path.basename(path.rstrip(os.sep)) or "root")
                backup_path = _backup(path, backup_root, key)
                applied.append((step, path, hash_before, backup_path))
            _run_step(step, target, is_global, runtime, stale_skills=stale)
        # Manifest write is itself a tracked, backed-up, rollback-eligible step: back up whatever
        # manifest.json existed before (matching the standard hash_before/backup_path shape used
        # by every other path), THEN overwrite it — so `rollback()` restores the PRIOR manifest
        # right alongside the file effects, and a rolled-back upgrade never leaves a manifest
        # claiming the new version is installed when its files were just undone.
        manifest_path = _manifest_path(target)
        manifest_hash_before = _hash_path(manifest_path)
        manifest_backup = _backup(manifest_path, backup_root,
                                  os.path.join("manifest", "manifest.json"))
        applied.append(("manifest", manifest_path, manifest_hash_before, manifest_backup))
        _write_manifest(target, {
            "schema": MANIFEST_SCHEMA,
            "version": resolved_version,
            "previous_version": receipt["previous_version"],
            "skills": list(_lib.SKILLS),
            "runtime": runtime,
            "transaction_id": transaction_id,
            "reconciled_stale_skills": stale,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })
        receipt["steps"] = [
            {"step": s, "path": p, "hash_before": hb, "hash_after": _hash_path(p),
             "backup_path": bp}
            for s, p, hb, bp in applied
        ]
        receipt["status"] = "APPLIED"
        receipt["applied_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        _write_receipt(target, transaction_id, receipt)
        return receipt
    except Exception as e:  # noqa: BLE001 — deliberately broad: ANY failure must roll back
        _uninstalled_service = False
        for step, path, hash_before, backup_path in reversed(applied):
            if step == "service" and not _uninstalled_service:
                # Undo the OS-level registration itself (systemctl disable / remove the
                # Startup shim), not just the unit/launcher FILE — file-only restore would leave
                # a systemd unit re-materialized without ever having been (re-)enabled.
                _service_uninstall()
                _uninstalled_service = True
            if hash_before is None:
                _remove_and_prune(path, target)
            else:
                _restore(path, backup_path)
        receipt["steps"] = [
            {"step": s, "path": p, "hash_before": hb, "hash_after": None, "backup_path": bp}
            for s, p, hb, bp in applied
        ]
        receipt["status"] = "ROLLED_BACK"
        receipt["error"] = str(e)
        receipt["rolled_back_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        _write_receipt(target, transaction_id, receipt)
        # A rolled-back transaction must not leave a stale/partial manifest claiming success —
        # if the prior manifest existed, it is already untouched on disk (this function never
        # wrote a new one); if there was none, none exists now either. Nothing to undo here.
        raise InstallTransactionError(str(e), receipt) from e


def rollback(transaction_id: str, target: str) -> Dict[str, Any]:
    """Undo a previously APPLIED transaction from its persisted receipt. Idempotent: rolling
    back an already-ROLLED_BACK transaction is a no-op that just returns the receipt. Raises
    FileNotFoundError if no receipt exists for that id under `target`."""
    path = os.path.join(_receipts_dir(target), transaction_id + ".json")
    if not os.path.exists(path):
        raise FileNotFoundError(
            "no install receipt for transaction %r under %s" % (transaction_id, target))
    with open(path, encoding="utf-8") as f:
        receipt = json.load(f)
    if receipt.get("status") == "ROLLED_BACK":
        return receipt
    _uninstalled_service = False
    for entry in reversed(receipt.get("steps", [])):
        if entry.get("step") == "service" and not _uninstalled_service:
            _service_uninstall()
            _uninstalled_service = True
        if entry.get("hash_before") is None:
            _remove_and_prune(entry["path"], target)
        else:
            _restore(entry["path"], entry.get("backup_path"))
    receipt["status"] = "ROLLED_BACK"
    receipt["rolled_back_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _write_receipt(target, transaction_id, receipt)
    return receipt


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Apply or roll back a simplicio-loop install transaction.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_apply = sub.add_parser("apply", help="apply the file effects for a runtime into --target")
    p_apply.add_argument("runtime")
    p_apply.add_argument("--target", required=True)
    p_apply.add_argument("--global", dest="is_global", action="store_true")
    p_apply.add_argument("--mode", default="minimal")
    p_apply.add_argument("--with-service", action="store_true",
                         help="explicit consent for service registration (required, with "
                              "--with-proxy, to unblock --mode full-stack)")
    p_apply.add_argument("--with-proxy", action="store_true",
                         help="explicit consent for proxy/base-URL wiring (required, with "
                              "--with-service, to unblock --mode full-stack)")
    p_apply.add_argument("--test-fail-step", default=None, help=argparse.SUPPRESS)

    p_rollback = sub.add_parser("rollback", help="roll back a transaction id under --target")
    p_rollback.add_argument("transaction_id")
    p_rollback.add_argument("--target", required=True)

    args = parser.parse_args(argv)
    if args.command == "apply":
        try:
            receipt = apply(args.runtime, target=args.target, is_global=args.is_global,
                           mode=args.mode, with_service=args.with_service,
                           with_proxy=args.with_proxy, fail_step=args.test_fail_step)
        except InstallTransactionError as e:
            print(json.dumps(e.receipt, indent=2, sort_keys=True, default=str))
            return 4
        print(json.dumps(receipt, indent=2, sort_keys=True, default=str))
        return 0 if receipt["status"] != "BLOCKED" else 3
    else:
        try:
            receipt = rollback(args.transaction_id, args.target)
        except FileNotFoundError as e:
            print("! %s" % e)
            return 3
        print(json.dumps(receipt, indent=2, sort_keys=True, default=str))
        return 0


if __name__ == "__main__":
    sys.exit(main())
