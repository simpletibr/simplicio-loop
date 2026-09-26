"""WI-466 Continuous Findings — finding router (dedup + canonical issue).

Routes a confirmed finding to exactly ONE canonical GitHub issue in the
responsible repository (or a local fallback store when gh/network is
unavailable). Deduplicates by fingerprint so the same root problem never
spawns duplicate issues. Links the originating loop item to the issue and
refuses to let the item be marked done while an in-scope problem is untracked.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .finding_report import emit_finding, fingerprint, SEVERITY_ENUM
from .technical_debt import is_hard_blocker

LOCAL_STORE = Path(".simplicio-loop/orchestrator/findings/issue_routes.json")


@dataclass
class RouteResult:
    finding_id: str
    fingerprint: str
    issue_ref: str
    created: bool
    updated: bool
    tracked: bool
    classification: str = "finding"
    blocking: bool = True


@dataclass
class _RouterState:
    routes: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    @staticmethod
    def load(path: Path) -> "_RouterState":
        if path.exists():
            try:
                return _RouterState(routes=json.loads(path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                return _RouterState()
        return _RouterState()

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.routes, indent=2, ensure_ascii=False), encoding="utf-8")


def _gh_available() -> bool:
    try:
        r = subprocess.run(["gh", "--version"], capture_output=True, text=True, timeout=10)
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _gh_issue_create(repo: str, title: str, body: str) -> Optional[str]:
    try:
        r = subprocess.run(
            ["gh", "issue", "create", "--repo", repo, "--title", title,
             "--body", body, "--json", "number", "--template", "{{.number}}"],
            capture_output=True, text=True, timeout=60,
        )
        if r.returncode == 0:
            return f"#{r.stdout.strip()}"
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def _gh_issue_comment(repo: str, number: str, body: str) -> bool:
    try:
        r = subprocess.run(
            ["gh", "issue", "comment", number, "--repo", repo, "--body", body],
            capture_output=True, text=True, timeout=60,
        )
        return r.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def _build_body(finding: Dict[str, Any], item_id: Optional[str]) -> str:
    lines = [
        f"## Continuous Finding ({finding.get('severity')})",
        "",
        f"- **Stage:** {finding.get('stage')}",
        f"- **Source:** {finding.get('source')}",
        f"- **Confirmed:** {finding.get('confirmed')}",
        f"- **Fingerprint:** {finding.get('fingerprint')}",
        f"- **Loop item:** {item_id or 'n/a'}",
        f"- **Classification:** {finding.get('classification') or 'finding'}",
        "",
        "### Context",
        finding.get('detail') or "(no extra detail provided)",
        "",
        "### Reproduction",
        f"1. Stage `{finding.get('stage')}` detected problem at `{finding.get('source')}`.",
        "",
        "### Cause",
        "(to be filled by resolver)",
        "",
        "### Plan",
        "1. Reproduce\n2. Root-cause\n3. Fix\n4. Test",
        "",
        "### Acceptance Criteria",
        "- [ ] Problem reproduced",
        "- [ ] Root cause identified",
        "- [ ] Fix implemented with tests",
        "",
        "### Test strategy",
        "Unit + integration covering the fixed path.",
    ]
    return "\n".join(lines)


def route_finding(
    stage: str,
    finding_id: str,
    severity: str,
    source: str,
    confirmed: bool,
    *,
    item_id: Optional[str] = None,
    repo: Optional[str] = None,
    detail: Optional[str] = None,
    state_path: Optional[str] = None,
    classification: str = "finding",
    blocking: Optional[bool] = None,
) -> RouteResult:
    """Route one finding to exactly one canonical issue (dedup by fingerprint).

    Returns RouteResult with the issue reference and whether it was created/
    updated. When gh is unavailable, falls back to a local route store so the
    finding is still tracked (never lost).
    """
    if severity not in SEVERITY_ENUM:
        raise ValueError(f"severity must be one of {SEVERITY_ENUM}, got {severity!r}")
    classification = str(classification or "finding").strip().lower()
    is_debt = classification == "technical_debt"
    effective_blocking = (not is_debt) if blocking is None else bool(blocking)
    if is_debt and effective_blocking:
        raise ValueError("technical_debt classification must be non-blocking")
    if effective_blocking and is_hard_blocker(finding_id):
        # This is intentionally not a debt downgrade; the normal finding route remains.
        classification = "finding"
    fp_base = fingerprint(stage, finding_id, source)
    fp = fp_base if classification == "finding" else fingerprint(
        stage, classification + ":" + finding_id, source
    )
    store_path = Path(state_path) if state_path else LOCAL_STORE
    state = _RouterState.load(store_path)

    if fp in state.routes:
        existing = state.routes[fp]
        # dedupe: only add a comment if new evidence arrived
        if confirmed and not existing.get("confirmed"):
            existing["confirmed"] = True
            state.save(store_path)
        return RouteResult(
            finding_id, fp, existing["issue_ref"], False, False, True,
            str(existing.get("classification") or "finding"),
            bool(existing.get("blocking", True)),
        )

    rec = emit_finding(stage, finding_id, severity, source, confirmed, detail)
    rec["classification"] = classification
    rec["blocking"] = effective_blocking
    title_prefix = "technical-debt" if is_debt else "finding"
    title = f"[{title_prefix}] {stage}: {finding_id} ({severity})"
    body = _build_body(rec, item_id)

    issue_ref = None
    created = False
    if repo and _gh_available():
        ref = _gh_issue_create(repo, title, body)
        if ref:
            issue_ref = ref
            created = True

    if issue_ref is None:
        # local fallback store (never lose the finding)
        issue_ref = f"local:{fp[:12]}"
        created = True

    state.routes[fp] = {
        "issue_ref": issue_ref,
        "finding_id": finding_id,
        "stage": stage,
        "severity": severity,
        "source": source,
        "confirmed": bool(confirmed),
        "item_id": item_id,
        "created": created,
        "classification": classification,
        "blocking": effective_blocking,
    }
    state.save(store_path)
    return RouteResult(
        finding_id, fp, issue_ref, created, False, True,
        classification, effective_blocking,
    )


def untracked_problems(item_id: Optional[str] = None, state_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return in-scope findings that are NOT yet tracked by a real issue.

    A finding is 'untracked' if its route is a local fallback (no real gh issue).
    An item must NOT be marked done while any in-scope finding is untracked.
    """
    store_path = Path(state_path) if state_path else LOCAL_STORE
    state = _RouterState.load(store_path)
    out = []
    for fp, r in state.routes.items():
        if item_id and r.get("item_id") != item_id:
            continue
        if r.get("blocking", True) is False or r.get("classification") == "technical_debt":
            continue
        if not str(r.get("issue_ref", "")).startswith("#"):
            out.append(r)
    return out


def technical_debts(item_id: Optional[str] = None, state_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return advisory technical-debt routes; these never block unrelated work."""
    store_path = Path(state_path) if state_path else LOCAL_STORE
    state = _RouterState.load(store_path)
    return [
        dict(route) for route in state.routes.values()
        if route.get("classification") == "technical_debt"
        and (not item_id or route.get("item_id") == item_id)
    ]


def completion_blocked(item_id: Optional[str] = None, state_path: Optional[str] = None) -> bool:
    """Completion gate for the loop: True while any in-scope confirmed finding
    is still untracked by a real issue.

    A loop item MUST NOT be marked done while this returns True. The
    `findings reconcile` subcommand surfaces this as a non-zero exit code.
    """
    return len(untracked_problems(item_id=item_id, state_path=state_path)) > 0


__all__ = ["route_finding", "untracked_problems", "technical_debts", "completion_blocked", "RouteResult"]
