"""Deterministic Markdown, Gherkin, and JSON task normalization.

Task input is untrusted data. This module performs no repository IO, command
execution, network access, or model calls.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

TASK_INTENT_SCHEMA = "simplicio.task-intent/v1"
TASK_CONTEXT_SCHEMA = "simplicio.task-context/v1"

_SECTIONS = {
    "criterios de aceite": "acceptance_criteria",
    "acceptance criteria": "acceptance_criteria",
    "regras de negocio": "business_rules",
    "business rules": "business_rules",
    "requisitos nao funcionais": "non_functional_requirements",
    "non functional requirements": "non_functional_requirements",
    "non-functional requirements": "non_functional_requirements",
    "prototipos": "prototypes",
    "prototypes": "prototypes",
    "acesso": "access",
    "access": "access",
    "dependencias": "dependencies",
    "dependencies": "dependencies",
    "sinais de impacto": "impact",
    "impact": "impact",
    "informacoes adicionais": "additional_information",
    "additional information": "additional_information",
}
_METADATA = {
    "sistema": "system",
    "system": "system",
    "funcionalidade": "functionality",
    "functionality": "functionality",
    "feature": "functionality",
    "tipo": "change_type",
    "type": "change_type",
    "change type": "change_type",
}
_IMPACT = {
    "frontend": "frontend",
    "front end": "frontend",
    "backend": "backend",
    "back end": "backend",
    "banco": "database",
    "banco de dados": "database",
    "database": "database",
    "integracoes": "integrations",
    "integrations": "integrations",
}
_RULE_REF = re.compile(r"\bRN\d+\b", re.IGNORECASE)
_MARKDOWN_REF = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
_URL = re.compile(r"https?://\S+")
_BUDGET_HINTS = (
    re.compile(
        r"\b(?:serialized|seriali[sz]ed|output|context)\s+(?:token\s+)?budget\s*(?:[:=]|of|is|within|under|<=)?\s*(\d{2,6})\b",
        re.IGNORECASE,
    ),
    re.compile(r"\btoken\s+budget\s*(?:[:=]|of|is|within|under|<=)?\s*(\d{2,6})\b", re.IGNORECASE),
    re.compile(r"\bwithin\s+(\d{2,6})\s+tokens\b", re.IGNORECASE),
)


def _text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", str(value))).strip()


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(char for char in normalized if not unicodedata.combining(char)).casefold()


def _plain(line: str) -> str:
    value = re.sub(r"^#{1,6}\s*", "", line.strip())
    value = re.sub(r"^\d+\.\s*", "", value)
    return value.strip("*_ ").strip()


def _list_value(line: str) -> str:
    return _text(re.sub(r"^(?:[-*+]\s+|\d+[.)]\s+)", "", line.strip()))


def _as_list(value: Any) -> list[str]:
    values = value if isinstance(value, list) else ([] if value is None else [value])
    return [_text(item) for item in values if _text(item)]


def _without_refs(value: Any) -> str:
    return _text(re.sub(r"\s*\[(?:RN\d+|AC\d+)\]", "", _text(value), flags=re.IGNORECASE))


def _rule_ids(*values: Any) -> list[str]:
    found: set[str] = set()
    for value in values:
        items = value if isinstance(value, list) else [value]
        for item in items:
            found.update(match.upper() for match in _RULE_REF.findall(str(item or "")))
    return sorted(found, key=lambda item: (int(item[2:]), item))


def _identifier(value: Any, prefix: str, index: int) -> str:
    match = re.search(rf"\b{prefix}\s*0*(\d+)\b", _text(value), re.IGNORECASE)
    return f"{prefix}{int(match.group(1)):02d}" if match else f"{prefix}{index:02d}"


def canonical_json(value: Any) -> str:
    """Return deterministic UTF-8-safe JSON text."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _flatten_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [_text(value)] if _text(value) else []
    if isinstance(value, Mapping):
        chunks: list[str] = []
        for key in sorted(value, key=str):
            if key in {"fingerprint", "schema"}:
                continue
            chunks.extend(_flatten_strings(value[key]))
        return chunks
    if isinstance(value, (list, tuple, set)):
        chunks: list[str] = []
        for item in value:
            chunks.extend(_flatten_strings(item))
        return chunks
    return []


def extract_task_context_settings(
    *,
    goal: str = "",
    task_intent: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Extract deterministic task-context hints without changing the v1 schema.

    This keeps `parse_task_intent()` backward compatible while still allowing
    the task-aware handoff path to honor inline budget directives such as
    "serialized output budget 120" or "within 300 tokens".
    """
    text = "\n".join([goal, *_flatten_strings(task_intent or {})])
    budget: int | None = None
    for pattern in _BUDGET_HINTS:
        match = pattern.search(text)
        if match:
            budget = int(match.group(1))
            break
    return {
        "serialized_output_token_budget": budget,
        "budget_declared": budget is not None,
    }


def build_task_query_plan(
    *,
    goal: str = "",
    task_intent: Mapping[str, Any] | None = None,
    target: str = "",
    query_terms: list[str] | None = None,
) -> dict[str, Any]:
    """Return the normalized retrieval query plan used by task-aware selection."""
    from .retrieval_index import build_query_plan

    return build_query_plan(
        goal,
        task_intent=task_intent,
        target=target,
        query_terms=query_terms,
    ).to_dict()


def _scenario(value: Any, index: int) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {"title": value}
    given = [_without_refs(item) for item in _as_list(raw.get("given"))]
    when = [_without_refs(item) for item in _as_list(raw.get("when"))]
    then = [_without_refs(item) for item in _as_list(raw.get("then"))]
    return {
        "id": _identifier(raw.get("id"), "AC", index),
        "title": _without_refs(raw.get("title")),
        "given": given,
        "when": when,
        "then": then,
        "rule_ids": _rule_ids(
            raw.get("rule_ids"),
            raw.get("title"),
            raw.get("given"),
            raw.get("when"),
            raw.get("then"),
        ),
    }


def _rule(value: Any, index: int) -> dict[str, str]:
    if isinstance(value, dict):
        return {
            "id": _identifier(value.get("id"), "RN", index),
            "description": _text(value.get("description") or value.get("text")),
        }
    match = re.match(r"^(RN\d+)\s*[-\u2013\u2014:]\s*(.+)$", _text(value), re.IGNORECASE)
    if match:
        return {"id": _identifier(match.group(1), "RN", index), "description": _text(match.group(2))}
    return {"id": f"RN{index:02d}", "description": _text(value)}


def _requirement(value: Any, index: int) -> dict[str, str]:
    if isinstance(value, dict):
        return {
            "id": _identifier(value.get("id"), "NFR", index),
            "description": _text(value.get("description") or value.get("text")),
        }
    match = re.match(r"^(?:NFR|RNF)\s*0*(\d+)\s*[-\u2013\u2014:]\s*(.+)$", _text(value), re.IGNORECASE)
    if match:
        return {"id": f"NFR{int(match.group(1)):02d}", "description": _text(match.group(2))}
    return {"id": f"NFR{index:02d}", "description": _text(value)}


def _prototype(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        description = _text(value.get("description") or value.get("text"))
        references = _as_list(value.get("references"))
    else:
        description, references = _text(value), []
    references.extend(_MARKDOWN_REF.findall(description))
    references.extend(_URL.findall(description))
    return {
        "description": _text(_MARKDOWN_REF.sub("", description)),
        "references": sorted(set(_text(item) for item in references if _text(item))),
    }


def _impact_signal(value: Any) -> dict[str, str]:
    if isinstance(value, dict):
        signal = _fold(_text(value.get("signal") or "unknown")).replace(" ", "_")
        notes = _text(value.get("notes"))
    else:
        raw, folded = _text(value), _fold(_text(value))
        if raw.startswith("\u2713") or re.match(r"^(?:yes|sim)\b", folded):
            signal = "yes"
        elif raw.startswith("\u2717") or re.match(r"^(?:no|nao)\b", folded):
            signal = "no"
        elif re.match(r"^(?:possible|possivel)\b", folded):
            signal = "possible"
        else:
            signal = "unknown"
        prefix = r"^(?:\u2713|\u2717|yes|sim|no|n(?:a|\u00e3)o|possible|poss(?:i|\u00ed)vel)\s*"
        notes = _text(re.sub(prefix, "", raw, flags=re.IGNORECASE).strip("() "))
    if signal not in {"yes", "no", "possible", "unknown"}:
        signal = "unknown"
    return {"signal": signal, "notes": notes}


def _first(raw: dict[str, Any], *keys: str) -> Any:
    return next((raw[key] for key in keys if key in raw), "")


def _normalize_mapping(raw: dict[str, Any]) -> dict[str, Any]:
    story = raw.get("story") or raw.get("historia") or {}
    story = story if isinstance(story, dict) else {}
    acceptance = raw.get("acceptance_criteria") or raw.get("scenarios") or raw.get("cenarios") or []
    rules = raw.get("business_rules") or raw.get("rules") or raw.get("regras_negocio") or []
    requirements = (
        raw.get("non_functional_requirements") or raw.get("nfr") or raw.get("requisitos_nao_funcionais") or []
    )
    prototypes = raw.get("prototypes") or raw.get("prototipos") or []
    impact_raw = raw.get("impact") or raw.get("sinais_impacto") or {}
    impact: dict[str, dict[str, str]] = {}
    if isinstance(impact_raw, dict):
        for key, value in impact_raw.items():
            canonical_key = _IMPACT.get(_fold(_text(key)), _text(key))
            if canonical_key:
                impact[canonical_key] = _impact_signal(value)

    intent = {
        "schema": TASK_INTENT_SCHEMA,
        "system": _text(_first(raw, "system", "sistema")),
        "functionality": _text(_first(raw, "functionality", "funcionalidade", "feature")),
        "change_type": _text(_first(raw, "change_type", "type", "tipo")),
        "story": {
            "actor": _text(_first(story, "actor", "as_a", "como")).rstrip(","),
            "desire": _text(_first(story, "desire", "want", "quero")).rstrip(","),
            "benefit": _text(_first(story, "benefit", "so_that", "para")),
        },
        "acceptance_criteria": [_scenario(item, index) for index, item in enumerate(acceptance, 1)],
        "business_rules": [_rule(item, index) for index, item in enumerate(rules, 1)],
        "non_functional_requirements": [
            _requirement(item, index) for index, item in enumerate(requirements, 1)
        ],
        "prototypes": [_prototype(item) for item in prototypes],
        "access": _as_list(raw.get("access") or raw.get("acesso")),
        "dependencies": _as_list(raw.get("dependencies") or raw.get("dependencias")),
        "impact": dict(sorted(impact.items())),
        "additional_information": _as_list(
            raw.get("additional_information") or raw.get("informacoes_adicionais")
        ),
    }
    semantic = deepcopy(intent)
    intent["fingerprint"] = hashlib.sha256(canonical_json(semantic).encode("utf-8")).hexdigest()
    return intent


def _section(line: str) -> str | None:
    return _SECTIONS.get(_fold(_plain(line)).rstrip(":"))


def _parse_text(raw: str) -> dict[str, Any]:
    data: dict[str, Any] = {
        "story": {},
        "acceptance_criteria": [],
        "business_rules": [],
        "non_functional_requirements": [],
        "prototypes": [],
        "access": [],
        "dependencies": [],
        "impact": {},
        "additional_information": [],
    }
    section_lines: dict[str, list[str]] = {name: [] for name in set(_SECTIONS.values())}
    current_section: str | None = None
    current_scenario: dict[str, Any] | None = None
    current_step: str | None = None

    for source_line in raw.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if not source_line.strip():
            continue
        matched_section = _section(source_line)
        if matched_section:
            current_section, current_scenario, current_step = matched_section, None, None
            continue
        plain = _plain(source_line)

        metadata = re.match(r"^([^:]+):\s*(.+)$", plain)
        if metadata and (key := _METADATA.get(_fold(metadata.group(1)))):
            data[key] = _text(metadata.group(2))
            continue

        story_patterns = (
            ("actor", r"^(?:COMO|AS\s+AN?)\s+(.+)$"),
            ("desire", r"^(?:QUERO|I\s+WANT)\s+(.+)$"),
            ("benefit", r"^(?:PARA|SO\s+THAT)\s+(.+)$"),
        )
        story_match = next(
            ((key, match) for key, pattern in story_patterns if (match := re.match(pattern, plain, re.I))),
            None,
        )
        if story_match:
            data["story"][story_match[0]] = _text(story_match[1].group(1)).rstrip(",")
            continue

        criterion_match = re.match(
            r"^(AC\s*\d+)\s*[-\u2013\u2014:]\s*(.+)$",
            _list_value(plain),
            re.IGNORECASE,
        )
        if criterion_match and current_section == "acceptance_criteria":
            current_scenario = {
                "id": criterion_match.group(1),
                "title": criterion_match.group(2),
                "given": [],
                "when": [],
                "then": [],
                "rule_ids": _rule_ids(criterion_match.group(2)),
            }
            data["acceptance_criteria"].append(current_scenario)
            current_step = None
            continue

        scenario_match = re.match(
            r"^(?:CEN(?:A|\u00c1)RIO|SCENARIO)(?:\s+(AC\s*\d+|\d+))?\s*:\s*(.+)$",
            plain,
            re.IGNORECASE,
        )
        if scenario_match:
            token = scenario_match.group(1)
            scenario_id = token if token and _fold(token).startswith("ac") else None
            if token and token.isdigit():
                scenario_id = f"AC{int(token):02d}"
            current_scenario = {
                "id": scenario_id,
                "title": scenario_match.group(2),
                "given": [],
                "when": [],
                "then": [],
                "rule_ids": [],
            }
            data["acceptance_criteria"].append(current_scenario)
            current_step = None
            continue

        if current_scenario is not None:
            step = re.match(
                r"^(DADO|GIVEN|QUANDO|WHEN|ENT(?:A|\u00c3)O|THEN)\s+(.+)$",
                plain,
                re.IGNORECASE,
            )
            if step:
                current_step = {
                    "dado": "given",
                    "given": "given",
                    "quando": "when",
                    "when": "when",
                    "entao": "then",
                    "then": "then",
                }[_fold(step.group(1))]
                value = step.group(2)
                current_scenario["rule_ids"].extend(_rule_ids(value))
                current_scenario[current_step].append(_without_refs(value))
                continue
            and_step = re.match(r"^(?:E|AND)\s+(.+)$", plain, re.IGNORECASE)
            if and_step and current_step:
                value = and_step.group(1)
                current_scenario["rule_ids"].extend(_rule_ids(value))
                current_scenario[current_step].append(_without_refs(value))
                continue

        rule = re.match(r"^(RN\d+)\s*[-\u2013\u2014:]\s*(.+)$", _list_value(plain), re.IGNORECASE)
        if rule and current_section == "business_rules":
            data["business_rules"].append({"id": rule.group(1).upper(), "description": _text(rule.group(2))})
            continue
        if current_section and (value := _list_value(plain)):
            section_lines[current_section].append(value)

    for key in ("business_rules", "non_functional_requirements", "prototypes"):
        data[key].extend(section_lines[key])
    for key in ("access", "dependencies", "additional_information"):
        data[key].extend(section_lines[key])
    for value in section_lines["impact"]:
        if (match := re.match(r"^([^:]+):\s*(.+)$", value)) and (key := _IMPACT.get(_fold(match.group(1)))):
            data["impact"][key] = match.group(2)
    return _normalize_mapping(data)


def parse_task_intent(raw: str | dict[str, Any], *, source_format: str = "auto") -> dict[str, Any]:
    """Parse a raw task into the versioned deterministic intent model."""
    if source_format not in {"auto", "markdown", "gherkin", "json"}:
        raise ValueError("source_format must be auto, markdown, gherkin, or json")
    if isinstance(raw, dict):
        return _normalize_mapping(raw)
    if not isinstance(raw, str):
        raise TypeError("raw task must be text or a JSON object")
    stripped = raw.lstrip("\ufeff \t\r\n")
    if source_format in {"auto", "json"} and stripped.startswith("{"):
        try:
            decoded = json.loads(stripped)
        except json.JSONDecodeError:
            if source_format == "json":
                raise
        else:
            if not isinstance(decoded, dict):
                raise TypeError("JSON task must be an object")
            return _normalize_mapping(decoded)
    return _parse_text(raw)


normalize_task_intent = parse_task_intent

__all__ = [
    "TASK_CONTEXT_SCHEMA",
    "TASK_INTENT_SCHEMA",
    "build_task_query_plan",
    "canonical_json",
    "extract_task_context_settings",
    "normalize_task_intent",
    "parse_task_intent",
]
