"""Fail-closed candidate transaction and promotion primitives (issue #118).

The module is deliberately independent of the LLM and of git's index.  A
candidate is built in an isolated directory, a receipt freezes the candidate
and the repository base, and promotion is the only operation allowed to touch
the worktree.  Every mutation is journaled so a partial promotion can be
rolled back or recovered deterministically.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

SCHEMA = "simplicio.transaction/v1"
_TAIL = 4000
_COMMAND_PLACEHOLDERS = {
    "",
    "echo 'configure SIMPLICIO_TEST_CMD'",
    'echo "configure SIMPLICIO_TEST_CMD"',
}


class TransactionError(RuntimeError):
    """Base class for transaction failures."""


class DirtyWorktreeError(TransactionError):
    pass


class ReceiptError(TransactionError):
    pass


class ConcurrentModificationError(TransactionError):
    pass


class UnsafePathError(TransactionError):
    pass


def _normalized_commands(commands: Iterable[object]) -> tuple[str, ...]:
    return tuple(str(item).strip() for item in commands)


def _validated_receipt_commands(
    commands: Iterable[object],
    exit_codes: Iterable[object],
    *,
    require_promotable: bool,
) -> tuple[tuple[str, ...], tuple[int, ...]]:
    normalized_commands = _normalized_commands(commands)
    normalized_exit_codes = tuple(int(str(item).strip()) for item in exit_codes)
    if len(normalized_commands) != len(normalized_exit_codes):
        raise ReceiptError("transaction receipt commands/exit_codes length mismatch")
    if any(not command for command in normalized_commands):
        raise ReceiptError("transaction receipt contains an empty command")
    if require_promotable:
        if not normalized_commands:
            raise ReceiptError("cannot promote without a verification command receipt")
        if any(command in _COMMAND_PLACEHOLDERS for command in normalized_commands):
            raise ReceiptError("cannot promote placeholder verification command")
    return normalized_commands, normalized_exit_codes


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative(path: str | os.PathLike[str]) -> str:
    value = str(path).replace("\\", "/")
    candidate = Path(value)
    if candidate.is_absolute() or value.startswith("/"):
        raise UnsafePathError(f"absolute path is outside transaction scope: {path}")
    parts = [part for part in value.split("/") if part not in ("", ".")]
    if any(part == ".." for part in parts):
        raise UnsafePathError(f"path traversal is outside transaction scope: {path}")
    if not parts:
        raise UnsafePathError("empty transaction path")
    return "/".join(parts)


def _inside(root: Path, relative: str) -> Path:
    safe = _relative(relative)
    target = (root / Path(safe)).resolve(strict=False)
    root_resolved = root.resolve()
    try:
        target.relative_to(root_resolved)
    except ValueError as exc:
        raise UnsafePathError(f"path escapes transaction root: {relative}") from exc
    # A pre-existing symlink is not an allowed promotion target.  Resolving
    # first makes links that point outside the root fail closed.
    current = root_resolved
    for part in Path(safe).parts:
        current = current / part
        if current.is_symlink():
            raise UnsafePathError(f"symlink promotion target is not allowed: {relative}")
    return root / Path(safe)


def _tree_digest(root: Path, paths: Iterable[str] | None = None) -> str:
    rows: list[tuple[str, str]] = []
    selected = sorted({_relative(path) for path in paths}) if paths is not None else None
    if selected is None:
        for item in root.rglob("*"):
            if item.is_file() and ".git" not in item.parts and ".simplicio" not in item.parts:
                selected = selected or []
                selected.append(item.relative_to(root).as_posix())
        selected = sorted(set(selected or []))
    for relative in selected:
        item = _inside(root, relative)
        rows.append((relative, sha256_file(item) if item.is_file() else "<missing>"))
    payload = "\n".join(f"{path}:{digest}" for path, digest in rows).encode()
    return sha256_bytes(payload)


def _git_dirty(root: Path) -> bool:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=root,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return False
    return bool(result.stdout.strip())


@dataclass(frozen=True)
class FileReceipt:
    path: str
    before_sha256: str | None
    after_sha256: str | None
    existed_before: bool
    existed_after: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "before_sha256": self.before_sha256,
            "after_sha256": self.after_sha256,
            "existed_before": self.existed_before,
            "existed_after": self.existed_after,
        }


@dataclass(frozen=True)
class VerificationReceipt:
    transaction_id: str
    base_sha: str
    candidate_sha: str
    files: tuple[FileReceipt, ...]
    commands: tuple[str, ...] = ()
    exit_codes: tuple[int, ...] = ()
    stdout_tail: str = ""
    stderr_tail: str = ""
    created_at: int = field(default_factory=lambda: int(time.time()))

    @property
    def digest(self) -> str:
        payload = json.dumps(self.to_dict(include_digest=False), sort_keys=True, separators=(",", ":"))
        return sha256_bytes(payload.encode())

    def to_dict(self, *, include_digest: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema": SCHEMA,
            "transaction_id": self.transaction_id,
            "base_sha": self.base_sha,
            "candidate_sha": self.candidate_sha,
            "files": [item.to_dict() for item in self.files],
            "commands": list(self.commands),
            "exit_codes": list(self.exit_codes),
            "stdout_tail": self.stdout_tail[-_TAIL:],
            "stderr_tail": self.stderr_tail[-_TAIL:],
            "created_at": self.created_at,
        }
        if include_digest:
            payload["receipt_digest"] = self.digest
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> VerificationReceipt:
        if payload.get("schema") != SCHEMA:
            raise ReceiptError("unsupported transaction receipt schema")
        try:
            raw_files = payload.get("files")
            raw_commands = payload.get("commands", [])
            raw_exit_codes = payload.get("exit_codes", [])
            if not isinstance(raw_files, list) or not isinstance(raw_commands, list):
                raise TypeError("receipt arrays are malformed")
            if not isinstance(raw_exit_codes, list):
                raise TypeError("receipt exit codes are malformed")
            commands, exit_codes = _validated_receipt_commands(
                raw_commands,
                raw_exit_codes,
                require_promotable=False,
            )
            files = tuple(
                FileReceipt(
                    path=_relative(str(cast(dict[str, Any], item)["path"])),
                    before_sha256=cast(dict[str, Any], item).get("before_sha256"),
                    after_sha256=cast(dict[str, Any], item).get("after_sha256"),
                    existed_before=bool(cast(dict[str, Any], item)["existed_before"]),
                    existed_after=bool(cast(dict[str, Any], item)["existed_after"]),
                )
                for item in raw_files
            )
            receipt = cls(
                transaction_id=str(payload["transaction_id"]),
                base_sha=str(payload["base_sha"]),
                candidate_sha=str(payload["candidate_sha"]),
                files=files,
                commands=commands,
                exit_codes=exit_codes,
                stdout_tail=str(payload.get("stdout_tail", "")),
                stderr_tail=str(payload.get("stderr_tail", "")),
                created_at=int(cast(int | str, payload.get("created_at", 0))),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ReceiptError("malformed transaction receipt") from exc
        if payload.get("receipt_digest") != receipt.digest:
            raise ReceiptError("transaction receipt digest mismatch")
        return receipt


@dataclass
class Transaction:
    root: Path
    candidate: Path
    transaction_id: str
    dirty_policy: str
    base_sha: str
    initial_sha: str
    journal: Path
    _promoted: bool = False

    def _append(self, event: str, **data: object) -> None:
        self.journal.parent.mkdir(parents=True, exist_ok=True)
        with self.journal.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"event": event, "at": int(time.time()), **data}, sort_keys=True) + "\n")

    def receipt(
        self,
        paths: Iterable[str],
        *,
        commands: Iterable[str] = (),
        exit_codes: Iterable[int] = (),
        stdout: str = "",
        stderr: str = "",
    ) -> VerificationReceipt:
        safe_paths = tuple(sorted({_relative(path) for path in paths}))
        normalized_commands, normalized_exit_codes = _validated_receipt_commands(
            commands,
            exit_codes,
            require_promotable=False,
        )
        files = []
        for relative in safe_paths:
            before = _inside(self.root, relative)
            after = _inside(self.candidate, relative)
            files.append(
                FileReceipt(
                    relative,
                    sha256_file(before) if before.is_file() else None,
                    sha256_file(after) if after.is_file() else None,
                    before.is_file(),
                    after.is_file(),
                )
            )
        receipt = VerificationReceipt(
            self.transaction_id,
            self.base_sha,
            _tree_digest(self.candidate, safe_paths),
            tuple(files),
            normalized_commands,
            normalized_exit_codes,
            stdout[-_TAIL:],
            stderr[-_TAIL:],
        )
        self._append(
            "receipt",
            digest=receipt.digest,
            candidate_sha=receipt.candidate_sha,
            receipt=receipt.to_dict(),
        )
        return receipt

    def promote(self, receipt: VerificationReceipt) -> None:
        if receipt.transaction_id != self.transaction_id or receipt.base_sha != self.base_sha:
            raise ReceiptError("receipt is not bound to this transaction/base")
        _validated_receipt_commands(receipt.commands, receipt.exit_codes, require_promotable=True)
        if any(code != 0 for code in receipt.exit_codes):
            raise ReceiptError("cannot promote a receipt with a failing command")
        paths = [item.path for item in receipt.files]
        for item in receipt.files:
            current = _inside(self.root, item.path)
            exists_now = current.is_file()
            if exists_now != item.existed_before:
                raise ConcurrentModificationError(
                    f"repository changed after transaction began for promoted path: {item.path}"
                )
            current_sha = sha256_file(current) if exists_now else None
            if current_sha != item.before_sha256:
                raise ConcurrentModificationError(
                    f"repository changed after transaction began for promoted path: {item.path}"
                )
        if _tree_digest(self.candidate, paths) != receipt.candidate_sha:
            raise ReceiptError("candidate changed after verification")
        backup = self.journal.with_suffix(".backup")
        backup.mkdir(parents=True, exist_ok=True)
        self._append("promotion-start", files=paths)
        try:
            for item in receipt.files:
                target = _inside(self.root, item.path)
                source = _inside(self.candidate, item.path)
                backup_target = backup / Path(item.path)
                backup_target.parent.mkdir(parents=True, exist_ok=True)
                if target.is_file():
                    shutil.copy2(target, backup_target)
                elif target.exists():
                    raise UnsafePathError(f"non-file target cannot be promoted: {item.path}")
                if source.is_file():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    temporary = target.with_name(target.name + f".simplicio-tmp-{self.transaction_id}")
                    shutil.copy2(source, temporary)
                    os.replace(temporary, target)
                elif target.exists():
                    target.unlink()
            self._promoted = True
            self._append("promotion-committed", files=paths)
        except Exception:
            self.rollback(receipt)
            raise

    def rollback(self, receipt: VerificationReceipt | None = None) -> None:
        backup = self.journal.with_suffix(".backup")
        if receipt is None:
            receipt = self._receipt_from_journal()
        if receipt:
            for item in receipt.files:
                target = _inside(self.root, item.path)
                saved = backup / Path(item.path)
                if saved.is_file():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(saved, target)
                elif target.exists() and not item.existed_before:
                    target.unlink()
        self._append("rollback", files=[item.path for item in receipt.files] if receipt else [])

    def _receipt_from_journal(self) -> VerificationReceipt | None:
        if not self.journal.is_file():
            return None
        latest: VerificationReceipt | None = None
        for line in self.journal.read_text(encoding="utf-8").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("event") == "receipt" and isinstance(event.get("receipt"), dict):
                try:
                    latest = VerificationReceipt.from_dict(event["receipt"])
                except ReceiptError:
                    continue
        return latest


def begin_transaction(
    root: str | os.PathLike[str],
    *,
    dirty_policy: str = "reject",
    transaction_id: str | None = None,
    candidate: str | os.PathLike[str] | None = None,
) -> Transaction:
    root_path = Path(root).resolve()
    if dirty_policy not in {"reject", "preserve"}:
        raise ValueError("dirty_policy must be 'reject' or 'preserve'")
    if dirty_policy == "reject" and _git_dirty(root_path):
        raise DirtyWorktreeError("worktree is dirty; use dirty_policy='preserve' explicitly")
    candidate_path = (
        Path(candidate).resolve() if candidate else Path(tempfile.mkdtemp(prefix="simplicio-tx-"))
    )
    candidate_path.mkdir(parents=True, exist_ok=True)
    tx_id = transaction_id or f"tx-{uuid.uuid4().hex}"
    base_sha = _tree_digest(root_path)
    journal = root_path / ".simplicio" / "transactions" / f"{tx_id}.jsonl"
    tx = Transaction(root_path, candidate_path, tx_id, dirty_policy, base_sha, base_sha, journal)
    tx._append("begin", dirty_policy=dirty_policy, base_sha=base_sha, candidate=str(candidate_path))
    return tx


__all__ = [
    "ConcurrentModificationError",
    "DirtyWorktreeError",
    "FileReceipt",
    "ReceiptError",
    "SCHEMA",
    "Transaction",
    "TransactionError",
    "UnsafePathError",
    "VerificationReceipt",
    "begin_transaction",
    "sha256_file",
]
