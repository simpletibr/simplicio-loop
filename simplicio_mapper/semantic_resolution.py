"""Optional compiler-semantic resolution boundary.

Regex extraction is useful for discovery, but it must never be presented as
semantic symbol resolution.  This module defines a small JSON protocol for a
Roslyn adapter (or another deterministic compiler service) and keeps an
unavailable or malformed service on the explicit heuristic fallback path.

Configure a service with ``SIMPLICIO_MAPPER_SEMANTIC_COMMAND``.  The command
receives one JSON request on stdin and returns one JSON response on stdout:

.. code-block:: json

  {"schema":"simplicio.mapper-semantic-request/v1", "language":"csharp",
   "source_generation":[{"path":"src/Service.cs","content":"..."}],
   "symbols":[], "call_sites":[{"source_file":"src/App.cs",
   "name":"Compute", "line":12}]}

The response uses ``simplicio.mapper-semantic-result/v1`` and may contain
``symbols`` and ``resolutions``.  A resolution identifies the call site and
the compiler-resolved ``target_symbol`` (or ``symbol_id``).  The protocol is
intentionally transport-only: Roslyn package/tool ownership remains with the
Runtime or host that supplies the service.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

REQUEST_SCHEMA = "simplicio.mapper-semantic-request/v1"
RESULT_SCHEMA = "simplicio.mapper-semantic-result/v1"
PROTOCOL_VERSION = "v1"
COMMAND_ENV = "SIMPLICIO_MAPPER_SEMANTIC_COMMAND"
TIMEOUT_ENV = "SIMPLICIO_MAPPER_SEMANTIC_TIMEOUT_S"
DEFAULT_TIMEOUT_S = 10.0
SUPPORTED_LANGUAGES = frozenset({"csharp", "razor"})


@dataclass(frozen=True)
class SemanticResolutionReceipt:
    status: str
    languages: tuple[str, ...] = ()
    provider: str | None = None
    provider_version: str | None = None
    resolved_calls: int = 0
    symbols: int = 0
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "simplicio.mapper-semantic-resolution/v1",
            "protocol": PROTOCOL_VERSION,
            "status": self.status,
            "languages": list(self.languages),
            "provider": self.provider,
            "provider_version": self.provider_version,
            "resolved_calls": self.resolved_calls,
            "symbols": self.symbols,
            "reason": self.reason,
        }


def _timeout() -> float:
    raw = os.environ.get(TIMEOUT_ENV, "").strip()
    try:
        value = float(raw)
    except ValueError:
        value = DEFAULT_TIMEOUT_S
    return value if value > 0 else DEFAULT_TIMEOUT_S


def _command(value: str | Sequence[str] | None) -> list[str] | None:
    if value is None:
        value = os.environ.get(COMMAND_ENV, "").strip()
    if isinstance(value, str):
        try:
            parts = shlex.split(value)
        except ValueError:
            return None
    else:
        parts = [str(item) for item in value]
    return parts or None


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _int(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 1:
        return value
    return None


def _normalize_result(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema") != RESULT_SCHEMA:
        raise ValueError("semantic_service_schema_mismatch")
    if value.get("protocol") not in {None, PROTOCOL_VERSION}:
        raise ValueError("semantic_service_protocol_unsupported")
    for key in ("resolutions", "symbols"):
        if key in value and not isinstance(value[key], list):
            raise ValueError(f"semantic_service_{key}_invalid")
        if any(not isinstance(item, dict) for item in value.get(key, [])):
            raise ValueError(f"semantic_service_{key}_item_invalid")
    return value


class RoslynSemanticAdapter:
    """Invoke a deterministic Roslyn-compatible semantic service."""

    def __init__(
        self,
        command: str | Sequence[str] | None = None,
        *,
        runner: Callable[..., Any] = subprocess.run,
    ) -> None:
        self.command = command
        self.runner = runner

    def resolve(
        self,
        cwd: str,
        language: str,
        source_generation: list[dict[str, str]],
        symbols: list[dict[str, Any]],
        call_sites: list[dict[str, Any]],
    ) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        languages = tuple(sorted({language}))
        if language not in SUPPORTED_LANGUAGES:
            return None, SemanticResolutionReceipt(
                "not_required", languages=languages, reason="language_not_supported_by_semantic_adapter"
            ).as_dict()
        command = _command(self.command)
        if command is None:
            return None, SemanticResolutionReceipt(
                "unavailable", languages=languages, reason="semantic_service_not_configured"
            ).as_dict()
        request = {
            "schema": REQUEST_SCHEMA,
            "protocol": PROTOCOL_VERSION,
            "language": language,
            "source_generation": sorted(source_generation, key=lambda item: item["path"]),
            "symbols": sorted(
                symbols,
                key=lambda item: (
                    str(item.get("defined_in") or ""),
                    int(item.get("line") or 0),
                    str(item.get("qualified_name") or item.get("name") or ""),
                ),
            ),
            "call_sites": sorted(
                call_sites,
                key=lambda item: (
                    str(item.get("source_file") or ""),
                    int(item.get("line") or 0),
                    str(item.get("name") or ""),
                ),
            ),
        }
        try:
            completed = self.runner(
                command,
                cwd=cwd,
                input=json.dumps(request, ensure_ascii=False, separators=(",", ":")),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=_timeout(),
                check=False,
            )
        except subprocess.TimeoutExpired:
            return None, SemanticResolutionReceipt(
                "unavailable", languages=languages, reason="semantic_service_timeout"
            ).as_dict()
        except (OSError, subprocess.SubprocessError) as error:
            return None, SemanticResolutionReceipt(
                "unavailable", languages=languages, reason=f"semantic_service_execution_failed:{type(error).__name__}"
            ).as_dict()
        if completed.returncode != 0:
            return None, SemanticResolutionReceipt(
                "unavailable", languages=languages, reason=f"semantic_service_exit:{completed.returncode}"
            ).as_dict()
        try:
            result = _normalize_result(json.loads(completed.stdout or ""))
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            return None, SemanticResolutionReceipt(
                "unavailable", languages=languages, reason=f"semantic_service_invalid_result:{error}"
            ).as_dict()
        resolutions = [item for item in result.get("resolutions", []) if isinstance(item, dict)]
        semantic_symbols = [item for item in result.get("symbols", []) if isinstance(item, dict)]
        receipt = SemanticResolutionReceipt(
            "available",
            languages=languages,
            provider=_text(result.get("provider")),
            provider_version=_text(result.get("provider_version")),
            resolved_calls=len(resolutions),
            symbols=len(semantic_symbols),
        ).as_dict()
        return result, receipt


SemanticAdapter = RoslynSemanticAdapter


def resolve_semantic_calls(
    cwd: str,
    language: str,
    source_generation: list[dict[str, str]],
    symbols: list[dict[str, Any]],
    call_sites: list[dict[str, Any]],
    *,
    adapter: RoslynSemanticAdapter | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Resolve call sites, returning a receipt even when no service exists."""
    if not call_sites:
        return None, SemanticResolutionReceipt(
            "not_required", languages=(language,), reason="no_call_sites"
        ).as_dict()
    service = adapter or RoslynSemanticAdapter()
    return service.resolve(cwd, language, source_generation, symbols, call_sites)


def resolution_key(value: Mapping[str, Any]) -> tuple[str, int, str] | None:
    source_file = _text(value.get("source_file"))
    line = _int(value.get("line") or value.get("source_line"))
    name = _text(value.get("name") or value.get("call_name"))
    if not source_file or line is None or not name:
        return None
    return source_file.replace("\\", "/").lstrip("./"), line, name


__all__ = [
    "COMMAND_ENV",
    "PROTOCOL_VERSION",
    "REQUEST_SCHEMA",
    "RESULT_SCHEMA",
    "RoslynSemanticAdapter",
    "SemanticAdapter",
    "SemanticResolutionReceipt",
    "resolution_key",
    "resolve_semantic_calls",
]
