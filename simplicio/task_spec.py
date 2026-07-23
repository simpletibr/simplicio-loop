"""Deterministic intake for raw task cards.

This module is deliberately provider-free: it turns Portuguese or English
Markdown into the versioned ``simplicio.task-spec/v2`` interchange contract
without invoking an LLM, mapper, runtime, or edit operator.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from dataclasses import fields as dataclass_fields
from typing import Any

TASK_SPEC_SCHEMA = "simplicio.task-spec/v2"
TASK_SPEC_COMPATIBILITY = {
    "major": 2,
    "minimum_consumer_major": 2,
    "contract": "additive-fields-within-major",
    "consumers": ["simplicio-runtime", "simplicio-loop", "simplicio-mcp"],
}


class TaskSpecValidationError(ValueError):
    """Raised when raw input cannot become a valid TaskSpec."""

    def __init__(self, diagnostics: Iterable[str]) -> None:
        self.diagnostics = list(diagnostics)
        super().__init__("; ".join(self.diagnostics))


def _contains_non_finite(value: Any) -> bool:
    if isinstance(value, float):
        return not math.isfinite(value)
    if isinstance(value, dict):
        return any(_contains_non_finite(key) or _contains_non_finite(item) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return any(_contains_non_finite(item) for item in value)
    return False


@dataclass(frozen=True)
class SourceSpan:
    start: int
    end: int
    start_line: int
    end_line: int

    def to_dict(self) -> dict[str, int]:
        return {
            "start": self.start,
            "end": self.end,
            "start_line": self.start_line,
            "end_line": self.end_line,
        }


@dataclass(frozen=True)
class SourceRef:
    kind: str = "argument"
    locator: str | None = None
    encoding: str = "utf-8"


@dataclass
class TaskSpec:
    task_id: str
    source: dict[str, Any]
    source_hash: str
    language: str
    system: str | None = None
    functionality: str | None = None
    task_type: str | None = None
    narrative: dict[str, str | None] = field(default_factory=dict)
    acceptance_criteria: list[dict[str, Any]] = field(default_factory=list)
    business_rules: list[dict[str, Any]] = field(default_factory=list)
    non_functional_requirements: list[dict[str, Any]] = field(default_factory=list)
    prototypes: list[dict[str, Any]] = field(default_factory=list)
    attachments: list[dict[str, Any]] = field(default_factory=list)
    navigation: list[dict[str, Any]] = field(default_factory=list)
    dependencies: list[dict[str, Any]] = field(default_factory=list)
    impact_signals: dict[str, dict[str, Any]] = field(default_factory=dict)
    additional_information: list[dict[str, Any]] = field(default_factory=list)
    uncertainties: list[dict[str, Any]] = field(default_factory=list)
    human_gates: list[dict[str, Any]] = field(default_factory=list)
    verification_commands: list[dict[str, Any]] = field(default_factory=list)
    source_span: dict[str, int] = field(default_factory=dict)
    original_text: str = ""
    extra_fields: dict[str, Any] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        reserved = {item.name for item in dataclass_fields(type(self)) if item.name != "extra_fields"} | {
            "schema"
        }
        collisions = sorted(reserved & set(self.extra_fields))
        if collisions:
            raise TaskSpecValidationError(
                [f"TaskSpec additive fields collide with reserved fields: {', '.join(collisions)}"]
            )

    def to_dict(self) -> dict[str, Any]:
        payload = dict(self.extra_fields)
        payload.update(
            {
                "schema": TASK_SPEC_SCHEMA,
                "task_id": self.task_id,
                "source": self.source,
                "source_hash": self.source_hash,
                "language": self.language,
                "system": self.system,
                "functionality": self.functionality,
                "task_type": self.task_type,
                "narrative": self.narrative,
                "acceptance_criteria": self.acceptance_criteria,
                "business_rules": self.business_rules,
                "non_functional_requirements": self.non_functional_requirements,
                "prototypes": self.prototypes,
                "attachments": self.attachments,
                "navigation": self.navigation,
                "dependencies": self.dependencies,
                "impact_signals": self.impact_signals,
                "additional_information": self.additional_information,
                "uncertainties": self.uncertainties,
                "human_gates": self.human_gates,
                "verification_commands": self.verification_commands,
                "source_span": self.source_span,
                "original_text": self.original_text,
            }
        )
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> TaskSpec:
        """Restore a version-compatible external TaskSpec without dropping fields."""
        if not isinstance(payload, dict):
            raise TaskSpecValidationError(["TaskSpec payload must be an object"])
        schema = payload.get("schema")
        if schema != TASK_SPEC_SCHEMA:
            raise TaskSpecValidationError(
                [f"unsupported TaskSpec schema {schema!r}; expected {TASK_SPEC_SCHEMA!r}"]
            )
        required = ("task_id", "source", "source_hash", "language")
        missing = [name for name in required if not payload.get(name)]
        if missing:
            raise TaskSpecValidationError([f"TaskSpec missing required fields: {', '.join(missing)}"])
        if not isinstance(payload["task_id"], str):
            raise TaskSpecValidationError(["TaskSpec task_id must be a string"])
        if not isinstance(payload["source"], dict):
            raise TaskSpecValidationError(["TaskSpec source must be an object"])
        if not isinstance(payload["language"], str):
            raise TaskSpecValidationError(["TaskSpec language must be a string"])
        for name in ("system", "functionality", "task_type"):
            if payload.get(name) is not None and not isinstance(payload[name], str):
                raise TaskSpecValidationError([f"TaskSpec {name} must be a string or null"])
        narrative = payload.get("narrative", {})
        if not isinstance(narrative, dict):
            raise TaskSpecValidationError(["TaskSpec narrative must be an object"])
        if any(
            not isinstance(key, str) or (value is not None and not isinstance(value, str))
            for key, value in narrative.items()
        ):
            raise TaskSpecValidationError(
                ["TaskSpec narrative keys must be strings and values must be strings or null"]
            )
        list_fields = (
            "acceptance_criteria",
            "business_rules",
            "non_functional_requirements",
            "prototypes",
            "attachments",
            "navigation",
            "dependencies",
            "additional_information",
            "uncertainties",
            "human_gates",
            "verification_commands",
        )
        for name in list_fields:
            value = payload.get(name, [])
            if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
                raise TaskSpecValidationError([f"TaskSpec {name} must be a list of objects"])
        if not isinstance(payload.get("impact_signals", {}), dict):
            raise TaskSpecValidationError(["TaskSpec impact_signals must be an object"])
        if not isinstance(payload.get("source_span", {}), dict):
            raise TaskSpecValidationError(["TaskSpec source_span must be an object"])
        if not isinstance(payload.get("original_text", ""), str):
            raise TaskSpecValidationError(["TaskSpec original_text must be a string"])
        if _contains_non_finite(payload):
            raise TaskSpecValidationError(["TaskSpec must not contain NaN or infinite numbers"])
        if not isinstance(payload["source_hash"], str) or not re.fullmatch(
            r"[0-9a-f]{64}", payload["source_hash"]
        ):
            raise TaskSpecValidationError(["TaskSpec source_hash must be a lowercase SHA-256 digest"])
        original_text = payload.get("original_text", "")
        if original_text and _source_hash(str(original_text)) != payload["source_hash"]:
            raise TaskSpecValidationError(
                ["TaskSpec source_hash does not match the normalized original_text"]
            )
        criteria = payload.get("acceptance_criteria", [])
        if not isinstance(criteria, list) or not criteria:
            raise TaskSpecValidationError(["TaskSpec acceptance_criteria must be a non-empty list"])
        criterion_ids = [str(item.get("id", "")).strip() for item in criteria if isinstance(item, dict)]
        if len(criterion_ids) != len(criteria) or any(not item for item in criterion_ids):
            raise TaskSpecValidationError(
                ["every acceptance criterion must be an object with a non-empty id"]
            )
        if len(criterion_ids) != len(set(criterion_ids)):
            raise TaskSpecValidationError(["TaskSpec contains duplicate acceptance criterion IDs"])
        for command in payload.get("verification_commands", []):
            if not isinstance(command.get("command"), str) or not command["command"].strip():
                raise TaskSpecValidationError(
                    ["every verification command must contain a non-empty command string"]
                )
            verifier = command.get("verifier", "pytest")
            if not isinstance(verifier, str) or not verifier.strip():
                raise TaskSpecValidationError(
                    ["every verification command verifier must be a non-empty string"]
                )
            timeout = command.get("timeout_s", 300.0)
            if (
                isinstance(timeout, bool)
                or not isinstance(timeout, (int, float))
                or not math.isfinite(float(timeout))
                or timeout <= 0
            ):
                raise TaskSpecValidationError(
                    ["every verification command timeout_s must be a positive finite number"]
                )

        known = {item.name for item in dataclass_fields(cls)} - {"extra_fields"}
        values = {name: payload[name] for name in known if name in payload}
        values["extra_fields"] = {
            name: value for name, value in payload.items() if name not in known and name != "schema"
        }
        return cls(**values)

    def canonical_hash(self) -> str:
        """Return the stable digest used to prove lossless handoff between processes."""
        encoded = json.dumps(
            self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass
class TaskSpecDocument:
    tasks: list[TaskSpec]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": TASK_SPEC_SCHEMA,
            "compatibility": dict(TASK_SPEC_COMPATIBILITY),
            "tasks": [task.to_dict() for task in self.tasks],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> TaskSpecDocument:
        if not isinstance(payload, dict):
            raise TaskSpecValidationError(["TaskSpec document must be an object"])
        if payload.get("schema") != TASK_SPEC_SCHEMA:
            raise TaskSpecValidationError(
                [f"unsupported TaskSpec schema {payload.get('schema')!r}; expected {TASK_SPEC_SCHEMA!r}"]
            )
        raw_tasks = payload.get("tasks")
        if not isinstance(raw_tasks, list) or not raw_tasks:
            raise TaskSpecValidationError(["TaskSpec document must contain at least one task"])
        return cls(tasks=[TaskSpec.from_dict(task) for task in raw_tasks])


@dataclass(frozen=True)
class _Line:
    text: str
    start: int
    end: int
    number: int


_SECTION_NAMES = {
    "acceptance_criteria": ("criterios de aceite", "criterio de aceite", "acceptance criteria"),
    "business_rules": ("regras de negocio", "regra de negocio", "business rules", "business rule"),
    "non_functional_requirements": (
        "requisitos nao funcionais",
        "requisito nao funcional",
        "non functional requirements",
        "non functional requirement",
    ),
    "prototypes": ("prototipos", "prototipo", "prototypes", "prototype"),
    "attachments": ("anexos", "anexo", "attachments", "attachment"),
    "navigation": ("acesso", "navegacao", "access", "navigation"),
    "dependencies": (
        "dependencias",
        "dependencia",
        "dependencies",
        "dependency",
        "arquivos alvo do slice",
        "target files",
        "slice target files",
    ),
    "impact_signals": ("sinais de impacto", "impact signals", "impact"),
    "additional_information": (
        "informacoes adicionais",
        "informacao adicional",
        "additional information",
        "additional notes",
    ),
    "uncertainties": ("incertezas", "uncertainties"),
    "human_gates": ("gates humanos", "human gates"),
    "contract": ("contract",),
    "constraints": ("constraints",),
}


def _fold(value: str) -> str:
    table = str.maketrans("áàâãäéèêëíìîïóòôõöúùûüçñ", "aaaaaeeeeiiiiooooouuuucn")
    return value.lower().translate(table)


def _normalized_for_hash(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def _source_hash(text: str) -> str:
    return hashlib.sha256(_normalized_for_hash(text).encode("utf-8")).hexdigest()


def _lines(text: str, *, base_start: int = 0, base_line: int = 1) -> list[_Line]:
    result: list[_Line] = []
    offset = 0
    for index, raw in enumerate(text.splitlines(keepends=True)):
        clean = raw.rstrip("\r\n")
        result.append(_Line(clean, base_start + offset, base_start + offset + len(clean), base_line + index))
        offset += len(raw)
    if text and not result:
        result.append(_Line(text, base_start, base_start + len(text), base_line))
    return result


def _span(lines: list[_Line], first: int, last: int | None = None) -> SourceSpan:
    final = first if last is None else last
    return SourceSpan(lines[first].start, lines[final].end, lines[first].number, lines[final].number)


def _clean_heading(text: str) -> str:
    value = re.sub(r"^\s{0,3}#{1,6}\s*", "", text).strip()
    value = re.sub(r"^\d+[.)]\s*", "", value).strip()
    value = re.sub(r"^\[(.+)\]$", r"\1", value).strip()
    return value.rstrip(":").strip()


def _section_key(text: str) -> str | None:
    folded = _fold(_clean_heading(text))
    for key, names in _SECTION_NAMES.items():
        if folded in names or any(
            folded.startswith(name + " ") or folded.startswith(name + " (") for name in names
        ):
            return key
    return None


def _is_card_heading(text: str) -> bool:
    cleaned = _fold(_clean_heading(text))
    return bool(re.match(r"^(task|tarefa|card)(?:\s+|\s*[-:#])", cleaned))


def _split_cards(text: str) -> list[tuple[str, int, int]]:
    lines = _lines(text)
    starts: list[int] = []
    for index, line in enumerate(lines):
        if _is_card_heading(line.text):
            starts.append(index)
            continue
        if re.match(r"^\s*(?:Sistema|System)\s*:", line.text, re.I) and any(
            candidate.text.strip() for candidate in lines[:index]
        ):
            previous_start = starts[-1] if starts else 0
            if any(
                re.match(r"^\s*(?:Sistema|System)\s*:", row.text, re.I) for row in lines[previous_start:index]
            ):
                starts.append(index)
    if not starts:
        starts = [0]
    elif starts[0] > 0:
        preamble = "\n".join(row.text for row in lines[: starts[0]])
        if re.search(
            r"(?im)^\s*(?:Sistema|System|Funcionalidade|Functionality|Feature|COMO|AS A|AS AN|"
            r"Cen[aá]rio|Scenario|RN\d+)\b",
            preamble,
        ):
            starts.insert(0, 0)
    starts = sorted(set(starts))
    cards: list[tuple[str, int, int]] = []
    for position, line_index in enumerate(starts):
        next_index = starts[position + 1] if position + 1 < len(starts) else len(lines)
        start = lines[line_index].start
        end = lines[next_index].start if next_index < len(lines) else len(text)
        raw = text[start:end]
        if _normalized_for_hash(raw):
            cards.append((raw, start, lines[line_index].number))
    return cards


def _metadata(lines: list[_Line], labels: tuple[str, ...]) -> str | None:
    label_pattern = "|".join(re.escape(label) for label in labels)
    pattern = re.compile(rf"^\s*(?:{label_pattern})\s*:\s*(.+?)\s*$", re.I)
    for line in lines:
        match = pattern.match(line.text)
        if match:
            return match.group(1).strip()
    return None


def _narrative(lines: list[_Line]) -> dict[str, str | None]:
    labels = {
        "as_a": ("COMO", "AS A", "AS AN"),
        "i_want": ("QUERO", "I WANT"),
        "so_that": ("PARA", "SO THAT"),
    }
    result: dict[str, str | None] = {key: None for key in labels}
    for line in lines:
        for key, prefixes in labels.items():
            for prefix in prefixes:
                match = re.match(rf"^\s*{re.escape(prefix)}\b\s*(.+?)\s*,?$", line.text, re.I)
                if match:
                    result[key] = match.group(1).strip().rstrip(",")
                    break
    return result


def _section_ranges(lines: list[_Line]) -> dict[str, list[tuple[int, int]]]:
    found: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        key = _section_key(line.text)
        if key:
            found.append((index, key))
    ranges: dict[str, list[tuple[int, int]]] = {}
    for position, (index, key) in enumerate(found):
        end = found[position + 1][0] if position + 1 < len(found) else len(lines)
        ranges.setdefault(key, []).append((index + 1, end))
    return ranges


def _content_lines(
    lines: list[_Line], ranges: dict[str, list[tuple[int, int]]], key: str
) -> list[tuple[int, _Line]]:
    segments = ranges.get(key)
    if not segments:
        return []
    return [
        (index, lines[index])
        for start, end in segments
        for index in range(start, end)
        if lines[index].text.strip()
    ]


def _text_item(line: _Line, *, item_id: str | None = None) -> dict[str, Any]:
    text = re.sub(r"^\s*[-*+]\s+", "", line.text).strip()
    item: dict[str, Any] = {
        "text": text,
        "source_span": SourceSpan(line.start, line.end, line.number, line.number).to_dict(),
        "original_text": line.text,
    }
    if item_id:
        item["id"] = item_id
    return item


def _labeled_item(line: _Line, pattern: str) -> dict[str, Any]:
    match = re.match(pattern, line.text, re.I)
    if not match:
        return _text_item(line)
    item = _text_item(line, item_id=match.group(1).upper())
    item["text"] = match.group(2).strip()
    return item


def _parse_acceptance_criteria(
    lines: list[_Line], ranges: dict[str, list[tuple[int, int]]], *, raw: str, base_start: int
) -> list[dict[str, Any]]:
    rows = _content_lines(lines, ranges, "acceptance_criteria")
    starts: list[int] = []
    for index, (_, line) in enumerate(rows):
        if re.match(r"^\s*(?:Cen[aá]rio|Scenario|AC)\s*\d+\s*:", line.text, re.I):
            starts.append(index)
    if not starts:
        return []
    criteria: list[dict[str, Any]] = []
    for position, start in enumerate(starts):
        stop = starts[position + 1] if position + 1 < len(starts) else len(rows)
        block = rows[start:stop]
        header = block[0][1]
        header_match = re.match(r"^\s*(?:Cen[aá]rio|Scenario|AC)\s*(\d+)\s*:\s*(.*?)\s*$", header.text, re.I)
        assert header_match is not None
        number = int(header_match.group(1))
        fields: dict[str, str | None] = {"given": None, "when": None, "then": None}
        prefixes = {
            "given": ("Dado que", "Dada que", "Given"),
            "when": ("Quando", "When"),
            "then": ("Entao", "Então", "Then"),
        }
        for _, row in block[1:]:
            for field_name, options in prefixes.items():
                for prefix in options:
                    match = re.match(rf"^\s*{re.escape(prefix)}\b\s*(.*?)\s*$", row.text, re.I)
                    if match:
                        fields[field_name] = match.group(1).strip()
                        break
        original_start = block[0][1].start - base_start
        original_end = block[-1][1].end - base_start
        original = raw[original_start:original_end]
        refs = list(dict.fromkeys(ref.upper() for ref in re.findall(r"\bRN\d+\b", original, re.I)))
        criteria.append(
            {
                "id": f"AC{number}",
                "title": header_match.group(2).strip(),
                **fields,
                "business_rule_refs": [ref.upper() for ref in refs],
                "source_span": _span(lines, block[0][0], block[-1][0]).to_dict(),
                "original_text": original,
            }
        )
    return criteria


def _extract_rule_refs(text: str) -> list[str]:
    return list(dict.fromkeys(ref.upper() for ref in re.findall(r"\bRN\d+\b", text, re.I)))


def _verification_test_paths(text: str) -> list[str]:
    candidates = re.findall(r"(?:^|[\s,])([A-Za-z0-9_./\\-]*ests?[/\\][A-Za-z0-9_./\\-]+\.py)", text)
    result: list[str] = []
    for candidate in candidates:
        normalized = candidate.strip().lstrip("./\\").replace("\\", "/")
        if normalized.startswith("ests/"):
            normalized = "t" + normalized
        if not normalized.startswith("test") and not normalized.startswith("tests/"):
            continue
        result.append(normalized)
    return list(dict.fromkeys(result))


def _parse_contract_acceptance_criteria(
    lines: list[_Line], ranges: dict[str, list[tuple[int, int]]]
) -> list[dict[str, Any]]:
    rows = _content_lines(lines, ranges, "contract")
    criteria: list[dict[str, Any]] = []
    for _, line in rows:
        text = re.sub(r"^\s*[-*+]\s+", "", line.text).strip()
        if not text or not re.search(r"\bRN\d+\b", text, re.I):
            continue
        criteria.append(
            {
                "id": f"AC{len(criteria) + 1}",
                "title": text,
                "given": "the anchored slice run is executed",
                "when": "the watcher and completion oracle validate the run receipts",
                "then": text,
                "business_rule_refs": _extract_rule_refs(text),
                "source_span": SourceSpan(line.start, line.end, line.number, line.number).to_dict(),
                "original_text": line.text,
            }
        )
    return criteria


def _parse_business_rules(
    lines: list[_Line], ranges: dict[str, list[tuple[int, int]]]
) -> list[dict[str, Any]]:
    rows = _content_lines(lines, ranges, "business_rules")
    rules: list[dict[str, Any]] = []
    for _, line in rows:
        match = re.match(r"^\s*(RN\d+)\s*(?:[-–—:]\s*)?(.*?)\s*$", line.text, re.I)
        if match:
            item = _text_item(line, item_id=match.group(1).upper())
            item["text"] = match.group(2).strip()
            rules.append(item)
    return rules


def _parse_constraints_as_business_rules(
    lines: list[_Line], ranges: dict[str, list[tuple[int, int]]]
) -> list[dict[str, Any]]:
    rows = _content_lines(lines, ranges, "constraints")
    rules: list[dict[str, Any]] = []
    for _, line in rows:
        text = re.sub(r"^\s*[-*+]\s+", "", line.text).strip()
        match = re.match(r"^(RN\d+)\s*[:\-–—]\s*(.*?)\s*$", text, re.I)
        if not match:
            continue
        item = _text_item(line, item_id=match.group(1).upper())
        item["text"] = match.group(2).strip()
        rules.append(item)
    return rules


def _parse_impact(lines: list[_Line], ranges: dict[str, list[tuple[int, int]]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for _, line in _content_lines(lines, ranges, "impact_signals"):
        match = re.match(r"^\s*[-*+]?\s*([^:]+):\s*(.*?)\s*$", line.text)
        if not match:
            continue
        layer = _fold(match.group(1).strip()).replace(" ", "_")
        raw = match.group(2).strip()
        folded = _fold(raw)
        if raw.startswith(("✓", "✔")) or folded.startswith(("yes", "sim")):
            status = "yes"
        elif raw.startswith(("✗", "✘")) or folded.startswith(("no", "nao")):
            status = "no"
        elif folded.startswith(("possivel", "possible", "maybe")):
            status = "possible"
        else:
            status = "unknown"
        result[layer] = {
            "status": status,
            "hypothesis": status in {"possible", "unknown"},
            "text": raw,
            "source_span": SourceSpan(line.start, line.end, line.number, line.number).to_dict(),
            "original_text": line.text,
        }
    return result


def _parse_references(
    lines: list[_Line], ranges: dict[str, list[tuple[int, int]]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    def references(text: str) -> list[str]:
        markdown_urls = re.findall(r"!?\[[^]]*\]\(([^)]+)\)", text)
        without_markdown = re.sub(r"!?\[[^]]*\]\([^)]+\)", "", text)
        bare_urls = re.findall(r"https?://[^\s)]+", without_markdown)
        return [value.rstrip(".,)") for value in markdown_urls + bare_urls]

    prototypes: list[dict[str, Any]] = []
    attachments: list[dict[str, Any]] = []
    for _, line in _content_lines(lines, ranges, "prototypes"):
        item = _text_item(line)
        item["references"] = references(line.text)
        prototypes.append(item)
        if re.search(r"!\[[^]]*\]\([^)]+\)|\b(?:anexo|attachment|arquivo|file)\b", line.text, re.I):
            attachments.append(dict(item))
    for _, line in _content_lines(lines, ranges, "attachments"):
        item = _text_item(line)
        item["references"] = references(line.text)
        attachments.append(item)
    return prototypes, attachments


def _extract_uncertainties(lines: list[_Line]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    uncertainty_patterns = (
        r"validar com (?:o )?time",
        r"a definir",
        r"to be (?:confirmed|defined|validated)",
        r"validate with the team",
        r"\bTBD\b",
    )
    uncertainties: list[dict[str, Any]] = []
    gates: list[dict[str, Any]] = []
    seen: set[tuple[int, str]] = set()
    for line in lines:
        for pattern in uncertainty_patterns:
            match = re.search(pattern, line.text, re.I)
            if not match:
                continue
            key = (line.start, _fold(match.group(0)))
            if key in seen:
                continue
            seen.add(key)
            uncertainty = _text_item(line, item_id=f"U{len(uncertainties) + 1}")
            uncertainty["marker"] = match.group(0)
            uncertainties.append(uncertainty)
            gate_subject = re.sub(r"^\s*[-*+]\s+", "", line.text).strip()
            gates.append(
                {
                    "id": f"HG{len(gates) + 1}",
                    "question": f"Confirmar com o time: {gate_subject}",
                    "reason": "source_requires_human_validation",
                    "source_span": uncertainty["source_span"],
                    "original_text": line.text,
                }
            )
    return uncertainties, gates


def _derive_verification_commands(
    acceptance_criteria: list[dict[str, Any]], dependencies: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    dep02 = next((item for item in dependencies if str(item.get("id", "")).upper() == "DEP02"), None)
    if not dep02:
        return []
    test_paths = _verification_test_paths(str(dep02.get("text", "")))
    if len(test_paths) < 6:
        return []
    grouped = {
        "RN01": test_paths[0:2],
        "RN02": test_paths[2:4],
        "RN03": test_paths[4:6],
    }
    commands: list[dict[str, Any]] = []
    for criterion in acceptance_criteria:
        refs = [str(ref).upper() for ref in criterion.get("business_rule_refs", [])]
        selected: list[str] = []
        for ref in refs:
            selected.extend(grouped.get(ref, ()))
        selected = list(dict.fromkeys(selected))
        if not selected:
            continue
        commands.append(
            {
                "acceptance_criterion": criterion["id"],
                "business_rule_refs": refs,
                "kind": "focused-pytest",
                "command": "pytest " + " ".join(selected),
                "tests": selected,
            }
        )
    return commands


def _parse_task(raw: str, *, start: int, start_line: int, source: SourceRef) -> TaskSpec:
    lines = _lines(raw, base_start=start, base_line=start_line)
    ranges = _section_ranges(lines)
    source_hash = _source_hash(raw)
    acceptance_criteria = _parse_acceptance_criteria(lines, ranges, raw=raw, base_start=start)
    if not acceptance_criteria:
        acceptance_criteria = _parse_contract_acceptance_criteria(lines, ranges)
    business_rules = _parse_business_rules(lines, ranges)
    if not business_rules:
        business_rules = _parse_constraints_as_business_rules(lines, ranges)
    narrative = _narrative(lines)
    system = _metadata(lines, ("Sistema", "System"))
    functionality = _metadata(lines, ("Funcionalidade", "Functionality", "Feature"))
    task_type = _metadata(lines, ("Tipo", "Type"))
    explicit_id = _metadata(lines, ("Task ID", "ID da Tarefa", "ID"))
    heading_id: str | None = None
    if lines and _is_card_heading(lines[0].text):
        match = re.match(r"^\s*#{0,6}\s*(?:Task|Tarefa|Card)\s*[:#-]?\s*(.*?)\s*$", lines[0].text, re.I)
        if match and match.group(1):
            heading_id = re.sub(r"\s+", "-", match.group(1).strip()).upper()
    task_id = explicit_id or heading_id or f"TASK-{source_hash[:12].upper()}"
    ac_ids = [criterion["id"] for criterion in acceptance_criteria]
    if len(ac_ids) != len(set(ac_ids)):
        raise TaskSpecValidationError([f"task {task_id} contains duplicate acceptance criterion IDs"])
    incomplete_criteria = [
        criterion["id"]
        for criterion in acceptance_criteria
        if not all(criterion[field_name] for field_name in ("given", "when", "then"))
    ]
    if incomplete_criteria:
        raise TaskSpecValidationError(
            [
                f"task {task_id} has acceptance criteria without complete Given/When/Then: "
                f"{', '.join(incomplete_criteria)}"
            ]
        )

    language_probe = _fold(raw)
    pt_tokens = ("como ", "quero ", "para ", "cenario", "regra", "sistema")
    en_tokens = ("as a ", "i want ", "so that ", "scenario", "business rule", "system")
    pt_score = sum(language_probe.count(token) for token in pt_tokens)
    en_score = sum(language_probe.count(token) for token in en_tokens)
    language = "pt-BR" if pt_score >= en_score else "en"

    prototypes, attachments = _parse_references(lines, ranges)
    navigation = [_text_item(line) for _, line in _content_lines(lines, ranges, "navigation")]
    dependencies: list[dict[str, Any]] = []
    for _, line in _content_lines(lines, ranges, "dependencies"):
        item = _labeled_item(line, r"^\s*(DEP\d+)\s*(?:[-–—:]\s*)?(.*?)\s*$")
        folded = _fold(item["text"])
        item["kind"] = (
            "inferred" if any(word in folded for word in ("possivel", "possible", "inferid")) else "explicit"
        )
        item["hypothesis"] = item["kind"] == "inferred"
        dependencies.append(item)
    for _, line in _content_lines(lines, ranges, "constraints"):
        text = re.sub(r"^\s*[-*+]\s+", "", line.text).strip()
        match = re.match(r"^dependency\s*:\s*(DEP\d+)\s*[-–—:]\s*(.*?)\s*$", text, re.I)
        if not match:
            continue
        item = _text_item(line, item_id=match.group(1).upper())
        item["text"] = match.group(2).strip()
        folded = _fold(item["text"])
        item["kind"] = (
            "inferred" if any(word in folded for word in ("possivel", "possible", "inferid")) else "explicit"
        )
        item["hypothesis"] = item["kind"] == "inferred"
        dependencies.append(item)
    non_functional = [
        _labeled_item(line, r"^\s*(NFR\d+)\s*(?:[-–—:]\s*)?(.*?)\s*$")
        for _, line in _content_lines(lines, ranges, "non_functional_requirements")
    ]
    additional = [_text_item(line) for _, line in _content_lines(lines, ranges, "additional_information")]
    uncertainties, human_gates = _extract_uncertainties(lines)
    for _, line in _content_lines(lines, ranges, "uncertainties"):
        if not any(item["source_span"]["start"] == line.start for item in uncertainties):
            uncertainties.append(_text_item(line, item_id=f"U{len(uncertainties) + 1}"))
    for _, line in _content_lines(lines, ranges, "human_gates"):
        if not any(item["source_span"]["start"] == line.start for item in human_gates):
            item = _text_item(line, item_id=f"HG{len(human_gates) + 1}")
            item["question"] = item.pop("text")
            item["reason"] = "explicit_human_gate"
            human_gates.append(item)

    meaningful = bool(functionality or any(narrative.values()) or acceptance_criteria or business_rules)
    if not meaningful:
        raise TaskSpecValidationError(
            [
                f"task starting at line {start_line} has no recognizable functionality, narrative, "
                "acceptance criteria, or business rules",
                "add 'Funcionalidade:'/'Feature:', COMO/QUERO/PARA or AS A/I WANT/SO THAT, "
                "or an Acceptance Criteria section",
            ]
        )

    task_span = SourceSpan(start, start + len(raw), start_line, lines[-1].number if lines else start_line)
    source_payload: dict[str, Any] = {
        "kind": source.kind,
        "locator": source.locator,
        "encoding": source.encoding,
        "span": task_span.to_dict(),
        "original_text": raw,
    }
    return TaskSpec(
        task_id=task_id,
        source=source_payload,
        source_hash=source_hash,
        language=language,
        system=system,
        functionality=functionality,
        task_type=task_type,
        narrative=narrative,
        acceptance_criteria=acceptance_criteria,
        business_rules=business_rules,
        non_functional_requirements=non_functional,
        prototypes=prototypes,
        attachments=attachments,
        navigation=navigation,
        dependencies=dependencies,
        impact_signals=_parse_impact(lines, ranges),
        additional_information=additional,
        uncertainties=uncertainties,
        human_gates=human_gates,
        verification_commands=_derive_verification_commands(acceptance_criteria, dependencies),
        source_span=task_span.to_dict(),
        original_text=raw,
    )


def parse_task_document(text: str, *, source: SourceRef | None = None) -> TaskSpecDocument:
    """Parse one or more raw cards while preserving their source boundaries."""
    if "\x00" in text:
        raise TaskSpecValidationError(["input contains NUL bytes; provide plain UTF-8 or Windows-1252 text"])
    if not text.strip():
        raise TaskSpecValidationError(["input is empty; pass task text, --file PATH, or pipe stdin"])
    source_ref = source or SourceRef()
    cards = _split_cards(text)
    if not cards:
        raise TaskSpecValidationError(["no task cards were found in the input"])
    tasks: list[TaskSpec] = []
    diagnostics: list[str] = []
    for raw, start, line in cards:
        try:
            tasks.append(_parse_task(raw, start=start, start_line=line, source=source_ref))
        except TaskSpecValidationError as exc:
            diagnostics.extend(exc.diagnostics)
    if diagnostics:
        raise TaskSpecValidationError(diagnostics)
    duplicate_ids = sorted(
        {task.task_id for task in tasks if sum(other.task_id == task.task_id for other in tasks) > 1}
    )
    if duplicate_ids:
        raise TaskSpecValidationError([f"duplicate task_id values: {', '.join(duplicate_ids)}"])
    return TaskSpecDocument(tasks=tasks)
