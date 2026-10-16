"""Task spec payload, task goal and context-handoff arguments for the runner (#1818 split of runner_core).

Functions moved verbatim from `simplicio_loop/runner_core.py` (#1818).
`runner_core` re-exports them, so import paths and patch targets on `runner_core` keep working.
"""
from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Tuple

from .authority_boundary import prepare_authorization_handoff


def _criteria_text(task: Dict[str, Any]) -> str:
    lines = []
    for scenario in task.get("scenarios") or []:
        parts = []
        if scenario.get("then"):
            parts.extend(scenario["then"])
        else:
            parts.append(scenario.get("title") or scenario.get("id") or "scenario")
        lines.append("- " + " ".join(parts))
    return "\n".join(lines)


def _constraints_text(task: Dict[str, Any]) -> str:
    lines = []
    for rule in task.get("rules") or []:
        lines.append(f"- {rule.get('id')}: {rule.get('text')}")
    deps = (task.get("dependencies") or {}).get("items") or []
    for dep in deps:
        lines.append(f"- dependency: {dep}")
    return "\n".join(lines)


def _task_goal(task: Dict[str, Any]) -> str:
    identity = task.get("identity") or {}
    story = task.get("story") or {}
    parts = [
        p
        for p in [
            identity.get("system"),
            identity.get("feature"),
            identity.get("type"),
            story.get("persona"),
            story.get("desire"),
            story.get("value"),
        ]
        if p
    ]
    return " | ".join(parts)


def _task_spec_payload(task: Mapping[str, Any]) -> Dict[str, Any]:
    """Build the lossless Dev CLI TaskSpec handoff from a Loop task contract.

    Loop's contract is intentionally richer than the public TaskSpec.  The full
    contract is retained in an additive field while the canonical fields are
    mapped explicitly, so the operator never has to reconstruct the task from
    flattened goal/criteria/constraint strings.
    """
    original_text = str(task.get("original_text") or "")
    if not original_text.strip():
        raise RuntimeError("typed TaskSpec handoff requires task-contract original_text")
    normalized = original_text.replace("\r\n", "\n").replace("\r", "\n").strip()
    source_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    identity = dict(task.get("identity") or {})
    story = dict(task.get("story") or {})

    acceptance_criteria = []
    for scenario in task.get("scenarios") or []:
        item = dict(scenario)
        item.setdefault("original_text", " ".join(
            str(part).strip()
            for part in (
                item.get("title", ""),
                *[str(value) for value in item.get("given") or []],
                *[str(value) for value in item.get("when") or []],
                *[str(value) for value in item.get("then") or []],
            )
            if str(part).strip()
        ))
        acceptance_criteria.append(item)

    def stateful_items(value: Any, prefix: str) -> list[Dict[str, Any]]:
        if not isinstance(value, Mapping):
            return []
        state = str(value.get("state") or "unknown")
        items = []
        for index, entry in enumerate(value.get("items") or [], start=1):
            if isinstance(entry, Mapping):
                item = dict(entry)
                item.setdefault("id", f"{prefix}{index}")
                item.setdefault("original_text", str(item.get("text") or item.get("summary") or ""))
            else:
                item = {"id": f"{prefix}{index}", "text": str(entry), "original_text": str(entry)}
            item.setdefault("state", state)
            items.append(item)
        return items

    questions = [dict(item) for item in task.get("questions") or [] if isinstance(item, Mapping)]
    assumptions = [dict(item) for item in task.get("assumptions") or [] if isinstance(item, Mapping)]
    blockers = [dict(item) for item in task.get("blockers") or [] if isinstance(item, Mapping)]
    access_path = str(task.get("access_path") or "").strip()
    source = task.get("source") or {}
    task_id = str(identity.get("id") or identity.get("title") or f"TASK-{source_hash[:12].upper()}")
    payload: Dict[str, Any] = {
        "schema": "simplicio.task-spec/v2",
        "task_id": task_id,
        "source": {
            "kind": "simplicio-loop-task-contract",
            "locator": str(source.get("path") or "") or None,
            "encoding": "utf-8",
        },
        "source_hash": source_hash,
        "language": "unknown",
        "system": str(identity.get("system") or "") or None,
        "functionality": str(identity.get("feature") or "") or None,
        "task_type": str(identity.get("type") or "") or None,
        "narrative": {
            "persona": str(story.get("persona") or "") or None,
            "desire": str(story.get("desire") or "") or None,
            "value": str(story.get("value") or "") or None,
        },
        "acceptance_criteria": acceptance_criteria,
        "business_rules": [dict(item) for item in task.get("rules") or [] if isinstance(item, Mapping)],
        "non_functional_requirements": stateful_items(task.get("nfrs"), "NFR"),
        "prototypes": [dict(item) for item in task.get("prototypes") or [] if isinstance(item, Mapping)],
        "attachments": [],
        "navigation": ([{"id": "NAV1", "path": access_path, "original_text": access_path}]
                        if access_path else []),
        "dependencies": stateful_items(task.get("dependencies"), "DEP"),
        "impact_signals": dict(task.get("impact_signals") or {}),
        "additional_information": [
            {"id": f"INFO{index}", "text": str(item), "original_text": str(item)}
            for index, item in enumerate(task.get("additional_information") or [], start=1)
        ],
        "uncertainties": questions + assumptions + blockers,
        "human_gates": [dict(item) for item in questions],
        "verification_commands": ([{"command": test_command, "verifier": "declared"}]
                              if (test_command := os.environ.get("SIMPLICIO_TEST_CMD", "").strip())
                              else []),
        "source_span": {},
        "original_text": original_text,
        # Additive field: preserves every Loop-only field and makes the handoff
        # auditable without teaching the Dev CLI private Loop schema.
        "loop_task_contract": json.loads(json.dumps(dict(task), ensure_ascii=False)),
    }
    return payload


def _task_spec_hash(payload: Mapping[str, Any]) -> str:
    """Return the Dev CLI canonical TaskSpec hash for receipt correlation."""
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _derive_context_handle(snapshot_path: Path, pack_path: Path, execution_path: Path, repo_path: Path) -> str:
    """Derive the canonical Dev CLI handle from Mapper-owned artifacts."""
    try:
        from simplicio.plan_compiler.mapper_context import bind_mapper_context

        binding = bind_mapper_context(
            _load_json(snapshot_path),
            _load_json(pack_path),
            source_root=repo_path,
            execution_context_payload=_load_json(execution_path),
        )
        return str(binding.context_handle.value)
    except Exception:
        # Context derivation is fail-closed; Dev CLI reports the typed gate.
        return ""


def _context_handoff_args(
    repo_path: Path,
    run_root: Path,
    *,
    attempt_id: str = "",
    lease_id: str = "",
    fencing_token: str = "",
) -> Tuple[List[str], Dict[str, Any]]:
    """Project canonical Mapper context artifacts into the Dev CLI argv.

    The compact Mapper handoff is not a ContextSnapshot.  This helper only
    forwards explicitly supplied canonical artifacts and never derives a
    handle from a path or from ``mapper_context_hash``.  Missing artifacts are
    recorded as a diagnostic; the integrated Dev CLI remains the fail-closed
    owner of the final context gate.
    """
    authorization_args, authorization_handoff = prepare_authorization_handoff(run_root)
    mapper_path = run_root / "mapper-context.json"
    if not mapper_path.exists():
        return list(authorization_args), {
            "status": "missing", "reason_code": "CONTEXT_ARTIFACTS_UNAVAILABLE",
            "authorization": authorization_handoff,
        }
    try:
        mapper = _load_json(mapper_path)
    except (OSError, ValueError):
        return list(authorization_args), {
            "status": "invalid", "reason_code": "CONTEXT_ARTIFACTS_INVALID",
            "authorization": authorization_handoff,
        }
    handoff = mapper.get("handoff") if isinstance(mapper.get("handoff"), Mapping) else {}
    stdout = handoff.get("stdout") if isinstance(handoff.get("stdout"), Mapping) else handoff
    if not isinstance(stdout, Mapping):
        stdout = {}

    def first_value(keys: Sequence[str]) -> Any:
        for container in (mapper, stdout):
            for key in keys:
                value = container.get(key) if isinstance(container, Mapping) else None
                if value not in (None, "", {}):
                    return value
        return None

    def persist_artifact(value: Any, filename: str, fallbacks: Sequence[Path] = ()) -> Path | None:
        if isinstance(value, Mapping):
            reference_schema = str(value.get("schema") or "")
            handle = value.get("expansion_handle")
            handle_path = handle.get("path") if isinstance(handle, Mapping) else None
            if reference_schema == "simplicio.context-reference/v1" and isinstance(handle_path, str) and handle_path.strip():
                candidates = [Path(handle_path)]
                if not Path(handle_path).is_absolute():
                    candidates = [repo_path / handle_path, run_root / handle_path]
                for candidate in candidates:
                    try:
                        resolved = candidate.resolve()
                        if resolved.exists():
                            return resolved
                    except OSError:
                        continue
                return None
            path = run_root / filename
            _write_json(path, dict(value))
            return path
        candidates: List[Path] = []
        if isinstance(value, str) and value.strip():
            candidate = Path(value)
            candidates = ([candidate] if candidate.is_absolute()
                          else [base / candidate for base in (repo_path, run_root)])
        candidates.extend(fallbacks)
        for candidate in candidates:
            try:
                resolved = candidate.resolve()
                if resolved.exists():
                    return resolved
            except OSError:
                continue
        return None

    snapshot_path = persist_artifact(
        first_value(("context_snapshot", "canonical_context_snapshot", "context_snapshot_path")),
        "context-snapshot.json",
        (repo_path / ".simplicio-loop" / "context-snapshot.json",),
    )
    pack_path = persist_artifact(
        first_value(("context_pack", "canonical_context_pack", "context_pack_path")),
        "context-pack.json",
    )
    execution_path = persist_artifact(
        first_value(("execution_context", "canonical_execution_context", "execution_context_path")),
        "execution-context.json",
    )
    if mapper.get("degraded_local") and pack_path and _degraded_mapper_fallback_enabled():
        # Standalone Dev CLI can consume the explicit local pack without the
        # Mapper-owned snapshot/execution artifacts that a full handoff provides.
        args = ["--context-pack", str(pack_path)]
        args.extend(authorization_args)
        return args, {
            "status": "degraded_local",
            "context_handle": "",
            "pack_path": str(pack_path),
            "authorization": authorization_handoff,
            "evidence_status": "UNVERIFIED",
        }
    raw_context_handle = first_value(("context_handle", "canonical_context_handle"))
    context_handle = str(raw_context_handle).strip() if raw_context_handle not in (None, "", {}) else ""
    if not context_handle and all((snapshot_path, pack_path, execution_path)):
        context_handle = _runner_core._derive_context_handle(snapshot_path, pack_path, execution_path, repo_path)
    identity_values = (attempt_id.strip(), lease_id.strip(), fencing_token.strip())
    identity_present = any(identity_values)
    identity_complete = all(identity_values)
    if identity_present and not identity_complete:
        return list(authorization_args), {
            "status": "missing",
            "reason_code": "CONTEXT_AUTHORIZATION_INCOMPLETE",
            "snapshot": bool(snapshot_path),
            "pack": bool(pack_path),
            "execution_context": bool(execution_path),
            "context_handle": bool(context_handle),
            "authorization": authorization_handoff,
        }
    if not all((snapshot_path, pack_path, execution_path)):
        return list(authorization_args), {
            "status": "missing",
            "reason_code": "CONTEXT_ARTIFACTS_INCOMPLETE",
            "snapshot": bool(snapshot_path),
            "pack": bool(pack_path),
            "execution_context": bool(execution_path),
            "context_handle": bool(context_handle),
            "authorization": authorization_handoff,
        }
    args = [
        "--context-snapshot", str(snapshot_path),
        "--context-pack", str(pack_path),
        "--execution-context", str(execution_path),
    ]
    if context_handle:
        args.extend(["--context-handle", context_handle])
    if identity_complete:
        args.extend([
            "--attempt-id", attempt_id,
            "--lease-id", lease_id,
            "--fencing-token", fencing_token,
        ])
    args.extend(authorization_args)
    return args, {
        "status": "propagated",
        "context_handle": context_handle,
        "context_handle_derived_by": "simplicio-dev-cli" if not context_handle else "mapper",
        "snapshot_path": str(snapshot_path),
        "pack_path": str(pack_path),
        "execution_context_path": str(execution_path),
        "authorization": authorization_handoff,
    }

# Late imports (#1818): bound after this module's definitions so the runner modules can import each other.
from .runner_core import (_load_json, _write_json)  # noqa: E402
from .runner_mapper_env import (_degraded_mapper_fallback_enabled)  # noqa: E402
from . import runner_core as _runner_core  # noqa: E402
