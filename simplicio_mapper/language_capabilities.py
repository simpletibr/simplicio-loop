"""Language/capability negotiation for the Mapper execution boundary.

The Mapper observes every language supported by the Python implementation, but
the optional native core is promoted one capability at a time.  A native
kernel therefore cannot make an unsupported capability disappear: callers get
an explicit Python-reference route and the receipt records the degradation.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from . import _native

CAPABILITY_SCHEMA = "simplicio.mapper-capability-coverage/v1"
CONTRACT_VERSION = "v1"

# Keep this list aligned with the language detector in mapper.parse.  The list
# is deliberately broader than the Rust core's current language set; the
# Python mapper remains the canonical implementation for the rest.
LANGUAGES = (
    "csharp",
    "razor",
    "sql",
    "typescript",
    "javascript",
    "python",
    "rust",
    "go",
    "java",
    "kotlin",
    "dart",
    "c",
    "cpp",
    "swift",
    "objectivec",
    "vue",
    "svelte",
    "scala",
    "php",
    "ruby",
    "elixir",
    "erlang",
    "lua",
    "r",
    "julia",
    "perl",
    "matlab",
    "html",
    "xhtml",
    "css",
    "scss",
    "sass",
    "less",
    "html-template",
)

CAPABILITIES = (
    "language-detection",
    "file-inventory",
    "imports",
    "symbols",
    "local-references",
    "calls",
    "endpoints-routes",
    "screens-templates",
    "sql-objects",
    "business-rules",
    "flows",
    "tests",
    "architecture",
    "precedents",
    "retrieval-hints",
)

PRIORITY_STACKS = (
    {"priority": 1, "name": "dotnet", "languages": ["csharp", "razor"], "frameworks": ["aspnet", "azure-functions"]},
    {"priority": 2, "name": "sql", "languages": ["sql"], "frameworks": []},
    {"priority": 3, "name": "typescript-javascript", "languages": ["typescript", "javascript"], "frameworks": []},
    {"priority": 4, "name": "python", "languages": ["python"], "frameworks": []},
    {"priority": 5, "name": "rust", "languages": ["rust"], "frameworks": []},
    {"priority": 6, "name": "go", "languages": ["go"], "frameworks": []},
    {"priority": 7, "name": "jvm", "languages": ["java", "kotlin"], "frameworks": []},
    {
        "priority": 8,
        "name": "remaining",
        "languages": [
            "dart", "c", "cpp", "swift", "objectivec", "vue", "svelte", "scala",
            "php", "ruby", "elixir", "erlang", "lua", "r", "julia", "perl", "matlab",
            "html", "xhtml", "css", "scss", "sass", "less", "html-template",
        ],
        "frameworks": [],
    },
)

STATUSES = frozenset({"MISSING", "SHADOW", "NATIVE_PARITY", "MISMATCH"})

# SHADOW means that the Python mapper has a deterministic implementation, but
# no native parity proof exists.  MISSING is intentionally conservative: the
# artifact may carry discovery facts, but it cannot claim this capability.
_SHADOW_CAPABILITIES = frozenset(
    {
        "language-detection",
        "file-inventory",
        "symbols",
        "calls",
        "endpoints-routes",
        "screens-templates",
        "business-rules",
        "flows",
        "tests",
        "architecture",
        "precedents",
        "retrieval-hints",
    }
)

_NATIVE_PARITY_LANGUAGES = frozenset(
    {"python", "javascript", "typescript", "csharp", "razor", "go"}
)


def _baseline_status(language: str, capability: str) -> str:
    if capability == "imports" and language in _NATIVE_PARITY_LANGUAGES:
        return "NATIVE_PARITY"
    if capability == "sql-objects":
        return "SHADOW" if language == "sql" else "MISSING"
    if capability in _SHADOW_CAPABILITIES:
        return "SHADOW"
    return "MISSING"


def _native_route(language: str, capability: str) -> dict[str, Any]:
    native_capability = {
        "imports": "imports",
    }.get(capability)
    if native_capability is None:
        return {
            "backend": "python-reference",
            "status": "fallback",
            "reason": "native_capability_not_advertised",
        }
    if _native.native_default(native_capability, language):
        return {
            "backend": "rust-core",
            "status": "native",
            "reason": "capability_parity_and_language_supported",
        }
    if not _native.HAS_NATIVE:
        reason = "native_extension_unavailable"
    elif language not in set(_native.CAPABILITIES.get("languages") or ()):
        reason = "language_not_advertised_by_native_core"
    else:
        reason = "native_capability_not_available"
    return {"backend": "python-reference", "status": "fallback", "reason": reason}


def native_route(language: str, capability: str) -> dict[str, Any]:
    """Return the safe backend route for one language/capability pair."""
    if language not in LANGUAGES:
        return {
            "backend": "python-reference",
            "status": "fallback",
            "reason": "language_not_in_capability_catalog",
        }
    if capability not in CAPABILITIES:
        return {
            "backend": "python-reference",
            "status": "fallback",
            "reason": "capability_not_in_catalog",
        }
    return _native_route(language, capability)


def _promotion(language: str, statuses: Mapping[str, str]) -> dict[str, Any]:
    blockers = sorted(
        capability
        for capability in CAPABILITIES
        if statuses.get(capability) in {"MISSING", "MISMATCH"}
    )
    return {
        "native_default": not blockers,
        "eligible": not blockers,
        "blocking_capabilities": blockers,
        "rule": "native promotion requires every advertised capability to be NATIVE_PARITY",
    }


def build_capability_coverage(
    files: Iterable[Any],
    *,
    semantic_resolution: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a bounded receipt for languages observed in one mapping run.

    The static matrix is the authority for promotion.  This receipt adds the
    observed file counts, actual native routes and semantic-service status so
    downstream handoffs can explain why a language was or was not promoted.
    """
    counts: dict[str, int] = {}
    for file in files:
        language = str(getattr(file, "language", "") or "")
        if language:
            counts[language] = counts.get(language, 0) + 1

    semantic = dict(semantic_resolution or {})
    semantic_languages = set(semantic.get("languages") or ())
    observed: dict[str, Any] = {}
    promotions: dict[str, Any] = {}
    for language in sorted(counts):
        statuses = {capability: _baseline_status(language, capability) for capability in CAPABILITIES}
        status_groups: dict[str, list[str]] = {}
        backend_groups: dict[str, list[str]] = {}
        route_groups: dict[str, list[str]] = {}
        evidence_groups: dict[str, list[str]] = {}
        for capability in CAPABILITIES:
            route = native_route(language, capability)
            evidence = "semantic" if capability == "calls" and language in semantic_languages else "reference"
            status_groups.setdefault(statuses[capability], []).append(capability)
            backend_groups.setdefault(route["backend"], []).append(capability)
            route_groups.setdefault(route["status"], []).append(capability)
            evidence_groups.setdefault(evidence, []).append(capability)
        if language in semantic_languages and semantic.get("status") == "available":
            backend_groups.setdefault("python-reference", []).remove("calls")
            backend_groups.setdefault("semantic-service", []).append("calls")
            route_groups.setdefault("fallback", []).remove("calls")
            route_groups.setdefault("semantic", []).append("calls")
        degradations: list[str] = []
        if language in {"csharp", "razor"} and semantic.get("status") != "available":
            degradations.append(
                f"calls:{language}:{semantic.get('reason') or 'semantic_service_unavailable'}"
            )
        observed[language] = {
            "file_count": counts[language],
            "capabilities": {
                "status": {key: values for key, values in sorted(status_groups.items())},
                "backend": {key: values for key, values in sorted(backend_groups.items())},
                "route_status": {key: values for key, values in sorted(route_groups.items())},
                "evidence": {key: values for key, values in sorted(evidence_groups.items())},
            },
            "degraded": sorted(degradations),
        }
        promotions[language] = _promotion(language, statuses)

    return {
        "schema": CAPABILITY_SCHEMA,
        "version": 1,
        "contract_version": CONTRACT_VERSION,
        "required_capabilities": list(CAPABILITIES),
        "languages": observed,
        "native_promotion": promotions,
        "semantic_resolution": semantic,
    }


def build_matrix_rows(
    evidence: Mapping[tuple[str, str], Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Build canonical rows; only explicit green evidence can promote a row."""
    evidence = evidence or {}
    rows: list[dict[str, Any]] = []
    for language in LANGUAGES:
        for capability in CAPABILITIES:
            key = (language, capability)
            baseline = _baseline_status(language, capability)
            proof = evidence.get(key, {})
            status = str(proof.get("status") or baseline)
            if status not in STATUSES:
                status = "MISMATCH"
            if status == "NATIVE_PARITY" and proof.get("native_default") is not True:
                status = "MISMATCH"
            rows.append(
                {
                    "language": language,
                    "capability": capability,
                    "contract_version": CONTRACT_VERSION,
                    "status": status,
                    "native_default": status == "NATIVE_PARITY",
                    "evidence_id": proof.get("evidence_id"),
                }
            )
    return rows


def validate_promotion(rows: Iterable[Mapping[str, Any]]) -> list[str]:
    """Fail closed if a language is promoted with a missing/mismatched row."""
    rows = list(rows)
    grouped: dict[str, dict[str, str]] = {}
    errors: list[str] = []
    for row in rows:
        language = str(row.get("language") or "")
        capability = str(row.get("capability") or "")
        status = str(row.get("status") or "")
        if language not in LANGUAGES or capability not in CAPABILITIES:
            errors.append(f"row_key_invalid:{language}@{capability}")
            continue
        grouped.setdefault(language, {})[capability] = status
    for row in rows:
        if row.get("native_default") is True and row.get("status") != "NATIVE_PARITY":
            errors.append(
                f"native_default_without_parity:{row.get('language')}@{row.get('capability')}"
            )
    for language in LANGUAGES:
        statuses = grouped.get(language, {})
        missing = [capability for capability in CAPABILITIES if capability not in statuses]
        if missing:
            errors.append(f"matrix_incomplete:{language}")
    return errors


__all__ = [
    "CAPABILITIES",
    "CAPABILITY_SCHEMA",
    "CONTRACT_VERSION",
    "LANGUAGES",
    "PRIORITY_STACKS",
    "build_capability_coverage",
    "build_matrix_rows",
    "native_route",
    "validate_promotion",
]
