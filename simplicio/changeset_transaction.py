"""Local, recoverable transaction boundary for validated changesets."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
import time
from pathlib import Path
from typing import Any, NoReturn

from .mechanical_edit import execute_plan
from .utils.fs import write_text_atomic

TRANSACTION_SCHEMA = "simplicio.fast.changeset-transaction/v1"


class ChangesetTransactionError(ValueError):
    def __init__(self, code: str, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.code = code
        self.extra = extra


def changeset_digest(changeset: dict[str, Any]) -> str:
    payload = json.dumps(changeset, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _hash(path: Path) -> str | None:
    if not path.exists():
        return None
    if not path.is_file() or path.is_symlink():
        raise ChangesetTransactionError(
            "PATH_UNAUTHORIZED", f"transaction target is not a regular file: {path}"
        )
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _mode(path: Path) -> int | None:
    """Return portable permission bits for a regular file, if it exists."""

    if not path.exists():
        return None
    if not path.is_file() or path.is_symlink():
        raise ChangesetTransactionError(
            "PATH_UNAUTHORIZED", f"transaction target is not a regular file: {path}"
        )
    return stat.S_IMODE(path.stat().st_mode)


def _safe_path(root: Path, relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts or not relative:
        raise ChangesetTransactionError("PATH_UNAUTHORIZED", f"unsafe transaction path: {relative}")
    target = (root / candidate).resolve(strict=False)
    if not target.is_relative_to(root.resolve()):
        raise ChangesetTransactionError("PATH_UNAUTHORIZED", f"path escapes transaction root: {relative}")
    current = root.resolve()
    for part in candidate.parts:
        current /= part
        if current.is_symlink():
            raise ChangesetTransactionError("PATH_UNAUTHORIZED", f"symlink target is not allowed: {relative}")
    return root / candidate


def _paths(plan: dict[str, Any]) -> list[str]:
    values = {str(path) for path in plan.get("touched_files", []) if isinstance(path, str)}
    for operation in plan.get("operations", []):
        if not isinstance(operation, dict):
            continue
        for key in ("path", "dest"):
            if isinstance(operation.get(key), str):
                values.add(operation[key])
    return sorted(values)


def _state_path(root: Path, key: str) -> Path:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return root / ".simplicio" / "changeset-transactions" / f"{digest}.json"


def _write_state(path: Path, state: dict[str, Any]) -> None:
    write_text_atomic(path, json.dumps(state, sort_keys=True, indent=2) + "\n")


def _pause_for_fault_injection(point: str) -> None:
    """Pause only when an explicit test harness requests a crash window."""

    if os.environ.get("SIMPLICIO_TRANSACTION_PAUSE_AT") != point:
        return
    seconds = float(os.environ.get("SIMPLICIO_TRANSACTION_PAUSE_SECONDS", "30"))
    time.sleep(max(0.0, seconds))


def existing_transaction_result(
    root: str | Path,
    *,
    idempotency_key: str,
    changeset_digest_value: str,
) -> dict[str, Any] | None:
    path = _state_path(Path(root).resolve(), idempotency_key)
    if not path.is_file():
        return None
    try:
        previous = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ChangesetTransactionError("RECOVERY_REQUIRED", "transaction journal is unreadable") from exc
    if previous.get("changeset_digest") != changeset_digest_value:
        raise ChangesetTransactionError("REPLAY_CONFLICT", "idempotency key is bound to another changeset")
    if previous.get("state") in {"COMMITTED", "FAILED_BEFORE_COMMIT"} and isinstance(
        previous.get("result"), dict
    ):
        result = dict(previous["result"])
        result["replayed"] = True
        return result
    raise ChangesetTransactionError("RECOVERY_REQUIRED", "transaction requires recovery before replay")


def _result_with_transaction(result: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    result["transaction"] = {
        "schema": TRANSACTION_SCHEMA,
        "idempotency_key": state["idempotency_key"],
        "changeset_digest": state["changeset_digest"],
        "state": state["state"],
        "receipt_path": state["receipt_path"],
    }
    return result


def _rollback_after_commit_failure(
    *,
    root_path: Path,
    before: dict[str, str | None],
    before_modes: dict[str, int | None],
    backup: Path,
    state: dict[str, Any],
    state_path: Path,
    cause: BaseException,
) -> NoReturn:
    """Restore the pre-commit snapshot and raise a typed partial-commit error."""
    state["state"] = "ROLLING_BACK"
    _write_state(state_path, state)
    try:
        for relative, digest in before.items():
            target = _safe_path(root_path, relative)
            saved = _safe_path(backup, relative)
            if digest is None:
                if target.exists():
                    target.unlink()
            elif saved.is_file():
                shutil.copy2(saved, target)
                if before_modes.get(relative) is not None:
                    os.chmod(target, int(before_modes[relative]))
        state["state"] = "ROLLED_BACK"
        _write_state(state_path, state)
    except Exception as rollback_error:
        state["state"] = "ROLLBACK_FAILED"
        state["rollback_error"] = type(rollback_error).__name__
        _write_state(state_path, state)
        raise ChangesetTransactionError(
            "ROLLBACK_FAILED", "transaction rollback could not be proven"
        ) from rollback_error
    raise ChangesetTransactionError("COMMIT_PARTIAL", "transaction failed and was rolled back") from cause


def recover_changeset_transaction(
    root: str | Path,
    *,
    idempotency_key: str,
    changeset_digest_value: str,
) -> dict[str, Any]:
    """Restore a journal left before COMMITTED and prove the old hashes."""
    root_path = Path(root).resolve()
    state_path = _state_path(root_path, idempotency_key)
    lock_path = state_path.with_suffix(".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(f"pid={os.getpid()}\n")
    except FileExistsError as exc:
        raise ChangesetTransactionError(
            "TRANSACTION_BUSY", "another process owns this idempotency key"
        ) from exc
    try:
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ChangesetTransactionError("RECOVERY_REQUIRED", "transaction journal is unreadable") from exc
        if state.get("changeset_digest") != changeset_digest_value:
            raise ChangesetTransactionError(
                "REPLAY_CONFLICT", "idempotency key is bound to another changeset"
            )
        if state.get("state") == "COMMITTED" and isinstance(state.get("result"), dict):
            result = dict(state["result"])
            result["replayed"] = True
            return result
        if state.get("state") not in {"STAGED", "COMMITTING", "ROLLING_BACK"}:
            raise ChangesetTransactionError("RECOVERY_NOT_REQUIRED", "transaction has no recoverable commit")

        before = state.get("before")
        before_modes = state.get("before_modes", {})
        if not isinstance(before, dict):
            raise ChangesetTransactionError("RECOVERY_REQUIRED", "transaction journal has no before hashes")
        backup = Path(str(state.get("backup", "")))
        if not backup.is_absolute():
            raise ChangesetTransactionError("RECOVERY_REQUIRED", "transaction backup path is invalid")
        for relative, digest in before.items():
            target = _safe_path(root_path, str(relative))
            saved = _safe_path(backup, str(relative))
            if digest is None:
                if target.exists():
                    target.unlink()
            elif saved.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(saved, target)
                if isinstance(before_modes, dict) and before_modes.get(str(relative)) is not None:
                    os.chmod(target, int(before_modes[str(relative)]))
            else:
                raise ChangesetTransactionError(
                    "RECOVERY_REQUIRED", f"missing backup for transaction path: {relative}"
                )
        after = {str(relative): _hash(_safe_path(root_path, str(relative))) for relative in before}
        if after != {str(relative): digest for relative, digest in before.items()}:
            raise ChangesetTransactionError("RECOVERY_REQUIRED", "recovery hashes do not match the journal")
        state.update({"state": "ROLLED_BACK", "after": after, "recovered": True})
        _write_state(state_path, state)
        return {
            "status": "recovered",
            "applied": False,
            "replayed": False,
            "transaction": {
                "schema": TRANSACTION_SCHEMA,
                "idempotency_key": idempotency_key,
                "changeset_digest": changeset_digest_value,
                "state": "ROLLED_BACK",
                "receipt_path": str(state_path),
            },
        }
    finally:
        try:
            lock_path.unlink()
        except OSError:
            pass


def execute_changeset_transaction(
    plan: dict[str, Any],
    *,
    root: str | Path,
    idempotency_key: str,
    changeset_digest_value: str,
) -> dict[str, Any]:
    """Serialize one idempotency key before staging or committing it."""
    state_path = _state_path(Path(root).resolve(), idempotency_key)
    lock_path = state_path.with_suffix(".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(f"pid={os.getpid()}\n")
    except FileExistsError as exc:
        raise ChangesetTransactionError(
            "TRANSACTION_BUSY", "another process owns this idempotency key"
        ) from exc
    try:
        return _execute_changeset_transaction(
            plan,
            root=root,
            idempotency_key=idempotency_key,
            changeset_digest_value=changeset_digest_value,
        )
    finally:
        try:
            lock_path.unlink()
        except OSError:
            pass


def _execute_changeset_transaction(
    plan: dict[str, Any],
    *,
    root: str | Path,
    idempotency_key: str,
    changeset_digest_value: str,
) -> dict[str, Any]:
    """Stage, verify, commit and journal one multi-file changeset."""
    root_path = Path(root).resolve()
    state_path = _state_path(root_path, idempotency_key)
    if state_path.is_file():
        try:
            previous = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ChangesetTransactionError("RECOVERY_REQUIRED", "transaction journal is unreadable") from exc
        if previous.get("changeset_digest") != changeset_digest_value:
            raise ChangesetTransactionError(
                "REPLAY_CONFLICT", "idempotency key is bound to another changeset"
            )
        if previous.get("state") in {"COMMITTED", "FAILED_BEFORE_COMMIT"} and isinstance(
            previous.get("result"), dict
        ):
            replay = dict(previous["result"])
            replay["replayed"] = True
            return replay
        raise ChangesetTransactionError("RECOVERY_REQUIRED", "transaction requires recovery before replay")

    paths = _paths(plan)
    before: dict[str, str | None] = {}
    before_modes: dict[str, int | None] = {}
    candidate = Path(tempfile.mkdtemp(prefix=f".simplicio-tx-{idempotency_key}-", dir=root_path.parent))
    backup = candidate.with_name(candidate.name + ".backup")
    state: dict[str, Any] = {
        "schema": TRANSACTION_SCHEMA,
        "idempotency_key": idempotency_key,
        "changeset_digest": changeset_digest_value,
        "paths": paths,
        "state": "INTENT",
        "receipt_path": str(state_path),
        "candidate": str(candidate),
        "backup": str(backup),
    }
    started = time.perf_counter()
    stage_started = started
    _write_state(state_path, state)
    try:
        for relative in paths:
            source = _safe_path(root_path, relative)
            before[relative] = _hash(source)
            before_modes[relative] = _mode(source)
            if source.is_file():
                target = _safe_path(candidate, relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
        state["state"] = "STAGED"
        state["before"] = before
        state["before_modes"] = before_modes
        state["timings_ms"] = {
            "stage": round((time.perf_counter() - stage_started) * 1000, 3),
        }
        _write_state(state_path, state)

        result = execute_plan(plan, root=candidate, apply=True, allow_native=False)
        if result.get("status") != "ok":
            state["state"] = "FAILED_BEFORE_COMMIT"
            state["result"] = result
            _write_state(state_path, state)
            return _result_with_transaction(result, state)

        for relative in paths:
            if _hash(_safe_path(root_path, relative)) != before[relative]:
                raise ChangesetTransactionError(
                    "CONCURRENT_MODIFICATION", f"source changed during staging: {relative}"
                )
        state["state"] = "COMMITTING"
        _write_state(state_path, state)
        commit_started = time.perf_counter()
        backup.mkdir(parents=True, exist_ok=True)
        for relative in paths:
            target = _safe_path(root_path, relative)
            saved = _safe_path(backup, relative)
            if target.is_file():
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, saved)
        _pause_for_fault_injection("after_backup")
        for relative in paths:
            target = _safe_path(root_path, relative)
            staged = _safe_path(candidate, relative)
            if staged.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_name(f".{target.name}.{idempotency_key}.tmp")
                shutil.copy2(staged, temporary)
                os.replace(temporary, target)
                if before_modes.get(relative) is not None:
                    os.chmod(target, int(before_modes[relative]))
            elif target.exists():
                target.unlink()
        after = {relative: _hash(_safe_path(root_path, relative)) for relative in paths}
        after_modes = {relative: _mode(_safe_path(root_path, relative)) for relative in paths}
        receipt = {
            "schema": TRANSACTION_SCHEMA,
            "idempotency_key": idempotency_key,
            "changeset_digest": changeset_digest_value,
            "state": "COMMITTED",
            "timings_ms": {
                "stage": state["timings_ms"]["stage"],
                "commit": round((time.perf_counter() - commit_started) * 1000, 3),
                "total": round((time.perf_counter() - started) * 1000, 3),
            },
            "files": [
                {
                    "path": relative,
                    "before_sha256": before[relative],
                    "after_sha256": after[relative],
                    "before_mode": before_modes[relative],
                    "after_mode": after_modes[relative],
                }
                for relative in paths
                if before[relative] != after[relative]
            ],
        }
        result_payload = {
            "status": "ok",
            "applied": True,
            "noop": not receipt["files"],
            "files": receipt["files"],
            "validation": result.get("validation", []),
            "planned_diff": result.get("planned_diff", ""),
            "transaction": receipt,
        }
        state.update(
            {
                "state": "COMMITTED",
                "after": after,
                "after_modes": after_modes,
                "receipt": receipt,
                "timings_ms": receipt["timings_ms"],
                "result": result_payload,
            }
        )
        _write_state(state_path, state)
        return result_payload
    except ChangesetTransactionError as exc:
        # Validation and source-drift failures happen before the destructive
        # commit boundary. Persist the refusal so a retry/replay cannot leave
        # an orphaned STAGED journal that falsely demands recovery.
        if state["state"] in {"INTENT", "STAGED"}:
            result_payload = {
                "status": "refused",
                "applied": False,
                "noop": False,
                "files": [],
                "validation": [],
                "planned_diff": "",
                "errors": [{"code": exc.code, "message": str(exc), **exc.extra}],
            }
            state.update({"state": "FAILED_BEFORE_COMMIT", "result": result_payload})
            _write_state(state_path, state)
            return _result_with_transaction(result_payload, state)
        # Once COMMITTING has been persisted, route typed filesystem errors
        # through the same rollback path as untyped OS errors.
        _rollback_after_commit_failure(
            root_path=root_path,
            before=before,
            before_modes=before_modes,
            backup=backup,
            state=state,
            state_path=state_path,
            cause=exc,
        )
    except Exception as exc:
        _rollback_after_commit_failure(
            root_path=root_path,
            before=before,
            before_modes=before_modes,
            backup=backup,
            state=state,
            state_path=state_path,
            cause=exc,
        )
    finally:
        shutil.rmtree(candidate, ignore_errors=True)
        shutil.rmtree(backup, ignore_errors=True)
