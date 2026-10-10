"""Structured output at the origin (issue #1612, PR B): what each CLI and each provider model can be told to emit.

A provider ``response_format`` or a CLI schema flag only narrows what the model emits. The post-answer check in
``plan_scope`` stays the only validator, so every answer is still parsed against the closed contract. This module holds
the capability tables, the schema both kinds of origin receive, the output budget of a task and the receipt
``structured_output: enforced|validated_only`` with its reason.

``origin_schema`` is the contract in the one form every CLI and provider takes: only portable keywords, and every
property required (OpenAI strict mode and ``codex exec --output-schema`` refuse optional properties). ``find`` is then
``""`` for a new file and ``need`` is ``[]`` when the plan asks for no more lines, which the contract also accepts.
"""
from __future__ import annotations

import copy
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import plan_scope

ENFORCED = "enforced"
VALIDATED_ONLY = "validated_only"

# Keywords the origin schema drops: annotations, and the conditional that keeps an empty plan out. The conditional
# stays in the contract, where the validator applies it.
_NON_PORTABLE = frozenset({"$schema", "$id", "title", "if", "then", "else"})


@dataclass(frozen=True)
class CliCapability:
    """``flag`` is the CLI's schema option; ``inline`` says the schema JSON follows it, else a file path does."""

    flag: str
    inline: bool = True


# Measured with ``<cli> --help`` on this host (claude 2.1.292, codex-cli 0.154.0, agy 1.3.2, grok 1.0.46,
# opencode 1.18.30). opencode lists no schema option. gemini is not installed here and no flag was measured.
# claude: ``--json-schema <schema>`` and the JSON envelope keeps the answer text in ``result`` (one call measured).
CLI_FLAGS: dict[str, CliCapability] = {
    "claude": CliCapability("--json-schema"),
    "agy": CliCapability("--json-schema"),
    "grok": CliCapability("--json-schema"),
    "codex": CliCapability("--output-schema", inline=False),
    "opencode": CliCapability(""),
}
_NO_FLAG_REASON = {"opencode": "no_schema_flag", "gemini": "cli_not_measured"}

# Models that declare ``structured_outputs`` in the OpenRouter catalog (GET /api/v1/models ``supported_parameters``,
# read 2026-10-09). A model outside this table is ``validated_only``. Models that need an all-optional-free schema
# are fine here too: ``origin_schema`` already requires every property.
PROVIDER_MODELS = frozenset({
    "deepseek/deepseek-v4.1-flash",
    "deepseek/deepseek-v4-flash",
    "deepseek/deepseek-v4-pro",
})

MIN_TOKENS = 2048
NEW_FILE_TOKENS = 4096  # a file the task creates, or a task that names no file
FILE_TOKENS_MAX = 6144  # one existing file: find and replace may each hold it all, bounded
CHARS_PER_TOKEN = 3
MAX_TOKENS = 16384  # same ceiling as provider_worker.OPENROUTER_MAX_TOKENS


def origin_schema(kind: str) -> dict[str, Any]:
    """The closed contract of ``kind`` ("plan" or "verdict") as the origin takes it. A fresh copy on every call."""
    return _portable(copy.deepcopy(plan_scope.RESPONSE_SCHEMAS[kind]))


def _portable(schema: dict[str, Any]) -> dict[str, Any]:
    out = {key: value for key, value in schema.items() if key not in _NON_PORTABLE}
    if "properties" in out:
        out["properties"] = {name: _portable(sub) for name, sub in out["properties"].items()}
        out["required"] = list(out["properties"])
    if isinstance(out.get("items"), dict):
        out["items"] = _portable(out["items"])
    return out


def _compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def cli_needs_file(family: str) -> bool:
    """True when the CLI reads the schema from a file (the caller writes ``schema_text()`` there)."""
    capability = CLI_FLAGS.get(family)
    return bool(capability and capability.flag and not capability.inline)


def schema_text(kind: str = "plan") -> str:
    return _compact(origin_schema(kind))


def cli_flags(family: str, schema_file: str = "", kind: str = "plan") -> list[str]:
    """The argv words that make ``family`` emit the ``kind`` schema; empty when the CLI has no such flag."""
    capability = CLI_FLAGS.get(family)
    if capability is None or not capability.flag:
        return []
    if capability.inline:
        return [capability.flag, schema_text(kind)]
    if not schema_file:
        raise ValueError(f"{family} reads the schema from a file: pass schema_file")
    return [capability.flag, schema_file]


def cli_receipt(family: str) -> tuple[str, str]:
    """``(structured_output, reason)`` of a planner run through ``family``."""
    capability = CLI_FLAGS.get(family)
    if capability is not None and capability.flag:
        return ENFORCED, f"flag:{capability.flag}"
    return VALIDATED_ONLY, _NO_FLAG_REASON.get(family, "unknown_family")


def provider_receipt(model: str) -> tuple[str, str]:
    if model in PROVIDER_MODELS:
        return ENFORCED, "model_declares_structured_outputs"
    return VALIDATED_ONLY, "model_not_in_table"


def _schema_name(kind: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", plan_scope.RESPONSE_SCHEMAS[kind]["$id"]).strip("_")


def _file_tokens(path: Path) -> int:
    return min(2 * math.ceil(path.stat().st_size / CHARS_PER_TOKEN), FILE_TOKENS_MAX)


def max_tokens_for(tasks: Sequence[Mapping[str, Any]], root: str | Path) -> int:
    """Output budget of these tasks: the floor, a creation allowance per new target, the named files that exist."""
    root = Path(root)
    total, counted = MIN_TOKENS, set()
    for task in tasks:
        target = task.get("target")
        if not target or not (root / target).is_file():
            total += NEW_FILE_TOKENS
        for name in (target, *(task.get("context") or [])):
            if name and name not in counted and (root / name).is_file():
                counted.add(name)
                total += _file_tokens(root / name)
    return min(total, MAX_TOKENS)


def output_tokens_by_task(calls: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Output tokens per task group: the sum of ``completion_tokens`` over the calls that answered it.

    ``MEASURED`` only when every call of the group came back with the provider's own usage; otherwise the count is
    ``None`` and the basis ``UNVERIFIED``. An estimate is never reported as measured. A call with no ``tasks``
    (the 1-token cache warm-up) belongs to no task.
    """
    groups: dict[tuple[int, ...], list[Mapping[str, Any]]] = {}
    for call in calls:
        if call.get("tasks"):
            groups.setdefault(tuple(call["tasks"]), []).append(call)
    out = []
    for tasks, group in groups.items():
        measured = all(c.get("ok", True) and c.get("usage_reported") for c in group)
        out.append({"tasks": list(tasks), "calls": len(group), "basis": "MEASURED" if measured else "UNVERIFIED",
                    "output_tokens": sum(int(c.get("completion_tokens") or 0) for c in group) if measured else None})
    return out


def output_metrics(calls: Sequence[Mapping[str, Any]], rejections: Sequence[Sequence[str]]) -> dict[str, Any]:
    """MEASURED structured-output metrics of a run: rejections by kind (counted from the violations) and the
    output tokens of each task. ``rejections`` holds the violations of every refused answer."""
    return {
        "rejected_answers": len(rejections),
        "rejected": plan_scope.counters(v for violations in rejections for v in violations),
        "output_tokens_by_task": output_tokens_by_task(calls),
    }


def provider_fields(model: str, tasks: Sequence[Mapping[str, Any]], root: str | Path,
                    kind: str = "plan") -> dict[str, Any]:
    """The chat-completion fields for these tasks: ``max_tokens`` always, ``response_format`` for a listed model."""
    fields: dict[str, Any] = {"max_tokens": max_tokens_for(tasks, root)}
    if model in PROVIDER_MODELS:
        fields["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": _schema_name(kind), "strict": True, "schema": origin_schema(kind)},
        }
    return fields
