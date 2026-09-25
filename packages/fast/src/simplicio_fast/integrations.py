from __future__ import annotations

import hashlib
import importlib.metadata
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


MINIMUM_MAPPER = (0, 26, 11)
MINIMUM_DEV_CLI = (0, 18, 6)


def _version_tuple(value: str | None) -> tuple[int, ...] | None:
    if not value:
        return None
    parts: list[int] = []
    for part in value.split("."):
        digits = "".join(character for character in part if character.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts) if parts else None


def _distribution_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _executable(*names: str) -> str | None:
    for name in names:
        found = shutil.which(name)
        if found:
            return found
        sibling = Path(sys.executable).with_name(name)
        if sibling.is_file():
            return str(sibling)
    return None


def integration_status() -> dict[str, Any]:
    """Return the single compatibility decision used by doctor and receipts.

    The status is deliberately fail-closed: package metadata without an
    executable, or an executable below the tested contract, is not integrated.
    """
    mapper_version = _distribution_version("simplicio-mapper")
    dev_cli_version = _distribution_version("simplicio-cli")
    dev_cli_executable = _executable("simplicio-dev-cli", "simplicio-cli")
    mapper_ok = bool(
        mapper_version
        and _executable("simplicio-mapper")
        and (_version_tuple(mapper_version) or ()) >= MINIMUM_MAPPER
    )
    dev_cli_ok = bool(
        dev_cli_version
        and dev_cli_executable
        and (_version_tuple(dev_cli_version) or ()) >= MINIMUM_DEV_CLI
    )
    return {
        "schema": "simplicio.fast.integration-status/v1",
        "mapper": {
            "package": "simplicio-mapper",
            "version": mapper_version,
            "minimum": ".".join(map(str, MINIMUM_MAPPER)),
            "executable": _executable("simplicio-mapper"),
            "compatible": mapper_ok,
        },
        "dev_cli": {
            "package": "simplicio-cli",
            "version": dev_cli_version,
            "minimum": ".".join(map(str, MINIMUM_DEV_CLI)),
            "executable": dev_cli_executable,
            "compatible": dev_cli_ok,
        },
        "integrated_ready": mapper_ok and dev_cli_ok,
    }


def _contract_hash(value: bytes | str) -> str:
    """Match simplicio-dev-cli's text hash while preserving Fast's byte guard."""
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError:
            return hashlib.sha256(value).hexdigest()
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def run_mapper(root: Path) -> dict[str, Any] | None:
    sibling = Path(sys.executable).with_name("simplicio-mapper")
    executable = shutil.which("simplicio-mapper") or (
        str(sibling) if sibling.is_file() else None
    )
    if executable is None:
        return None
    completed = subprocess.run(
        [executable, "index", str(root), "--json"],
        stdin=subprocess.DEVNULL,
        text=True,
        capture_output=True,
        check=False,
        close_fds=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "simplicio-mapper failed: "
            + (completed.stderr.strip() or completed.stdout.strip())
        )
    payload: Any
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        payload = {"stdout": completed.stdout.strip()}
    return {
        "adapter": "simplicio-mapper",
        "status": "executed",
        "command": "index",
        "result": payload,
    }


def run_dev_cli_changeset(
    root: Path, changeset: dict[str, Any], *, write: bool
) -> dict[str, Any] | None:
    try:
        from simplicio.mechanical_edit import execute_plan
    except ImportError:
        return None

    operations: list[dict[str, Any]] = []
    touched: list[str] = []
    for change in changeset["changes"]:
        relative = change["path"]
        touched.append(relative)
        path = root / relative
        raw = path.read_bytes()
        actual = hashlib.sha256(raw).hexdigest()
        if actual != change["expected_sha256"]:
            raise ValueError(f"stale source hash for {relative}")
        lines = raw.decode("utf-8").splitlines(keepends=True)
        for replacement in change["replacements"]:
            start = replacement["start_line"]
            end = replacement["end_line"]
            range_text = "".join(lines[start - 1 : end])
            text = replacement["content"]
            if text and not text.endswith("\n"):
                text += "\n"
            operations.append(
                {
                    "op": "replace_range",
                    "path": relative,
                    "start_line": start,
                    "end_line": end,
                    "text": text,
                    "file_sha256": _contract_hash(raw),
                    "range_sha256": _contract_hash(range_text),
                }
            )
    result = execute_plan(
        {
            "schema": "simplicio.mechanical-edit/v1",
            "touched_files": sorted(set(touched)),
            "operations": operations,
        },
        root=root,
        apply=write,
    )
    return {
        "adapter": "simplicio-dev-cli",
        "status": "executed",
        "result": result,
    }


def run_runtime_effect_transaction(
    root: Path, transaction: dict[str, Any]
) -> dict[str, Any]:
    """Submit a coordinator-issued EffectTransaction to Runtime.

    Fast never issues authorization or applies a Full effect itself.  It only
    reconstructs the typed Runtime context from the coordinator payload and
    delegates the effect to the real RuntimeEffectSink.
    """
    if transaction.get("schema") != "simplicio.effect-transaction/v1":
        raise ValueError("unsupported Runtime effect transaction schema")
    effect_payload = transaction.get("effect")
    plan_payload = transaction.get("plan")
    causal = transaction.get("causal")
    authorization_payload = transaction.get("authorization")
    validation_payload = transaction.get("validation_plan", [])
    if not isinstance(effect_payload, dict):
        raise ValueError("Runtime transaction effect must be an object")
    if not isinstance(plan_payload, dict):
        raise ValueError("Runtime transaction plan must be an object")
    if not isinstance(causal, dict):
        raise ValueError("Runtime transaction causal data must be an object")
    if not isinstance(authorization_payload, dict):
        raise ValueError("Runtime transaction authorization must be an object")
    if not isinstance(validation_payload, list) or not all(
        isinstance(item, dict) for item in validation_payload
    ):
        raise ValueError(
            "Runtime transaction validation_plan must be a list of objects"
        )

    from simplicio.plan_compiler.authority import EffectAuthorization
    from simplicio.plan_compiler.effect_sink import EffectDispatchContext
    from simplicio.plan_compiler.models import EffectPlan, PlanDAG, VerificationPlan
    from simplicio.plan_compiler.runtime_effect_sink import RuntimeEffectSink

    effect = EffectPlan.from_dict(effect_payload)
    plan = PlanDAG.from_dict(plan_payload)
    node = next(
        (item for item in plan.nodes if item.node_id == effect.plan_node_id), None
    )
    if node is None:
        raise ValueError("Runtime transaction effect references an unknown plan node")
    verifications = [VerificationPlan.from_dict(item) for item in validation_payload]
    authorization = EffectAuthorization.from_dict(authorization_payload)
    if causal.get("effect_id") != effect.effect_id:
        raise ValueError("Runtime transaction effect_id does not match effect")
    if causal.get("plan_node_id") != effect.plan_node_id:
        raise ValueError("Runtime transaction plan_node_id does not match effect")
    if causal.get("plan_id") != plan.plan_id or causal.get("goal_id") != plan.goal_id:
        raise ValueError("Runtime transaction causal plan identity does not match plan")
    if transaction.get("write_set") != node.write_set:
        raise ValueError("Runtime transaction write_set does not match plan node")
    if transaction.get("acceptance_criteria_refs") != node.acceptance_criteria_refs:
        raise ValueError(
            "Runtime transaction acceptance criteria do not match plan node"
        )
    plan.validate(effects=[effect], verifications=verifications)

    context = EffectDispatchContext(
        plan_id=plan.plan_id,
        goal_id=plan.goal_id,
        plan_node=node,
        verifications=verifications,
        coordinator_kind=str(causal.get("coordinator_kind", "")),
        coordinator_id=str(causal.get("coordinator_id", "")),
        session_id=str(causal.get("session_id", "")),
        turn_id=str(causal.get("turn_id", "")),
        attempt=int(causal.get("attempt", 1)),
        subworkflow_id=str(causal.get("subworkflow_id", "")),
        deadline=transaction.get("deadline"),
        policy_revision=str(transaction.get("policy_revision", "")),
        base_hash=str(transaction.get("base_hash", "")),
        source_hash=str(transaction.get("source_hash", "")),
        context_handle=str(causal.get("context_handle", effect.context_handle)),
        lease_id=authorization.lease_id,
        fencing_token=authorization.fencing_token,
        authorization=authorization,
        plan=plan,
    )
    outcome = RuntimeEffectSink.from_environment(root=root).submit(effect, context)
    return outcome.to_dict()
