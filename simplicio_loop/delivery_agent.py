"""Concrete `delivery_agent` stage-agent role (#429, EPIC #422 "Portable Stage Agents").

Issue #429 asks for the ONLY role authorized to turn an approved candidate into an
OBSERVED delivery: push, PR, checks/reviews, merge, target-reachability proof, source
comment/close, all bound to the SAME head/tree/plan/source identity that the
implementation (#426), safety (#428) and review-panel (#427) receipts were issued
against. `contracts/stage-agents/v1/stages.json` already registers the `delivery_agent`
role and its `delivering` stage (#423); this module is the role's *own* invariant
machinery, in the same "pure reducer over injected receipts/adapter results" style as
`safety_agents/safety_gate_agent.py` and `implementation_agent.py`.

Two named anti-patterns this module exists specifically to prevent (see AGENTS.md task
brief for #429 and the issue's own "Não pode" boundary):

  1. "PR aberta/push não satisfaz merge/delivery" — a PR merely existing (or being open)
     must never be treated as delivered.
  2. "inferir merge de push/branch/mergedAt sem reachability" — an adapter-reported
     `merged`/`mergedAt` field is NEVER trusted by itself; `mark_target_reachability`
     always requires an independently-observed `ancestor_check` result (e.g. `git
     merge-base --is-ancestor <sha> <target>`) before a receipt may declare `merged=True`.

The module's core (`plan_next_step`, `build_delivery_receipt`, preconditions, idempotency,
identity checks) is a pure, network-free reducer, exactly like the sibling roles: it
never itself shells out to `git`/`gh`. `GitHubDeliveryAdapter` (this module) and any other
concrete `DeliveryAdapter` implementation are the only pieces that perform I/O, and the
saga driver (`run_delivery_saga`) always follows pre-query -> intent -> effect ->
post-query -> confirmation for every external effect, binding each to an idempotency key
so a retried/duplicated call never repeats a side effect.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, MutableMapping, Optional, Protocol, Sequence

from .watcher247.closing_words import sanitize

DELIVERY_STAGE_RECEIPT_SCHEMA = "simplicio.delivery-stage-receipt/v1"
DELIVERY_AGENT_ROLE_ID = "delivery_agent"
PR_BODY_INTEGRITY_SCHEMA = "simplicio.pr-body-integrity/v1"

VERDICT_PASS = "pass"
VERDICT_BLOCKED = "blocked"
VERDICT_FAILED = "failed"

# The delivery saga (issue #429 "Saga de entrega") — ordered, each fence-bound and
# idempotent, each with a pre-query and a post-query/confirmation.
SAGA_EVENTS = (
    "DeliveryPrepared",
    "ComposedVerificationStarted",
    "ComposedVerificationPassed",
    "PushIntent",
    "PushConfirmed",
    "PullRequestIntent",
    "PullRequestObserved",
    "ChecksObserved",
    "ReviewsObserved",
    "MergeIntent",
    "MergeConfirmed",
    "TargetReachabilityObserved",
    "SourceCommentIntent",
    "SourceCommentConfirmed",
    "SourceCloseIntent",
    "SourceCloseConfirmed",
    "DeliveryReceiptAccepted",
)

# Receipts this role is categorically forbidden from ever writing (it delivers, it does
# not re-approve implementation/safety/review, and it is not the completion auditor).
FORBIDDEN_RECEIPT_SCHEMAS = frozenset((
    "simplicio.implementation-stage-receipt/v1",
    "simplicio.safety-stage-receipt/v1",
    "simplicio.review-receipt/v1",
    "simplicio.completion-receipt/v1",
))


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _canonical_pr_body(body: str) -> str:
    return str(body).replace("\r\n", "\n").replace("\r", "\n")


def _markdown_body_shape(body: str) -> Dict[str, Any]:
    lines = _canonical_pr_body(body).splitlines()
    fence_lines = sum(1 for line in lines if line.lstrip().startswith(("```", "~~~")))
    table_lines = [line for line in lines if line.strip().startswith("|") and line.strip().endswith("|")]
    table_separators = sum(
        1 for line in table_lines
        if re.fullmatch(r"\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?", line.strip())
    )
    return {
        "line_count": len(lines),
        "nonblank_line_count": sum(1 for line in lines if line.strip()),
        "heading_count": sum(1 for line in lines if re.match(r"^\s{0,3}#{1,6}\s+", line)),
        "list_item_count": sum(1 for line in lines if re.match(r"^\s{0,3}(?:[-*+]\s+|\d+[.)]\s+)", line)),
        "table_row_count": len(table_lines),
        "table_separator_count": table_separators,
        "fenced_block_count": fence_lines // 2,
        "fences_balanced": fence_lines % 2 == 0,
        "link_count": len(re.findall(r"\[[^\]]+\]\([^)]*\)", _canonical_pr_body(body))),
    }


def _rendered_body_shape(body_html: str) -> Dict[str, int]:
    html = str(body_html or "")
    return {
        "heading_count": len(re.findall(r"<h[1-6]\b", html, flags=re.IGNORECASE)),
        "list_item_count": len(re.findall(r"<li\b", html, flags=re.IGNORECASE)),
        "table_row_count": len(re.findall(r"<tr\b", html, flags=re.IGNORECASE)),
        "fenced_block_count": len(re.findall(r"<pre\b[^>]*>\s*<code\b", html, flags=re.IGNORECASE)),
        "link_count": len(re.findall(r"<a\b", html, flags=re.IGNORECASE)),
    }


def build_pr_body_integrity(body: str) -> Dict[str, Any]:
    """Build the source-side contract used before PR publication.

    Line endings are canonicalized for the comparison hash, while the exact UTF-8
    source hash remains available for audit. Encoding errors and NUL bytes fail closed.
    """
    if not isinstance(body, str):
        raise DeliveryAgentError("PR body must be text", reason_code="pr_body_integrity")
    if "\x00" in body:
        raise DeliveryAgentError("PR body contains NUL", reason_code="pr_body_integrity")
    try:
        source_bytes = body.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise DeliveryAgentError("PR body is not valid UTF-8", reason_code="pr_body_integrity") from exc
    canonical = _canonical_pr_body(body)
    return {
        "schema": PR_BODY_INTEGRITY_SCHEMA,
        "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "canonical_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "markdown": _markdown_body_shape(canonical),
    }


def verify_pr_body_integrity(expected: Mapping[str, Any], observed_body: str,
                             observed_html: str) -> Dict[str, Any]:
    """Compare the raw post-publication body and its rendered HTML shape."""
    observed = build_pr_body_integrity(observed_body)
    errors: List[str] = []
    if expected.get("canonical_sha256") != observed["canonical_sha256"]:
        errors.append("canonical_body_hash_mismatch")
    if expected.get("markdown") != observed["markdown"]:
        errors.append("markdown_structure_mismatch")
    rendered = _rendered_body_shape(observed_html)
    if not str(observed_html or "").strip():
        errors.append("rendered_body_missing")
    else:
        markdown = observed["markdown"]
        expected_rendered = {
            "heading_count": markdown["heading_count"],
            "list_item_count": markdown["list_item_count"],
            "table_row_count": max(0, markdown["table_row_count"] - markdown["table_separator_count"]),
            "fenced_block_count": markdown["fenced_block_count"],
            "link_count": markdown["link_count"],
        }
        if rendered != expected_rendered:
            errors.append("rendered_structure_mismatch")
    return {
        "schema": PR_BODY_INTEGRITY_SCHEMA,
        "ok": not errors,
        "errors": errors,
        "expected": dict(expected),
        "observed": observed,
        "rendered": rendered,
    }


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def content_hash(obj: Any) -> str:
    return hashlib.sha256(_canonical(obj).encode("utf-8")).hexdigest()


class DeliveryAgentError(ValueError):
    """Base error for the delivery_agent role. Fail-closed, never silent."""

    def __init__(self, message: str, *, reason_code: str = "delivery_agent_error"):
        super().__init__(message)
        self.reason_code = reason_code


class PreconditionError(DeliveryAgentError):
    """Raised when a precondition required before delivery starts is missing/invalid."""

    def __init__(self, message: str):
        super().__init__(message, reason_code="precondition")


class IdentityDriftError(DeliveryAgentError):
    """Raised when head/base/tree/plan/source identity does not match across receipts."""

    def __init__(self, message: str):
        super().__init__(message, reason_code="identity_drift")


class ForbiddenReceiptError(DeliveryAgentError):
    """Raised when this role is asked to write a receipt owned by another role."""

    def __init__(self, message: str):
        super().__init__(message, reason_code="capability")


class BaseDriftRepairError(DeliveryAgentError):
    """Raised when base drift is detected and must be handed off to a repair/feedback
    agent instead of delivery proceeding (plan step 8)."""

    def __init__(self, message: str):
        super().__init__(message, reason_code="base_drift")


def assert_receipt_schema_allowed(schema: str) -> None:
    if str(schema) in FORBIDDEN_RECEIPT_SCHEMAS:
        raise ForbiddenReceiptError(
            f"delivery_agent may never write a {schema!r} receipt "
            "(implementation/safety/review/completion are independent roles)"
        )


# --------------------------------------------------------------------------- #
# 1. Identity — head/tree/plan/base/source must match across every upstream
#    receipt and the current delivery context (plan step 7, precondition:
#    "plan/source/base revision consistente").
# --------------------------------------------------------------------------- #
IDENTITY_KEYS = ("run_id", "task_id", "plan_revision", "head_sha", "base_sha", "tree_hash", "fence")


def compute_identity(**kwargs: Any) -> Dict[str, Any]:
    identity = {k: kwargs.get(k) for k in IDENTITY_KEYS}
    for k in ("run_id", "task_id", "head_sha", "base_sha", "tree_hash", "fence"):
        identity[k] = str(identity.get(k) or "")
    identity["plan_revision"] = int(identity.get("plan_revision") or 0)
    return identity


def check_identity_match(current: Mapping[str, Any], other: Mapping[str, Any], *, label: str) -> List[str]:
    """Return mismatch reasons (empty == identical) between `current` and a receipt-derived
    identity `other`. Only keys present (non-empty) in `other` are compared, so a receipt
    that omits a field is not falsely flagged -- but every populated field must match."""
    errors: List[str] = []
    for key in IDENTITY_KEYS:
        want = current.get(key)
        got = other.get(key)
        if got in (None, "", 0) and key != "plan_revision":
            continue
        if key == "plan_revision" and got in (None, 0):
            continue
        if str(want) != str(got):
            errors.append(f"{label}.{key} mismatch: expected {want!r}, receipt has {got!r}")
    return errors


def assert_identity_consistent(current: Mapping[str, Any], receipts: Mapping[str, Mapping[str, Any]]) -> None:
    """Fail-closed: every named upstream receipt's identity must match `current`'s.
    `receipts` maps a label (e.g. "implementation_receipt") -> the receipt-shaped dict."""
    all_errors: List[str] = []
    for label, receipt in receipts.items():
        all_errors.extend(check_identity_match(current, receipt, label=label))
    if all_errors:
        raise IdentityDriftError("identity drift across delivery preconditions: " + "; ".join(all_errors))


def detect_base_drift(*, expected_base_sha: str, current_base_sha: str) -> bool:
    """True when the target/default branch has moved since the candidate was formed
    (plan step 8: base drift is a repair handoff, not a delivery-time fix)."""
    return str(expected_base_sha or "") != str(current_base_sha or "")


# --------------------------------------------------------------------------- #
# 2. Preconditions (issue #429 "Precondições") — all must hold before the saga
#    is allowed to start.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class DeliveryPreconditions:
    ok: bool
    errors: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {"ok": self.ok, "errors": list(self.errors)}


def check_preconditions(
    *,
    stage_graph_valid: bool,
    identity: Mapping[str, Any],
    implementation_receipt: Optional[Mapping[str, Any]],
    safety_receipt: Optional[Mapping[str, Any]],
    safety_receipt_fresh: bool,
    review_receipts: Sequence[Mapping[str, Any]],
    review_synthesis: Optional[Mapping[str, Any]],
    task_anchor_gate_open: bool,
    secret_scan_ok: bool,
    delivery_target: Optional[Mapping[str, Any]],
    action_authorizations: Mapping[str, bool],
) -> DeliveryPreconditions:
    """Pure precondition gate. Every listed failure is additive (never short-circuits)
    so a caller sees the full blocker set at once, matching `safety_gate_agent`'s and
    `implementation_agent`'s fail-closed discipline."""
    errors: List[str] = []

    if not stage_graph_valid:
        errors.append("stage graph is invalid")

    if implementation_receipt is None:
        errors.append("missing implementation receipt")
    elif str(implementation_receipt.get("verdict")) != "pass" and str(implementation_receipt.get("verdict")) != VERDICT_PASS:
        errors.append("implementation receipt is not pass")
    elif not str(implementation_receipt.get("head_sha") or ""):
        errors.append("implementation receipt has no immutable head_sha")

    if safety_receipt is None:
        errors.append("missing safety receipt")
    elif str(safety_receipt.get("decision")) not in ("ALLOW", "ALLOW_WITH_CONSTRAINTS"):
        errors.append(f"safety receipt decision is {safety_receipt.get('decision')!r}, not ALLOW")
    if safety_receipt is not None and not safety_receipt_fresh:
        errors.append("safety receipt is not fresh")

    required_roles = {
        "security_correctness_reviewer", "maintainability_reviewer",
        "runtime_reproduction_verifier", "blast_radius_reviewer",
    }
    present_roles = {r.get("role_id") for r in review_receipts}
    missing_roles = required_roles - present_roles
    if missing_roles:
        errors.append(f"missing review receipts for roles: {sorted(missing_roles)}")
    if review_synthesis is None:
        errors.append("missing review synthesis")
    elif str(review_synthesis.get("verdict")) != VERDICT_PASS:
        errors.append(f"review synthesis verdict is {review_synthesis.get('verdict')!r}, not pass")

    if not task_anchor_gate_open:
        errors.append("task anchor / AC gate is not open (unverified AC remains)")

    if not secret_scan_ok:
        errors.append("secret scan did not pass")

    if not delivery_target or not str((delivery_target or {}).get("target_branch") or "").strip():
        errors.append("delivery target/policy is missing target_branch")

    for effect in ("push", "pull_request", "merge", "comment", "close"):
        if not action_authorizations.get(effect):
            errors.append(f"action authorization missing for effect: {effect}")

    return DeliveryPreconditions(ok=not errors, errors=errors)


def assert_preconditions_ok(preconditions: DeliveryPreconditions) -> None:
    if not preconditions.ok:
        raise PreconditionError("delivery preconditions not satisfied: " + "; ".join(preconditions.errors))


# --------------------------------------------------------------------------- #
# 3. Idempotency keys — bind every external effect so a retry never repeats it
#    (plan step 6).
# --------------------------------------------------------------------------- #
def idempotency_key(*, effect: str, run_id: str, task_id: str, fence: str, head_sha: str) -> str:
    """A deterministic key: same (effect, run, task, fence, head) always yields the same
    key, so a caller can dedup a retried effect against a durable store before performing
    it again."""
    return content_hash({
        "effect": str(effect), "run_id": str(run_id), "task_id": str(task_id),
        "fence": str(fence), "head_sha": str(head_sha),
    })


class IdempotencyLedger:
    """Minimal in-memory/injectable ledger recording which idempotency keys already
    produced a confirmed external effect. A real deployment persists this (e.g. in the
    ops ledger); tests can use the default dict-backed store."""

    def __init__(self, store: Optional[MutableMapping[str, Mapping[str, Any]]] = None) -> None:
        self._store: MutableMapping[str, Mapping[str, Any]] = store if store is not None else {}

    def seen(self, key: str) -> Optional[Mapping[str, Any]]:
        return self._store.get(key)

    def record(self, key: str, result: Mapping[str, Any]) -> None:
        self._store[key] = dict(result)


# --------------------------------------------------------------------------- #
# 4. Composed verification (plan step 3 / issue reference #288) — run the test
#    suite + review-panel synthesis check together as one gate, since a
#    dedicated merge-queue concept does not yet exist in this repo.
# --------------------------------------------------------------------------- #
def composed_verification(
    *,
    test_runs: Sequence[Mapping[str, Any]],
    review_synthesis: Mapping[str, Any],
) -> Dict[str, Any]:
    """One gate = test suite green AND review-panel synthesis PASS. Never invents a
    passing result: an empty `test_runs` is treated as not-passing."""
    from . import implementation_agent as _ia

    test_validation = _ia.all_tests_verified(test_runs)
    tests_ok = test_validation["ok"] and test_validation["passing"]
    review_ok = str(review_synthesis.get("verdict")) == VERDICT_PASS
    ok = tests_ok and review_ok
    return {
        "schema": "simplicio.composed-verification/v1",
        "ok": ok,
        "tests_ok": tests_ok,
        "review_ok": review_ok,
        "test_validation": test_validation,
        "review_verdict": review_synthesis.get("verdict"),
    }


# --------------------------------------------------------------------------- #
# 5. Adapter interface — adapter-agnostic core; GitHubDeliveryAdapter is one
#    concrete implementation (plan step 4). Every method is pre-query / effect
#    / post-query shaped so the saga driver can compose pre -> intent -> effect
#    -> post -> confirm uniformly regardless of adapter.
# --------------------------------------------------------------------------- #
class DeliveryAdapter(Protocol):
    def find_existing_pr(self, *, branch: str) -> Optional[Dict[str, Any]]: ...

    def push(self, *, branch: str, head_sha: str) -> Dict[str, Any]: ...

    def query_push(self, *, branch: str) -> Dict[str, Any]: ...

    def create_or_update_pr(self, *, branch: str, base: str, title: str, body: str) -> Dict[str, Any]: ...

    def query_pr(self, *, pr_id: str) -> Dict[str, Any]: ...

    def query_checks(self, *, pr_id: str) -> List[Dict[str, Any]]: ...

    def query_reviews(self, *, pr_id: str) -> List[Dict[str, Any]]: ...

    def merge(self, *, pr_id: str, strategy: str) -> Dict[str, Any]: ...

    def query_merge(self, *, pr_id: str) -> Dict[str, Any]: ...

    def check_reachability(self, *, commit_sha: str, target_branch: str) -> Dict[str, Any]: ...

    def comment(self, *, source_id: str, body: str, idempotency_key: str) -> Dict[str, Any]: ...

    def query_comments(self, *, source_id: str) -> List[Dict[str, Any]]: ...

    def close(self, *, source_id: str, idempotency_key: str) -> Dict[str, Any]: ...

    def query_source_state(self, *, source_id: str) -> Dict[str, Any]: ...


class GitHubDeliveryAdapter:
    """Concrete GitHub adapter, transport-shaped like `merge_executor.MergeExecutor` and
    `github_lifecycle.py`: every call is injectable via `runner` (default `subprocess.run`)
    so it is unit-testable without a network, while still usable for real."""

    def __init__(self, *, repo: str, runner: Optional[Callable[..., Any]] = None, timeout: int = 30) -> None:
        import subprocess as _subprocess

        if not str(repo).strip():
            raise DeliveryAgentError("repo is required (owner/name)", reason_code="config")
        self.repo = str(repo).strip()
        self.runner = runner or _subprocess.run
        self.timeout = timeout

    def _gh(self, args: Sequence[str], *, check: bool = True) -> Any:
        completed = self.runner(["gh", *args], capture_output=True, text=True, timeout=self.timeout)
        if check and completed.returncode != 0:
            raise DeliveryAgentError(
                f"gh {' '.join(args)} failed (exit {completed.returncode}): "
                f"{(completed.stderr or completed.stdout or '').strip()}",
                reason_code="adapter_transport",
            )
        return completed

    def find_existing_pr(self, *, branch: str) -> Optional[Dict[str, Any]]:
        completed = self._gh(
            ["pr", "list", "--repo", self.repo, "--head", branch, "--state", "all",
             "--json", "number,url,state,mergeable,mergeStateStatus"],
            check=False,
        )
        if completed.returncode != 0:
            return None
        try:
            items = json.loads(completed.stdout or "[]")
        except (ValueError, TypeError):
            return None
        if not items:
            return None
        for item in items:
            if item.get("state") == "OPEN":
                return item
        return items[0]

    def push(self, *, branch: str, head_sha: str) -> Dict[str, Any]:
        completed = self.runner(["git", "push", "origin", f"{head_sha}:refs/heads/{branch}"],
                                 capture_output=True, text=True, timeout=self.timeout)
        return {"ok": completed.returncode == 0, "detail": (completed.stdout or "") + (completed.stderr or "")}

    def query_push(self, *, branch: str) -> Dict[str, Any]:
        completed = self.runner(["git", "ls-remote", "origin", f"refs/heads/{branch}"],
                                 capture_output=True, text=True, timeout=self.timeout)
        out = (completed.stdout or "").strip()
        remote_sha = out.split()[0] if out else ""
        return {"branch": branch, "remote_head_sha": remote_sha}

    def _gh_with_body_file(self, args: Sequence[str], body: str) -> Any:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="", delete=False, suffix=".md"
        ) as body_file:
            body_file.write(body)
            body_path = body_file.name
        try:
            return self._gh([*args, "--body-file", body_path])
        finally:
            try:
                os.unlink(body_path)
            except FileNotFoundError:
                pass

    def _validated_pr(self, *, pr_id: str, expected: Mapping[str, Any]) -> Dict[str, Any]:
        observed = self.query_pr(pr_id=pr_id)
        verification = verify_pr_body_integrity(
            expected,
            str(observed.get("body") or ""),
            str(observed.get("bodyHTML") or ""),
        )
        if not verification["ok"]:
            raise DeliveryAgentError(
                f"PR #{pr_id} body integrity failed: {','.join(verification['errors'])}",
                reason_code="pr_body_integrity",
            )
        return {**observed, "body_integrity": verification}

    def create_or_update_pr(self, *, branch: str, base: str, title: str, body: str) -> Dict[str, Any]:
        title = sanitize(title, "PR title")  # both `pr create` and `pr edit` leave through here (#1644)
        body = sanitize(body, "PR body")
        expected = build_pr_body_integrity(body)
        existing = self.find_existing_pr(branch=branch)
        if existing is not None and existing.get("state") == "OPEN":
            pr_id = str(existing["number"])
            observed = self.query_pr(pr_id=pr_id)
            observed_contract = build_pr_body_integrity(str(observed.get("body") or ""))
            if observed_contract["canonical_sha256"] != expected["canonical_sha256"]:
                self._gh_with_body_file(
                    ["pr", "edit", pr_id, "--repo", self.repo],
                    body,
                )
            validated = self._validated_pr(pr_id=pr_id, expected=expected)
            return {
                "number": int(pr_id),
                "url": validated.get("url", existing.get("url", "")),
                "state": "OPEN",
                "body_integrity": validated["body_integrity"],
            }
        completed = self._gh_with_body_file(
            ["pr", "create", "--repo", self.repo, "--head", branch, "--base", base, "--title", title],
            body,
        )
        lines = [ln for ln in completed.stdout.strip().splitlines() if ln.strip()]
        url = lines[-1] if lines else ""
        try:
            number = int(url.rstrip("/").rsplit("/", 1)[-1])
        except ValueError:
            number = 0
        if not number:
            raise DeliveryAgentError(
                "gh pr create returned no PR number",
                reason_code="adapter_transport",
            )
        validated = self._validated_pr(pr_id=str(number), expected=expected)
        return {
            "number": number,
            "url": validated.get("url", url),
            "state": "OPEN",
            "body_integrity": validated["body_integrity"],
        }

    def query_pr(self, *, pr_id: str) -> Dict[str, Any]:
        completed = self._gh(["pr", "view", str(pr_id), "--repo", self.repo,
                               "--json", "number,url,state,mergeable,mergeStateStatus,headRefOid,body,bodyHTML"])
        return json.loads(completed.stdout or "{}")

    def query_checks(self, *, pr_id: str) -> List[Dict[str, Any]]:
        completed = self._gh(["pr", "checks", str(pr_id), "--repo", self.repo, "--json",
                               "name,state,bucket"], check=False)
        try:
            return json.loads(completed.stdout or "[]")
        except (ValueError, TypeError):
            return []

    def query_reviews(self, *, pr_id: str) -> List[Dict[str, Any]]:
        completed = self._gh(["pr", "view", str(pr_id), "--repo", self.repo, "--json", "reviews"], check=False)
        try:
            return json.loads(completed.stdout or "{}").get("reviews", [])
        except (ValueError, TypeError):
            return []

    def merge(self, *, pr_id: str, strategy: str) -> Dict[str, Any]:
        args = ["pr", "merge", str(pr_id), "--repo", self.repo, f"--{strategy}", "--delete-branch"]
        completed = self._gh(args, check=False)
        return {"ok": completed.returncode == 0, "detail": (completed.stderr or completed.stdout or "").strip()}

    def query_merge(self, *, pr_id: str) -> Dict[str, Any]:
        completed = self._gh(["pr", "view", str(pr_id), "--repo", self.repo,
                               "--json", "state,mergeCommit,baseRefName"])
        data = json.loads(completed.stdout or "{}")
        merge_commit = data.get("mergeCommit") or {}
        return {
            "state": data.get("state"),
            "merge_commit_sha": str(merge_commit.get("oid") or ""),
            "base_ref": data.get("baseRefName") or "",
        }

    def check_reachability(self, *, commit_sha: str, target_branch: str) -> Dict[str, Any]:
        """The core anti-'mergedAt without reachability' primitive: an independent,
        adapter-reported `merged`/`mergeCommit` field is NEVER trusted alone. This asks
        git itself whether `commit_sha` is an ancestor of `target_branch` (or patch-
        equivalent for squash/rebase, via `git cherry`), and reports the observed answer
        regardless of what the PR object claims."""
        self.runner(["git", "fetch", "origin", target_branch], capture_output=True, text=True, timeout=self.timeout)
        ancestor = self.runner(
            ["git", "merge-base", "--is-ancestor", commit_sha, f"origin/{target_branch}"],
            capture_output=True, text=True, timeout=self.timeout,
        )
        reachable = getattr(ancestor, "returncode", 1) == 0
        patch_equivalent = False
        if not reachable:
            cherry = self.runner(
                ["git", "cherry", f"origin/{target_branch}", commit_sha],
                capture_output=True, text=True, timeout=self.timeout,
            )
            out = (getattr(cherry, "stdout", "") or "").strip()
            # `git cherry` prefixes an already-applied (patch-equivalent) commit with "-".
            patch_equivalent = out.startswith("-")
        return {
            "commit_sha": commit_sha, "target_branch": target_branch,
            "reachable": bool(reachable or patch_equivalent),
            "ancestor": bool(reachable), "patch_equivalent": bool(patch_equivalent),
        }

    def comment(self, *, source_id: str, body: str, idempotency_key: str) -> Dict[str, Any]:
        marker = f"<!-- simplicio-delivery-evidence:{idempotency_key} -->"
        existing = self.query_comments(source_id=source_id)
        for c in existing:
            if marker in str(c.get("body", "")):
                return {"ok": True, "deduped": True, "comment": c}
        completed = self._gh(["issue", "comment", str(source_id), "--repo", self.repo,
                               "--body", f"{body}\n\n{marker}"], check=False)
        return {"ok": completed.returncode == 0, "deduped": False,
                "detail": (completed.stderr or completed.stdout or "").strip()}

    def query_comments(self, *, source_id: str) -> List[Dict[str, Any]]:
        completed = self._gh(["issue", "view", str(source_id), "--repo", self.repo, "--json", "comments"],
                              check=False)
        try:
            return json.loads(completed.stdout or "{}").get("comments", [])
        except (ValueError, TypeError):
            return []

    def close(self, *, source_id: str, idempotency_key: str) -> Dict[str, Any]:
        completed = self._gh(["issue", "close", str(source_id), "--repo", self.repo], check=False)
        return {"ok": completed.returncode == 0, "detail": (completed.stderr or completed.stdout or "").strip()}

    def query_source_state(self, *, source_id: str) -> Dict[str, Any]:
        completed = self._gh(["issue", "view", str(source_id), "--repo", self.repo, "--json", "state"])
        return json.loads(completed.stdout or "{}")


# --------------------------------------------------------------------------- #
# 6. The pre-query -> intent -> effect -> post-query -> confirmation driver
#    (plan step 5, the core invariant of #429).
# --------------------------------------------------------------------------- #
@dataclass
class SagaStep:
    event: str
    ok: bool
    detail: Dict[str, Any]


class DeliverySaga:
    """Drives the ordered `SAGA_EVENTS` list, recording a `SagaStep` per transition.
    Every external effect goes through `_effected` which checks the idempotency ledger
    FIRST (pre-query), performs the effect only if not already recorded, then re-queries
    the adapter for the post-state and only records the ledger entry once the post-query
    confirms the effect actually landed."""

    def __init__(self, *, adapter: DeliveryAdapter, ledger: Optional[IdempotencyLedger] = None) -> None:
        self.adapter = adapter
        self.ledger = ledger or IdempotencyLedger()
        self.steps: List[SagaStep] = []

    def _emit(self, event: str, ok: bool, detail: Mapping[str, Any]) -> SagaStep:
        step = SagaStep(event=event, ok=ok, detail=dict(detail))
        self.steps.append(step)
        return step

    def _effected(self, *, key: str, effect_fn: Callable[[], Dict[str, Any]],
                  post_query_fn: Callable[[], Dict[str, Any]],
                  confirm_fn: Callable[[Dict[str, Any]], bool]) -> Dict[str, Any]:
        """pre-query (ledger) -> intent/effect (only if unseen) -> post-query -> confirm."""
        seen = self.ledger.seen(key)
        if seen is not None:
            return {**seen, "deduped": True}
        effect_fn()
        post = post_query_fn()
        confirmed = confirm_fn(post)
        result = {**post, "confirmed": bool(confirmed), "deduped": False}
        if confirmed:
            self.ledger.record(key, result)
        return result

    # -- 1. DeliveryPrepared ------------------------------------------------
    def prepare(self, *, identity: Mapping[str, Any]) -> SagaStep:
        return self._emit("DeliveryPrepared", True, {"identity": dict(identity)})

    # -- 2. ComposedVerification ---------------------------------------------
    def verify(self, *, test_runs: Sequence[Mapping[str, Any]], review_synthesis: Mapping[str, Any]) -> SagaStep:
        self._emit("ComposedVerificationStarted", True, {})
        result = composed_verification(test_runs=test_runs, review_synthesis=review_synthesis)
        return self._emit("ComposedVerificationPassed", result["ok"], result)

    # -- 3. Push --------------------------------------------------------------
    def push(self, *, branch: str, head_sha: str, run_id: str, task_id: str, fence: str) -> SagaStep:
        key = idempotency_key(effect="push", run_id=run_id, task_id=task_id, fence=fence, head_sha=head_sha)
        pre = self.adapter.query_push(branch=branch)
        self._emit("PushIntent", True, {"pre": pre, "idempotency_key": key})
        if pre.get("remote_head_sha") == head_sha:
            result = {"remote_head_sha": head_sha, "confirmed": True, "deduped": True}
        else:
            result = self._effected(
                key=key,
                effect_fn=lambda: self.adapter.push(branch=branch, head_sha=head_sha),
                post_query_fn=lambda: self.adapter.query_push(branch=branch),
                confirm_fn=lambda post: post.get("remote_head_sha") == head_sha,
            )
        return self._emit("PushConfirmed", bool(result.get("confirmed")), result)

    # -- 4. Pull request --------------------------------------------------------
    def open_pr(self, *, branch: str, base: str, title: str, body: str,
                run_id: str, task_id: str, fence: str, head_sha: str) -> SagaStep:
        key = idempotency_key(effect="pull_request", run_id=run_id, task_id=task_id, fence=fence, head_sha=head_sha)
        pre = self.adapter.find_existing_pr(branch=branch)
        self._emit("PullRequestIntent", True, {"pre": pre, "idempotency_key": key})
        pr = self._effected(
            key=key,
            effect_fn=lambda: self.adapter.create_or_update_pr(branch=branch, base=base, title=title, body=body),
            post_query_fn=lambda: self.adapter.create_or_update_pr(branch=branch, base=base, title=title, body=body),
            confirm_fn=lambda post: bool(post.get("number")),
        )
        return self._emit("PullRequestObserved", bool(pr.get("confirmed")), pr)

    # -- 5. Checks / reviews (observation only, no effect) -----------------------
    def observe_checks(self, *, pr_id: str) -> SagaStep:
        checks = self.adapter.query_checks(pr_id=pr_id)
        ok = all(str(c.get("bucket") or c.get("state") or "").upper() not in ("FAIL", "FAILURE") for c in checks)
        return self._emit("ChecksObserved", ok, {"checks": checks})

    def observe_reviews(self, *, pr_id: str, required_approvals: int = 0) -> SagaStep:
        reviews = self.adapter.query_reviews(pr_id=pr_id)
        changes_requested = [r for r in reviews if str(r.get("state")) == "CHANGES_REQUESTED"]
        approvals = [r for r in reviews if str(r.get("state")) == "APPROVED"]
        ok = not changes_requested and len(approvals) >= required_approvals
        return self._emit("ReviewsObserved", ok, {"reviews": reviews, "approvals": len(approvals)})

    # -- 6. Merge -----------------------------------------------------------------
    def merge(self, *, pr_id: str, strategy: str, run_id: str, task_id: str, fence: str, head_sha: str) -> SagaStep:
        key = idempotency_key(effect="merge", run_id=run_id, task_id=task_id, fence=fence, head_sha=head_sha)
        pre = self.adapter.query_merge(pr_id=pr_id)
        self._emit("MergeIntent", True, {"pre": pre, "idempotency_key": key})

        def confirm(post: Dict[str, Any]) -> bool:
            # NOTE: this confirms the merge *command* landed a state; it deliberately does
            # NOT by itself declare "delivered" — that requires TargetReachabilityObserved.
            return str(post.get("state")) == "MERGED" and bool(post.get("merge_commit_sha"))

        result = self._effected(
            key=key,
            effect_fn=lambda: self.adapter.merge(pr_id=pr_id, strategy=strategy),
            post_query_fn=lambda: self.adapter.query_merge(pr_id=pr_id),
            confirm_fn=confirm,
        )
        return self._emit("MergeConfirmed", bool(result.get("confirmed")), result)

    # -- 7. Target reachability — THE anti-pattern gate --------------------------
    def observe_target_reachability(self, *, commit_sha: str, target_branch: str) -> SagaStep:
        """Never trusts `MergeConfirmed`'s `state == MERGED` alone: independently asks the
        adapter's `check_reachability` (git ancestry / patch-equivalence), and only THIS
        step's `ok=True` may license `merged=True` in the final receipt."""
        observed = self.adapter.check_reachability(commit_sha=commit_sha, target_branch=target_branch)
        return self._emit("TargetReachabilityObserved", bool(observed.get("reachable")), observed)

    # -- 8. Source comment --------------------------------------------------------
    def comment_source(self, *, source_id: str, body: str, run_id: str, task_id: str, fence: str,
                        head_sha: str) -> SagaStep:
        key = idempotency_key(effect="comment", run_id=run_id, task_id=task_id, fence=fence, head_sha=head_sha)
        self._emit("SourceCommentIntent", True, {"idempotency_key": key})
        result = self._effected(
            key=key,
            effect_fn=lambda: self.adapter.comment(source_id=source_id, body=body, idempotency_key=key),
            post_query_fn=lambda: {"comments": self.adapter.query_comments(source_id=source_id)},
            confirm_fn=lambda post: any(key in str(c.get("body", "")) for c in post.get("comments", [])),
        )
        return self._emit("SourceCommentConfirmed", bool(result.get("confirmed")), result)

    # -- 9. Source close — ONLY after confirmed delivery + re-query --------------
    def close_source(self, *, source_id: str, delivered: bool, run_id: str, task_id: str, fence: str,
                      head_sha: str) -> SagaStep:
        key = idempotency_key(effect="close", run_id=run_id, task_id=task_id, fence=fence, head_sha=head_sha)
        self._emit("SourceCloseIntent", True, {"idempotency_key": key, "delivered": delivered})
        if not delivered:
            # This is the explicit anti-pattern: never close on PR-existence/merge-intent
            # alone. Refuse outright rather than perform (and later have to undo) the effect.
            return self._emit("SourceCloseConfirmed", False,
                               {"reason": "delivery not confirmed; refusing to close source item"})
        result = self._effected(
            key=key,
            effect_fn=lambda: self.adapter.close(source_id=source_id, idempotency_key=key),
            post_query_fn=lambda: self.adapter.query_source_state(source_id=source_id),
            confirm_fn=lambda post: str(post.get("state", "")).upper() in ("CLOSED", "CLOSED_COMPLETED"),
        )
        return self._emit("SourceCloseConfirmed", bool(result.get("confirmed")), result)


def steps_ok(steps: Sequence[SagaStep]) -> bool:
    return all(s.ok for s in steps)


def find_step(steps: Sequence[SagaStep], event: str) -> Optional[SagaStep]:
    for s in reversed(steps):
        if s.event == event:
            return s
    return None


# --------------------------------------------------------------------------- #
# 7. Base drift -> repair handoff (plan step 8), regression/reopen stub
#    (plan step 14).
# --------------------------------------------------------------------------- #
def repair_handoff(*, reason: str, identity: Mapping[str, Any]) -> Dict[str, Any]:
    """Minimal, testable stub result for handing base drift (or a regression/reopen
    signal) to the feedback/recovery agent (`feedback_recovery_agent` role already
    registered in stages.json). A real deployment wires this to that agent's queue."""
    return {
        "schema": "simplicio.delivery-repair-handoff/v1",
        "reason": str(reason),
        "identity": dict(identity),
        "handed_off_to": "feedback_recovery_agent",
        "handed_off_at": _now(),
    }


def regression_reopen_stub(*, source_id: str, signal: str) -> Dict[str, Any]:
    """Stub interface (plan step 14): a completion_auditor/feedback_recovery_agent that
    detects a post-merge regression can reopen via this shape without delivery_agent
    itself re-approving anything."""
    return {
        "schema": "simplicio.delivery-regression-signal/v1",
        "source_id": str(source_id),
        "signal": str(signal),
        "routed_to": "feedback_recovery_agent",
        "created_at": _now(),
    }


# --------------------------------------------------------------------------- #
# 8. status/blocker/next-action surface (plan step 15).
# --------------------------------------------------------------------------- #
def delivery_status(steps: Sequence[SagaStep]) -> Dict[str, Any]:
    completed_events = [s.event for s in steps if s.ok]
    blocking = next((s for s in steps if not s.ok), None)
    remaining = [e for e in SAGA_EVENTS if e not in completed_events]
    return {
        "completed_events": completed_events,
        "remaining_events": remaining,
        "blocker": None if blocking is None else {"event": blocking.event, "detail": blocking.detail},
        "next_action": remaining[0] if remaining and blocking is None else (blocking.event if blocking else None),
    }


# --------------------------------------------------------------------------- #
# 9. The composed #429 receipt — content-addressed, fail-closed by construction.
# --------------------------------------------------------------------------- #
def build_delivery_stage_receipt(
    *,
    run_id: str,
    task_id: str,
    attempt_id: str,
    fence: str,
    plan_revision: int,
    identity: Mapping[str, Any],
    preconditions: DeliveryPreconditions,
    saga: DeliverySaga,
    source_id: str,
    target_branch: str,
    pr_url: str = "",
) -> Dict[str, Any]:
    """Build the typed `simplicio.delivery-stage-receipt/v1`. `merged` is true ONLY when
    both `MergeConfirmed` (adapter state) AND `TargetReachabilityObserved` (independent
    git ancestry/patch-equivalence check) passed -- neither alone is sufficient, which is
    exactly the "mergedAt without reachability" bug class this receipt must never contain.
    `closed` is true ONLY when `SourceCloseConfirmed` passed, which itself refuses to run
    unless `delivered` was already true."""
    assert_receipt_schema_allowed(DELIVERY_STAGE_RECEIPT_SCHEMA)

    steps = saga.steps
    merge_step = find_step(steps, "MergeConfirmed")
    reach_step = find_step(steps, "TargetReachabilityObserved")
    close_step = find_step(steps, "SourceCloseConfirmed")
    comment_step = find_step(steps, "SourceCommentConfirmed")
    pr_step = find_step(steps, "PullRequestObserved")

    merged = bool(merge_step and merge_step.ok and reach_step and reach_step.ok)
    delivered = merged
    closed = bool(close_step and close_step.ok and delivered)

    if not preconditions.ok:
        verdict = VERDICT_BLOCKED
    elif not steps_ok(steps):
        verdict = VERDICT_BLOCKED if not any(s.event in ("MergeIntent", "PushIntent") for s in steps if not s.ok) else VERDICT_FAILED
    elif delivered:
        verdict = VERDICT_PASS
    else:
        verdict = VERDICT_BLOCKED

    status = delivery_status(steps)

    receipt: Dict[str, Any] = {
        "schema": DELIVERY_STAGE_RECEIPT_SCHEMA,
        "role_id": DELIVERY_AGENT_ROLE_ID,
        "run_id": str(run_id),
        "task_id": str(task_id),
        "attempt_id": str(attempt_id),
        "fence": str(fence),
        "plan_revision": int(plan_revision),
        "identity": dict(identity),
        "preconditions": preconditions.to_dict(),
        "source_id": str(source_id),
        "target_branch": str(target_branch),
        "pr_url": str(pr_url or (pr_step.detail.get("url") if pr_step else "") or ""),
        "verdict": verdict,
        "saga_events": [{"event": s.event, "ok": s.ok, "detail": s.detail} for s in steps],
        "status": status,
        "merged": merged,
        "merge_confirmed": bool(merge_step and merge_step.ok),
        "target_reachability_observed": bool(reach_step and reach_step.ok),
        "reachability_detail": reach_step.detail if reach_step else None,
        "delivered": delivered,
        "source_commented": bool(comment_step and comment_step.ok),
        "source_closed": closed,
        "complete": False,  # only the completion_auditor may ever declare completion
        "created_at": _now(),
    }
    receipt["receipt_hash"] = content_hash({k: v for k, v in receipt.items() if k != "receipt_hash"})
    return receipt


def receipt_is_delivered(receipt: Mapping[str, Any]) -> bool:
    """A receipt counts as delivered only via the real gate, never via a bare `verdict`
    string or the presence of a `pr_url` -- both `merged` and
    `target_reachability_observed` must independently be True."""
    return (
        receipt.get("verdict") == VERDICT_PASS
        and bool(receipt.get("merged"))
        and bool(receipt.get("target_reachability_observed"))
        and bool(receipt.get("delivered"))
    )


def to_stage_receipt(
    delivery_receipt: Mapping[str, Any],
    *,
    receipt_id: str,
    agent_instance_id: str,
    attempt_ordinal: int = 1,
    context_hash: str = "0" * 64,
    manifest_hash: str = "0" * 64,
) -> Dict[str, Any]:
    """Project the #429 receipt into a `simplicio.stage-receipt/v1`-shaped dict for the
    `delivering` stage owned by the `delivery_agent` role (see `stage_agents.py`).

    ``context_hash``/``manifest_hash`` default to an all-zero placeholder when
    the caller doesn't have the coordinator's real values on hand -- a real
    coordinator-driven caller MUST pass the actual `AgentInstance` values, or
    `stage_agents.validate_receipt()` will (correctly) reject the mismatch.
    """
    verdict_map = {VERDICT_PASS: "pass", VERDICT_BLOCKED: "blocked", VERDICT_FAILED: "fail"}
    verdict = verdict_map.get(delivery_receipt.get("verdict"), "blocked")
    accepted = verdict == "pass"
    ts = _now()
    receipt: Dict[str, Any] = {
        "schema": "simplicio.stage-receipt/v1",
        "receipt_id": str(receipt_id),
        "agent_instance_id": str(agent_instance_id),
        "role_id": DELIVERY_AGENT_ROLE_ID,
        "stage_id": "delivering",
        "run_id": str(delivery_receipt.get("run_id") or ""),
        "task_id": str(delivery_receipt.get("task_id") or ""),
        "attempt_id": str(delivery_receipt.get("attempt_id") or ""),
        "attempt_ordinal": int(attempt_ordinal),
        "fence": str(delivery_receipt.get("fence") or ""),
        "plan_revision": int(delivery_receipt.get("plan_revision") or 0),
        "created_at": ts,
        "observed_at": ts,
        "ttl_seconds": 3600,
        "context_hash": str(context_hash),
        "manifest_hash": str(manifest_hash),
        "verdict": verdict,
        "evidence_refs": [str(delivery_receipt.get("pr_url") or "n/a")],
        "accepted": accepted,
        "reason_code": str(delivery_receipt.get("reason_code") or "ok"),
        "input_hash": content_hash(delivery_receipt.get("idempotency_key") or ""),
        "output_hash": str(delivery_receipt.get("receipt_hash") or content_hash(None)),
        "previous_receipt_hashes": [],
        "covered_acceptance_criteria": ["n/a"],
        "commands": ["n/a"],
        "exit_codes": {},
        "artifact_refs": [str(delivery_receipt.get("pr_url") or "")] if delivery_receipt.get("pr_url") else [],
        "next_stage_recommendation": "unknown",
    }
    if not accepted:
        receipt["rejection_reason"] = str(delivery_receipt.get("reason_code") or "not_accepted")
    payload = dict(receipt)
    receipt["integrity_hash"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()
    return receipt


__all__ = [
    "DELIVERY_STAGE_RECEIPT_SCHEMA",
    "DELIVERY_AGENT_ROLE_ID",
    "VERDICT_PASS",
    "VERDICT_BLOCKED",
    "VERDICT_FAILED",
    "SAGA_EVENTS",
    "FORBIDDEN_RECEIPT_SCHEMAS",
    "DeliveryAgentError",
    "PreconditionError",
    "IdentityDriftError",
    "ForbiddenReceiptError",
    "BaseDriftRepairError",
    "content_hash",
    "assert_receipt_schema_allowed",
    "compute_identity",
    "check_identity_match",
    "assert_identity_consistent",
    "detect_base_drift",
    "DeliveryPreconditions",
    "check_preconditions",
    "assert_preconditions_ok",
    "idempotency_key",
    "IdempotencyLedger",
    "composed_verification",
    "DeliveryAdapter",
    "GitHubDeliveryAdapter",
    "SagaStep",
    "DeliverySaga",
    "steps_ok",
    "find_step",
    "repair_handoff",
    "regression_reopen_stub",
    "delivery_status",
    "build_delivery_stage_receipt",
    "receipt_is_delivered",
    "to_stage_receipt",
]
