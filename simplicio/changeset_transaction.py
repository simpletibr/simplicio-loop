"""Local, recoverable transaction boundary for validated changesets."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

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
    if previous.get("state") == "COMMITTED" and isinstance(previous.get("result"), dict):
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
            raise ChangesetTransactionError("REPLAY_CONFLICT", "idempotency key is bound to another changeset")
        if state.get("state") == "COMMITTED" and isinstance(state.get("result"), dict):
            result = dict(state["result"])
            result["replayed"] = True
            return result
        if state.get("state") not in {"STAGED", "COMMITTING", "ROLLING_BACK"}:
            raise ChangesetTransactionError("RECOVERY_NOT_REQUIRED", "transaction has no recoverable commit")

        before = state.get("before")
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
        if previous.get("state") == "COMMITTED" and isinstance(previous.get("result"), dict):
            replay = dict(previous["result"])
            replay["replayed"] = True
            return replay
        raise ChangesetTransactionError("RECOVERY_REQUIRED", "transaction requires recovery before replay")

    paths = _paths(plan)
    before: dict[str, str | None] = {}
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
    _write_state(state_path, state)
    try:
        for relative in paths:
            source = _safe_path(root_path, relative)
            before[relative] = _hash(source)
            if source.is_file():
                target = _safe_path(candidate, relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
        state["state"] = "STAGED"
        state["before"] = before
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
        backup.mkdir(parents=True, exist_ok=True)
        for relative in paths:
            target = _safe_path(root_path, relative)
            staged = _safe_path(candidate, relative)
            saved = _safe_path(backup, relative)
            if target.is_file():
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, saved)
            if staged.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_name(f".{target.name}.{idempotency_key}.tmp")
                shutil.copy2(staged, temporary)
                os.replace(temporary, target)
            elif target.exists():
                target.unlink()
        after = {relative: _hash(_safe_path(root_path, relative)) for relative in paths}
        receipt = {
            "schema": TRANSACTION_SCHEMA,
            "idempotency_key": idempotency_key,
            "changeset_digest": changeset_digest_value,
            "state": "COMMITTED",
            "files": [
                {"path": relative, "before_sha256": before[relative], "after_sha256": after[relative]}
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
        state.update({"state": "COMMITTED", "after": after, "receipt": receipt, "result": result_payload})
        _write_state(state_path, state)
        return result_payload
    except ChangesetTransactionError:
        raise
    except Exception as exc:
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
            state["state"] = "ROLLED_BACK"
            _write_state(state_path, state)
        except Exception as rollback_error:
            state["state"] = "ROLLBACK_FAILED"
            state["rollback_error"] = type(rollback_error).__name__
            _write_state(state_path, state)
            raise ChangesetTransactionError(
                "ROLLBACK_FAILED", "transaction rollback could not be proven"
            ) from rollback_error
        raise ChangesetTransactionError("COMMIT_PARTIAL", "transaction failed and was rolled back") from exc
    finally:
        shutil.rmtree(candidate, ignore_errors=True)
        shutil.rmtree(backup, ignore_errors=True)
