from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Tuple

SCHEMA = "simplicio.task-contract/v1"

SECTION_PATTERNS = {
    "acceptance_criteria": re.compile(
        r"^\s*1\.\s*(?:Crit[ée]rios de Aceite|Acceptance Criteria)\b", re.I
    ),
    "business_rules": re.compile(
        r"^\s*2\.\s*(?:Regras de Neg[óo]cio|Business Rules)\b", re.I
    ),
    "nfrs": re.compile(
        r"^\s*3\.\s*(?:Requisitos N[ãa]o Funcionais|Non[- ]Functional Requirements)\b", re.I
    ),
    "prototypes": re.compile(r"^\s*4\.\s*(?:Prot[óo]tipos|Prototypes)\b", re.I),
    "access": re.compile(r"^\s*5\.\s*(?:Acesso|Access)\b", re.I),
    "dependencies": re.compile(r"^\s*6\.\s*(?:Depend[êe]ncias|Dependencies)\b", re.I),
    "impact_signals": re.compile(r"^\s*7\.\s*(?:Sinais de Impacto|Impact Signals)\b", re.I),
    "additional_information": re.compile(
        r"^\s*8\.\s*(?:Informa[çc][õo]es Adicionais|Additional Information)\b", re.I
    ),
    "routing": re.compile(r"^\s*9\.\s*(?:Roteamento|Routing)\b", re.I),
}
SCENARIO_RE = re.compile(
    r"^\s*(?:Cen[áa]rio|Scenario)\s+(?P<num>\d+)\s*:\s*(?P<title>.+?)\s*$", re.I
)
RULE_RE = re.compile(r"^\s*(?P<id>RN\d+)\s*[–-]\s*(?P<text>.+?)\s*$", re.I)
RULE_REF_RE = re.compile(r"\[(RN\d+)\]", re.I)
IDENTITY_RE = re.compile(
    r"^\s*(Sistema|System|Funcionalidade|Feature|Tipo|Type)\s*:\s*(.+?)\s*$", re.I
)
TASK_ID_RE = re.compile(
    r"^\s*(?P<id>[A-Za-z][A-Za-z0-9]*(?:[-_][A-Za-z0-9]+)+)\b"
)
INLINE_DEPENDENCY_RE = re.compile(
    r"^\s*(?:Depends on|Depende de|Depend[êe]ncia|Dependencia)\s*:\s*(?P<value>.+?)\s*$",
    re.I,
)
STORY_RE = re.compile(r"^\s*(COMO|QUERO|PARA|AS|I WANT|SO THAT)\s+(.+?)\s*$", re.I)
GIVEN_RE = re.compile(r"^\s*(?:Dado(?: que)?|Given)\s+(.+?)\s*$", re.I)
WHEN_RE = re.compile(r"^\s*(?:Quando|When)\s+(.+?)\s*$", re.I)
THEN_RE = re.compile(r"^\s*(?:Ent[aã]o|Then)\s+(.+?)\s*$", re.I)
MULTI_TASK_SPLIT_RE = re.compile(r"(?=^\s*(?:Sistema|System)\s*:)", re.I | re.M)
_TASK_START_PREFIXES = ("sistema:", "system:")
WS_RE = re.compile(r"\s+")
URL_RE = re.compile(r"https?://\S+", re.I)

# -- routing (issue #287: role/capability/budget/fallback fields on the task ----
# contract, so simplicio_loop/model_router.py::route()/route_with_fallback() can
# be driven by a real, frozen task contract instead of a synthetic requirements
# dict handed in ad hoc.
ROUTING_LINE_RE = re.compile(r"^\s*-?\s*(?P<key>[^:]+):\s*(?P<value>.*)$")
ROUTING_LABELS = {
    "papel": "role",
    "role": "role",
    "capacidades obrigatórias": "required_capabilities",
    "capacidades obrigatorias": "required_capabilities",
    "required_capabilities": "required_capabilities",
    "capacidades preferenciais": "preferred_capabilities",
    "preferred_capabilities": "preferred_capabilities",
    "providers permitidos": "allowed_providers",
    "allowed_providers": "allowed_providers",
    "providers proibidos": "denied_providers",
    "denied_providers": "denied_providers",
    "budget tokens": "budget_tokens",
    "budget_tokens": "budget_tokens",
    "budget usd": "budget_usd",
    "budget_usd": "budget_usd",
    "budget segundos": "budget_seconds",
    "budget_seconds": "budget_seconds",
    "política de fallback": "fallback_policy",
    "politica de fallback": "fallback_policy",
    "fallback_policy": "fallback_policy",
    "máximo de routes": "max_routes",
    "maximo de routes": "max_routes",
    "max_routes": "max_routes",
    "review independente": "independent_review",
    "independent_review": "independent_review",
}
DEFAULT_ROUTING_ROLE = "executor"
ROUTING_ROLES = frozenset(("planner", "executor", "reviewer", "tester"))
FALLBACK_POLICIES = frozenset(("block", "retry_same_route", "fallback_route"))


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _norm(text: str) -> str:
    return WS_RE.sub(" ", (text or "").strip())


def _stable_hash(data: Any) -> str:
    blob = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def split_tasks(text: str) -> List[str]:
    chunks = [c.strip() for c in MULTI_TASK_SPLIT_RE.split(text or "") if c.strip()]
    if not chunks:
        return []
    if len(chunks) == 1:
        return chunks
    merged: List[str] = []
    for chunk in chunks:
        if chunk.lower().startswith(_TASK_START_PREFIXES):
            merged.append(chunk)
        elif merged:
            merged[-1] = merged[-1].rstrip() + "\n\n" + chunk
        else:
            merged.append(chunk)
    return [c for c in merged if c.strip()]


def _collect_sections(lines: List[str]) -> Tuple[Dict[str, List[str]], List[str]]:
    sections: Dict[str, List[str]] = {k: [] for k in SECTION_PATTERNS}
    preamble: List[str] = []
    current = None
    for line in lines:
        heading = re.match(r"^\s*#{1,6}\s*(.+?)\s*#*\s*$", line)
        if heading:
            label = heading.group(1).strip().lower()
            heading_map = {
                "acceptance criteria": "acceptance_criteria",
                "acceptance criteria / cenários": "acceptance_criteria",
                "critérios de aceite": "acceptance_criteria",
                "criterios de aceite": "acceptance_criteria",
                "cenários de aceitação": "acceptance_criteria",
                "cenarios de aceitacao": "acceptance_criteria",
                "business rules": "business_rules",
                "regras de negócio": "business_rules",
                "regras de negocio": "business_rules",
                "non-functional requirements": "nfrs",
                "non functional requirements": "nfrs",
                "requisitos não funcionais": "nfrs",
                "requisitos nao funcionais": "nfrs",
                "prototypes": "prototypes",
                "protótipos": "prototypes",
                "prototipos": "prototypes",
                "access": "access",
                "acesso": "access",
                "dependencies": "dependencies",
                "dependências": "dependencies",
                "dependencias": "dependencies",
                "impact signals": "impact_signals",
                "sinais de impacto": "impact_signals",
                "additional information": "additional_information",
                "informações adicionais": "additional_information",
                "informacoes adicionais": "additional_information",
                "routing": "routing",
                "roteamento": "routing",
            }
            mapped = heading_map.get(label)
            if mapped:
                current = mapped
                continue
            scenario_heading = re.match(
                r"(?:scn|scenario|cenário|cenario)\s*[-#:]?\s*(\d+)\s*(?:[-—:]\s*)?(.*)$",
                label, re.I,
            )
            if scenario_heading and current == "acceptance_criteria":
                number, title = scenario_heading.groups()
                sections[current].append(f"Cenário {number}: {title or 'Scenario ' + number}")
                continue
        matched = False
        for name, rx in SECTION_PATTERNS.items():
            if rx.match(line):
                current = name
                matched = True
                break
        if matched:
            continue
        if current is None:
            preamble.append(line)
        else:
            sections[current].append(line)
    return sections, preamble


def _parse_identity(lines: Iterable[str]) -> Dict[str, str]:
    out = {"id": "", "system": "", "feature": "", "type": "", "title": ""}
    for line in lines:
        m = IDENTITY_RE.match(line)
        if not m:
            continue
        key = m.group(1).strip().lower()
        value = _norm(m.group(2))
        if key in {"sistema", "system"}:
            out["system"] = value
        elif key in {"funcionalidade", "feature"}:
            out["feature"] = value
        elif key in {"tipo", "type"}:
            out["type"] = value
    title_parts = [p for p in (out["feature"], out["type"]) if p]
    out["title"] = " — ".join(title_parts) if title_parts else out["feature"] or out["system"]
    feature_match = TASK_ID_RE.match(out["feature"])
    if feature_match:
        out["id"] = feature_match.group("id")
    return out


def _parse_inline_dependencies(lines: Iterable[str]) -> List[str]:
    dependencies: List[str] = []
    for line in lines:
        match = INLINE_DEPENDENCY_RE.match(line)
        if not match:
            continue
        dependencies.extend(
            value.strip().lstrip("-* ")
            for value in re.split(r"[,;]", match.group("value"))
            if value.strip().lstrip("-* ")
        )
    return dependencies


def _parse_story(lines: Iterable[str]) -> Dict[str, str]:
    story = {"persona": "", "desire": "", "value": ""}
    for line in lines:
        m = STORY_RE.match(line)
        if not m:
            continue
        key = m.group(1).upper()
        value = _norm(m.group(2)).rstrip(",")
        if key in {"COMO", "AS"}:
            story["persona"] = value
        elif key in {"QUERO", "I WANT"}:
            story["desire"] = value
        elif key in {"PARA", "SO THAT"}:
            story["value"] = value
    return story


def _verification_intent(scenario: Dict[str, Any]) -> str:
    focus = scenario.get("title") or "scenario"
    rule_refs = ", ".join(scenario.get("rule_refs") or [])
    if rule_refs:
        return f"Reexecutar comportamento de '{focus}' com cobertura de {rule_refs}"
    return f"Reexecutar comportamento de '{focus}'"


def _parse_scenarios(lines: Iterable[str]) -> List[Dict[str, Any]]:
    scenarios: List[Dict[str, Any]] = []
    current: Dict[str, Any] | None = None
    for raw in lines:
        line = raw.rstrip()
        m = SCENARIO_RE.match(line)
        if m:
            if current:
                current["verification_intent"] = _verification_intent(current)
                scenarios.append(current)
            current = {
                "id": f"SCN{m.group('num')}",
                "title": _norm(m.group("title")),
                "given": [],
                "when": [],
                "then": [],
                "rule_refs": [],
            }
            continue
        if not current:
            continue
        gm = GIVEN_RE.match(line)
        if gm:
            current["given"].append(_norm(gm.group(1)))
            current["rule_refs"].extend(r.upper() for r in RULE_REF_RE.findall(line))
            continue
        wm = WHEN_RE.match(line)
        if wm:
            current["when"].append(_norm(wm.group(1)))
            current["rule_refs"].extend(r.upper() for r in RULE_REF_RE.findall(line))
            continue
        tm = THEN_RE.match(line)
        if tm:
            then_text = _norm(tm.group(1))
            current["then"].append(then_text)
            current["rule_refs"].extend(r.upper() for r in RULE_REF_RE.findall(line))
            continue
        if line.strip():
            current["rule_refs"].extend(r.upper() for r in RULE_REF_RE.findall(line))
    if current:
        current["verification_intent"] = _verification_intent(current)
        scenarios.append(current)
    for scn in scenarios:
        seen = set()
        refs = []
        for ref in scn["rule_refs"]:
            if ref not in seen:
                refs.append(ref)
                seen.add(ref)
        scn["rule_refs"] = refs
    return scenarios


def _parse_rules(lines: Iterable[str], scenarios: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    refs_by_rule: Dict[str, List[str]] = {}
    for scenario in scenarios:
        for ref in scenario.get("rule_refs") or []:
            refs_by_rule.setdefault(ref, []).append(scenario["id"])
    rules = []
    for line in lines:
        m = RULE_RE.match(line)
        if not m:
            continue
        rid = m.group("id").upper()
        rules.append(
            {
                "id": rid,
                "text": _norm(m.group("text")),
                "scenario_refs": refs_by_rule.get(rid, []),
            }
        )
    return rules


def _parse_stateful_list(lines: Iterable[str], unknown_markers: List[str]) -> Dict[str, Any]:
    cleaned = [_norm(line.lstrip("-*")) for line in lines if _norm(line)]
    blob = " ".join(cleaned).lower()
    if not cleaned:
        return {"state": "unknown", "items": []}
    if any(marker in blob for marker in unknown_markers):
        return {"state": "unknown", "items": cleaned}
    if "nenhuma" in blob or "nenhum" in blob or "none identified" in blob:
        return {"state": "confirmed_none", "items": cleaned}
    return {"state": "declared", "items": cleaned}


def _parse_prototypes(lines: Iterable[str]) -> List[Dict[str, Any]]:
    cleaned = [_norm(line.lstrip("-*")) for line in lines if _norm(line)]
    if not cleaned:
        return []
    out = []
    for item in cleaned:
        urls = URL_RE.findall(item)
        status = "available" if urls else "missing"
        out.append({
            "reference": item,
            "status": status,
            "hash": "",
            "trust": "untrusted",
            "provenance": {
                "kind": "url" if urls else "inline-reference",
                "urls": urls,
                "source": "task_markdown",
                "verified": False,
            },
        })
    return out


def _collect_external_references(contract: Dict[str, Any]) -> List[Dict[str, Any]]:
    refs: List[Dict[str, Any]] = []
    seen = set()
    for proto in contract.get("prototypes") or []:
        prov = proto.get("provenance") or {}
        for url in prov.get("urls") or []:
            if url in seen:
                continue
            refs.append({
                "kind": "url",
                "value": url,
                "trust": "untrusted",
                "source_section": "prototypes",
                "verified": False,
                "hash": "",
            })
            seen.add(url)
    for section in contract.get("raw_sections") or []:
        for url in URL_RE.findall(section.get("content", "")):
            if url in seen:
                continue
            refs.append({
                "kind": "url",
                "value": url,
                "trust": "untrusted",
                "source_section": section.get("name", "raw"),
                "verified": False,
                "hash": "",
            })
            seen.add(url)
    return refs


def _parse_access(lines: Iterable[str]) -> str:
    for line in lines:
        value = _norm(line.lstrip("-*"))
        if value:
            return value
    return ""


def _impact_value(line: str) -> Tuple[str, str]:
    low = line.lower()
    if "✓" in line or "sim" in low or low.endswith(": y"):
        return "yes", "stated"
    if "poss" in low:
        return "possible", "stated"
    if "✗" in line or "não" in low or "nao" in low:
        return "no", "stated"
    return "unknown", "unknown"


def _parse_impact(lines: Iterable[str]) -> Dict[str, Dict[str, str]]:
    impact = {
        "frontend": {"value": "unknown", "confidence": "unknown"},
        "backend": {"value": "unknown", "confidence": "unknown"},
        "database": {"value": "unknown", "confidence": "unknown"},
        "integrations": {"value": "unknown", "confidence": "unknown"},
    }
    for raw in lines:
        line = _norm(raw)
        if not line:
            continue
        low = line.lower()
        value, confidence = _impact_value(line)
        if low.startswith("frontend"):
            impact["frontend"] = {"value": value, "confidence": confidence}
        elif low.startswith("backend"):
            impact["backend"] = {"value": value, "confidence": confidence}
        elif low.startswith("banco"):
            impact["database"] = {"value": value, "confidence": confidence}
        elif low.startswith("integra"):
            impact["integrations"] = {"value": value, "confidence": confidence}
    return impact


def _split_csv(value: str) -> List[str]:
    return [v.strip() for v in re.split(r"[,;]", value or "") if v.strip()]


def _parse_bool_pt(value: str) -> bool:
    return (value or "").strip().lower() in {"sim", "yes", "true", "1", "s", "y"}


def _parse_number(value: str) -> Any:
    text = (value or "").strip()
    if not text:
        return None
    try:
        if "." in text:
            return float(text)
        return int(text)
    except ValueError:
        return None


def _empty_routing() -> Dict[str, Any]:
    return {
        "state": "unspecified",
        "role": DEFAULT_ROUTING_ROLE,
        "required_capabilities": [],
        "preferred_capabilities": [],
        "allowed_providers": [],
        "denied_providers": [],
        "budget": {"tokens": None, "usd": None, "seconds": None, "state": "unspecified"},
        "fallback_policy": "block",
        "max_routes": 1,
        "independent_review": False,
    }


def _parse_routing(lines: Iterable[str]) -> Dict[str, Any]:
    """Parse the optional '9. Roteamento' section into role/capability/budget/
    fallback-policy fields the router can consume directly (see
    :func:`routing_requirements`). Absent section => explicit ``state:
    "unspecified"`` defaults, never a silently-invented role/policy."""
    fields: Dict[str, str] = {}
    for raw in lines:
        if not _norm(raw):
            continue
        m = ROUTING_LINE_RE.match(raw)
        if not m:
            continue
        label = _norm(m.group("key")).lower()
        canonical = ROUTING_LABELS.get(label)
        if canonical:
            fields[canonical] = _norm(m.group("value"))
    if not fields:
        return _empty_routing()

    role = (fields.get("role") or "").strip().lower() or DEFAULT_ROUTING_ROLE
    if role not in ROUTING_ROLES:
        role = DEFAULT_ROUTING_ROLE

    budget_tokens = _parse_number(fields.get("budget_tokens", ""))
    budget_usd = _parse_number(fields.get("budget_usd", ""))
    budget_seconds = _parse_number(fields.get("budget_seconds", ""))
    budget_state = "declared" if any(v is not None for v in (budget_tokens, budget_usd, budget_seconds)) else "unspecified"

    fallback_policy = (fields.get("fallback_policy") or "").strip().lower() or "block"
    if fallback_policy not in FALLBACK_POLICIES:
        fallback_policy = "block"

    max_routes_raw = _parse_number(fields.get("max_routes", ""))
    max_routes = int(max_routes_raw) if isinstance(max_routes_raw, (int, float)) and max_routes_raw >= 1 else 1

    return {
        "state": "declared",
        "role": role,
        "required_capabilities": _split_csv(fields.get("required_capabilities", "")),
        "preferred_capabilities": _split_csv(fields.get("preferred_capabilities", "")),
        "allowed_providers": _split_csv(fields.get("allowed_providers", "")),
        "denied_providers": _split_csv(fields.get("denied_providers", "")),
        "budget": {
            "tokens": budget_tokens,
            "usd": budget_usd,
            "seconds": budget_seconds,
            "state": budget_state,
        },
        "fallback_policy": fallback_policy,
        "max_routes": max_routes,
        "independent_review": _parse_bool_pt(fields.get("independent_review", "")),
    }


def routing_requirements(contract: Mapping[str, Any]) -> Dict[str, Any]:
    """Project a compiled contract's ``routing`` section onto the requirements
    shape ``simplicio_loop.model_router.route()``/``route_with_fallback()``
    expect. Budget/fallback_policy/max_routes are not part of registry
    eligibility (they drive the fallback layer, not candidate filtering) so
    they are intentionally left out of the returned dict; read them from
    ``contract["routing"]`` directly when driving retries."""
    routing = contract.get("routing") or _empty_routing()
    return {
        "role": routing.get("role") or DEFAULT_ROUTING_ROLE,
        "required_capabilities": list(routing.get("required_capabilities") or []),
        "preferred_capabilities": list(routing.get("preferred_capabilities") or []),
        "allowed_providers": list(routing.get("allowed_providers") or []),
        "denied_providers": list(routing.get("denied_providers") or []),
        "independent_review": bool(routing.get("independent_review")),
    }


def _parse_additional_information(lines: Iterable[str]) -> Tuple[List[str], str]:
    items = [_norm(line.lstrip("-*")) for line in lines if _norm(line)]
    production = ""
    for item in items:
        if "produção" in item.lower() or "producao" in item.lower():
            production = item
            break
    return items, production


def _classify_ambiguities(contract: Dict[str, Any]) -> Tuple[List[Dict[str, str]], List[Dict[str, str]], List[Dict[str, str]], List[Dict[str, str]]]:
    questions: List[Dict[str, str]] = []
    assumptions: List[Dict[str, str]] = []
    blockers: List[Dict[str, str]] = []
    decision_ledger: List[Dict[str, str]] = []

    if (contract.get("nfrs") or {}).get("state") == "unknown":
        questions.append({
            "id": "Q-NFR-1",
            "classification": "assumption-reversible",
            "summary": "NFRs não identificados na entrada; validar com o time antes de concluir delivery maior que verified.",
            "evidence": "section:nfrs=unknown",
        })
    if (contract.get("dependencies") or {}).get("state") == "unknown":
        questions.append({
            "id": "Q-DEP-1",
            "classification": "assumption-reversible",
            "summary": "Dependências não confirmadas; não converter unknown em none automaticamente.",
            "evidence": "section:dependencies=unknown",
        })
    impact = contract.get("impact_signals") or {}
    if ((impact.get("frontend") or {}).get("value") == "yes"
            and (impact.get("backend") or {}).get("value") == "possible"):
        questions.append({
            "id": "Q-LAYER-1",
            "classification": "decision-required",
            "summary": "Frontend confirmado e backend possível exigem investigação do mapper antes de escolher a camada.",
            "evidence": "impact:frontend=yes backend=possible",
        })
    prototypes = contract.get("prototypes") or []
    if any(proto.get("status") == "missing" for proto in prototypes):
        assumptions.append({
            "id": "A-PROTOTYPE-1",
            "classification": "assumption-reversible",
            "summary": "Sem protótipo verificável; seguir pela task textual até surgir evidência visual confiável.",
            "evidence": "prototype:missing",
        })
    rule_ids = {rule.get("id") for rule in (contract.get("rules") or [])}
    if "RN02" in rule_ids:
        questions.append({
            "id": "Q-DATE-1",
            "classification": "assumption-reversible",
            "summary": "Empate de data, data ausente/inválida e estabilidade da ordenação precisam de decisão explícita se o código/domínio não resolver.",
            "evidence": "rule:RN02 date-ordering",
        })
    if "RN03" in rule_ids:
        questions.append({
            "id": "Q-COLLATION-1",
            "classification": "assumption-reversible",
            "summary": "Colação alfabética (acentos/case) precisa ser confirmada se o código/domínio não definir o comportamento.",
            "evidence": "rule:RN03 alphabetical-order",
        })
    raw_text = " ".join(item.get("content", "") for item in (contract.get("raw_sections") or []))
    if any(token in raw_text.lower() for token in ["ignore o loop", "<promise>", "powershell", "cmd /c", "bash -c"]):
        blockers.append({
            "id": "B-UNTRUSTED-1",
            "classification": "out-of-scope",
            "summary": "Conteúdo da task contém texto operacional/instrucional não confiável; tratar como dado, nunca como reconfiguração do loop.",
            "evidence": "raw-section contains untrusted operational text",
        })

    for item in questions + assumptions + blockers:
        decision_ledger.append({
            "id": item["id"],
            "classification": item["classification"],
            "summary": item["summary"],
            "evidence": item["evidence"],
        })
    return questions, assumptions, blockers, decision_ledger


def compile_task(text: str, source_path: str = "") -> Dict[str, Any]:
    raw = text.replace("\r\n", "\n")
    lines = raw.splitlines()
    sections, preamble = _collect_sections(lines)
    identity = _parse_identity(preamble)
    story = _parse_story(preamble)
    scenarios = _parse_scenarios(sections["acceptance_criteria"])
    rules = _parse_rules(sections["business_rules"], scenarios)
    nfrs = _parse_stateful_list(
        sections["nfrs"],
        ["validar com o time", "validar com a equipe", "validate with the team", "unknown"],
    )
    dependencies = _parse_stateful_list(
        sections["dependencies"] + _parse_inline_dependencies(preamble),
        ["validar com o time", "validar com a equipe", "unknown"],
    )
    prototypes = _parse_prototypes(sections["prototypes"])
    access_path = _parse_access(sections["access"])
    additional_information, production_signal = _parse_additional_information(
        sections["additional_information"]
    )
    routing = _parse_routing(sections["routing"])
    contract = {
        "schema": SCHEMA,
        "id": identity.get("id", ""),
        # Preserve the exact provider-free source for typed downstream handoff.
        # The structured fields remain useful for Loop planning, but they are not
        # a substitute for the source that produced them.
        "original_text": raw,
        "source": {
            "kind": "markdown",
            "path": source_path or "",
            "hash": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
            "compiled_at": _now(),
        },
        "identity": identity,
        "story": story,
        "scenarios": scenarios,
        "rules": rules,
        "nfrs": nfrs,
        "prototypes": prototypes,
        "access_path": access_path,
        "dependencies": dependencies,
        "impact_signals": _parse_impact(sections["impact_signals"]),
        "constraints": [],
        "additional_information": additional_information,
        "production_signal": production_signal,
        "routing": routing,
        "questions": [],
        "assumptions": [],
        "blockers": [],
        "decision_ledger": [],
        "external_references": [],
        "raw_sections": [
            {"name": name, "content": "\n".join(v).strip()}
            for name, v in sections.items()
            if name not in {"acceptance_criteria", "business_rules", "routing"} and "\n".join(v).strip()
        ],
    }
    questions, assumptions, blockers, decision_ledger = _classify_ambiguities(contract)
    contract["questions"] = questions
    contract["assumptions"] = assumptions
    contract["blockers"] = blockers
    contract["decision_ledger"] = decision_ledger
    contract["external_references"] = _collect_external_references(contract)
    semantic_payload = {
        "identity": contract["identity"],
        "story": contract["story"],
        "scenarios": contract["scenarios"],
        "rules": contract["rules"],
        "nfrs": contract["nfrs"],
        "prototypes": contract["prototypes"],
        "access_path": contract["access_path"],
        "dependencies": contract["dependencies"],
        "impact_signals": contract["impact_signals"],
        "constraints": contract["constraints"],
        "additional_information": contract["additional_information"],
        "production_signal": contract["production_signal"],
        "routing": contract["routing"],
        "questions": contract["questions"],
        "assumptions": contract["assumptions"],
        "blockers": contract["blockers"],
        "decision_ledger": contract["decision_ledger"],
        "external_references": contract["external_references"],
        "raw_sections": contract["raw_sections"],
    }
    contract["contract_hash"] = _stable_hash(semantic_payload)
    return contract


def compile_many(text: str, source_path: str = "") -> Dict[str, Any]:
    stripped = (text or "").lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON task collection: {exc}") from exc
        if not isinstance(payload, Mapping) or payload.get("schema") != f"{SCHEMA}.collection":
            raise ValueError("JSON task input must be a simplicio.task-contract/v1.collection")
        tasks = payload.get("tasks")
        if not isinstance(tasks, list) or not tasks or any(not isinstance(task, Mapping) for task in tasks):
            raise ValueError("JSON task collection requires a non-empty tasks array")
        expected_hash = _stable_hash([task.get("contract_hash") for task in tasks])
        if payload.get("collection_hash") != expected_hash:
            raise ValueError("JSON task collection hash mismatch")
        return {
            "schema": f"{SCHEMA}.collection",
            "task_count": len(tasks),
            "tasks": [dict(task) for task in tasks],
            "collection_hash": expected_hash,
        }
    tasks = split_tasks(text)
    compiled = [compile_task(task, source_path=source_path) for task in tasks]
    return {
        "schema": f"{SCHEMA}.collection",
        "task_count": len(compiled),
        "tasks": compiled,
        "collection_hash": _stable_hash([task["contract_hash"] for task in compiled]),
    }


def validate_contract(contract: Dict[str, Any]) -> Dict[str, List[str]]:
    errors: List[str] = []
    warnings: List[str] = []
    scenarios = contract.get("scenarios") or []
    rules = contract.get("rules") or []
    rule_ids = [rule.get("id") for rule in rules]
    rule_set = set(rule_ids)
    if len(rule_set) != len(rule_ids):
        errors.append("duplicate rule id")
    scenario_ids = [scenario.get("id") for scenario in scenarios]
    if len(set(scenario_ids)) != len(scenario_ids):
        errors.append("duplicate scenario id")
    if not scenarios:
        errors.append(
            "no scenarios parsed; use 'Scenario N:' / 'Given' / 'When' / 'Then' "
            "or 'Cenário N:' / 'Dado' / 'Quando' / 'Então' under "
            "'1. Acceptance Criteria' / '1. Critérios de Aceite'"
        )
    for scenario in scenarios:
        sid = scenario.get("id", "?")
        if not scenario.get("then"):
            errors.append(f"{sid}: missing Then")
        for ref in scenario.get("rule_refs") or []:
            if ref not in rule_set:
                errors.append(f"{sid}: references undefined rule {ref}")
    used_rule_refs = {ref for scenario in scenarios for ref in (scenario.get("rule_refs") or [])}
    for rule in rules:
        rid = rule.get("id", "?")
        if rid not in used_rule_refs:
            errors.append(f"{rid}: defined but not referenced by any scenario")
        if not rule.get("scenario_refs"):
            warnings.append(f"{rid}: has no linked scenario refs")
    prototypes = contract.get("prototypes") or []
    for proto in prototypes:
        if proto.get("status") == "missing":
            warnings.append("prototype missing")
    if (contract.get("nfrs") or {}).get("state") == "unknown":
        warnings.append("nfrs require validation")
    if (contract.get("dependencies") or {}).get("state") == "unknown":
        warnings.append("dependencies require validation")
    routing = contract.get("routing") or {}
    if routing.get("state") == "unspecified":
        warnings.append("routing section not declared; defaulting to role=executor, fallback_policy=block")
    return {"errors": errors, "warnings": warnings}


def preview_contract(contract: Dict[str, Any]) -> str:
    validation = validate_contract(contract)
    identity = contract.get("identity") or {}
    lines = [
        f"schema: {contract.get('schema', SCHEMA)}",
        f"title: {identity.get('title') or identity.get('feature') or '(untitled)'}",
        f"system: {identity.get('system') or '-'}",
        f"scenarios: {len(contract.get('scenarios') or [])}",
        f"rules: {len(contract.get('rules') or [])}",
        f"nfr_state: {(contract.get('nfrs') or {}).get('state', 'unknown')}",
        f"dependency_state: {(contract.get('dependencies') or {}).get('state', 'unknown')}",
        f"errors: {len(validation['errors'])}",
        f"warnings: {len(validation['warnings'])}",
        f"contract_hash: {contract.get('contract_hash', '')}",
    ]
    for scenario in contract.get("scenarios") or []:
        refs = ",".join(scenario.get("rule_refs") or []) or "-"
        lines.append(f"- {scenario['id']}: {scenario.get('title', '')} [{refs}]")
    return "\n".join(lines)


def _load_input(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8")


def _write_json(path: str, payload: Dict[str, Any]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _cmd_compile(args: argparse.Namespace) -> int:
    raw = _load_input(args.input)
    payload = compile_many(raw, source_path="" if args.input == "-" else str(Path(args.input)))
    if args.out:
        _write_json(args.out, payload)
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    try:
        payload = _load_compiled_contract(args.contract)
    except ValueError as exc:
        return _print_contract_error(str(exc))
    if not isinstance(payload, Mapping):
        return _print_contract_error(
            f"contract root must be a JSON object: {args.contract}"
        )
    tasks = payload.get("tasks") or [payload]
    all_errors: List[str] = []
    all_warnings: List[str] = []
    for idx, task in enumerate(tasks, start=1):
        result = validate_contract(dict(task))
        for err in result["errors"]:
            all_errors.append(f"task[{idx}] {err}")
        for warning in result["warnings"]:
            all_warnings.append(f"task[{idx}] {warning}")
    out = {"ok": not all_errors, "errors": all_errors, "warnings": all_warnings}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if not all_errors else 2


def _load_compiled_contract(path: str) -> Any:
    """Read a compiled contract document, failing closed on unusable input.

    ``preview`` and ``validate`` consume compiled contracts.  A missing path, an
    unreadable file or a non-JSON source (a raw markdown task file, for example)
    must produce a clean, actionable error instead of an unhandled traceback.
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(
            f"contract file is not readable: {path}: {exc.strerror or exc}"
        ) from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"contract file is not valid JSON: {path}: {exc}. "
            "Run `simplicio-loop task compile --input <markdown> --out <contract.json>` first."
        ) from exc


def _print_contract_error(message: str) -> int:
    print(json.dumps({"ok": False, "errors": [message]}, ensure_ascii=False, indent=2))
    return 2


def _cmd_preview(args: argparse.Namespace) -> int:
    try:
        payload = _load_compiled_contract(args.contract)
    except ValueError as exc:
        return _print_contract_error(str(exc))
    if not isinstance(payload, Mapping):
        return _print_contract_error(
            f"contract root must be a JSON object: {args.contract}"
        )
    tasks = payload.get("tasks") or [payload]
    for idx, task in enumerate(tasks, start=1):
        if idx > 1:
            print("")
        print(f"[task {idx}]")
        print(preview_contract(dict(task)))
    return 0


def _planes_sample() -> str:
    return """Sistema: PLANES
Funcionalidade: Tela de Modelagem — Ordenação de linhas
Tipo: Evolução

COMO analista do ONS,
QUERO que as linhas da tela de modelagem sejam ordenadas por tipo (estrutural primeiro) e depois por data de início (mais antigo para mais novo) entre temporais e modelagem,
PARA que a visualização dos dados siga uma ordem lógica e facilite a análise dos estudos.

1. Critérios de Aceite

Cenário 1: Estrutural aparece primeiro
  Dado que a usina possui linhas do tipo estrutural, temporal e modelagem
  Quando a tela de modelagem for exibida
  Então a linha do tipo estrutural deve aparecer primeiro [RN01]

Cenário 2: Temporal e modelagem ordenados por data de início
  Dado que a usina possui múltiplas linhas dos tipos temporal e modelagem
  Quando a tela de modelagem for exibida
  Então as linhas temporais e de modelagem devem ser ordenadas por data de início, do mais antigo para o mais novo [RN02]

2. Regras de Negócio

RN01 – Dentro de cada usina, a linha do tipo estrutural deve sempre aparecer primeiro.
RN02 – Após o estrutural, as linhas dos tipos temporal e modelagem devem ser ordenadas por data de início.

3. Requisitos Não Funcionais

Nenhum requisito não-funcional identificado na entrada — validar com o time.

6. Dependências

Nenhuma dependência identificada na entrada — validar com o time.
"""


def _cmd_selftest() -> int:
    compiled = compile_many(_planes_sample())
    assert compiled["task_count"] == 1
    task = compiled["tasks"][0]
    assert len(task["scenarios"]) == 2
    assert len(task["rules"]) == 2
    assert task["nfrs"]["state"] == "unknown"
    assert task["dependencies"]["state"] == "unknown"
    result = validate_contract(task)
    assert not result["errors"], result
    print("selftest: PASS task-contract compiler")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="simplicio-loop task")
    sub = parser.add_subparsers(dest="verb", required=True)

    p_compile = sub.add_parser("compile", help="compile markdown task(s) into a canonical contract")
    p_compile.add_argument("--input", required=True, help="markdown file path or - for stdin")
    p_compile.add_argument("--out", help="write JSON contract to a file")
    p_compile.set_defaults(func=_cmd_compile)

    p_validate = sub.add_parser("validate", help="validate a compiled contract JSON")
    p_validate.add_argument("contract", help="compiled contract path")
    p_validate.set_defaults(func=_cmd_validate)

    p_preview = sub.add_parser("preview", help="show a compact preview of a compiled contract")
    p_preview.add_argument("contract", help="compiled contract path")
    p_preview.set_defaults(func=_cmd_preview)

    p_selftest = sub.add_parser("selftest", help="run deterministic task-contract selftest")
    p_selftest.set_defaults(func=lambda _args: _cmd_selftest())
    return parser


def main(argv: List[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
