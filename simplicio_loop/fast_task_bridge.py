"""Task-scoped binding between Loop receipts and the public Fast workspace API.

The bridge deliberately uses only ``simplicio_fast.WorkspaceStore`` public
methods.  Missing or incompatible Fast state is represented as an explicit
fallback instead of being guessed from internal snapshot files.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .fast_integration import FAST_CHANGESET_SCHEMA, FastStaleChangeset, validate_changeset

SCHEMA = "simplicio.loop.fast-task-binding/v1"


class FastTaskBridgeError(RuntimeError):
    """The task cannot be safely bound to a Fast generation."""


class FastTaskBridgeUnavailable(FastTaskBridgeError):
    """Fast's public workspace API is unavailable or incompatible."""


def _hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _value(obj: Any, *names: str, default: str = "") -> str:
    for name in names:
        value = obj.get(name) if isinstance(obj, Mapping) else getattr(obj, name, None)
        if value is not None and str(value):
            return str(value)
    return default


def _manifest_generation(manifest: Any) -> str:
    generation = _value(manifest, "generation_id", "generation")
    if not generation:
        raise FastTaskBridgeUnavailable("Fast manifest has no generation")
    return generation


@dataclass(frozen=True)
class FastTaskBinding:
    task_id: str
    attempt_id: str
    worktree_id: str
    mapper_generation: str
    mapper_context_hash: str
    base_generation: str
    overlay_generation: str
    lease_id: str
    fast_version: str
    receipt_hash: str
    refreshed_paths: tuple[str, ...] = ()
    schema: str = SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {"schema": self.schema, "task_id": self.task_id, "attempt_id": self.attempt_id,
                "worktree_id": self.worktree_id, "mapper_generation": self.mapper_generation,
                "mapper_context_hash": self.mapper_context_hash, "base_generation": self.base_generation,
                "overlay_generation": self.overlay_generation, "lease_id": self.lease_id,
                "fast_version": self.fast_version, "receipt_hash": self.receipt_hash,
                "refreshed_paths": list(self.refreshed_paths)}


class FastTaskBridge:
    """Create and refresh isolated Fast workspace bindings for Loop attempts."""

    def __init__(self, root: str | Path, *, storage: str | Path | None = None,
                 store_factory: Callable[[Path, Path | None], Any] | None = None,
                 config: Mapping[str, object] | None = None, fast_version: str = "") -> None:
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise ValueError("Fast bridge root must be a directory")
        self.storage = Path(storage).resolve() if storage else self.root / ".simplicio-loop" / "fast-storage"
        self._store_factory = store_factory or self._default_store
        self.config = dict(config or {})
        self.fast_version = fast_version
        self._store: Any | None = None
        self._base: tuple[str, str] | None = None

    @staticmethod
    def _default_store(root: Path, storage: Path | None) -> Any:
        try:
            from simplicio_fast import WorkspaceStore
        except ImportError as exc:
            raise FastTaskBridgeUnavailable("simplicio_fast WorkspaceStore is unavailable") from exc
        return WorkspaceStore(root, storage=storage)

    def _workspace(self) -> Any:
        if self._store is None:
            try:
                self._store = self._store_factory(self.root, self.storage)
            except FastTaskBridgeError:
                raise
            except Exception as exc:
                raise FastTaskBridgeUnavailable(f"Fast WorkspaceStore unavailable: {exc}") from exc
        return self._store

    def prepare(self, *, task_id: str, attempt_id: str, worktree_id: str,
                mapper_receipt: Mapping[str, Any]) -> FastTaskBinding:
        if not all(str(value).strip() for value in (task_id, attempt_id, worktree_id)):
            raise ValueError("task_id, attempt_id, and worktree_id are required")
        state = mapper_receipt.get("repo_state_after") if isinstance(mapper_receipt.get("repo_state_after"), Mapping) else {}
        mapper_generation = str(mapper_receipt.get("generation") or state.get("generation") or "")
        mapper_context_hash = str(mapper_receipt.get("context_hash") or mapper_receipt.get("context_pack_hash") or "")
        if not mapper_generation or not mapper_context_hash:
            raise FastTaskBridgeError("mapper receipt lacks generation/context binding")
        store = self._workspace()
        config_key = _hash(self.config)
        if self._base is None or self._base[0] != config_key:
            try:
                manifest = store.build_base(config=self.config or None)
            except Exception as exc:
                raise FastTaskBridgeUnavailable(f"Fast base build failed: {exc}") from exc
            base_generation = _manifest_generation(manifest)
            self._base = (config_key, base_generation)
        else:
            base_generation = self._base[1]
        try:
            lease = store.pin(base_generation, owner=f"{attempt_id}:{worktree_id}")
            overlay = store.create_overlay(worktree_id, base_generation)
        except Exception as exc:
            raise FastTaskBridgeUnavailable(f"Fast task binding failed: {exc}") from exc
        overlay_generation = _value(overlay, "overlay_generation", "generation")
        if not overlay_generation:
            raise FastTaskBridgeUnavailable("Fast overlay has no generation")
        lease_id = _value(lease, "lease_id", "id")
        payload = {"schema": SCHEMA, "task_id": task_id, "attempt_id": attempt_id,
                   "worktree_id": worktree_id, "mapper_generation": mapper_generation,
                   "mapper_context_hash": mapper_context_hash, "base_generation": base_generation,
                   "overlay_generation": overlay_generation, "lease_id": lease_id,
                   "fast_version": self.fast_version}
        payload["receipt_hash"] = _hash(payload)
        return FastTaskBinding(**payload)

    def refresh(self, binding: FastTaskBinding, changed_paths: Sequence[str]) -> FastTaskBinding:
        paths = tuple(sorted({str(path).replace("\\", "/") for path in changed_paths if str(path)}))
        if not paths:
            return binding
        store = self._workspace()
        try:
            overlay = store.refresh(binding.worktree_id, binding.base_generation, binding.overlay_generation)
        except Exception as exc:
            raise FastTaskBridgeError(f"Fast overlay refresh failed: {exc}") from exc
        generation = _value(overlay, "overlay_generation", "generation")
        if not generation:
            raise FastTaskBridgeError("Fast refresh returned no overlay generation")
        payload = binding.to_dict()
        payload.update({"overlay_generation": generation, "refreshed_paths": list(paths)})
        payload["receipt_hash"] = _hash({key: value for key, value in payload.items() if key != "receipt_hash"})
        payload["refreshed_paths"] = tuple(paths)
        return FastTaskBinding(**{key: payload[key] for key in FastTaskBinding.__dataclass_fields__})

    def release(self, binding: FastTaskBinding) -> None:
        if binding.lease_id:
            self._workspace().release_lease(binding.lease_id)

    @staticmethod
    def validate_changeset(binding: FastTaskBinding, changeset: Mapping[str, Any]) -> dict[str, Any]:
        try:
            return validate_changeset(changeset, generation=binding.overlay_generation,
                                     context_hash=binding.mapper_context_hash)
        except FastStaleChangeset:
            raise
        except Exception as exc:
            raise FastTaskBridgeError(f"invalid Fast changeset: {exc}") from exc


__all__ = ["SCHEMA", "FastTaskBinding", "FastTaskBridge", "FastTaskBridgeError",
           "FastTaskBridgeUnavailable", "FAST_CHANGESET_SCHEMA"]
