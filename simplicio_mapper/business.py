"""Business rules and domain glossary extraction (Flow Documentation Engine F3).

Extracts *observable* signals only — validation, state machines, permission
gates, limits/quotas, and side-effects — each with ``path:line`` evidence.
Never infers semantic intent ("why" a rule exists); that stays human/agent
work on top of this artifact. Precision is favored over recall: a handful
of high-confidence rules beats a hundred speculative ones (see
``.specs/product/flow-documentation-spec.md`` F3).

Emits ``simplicio.business-rules/v1`` as documented in
``SIMPLICIO_INTEGRATION.md``.
"""

from __future__ import annotations

import os
import re

from .diagrams import render_state_diagram, to_markdown_block
from .flows import build_flow_inventory
from .mapper import _token_words

BUSINESS_RULES_SCHEMA = "simplicio.business-rules/v1"
BUSINESS_RULES_VERSION = 1

_TEXT_EXTS = {".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".java", ".cs", ".rb"}

_LIMIT_NAME = re.compile(r"\b([A-Z][A-Z0-9_]*(?:_MAX|_MIN|_LIMIT|_QUOTA|_TIMEOUT|_TTL)|MAX_[A-Z0-9_]+|MIN_[A-Z0-9_]+)\b")
_COMPARISON = re.compile(r"[<>]=?|==")

_PERMISSION_PATTERNS = [
    re.compile(r"@\w*(login_required|requires_role|requires_auth|permission_required|staff_member_required)\w*", re.I),
    re.compile(r"\b(has_permission|require_role|check_permission|is_authenticated|require_auth)\s*\("),
]

_VALIDATION_PATTERNS = [
    re.compile(r"class\s+\w+\(\s*(BaseModel|BaseSettings)\s*\)"),
    re.compile(r"@(validator|field_validator|root_validator)\b"),
    re.compile(r"\bz\.object\s*\("),
    re.compile(r"\bJoi\.object\s*\("),
]

_SIDE_EFFECT_PATTERNS = [
    (re.compile(r"\b(send_mail|send_email|sendMail|sendEmail)\s*\("), "notification"),
    (re.compile(r"\b(notify|send_notification|sendNotification)\s*\("), "notification"),
    (re.compile(r"\b(audit_log|auditLog|log_event|logEvent|track_event|trackEvent)\s*\("), "audit"),
    (re.compile(r"\b(charge|create_charge|process_payment|processPayment|create_refund)\s*\("), "billing"),
]

_INVARIANT_PATTERN = re.compile(r"\b(?:assert\s+[^,]+,\s*['\"]([^'\"]+)['\"]|raise\s+\w*Error\(\s*['\"]([^'\"]+)['\"])")

_ENUM_CLASS = re.compile(r"class\s+(\w+)\s*\(\s*[\w.,\s]*Enum\s*\)\s*:")
_ENUM_MEMBER = re.compile(r"^\s{4,8}([A-Z][A-Z0-9_]*)\s*=")
_ASSIGN_STATE = re.compile(r"\b\w+\.(\w+)\s*=\s*(?:[A-Za-z_][\w.]*\.)?([A-Z][A-Z0-9_]*)\b")
_DEF_LINE = re.compile(r"^(\s*)def\s+\w+")

_GLOSSARY_STOPWORDS = {
    "self", "cls", "true", "false", "none", "null", "undefined", "return", "import", "from", "def", "class",
    "test", "tests", "index", "main", "util", "utils", "helper", "helpers", "src", "lib", "app", "get", "set",
}
_DOMAIN_DOCS = (".specs/product/DOMAIN.md", "docs/domain-map.md")


def _read(cwd: str, rel: str) -> str:
    try:
        with open(os.path.join(cwd, rel), encoding="utf-8", errors="ignore") as handle:
            return handle.read()
    except OSError:
        return ""


def _extract_limits(rel: str, text: str) -> list[dict]:
    rules = []
    seen = set()
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not _COMPARISON.search(line):
            continue
        for match in _LIMIT_NAME.finditer(line):
            name = match.group(1)
            key = (name, lineno)
            if key in seen:
                continue
            seen.add(key)
            rules.append({
                "id": f"rule.limit.{name.lower()}",
                "category": "limit",
                "statement": f"`{name}` is compared against a value — treated as a limit/quota/timeout gate",
                "evidence": [{"path": rel, "line": lineno}],
                "confidence": "observed",
            })
    return rules


def _extract_pattern_rules(rel: str, text: str, patterns: list, category: str, statement: str) -> list[dict]:
    rules = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for pattern in patterns:
            if pattern.search(line):
                rules.append({
                    "id": f"rule.{category}.{rel}.{lineno}",
                    "category": category,
                    "statement": statement,
                    "evidence": [{"path": rel, "line": lineno}],
                    "confidence": "observed",
                })
                break
    return rules


def _extract_side_effects(rel: str, text: str) -> list[dict]:
    rules = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for pattern, kind in _SIDE_EFFECT_PATTERNS:
            if pattern.search(line):
                rules.append({
                    "id": f"rule.side-effect.{kind}.{rel}.{lineno}",
                    "category": "side-effect",
                    "statement": f"business side-effect observed: {kind}",
                    "evidence": [{"path": rel, "line": lineno}],
                    "confidence": "observed",
                })
    return rules


def _extract_invariants(rel: str, text: str) -> list[dict]:
    rules = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        match = _INVARIANT_PATTERN.search(line)
        if not match:
            continue
        message = (match.group(1) or match.group(2) or "").strip()
        if not message:
            continue
        rules.append({
            "id": f"rule.invariant.{rel}.{lineno}",
            "category": "invariant",
            "statement": message,
            "evidence": [{"path": rel, "line": lineno}],
            "confidence": "observed",
        })
    return rules


def _extract_state_machines(rel: str, text: str) -> list[dict]:
    lines = text.splitlines()
    machines = []
    i = 0
    n = len(lines)
    while i < n:
        match = _ENUM_CLASS.search(lines[i])
        if not match:
            i += 1
            continue
        name = match.group(1)
        members: list[dict] = []
        j = i + 1
        while j < n:
            line = lines[j]
            member_match = _ENUM_MEMBER.match(line)
            if member_match:
                members.append({"name": member_match.group(1), "line": j + 1})
                j += 1
                continue
            if line.strip() and not line.startswith((" ", "\t")):
                break
            if line.strip() and not member_match:
                j += 1
                continue
            if not line.strip():
                j += 1
                continue
            j += 1
        if len(members) >= 2:
            machines.append({
                "name": name,
                "states": [m["name"] for m in members],
                "evidence": [{"path": rel, "line": i + 1}],
                "transitions": [],
            })
        i = j
    return machines


def _extract_transitions_for_file(rel: str, text: str, known_states: set[str]) -> list[dict]:
    """Bounded, per-function scan for sequential same-attribute state
    assignments (e.g. ``order.status = OrderStatus.PENDING`` ... later in the
    same function ``order.status = OrderStatus.SHIPPED``). Cross-function or
    cross-file transitions are intentionally not inferred — favors precision."""
    lines = text.splitlines()
    transitions = []
    i = 0
    n = len(lines)
    while i < n:
        def_match = _DEF_LINE.match(lines[i])
        if not def_match:
            i += 1
            continue
        indent = len(def_match.group(1))
        j = i + 1
        by_attr: dict[str, list[tuple[str, int]]] = {}
        while j < n:
            line = lines[j]
            stripped = line.strip()
            if stripped and (len(line) - len(line.lstrip())) <= indent:
                break
            for assign in _ASSIGN_STATE.finditer(line):
                attr, state = assign.group(1), assign.group(2)
                if state in known_states:
                    by_attr.setdefault(attr, []).append((state, j + 1))
            j += 1
        for sequence in by_attr.values():
            for k in range(len(sequence) - 1):
                from_state, _from_line = sequence[k]
                to_state, to_line = sequence[k + 1]
                if from_state == to_state:
                    continue
                transitions.append({"from": from_state, "to": to_state, "evidence": {"path": rel, "line": to_line}})
        i = max(j, i + 1)
    return transitions


def _domain_doc_terms(cwd: str) -> dict[str, str]:
    terms: dict[str, str] = {}
    for rel in _DOMAIN_DOCS:
        if not os.path.isfile(os.path.join(cwd, rel)):
            continue
        text = _read(cwd, rel)
        for match in re.finditer(r"^#{2,4}\s+(.+)$", text, re.MULTILINE):
            term = match.group(1).strip().strip("`").lower()
            if term and term not in terms:
                terms[term] = rel
        for match in re.finditer(r"\*\*([A-Za-z][\w -]{2,40})\*\*", text):
            term = match.group(1).strip().lower()
            if term and term not in terms:
                terms[term] = rel
    return terms


def _build_glossary(cwd: str, symbol_index: dict) -> list[dict]:
    domain_terms = _domain_doc_terms(cwd)
    occurrences: dict[str, int] = {}
    for symbol in symbol_index.get("symbols") or []:
        for word in _token_words(symbol.get("name", "")):
            if word in _GLOSSARY_STOPWORDS or len(word) < 3:
                continue
            occurrences[word] = occurrences.get(word, 0) + 1

    glossary = []
    seen_terms = set()
    for term, source in sorted(domain_terms.items()):
        key = term.replace(" ", "_").replace("-", "_")
        count = occurrences.get(key, 0) or occurrences.get(term.split()[0], 0)
        glossary.append({"term": term, "status": "documented", "definition_source": source, "occurrences": count})
        seen_terms.add(term)
    for word, count in sorted(occurrences.items(), key=lambda kv: (-kv[1], kv[0])):
        if word in seen_terms or count < 3:
            continue
        glossary.append({"term": word, "status": "undocumented", "definition_source": None, "occurrences": count})
    return glossary


def build_business_rules(cwd: str, artifacts: dict) -> dict:
    abs_cwd = os.path.abspath(cwd)
    project_map = artifacts["project_map"]
    symbol_index = artifacts["symbol_index"]
    flow_inventory = build_flow_inventory(abs_cwd, artifacts)

    source_files = [
        f["path"] for f in project_map.get("files") or []
        if os.path.splitext(f["path"])[1] in _TEXT_EXTS
    ]

    rules: list[dict] = []
    state_machines: list[dict] = []
    known_states: set[str] = set()
    file_texts: dict[str, str] = {}

    for rel in sorted(source_files):
        text = _read(abs_cwd, rel)
        if not text:
            continue
        file_texts[rel] = text
        rules.extend(_extract_limits(rel, text))
        rules.extend(_extract_pattern_rules(rel, text, _PERMISSION_PATTERNS, "permission", "access gate: authentication/authorization check observed"))
        rules.extend(_extract_pattern_rules(rel, text, _VALIDATION_PATTERNS, "validation", "input validation gate observed"))
        rules.extend(_extract_side_effects(rel, text))
        rules.extend(_extract_invariants(rel, text))
        machines = _extract_state_machines(rel, text)
        state_machines.extend(machines)
        for machine in machines:
            known_states.update(machine["states"])

    for rel, text in file_texts.items():
        for transition in _extract_transitions_for_file(rel, text, known_states):
            for machine in state_machines:
                if transition["from"] in machine["states"] and transition["to"] in machine["states"]:
                    if transition not in machine["transitions"]:
                        machine["transitions"].append(transition)

    flow_paths: dict[str, list[str]] = {}
    for flow in flow_inventory.get("flows") or []:
        touched = {step["path"] for step in flow["steps"]} | {e["evidence"]["path"] for e in flow["effects"]}
        for path in touched:
            flow_paths.setdefault(path, []).append(flow["id"])
    for rule in rules:
        flow_ids: set[str] = set()
        for evidence in rule["evidence"]:
            flow_ids.update(flow_paths.get(evidence["path"], []))
        rule["flows"] = sorted(flow_ids)

    rules.sort(key=lambda r: (r["category"], r["id"]))
    state_machines.sort(key=lambda m: m["name"])
    glossary = _build_glossary(abs_cwd, symbol_index)

    return {
        "schema": BUSINESS_RULES_SCHEMA,
        "version": BUSINESS_RULES_VERSION,
        "generated_at": project_map.get("generated_at"),
        "rules": rules,
        "state_machines": state_machines,
        "glossary": glossary,
    }


def render_business_rules_markdown(payload: dict) -> str:
    rules = payload["rules"]
    state_machines = payload["state_machines"]
    glossary = payload["glossary"]
    lines = [
        "# Business Flows & Rules",
        "",
        "Auto-generated. Rules below are **observable** signals (validation, "
        "permission gates, limits/quotas, side-effects, invariants) with "
        "`path:line` evidence. Semantic intent (the *why*) is never inferred.",
        "",
        f"- Rules detected: {len(rules)}",
        f"- State machines detected: {len(state_machines)}",
        f"- Glossary terms: {len(glossary)}",
        "",
    ]
    if not rules and not state_machines:
        lines.append("No observable business rules were detected in this repository.")

    by_category: dict[str, list[dict]] = {}
    for rule in rules:
        by_category.setdefault(rule["category"], []).append(rule)
    for category in sorted(by_category):
        lines += [f"## {category.replace('-', ' ').title()}", "", "| Rule | Evidence | Flows |", "| --- | --- | --- |"]
        for rule in by_category[category]:
            evidence = ", ".join(f"`{e['path']}:{e['line']}`" for e in rule["evidence"])
            flows = ", ".join(rule.get("flows") or []) or "—"
            lines.append(f"| {rule['statement']} | {evidence} | {flows} |")
        lines.append("")

    if state_machines:
        lines += ["## State Machines", ""]
        for machine in state_machines:
            lines += [f"### {machine['name']}", ""]
            transitions = [{"from": t["from"], "to": t["to"]} for t in machine["transitions"]]
            diagram = render_state_diagram(machine["states"], transitions)
            lines.append(to_markdown_block(diagram))
            if not machine["transitions"]:
                lines.append("_No transitions observed between these states._")
                lines.append("")

    if glossary:
        lines += ["## Glossary", "", "| Term | Status | Source | Occurrences |", "| --- | --- | --- | --- |"]
        for item in glossary:
            lines.append(
                f"| {item['term']} | {item['status']} | {item.get('definition_source') or '—'} | {item['occurrences']} |"
            )
        lines.append("")

    return "\n".join(lines)
