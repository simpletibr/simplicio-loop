"""GitHub issue lifecycle adapter (#285) — one canonical, idempotent status comment.

Issue #285 asks for the full GitHub source adapter: `list_ready`/`get_details`/
`claim`/`update_status`/`attach_evidence`/`close`/`requery`/`reconcile`, an
outbox, lease/fencing integration, and duplicate-comment recovery. This module
reuses rather than duplicates prior work: `#295` already built a fail-closed,
idempotent, marker-based create-or-update primitive
(`scripts/pr_evidence.py::publish_comment`/`find_existing_comment` — no shell
interpolation, JSON payload on stdin, `PublishError` on any `gh` failure). On
top of that primitive this module adds:

  * a minimal, VALIDATED lifecycle state machine (`LIFECYCLE_STATES`,
    `validate_transition`) — an event that isn't a legal transition from the
    current state is rejected with a reason code, never silently accepted;
  * a deterministic, sanitized renderer for the canonical status comment
    (`render_lifecycle_comment`), using ITS OWN marker
    (`<!-- simplicio-loop:lifecycle-status:v1 -->`), distinct from the #295
    evidence-comment marker `PR_EVIDENCE_COMMENT_MARKER` so the two never
    collide when both happen to be searched for on the same issue. The two
    markers being distinct constants does NOT mean two active comments: since
    `scripts/pr_evidence.py::publish_evidence_via_lifecycle` was added, the
    evidence-comment CALLER (`cmd_comment --publish`) delegates through THIS
    module's `publish_lifecycle_state` and lands on the SAME canonical
    comment as `claim`/`PLANNED` — `PR_EVIDENCE_COMMENT_MARKER` now only
    matters as the underlying idempotent-primitive's own default marker
    parameter, not as a second comment on the issue;
  * `publish_lifecycle_state`: publish (create-or-update, idempotent, via the
    #295 primitive) THEN immediately re-query the same comment and compare the
    observed body hash against the expected one — the issue's "só retornar
    sucesso se o ID e body hash observados coincidirem" requirement — producing
    a `simplicio.github-lifecycle-receipt/v1` receipt rather than a bare bool.
    It now also accepts an optional `require_active` callable (typically
    a lease/fence check, #183) invoked immediately before the
    remote write — a stale/lost lease raises and blocks the write, never
    silently proceeds — and an optional `outbox_dir` so a pending-operation
    record is persisted BEFORE the remote call and only cleared after the
    write is confirmed by re-query (crash-after-POST recovery, see
    `reconcile`);
  * `list_ready`/`get_details`/`requery` — real, paginated read-side verbs
    against `gh api`, metadata-only for `list_ready` (never fetching bodies/
    comments during triage), full paginated comments + a deterministic
    `source_revision` hash (excluding the adapter's own canonical comment) for
    `get_details`;
  * a lightweight outbox (`record_pending_operation`/`mark_operation_done`/
    `list_pending_operations`) and `reconcile(operation_id)` that re-queries
    the source and the marker-tagged comment to recover a crash between a
    confirmed remote write and the local receipt, without ever posting a
    second comment;
  * `close_source_issue`: real `gh issue close` wiring, fail-closed — the
    issue is only reported closed after a post-close re-query confirms
    `state == "closed"`, and a close that succeeds remotely but whose final
    comment update cannot be confirmed reports `CLOSE_PENDING_RECONCILIATION`
    (kept in the outbox for `reconcile`) instead of a fake success.

Still out of scope for this increment (tracked, not claimed done):
`claim`/`update_status`/`attach_evidence` as a single unified `Protocol`
class (the equivalent operations exist today as free functions plus the
runner wiring in `simplicio_loop/runner.py::_sync_github_lifecycle` --
see `simplicio_loop/source_adapter.py` for the formal `Protocol`, added
separately).

## Duplicate-comment election (#285 "Recuperação de duplicatas")

The normal path never produces a duplicate: `publish_lifecycle_state` always
create-or-updates via the marker, guarded by the lease. But a legacy comment
from before this system existed, or a race that landed two POSTs before the
lease fully serialized writers, can still leave two-or-more marker-tagged
comments on the same issue. `reconcile_duplicate_comments` recovers from that:

  * paginate every comment and collect every one carrying
    `LIFECYCLE_COMMENT_MARKER` (`find_marker_comments`);
  * elect ONE canonical comment deterministically -- lowest comment `id` wins
    (`elect_canonical_comment`), matching `get_details`'s own canonical-comment
    rule so the two never disagree;
  * every OTHER marker-tagged comment is a duplicate. For each one,
    `mark_comment_superseded` edits it to append a `SUPERSEDED` banner --
    but ONLY when its author matches the adapter's own authenticated login
    (`get_authenticated_login`). A duplicate authored by a different login
    (another human, another bot, another actor entirely) is left completely
    untouched and reported as `skipped_foreign_author` -- "nunca editar/apagar
    comentário de outro usuário" is absolute, not best-effort;
  * marking is itself idempotent: a comment that already carries the
    `SUPERSEDED` banner is left alone (`already_superseded`), so re-running
    reconciliation never appends the banner twice.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from . import freshness
from . import source_snapshot as _source_snapshot

LIFECYCLE_SCHEMA = "simplicio.github-lifecycle-receipt/v1"
SNAPSHOT_SCHEMA = "simplicio.github-source-snapshot/v1"
LIST_READY_SCHEMA = "simplicio.github-list-ready/v1"
DUPLICATE_ELECTION_SCHEMA = "simplicio.github-duplicate-election/v1"
LIFECYCLE_COMMENT_MARKER = "<!-- simplicio-loop:lifecycle-status:v1 -->"
SUPERSEDED_MARKER = "<!-- simplicio-loop:lifecycle-status:superseded/v1 -->"
SUPERSEDED_BANNER = (
    "\n> ⚠️ **SUPERSEDED** — a newer canonical status comment now "
    "tracks this issue's Simplicio Loop lifecycle; this one is kept for audit "
    "only and is no longer updated.\n" + SUPERSEDED_MARKER
)

# #285 "Definir reason codes no mínimo para": the minimum set the issue enumerates.
REASON_CODES = frozenset({
    "AUTH_REQUIRED", "PERMISSION_DENIED", "RATE_LIMITED", "NETWORK_UNAVAILABLE",
    "SOURCE_NOT_FOUND", "SOURCE_CLOSED", "SOURCE_CHANGED", "CLAIM_CONFLICT",
    "LEASE_LOST", "FENCE_MISMATCH", "COMMENT_NOT_FOUND", "COMMENT_AUTHOR_MISMATCH",
    "COMMENT_HASH_MISMATCH", "REMOTE_WRITE_UNCONFIRMED", "EVIDENCE_INCOMPLETE",
    "DELIVERY_PENDING", "CLOSE_PENDING_RECONCILIATION",
    # additions this increment needed in practice:
    "SOURCE_CLOSE_FAILED", "SOURCE_CLOSE_UNCONFIRMED", "OPERATION_NOT_FOUND",
})


class GitHubTransportError(RuntimeError):
    """A `gh` invocation failed or returned unparsable data. Carries a typed reason_code."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code if reason_code in REASON_CODES else "NETWORK_UNAVAILABLE"


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _classify_gh_failure(returncode: int, stderr: str) -> str:
    """Best-effort HTTP/CLI status -> reason_code mapping (#285 "401/403/404/... devem
    ser diferenciados")."""
    text = (stderr or "").lower()
    for code, reason in (
        ("401", "AUTH_REQUIRED"), ("403", "PERMISSION_DENIED"), ("404", "SOURCE_NOT_FOUND"),
        ("409", "CLAIM_CONFLICT"), ("422", "SOURCE_CHANGED"), ("429", "RATE_LIMITED"),
    ):
        if code in text:
            return reason
    if "rate limit" in text:
        return "RATE_LIMITED"
    if "could not resolve host" in text or "timeout" in text or "connection" in text:
        return "NETWORK_UNAVAILABLE"
    return "NETWORK_UNAVAILABLE"


def _paginated_gh_api(path_base: str, *, runner: Callable, timeout: int,
                      per_page: int = 100, max_pages: int = 50) -> List[Dict[str, Any]]:
    """GET every page of a `gh api` list endpoint, in order. #285: "paginação completa"."""
    items: List[Dict[str, Any]] = []
    page = 1
    while page <= max_pages:
        sep = "&" if "?" in path_base else "?"
        url = f"{path_base}{sep}per_page={per_page}&page={page}"
        completed = runner(["gh", "api", url], capture_output=True, text=True, timeout=timeout, check=False,
                          encoding="utf-8", errors="replace")
        if completed.returncode != 0:
            raise GitHubTransportError(_classify_gh_failure(completed.returncode, completed.stderr),
                                       "gh api %s failed: %s" % (url, (completed.stderr or "").strip()))
        try:
            batch = json.loads(completed.stdout or "[]")
        except ValueError as exc:
            raise GitHubTransportError("NETWORK_UNAVAILABLE", "gh api returned non-JSON page: %s" % exc)
        if not isinstance(batch, list):
            batch = []
        items.extend(batch)
        if len(batch) < per_page:
            break
        page += 1
    return items

# #285 "Estados mínimos"
LIFECYCLE_STATES: Tuple[str, ...] = (
    "DISCOVERED",
    "CLAIMED",
    "PLANNED",
    "IN_PROGRESS",
    "VERIFYING",
    "BLOCKED",
    "PAUSED_NETWORK",
    "AWAITING_DECISION",
    "PR_OPEN",
    "MERGE_READY",
    "MERGED",
    "CLOSING",
    "CLOSE_PENDING_RECONCILIATION",
    "CLOSED",
    "RELEASED",
)

# Forward-flow transitions (the "happy path" the issue's ASCII diagram describes,
# plus the terminal/side states every stage can fall into). Regressions (e.g.
# PR_OPEN -> IN_PROGRESS) are only ever valid with an explicit reason_code, never
# as a bare state hop -- see `validate_transition`.
_FORWARD_TRANSITIONS: Dict[str, Sequence[str]] = {
    "DISCOVERED": ("CLAIMED",),
    "CLAIMED": ("PLANNED", "BLOCKED", "PAUSED_NETWORK"),
    "PLANNED": ("IN_PROGRESS", "AWAITING_DECISION", "BLOCKED", "PAUSED_NETWORK"),
    "IN_PROGRESS": ("VERIFYING", "BLOCKED", "PAUSED_NETWORK", "AWAITING_DECISION"),
    "VERIFYING": ("PR_OPEN", "BLOCKED", "AWAITING_DECISION"),
    "PR_OPEN": ("MERGE_READY", "BLOCKED", "AWAITING_DECISION"),
    "MERGE_READY": ("MERGED", "BLOCKED"),
    "MERGED": ("CLOSING",),
    "CLOSING": ("CLOSED", "CLOSE_PENDING_RECONCILIATION"),
    "CLOSE_PENDING_RECONCILIATION": ("CLOSED",),
    "CLOSED": ("RELEASED",),
    # side states can resume forward once the blocker clears
    "BLOCKED": ("IN_PROGRESS", "PLANNED", "AWAITING_DECISION"),
    "PAUSED_NETWORK": ("CLAIMED", "PLANNED", "IN_PROGRESS"),
    "AWAITING_DECISION": ("PLANNED", "IN_PROGRESS", "VERIFYING", "BLOCKED"),
    "RELEASED": (),
}

# Reason codes that authorize an explicit REGRESSION (a hop not in
# `_FORWARD_TRANSITIONS`) -- per the issue: "Regressões de estado só são
# permitidas com reason code explícito".
REGRESSION_REASON_CODES = frozenset({
    "SOURCE_CHANGED", "CHECKS_REGRESSED", "REVIEW_REOPENED", "LEASE_REASSIGNED",
    "DELIVERY_REGRESSED",
})


def validate_transition(from_state: str, to_state: str, *, reason_code: str = "") -> Dict[str, Any]:
    """Validate one lifecycle transition. Never raises; returns a structured verdict.

    A duplicate event (to_state == from_state) is a no-op, always valid --
    "Eventos duplicados são no-op idempotente" per the issue text.
    """
    if from_state not in LIFECYCLE_STATES:
        return {"ok": False, "reason_code": "unknown_from_state", "reason": f"unknown state {from_state!r}"}
    if to_state not in LIFECYCLE_STATES:
        return {"ok": False, "reason_code": "unknown_to_state", "reason": f"unknown state {to_state!r}"}
    if to_state == from_state:
        return {"ok": True, "reason_code": "duplicate_noop", "reason": "duplicate event, no-op"}
    if to_state in _FORWARD_TRANSITIONS.get(from_state, ()):
        return {"ok": True, "reason_code": "transition_valid", "reason": f"{from_state} -> {to_state} is a valid forward transition"}
    if reason_code in REGRESSION_REASON_CODES:
        return {"ok": True, "reason_code": reason_code, "reason": f"{from_state} -> {to_state} authorized as a regression ({reason_code})"}
    return {"ok": False, "reason_code": "transition_invalid",
            "reason": f"{from_state} -> {to_state} is not a valid forward transition and no regression reason_code was given"}


def _redact(text: str) -> str:
    """Best-effort redaction of anything that looks like a secret/token before it
    ever reaches a public GitHub comment -- #285's "sem segredos" principle."""
    import re

    text = re.sub(r"(gh[pousr]_[A-Za-z0-9]{20,})", "[REDACTED-TOKEN]", text)
    text = re.sub(r"(?i)(api[_-]?key|token|secret|password)\s*[:=]\s*\S+", r"\1: [REDACTED]", text)
    return text


def render_lifecycle_comment(
    *,
    state: str,
    run_id: str,
    attempt_id: str,
    agent_id: str = "",
    runtime: str = "",
    device: str = "",
    lease_id: str = "",
    fencing_token: str = "",
    branch: str = "",
    worktree: str = "",
    updated_at: str = "",
    goal: str = "",
    scope: str = "",
    acceptance_criteria: Optional[Sequence[Mapping[str, Any]]] = None,
    plan_steps: Optional[Sequence[str]] = None,
    progress: str = "",
    blockers: Optional[Sequence[str]] = None,
    tests_and_evidence: str = "",
    delivery: str = "",
) -> str:
    """Deterministic renderer for the ONE canonical status comment (#285).

    Every field is sanitized (`_redact`) before rendering -- a secret or a raw
    stack trace in an upstream field must never reach the public comment.
    """
    if state not in LIFECYCLE_STATES:
        raise ValueError(f"unknown lifecycle state: {state!r}")
    acs = list(acceptance_criteria or [])
    steps = list(plan_steps or [])
    blocked = list(blockers or [])

    lines: List[str] = []
    lines.append("## \U0001F501 Simplicio Loop — status da execução")
    lines.append("")
    lines.append("| Campo | Valor |")
    lines.append("|---|---|")
    lines.append(f"| Estado | {state} |")
    lines.append(f"| Run / attempt | {run_id} / {attempt_id} |")
    if agent_id:
        lines.append(f"| Agente | {agent_id} |")
    if runtime or device:
        lines.append(f"| Runtime / device | {runtime} / {device} |")
    if lease_id or fencing_token:
        lines.append(f"| Lease / fence | {lease_id} / {fencing_token} |")
    if branch or worktree:
        lines.append(f"| Branch / worktree | {branch} / {worktree} |")
    if updated_at:
        lines.append(f"| Atualizado | {updated_at} |")
    lines.append("")

    if goal or scope:
        lines.append("### Objetivo e escopo")
        if goal:
            lines.append(goal)
        if scope:
            lines.append(scope)
        lines.append("")

    if acs:
        lines.append("### Critérios de aceite")
        for ac in acs:
            ac_id = str(ac.get("id") or "").strip()
            text = str(ac.get("text") or "").strip()
            done = bool(ac.get("done"))
            box = "x" if done else " "
            label = f"**{ac_id}** " if ac_id else ""
            lines.append(f"- [{box}] {label}{text}".rstrip())
        lines.append("")

    if steps:
        lines.append("### Plano passo a passo")
        for idx, step in enumerate(steps, start=1):
            lines.append(f"{idx}. {step}")
        lines.append("")

    if progress or blocked:
        lines.append("### Progresso e blockers")
        if progress:
            lines.append(progress)
        for b in blocked:
            lines.append(f"- BLOCKER: {b}")
        lines.append("")

    if tests_and_evidence:
        lines.append("### Testes e evidências")
        lines.append(tests_and_evidence)
        lines.append("")

    if delivery:
        lines.append("### Entrega")
        lines.append(delivery)
        lines.append("")

    lines.append(LIFECYCLE_COMMENT_MARKER)
    body = "\n".join(lines).rstrip() + "\n"
    return _redact(body)


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


LIFECYCLE_RECEIPT_FILENAME = "github-lifecycle-receipt.json"


def lifecycle_receipt_path(run_dir: str | Path) -> Path:
    return Path(run_dir) / LIFECYCLE_RECEIPT_FILENAME


def persist_lifecycle_receipt(receipt: Mapping[str, Any], run_dir: str | Path) -> str:
    """Persist the latest lifecycle receipt into the run directory (#285: oracle/COMPLETE-gate
    integration). This is what lets `simplicio_loop.oracle.evaluate_completion` see
    `CLOSE_PENDING_RECONCILIATION` and block "done" instead of it being an inert status only
    ever visible in the GitHub comment/outbox. Atomic write via temp-file rename."""
    directory = Path(run_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = lifecycle_receipt_path(directory)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(dict(receipt), ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return str(path)


def load_lifecycle_receipt(run_dir: str | Path) -> Optional[Dict[str, Any]]:
    """Load the last-persisted lifecycle receipt for a run, or `None` if no lifecycle sync/close
    has ever persisted one for this run directory (a source-less run, or a run predating this
    integration -- both must be treated as "no opinion", never as a block)."""
    path = lifecycle_receipt_path(run_dir)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def operation_id(*, provider: str, repo: str, issue: str, run_id: str, attempt_id: str,
                 fencing_token: str, lifecycle_revision: int, operation_kind: str) -> str:
    """Deterministic operation id (#285's idempotency-key tuple)."""
    payload = {
        "provider": provider, "repo": repo, "issue": str(issue), "run_id": run_id,
        "attempt_id": attempt_id, "fencing_token": fencing_token,
        "lifecycle_revision": int(lifecycle_revision), "operation_kind": operation_kind,
    }
    return content_hash(json.dumps(payload, sort_keys=True, ensure_ascii=False))


def list_ready(
    owner: str,
    repo: str,
    *,
    state: str = "open",
    labels: Sequence[str] = (),
    assignee: str = "",
    milestone: str = "",
    runner: Callable = subprocess.run,
    timeout: int = 20,
) -> Dict[str, Any]:
    """`list_ready` (#285): metadata-only triage listing, paginated, deterministic order.

    Filters explicit state/labels/assignee/milestone at the query level (not fetched
    then filtered client-side, so triage never over-fetches). GitHub's issues list
    endpoint also returns pull requests -- every item carrying a `pull_request` key is
    dropped so a PR is never returned as an executable issue by mistake. Bodies and
    comments are never requested here; only the metadata list-ready needs.
    """
    path = f"repos/{owner}/{repo}/issues?state={state}&sort=created&direction=asc"
    if labels:
        path += "&labels=" + ",".join(str(l) for l in labels)
    if assignee:
        path += f"&assignee={assignee}"
    if milestone:
        path += f"&milestone={milestone}"
    raw_items = _paginated_gh_api(path, runner=runner, timeout=timeout)
    ready = [item for item in raw_items if isinstance(item, dict) and "pull_request" not in item]
    ready.sort(key=lambda item: int(item.get("number") or 0))
    summaries = [{
        "number": item.get("number"),
        "title": item.get("title", ""),
        "state": item.get("state", ""),
        "labels": [l.get("name") for l in (item.get("labels") or []) if isinstance(l, dict)],
        "assignees": [a.get("login") for a in (item.get("assignees") or []) if isinstance(a, dict)],
        "milestone": (item.get("milestone") or {}).get("title", "") if isinstance(item.get("milestone"), dict) else "",
        "updated_at": item.get("updated_at", ""),
        "url": item.get("html_url", ""),
    } for item in ready]
    return {
        "schema": LIST_READY_SCHEMA,
        "provider": "github",
        "repo": f"{owner}/{repo}",
        "query": {"state": state, "labels": list(labels), "assignee": assignee, "milestone": milestone},
        "items": summaries,
        "count": len(summaries),
        "pages_fetched": max(1, -(-len(raw_items) // 100)) if raw_items else 1,
        "observed_at": _now_iso(),
    }


def get_details(owner: str, repo: str, issue: str, *, runner: Callable = subprocess.run,
                timeout: int = 20) -> Dict[str, Any]:
    """`get_details` (#285): full paginated issue + comments, canonical comment separated.

    Loads title/body/state/state_reason/labels/assignees/milestone/author/timestamps,
    then paginates ALL comments. The Loop's own `LIFECYCLE_COMMENT_MARKER` comment is
    identified and excluded from `source_revision` (self-drift guard: the adapter's own
    progress writes must never look like a material human edit), while every OTHER
    comment counts toward the revision hash. All issue/comment text is treated as
    untrusted data, never as instructions -- callers must not execute anything found
    inside `title`/`body`/comment text.
    """
    completed = runner(["gh", "api", f"repos/{owner}/{repo}/issues/{issue}"],
                       capture_output=True, text=True, timeout=timeout, check=False,
                       encoding="utf-8", errors="replace")
    if completed.returncode != 0:
        raise GitHubTransportError(_classify_gh_failure(completed.returncode, completed.stderr),
                                   "gh api issue view failed: %s" % (completed.stderr or "").strip())
    try:
        issue_data = json.loads(completed.stdout or "{}")
    except ValueError as exc:
        raise GitHubTransportError("NETWORK_UNAVAILABLE", "gh api returned non-JSON issue: %s" % exc)
    # A merged PR is a valid historical dependency for intake planning.  Keep
    # rejecting open PRs so issue-only lifecycle operations remain fail-closed.
    if "pull_request" in issue_data and issue_data.get("state") != "closed":
        raise GitHubTransportError("SOURCE_NOT_FOUND", f"#{issue} is a pull request, not an issue")

    comments = _paginated_gh_api(f"repos/{owner}/{repo}/issues/{issue}/comments",
                                 runner=runner, timeout=timeout)
    canonical_comment = None
    human_comments: List[Dict[str, Any]] = []
    for c in comments:
        if LIFECYCLE_COMMENT_MARKER in (c.get("body") or ""):
            if canonical_comment is None or int(c.get("id", 0)) < int(canonical_comment.get("id", 0)):
                canonical_comment = c
        else:
            human_comments.append(c)

    authoritative = {
        "title": issue_data.get("title", ""),
        "body": issue_data.get("body") or "",
        "state": issue_data.get("state", ""),
        "state_reason": issue_data.get("state_reason") or "",
        "labels": sorted(l.get("name", "") for l in (issue_data.get("labels") or []) if isinstance(l, dict)),
        "assignees": sorted(a.get("login", "") for a in (issue_data.get("assignees") or []) if isinstance(a, dict)),
        "milestone": (issue_data.get("milestone") or {}).get("title", "") if isinstance(issue_data.get("milestone"), dict) else "",
        "author": (issue_data.get("user") or {}).get("login", ""),
        "created_at": issue_data.get("created_at", ""),
        "human_comments": [{"id": c.get("id"), "author": (c.get("user") or {}).get("login", ""),
                            "body": c.get("body") or "", "created_at": c.get("created_at", "")}
                           for c in sorted(human_comments, key=lambda c: int(c.get("id") or 0))],
    }
    source_revision = content_hash(json.dumps(authoritative, sort_keys=True, ensure_ascii=False))

    return {
        "schema": SNAPSHOT_SCHEMA,
        "provider": "github",
        "repo": f"{owner}/{repo}",
        "issue": str(issue),
        "url": issue_data.get("html_url", ""),
        "title": authoritative["title"],
        "body": authoritative["body"],
        "state": authoritative["state"],
        "state_reason": authoritative["state_reason"],
        "labels": authoritative["labels"],
        "assignees": authoritative["assignees"],
        "milestone": authoritative["milestone"],
        "author": authoritative["author"],
        "created_at": authoritative["created_at"],
        "updated_at": issue_data.get("updated_at", ""),
        "human_comments": authoritative["human_comments"],
        "canonical_comment": ({"id": canonical_comment.get("id"),
                               "body": canonical_comment.get("body") or "",
                               "body_hash": content_hash(canonical_comment.get("body") or "")}
                              if canonical_comment else None),
        "source_revision": source_revision,
        "observed_at": _now_iso(),
    }


def requery(owner: str, repo: str, issue: str, *, comment_id: Optional[int] = None,
           runner: Callable = subprocess.run, timeout: int = 20) -> Dict[str, Any]:
    """`requery` (#285): re-read the source of truth immediately before/after a mutation.

    A thin, explicitly-named wrapper over `get_details` (paginates everything again,
    never trusts a cached snapshot) plus, when `comment_id` is supplied, an extra
    direct fetch of that exact comment so a caller can compare its OWN expected body
    hash against what GitHub currently serves for that id (the "confirmed by re-query"
    requirement for every write).
    """
    snapshot = get_details(owner, repo, issue, runner=runner, timeout=timeout)
    snapshot["requeried_at"] = _now_iso()
    if comment_id is not None:
        body = _get_comment_body(owner, repo, comment_id, runner, timeout)
        snapshot["requeried_comment"] = {
            "id": comment_id,
            "body_hash": content_hash(body) if body is not None else "",
            "found": body is not None,
        }
    return snapshot


# --- duplicate-comment election (#285 "Recuperação de duplicatas") ---------------------


def get_authenticated_login(runner: Callable = subprocess.run, timeout: int = 20) -> Optional[str]:
    """Return the `gh`-authenticated actor's login, or `None` if it cannot be determined
    (no auth, network failure, unparsable response). Used to scope `SUPERSEDED` edits to
    comments this adapter itself authored -- never another actor's comment."""
    completed = runner(["gh", "api", "user"], capture_output=True, text=True, timeout=timeout,
                       check=False, encoding="utf-8", errors="replace")
    if completed.returncode != 0:
        return None
    try:
        data = json.loads(completed.stdout or "{}")
    except ValueError:
        return None
    login = data.get("login") if isinstance(data, dict) else None
    return login or None


def find_marker_comments(comments: Sequence[Mapping[str, Any]],
                         marker: str = LIFECYCLE_COMMENT_MARKER) -> List[Dict[str, Any]]:
    """Every comment (in `comments`, e.g. from a paginated `gh api .../comments` call)
    whose body carries `marker`, in the order given."""
    return [dict(c) for c in comments if isinstance(c, dict) and marker in (c.get("body") or "")]


def elect_canonical_comment(
    marker_comments: Sequence[Mapping[str, Any]],
) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    """Deterministically elect ONE canonical comment among every marker-tagged comment
    found on the issue: the lowest `id` wins (the first one ever created), matching
    `get_details`'s own canonical-comment tie-break so the two never disagree. Returns
    `(canonical, duplicates)` -- `duplicates` is every other marker-tagged comment,
    oldest first, regardless of author (author filtering happens at edit time, in
    `mark_comment_superseded`, never at election time)."""
    ordered = sorted((dict(c) for c in marker_comments), key=lambda c: int(c.get("id") or 0))
    if not ordered:
        return None, []
    return ordered[0], ordered[1:]


def mark_comment_superseded(
    owner: str,
    repo: str,
    comment: Mapping[str, Any],
    *,
    own_login: Optional[str],
    runner: Callable = subprocess.run,
    timeout: int = 20,
) -> Dict[str, Any]:
    """Edit ONE duplicate comment to append the `SUPERSEDED` banner -- but ONLY when its
    author matches `own_login`. A comment authored by anyone else is left completely
    untouched (#285: "nunca editar/apagar comentário de outro usuário" -- absolute, not
    best-effort) and reported as `skipped_foreign_author` so a human/reconciliation job
    can decide what (if anything) to do about it. Idempotent: a comment that already
    carries `SUPERSEDED_MARKER` is left alone (`already_superseded`), so a repeated
    reconciliation run never double-appends the banner."""
    comment_id = comment.get("id")
    author = (comment.get("user") or {}).get("login") or ""
    body = comment.get("body") or ""
    if own_login is None or author != own_login:
        return {"comment_id": comment_id, "author": author, "action": "skipped_foreign_author"}
    if SUPERSEDED_MARKER in body:
        return {"comment_id": comment_id, "author": author, "action": "already_superseded"}
    new_body = body.rstrip("\n") + "\n" + SUPERSEDED_BANNER + "\n"
    completed = runner(
        ["gh", "api", "-X", "PATCH", "repos/%s/%s/issues/comments/%s" % (owner, repo, comment_id),
         "--input", "-"],
        capture_output=True, text=True, timeout=timeout, check=False,
        encoding="utf-8", errors="replace", input=json.dumps({"body": new_body}),
    )
    if completed.returncode != 0:
        return {"comment_id": comment_id, "author": author, "action": "failed",
                "reason_code": _classify_gh_failure(completed.returncode, completed.stderr)}
    return {"comment_id": comment_id, "author": author, "action": "marked_superseded"}


def reconcile_duplicate_comments(
    owner: str,
    repo: str,
    issue: str,
    *,
    own_login: Optional[str] = None,
    marker: str = LIFECYCLE_COMMENT_MARKER,
    runner: Callable = subprocess.run,
    timeout: int = 20,
) -> Dict[str, Any]:
    """Full duplicate-comment election + safe repair (#285 "Recuperação de duplicatas"):
    paginate every comment, find every marker match, elect the canonical one
    deterministically, and mark every OTHER match authored by `own_login` as
    `SUPERSEDED`. `own_login` defaults to the live `gh`-authenticated login
    (`get_authenticated_login`) when not supplied -- callers with a cached identity
    may pass it explicitly to skip that extra call. Never creates, deletes, or edits
    the canonical comment itself; purely a repair pass over its duplicates."""
    if own_login is None:
        own_login = get_authenticated_login(runner=runner, timeout=timeout)
    comments = _paginated_gh_api(f"repos/{owner}/{repo}/issues/{issue}/comments",
                                 runner=runner, timeout=timeout)
    marker_comments = find_marker_comments(comments, marker=marker)
    canonical, duplicates = elect_canonical_comment(marker_comments)
    actions = [mark_comment_superseded(owner, repo, dup, own_login=own_login,
                                       runner=runner, timeout=timeout)
              for dup in duplicates]
    return {
        "schema": DUPLICATE_ELECTION_SCHEMA,
        "repo": f"{owner}/{repo}",
        "issue": str(issue),
        "canonical_comment_id": canonical.get("id") if canonical else None,
        "duplicate_count": len(duplicates),
        "actions": actions,
        "observed_at": _now_iso(),
    }


# --- outbox: persist intent before a remote mutation, clear only after confirmation ----


ISSUE_STATE_VERIFIER_SCHEMA = "simplicio.issue-state-verifier/v1"


def verify_issue_state(owner: str, repo: str, issue: str, *, expected_state: Optional[str] = None,
                       cached_snapshot: Optional[Dict[str, Any]] = None, ttl_seconds: int = 0,
                       runner: Callable = subprocess.run, timeout: int = 20) -> Dict[str, Any]:
    """`IssueStateVerifier` (#290): re-query the actual current state of a source issue
    (open/closed/reopened) right before trusting it, rather than caching a stale read.

    Composes with -- does not reinvent -- #285's `requery()` for the live read. The
    #290 TTL/freshness policy (`simplicio_loop/freshness.py`) decides whether a
    `cached_snapshot` (e.g. a `get_details`/`requery` result read earlier in the same
    turn) is still trustworthy: `ttl_seconds<=0` (the default) always forces a live
    re-query -- the safe default for a verifier whose entire purpose is "don't trust a
    stale read" -- while a caller that has good reason to reuse a very recent read (for
    example, a chain of checks within the same reconciliation transaction) may pass a
    positive `ttl_seconds` together with the `cached_snapshot` it wants considered.

    "Unknown is not pass": a transport failure on the forced live query reports
    `verified=False` with the underlying `GitHubTransportError.reason_code` -- it never
    falls back to trusting the cache just because the network call failed.
    """
    stale = True
    snapshot: Dict[str, Any] = {}
    source = "live"
    if cached_snapshot is not None:
        observed_at = cached_snapshot.get("requeried_at") or cached_snapshot.get("observed_at")
        stale = freshness.is_stale(observed_at, ttl_seconds)
        if not stale:
            snapshot = cached_snapshot
            source = "cache"
    if stale:
        try:
            snapshot = requery(owner, repo, issue, runner=runner, timeout=timeout)
        except GitHubTransportError as exc:
            return {
                "schema": ISSUE_STATE_VERIFIER_SCHEMA,
                "repo": f"{owner}/{repo}", "issue": str(issue),
                "state": None, "source": "live", "stale": True,
                "verified": False, "reason_code": exc.reason_code,
            }
        source = "live"
    state = snapshot.get("state")
    result: Dict[str, Any] = {
        "schema": ISSUE_STATE_VERIFIER_SCHEMA,
        "repo": f"{owner}/{repo}",
        "issue": str(issue),
        "state": state,
        "source": source,
        "stale": stale,
        "observed_at": snapshot.get("requeried_at") or snapshot.get("observed_at"),
    }
    if expected_state is not None and state != expected_state:
        result["verified"] = False
        result["reason_code"] = "issue_state_mismatch"
        result["expected_state"] = expected_state
    else:
        result["verified"] = True
        result["reason_code"] = None
    return result


def _outbox_path(outbox_dir: str | Path, op_id: str) -> Path:
    return Path(outbox_dir) / f"{op_id}.json"


def record_pending_operation(outbox_dir: str | Path, op_id: str, payload: Mapping[str, Any]) -> Path:
    """Persist a pending operation BEFORE the remote call (#285 step 10: "persistir
    operação pendente antes da chamada remota"). Atomic write via a temp-file rename so
    a crash mid-write never leaves a half-written record."""
    directory = Path(outbox_dir)
    directory.mkdir(parents=True, exist_ok=True)
    record = {"operation_id": op_id, "status": "pending", "recorded_at": _now_iso(), **dict(payload)}
    target = _outbox_path(directory, op_id)
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
    os.replace(tmp, target)
    return target


def mark_operation_done(outbox_dir: str | Path, op_id: str, receipt: Mapping[str, Any]) -> Path:
    """Mark a pending operation confirmed. Kept (not deleted) for audit, with `status`
    flipped to `done` -- `list_pending_operations` only ever returns `status == pending`."""
    directory = Path(outbox_dir)
    target = _outbox_path(directory, op_id)
    existing: Dict[str, Any] = {}
    if target.exists():
        try:
            existing = json.loads(target.read_text(encoding="utf-8"))
        except ValueError:
            existing = {}
    existing.update({"operation_id": op_id, "status": "done", "confirmed_at": _now_iso(), "receipt": dict(receipt)})
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(existing, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
    os.replace(tmp, target)
    return target


def list_pending_operations(outbox_dir: str | Path) -> List[Dict[str, Any]]:
    directory = Path(outbox_dir)
    if not directory.exists():
        return []
    pending = []
    for path in sorted(directory.glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if record.get("status") == "pending":
            pending.append(record)
    return pending


def reconcile(op_id: str, *, outbox_dir: str | Path, owner: str, repo: str, issue: str,
             comment_id: Optional[int] = None, expected_body_hash: str = "",
             runner: Callable = subprocess.run, timeout: int = 20) -> Dict[str, Any]:
    """`reconcile` (#285): recover a pending operation after a crash between a
    confirmed remote write and the local receipt, without ever posting a second
    comment. Re-queries the source; if the observed comment/issue state now matches
    what the pending record expected, the operation is marked `done` and `reconciled`
    is returned. Never creates or edits anything itself -- purely observational.
    """
    directory = Path(outbox_dir)
    record_path = _outbox_path(directory, op_id)
    if not record_path.exists():
        return {"schema": LIFECYCLE_SCHEMA, "operation_id": op_id, "outcome": "not_found",
                "reason_code": "OPERATION_NOT_FOUND"}
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except ValueError:
        record = {}
    if record.get("status") == "done":
        return {"schema": LIFECYCLE_SCHEMA, "operation_id": op_id, "outcome": "reconciled",
                "receipt": record.get("receipt")}

    snapshot = requery(owner, repo, issue, comment_id=comment_id, runner=runner, timeout=timeout)
    observed_hash = ""
    if comment_id is not None:
        observed_hash = (snapshot.get("requeried_comment") or {}).get("body_hash", "")
    elif snapshot.get("canonical_comment"):
        observed_hash = snapshot["canonical_comment"]["body_hash"]
    matches = bool(expected_body_hash) and observed_hash == expected_body_hash
    if matches:
        receipt = {"schema": LIFECYCLE_SCHEMA, "operation_id": op_id, "outcome": "reconciled",
                  "observed_body_hash": observed_hash, "source_revision": snapshot.get("source_revision")}
        mark_operation_done(directory, op_id, receipt)
        return receipt
    return {"schema": LIFECYCLE_SCHEMA, "operation_id": op_id, "outcome": "still_pending",
            "observed_body_hash": observed_hash, "expected_body_hash": expected_body_hash,
            "source_revision": snapshot.get("source_revision")}


def _get_comment_body(owner: str, repo: str, comment_id: int,
                      runner: Callable, timeout: int) -> Optional[str]:
    completed = runner(
        ["gh", "api", "repos/%s/%s/issues/comments/%s" % (owner, repo, comment_id)],
        capture_output=True, text=True, timeout=timeout, check=False,
        encoding="utf-8", errors="replace",
    )
    if completed.returncode != 0:
        return None
    try:
        return json.loads(completed.stdout).get("body")
    except ValueError:
        return None


def publish_lifecycle_state(
    *,
    owner: str,
    repo: str,
    issue: str,
    state: str,
    run_id: str,
    attempt_id: str,
    fencing_token: str = "",
    lifecycle_revision: int = 0,
    publish_comment_fn: Callable,
    runner: Callable = subprocess.run,
    timeout: int = 20,
    require_active: Optional[Callable[[], None]] = None,
    outbox_dir: Optional[str | Path] = None,
    **render_kwargs: Any,
) -> Dict[str, Any]:
    """Publish one lifecycle state to the ONE canonical comment, then re-query and
    confirm the observed id/body-hash match what was just written.

    `publish_comment_fn` is `scripts.pr_evidence.publish_comment` injected by the
    caller (kept as a parameter, not a hard import, so this module has no import
    cycle with `scripts/`) -- it already provides idempotent create-or-update via
    `LIFECYCLE_COMMENT_MARKER`. Returns a `simplicio.github-lifecycle-receipt/v1`
    receipt; never raises for an ordinary publish/re-query mismatch (that is
    reported as `verified: False`, `outcome: "blocked"` instead), but a
    `PublishError` from the underlying transport (auth/network/permission)
    propagates -- fail-closed, never silently swallowed into a fake "verified".

    `require_active`, when given, is called with no arguments IMMEDIATELY before the
    remote write (e.g. a lease/fence check, #183) -- a lost/stale lease
    raises there and the write never happens (#285 "verificar lease/fence imediatamente
    antes da escrita"). `outbox_dir`, when given, persists a pending-operation record
    before the remote call and clears it only after the write is confirmed (#285's
    outbox: "Uma queda após o GitHub aceitar a escrita, mas antes do receipt local,
    deve ser recuperada pelo marker + body hash sem novo comentário" -- see
    `reconcile`).
    """
    body = render_lifecycle_comment(state=state, run_id=run_id, attempt_id=attempt_id,
                                    fencing_token=fencing_token, **render_kwargs)
    expected_hash = content_hash(body)
    op_id = operation_id(provider="github", repo=f"{owner}/{repo}", issue=str(issue),
                        run_id=run_id, attempt_id=attempt_id, fencing_token=fencing_token,
                        lifecycle_revision=lifecycle_revision, operation_kind=f"update_status:{state}")

    if require_active is not None:
        require_active()  # raises (e.g. LeaseLostDuringExecution) -- never caught here, fail-closed

    if outbox_dir is not None:
        record_pending_operation(outbox_dir, op_id, {
            "repo": f"{owner}/{repo}", "issue": str(issue), "run_id": run_id,
            "attempt_id": attempt_id, "operation_kind": f"update_status:{state}",
            "expected_body_hash": expected_hash,
        })

    result = publish_comment_fn(owner, repo, str(issue), body, marker=LIFECYCLE_COMMENT_MARKER,
                                runner=runner, timeout=timeout)
    comment_id = result.get("id")
    observed_body = _get_comment_body(owner, repo, comment_id, runner, timeout) if comment_id is not None else None
    observed_hash = content_hash(observed_body) if observed_body is not None else ""
    verified = comment_id is not None and observed_hash == expected_hash

    receipt = {
        "schema": LIFECYCLE_SCHEMA,
        "operation_id": op_id,
        "run_id": run_id,
        "attempt_id": attempt_id,
        "fencing_token": fencing_token,
        "repo": f"{owner}/{repo}",
        "issue": str(issue),
        "state": state,
        "comment_id": comment_id,
        "expected_body_hash": expected_hash,
        "observed_body_hash": observed_hash,
        "action": result.get("action"),
        "outcome": (result.get("action") or "blocked") if verified else "blocked",
        "verified": verified,
    }
    if outbox_dir is not None:
        if verified:
            mark_operation_done(outbox_dir, op_id, receipt)
        # else: leave the pending record for `reconcile()` -- a crash/race between the
        # confirmed remote write (if any actually landed) and this local receipt must
        # stay recoverable, never silently dropped.
    return receipt


def _wrap_source_revision_as_snapshot(snapshot_like: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Normalize either a raw `get_details()`-shaped mapping (has `source_revision`) or an
    already-wrapped `simplicio.source-snapshot/v1` mapping (has `source.snapshot_hash`) into the
    latter shape -- the one `source_snapshot.detect_source_drift`/`snapshot_hash_of` expect.
    A falsy/empty input normalizes to `{}` (no snapshot -> "no_snapshot", never a false drift)."""
    if not snapshot_like:
        return {}
    source = snapshot_like.get("source")
    if isinstance(source, Mapping) and "snapshot_hash" in source:
        return dict(snapshot_like)
    return {"source": {"snapshot_hash": str(snapshot_like.get("source_revision") or "")}}


def capture_close_precheck_snapshot(owner: str, repo: str, issue: str, *,
                                    runner: Callable = subprocess.run, timeout: int = 20) -> Dict[str, Any]:
    """Capture a `get_details()` snapshot suitable for the #285 close-time material-edit
    check (`detect_close_source_drift`) -- callable at claim/plan time so a caller has a
    `planning_snapshot` to hand to `close_source_issue` later, or again right before close
    to build the "current" side of the comparison."""
    return get_details(owner, repo, issue, runner=runner, timeout=timeout)


def detect_close_source_drift(
    owner: str,
    repo: str,
    issue: str,
    planning_snapshot: Mapping[str, Any],
    *,
    runner: Callable = subprocess.run,
    timeout: int = 20,
) -> Dict[str, Any]:
    """#285 remaining gap: detect a material human edit (title/body/labels/milestone/
    assignees) or a new human comment on `issue` between planning/claim time and close time.

    Reuses #284's exact comparison primitive (`source_snapshot.detect_source_drift`) rather
    than reinventing hash comparison. Deliberately does NOT feed it raw
    `source_snapshot.capture_github_issue_snapshot()` output on either side: that primitive
    hashes every comment INCLUDING the adapter's own canonical lifecycle status comment,
    which is rewritten on every lifecycle transition (CLAIMED -> PLANNED -> ... -> CLOSING)
    between planning time and close time -- comparing on that basis would self-drift on
    every single close. `get_details()`'s `source_revision` is built exactly to avoid this:
    it hashes title/body/state/state_reason/labels/assignees/milestone/author/created_at
    plus every HUMAN comment, explicitly excluding the adapter's own marker-tagged comment
    (see `get_details` docstring). `planning_snapshot` may be either a raw `get_details()`
    mapping (has `source_revision`) or an already-wrapped `simplicio.source-snapshot/v1`
    mapping (has `source.snapshot_hash`) -- both are accepted via
    `_wrap_source_revision_as_snapshot`.
    """
    current_details = get_details(owner, repo, issue, runner=runner, timeout=timeout)
    baseline = _wrap_source_revision_as_snapshot(planning_snapshot)
    current = _wrap_source_revision_as_snapshot(current_details)
    verdict = _source_snapshot.detect_source_drift(baseline, current)
    verdict["current_snapshot"] = current_details
    return verdict


def close_source_issue(
    *,
    owner: str,
    repo: str,
    issue: str,
    run_id: str,
    attempt_id: str,
    fencing_token: str = "",
    lifecycle_revision: int = 0,
    reason: str = "completed",
    require_active: Optional[Callable[[], None]] = None,
    publish_comment_fn: Optional[Callable] = None,
    runner: Callable = subprocess.run,
    timeout: int = 20,
    outbox_dir: Optional[str | Path] = None,
    precheck_issue_state: bool = False,
    planning_snapshot: Optional[Mapping[str, Any]] = None,
    **render_kwargs: Any,
) -> Dict[str, Any]:
    """`close` (#285): real `gh issue close` wiring, fail-closed.

    Order of operations mirrors the issue's DoD: (0) OPTIONAL pre-transition
    reconciliation -- when `precheck_issue_state=True`, `verify_issue_state` (#290's
    `IssueStateVerifier`) forces a fresh live re-query of the issue and confirms it is
    still `open` immediately before attempting the mutation; if it has already moved
    (closed by another actor/run, or the query itself fails) this returns
    `SOURCE_ALREADY_CLOSED`/`SOURCE_STATE_PRECHECK_FAILED` WITHOUT ever calling `gh
    issue close` -- avoiding both a redundant close attempt and a false assumption
    about the starting state; (1) lease/fence check via `require_active`, (2) the
    actual `gh issue close --reason <reason>` call using structured argv (never shell
    interpolation) -- any non-zero exit is reported as `SOURCE_CLOSE_FAILED` and
    NOTHING further happens (no comment update, no false "closed"); (3) an immediate
    post-transition re-query (`get_details`) confirms `state == "closed"` -- if it does
    not, `SOURCE_CLOSE_UNCONFIRMED` is returned rather than trusting the exit code
    alone; (4) only then is the canonical comment moved to `CLOSED` via
    `publish_lifecycle_state`. If steps 1-3 succeed but the final comment update
    cannot be confirmed, this returns `outcome: "CLOSE_PENDING_RECONCILIATION"` (the
    source IS closed; the operation stays in the outbox for `reconcile()`) instead of
    silently reporting a clean success.

    `precheck_issue_state` defaults to `False` so existing callers/tests that already
    trust their own upstream state tracking are unaffected; new call sites (and the
    reconciliation transaction described in #290 Fase "Reconciliation transaction")
    should pass `True`.

    `planning_snapshot`, when supplied, is a snapshot of the issue captured at
    planning/claim time (any `get_details()`-shaped mapping, e.g. from
    `capture_close_precheck_snapshot` called earlier in the run). Immediately before
    the actual `gh issue close` call, the CURRENT issue state is re-fetched and
    compared against it via `detect_close_source_drift` (#285's still-open gap: "não
    exige que a fonte continue compatível com o snapshot planejado"). Any material
    difference -- title, body, state, state_reason, labels, milestone, assignees, or a
    new HUMAN comment posted since the snapshot (the adapter's own canonical lifecycle
    comment is excluded, so its own progress updates never trigger a false positive) --
    blocks the close with `reason_code: "SOURCE_CHANGED"`, fail-closed, WITHOUT ever
    calling `gh issue close`. Omitting `planning_snapshot` (the default, `None`) skips
    this check entirely -- existing callers that have not wired a planning-time capture
    are unaffected, exactly like `precheck_issue_state`.
    """
    op_id = operation_id(provider="github", repo=f"{owner}/{repo}", issue=str(issue),
                        run_id=run_id, attempt_id=attempt_id, fencing_token=fencing_token,
                        lifecycle_revision=lifecycle_revision, operation_kind="close")

    if precheck_issue_state:
        precheck = verify_issue_state(owner, repo, issue, expected_state="open",
                                      runner=runner, timeout=timeout)
        if not precheck.get("verified"):
            already_closed = precheck.get("state") == "closed"
            return {
                "schema": LIFECYCLE_SCHEMA, "operation_id": op_id, "repo": f"{owner}/{repo}",
                "issue": str(issue), "outcome": "blocked",
                "reason_code": "SOURCE_ALREADY_CLOSED" if already_closed else "SOURCE_STATE_PRECHECK_FAILED",
                "precheck": precheck, "verified": False,
            }

    if require_active is not None:
        require_active()

    if planning_snapshot is not None:
        drift = detect_close_source_drift(owner, repo, issue, planning_snapshot,
                                          runner=runner, timeout=timeout)
        if drift.get("drifted"):
            return {
                "schema": LIFECYCLE_SCHEMA, "operation_id": op_id, "repo": f"{owner}/{repo}",
                "issue": str(issue), "outcome": "blocked", "reason_code": "SOURCE_CHANGED",
                "drift": drift, "verified": False,
            }

    if outbox_dir is not None:
        record_pending_operation(outbox_dir, op_id, {
            "repo": f"{owner}/{repo}", "issue": str(issue), "run_id": run_id,
            "attempt_id": attempt_id, "operation_kind": "close",
        })

    completed = runner(["gh", "issue", "close", str(issue), "--repo", f"{owner}/{repo}",
                        "--reason", reason], capture_output=True, text=True, timeout=timeout, check=False,
                       encoding="utf-8", errors="replace")
    if completed.returncode != 0:
        return {
            "schema": LIFECYCLE_SCHEMA, "operation_id": op_id, "repo": f"{owner}/{repo}",
            "issue": str(issue), "outcome": "blocked", "reason_code": "SOURCE_CLOSE_FAILED",
            "reason": (completed.stderr or completed.stdout or "").strip(), "verified": False,
        }

    # #290 -- post-transition reconciliation: re-verify the observed state actually
    # matches the expected effect (closed) right after the mutation, via the same
    # IssueStateVerifier (forced live, ttl_seconds=0 default) rather than trusting the
    # `gh issue close` exit code alone.
    snapshot = get_details(owner, repo, issue, runner=runner, timeout=timeout)
    if snapshot.get("state") != "closed":
        return {
            "schema": LIFECYCLE_SCHEMA, "operation_id": op_id, "repo": f"{owner}/{repo}",
            "issue": str(issue), "outcome": "blocked", "reason_code": "SOURCE_CLOSE_UNCONFIRMED",
            "observed_state": snapshot.get("state"), "verified": False,
        }

    comment_receipt: Dict[str, Any]
    if publish_comment_fn is None:
        comment_receipt = {"verified": False, "reason_code": "REMOTE_WRITE_UNCONFIRMED",
                          "reason": "no publish_comment_fn supplied; comment not updated to CLOSED"}
    else:
        try:
            comment_receipt = publish_lifecycle_state(
                owner=owner, repo=repo, issue=issue, state="CLOSED", run_id=run_id,
                attempt_id=attempt_id, fencing_token=fencing_token,
                lifecycle_revision=lifecycle_revision, publish_comment_fn=publish_comment_fn,
                runner=runner, timeout=timeout, **render_kwargs,
            )
        except Exception as exc:  # noqa: BLE001 -- surfaced as unverified, never a fake pass
            comment_receipt = {"verified": False, "reason_code": "REMOTE_WRITE_UNCONFIRMED", "reason": str(exc)}

    if outbox_dir is not None:
        if comment_receipt.get("verified"):
            mark_operation_done(outbox_dir, op_id, comment_receipt)
        # else: source IS closed (confirmed above) but the final comment write is not --
        # leave the pending record so `reconcile()` can recover it without a second close.

    return {
        **comment_receipt,
        "operation_id": op_id,
        "repo": f"{owner}/{repo}",
        "issue": str(issue),
        "source_state": "closed",
        "outcome": "closed" if comment_receipt.get("verified") else "CLOSE_PENDING_RECONCILIATION",
    }


__all__ = [
    "LIFECYCLE_SCHEMA",
    "SNAPSHOT_SCHEMA",
    "LIST_READY_SCHEMA",
    "DUPLICATE_ELECTION_SCHEMA",
    "ISSUE_STATE_VERIFIER_SCHEMA",
    "LIFECYCLE_COMMENT_MARKER",
    "SUPERSEDED_MARKER",
    "LIFECYCLE_STATES",
    "REGRESSION_REASON_CODES",
    "REASON_CODES",
    "GitHubTransportError",
    "validate_transition",
    "render_lifecycle_comment",
    "content_hash",
    "operation_id",
    "publish_lifecycle_state",
    "list_ready",
    "get_details",
    "requery",
    "verify_issue_state",
    "reconcile",
    "record_pending_operation",
    "mark_operation_done",
    "list_pending_operations",
    "close_source_issue",
    "get_authenticated_login",
    "find_marker_comments",
    "elect_canonical_comment",
    "mark_comment_superseded",
    "reconcile_duplicate_comments",
    "capture_close_precheck_snapshot",
    "detect_close_source_drift",
    "lifecycle_state_for_phase_event",
    "LIFECYCLE_RECEIPT_FILENAME",
    "lifecycle_receipt_path",
    "persist_lifecycle_receipt",
    "load_lifecycle_receipt",
]


# --- runner event-stream projection (best-effort, see simplicio_loop/runner.py) --------

_PHASE_EVENT_TO_LIFECYCLE_STATE: Dict[str, str] = {
    "intake": "DISCOVERED",
    "worker_claimed": "CLAIMED",
    "planning": "PLANNED",
    "mapping": "PLANNED",
    "executing": "IN_PROGRESS",
    "validating": "VERIFYING",
    "watching": "VERIFYING",
    "watcher_challenge": "VERIFYING",
    "blocked": "BLOCKED",
    "awaiting_decision": "AWAITING_DECISION",
    "delivering": "PR_OPEN",
}


def lifecycle_state_for_phase_event(kind: str) -> Optional[str]:
    """Map one runner phase-event `kind` (see `simplicio_loop/runner.py::_PHASE_EVENT_KINDS`)
    to the lifecycle state it should project onto the canonical comment, or `None` if
    that event kind has no lifecycle projection (e.g. terminal `done`/`partial`, which
    the runner does not auto-close through -- see `close_source_issue` for the
    explicit, fail-closed close path)."""
    return _PHASE_EVENT_TO_LIFECYCLE_STATE.get(str(kind or ""))
