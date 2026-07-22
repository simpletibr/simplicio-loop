# ruff: noqa: E501
"""Create a reproducible, fail-closed audit of every GitHub issue.

The report is deliberately an evidence artifact, not a bulk issue editor.  It
preserves the original issue metadata and produces an implementable review
packet with the ten sections required by issue #265.  GitHub remains the
source of truth; ``--check`` fails when the checked-in snapshot is stale.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REPOSITORY = "wesleysimplicio/simplicio-dev-cli"
DEFAULT_JSON = ROOT / "docs/evidence/issue-265-meta-audit.json"
DEFAULT_MARKDOWN = ROOT / "docs/evidence/issue-265-meta-audit.md"
SCHEMA = "simplicio.dev-cli.meta-issue-audit/v1"
REQUIRED_SECTIONS = (
    "Contexto e problema",
    "Objetivo",
    "Fora de escopo",
    "Entradas, saídas e contratos",
    "Dependências e ordem",
    "Passo a passo implementável",
    "Fluxo de testes",
    "Critérios de aceite verificáveis",
    "Evidências obrigatórias",
    "Riscos, rollback e decisão de encerramento",
)
SECRET_PATTERNS = (
    re.compile(r"\b(?:gh[ps]|github_pat)_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)
MEASUREMENT_CLAIM = re.compile(
    r"(?:\b\d+(?:[.,]\d+)?\s*%|\b(?:faster|slower|performance|coverage|economia|"
    r"lat[êe]ncia|throughput|integra(?:ç|c)[aã]o)\b)",
    re.IGNORECASE,
)
EVIDENCE_WORD = re.compile(
    r"(?:benchmark|medid[ao]|m[eé]trica|pytest|teste|receipt|log|trace|evid[êe]ncia|"
    r"arquivo|commit|PR\s*#|https?://)",
    re.IGNORECASE,
)
REFERENCE = re.compile(r"(?<![\w/])#(\d+)\b")
PATH = re.compile(r"(?<![\w.-])(?:[\w.-]+/)+[\w.*?{}@+-]+(?:\.[\w*?{}+-]+)?")


def fetch_issues(repository: str, *, timeout: float = 20.0, retries: int = 2) -> list[dict[str, Any]]:
    """Fetch all issues (excluding pull requests), following API pagination."""
    url = f"https://api.github.com/repos/{repository}/issues?state=all&per_page=100&page=1"
    items: list[dict[str, Any]] = []
    while url:
        request = urllib.request.Request(
            url,
            headers={"Accept": "application/vnd.github+json", "User-Agent": "simplicio-meta-audit"},
        )
        for attempt in range(retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    page = json.load(response)
                    link = response.headers.get("Link", "")
                break
            except (urllib.error.URLError, TimeoutError):
                if attempt == retries:
                    raise
                time.sleep(0.25 * (2**attempt))
        if not isinstance(page, list):
            raise ValueError("GitHub issues response must be a list")
        items.extend(item for item in page if "pull_request" not in item)
        url = _next_link(link)
    return sorted(items, key=lambda item: (item["created_at"], item["number"]))


def _next_link(header: str) -> str:
    for part in header.split(","):
        match = re.match(r'\s*<([^>]+)>;\s*rel="([^"]+)"', part)
        if match and match.group(2) == "next":
            return match.group(1)
    return ""


def build_audit(raw_issues: Iterable[dict[str, Any]], repository: str) -> dict[str, Any]:
    issues = [_review_issue(item, repository) for item in raw_issues]
    issues.sort(key=lambda item: (item["created_at"], item["number"]))
    states = Counter(item["state"] for item in issues)
    labels = Counter(label for item in issues for label in item["labels"])
    components = Counter(item["classification"]["component"] for item in issues)
    decisions = Counter(item["closure_decision"] for item in issues)
    source_hash = hashlib.sha256(
        json.dumps(issues, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "schema": SCHEMA,
        "repository": repository,
        "source": "GitHub REST issues API; pull requests excluded",
        "source_sha256": source_hash,
        "ordering": "created_at ascending, number ascending",
        "summary": {
            "issues_total": len(issues),
            "by_state": dict(sorted(states.items())),
            "by_label": dict(sorted(labels.items())),
            "by_component": dict(sorted(components.items())),
            "by_closure_decision": dict(sorted(decisions.items())),
            "issues_with_all_review_sections": sum(
                set(REQUIRED_SECTIONS) <= set(item["review"]) for item in issues
            ),
            "issues_with_unmeasured_claims": sum(bool(item["unmeasured_claims"]) for item in issues),
            "issues_with_possible_secrets": sum(bool(item["possible_secrets"]) for item in issues),
        },
        "dependency_matrix": [
            {"issue": item["number"], "depends_on_or_references": item["references"]}
            for item in issues
            if item["references"]
        ],
        "issues": issues,
    }


def _review_issue(issue: dict[str, Any], repository: str) -> dict[str, Any]:
    body = str(issue.get("body") or "").strip()
    title = str(issue.get("title") or "").strip()
    text = f"{title}\n{body}"
    labels = sorted(str(item.get("name", "")) for item in issue.get("labels", []))
    references = sorted({int(value) for value in REFERENCE.findall(text) if int(value) != issue["number"]})
    paths = sorted(set(PATH.findall(body)))
    component = _classify_component(text, labels)
    risk = _classify_risk(text, labels)
    priority = _classify_priority(text, labels)
    unmeasured = [
        line.strip()
        for line in body.splitlines()
        if MEASUREMENT_CLAIM.search(line) and not EVIDENCE_WORD.search(line)
    ]
    secrets = [pattern.pattern for pattern in SECRET_PATTERNS if pattern.search(text)]
    has_pr_or_commit = bool(re.search(r"\b(?:PR|commit|pull request)\b", body, re.IGNORECASE))
    has_tests = bool(re.search(r"\b(?:test|teste|pytest|e2e|benchmark)\b", body, re.IGNORECASE))
    has_evidence = bool(re.search(r"\b(?:evid[êe]ncia|receipt|log|trace|m[eé]trica)\b", body, re.IGNORECASE))
    close_ready = (
        issue.get("state") == "closed" and has_pr_or_commit and has_tests and has_evidence and not secrets
    )
    review = {
        "Contexto e problema": body
        or f"A issue #{issue['number']} não possui descrição; o título é a única fonte disponível.",
        "Objetivo": f"Entregar e provar o resultado delimitado por: {title}",
        "Fora de escopo": "Mudanças não necessárias ao objetivo acima, refactors oportunistas e contratos de outros projetos sem issue cruzada.",
        "Entradas, saídas e contratos": f"Entradas: corpo e metadados da issue. Saídas: implementação e evidência auditável. Contratos citados: {', '.join(paths) if paths else 'nenhum caminho explícito; identificar antes de implementar'}.",
        "Dependências e ordem": f"Referências explícitas: {', '.join('#' + str(n) for n in references) if references else 'nenhuma'}. Ordem: validar contratos atuais da main antes de editar; registrar quebra cruzada em issue vinculada.",
        "Passo a passo implementável": "1. Reproduzir ou medir o estado inicial. 2. Confirmar contrato e superfície de mudança. 3. Implementar escopo mínimo. 4. Executar os testes aplicáveis. 5. Publicar PR/commit e receipts. 6. Revisar riscos antes de decidir o fechamento.",
        "Fluxo de testes": "Unitário: regras puras e entradas inválidas. Integração: contratos entre módulos. Sistema/E2E: comando feliz e falha observável. Regressão: cenário original. Concorrência/retry/timeout/cancelamento/rollback: exercer quando o fluxo possuir esses estados. Desempenho: benchmark antes/depois para hot path; segurança: secret/PII scan e abuso de input.",
        "Critérios de aceite verificáveis": "Implementação vinculada; unit, integração, sistema/E2E e regressão verdes; cobertura medida >=85% no código tocado (90% branch quando disponível); benchmark com números quando aplicável; argumentos inválidos, falhas, timeout e rollback demonstrados ou marcados N/A com justificativa.",
        "Evidências obrigatórias": "PR e commit; comandos e logs do gate local; receipts/métricas/hashes; relatório de falhas injetadas; matriz de dependências; diff da especificação; decisão de encerramento ou bloqueio.",
        "Riscos, rollback e decisão de encerramento": "Risco: descrição original incompleta ou evidência histórica não rastreável. Rollback: reverter o commit/PR e restaurar o contrato anterior documentado. Encerrar somente com evidência verificável; caso contrário classificar SPEC, BLOCKED ou NEEDS-IMPLEMENTATION.",
    }
    return {
        "number": issue["number"],
        "url": issue.get("html_url", f"https://github.com/{repository}/issues/{issue['number']}"),
        "title": title,
        "state": issue.get("state"),
        "state_reason": issue.get("state_reason"),
        "created_at": issue.get("created_at"),
        "updated_at": issue.get("updated_at"),
        "closed_at": issue.get("closed_at"),
        "labels": labels,
        "milestone": (issue.get("milestone") or {}).get("title"),
        "references": references,
        "referenced_paths": paths,
        "classification": {
            "epic": _classify_epic(text),
            "component": component,
            "risk": risk,
            "priority": priority,
        },
        "traceability": {
            "pr_or_commit_mentioned": has_pr_or_commit,
            "tests_mentioned": has_tests,
            "evidence_mentioned": has_evidence,
        },
        "unmeasured_claims": unmeasured,
        "possible_secrets": secrets,
        "review": review,
        "closure_decision": "CLOSE-READY"
        if close_ready
        else ("NEEDS-IMPLEMENTATION" if issue.get("state") == "open" else "HISTORICAL-EVIDENCE-GAP"),
    }


def _classify_epic(text: str) -> str:
    match = re.search(r"\[(?:epic|meta)[^]]*\]", text, re.IGNORECASE)
    return match.group(0) if match else "standalone"


def _classify_component(text: str, labels: list[str]) -> str:
    lowered = " ".join(labels).lower() + " " + text.lower()
    for component, words in (
        ("runtime", ("runtime", "effectsink", "tool execution")),
        ("mapper", ("mapper", "contextsnapshot", "mapping")),
        ("plandag", ("plandag", "planner", "plan compiler")),
        ("prompt", ("prompt", "precedent", "skill")),
        ("cli", (" cli", "command", "entrypoint", "doctor")),
        ("quality", ("test", "coverage", "audit", "benchmark", "quality", "ci")),
        ("docs", ("readme", "documentation", "docs")),
    ):
        if any(word in lowered for word in words):
            return component
    return "cross-cutting"


def _classify_risk(text: str, labels: list[str]) -> str:
    lowered = " ".join(labels).lower() + " " + text.lower()
    if any(word in lowered for word in ("security", "secret", "corrupt", "breaking", "p0", "critical")):
        return "high"
    if any(word in lowered for word in ("integration", "runtime", "migration", "performance", "retry")):
        return "medium"
    return "low"


def _classify_priority(text: str, labels: list[str]) -> str:
    lowered = " ".join(labels) + " " + text
    match = re.search(r"\bP([0-3])\b", lowered, re.IGNORECASE)
    return f"P{match.group(1)}" if match else "unassigned"


def render_markdown(audit: dict[str, Any]) -> str:
    summary = audit["summary"]
    lines = [
        "# Auditoria de issues — GitHub issue #265",
        "",
        "> Relatório gerado por `python3 scripts/meta_issue_audit.py`; não editar manualmente.",
        "",
        "## Escopo, responsabilidade e limites",
        "",
        "O `simplicio-dev-cli` é a CLI determinística de desenvolvimento que consome Mapper, PlanDAG, Prompt e Runtime, preservando contratos estáveis e saída auditável. Esta auditoria especifica e classifica issues; ela não substitui implementação, resultados de testes nem evidência externa, e não declara integração ou desempenho sem medição.",
        "",
        "## Inventário",
        "",
        f"- Total: **{summary['issues_total']}**",
        f"- Estados: `{json.dumps(summary['by_state'], sort_keys=True)}`",
        f"- Decisões: `{json.dumps(summary['by_closure_decision'], sort_keys=True)}`",
        f"- SHA-256 da normalização: `{audit['source_sha256']}`",
        "",
        "## Matriz resumida",
        "",
        "| # | criada | estado | componente | risco | prioridade | decisão |",
        "|---:|---|---|---|---|---|---|",
    ]
    for item in audit["issues"]:
        lines.append(
            f"| [{item['number']}]({item['url']}) | {item['created_at'][:10]} | {item['state']} | {item['classification']['component']} | {item['classification']['risk']} | {item['classification']['priority']} | {item['closure_decision']} |"
        )
    lines.extend(["", "## Revisões normalizadas (mais antiga → mais recente)", ""])
    for item in audit["issues"]:
        lines.extend(
            [
                f"### #{item['number']} — {item['title']}",
                "",
                f"- Estado/data: `{item['state']}`; criada `{item['created_at']}`; atualizada `{item['updated_at']}`",
                f"- Labels: `{', '.join(item['labels']) or 'nenhuma'}`",
                f"- Classificação: `{json.dumps(item['classification'], ensure_ascii=False, sort_keys=True)}`",
                f"- Rastreabilidade original: `{json.dumps(item['traceability'], sort_keys=True)}`",
                f"- Decisão: **{item['closure_decision']}**",
                "",
            ]
        )
        for section in REQUIRED_SECTIONS:
            lines.extend([f"#### {section}", "", item["review"][section], ""])
    return "\n".join(line.rstrip() for line in lines).rstrip() + "\n"


def write_reports(audit: dict[str, Any], json_path: Path, markdown_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    markdown_path.write_text(render_markdown(audit), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default=DEFAULT_REPOSITORY)
    parser.add_argument("--input", type=Path, help="Offline GitHub API JSON array")
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument(
        "--check", action="store_true", help="Fail if generated reports differ from checked-in files"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    raw = json.loads(args.input.read_text(encoding="utf-8")) if args.input else fetch_issues(args.repository)
    audit = build_audit(raw, args.repository)
    expected_json = json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    expected_md = render_markdown(audit)
    if args.check:
        stale = []
        if not args.json_output.is_file() or args.json_output.read_text(encoding="utf-8") != expected_json:
            stale.append(str(args.json_output))
        if (
            not args.markdown_output.is_file()
            or args.markdown_output.read_text(encoding="utf-8") != expected_md
        ):
            stale.append(str(args.markdown_output))
        if stale:
            print("stale meta-audit reports: " + ", ".join(stale))
            return 1
        print(
            f"meta-audit current: {audit['summary']['issues_total']} issues, sha256={audit['source_sha256']}"
        )
        return 0
    write_reports(audit, args.json_output, args.markdown_output)
    print(json.dumps(audit["summary"], ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
