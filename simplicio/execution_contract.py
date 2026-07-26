"""Compile a rich task specification into an immutable execution contract.

The compiler is intentionally pure: it does not discover files, invoke an LLM, run
tests, or edit a repository.  Its job is to freeze source intent, preserve
AC/RN/NFR provenance, expose undecided behaviour as human gates, and provide the
traceability surface consumed by later planner/executor stages.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, is_dataclass, replace
from hashlib import sha256
from typing import Any

SCHEMA = "simplicio.execution-contract/v1"
TASK_SPEC_SCHEMA = "simplicio.task-spec/v2"
CLAIM_UNVERIFIED = "UNVERIFIED"
CLAIM_MEASURED = "MEASURED"

_VERIFICATION_KINDS = frozenset({"unit", "integration", "e2e", "visual"})
_PLACEHOLDER_CRITERIA = {
    "- true state\n- false state",
    "true state\nfalse state",
    "- true\n- false",
    "make it work",
    "todo",
    "tbd",
}
_PLACEHOLDER_TEST_PARTS = (
    "configure simplicio_test_cmd",
    "echo test",
    "echo todo",
    "replace-with-test",
    "<test_command>",
)


def _source_digest(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    return sha256(normalized.encode()).hexdigest()


def _canonical_task_spec_hash(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()


class ContractCompilationError(ValueError):
    """Raised when input cannot produce a trustworthy contract."""

    def __init__(self, errors: Sequence[str]) -> None:
        self.errors = tuple(errors)
        super().__init__("execution contract compilation failed:\n  - " + "\n  - ".join(self.errors))


class ExecutionBlockedError(RuntimeError):
    """Raised when an execution attempt crosses an unresolved blocking gate."""

    def __init__(self, gate_ids: Sequence[str]) -> None:
        self.gate_ids = tuple(gate_ids)
        super().__init__("execution blocked by human gate(s): " + ", ".join(self.gate_ids))


class SourceDriftError(RuntimeError):
    """Raised when frozen source text changed and the contract needs re-anchoring."""


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        ordered = sorted(value.items(), key=lambda pair: str(pair[0]))
        return tuple((str(key), _freeze(item)) for key, item in ordered)
    if isinstance(value, list | tuple):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, tuple):
        if all(isinstance(item, tuple) and len(item) == 2 and isinstance(item[0], str) for item in value):
            return {item[0]: _thaw(item[1]) for item in value}
        return [_thaw(item) for item in value]
    return value


@dataclass(frozen=True)
class SourceSpan:
    data: tuple[tuple[str, Any], ...]

    @classmethod
    def from_value(cls, value: Any) -> SourceSpan | None:
        if value is None:
            return None
        if isinstance(value, Mapping):
            return cls(_freeze(value))
        return cls((("value", _freeze(value)),))

    def to_dict(self) -> dict[str, Any]:
        return _thaw(self.data)


@dataclass(frozen=True)
class SourceReference:
    kind: str
    locator: str
    span: SourceSpan | None
    original_text: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "locator": self.locator,
            "span": self.span.to_dict() if self.span else None,
            "original_text": self.original_text,
        }


@dataclass(frozen=True)
class VerificationIntent:
    id: str
    kind: str
    positive: str
    negative: str
    edge: str
    executor: str = "verification-worker"

    @property
    def is_executable(self) -> bool:
        return self.kind in _VERIFICATION_KINDS and bool(
            self.executor and self.positive and self.negative and self.edge
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "executor": self.executor,
            "positive": self.positive,
            "negative": self.negative,
            "edge": self.edge,
            "is_executable": self.is_executable,
        }


@dataclass(frozen=True)
class AcceptanceCriterion:
    id: str
    title: str
    given: str
    when: str
    then: str
    business_rule_refs: tuple[str, ...]
    source_span: SourceSpan | None
    original_text: str
    verification_intents: tuple[VerificationIntent, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "given": self.given,
            "when": self.when,
            "then": self.then,
            "business_rule_refs": list(self.business_rule_refs),
            "source_span": self.source_span.to_dict() if self.source_span else None,
            "original_text": self.original_text,
            "verification_intents": [intent.to_dict() for intent in self.verification_intents],
        }


@dataclass(frozen=True)
class Requirement:
    id: str
    kind: str
    text: str
    source_span: SourceSpan | None
    original_text: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "text": self.text,
            "source_span": self.source_span.to_dict() if self.source_span else None,
            "original_text": self.original_text,
        }


@dataclass(frozen=True)
class HumanGate:
    id: str
    question: str
    reason: str
    blocking: bool = True
    status: str = "open"
    source_span: SourceSpan | None = None

    @property
    def unresolved(self) -> bool:
        return self.blocking and self.status.lower() not in {"closed", "resolved", "approved"}

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "question": self.question,
            "reason": self.reason,
            "blocking": self.blocking,
            "status": self.status,
            "source_span": self.source_span.to_dict() if self.source_span else None,
        }


@dataclass(frozen=True)
class Hypothesis:
    subject: str
    statement: str
    status: str = CLAIM_UNVERIFIED

    def to_dict(self) -> dict[str, str]:
        return {"subject": self.subject, "statement": self.statement, "status": self.status}


@dataclass(frozen=True)
class EvidenceReceipt:
    id: str
    kind: str
    uri: str
    digest: str

    def __post_init__(self) -> None:
        if not all((self.id.strip(), self.kind.strip(), self.uri.strip(), self.digest.strip())):
            raise ValueError("evidence receipts require id, kind, uri, and digest")

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id, "kind": self.kind, "uri": self.uri, "digest": self.digest}


@dataclass(frozen=True)
class TraceabilityRow:
    acceptance_criterion: str
    business_rules: tuple[str, ...]
    verification_intents: tuple[str, ...]
    files: tuple[str, ...] = ()
    tests: tuple[str, ...] = ()
    evidence: tuple[EvidenceReceipt, ...] = ()
    status: str = CLAIM_UNVERIFIED

    def to_dict(self) -> dict[str, Any]:
        return {
            "acceptance_criterion": self.acceptance_criterion,
            "business_rules": list(self.business_rules),
            "verification_intents": list(self.verification_intents),
            "files": list(self.files),
            "tests": list(self.tests),
            "evidence": [receipt.to_dict() for receipt in self.evidence],
            "status": self.status,
        }


@dataclass(frozen=True)
class ExecutionContract:
    schema: str
    contract_id: str
    task_id: str
    source: SourceReference
    source_hash: str
    language: str
    system: str
    functionality: str
    task_type: str
    # Canonical JSON is the immutable lossless boundary.  Using the generic
    # tuple freezer here would collapse [] and {} into the same value.
    task_spec: str
    task_spec_hash: str
    narrative: tuple[tuple[str, Any], ...]
    acceptance_criteria: tuple[AcceptanceCriterion, ...]
    business_rules: tuple[Requirement, ...]
    non_functional_requirements: tuple[Requirement, ...]
    hypotheses: tuple[Hypothesis, ...]
    human_gates: tuple[HumanGate, ...]
    traceability_matrix: tuple[TraceabilityRow, ...]

    @property
    def execution_ready(self) -> bool:
        return not any(gate.unresolved for gate in self.human_gates) and all(
            intent.is_executable
            for criterion in self.acceptance_criteria
            for intent in criterion.verification_intents
        )

    @property
    def contract_hash(self) -> str:
        payload = self.to_dict(include_contract_hash=False)
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return sha256(canonical.encode()).hexdigest()

    def assert_executable(self) -> None:
        blocking = [gate.id for gate in self.human_gates if gate.unresolved]
        if blocking:
            raise ExecutionBlockedError(blocking)
        invalid = [
            intent.id
            for criterion in self.acceptance_criteria
            for intent in criterion.verification_intents
            if not intent.is_executable
        ]
        if invalid:
            raise ContractCompilationError(["non-executable verification intent(s): " + ", ".join(invalid)])

    def source_matches(self, current_text: str) -> bool:
        return _source_digest(current_text) == self.source_hash

    def assert_source_current(self, current_text: str) -> None:
        if not self.source_matches(current_text):
            raise SourceDriftError(
                f"source changed for {self.task_id}; frozen={self.source_hash[:12]}, "
                f"current={_source_digest(current_text)[:12]}; re-anchor required"
            )

    def claim_status(self, acceptance_criterion_id: str) -> str:
        for row in self.traceability_matrix:
            if row.acceptance_criterion == acceptance_criterion_id:
                return row.status
        raise KeyError(acceptance_criterion_id)

    def with_receipt(
        self,
        acceptance_criterion_id: str,
        receipt: EvidenceReceipt,
        *,
        files: Sequence[str] = (),
        tests: Sequence[str] = (),
    ) -> ExecutionContract:
        found = False
        rows: list[TraceabilityRow] = []
        for row in self.traceability_matrix:
            if row.acceptance_criterion != acceptance_criterion_id:
                rows.append(row)
                continue
            found = True
            rows.append(
                replace(
                    row,
                    files=tuple(dict.fromkeys((*row.files, *files))),
                    tests=tuple(dict.fromkeys((*row.tests, *tests))),
                    evidence=(*row.evidence, receipt),
                    status=CLAIM_MEASURED,
                )
            )
        if not found:
            raise KeyError(acceptance_criterion_id)
        return replace(self, traceability_matrix=tuple(rows))

    def to_dict(self, *, include_contract_hash: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema": self.schema,
            "contract_id": self.contract_id,
            "task_id": self.task_id,
            "source": self.source.to_dict(),
            "source_hash": self.source_hash,
            "language": self.language,
            "system": self.system,
            "functionality": self.functionality,
            "task_type": self.task_type,
            "task_spec": json.loads(self.task_spec),
            "task_spec_hash": self.task_spec_hash,
            "narrative": _thaw(self.narrative),
            "acceptance_criteria": [item.to_dict() for item in self.acceptance_criteria],
            "business_rules": [item.to_dict() for item in self.business_rules],
            "non_functional_requirements": [item.to_dict() for item in self.non_functional_requirements],
            "hypotheses": [item.to_dict() for item in self.hypotheses],
            "human_gates": [item.to_dict() for item in self.human_gates],
            "execution_ready": self.execution_ready,
            "traceability_matrix": [row.to_dict() for row in self.traceability_matrix],
        }
        if include_contract_hash:
            payload["contract_hash"] = self.contract_hash
        return payload


def _as_mapping(value: Any, path: str = "task_spec") -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        payload = to_dict()
        if isinstance(payload, Mapping):
            return dict(payload)
    if is_dataclass(value) and not isinstance(value, type):
        payload = asdict(value)
        if isinstance(payload, dict):
            return payload
    raise ContractCompilationError([f"{path} must be a mapping, dataclass, or expose to_dict()"])


def _items(value: Any) -> list[Any]:
    if isinstance(value, list | tuple):
        return list(value)
    if value is None:
        return []
    return [value]


def _text(value: Any, *keys: str) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, Mapping):
        for key in keys:
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
    return ""


def _stable_id(prefix: str, text: str, position: int) -> str:
    material = text.strip() or str(position)
    return f"{prefix}-{sha256(material.encode()).hexdigest()[:10]}"


def _normalize_identifier(value: Any, prefix: str, text: str, position: int) -> str:
    raw = str(value or "").strip().upper().replace(" ", "")
    if raw:
        return raw
    return _stable_id(prefix, text, position)


def _verification_kinds(task: Mapping[str, Any]) -> tuple[str, ...]:
    kinds = ["unit", "integration"]
    impacts = task.get("impact_signals")
    frontend = impacts.get("frontend") if isinstance(impacts, Mapping) else None
    if frontend or task.get("navigation"):
        kinds.append("e2e")
    if task.get("prototypes") or task.get("attachments"):
        kinds.append("visual")
    return tuple(kinds)


def _make_intents(
    ac_id: str, title: str, then: str, task: Mapping[str, Any]
) -> tuple[VerificationIntent, ...]:
    expected = then or title
    return tuple(
        VerificationIntent(
            id=f"VI-{ac_id}-{kind.upper()}",
            kind=kind,
            positive=f"prove expected outcome: {expected}",
            negative=f"prove the outcome is not reported when its preconditions are false: {expected}",
            edge=f"exercise equal, empty, duplicate, missing, or invalid boundary values for: {title}",
        )
        for kind in _verification_kinds(task)
    )


def _compile_acceptance_criteria(
    task: Mapping[str, Any], gates: list[HumanGate]
) -> tuple[AcceptanceCriterion, ...]:
    criteria: list[AcceptanceCriterion] = []
    seen: dict[str, str] = {}
    for position, raw in enumerate(_items(task.get("acceptance_criteria")), 1):
        item = _as_mapping(raw, f"acceptance_criteria[{position - 1}]")
        title = _text(item, "title", "text", "original_text")
        given = _text(item, "given")
        when = _text(item, "when")
        then = _text(item, "then", "expected")
        identifier = _normalize_identifier(item.get("id"), "AC", title + then, position)
        canonical = "|".join((title, given, when, then))
        if identifier in seen and seen[identifier] != canonical:
            gates.append(
                HumanGate(
                    id=f"contradiction-{identifier.lower()}",
                    question=f"Which definition of {identifier} is authoritative?",
                    reason="the same acceptance-criterion ID has conflicting text",
                )
            )
            continue
        if identifier in seen:
            continue
        seen[identifier] = canonical
        refs = tuple(
            dict.fromkeys(
                str(ref).strip().upper()
                for ref in _items(item.get("business_rule_refs") or item.get("rule_refs"))
                if str(ref).strip()
            )
        )
        original = _text(item, "original_text") or canonical
        criteria.append(
            AcceptanceCriterion(
                id=identifier,
                title=title or identifier,
                given=given,
                when=when,
                then=then,
                business_rule_refs=refs,
                source_span=SourceSpan.from_value(item.get("source_span")),
                original_text=original,
                verification_intents=_make_intents(identifier, title or identifier, then, task),
            )
        )
    if not criteria:
        gates.append(
            HumanGate(
                id="missing-acceptance-criteria",
                question="What observable outcomes define completion?",
                reason="the task has no acceptance criteria",
            )
        )
    return tuple(criteria)


def _compile_requirements(
    raw_items: Any, kind: str, prefix: str, gates: list[HumanGate]
) -> tuple[Requirement, ...]:
    requirements: list[Requirement] = []
    seen: dict[str, str] = {}
    for position, raw in enumerate(_items(raw_items), 1):
        item = {"text": raw} if isinstance(raw, str) else _as_mapping(raw, f"{kind}[{position - 1}]")
        text = _text(item, "text", "description", "original_text")
        identifier = _normalize_identifier(item.get("id"), prefix, text, position)
        if identifier in seen and seen[identifier] != text:
            gates.append(
                HumanGate(
                    id=f"contradiction-{identifier.lower()}",
                    question=f"Which definition of {identifier} is authoritative?",
                    reason=f"the same {kind} ID has conflicting text",
                )
            )
            continue
        if identifier in seen:
            continue
        seen[identifier] = text
        requirements.append(
            Requirement(
                id=identifier,
                kind=kind,
                text=text,
                source_span=SourceSpan.from_value(item.get("source_span")),
                original_text=_text(item, "original_text") or text,
            )
        )
    return tuple(requirements)


def _slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", normalized).strip("-") or "gate"


def _append_gate(gates: list[HumanGate], gate: HumanGate) -> None:
    if all(existing.id != gate.id for existing in gates):
        gates.append(gate)


def _source_coverage_gates(
    original_text: str,
    acceptance_criteria: tuple[AcceptanceCriterion, ...],
    business_rules: tuple[Requirement, ...],
    gates: list[HumanGate],
) -> None:
    scenario_ids = {
        f"AC{match}" for match in re.findall(r"(?im)^\s*(?:cen[aá]rio|scenario)\s*(\d+)\s*:", original_text)
    }
    declared_rule_ids = set(re.findall(r"(?im)^\s*((?:RN|BR)\d{1,4})\s*[\-–—]", original_text))
    actual_ac_ids = {item.id for item in acceptance_criteria}
    actual_rule_ids = {item.id for item in business_rules}
    for missing in sorted(scenario_ids - actual_ac_ids):
        _append_gate(
            gates,
            HumanGate(
                id=f"source-coverage-{missing.lower()}",
                question=f"Restore or explicitly remove {missing} from the frozen source.",
                reason="a source scenario is missing from the structured contract",
            ),
        )
    for missing in sorted(declared_rule_ids - actual_rule_ids):
        _append_gate(
            gates,
            HumanGate(
                id=f"source-coverage-{missing.lower()}",
                question=f"Restore or explicitly remove {missing} from the frozen source.",
                reason="a declared business rule is missing from the structured contract",
            ),
        )


def _semantic_gates(
    original_text: str,
    nfrs: tuple[Requirement, ...],
    task: Mapping[str, Any],
    gates: list[HumanGate],
    hypotheses: list[Hypothesis],
) -> None:
    plain = unicodedata.normalize("NFKD", original_text).encode("ascii", "ignore").decode().lower()
    if (
        "orden" in plain
        and ("data" in plain or "date" in plain)
        and not re.search(r"empat|tie.break|same date|equal date|mesma data", plain)
    ):
        _append_gate(
            gates,
            HumanGate(
                id="decision-date-tie",
                question="What is the deterministic tie-breaker when start dates are equal?",
                reason="date ordering does not specify equal-date behaviour",
            ),
        )
    if (
        "orden" in plain
        and ("data" in plain or "date" in plain)
        and not re.search(r"data (?:ausente|invalida|nula)|missing date|invalid date|null date", plain)
    ):
        _append_gate(
            gates,
            HumanGate(
                id="decision-date-missing-invalid",
                question="Where do missing or invalid start dates sort, and should invalid data fail?",
                reason="date ordering does not define missing/invalid values",
            ),
        )
    if ("alfabet" in plain or "alphabet" in plain) and not re.search(
        r"acent|case|maiusc|minusc|locale|collat", plain
    ):
        _append_gate(
            gates,
            HumanGate(
                id="decision-alphabetical-collation",
                question="Which locale/collation and accent/case rules define alphabetical order?",
                reason="alphabetical ordering is not deterministic without collation semantics",
            ),
        )
    if (
        "estrutural" in plain
        and "unic" in plain
        and not re.search(r"mais de uma estrutural|multiple structural|duplicate structural", plain)
    ):
        _append_gate(
            gates,
            HumanGate(
                id="decision-multiple-structural",
                question="Should more than one structural line fail validation or use a tie-breaker?",
                reason="uniqueness is stated but violation behaviour is unspecified",
            ),
        )
    if any("validar" in item.text.lower() or "validate" in item.text.lower() for item in nfrs):
        _append_gate(
            gates,
            HumanGate(
                id="nfr-validation-required",
                question="Which non-functional requirements must the team approve?",
                reason="the source explicitly says NFRs still require team validation",
            ),
        )
    impacts = task.get("impact_signals")
    if isinstance(impacts, Mapping):
        backend = impacts.get("backend")
        if isinstance(backend, Mapping):
            status = str(backend.get("status", "")).lower()
            statement = _text(backend, "text", "description") or "backend impact is possible"
            if status in {"possible", "possivel", "unknown", "tbd"} or bool(backend.get("hypothesis")):
                hypotheses.append(Hypothesis(subject="impact.backend", statement=statement))
                _append_gate(
                    gates,
                    HumanGate(
                        id="impact-backend-undecided",
                        question="Is backend work required, or is frontend ordering authoritative?",
                        reason="backend impact is explicitly marked possible/undecided",
                    ),
                )


def _input_gates(task: Mapping[str, Any], gates: list[HumanGate]) -> None:
    for position, raw in enumerate(_items(task.get("human_gates")), 1):
        item = {"question": raw} if isinstance(raw, str) else _as_mapping(raw, f"human_gates[{position - 1}]")
        question = _text(item, "question", "text", "description")
        identifier = str(item.get("id") or f"source-gate-{_slug(question)}")
        _append_gate(
            gates,
            HumanGate(
                id=identifier,
                question=question or "Resolve source human gate",
                reason=_text(item, "reason") or "declared by the task source",
                blocking=bool(item.get("blocking", True)),
                status=str(item.get("status", "open")),
                source_span=SourceSpan.from_value(item.get("source_span")),
            ),
        )
    for position, raw in enumerate(_items(task.get("uncertainties")), 1):
        item = {"text": raw} if isinstance(raw, str) else _as_mapping(raw, f"uncertainties[{position - 1}]")
        statement = _text(item, "text", "question", "description")
        _append_gate(
            gates,
            HumanGate(
                id=str(item.get("id") or f"uncertainty-{_slug(statement)}"),
                question=statement or f"Resolve uncertainty {position}",
                reason="uncertainty cannot be promoted to fact without a receipt",
                blocking=bool(item.get("blocking", True)),
                source_span=SourceSpan.from_value(item.get("source_span")),
            ),
        )


def _missing_field_gates(task: Mapping[str, Any], gates: list[HumanGate]) -> None:
    for field_name in ("system", "functionality", "task_type"):
        if not _text(task, field_name):
            _append_gate(
                gates,
                HumanGate(
                    id=f"missing-field-{field_name.replace('_', '-')}",
                    question=f"What is the task {field_name.replace('_', ' ')}?",
                    reason=f"TaskSpec field {field_name!r} is absent",
                ),
            )
    narrative = task.get("narrative")
    narrative_map = narrative if isinstance(narrative, Mapping) else {}
    for field_name in ("as_a", "i_want", "so_that"):
        if not _text(narrative_map, field_name):
            _append_gate(
                gates,
                HumanGate(
                    id=f"missing-field-narrative-{field_name.replace('_', '-')}",
                    question=f"Complete narrative field {field_name!r}.",
                    reason="the task narrative is incomplete",
                ),
            )


def _placeholder_errors(task: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    criteria = str(task.get("criteria", "")).strip().lower().replace("\r\n", "\n")
    if criteria in _PLACEHOLDER_CRITERIA:
        errors.append("placeholder criteria are forbidden in real execution")
    commands: list[str] = []
    for key in ("test_command", "verify"):
        if task.get(key) is not None:
            commands.append(str(task[key]).strip().lower())
    if any(part in command for command in commands for part in _PLACEHOLDER_TEST_PARTS):
        errors.append("placeholder test command is forbidden in real execution")
    return errors


def compile_execution_contract(task_spec: Any, *, execution_mode: bool = False) -> ExecutionContract:
    """Compile one TaskSpec/dict into a frozen, JSON-serializable contract."""

    task = _as_mapping(task_spec)
    if "tasks" in task:
        tasks = _items(task.get("tasks"))
        if len(tasks) != 1:
            raise ContractCompilationError(
                ["document contains multiple tasks; use compile_execution_contracts()"]
            )
        task = _as_mapping(tasks[0], "tasks[0]")
    schema = task.get("schema")
    if schema not in {None, TASK_SPEC_SCHEMA}:
        raise ContractCompilationError([f"unsupported TaskSpec schema: {schema!r}"])
    placeholder_errors = _placeholder_errors(task)
    if execution_mode and placeholder_errors:
        raise ContractCompilationError(placeholder_errors)

    source_raw = task.get("source")
    source_map = dict(source_raw) if isinstance(source_raw, Mapping) else {}
    source_text = source_map.get("original_text") or source_map.get("text")
    task_text = task.get("original_text")
    original_text = (
        source_text
        if isinstance(source_text, str) and source_text
        else task_text
        if isinstance(task_text, str) and task_text
        else json.dumps(task, ensure_ascii=False, sort_keys=True, default=str)
    )
    computed_source_hash = _source_digest(original_text)
    source_hash = str(task.get("source_hash") or computed_source_hash)
    errors: list[str] = []
    if not re.fullmatch(r"[0-9a-fA-F]{64}", source_hash):
        errors.append("source_hash must be a 64-character SHA-256 hex digest")
    elif source_hash.lower() != computed_source_hash:
        errors.append("source_hash does not match source.original_text; re-anchor required")
    if errors:
        raise ContractCompilationError(errors)

    # Keep the complete typed boundary alongside the normalized execution
    # projection.  Older callers may provide a mapping without ``schema``;
    # normalize that one additive field without changing the caller's object.
    task_spec_payload = dict(task)
    task_spec_payload.setdefault("schema", TASK_SPEC_SCHEMA)
    task_spec_json = json.dumps(task_spec_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    task_spec_hash = _canonical_task_spec_hash(task_spec_payload)

    gates: list[HumanGate] = []
    hypotheses: list[Hypothesis] = []
    _input_gates(task, gates)
    _missing_field_gates(task, gates)
    criteria = _compile_acceptance_criteria(task, gates)
    rules = _compile_requirements(task.get("business_rules"), "business_rule", "RN", gates)
    nfrs = _compile_requirements(
        task.get("non_functional_requirements"), "non_functional_requirement", "NFR", gates
    )
    known_rules = {rule.id for rule in rules}
    for criterion in criteria:
        for missing in set(criterion.business_rule_refs) - known_rules:
            _append_gate(
                gates,
                HumanGate(
                    id=f"source-coverage-{missing.lower()}",
                    question=f"Define referenced business rule {missing} or remove the reference.",
                    reason=f"{criterion.id} references an absent business rule",
                ),
            )
    _source_coverage_gates(original_text, criteria, rules, gates)
    _semantic_gates(original_text, nfrs, task, gates, hypotheses)

    matrix = tuple(
        TraceabilityRow(
            acceptance_criterion=criterion.id,
            business_rules=criterion.business_rule_refs,
            verification_intents=tuple(intent.id for intent in criterion.verification_intents),
        )
        for criterion in criteria
    )
    task_id = str(task.get("task_id") or _stable_id("TASK", original_text, 1))
    contract = ExecutionContract(
        schema=SCHEMA,
        contract_id=f"EC-{source_hash[:16]}",
        task_id=task_id,
        source=SourceReference(
            kind=str(source_map.get("kind", "unknown")),
            locator=str(source_map.get("locator", "inline")),
            span=SourceSpan.from_value(source_map.get("span") or task.get("source_span")),
            original_text=original_text,
        ),
        source_hash=source_hash.lower(),
        language=str(task.get("language", "unknown")),
        system=str(task.get("system") or ""),
        functionality=str(task.get("functionality") or ""),
        task_type=str(task.get("task_type") or ""),
        task_spec=task_spec_json,
        task_spec_hash=task_spec_hash,
        narrative=_freeze(task.get("narrative") or {}),
        acceptance_criteria=criteria,
        business_rules=rules,
        non_functional_requirements=nfrs,
        hypotheses=tuple(hypotheses),
        human_gates=tuple(gates),
        traceability_matrix=matrix,
    )
    if execution_mode:
        contract.assert_executable()
    return contract


def compile_execution_contracts(
    task_document: Any, *, execution_mode: bool = False
) -> tuple[ExecutionContract, ...]:
    """Compile every task in a TaskSpecDocument while preserving source order."""

    document = _as_mapping(task_document, "task_document")
    raw_tasks = _items(document.get("tasks")) if "tasks" in document else [document]
    if not raw_tasks:
        raise ContractCompilationError(["task document contains no tasks"])
    return tuple(compile_execution_contract(raw, execution_mode=execution_mode) for raw in raw_tasks)


__all__ = [
    "AcceptanceCriterion",
    "ContractCompilationError",
    "EvidenceReceipt",
    "ExecutionBlockedError",
    "ExecutionContract",
    "HumanGate",
    "Hypothesis",
    "Requirement",
    "SCHEMA",
    "SourceDriftError",
    "TraceabilityRow",
    "VerificationIntent",
    "compile_execution_contract",
    "compile_execution_contracts",
]
