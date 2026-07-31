"""Task-result assembly + dry-run precondition checks for pipeline.py.

Extracted from ``simplicio/pipeline.py`` as part of issue #141's coordinator
refactor (AC #2: keep ``pipeline.py`` under its 5,555-token baseline by
moving self-contained pieces into focused modules).  This module owns the
dry-run precondition gate (``_dry_run_preconditions``) and the result-dict
shape (``_task_result`` + ``_verify_receipt_payload`` /
``_diff_summary``), none of which participate in the generate→validate→test→
fix→verify loop itself.

The live receipt state (``_LAST_VERIFY_RECEIPT`` / ``_LAST_PATCH_RECEIPT``)
still lives in ``pipeline.py`` — it is coordination state written by the apply
stage and read both here (for the patch receipt) and by ``run_task``.  We read
it lazily through the ``pipeline`` module object so monkeypatched tests that
assert on ``pipeline._LAST_PATCH_RECEIPT`` keep seeing the real value.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .mapper import artifact_status, map_handoff
from .observability import estimate_tokens
from .orchestrator.cost_governor import _price as _estimate_price
from .pipeline_stages import IMPACT_RESULT_UNVERIFIED, extract_changed_files
from .prompt import latest_prompt_envelope
from .providers import _provider_id


def _verify_receipt_payload(receipt: dict[str, Any] | None) -> dict[str, Any] | None:
    if not receipt:
        return None
    commands = [str(item) for item in receipt.get("commands", [])]
    exit_codes = [int(item) for item in receipt.get("exit_codes", [])]
    payload = {
        "transaction_id": receipt.get("transaction_id"),
        "base_sha": receipt.get("base_sha"),
        "candidate_sha": receipt.get("candidate_sha"),
        "receipt_digest": receipt.get("receipt_digest"),
        "commands": commands,
        "exit_codes": exit_codes,
        "command": commands[0] if commands else None,
        "exit_code": exit_codes[0] if exit_codes else None,
        "stdout_tail": receipt.get("stdout_tail", ""),
        "stderr_tail": receipt.get("stderr_tail", ""),
        "files": receipt.get("files", []),
    }
    return payload


def _diff_summary(files_changed):
    if not files_changed:
        return "no changed files reported"
    return "changed " + ", ".join(files_changed)


def _degraded_mapper_context_allowed(context_pack: dict[str, Any] | None) -> bool:
    """Allow only Loop-issued, explicit degraded context in standalone mode."""
    if not isinstance(context_pack, dict):
        return False
    fidelity = context_pack.get("fidelity")
    if not isinstance(fidelity, dict) or fidelity.get("gate") != "degraded_local":
        return False
    if fidelity.get("status") != "UNVERIFIED":
        return False
    raw = os.environ.get("SIMPLICIO_ALLOW_DEGRADED_MAPPER", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _dry_run_preconditions(
    root: str | Path,
    target: str,
    *,
    context_pack: dict[str, Any] | None = None,
    allow_degraded_mapper: bool = False,
) -> list[dict[str, Any]]:
    root_path = Path(root).resolve()
    blockers: list[dict[str, Any]] = []

    target_value = Path(target)
    target_path = root_path / target_value
    target_exists = target_path.exists()
    parent_path = target_path.parent.resolve()
    target_inside_root = parent_path == root_path or root_path in parent_path.parents
    new_file_ready = (
        not target_exists
        and not target_value.is_absolute()
        and target_inside_root
        and parent_path.is_dir()
        and not target_path.is_symlink()
    )

    if target_value.is_absolute() or not target_inside_root:
        blockers.append(
            {
                "reason": "target_outside_root",
                "message": "requested target must remain inside the repo root",
                "next_surface": "task_target",
                "details": {"target": target, "root": str(root_path)},
            }
        )
    elif not target_exists and not new_file_ready:
        blockers.append(
            {
                "reason": "target_parent_invalid",
                "message": "new-file target requires an existing directory inside the repo root",
                "next_surface": "task_target",
                "details": {"target": target, "parent": str(parent_path)},
            }
        )

    artifacts = artifact_status(root_path)
    missing = [
        name
        for name in ("project_map", "precedent_index")
        if not bool((artifacts.get(name) or {}).get("present"))
    ]
    degraded_allowed = allow_degraded_mapper and _degraded_mapper_context_allowed(context_pack)
    if missing and not degraded_allowed:
        blockers.append(
            {
                "reason": "artifacts_missing",
                "message": "mapper artifacts required for dry-run task are missing",
                "next_surface": "mapper_artifacts",
                "details": {"missing": missing},
            }
        )

    inspection = artifacts.get("inspection") if isinstance(artifacts, dict) else None
    warnings = inspection.get("warnings", []) if isinstance(inspection, dict) else []
    stale_warnings = [str(item) for item in warnings if "stale" in str(item).lower()]
    if stale_warnings and not degraded_allowed:
        blockers.append(
            {
                "reason": "artifacts_stale",
                "message": "mapper artifacts are present but marked stale by inspection",
                "next_surface": "mapper_inspection",
                "details": {"warnings": stale_warnings},
            }
        )

    # Prefer the canonical Runtime-bound pack already supplied by the
    # caller. A generic mapper re-handoff here can discard task-aware fidelity
    # and is not authoritative for an integrated execution.
    handoff = {"context_pack": context_pack} if context_pack is not None else map_handoff(root_path)
    if handoff is None:
        if not new_file_ready:
            blockers.append(
                {
                    "reason": "no_handoff_targets",
                    "message": "mapper handoff context is unavailable for dry-run task",
                    "next_surface": "context_pack",
                    "details": {"target": target},
                }
            )
    else:
        pack = handoff.get("context_pack")
        if not isinstance(pack, dict):
            blockers.append(
                {
                    "reason": "no_handoff_targets",
                    "message": "mapper handoff context pack is missing or malformed",
                    "next_surface": "context_pack",
                    "details": {"target": target},
                }
            )
        else:
            files = [
                str(item.get("path"))
                for item in pack.get("files", [])
                if isinstance(item, dict) and item.get("path")
            ]
            if pack.get("needs_broader_context"):
                blockers.append(
                    {
                        "reason": "broader_context_required",
                        "message": "mapper handoff pack says broader context is required",
                        "next_surface": "context_pack",
                        "details": {"target": target},
                    }
                )
            elif not files:
                blockers.append(
                    {
                        "reason": "no_handoff_targets",
                        "message": "mapper handoff pack has no targetable files",
                        "next_surface": "context_pack",
                        "details": {"target": target},
                    }
                )
            elif target not in files and not new_file_ready:
                blockers.append(
                    {
                        "reason": "target_resolution_failed",
                        "message": "requested target is not present in mapper handoff files",
                        "next_surface": "task_target" if not target_exists else "context_pack",
                        "details": {"target": target, "known_targets": files[:12]},
                    }
                )

    if not target_exists and not new_file_ready:
        blockers.append(
            {
                "reason": "target_resolution_failed",
                "message": "requested target does not exist under the repo root",
                "next_surface": "task_target",
                "details": {"target": target},
            }
        )

    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for blocker in blockers:
        key = (str(blocker.get("reason")), str(blocker.get("next_surface")))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(blocker)
    return deduped


def target_kind(root: str | Path, target: str) -> str:
    """Return the stable target classification used by task JSON receipts."""
    path = Path(root).resolve() / Path(target)
    return "existing_file" if path.exists() else "new_file"


def _task_result(
    task_id,
    prompt,
    output,
    *,
    applied,
    status=None,
    warnings=None,
    blocked_preconditions=None,
    verify=None,
    impact=None,
    prompt_envelope=None,
    target_kind=None,
):
    from . import pipeline

    files_changed = extract_changed_files(output)
    prompt_tokens = estimate_tokens(prompt)
    completion_tokens = estimate_tokens(output or "")
    priced = os.environ.get("SIMPLICIO_PRICE_PER_MTOK") or (
        os.environ.get("SIMPLICIO_PRICE_PROMPT_PER_MTOK")
        or os.environ.get("SIMPLICIO_PRICE_COMPLETION_PER_MTOK")
    )
    model = os.environ.get("SIMPLICIO_MODEL", "")
    cost_usd = float(_estimate_price(model, prompt_tokens, completion_tokens)) if priced else 0.0
    result = {
        "task_id": task_id,
        "applied": bool(applied),
        "status": status or ("applied" if applied else "failed"),
        "files_changed": files_changed,
        "tokens_used": {
            "prompt": prompt_tokens,
            "completion": completion_tokens,
        },
        "cost_usd": cost_usd,
        "cost_basis": "estimated" if priced else "unknown_no_pricing_configured",
        "diff_summary": _diff_summary(files_changed),
        "warnings": warnings or [],
        "model": {
            "requested": os.environ.get("SIMPLICIO_MODEL", ""),
            "effective": os.environ.get("SIMPLICIO_EFFECTIVE_MODEL", os.environ.get("SIMPLICIO_MODEL", "")),
            "effort": os.environ.get("SIMPLICIO_REASONING_EFFORT", os.environ.get("SIMPLICIO_EFFORT", "")),
            "tier": os.environ.get("SIMPLICIO_MODEL_TIER", ""),
            "provider": _provider_id(
                os.environ.get("SIMPLICIO_MODEL", ""), os.environ.get("SIMPLICIO_BASE_URL", "")
            ),
        },
    }
    if target_kind is not None:
        result["target_kind"] = target_kind
    envelope = prompt_envelope or latest_prompt_envelope()
    if envelope is not None:
        result["prompt_envelope"] = envelope.receipt()
    if blocked_preconditions:
        result["blocked_preconditions"] = blocked_preconditions
    verify_receipt = _verify_receipt_payload(verify)
    if verify_receipt is not None:
        exit_codes = verify_receipt.get("exit_codes", [])
        if exit_codes:
            status = "verified" if all(code == 0 for code in exit_codes) else "failed"
        else:
            status = IMPACT_RESULT_UNVERIFIED
        result["verify"] = {
            "status": status,
            "receipt": verify_receipt,
        }
    # Issue #93: impact-test evidence block
    if impact is not None:
        result["impact"] = {
            "callers": impact.get("callers", []),
            "tests_run": impact.get("tests_run", []),
            "result": impact.get("result", IMPACT_RESULT_UNVERIFIED),
        }
        receipt = impact.get("receipt")
        if isinstance(receipt, dict):
            result["impact"]["receipt"] = dict(receipt)
        else:
            receipt = {
                "command": impact.get("command"),
                "exit_code": impact.get("returncode"),
                "output_tail": impact.get("output_tail", ""),
                "status": impact.get("status"),
            }
            if any(value not in (None, "", []) for value in receipt.values()):
                result["impact"]["receipt"] = receipt
        if impact.get("status") in ("ok", "passed"):
            result["impact"]["status"] = "verified"
        elif impact.get("status") in ("failed", "error"):
            result["impact"]["status"] = impact["status"]
        else:
            result["impact"]["status"] = IMPACT_RESULT_UNVERIFIED
    if pipeline._LAST_PATCH_RECEIPT is not None:
        result["patch"] = dict(pipeline._LAST_PATCH_RECEIPT)
    return result
