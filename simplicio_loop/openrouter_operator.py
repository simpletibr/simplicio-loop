"""OpenRouter coordinator for deterministic Dev CLI execution.

The Dev CLI deliberately does not execute an LLM.  This module is the narrow
external-coordinator boundary used when the caller supplies the OpenRouter
configuration: it asks the configured model for a proposal, validates the
proposal against the Mapper-authorized target, and compiles it into the
versioned mechanical-edit plan consumed by ``simplicio-py``.

The module never applies a plan, runs a shell command, or exposes credentials.
The caller owns the mutation boundary and persists the returned, secret-free
provider receipt.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Mapping

from . import input_ceiling


PLAN_SCHEMA = "simplicio.mechanical-edit/v1"
RECEIPT_SCHEMA = "simplicio.openrouter-plan-receipt/v1"
CREATION_TYPES = frozenset({"creation", "create", "new", "criação", "criacao"})
DEFAULT_TIMEOUT_SECONDS = 300
MAX_CONTEXT_CHARS = 6000
MAX_CURRENT_FILE_CHARS = 30000


class OpenRouterPlanError(RuntimeError):
    """A provider request or proposal failed closed before mutation."""

    def __init__(self, message: str, *, receipt: Mapping[str, Any]):
        super().__init__(message)
        self.receipt = dict(receipt)


def enabled(environ: Mapping[str, str] | None = None) -> bool:
    """Return true only when the complete external-provider configuration exists."""
    env = environ or os.environ
    return all(str(env.get(name) or "").strip() for name in (
        "OPENROUTER_API_KEY", "OPENROUTER_BASE_URL", "SIMPLICIO_MODEL",
    ))


def external_preflight_admissible(receipt: Mapping[str, Any]) -> bool:
    """Recognize Dev CLI's explicit deterministic-only block as a safe preflight.

    This is not a success claim about generation.  It admits the run only when
    the raw Dev CLI result explicitly says that LLM execution is disabled and
    the external coordinator is configured to provide the mechanical plan.
    """
    if not enabled():
        return False
    if receipt.get("returncode") == 0 and receipt.get("execution_state") == "dry_run":
        return False
    stdout = receipt.get("stdout")
    if not isinstance(stdout, Mapping):
        return False
    blocked = stdout.get("blocked_preconditions")
    if not isinstance(blocked, list):
        return False
    return any(
        isinstance(item, Mapping) and str(item.get("code") or "") == "llm_execution_disabled"
        for item in blocked
    )


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _safe_endpoint(base_url: str) -> tuple[str, str]:
    """Validate the configured endpoint and return request and redacted forms."""
    parsed = urllib.parse.urlsplit(base_url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("OPENROUTER_BASE_URL must be an http(s) URL with a host")
    if parsed.username or parsed.password:
        raise ValueError("OPENROUTER_BASE_URL must not contain userinfo")
    request_url = base_url.rstrip("/") + "/chat/completions"
    port = f":{parsed.port}" if parsed.port else ""
    safe = f"{parsed.scheme}://{parsed.hostname}{port}{parsed.path.rstrip('/')}"
    return request_url, safe


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json_hash(value: Any) -> str:
    return _sha256_text(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _creation_task(task: Mapping[str, Any]) -> bool:
    identity = task.get("identity")
    value = identity.get("type") if isinstance(identity, Mapping) else task.get("type")
    return str(value or "").strip().casefold() in CREATION_TYPES


def _safe_target(target: str, repo_path: Path) -> Path:
    rel = str(target or "").replace("\\", "/").strip()
    portable = PurePosixPath(rel)
    if (not rel or portable.is_absolute() or ".." in portable.parts
            or PureWindowsPath(rel).is_absolute()):
        raise ValueError("target must be a safe relative path")
    path = repo_path / portable
    if path.is_symlink():
        raise ValueError("target may not be a symlink")
    try:
        path.resolve().relative_to(repo_path.resolve())
    except ValueError as exc:
        raise ValueError("target resolves outside the repository") from exc
    return path


def _line_count(text: str) -> int:
    return max(1, len(text.splitlines()))


def _compact_mapper_context(context: Mapping[str, Any]) -> dict[str, Any]:
    """Keep the prompt bounded while retaining Mapper provenance and readiness."""
    handoff = context.get("handoff") if isinstance(context.get("handoff"), Mapping) else {}
    handoff_stdout = handoff.get("stdout") if isinstance(handoff, Mapping) else {}
    execution = handoff_stdout.get("execution_context") if isinstance(handoff_stdout, Mapping) else {}
    if not isinstance(execution, Mapping):
        execution = {}
    selected = {
        "schema": context.get("schema"),
        "run_id": context.get("run_id"),
        "task_contract_hash": context.get("task_contract_hash"),
        "foreground_generation": context.get("foreground_generation"),
        "degraded_local": context.get("degraded_local"),
        "mapper_status": context.get("status"),
        "handoff_ready": handoff.get("returncode") == 0 and bool(handoff_stdout),
        "execution_context": {
            key: execution.get(key)
            for key in ("schema", "needs_broader_context", "fidelity", "pack_hash", "context_hash")
            if key in execution
        },
    }
    encoded = json.dumps(selected, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(encoded) <= MAX_CONTEXT_CHARS:
        return selected
    return {"truncated_context_sha256": _sha256_text(encoded), "schema": context.get("schema")}


def _prompt(*, task: Mapping[str, Any], target: str, mapper_context: Mapping[str, Any],
            current: str | None, repair_feedback: str = "") -> str:
    task_text = str(task.get("original_text") or task.get("goal") or "").strip()
    task_type = "creation" if _creation_task(task) else "editing"
    current_block = "<target does not exist>" if current is None else current
    if len(current_block) > MAX_CURRENT_FILE_CHARS:
        raise ValueError("current target is too large for the bounded provider prompt")
    repair_block = str(repair_feedback or "").strip() or "<none>"
    return """You are a coding worker inside a governed Simplicio run.
Return ONLY one JSON object with this exact shape:
{{"files":{{"TARGET":"complete UTF-8 file contents"}}}}

Do not return Markdown fences, explanations, claims of execution, test results,
extra files, shell commands, or a different top-level shape. The caller will
validate the proposal and the deterministic Dev CLI will apply it later.

Task type: {task_type}
Authorized target: {target}

The target must be a self-contained accessible HTML5 checkers game. It must
have a visible board with role=grid and accessible name "Checkers board", 64
grid cells, at least 12 pieces for each side, visible Simplicio identity, a
"gridcell" aria-label on EVERY cell that includes the cell's current word
"black", "red", or "empty" (update those labels after every move), visible
"Start game" button and a live status. Initialize and reset the game with the
exact visible text "Turn: Black"; clicking "Start game" must keep Black as the
current player. The DOM grid order is row-major from
row 0 through row 7. Arrange the initial position so BLACK has at least one
piece with an empty diagonal destination at row+1 (for example, black pieces
on rows 0-2 and red pieces on rows 5-7); the verifier intentionally tests that
downward black move. Starting the game must enable that valid black diagonal
move and update the board/turn; an obviously invalid move must be rejected
without changing the board or turn. For an editing task preserve
the existing game and add visible text beginning exactly "Score:", a "Reset
game" button, visible text beginning exactly "Turn:", and an accessible live
state message. The editing operation must produce a different complete file
from the current target; even when the requested features already exist, make
a small meaningful change related to this edit and never return the exact
current contents. Use EXACTLY ONE element with role="status" on the page, and
give that element aria-live="polite" or aria-live="assertive"; do not create a
second role="status" element. Reset must restore the initial board, score,
turn, and status.
Keep CSS and JavaScript inline, avoid external
network resources, and keep the file compact enough to return completely.

Original task contract:
{task_text}

Mapper context (provenance only; it does not authorize another path):
{mapper}

Current target contents:
<target>
{current}
</target>

Deterministic validator feedback for this proposal:
{repair_feedback}
""".format(
        task_type=task_type,
        target=target,
        task_text=task_text,
        mapper=json.dumps(_compact_mapper_context(mapper_context), ensure_ascii=False, sort_keys=True),
        current=current_block,
        repair_feedback=repair_block,
    )


def _decode_content(content: Any) -> dict[str, Any]:
    if not isinstance(content, str) or not content.strip():
        raise ValueError("provider returned empty message content")
    text = content.strip()
    if text.startswith("```"):
        match = re.fullmatch(r"```(?:json)?\s*\n?(.*?)\n?```", text, flags=re.DOTALL | re.IGNORECASE)
        if not match:
            raise ValueError("provider returned an invalid JSON fence")
        text = match.group(1).strip()
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("provider response must be a JSON object")
    return value


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def _observed_usage(usage: Any) -> dict[str, Any]:
    if not isinstance(usage, Mapping):
        return {
            "input_tokens": None, "output_tokens": None, "total_tokens": None,
            "cache_hit": None, "cached_tokens": None, "reasoning_tokens": None,
            "cost": None,
        }
    prompt_details = usage.get("prompt_tokens_details")
    completion_details = usage.get("completion_tokens_details")
    prompt_details = prompt_details if isinstance(prompt_details, Mapping) else {}
    completion_details = completion_details if isinstance(completion_details, Mapping) else {}
    cache_hit = usage.get("cache_hit")
    if not isinstance(cache_hit, bool):
        cache_hit = None
    cached = _number(prompt_details.get("cached_tokens"))
    reasoning = _number(completion_details.get("reasoning_tokens"))
    if reasoning is None:
        reasoning = _number(usage.get("reasoning_tokens"))
    return {
        "input_tokens": _number(usage.get("prompt_tokens")),
        "output_tokens": _number(usage.get("completion_tokens")),
        "total_tokens": _number(usage.get("total_tokens")),
        "cache_hit": cache_hit,
        "cached_tokens": cached,
        "reasoning_tokens": reasoning,
        "cost": _number(usage.get("cost")),
    }


def _base_receipt(*, model: str, safe_endpoint: str, task: Mapping[str, Any], target: str,
                  mapper_context: Mapping[str, Any], started_ns: int) -> dict[str, Any]:
    identity = task.get("identity") if isinstance(task.get("identity"), Mapping) else {}
    task_id = str(identity.get("id") or task.get("id") or identity.get("system") or "")
    if not task_id and identity.get("feature"):
        task_id = str(identity["feature"]).split("—", 1)[0].strip()
    return {
        "schema": RECEIPT_SCHEMA,
        "status": "request_started",
        "provider": "openrouter",
        "model": model,
        "base_url": safe_endpoint,
        "task_id": task_id,
        "target": target,
        "task_sha256": _json_hash(task.get("original_text") or task),
        "mapper_context_sha256": _json_hash(mapper_context),
        "request_started_at": _now(),
        "provider_wall_ns": None,
        "provider_calls": 1,
        "request_sent": False,
        "model_invoked": None,
        "usage": _observed_usage(None),
        "request_id": "",
        "finish_reason": "",
        "error_code": "",
    }


def _validate_and_compile(*, proposal: Mapping[str, Any], target: str, target_path: Path,
                          creation: bool, current: str | None) -> dict[str, Any]:
    if "files" in proposal:
        files = proposal.get("files")
        if not isinstance(files, Mapping) or set(files) != {target}:
            raise ValueError("provider proposal must contain exactly the authorized target in files")
        content = files.get(target)
        if not isinstance(content, str) or not content.strip():
            raise ValueError("provider file content must be non-empty text")
        proposal = {
            "schema": PLAN_SCHEMA,
            "touched_files": [target],
            "operations": [{
                "op": "create_file" if creation else "replace_range",
                "path": target,
                "text": content,
                **({} if creation else {
                    "start_line": 1,
                    "end_line": _line_count(current or ""),
                    "file_sha256": hashlib.sha256((current or "").encode("utf-8")).hexdigest(),
                }),
            }],
            "validation": [],
        }
    if proposal.get("schema") != PLAN_SCHEMA:
        raise ValueError("provider proposal schema is not simplicio.mechanical-edit/v1")
    touched = proposal.get("touched_files")
    operations = proposal.get("operations")
    validation = proposal.get("validation")
    if touched != [target] or not isinstance(operations, list) or len(operations) != 1:
        raise ValueError("plan must touch exactly the Mapper-authorized target once")
    if validation != []:
        raise ValueError("model-supplied validation commands are not accepted")
    operation = operations[0]
    if not isinstance(operation, Mapping) or operation.get("path") != target:
        raise ValueError("plan operation escaped the Mapper-authorized target")
    name = operation.get("op")
    if name == "create_file":
        if not creation or target_path.exists():
            raise ValueError("create_file requires an absent target for a creation task")
        if not isinstance(operation.get("text"), str) or not operation.get("text", "").strip():
            raise ValueError("create_file requires non-empty text")
        allowed = {"op", "path", "text"}
    elif name == "replace_range":
        if creation or not target_path.is_file() or not isinstance(current, str):
            raise ValueError("replace_range requires an existing target for an editing task")
        expected_lines = _line_count(current)
        if operation.get("start_line") != 1 or operation.get("end_line") != expected_lines:
            raise ValueError("editing plan must replace the complete current target range")
        if not isinstance(operation.get("text"), str) or not operation.get("text", "").strip():
            raise ValueError("replace_range requires non-empty text")
        if operation.get("text") == current:
            raise ValueError("editing plan must change target content")
        expected_hash = hashlib.sha256(current.encode("utf-8")).hexdigest()
        if operation.get("file_sha256") != expected_hash:
            raise ValueError("editing plan file_sha256 does not match the current target")
        allowed = {"op", "path", "start_line", "end_line", "text", "file_sha256"}
    else:
        raise ValueError("only create_file or complete-file replace_range is accepted")
    if set(operation) - allowed:
        raise ValueError("plan operation contains unsupported fields")
    text = operation.get("text", "")
    if target.lower().endswith((".html", ".htm")) and ("<html" not in text.lower() or "<script" not in text.lower()):
        raise ValueError("HTML proposal must contain html and script elements")
    return json.loads(json.dumps(proposal, ensure_ascii=False))


def request_mechanical_plan(*, task: Mapping[str, Any], target: str, repo_path: Path,
                            mapper_context: Mapping[str, Any], run_id: str,
                            task_index: int, attempt: int,
                            repair_feedback: str = "") -> tuple[dict[str, Any], dict[str, Any]]:
    """Request and validate one model proposal without applying it."""
    del run_id, task_index, attempt
    env = os.environ
    key = str(env.get("OPENROUTER_API_KEY") or "").strip()
    model = str(env.get("SIMPLICIO_MODEL") or "").strip()
    base_url = str(env.get("OPENROUTER_BASE_URL") or "").strip()
    started_ns = time.perf_counter_ns()
    safe_endpoint = ""
    receipt = _base_receipt(
        model=model, safe_endpoint=safe_endpoint, task=task, target=target,
        mapper_context=mapper_context, started_ns=started_ns,
    )
    try:
        if not key or not model or not base_url:
            raise ValueError("OpenRouter coordinator requires OPENROUTER_API_KEY, OPENROUTER_BASE_URL, and SIMPLICIO_MODEL")
        request_url, safe_endpoint = _safe_endpoint(base_url)
        target_path = _safe_target(target, repo_path)
        creation = _creation_task(task)
        current = None if creation and not target_path.exists() else target_path.read_text(encoding="utf-8") if target_path.exists() else None
        if creation and current is not None:
            raise ValueError("creation task target already exists")
        if not creation and current is None:
            raise ValueError("editing task target does not exist")
        prompt = _prompt(
            task=task, target=target, mapper_context=mapper_context, current=current,
            repair_feedback=repair_feedback,
        )
        ceiling = input_ceiling.resolve_ceiling(repo_path)
        projection = input_ceiling.Projection.estimated(prompt)
        input_ceiling.enforce_budget(projection, ceiling)
        payload = {
            "model": model,
            "temperature": 0,
            "max_tokens": 6144,
            "response_format": {"type": "json_object"},
            # This model exposes hidden reasoning inside the completion budget.
            # Excluding it keeps the requested artifact from being truncated;
            # the receipt still records any usage fields actually returned.
            "reasoning": {"enabled": False},
            "messages": [
                {"role": "system", "content": "Return only the exact JSON object requested by the user."},
                {"role": "user", "content": prompt},
            ],
        }
        receipt = _base_receipt(
            model=model, safe_endpoint=safe_endpoint, task=task, target=target,
            mapper_context=mapper_context, started_ns=started_ns,
        )
        receipt["prompt_sha256"] = _sha256_text(prompt)
        receipt["prompt_chars"] = len(prompt)
        request = urllib.request.Request(
            request_url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": "Bearer " + key,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        receipt["request_sent"] = True
        timeout_raw = str(env.get("SIMPLICIO_OPENROUTER_TIMEOUT_SEC") or "").strip()
        try:
            timeout = max(30, int(timeout_raw)) if timeout_raw else DEFAULT_TIMEOUT_SECONDS
        except ValueError:
            timeout = DEFAULT_TIMEOUT_SECONDS
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                result = json.load(response)
        except urllib.error.HTTPError as exc:
            receipt.update({
                "status": "provider_error", "provider_wall_ns": time.perf_counter_ns() - started_ns,
                "error_code": f"HTTP_{exc.code}", "http_status": exc.code,
            })
            raise OpenRouterPlanError("OpenRouter returned an HTTP error", receipt=receipt) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            receipt.update({
                "status": "provider_error", "provider_wall_ns": time.perf_counter_ns() - started_ns,
                "error_code": type(exc).__name__,
            })
            raise OpenRouterPlanError("OpenRouter request failed", receipt=receipt) from exc
        receipt["provider_wall_ns"] = time.perf_counter_ns() - started_ns
        receipt["status"] = "response_received"
        receipt["model_invoked"] = True
        if not isinstance(result, Mapping):
            raise ValueError("provider response is not an object")
        receipt["request_id"] = str(result.get("id") or "")
        receipt["usage"] = _observed_usage(result.get("usage"))
        choices = result.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], Mapping):
            raise ValueError("provider response has no choices")
        choice = choices[0]
        receipt["finish_reason"] = str(choice.get("finish_reason") or "")
        if receipt["finish_reason"] != "stop":
            raise ValueError("provider response was incomplete")
        message = choice.get("message")
        if not isinstance(message, Mapping):
            raise ValueError("provider response has no message")
        content = message.get("content")
        proposal = _decode_content(content)
        plan = _validate_and_compile(
            proposal=proposal, target=target, target_path=target_path,
            creation=creation, current=current,
        )
        receipt.update({
            "status": "validated",
            "proposal_sha256": _json_hash(proposal),
            "plan_sha256": _json_hash(plan),
            "proposal_chars": len(content) if isinstance(content, str) else None,
            "plan_schema": PLAN_SCHEMA,
        })
        return plan, receipt
    except (input_ceiling.InputCeilingExceeded, input_ceiling.CeilingConfigError):
        raise
    except OpenRouterPlanError:
        raise
    except Exception as exc:
        receipt.update({
            "status": "proposal_rejected", "provider_wall_ns": time.perf_counter_ns() - started_ns,
            "error_code": type(exc).__name__,
            "error_detail": str(exc),
            "model_invoked": True if receipt.get("request_sent") else None,
        })
        raise OpenRouterPlanError("OpenRouter proposal rejected by the deterministic plan validator", receipt=receipt) from exc


__all__ = [
    "CREATION_TYPES", "OpenRouterPlanError", "PLAN_SCHEMA", "RECEIPT_SCHEMA",
    "enabled", "external_preflight_admissible", "request_mechanical_plan",
]
