"""Typed preparation of the immutable input identity for the task pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from os import PathLike
from pathlib import Path
from typing import Any

from .atomic_execution import AttemptContext


@dataclass(frozen=True)
class PipelineInput:
    """Canonical roots and identity fields consumed by pipeline stages."""

    actual_root: Path
    declared_repo_root: Path
    declared_scope_root: str | PathLike[str]
    canonical_snapshot_id: str
    canonical_pack_hash: str
    supplied_snapshot_id: str | None
    supplied_pack_hash: str | None
    snapshot_identity: str
    pack_identity: str
    attempt_identity: str


def prepare_pipeline_input(
    root: str | Path,
    *,
    repo_root: str | PathLike[str] | None,
    scope_root: str | PathLike[str] | None,
    context_snapshot: dict[str, Any] | None,
    context_pack: dict[str, Any] | None,
    context_snapshot_id: str | None,
    context_pack_hash: str | None,
    attempt_id: str | None,
    integrated_attempt: AttemptContext | None,
) -> PipelineInput:
    """Normalize input identity once before the pipeline selects a route."""

    actual_root = Path(root).resolve()
    declared_repo_root = Path(repo_root if repo_root is not None else actual_root).resolve()
    declared_scope_root = scope_root if scope_root is not None else actual_root
    canonical_snapshot_id = str((context_snapshot or {}).get("snapshot_id") or "").strip()
    canonical_pack_hash = str((context_pack or {}).get("pack_hash") or "").strip()
    supplied_snapshot_id = None if context_snapshot_id is None else str(context_snapshot_id).strip()
    supplied_pack_hash = None if context_pack_hash is None else str(context_pack_hash).strip()
    attempt_identity = (
        attempt_id
        if attempt_id is not None
        else (integrated_attempt.attempt_id if integrated_attempt else "")
    )
    return PipelineInput(
        actual_root=actual_root,
        declared_repo_root=declared_repo_root,
        declared_scope_root=declared_scope_root,
        canonical_snapshot_id=canonical_snapshot_id,
        canonical_pack_hash=canonical_pack_hash,
        supplied_snapshot_id=supplied_snapshot_id,
        supplied_pack_hash=supplied_pack_hash,
        snapshot_identity=canonical_snapshot_id,
        pack_identity=canonical_pack_hash or supplied_pack_hash or "",
        attempt_identity=attempt_identity,
    )
