#!/usr/bin/env python3
"""Read-only, reproducible GitHub issue specification audit (issue #647)."""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

SCHEMA = "simplicio.issue-meta-audit/v1"
SECTIONS = (
    "contexto e problema", "objetivo", "fora de escopo", "entradas, saídas e contratos",
    "dependências e ordem", "passo a passo implementável", "fluxo de testes",
    "critérios de aceite verificáveis", "evidências obrigatórias",
    "riscos, rollback e decisão de encerramento",
)
TEST_TERMS = ("caminho principal", "retry", "replay", "checkpoint", "concorrência",
              "cancelamento", "crash", "idempotência", "backpressure", "custo", "recuperação")
SECRET_PATTERNS = (
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"(?i)(?:password|senha|api[_-]?key)\s*[:=]\s*[^\s`]{8,}"),
)
MEASUREMENT_CLAIM = re.compile(r"(?i)\b(?:cobertura|coverage|performance|desempenho|economia|integração)\b")
MEASUREMENT_EVIDENCE = re.compile(r"(?i)(?:\d+(?:[.,]\d+)?\s*(?:%|ms|s|Mi?B|ops/s)|benchmark|métrica|receipt|log)")
REFERENCE = re.compile(r"(?:[\w.-]+/[\w.-]+)?#(\d+)|https://github\.com/[\w.-]+/[\w.-]+/(?:issues|pull)/(\d+)")
HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", re.MULTILINE)


def _fold(value: str) -> str:
    table = str.maketrans("áàâãäéèêëíìîïóòôõöúùûüç", "aaaaaeeeeiiiiooooouuuuc")
    return value.lower().translate(table).strip(" *:`._-")


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(value)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _safe_error(exc: BaseException) -> str:
    message = str(exc)
    for pattern in SECRET_PATTERNS:
        message = pattern.sub("[REDACTED]", message)
    return message[:500]


def fetch_issues(repo: str, *, timeout: float = 20, max_pages: int = 100,
                 opener: Callable[..., Any] = urllib.request.urlopen,
                 sleep: Callable[[float], None] = time.sleep) -> tuple[list[dict[str, Any]], list[str]]:
    """Fetch the complete REST issue collection, retrying transient responses."""
    url = f"https://api.github.com/repos/{repo}/issues?state=all&sort=created&direction=asc&per_page=100"
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "simplicio-loop-meta-audit"}
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    items: list[dict[str, Any]] = []
    errors: list[str] = []
    for page in range(1, max_pages + 1):
        response = None
        for attempt in range(4):
            try:
                response = opener(urllib.request.Request(url, headers=headers), timeout=timeout)
                break
            except urllib.error.HTTPError as exc:
                if exc.code not in (403, 429) and exc.code < 500:
                    errors.append(f"fetch page {page}: HTTP {exc.code}")
                    return items, errors
                if attempt == 3:
                    errors.append(f"fetch page {page}: HTTP {exc.code} after retries")
                    return items, errors
                sleep(min(2 ** attempt, 8))
            except (OSError, TimeoutError) as exc:
                if attempt == 3:
                    errors.append(f"fetch page {page}: {_safe_error(exc)}")
                    return items, errors
                sleep(min(2 ** attempt, 8))
        assert response is not None
        with response:
            payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, list):
                errors.append(f"fetch page {page}: response is not a list")
                return items, errors
            items.extend(item for item in payload if isinstance(item, dict))
            link = response.headers.get("Link", "")
        match = re.search(r'<([^>]+)>;\s*rel="next"', link)
        if not match:
            return items, errors
        url = match.group(1)
    errors.append(f"pagination exceeded max-pages={max_pages}")
    return items, errors


def _labels(issue: Mapping[str, Any]) -> list[str]:
    result = []
    for label in issue.get("labels", []):
        result.append(str(label.get("name", "")) if isinstance(label, Mapping) else str(label))
    return sorted(filter(None, result), key=str.casefold)


def audit_issue(issue: Mapping[str, Any]) -> dict[str, Any]:
    """Apply the objective #647 rubric to one issue without subjective scoring."""
    body = str(issue.get("body") or "")
    folded_body = _fold(body)
    headings = {_fold(value) for value in HEADING.findall(body)}
    missing = [section for section in SECTIONS if _fold(section) not in headings]
    findings = [f"missing_section:{section}" for section in missing]
    checks = {
        "all_sections": not missing,
        "numbered_steps": bool(re.search(r"(?m)^\s*(?:\d+[.)]|- \[[ xX]\])\s+", body)),
        "dependencies": "depend" in folded_body,
        "test_flow": "teste" in folded_body and all(_fold(term) in folded_body or "nao aplic" in folded_body for term in TEST_TERMS),
        "measurable_acceptance": bool(re.search(r"(?i)(?:\d+%|100%|<=|>=|≥|≤|zero|nenhum|todas?)", body)),
        "closure_evidence": bool(re.search(r"(?i)\bPR\b|pull request", body)) and "commit" in folded_body and "log" in folded_body and "evid" in folded_body,
        "measurement_backed": not MEASUREMENT_CLAIM.search(body) or bool(MEASUREMENT_EVIDENCE.search(body)),
        "no_secret_or_pii_examples": not any(pattern.search(body) for pattern in SECRET_PATTERNS),
        "rollback": "rollback" in folded_body,
        "failure_and_timeout": "falha" in folded_body and "timeout" in folded_body and ("entrada invalida" in folded_body or "entradas invalidas" in folded_body),
    }
    findings.extend(f"failed_check:{name}" for name, passed in checks.items() if not passed)
    labels = _labels(issue)
    label_text = " ".join(labels).lower()
    title = str(issue.get("title", ""))
    tags = re.findall(r"\[([^]]+)\]", title)
    priority = next((tag.upper() for tag in tags if re.fullmatch(r"P[0-3]", tag, re.I)), "unclassified")
    risk = next((label.split(":", 1)[1] for label in labels if label.lower().startswith("risk:")), "unclassified")
    component = next((label for label in labels if label.lower() in
                      {"orchestrator", "runtime", "coding-loop", "documentation", "performance", "ci", "build"}),
                     next((tag.lower() for tag in tags if not re.fullmatch(r"P[0-3]|META-AUDIT", tag, re.I)), "unclassified"))
    refs = sorted({int(a or b) for a, b in REFERENCE.findall(body) if a or b})
    epic = next((value for value in refs if value != int(issue.get("number", 0))), None)
    decision = "READY" if not findings else ("BLOCKED" if "blocked" in label_text else
               "NEEDS-IMPLEMENTATION" if str(issue.get("state")) == "closed" else "SPEC")
    return {
        "number": int(issue.get("number", 0)), "title": title,
        "state": str(issue.get("state", "unknown")), "created_at": str(issue.get("created_at", "")),
        "labels": labels, "references": refs, "checks": checks, "missing_sections": missing,
        "findings": findings, "decision": decision,
        "grouping": {"epic_reference": epic, "component": component, "risk": risk, "priority": priority},
    }


def build_report(raw_issues: Iterable[Mapping[str, Any]], *, repo: str,
                 fetch_errors: Sequence[str] = ()) -> dict[str, Any]:
    source = list(raw_issues)
    issues = sorted((audit_issue(item) for item in source if "pull_request" not in item),
                    key=lambda item: (item["created_at"], item["number"]))
    states = Counter(item["state"] for item in issues)
    labels = Counter(label for item in issues for label in item["labels"])
    grouping = {key: dict(sorted(Counter(item["grouping"][key] for item in issues).items(), key=lambda pair: str(pair[0])))
                for key in ("component", "risk", "priority")}
    conforming = sum(not item["findings"] for item in issues)
    complete = not fetch_errors and bool(issues)
    return {
        "schema": SCHEMA, "repository": repo,
        "summary": {"accessible_records": len(source), "issues": len(issues),
                    "pull_requests_excluded": len(source) - len(issues), "conforming": conforming,
                    "conformance_percent": round(100 * conforming / len(issues), 2) if issues else 0.0,
                    "by_state": dict(sorted(states.items())), "by_label": dict(sorted(labels.items())),
                    "grouping": grouping,
                    "fetch_complete": complete, "ready": complete and conforming == len(issues)},
        "fetch_errors": list(fetch_errors),
        "dependency_matrix": [{"issue": item["number"], "references": item["references"]} for item in issues],
        "issues": issues,
    }


def render_markdown(report: Mapping[str, Any]) -> str:
    summary = report["summary"]
    lines = ["# Auditoria reproduzível de issues", "", f"- Repositório: `{report['repository']}`",
             f"- Issues: **{summary['issues']}** (open/closed: `{json.dumps(summary['by_state'], sort_keys=True)}`)",
             f"- Conformidade: **{summary['conforming']}/{summary['issues']} ({summary['conformance_percent']}%)**",
             f"- Coleta completa: **{summary['fetch_complete']}**", f"- Decisão final: **{'READY' if summary['ready'] else 'BLOCKED'}**", "",
             "## Reprodução", "",
             "```bash", "python3 scripts/issue_meta_audit.py --repo simpletibr/simplicio-loop", "```", "",
             "A coleta é somente leitura, pagina todos os registros acessíveis e falha fechada quando a paginação ou qualquer item não satisfaz a rubrica. O JSON associado contém a matriz de dependências, agrupamentos, checks, achados e decisão por item.", "",
             "## Inventário (ordem de criação)", "", "| # | Estado | Criada | Decisão | Falhas |", "|---:|---|---|---|---:|"]
    for item in report["issues"]:
        lines.append(f"| {item['number']} | {item['state']} | {item['created_at']} | {item['decision']} | {len(item['findings'])} |")
    lines.extend(["", "## Erros de coleta", ""] + ([f"- `{error}`" for error in report["fetch_errors"]] or ["- Nenhum."]))
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default="simpletibr/simplicio-loop")
    parser.add_argument("--input", type=Path)
    parser.add_argument("--json-out", type=Path, default=Path("docs/audits/issues-meta-audit.json"))
    parser.add_argument("--markdown-out", type=Path, default=Path("docs/audits/issues-meta-audit.md"))
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--max-pages", type=int, default=100)
    args = parser.parse_args(argv)
    if args.input:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        raw, errors = (payload["items"], payload.get("errors", [])) if isinstance(payload, dict) else (payload, [])
    else:
        raw, errors = fetch_issues(args.repo, timeout=args.timeout, max_pages=args.max_pages)
    report = build_report(raw, repo=args.repo, fetch_errors=errors)
    _atomic_json(args.json_out, report)
    _atomic_text(args.markdown_out, render_markdown(report))
    print(json.dumps(report["summary"], sort_keys=True))
    return 0 if report["summary"]["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
