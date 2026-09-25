#!/usr/bin/env python3
"""Build a deterministic, replayable audit of every GitHub issue in a repository."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

SCHEMA = "simplicio.meta-issue-audit/v1"
REQUIRED_SECTIONS = [
    "context_and_problem",
    "objective",
    "out_of_scope",
    "inputs_outputs_contracts",
    "dependencies_and_order",
    "implementation_steps",
    "test_flow",
    "verifiable_acceptance_criteria",
    "mandatory_evidence",
    "risks_rollback_and_closure",
]
_SECRET_PATTERNS = (
    re.compile(r"(?i)(?:token|password|secret|api[_-]?key)\s*[=:]\s*\S+"),
    re.compile(r"\b(?:gh[opusr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
)
_CROSS_REPO_REF = re.compile(r"https://github\.com/([^/\s]+/[^/\s]+)/issues/(\d+)", re.I)
_LOCAL_REF = re.compile(r"(?<![\w/])#(\d+)\b")
_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.M)
_PR_REF = re.compile(r"https://github\.com/([^/\s]+/[^/\s]+)/pull/(\d+)", re.I)
_COMMIT_REF = re.compile(r"https://github\.com/([^/\s]+/[^/\s]+)/commit/([0-9a-f]{7,40})", re.I)


def _redact(value: str) -> tuple[str, bool]:
    changed = False
    for pattern in _SECRET_PATTERNS:
        value, count = pattern.subn("[REDACTED]", value)
        changed = changed or count > 0
    return value, changed


def _digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _section(body: str, names: tuple[str, ...]) -> str | None:
    matches = list(_HEADING.finditer(body))
    for index, match in enumerate(matches):
        normalized = re.sub(r"[^a-z0-9]+", " ", match.group(1).casefold()).strip()
        if any(name in normalized for name in names):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
            content = body[match.end() : end].strip()
            if content:
                return content
    return None


def _test_flow(number: int) -> list[dict[str, str]]:
    return [
        {"layer": "unit", "scenario": "Validate isolated rules with valid, invalid, empty, and boundary inputs."},
        {"layer": "integration", "scenario": "Exercise affected contracts and dependencies without replacing internal code with mocks."},
        {"layer": "system", "scenario": "Replay the observable flow on both a small and a large repository fixture."},
        {"layer": "regression", "scenario": f"Preserve the failure or requirement reported by issue #{number}."},
        {"layer": "state", "scenario": "Cover incremental changes, branch/SHA identity, removed files, cache cold/warm, and incompatible schemas."},
        {"layer": "concurrency", "scenario": "Exercise concurrent work, cancellation, timeout, retry, and idempotent recovery where applicable."},
        {"layer": "performance", "scenario": "For hot paths, record fixture size, warmups, samples, percentiles, baseline, and regression threshold."},
        {"layer": "security", "scenario": "Use invalid and adversarial input; prove logs and artifacts contain no secrets, PII, or private source."},
        {"layer": "reproduction", "scenario": "Publish a local or container command that does not require paid GitHub Actions."},
    ]


def _classification(issue: dict[str, Any]) -> dict[str, str]:
    labels = " ".join(
        str(label.get("name", "")) if isinstance(label, dict) else str(label)
        for label in issue.get("labels", [])
    ).casefold()
    title = str(issue.get("title") or "").casefold()
    text = f"{labels} {title}"
    priority = next((value.upper() for value in ("p0", "p1", "p2", "p3") if value in text), "UNSPECIFIED")
    risk = "high" if any(value in text for value in ("security", "release", "contract", "breaking")) else "standard"
    component = next(
        (value for value in ("mapper", "runtime", "cli", "agent", "docs", "ci", "benchmark") if value in text),
        "unclassified",
    )
    epic = "meta-audit" if "meta-audit" in text or "auditoria" in text else "unassigned"
    return {"epic": epic, "component": component, "risk": risk, "priority": priority}


def _associations(body: str) -> dict[str, list[str]]:
    return {
        "pull_requests": sorted({f"https://github.com/{repo}/pull/{number}" for repo, number in _PR_REF.findall(body)}),
        "commits": sorted({f"https://github.com/{repo}/commit/{sha}" for repo, sha in _COMMIT_REF.findall(body)}),
        "branches": [],
        "files": [],
        "tests": [],
        "projects": sorted({repo for repo, _number in _CROSS_REPO_REF.findall(body)}),
    }


def _review_markdown(review: dict[str, Any]) -> str:
    headings = {
        "context_and_problem": "Contexto e problema",
        "objective": "Objetivo",
        "out_of_scope": "Fora de escopo",
        "inputs_outputs_contracts": "Entradas, saídas e contratos",
        "dependencies_and_order": "Dependências e ordem",
        "implementation_steps": "Passo a passo implementável",
        "test_flow": "Fluxo de testes",
        "verifiable_acceptance_criteria": "Critérios de aceite verificáveis",
        "mandatory_evidence": "Evidências obrigatórias",
        "risks_rollback_and_closure": "Riscos, rollback e decisão de encerramento",
    }
    sections = []
    for key in REQUIRED_SECTIONS:
        value = review[key]
        if key == "test_flow":
            content = "\n".join(f"- **{item['layer']}** — {item['scenario']}" for item in value)
        elif isinstance(value, list):
            content = "\n".join(f"- {item}" for item in value)
        else:
            content = str(value)
        sections.append(f"## {headings[key]}\n\n{content}")
    return "\n\n".join(sections) + "\n"


def _review(issue: dict[str, Any], body: str, dependencies: dict[str, Any]) -> dict[str, Any]:
    number = int(issue["number"])
    title = str(issue.get("title") or f"Issue #{number}")
    context = _section(body, ("context", "problema", "problem")) or (
        f"The original issue requests: {title}. The original body is preserved by its SHA-256 digest; "
        "claims without executable evidence remain unverified."
    )
    objective = _section(body, ("objetivo", "objective", "goal")) or (
        f"Deliver and verify the observable outcome named by issue #{number}: {title}."
    )
    out_scope = _section(body, ("fora de escopo", "out of scope", "non goal")) or (
        "Unrelated refactors, unmeasured optimization claims, dependency releases, and changes to contracts not named by this issue."
    )
    contracts = _section(body, ("entradas", "inputs", "contract", "contrato")) or (
        "Inputs are the issue's declared reproducer and repository state; outputs are the reviewed code/docs, tests, "
        "versioned artifacts, and evidence. Any public schema change requires compatibility fixtures and migration notes."
    )
    dep_text = (
        f"Local issue references: {dependencies['local_issues'] or 'none declared'}; cross-repository references: "
        f"{dependencies['cross_repository'] or 'none declared'}. Resolve blocking contracts before implementation, "
        "then validate consumers before closure."
    )
    steps = [
        "1. Reproduce or restate the current behavior against the current default branch.",
        "2. Identify affected contracts, dependencies, files, tests, and rollback boundary.",
        "3. Add a failing regression or contract test before the smallest scoped change.",
        "4. Implement the change and exercise failure, timeout, invalid-input, cancellation, and recovery paths that apply.",
        "5. Run lint, unit, integration, system, coverage, security, and measured performance checks that apply.",
        "6. Attach commit/PR links, commands, logs, hashes, artifacts, metrics, residual risks, and the closure decision.",
    ]
    acceptance = [
        "1. The stated objective is observable through a deterministic command or artifact assertion.",
        "2. Applicable happy-path and failure-path tests pass, including invalid input, timeout, and rollback/recovery.",
        "3. Touched production code has measured coverage >=85% and branch coverage targets 90% when available.",
        "4. Performance, savings, coverage, and integration claims include raw measurements and fixture metadata.",
        "5. Public contracts remain compatible or publish a versioned migration with cross-project references.",
        "6. Logs and examples contain no secrets, PII, credentials, or private source content.",
    ]
    evidence = [
        "PR and commit SHA linked to the issue",
        "exact local/container commands with exit status and relevant logs",
        "test, coverage, and injected-failure results",
        "artifact and input SHA-256 hashes plus versioned receipts",
        "benchmark samples and baseline when a hot path changes",
        "dependency matrix, residual risks, rollback command, and explicit close/block decision",
    ]
    return {
        "context_and_problem": context,
        "objective": objective,
        "out_of_scope": out_scope,
        "inputs_outputs_contracts": contracts,
        "dependencies_and_order": dep_text,
        "implementation_steps": steps,
        "test_flow": _test_flow(number),
        "verifiable_acceptance_criteria": acceptance,
        "mandatory_evidence": evidence,
        "risks_rollback_and_closure": (
            "Rollback by reverting the focused commit and restoring the prior contract/artifact version. Keep open as SPEC, "
            "BLOCKED, or NEEDS-IMPLEMENTATION until implementation, evidence, dependency validation, and residual-risk review are complete."
        ),
    }


def build_audit(rows: list[dict[str, Any]], *, repository: str) -> dict[str, Any]:
    if not isinstance(rows, list):
        raise ValueError("issue export must be a JSON array")
    issues = [row for row in rows if isinstance(row, dict) and "pull_request" not in row]
    seen: set[int] = set()
    normalized = []
    redaction_count = 0
    for raw in sorted(issues, key=lambda item: (str(item.get("created_at", "")), int(item.get("number", 0)))):
        if "number" not in raw or "state" not in raw or "created_at" not in raw:
            raise ValueError("every issue requires number, state, and created_at")
        number = int(raw["number"])
        if number in seen:
            raise ValueError(f"duplicate issue number: {number}")
        seen.add(number)
        original_body = str(raw.get("body") or "")
        body, redacted = _redact(original_body)
        redaction_count += int(redacted)
        cross_refs = sorted(set(_CROSS_REPO_REF.findall(body)))
        cross_urls = [f"https://github.com/{repo}/issues/{ref}" for repo, ref in cross_refs if repo.casefold() != repository.casefold()]
        local = sorted({int(ref) for ref in _LOCAL_REF.findall(body) if int(ref) != number})
        for repo, ref in cross_refs:
            if repo.casefold() == repository.casefold() and int(ref) != number:
                local.append(int(ref))
        dependencies = {"local_issues": sorted(set(local)), "cross_repository": sorted(set(cross_urls))}
        state = str(raw["state"]).lower()
        review = _review(raw, body, dependencies)
        labels = sorted(
            str(label.get("name", "")) if isinstance(label, dict) else str(label)
            for label in raw.get("labels", [])
        )
        normalized.append(
            {
                "number": number,
                "state": state,
                "created_at": raw["created_at"],
                "updated_at": raw.get("updated_at"),
                "closed_at": raw.get("closed_at"),
                "title": str(raw.get("title") or ""),
                "url": raw.get("html_url"),
                "labels": labels,
                "author": (raw.get("user") or {}).get("login") if isinstance(raw.get("user"), dict) else None,
                "original_body_sha256": _digest(original_body),
                "review_body_sha256": _digest(json.dumps(review, ensure_ascii=False, sort_keys=True)),
                "dependencies": dependencies,
                "classification": _classification(raw),
                "associations": _associations(body),
                "test_flow": _test_flow(number),
                "evidence": {"required": review["mandatory_evidence"], "observed_in_export": []},
                "security": {"redactions_applied": redacted},
                "closure_decision": "KEEP_OPEN" if state == "open" else "REVIEW_CLOSED",
                "review": review,
                "proposed_body": _review_markdown(review),
            }
        )
    states = {"open": 0, "closed": 0}
    for issue in normalized:
        states[issue["state"]] = states.get(issue["state"], 0) + 1
    canonical_source = json.dumps(issues, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    dependency_matrix = [
        {
            "number": item["number"],
            "local_issues": item["dependencies"]["local_issues"],
            "cross_repository": item["dependencies"]["cross_repository"],
        }
        for item in normalized
        if item["dependencies"]["local_issues"] or item["dependencies"]["cross_repository"]
    ]
    return {
        "schema": SCHEMA,
        "repository": repository,
        "source_sha256": _digest(canonical_source),
        "summary": {"total": len(normalized), "open": states.get("open", 0), "closed": states.get("closed", 0)},
        "redacted_issue_count": redaction_count,
        "required_sections": REQUIRED_SECTIONS,
        "dependency_matrix": dependency_matrix,
        "issues": normalized,
    }


def fetch_issues(repository: str, *, timeout: float = 20.0) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for page in range(1, 101):
        query = urllib.parse.urlencode(
            {"state": "all", "per_page": 100, "page": page, "sort": "created", "direction": "asc"}
        )
        request = urllib.request.Request(
            f"https://api.github.com/repos/{repository}/issues?{query}",
            headers={"Accept": "application/vnd.github+json", "User-Agent": "simplicio-mapper-meta-audit"},
        )
        try:
            # The URL is constructed above with a fixed HTTPS GitHub API origin.
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
                page_rows = json.load(response)
        except (OSError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"GitHub issue fetch failed on page {page}: {exc}") from exc
        if not isinstance(page_rows, list):
            raise RuntimeError(f"GitHub issue fetch returned a non-array on page {page}")
        rows.extend(page_rows)
        if len(page_rows) < 100:
            return rows
    raise RuntimeError("GitHub issue pagination exceeded 100 pages")


def _serialized(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reproducible repository-wide GitHub issue meta-audit.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", type=Path, help="GitHub issues API JSON export.")
    source.add_argument("--fetch", action="store_true", help="Fetch all issue pages from the public GitHub API.")
    parser.add_argument("--repository", default="wesleysimplicio/simplicio-mapper")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--check", action="store_true", help="Fail if output differs; never write.")
    args = parser.parse_args(argv)
    try:
        if args.input:
            rows = json.loads(args.input.read_text(encoding="utf-8"))
        else:
            rows = fetch_issues(args.repository, timeout=args.timeout)
        payload = build_audit(rows, repository=args.repository)
        rendered = _serialized(payload)
        if args.check:
            current = args.output.read_text(encoding="utf-8") if args.output.is_file() else ""
            if current != rendered:
                print(f"audit output is out of date: {args.output}", file=sys.stderr)
                return 1
            print(f"audit output is current: {args.output} ({payload['summary']['total']} issues)")
            return 0
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
        print(f"wrote {args.output} ({payload['summary']['total']} issues)")
        return 0
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"meta-issue-audit: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
