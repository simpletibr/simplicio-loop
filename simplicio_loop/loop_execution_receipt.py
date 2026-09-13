"""Publish the run-bound ``simplicio.loop-execution/v1`` receipt.

The Loop owns the execution state and publishes one immutable, runtime-readable
projection only after the watcher, delivery, quality-matrix, and oracle gates
have passed.  The projection is a separate bundle so the Runtime never has to
guess which nested run files belong together or follow ``..`` paths.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "simplicio.loop-execution/v1"
CONTRACT_VERSION = "v1"
CHAIN = [
    "simplicio-loop",
    "simplicio-mapper",
    "simplicio-dev-cli",
    "simplicio-runtime",
]

_STATE_FILES = {
    "scratchpad_frontmatter": "scratchpad.md",
    "journal_record": "journal.jsonl",
    "anchor": "anchor.json",
    "watcher_challenge": "watcher_challenge.json",
    "watcher_state": "watcher_state.json",
}


class LoopExecutionReceiptError(RuntimeError):
    """Raised when a verified run cannot produce a complete receipt."""


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError) as exc:
        raise LoopExecutionReceiptError(f"{label} is unreadable: {exc}") from exc
    if not isinstance(payload, dict):
        raise LoopExecutionReceiptError(f"{label} must contain a JSON object")
    return payload


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_commit(repo: Path) -> str:
    try:
        process = subprocess.Popen(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except OSError as exc:
        raise LoopExecutionReceiptError(f"repository commit probe unavailable: {exc}") from exc
    try:
        stdout, _stderr = process.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        raise LoopExecutionReceiptError("repository commit probe timed out")
    commit = (stdout or "").strip()
    if process.returncode != 0 or not commit:
        raise LoopExecutionReceiptError("repository commit could not be measured")
    return commit


def _component(
    *,
    version: str,
    origin: str,
    receipt: str | None = None,
    fallback: bool = False,
    **extra: Any,
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "version": str(version).strip(),
        "origin": str(origin).strip() or "installed",
        "fallback": bool(fallback),
    }
    if not value["version"]:
        raise LoopExecutionReceiptError("component version is missing")
    if receipt:
        value["receipt"] = receipt
    value.update(extra)
    return value


def _contained_path(root: Path, candidate: Path, label: str) -> Path:
    """Resolve *candidate* and reject escapes or symlink indirection."""
    root_resolved = root.resolve()
    candidate_resolved = candidate.resolve(strict=False)
    try:
        candidate_resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise LoopExecutionReceiptError(
            f"{label} escapes its allowed root: {candidate}"
        ) from exc
    if candidate.is_symlink():
        raise LoopExecutionReceiptError(f"{label} must not be a symlink: {candidate}")
    return candidate_resolved


def _validated_run_id(manifest: Mapping[str, Any], run_dir: Path) -> str:
    value = str(manifest.get("run_id") or "").strip()
    if not value or value in {".", ".."} or "/" in value or "\\" in value:
        raise LoopExecutionReceiptError("manifest run_id is missing or unsafe")
    if value != run_dir.name:
        raise LoopExecutionReceiptError(
            f"manifest run_id {value!r} does not match run directory {run_dir.name!r}"
        )
    return value


def _stack_component(stack_lock: Mapping[str, Any], name: str) -> dict[str, Any]:
    for item in stack_lock.get("components", []) or []:
        if isinstance(item, Mapping) and item.get("name") == name:
            return dict(item)
    raise LoopExecutionReceiptError(f"stack lock is missing {name}")


def _copy_entry(source: Path, bundle: Path, name: str, run_dir: Path) -> dict[str, Any]:
    _contained_path(run_dir, source, f"source artifact {name}")
    if not source.is_file():
        raise LoopExecutionReceiptError(f"required receipt is missing: {source}")
    destination = bundle / name
    _contained_path(run_dir, destination, f"destination artifact {name}")
    if destination.is_symlink():
        raise LoopExecutionReceiptError(f"destination artifact must not be a symlink: {destination}")
    shutil.copyfile(source, destination)
    return {
        "path": name,
        "present": True,
        "valid": True,
        "sha256": _sha256(destination),
    }


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    if path.parent.is_symlink():
        raise LoopExecutionReceiptError(f"receipt directory must not be a symlink: {path.parent}")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink():
        raise LoopExecutionReceiptError(f"receipt directory must not be a symlink: {path.parent}")
    _contained_path(path.parent.parent, path, "published receipt")
    fd, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def build_receipt(
    *,
    repo: Path,
    run_dir: Path,
    manifest: Mapping[str, Any],
    stack_lock: Mapping[str, Any],
    mapper_preflight: Mapping[str, Any],
    operator_preflight: Mapping[str, Any],
    commit: str,
    artifacts: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Build the canonical envelope after all source files are copied."""
    from . import __version__

    mapper = _stack_component(stack_lock, "simplicio-mapper")
    dev_cli = _stack_component(stack_lock, "simplicio-cli")
    fast = _stack_component(stack_lock, "simplicio-fast")
    runtime = _stack_component(stack_lock, "simplicio-runtime")

    if any(
        bool(component.get("fallback") or component.get("fallback_used") or component.get("fallback_declared"))
        for component in (mapper, dev_cli, fast, runtime)
    ):
        raise LoopExecutionReceiptError("fallback execution cannot publish a verified receipt")
    if any(
        bool(preflight.get("fallback") or preflight.get("fallback_used") or preflight.get("fallback_declared"))
        for preflight in (mapper_preflight, operator_preflight)
    ):
        raise LoopExecutionReceiptError("preflight fallback cannot publish a verified receipt")

    mapper_version = str(mapper_preflight.get("version") or mapper.get("version") or "")
    dev_version = str(operator_preflight.get("version") or dev_cli.get("version") or "")
    fast_version = str(fast.get("version") or "")
    if not fast_version:
        raise LoopExecutionReceiptError("Fast version is missing from the stack lock")
    if fast.get("available") is False:
        raise LoopExecutionReceiptError("Fast is unavailable in the frozen stack lock")
    runtime_version = str(runtime.get("version") or "")
    runtime_available = bool(runtime.get("available", True))
    runtime_optional = False
    if not runtime_version or runtime_version.lower() == "installed":
        # The standalone Loop profile deliberately runs without the optional
        # runtime-backed executor.  Preserve that fact in the receipt instead
        # of fabricating a runtime version or rejecting an otherwise verified
        # mapper-backed run.  Runtime-backed profiles remain fail-closed.
        if str(stack_lock.get("route") or "") == "standalone" and not runtime_available:
            runtime_version = "unavailable"
            runtime_optional = True
        else:
            raise LoopExecutionReceiptError("Runtime version is missing from the stack lock")

    relative_run_dir = run_dir.relative_to(repo).as_posix()
    return {
        "schema": SCHEMA,
        "contract_version": CONTRACT_VERSION,
        "origin": {
            "component": "simplicio-loop",
            "version": str(__version__),
            "commit": commit,
        },
        "run_id": str(manifest.get("run_id") or run_dir.name),
        "workspace": str(repo.resolve()),
        "run_dir": relative_run_dir,
        "chain": list(CHAIN),
        "fallback_used": False,
        "fallback_declared": False,
        "artifacts": dict(artifacts),
        "mapper": _component(
            version=mapper_version,
            origin=str(mapper.get("executable") or "installed"),
            receipt="mapper.json",
            source_receipt="mapper-context.json",
        ),
        "dev_cli": _component(
            version=dev_version,
            origin=str(dev_cli.get("executable") or "installed"),
            receipt="dev-cli.json",
            source_receipt="operator-receipt.json",
        ),
        "fast": _component(
            version=fast_version,
            origin=str(fast.get("executable") or "installed"),
            verified=bool(fast.get("available", True)),
        ),
        "runtime": _component(
            version=runtime_version,
            origin=str(runtime.get("executable") or "installed"),
            build_sha=str(runtime.get("build_sha") or ""),
            available=runtime_available,
            required=not runtime_optional,
            optional=runtime_optional,
        ),
        "result": {
            "run_id": str(manifest.get("run_id") or run_dir.name),
            "status": "VERIFIED",
            "verified": True,
        },
        "bundle": {
            "path": relative_run_dir,
            "sha256": hashlib.sha256(
                json.dumps(dict(artifacts), sort_keys=True).encode("utf-8")
            ).hexdigest(),
        },
    }


def publish_loop_execution_receipt(
    *, repo: Path, run_dir: Path, manifest: Mapping[str, Any]
) -> dict[str, Any]:
    """Publish the receipt and return its measured publication metadata.

    Non-git temporary repositories used by legacy unit tests keep their former
    state-machine behavior. Real Loop runs are always git worktrees; there a
    missing source artifact raises and prevents a false ``done`` transition.
    """
    repo = repo.resolve()
    run_dir = _contained_path(repo, run_dir, "run directory")
    _contained_path(run_dir, run_dir / "loop", "loop state directory")
    final_bundle = _contained_path(run_dir, run_dir / "runtime-loop-execution", "runtime bundle")
    if final_bundle.exists() or final_bundle.is_symlink():
        raise LoopExecutionReceiptError(
            f"runtime bundle already exists; refusing to overwrite: {final_bundle}"
        )
    supplied_run_id = _validated_run_id(manifest, run_dir)

    try:
        commit = _git_commit(repo)
    except LoopExecutionReceiptError as exc:
        if not (repo / ".git").exists():
            return {"status": "SKIPPED", "reason": "repository_not_git", "detail": str(exc)}
        raise

    loop_dir = run_dir / "loop"
    try:
        staging_bundle = Path(tempfile.mkdtemp(prefix=".runtime-loop-execution-", dir=str(run_dir)))
        _contained_path(run_dir, staging_bundle, "staging runtime bundle")
    except (OSError, LoopExecutionReceiptError) as exc:
        raise LoopExecutionReceiptError(f"runtime bundle staging failed: {exc}") from exc
    published = False
    bundle_published = False
    source_paths = {
        **{name: loop_dir / source for name, source in _STATE_FILES.items()},
        "mapper": run_dir / "mapper-context.json",
        "dev_cli": run_dir / "operator-receipt.json",
    }
    try:
        artifacts: dict[str, dict[str, Any]] = {}
        for name, filename in _STATE_FILES.items():
            artifacts[name] = _copy_entry(source_paths[name], staging_bundle, filename, run_dir)
        _copy_entry(source_paths["mapper"], staging_bundle, "mapper.json", run_dir)
        _copy_entry(source_paths["dev_cli"], staging_bundle, "dev-cli.json", run_dir)

        manifest_payload = _read_json(run_dir / "manifest.json", "manifest")
        file_run_id = _validated_run_id(manifest_payload, run_dir)
        if file_run_id != supplied_run_id:
            raise LoopExecutionReceiptError("provided and persisted manifest run_id values differ")
        stack_lock = _read_json(run_dir / "stack-lock.json", "stack lock")
        mapper_preflight = _read_json(run_dir / "mapper-preflight.json", "Mapper preflight")
        operator_preflight = _read_json(run_dir / "operator-preflight.json", "Dev CLI preflight")
        receipt = build_receipt(
            repo=repo,
            run_dir=final_bundle,
            manifest=manifest_payload,
            stack_lock=stack_lock,
            mapper_preflight=mapper_preflight,
            operator_preflight=operator_preflight,
            commit=commit,
            artifacts={
                name: {**entry, "path": entry["path"]}
                for name, entry in artifacts.items()
            },
        )
        os.replace(staging_bundle, final_bundle)
        bundle_published = True
        receipt_path = repo / ".simplicio" / "loop-execution.json"
        _contained_path(repo, receipt_path.parent, "receipt directory")
        _atomic_json(receipt_path, receipt)
        published = True
    except LoopExecutionReceiptError:
        raise
    except (OSError, ValueError, TypeError) as exc:
        raise LoopExecutionReceiptError(f"runtime receipt publication failed: {exc}") from exc
    finally:
        if not published and staging_bundle.exists():
            shutil.rmtree(staging_bundle, ignore_errors=True)
        if not published and bundle_published and final_bundle.exists():
            shutil.rmtree(final_bundle, ignore_errors=True)
    return {
        "status": "VERIFIED",
        "receipt": str(receipt_path),
        "bundle": str(final_bundle),
        "run_id": receipt["run_id"],
        "commit": commit,
    }


__all__ = [
    "CONTRACT_VERSION",
    "CHAIN",
    "LoopExecutionReceiptError",
    "SCHEMA",
    "build_receipt",
    "publish_loop_execution_receipt",
]

# The universal envelope is the explicit v2 successor in the same
# loop-execution family.  Re-export its pure core here so existing receipt
# consumers have one canonical import surface and do not invent a parallel
# execution contract.
from .execution_envelope import (  # noqa: E402  (kept after the v1 definitions)
    EnvelopeValidationError,
    UniversalExecutionEnvelopeError,
    build_envelope,
    build_execution_envelope,
    build_universal_envelope,
    build_universal_execution_envelope,
    is_v1_receipt_compatible,
    validate_envelope,
    validate_execution_envelope,
    validate_universal_envelope,
    validate_universal_execution_envelope,
)

__all__ += [
    "EnvelopeValidationError",
    "UniversalExecutionEnvelopeError",
    "build_envelope",
    "build_execution_envelope",
    "build_universal_envelope",
    "build_universal_execution_envelope",
    "is_v1_receipt_compatible",
    "validate_envelope",
    "validate_execution_envelope",
    "validate_universal_envelope",
    "validate_universal_execution_envelope",
]
