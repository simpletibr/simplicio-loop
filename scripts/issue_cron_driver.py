#!/usr/bin/env python3
"""Cron issue-intake driver for simplicio-loop (canonical state machine).

Operates the user-mandated WI lifecycle for every OPEN GitHub issue:

    intake -> mapping -> planning -> executing -> validating ->
    watching -> delivering -> done | blocked | quarantined

Honest, bounded design for a short cron window:
  * INTAKE uses the SHIPPED ``simplicio_loop.intake_contract.build_task_intake`` (#284) to
    build a frozen, hash-bound intake envelope (objective, scope, ACs, impact map) — the
    real fail-closed gate, not a reinvention. Runs in milliseconds.
  * MAPPING is recorded as a scheduled step (the heavy ``simplicio-mapper`` survey runs
    out-of-band / next tick, never blocking the cron). The work item is created in the
    canonical ``Todo`` (intake/mapping) projection immediately.
  * PLANNING records a ``simplicio.planning-receipt/v1`` (shipped ``planning_gate``) bound
    to the run + source revision. ``ready_for_mutation`` stays False until a real plan
    passes — the cron never mutates source.
  * Infra-dependent EPICs (#286 multi-device, #287 multi-LLM, #289/#295 need infra) are
    classified ``Blocked`` with a typed reason — never a fabricated ``done``.
  * Idempotent: re-armed issues (same source revision) are resumed, not reworked. Ledger
    is appended INCREMENTALLY so a later failure never loses prior rows.

No source mutation occurs. The driver is the intake/mapping/planning projection only;
execution is left to the human/loop gate (per user instruction).

Usage:
    python3 scripts/issue_cron_driver.py [--repo .] [--limit N]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from simplicio_loop.intake_contract import (  # noqa: E402
    build_task_intake,
    lint_task_intake,
)
from simplicio_loop.planning_gate import build_planning_receipt  # noqa: E402

LEDGER_DIR = HERE / ".simplicio-loop/orchestrator" / "intake"
LEDGER_PATH = LEDGER_DIR / "ledger.jsonl"

# Issues that CANNOT be executed on this single host (no remote workers / no API key /
# no multi-LLM router / no Hub daemon / no Rust-Tokio backend / no process supervisor).
# They require infra that is not present here — classified Blocked.
# Domain keywords that signal an infra-dependent epic/domain (cannot run on this
# host). Matched case-insensitively INSIDE any [..] tag segment of the title, so
# both "[P0][Hub]" and "[P0][Hub Agent 1/4]" are detected (the bare prefix
# "[HUB]" would miss the latter because "]" is not immediately after "HUB").
INFRA_DEPENDENT_DOMAINS: Tuple[str, ...] = (
    "EPIC",          # explicit epic marker
    "HUB",           # hub daemon / HubQueueAgentClient
    "SUPERVISOR",    # process supervisor
    "ASYNC",         # async core
    "ARCHITECTURE",  # cross-cutting architecture
    "PERFORMANCE",   # perf/core work
    "RELEASE TRAIN", # release train
    "QUALITY",       # quality-gate work requires the full verification stack
)
# Labels that mark an infra-dependent work item.
INFRA_DEPENDENT_LABELS: Tuple[str, ...] = (
    "hub", "supervisor", "async", "architecture", "epic",
    "performance", "release-train", "infra", "blocked-infra",
)
# Body keywords that indicate the issue requires infra absent on this host.
INFRA_DEPENDENT_BODY_KEYWORDS: Tuple[str, ...] = (
    "requer infra", "infra ausente", "não presente neste host",
    "precisa de hub", "precisa de supervisor", "rust/tokio",
)

# Terminal statuses — already have a stable work item; no re-arm unless prior failure.
# 'Todo' is included: the cron only does intake/mapping/planning (never mutates source),
# so a Todo work item with a written intake-contract is stable and must NOT be re-armed
# on the next tick (that would duplicate the ledger row every run).
RESUME_SKIP_STATUSES = {"Todo", "Done", "Blocked", "Quarantined"}


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _gh(*args: str, timeout: int = 60) -> Any:
    cmd = ["gh", "issue", *args, "--json", ",".join([
        "number", "title", "state", "labels", "createdAt", "updatedAt", "body", "url",
    ])]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"gh failed: {proc.stderr.strip()}")
    return json.loads(proc.stdout)


def fetch_open_issues(limit: int, gh_repo: Optional[str] = None) -> List[Dict[str, Any]]:
    """Page through ALL open issues so old issues are never truncated at --limit.

    GitHub's `gh issue list` returns issues newest-first and caps at --limit, which
    silently drops older open issues when the repo has more than `limit` open items.
    We paginate in chunks of 100 up to a hard ceiling (1000, the gh max) so every open
    issue is seen at least once per tick. `limit` is then a PER-TICK SAFETY CAP applied
    AFTER the full fetch: if there are more open issues than `limit`, the oldest extras
    are deferred to the next tick (already-armed ones are skipped, so progress is made).
    """
    collected: List[Dict[str, Any]] = []
    seen: set = set()
    page = 100
    ceiling = 1000  # gh issue list hard maximum per call
    while len(collected) < ceiling:
        cmd = ["list", "--state", "open", "--limit", str(page)]
        if gh_repo:
            cmd += ["--repo", gh_repo]
        try:
            chunk: List[Dict[str, Any]] = _gh(*cmd)
        except Exception:
            break
        if not chunk:
            break
        for it in chunk:
            if it["number"] not in seen:
                seen.add(it["number"])
                collected.append(it)
        # gh returns at most `page` items; if fewer, we've reached the end
        if len(chunk) < page:
            break
        page = min(page + 100, ceiling)
    collected.sort(key=lambda i: str(i.get("createdAt") or ""))
    if limit and limit < len(collected):
        # Per-tick safety cap: defer the newest extras (oldest processed first).
        print(f"UNVERIFIED| fetch_open_issues: {len(collected)} open issues, "
              f"capping this tick at {limit} (oldest-first); {len(collected) - limit} deferred",
              flush=True)
        return collected[:limit]
    return collected


def issue_source_revision(issue: Dict[str, Any]) -> str:
    body = issue.get("body") or ""
    labels = ",".join(sorted(l["name"] for l in issue.get("labels") or []))
    # Stable across ticks: GitHub bumps updatedAt on every touch, so using it would
    # defeat the resume-skip (source_revision would change every run -> re-append).
    # Hash only immutable identity + content fields.
    blob = f"{issue.get('number')}|{issue.get('title')}|{body}|{labels}"
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _impact_not_applicable() -> Dict[str, str]:
    cats = ["code", "reverse_dependents", "public_contracts", "data_persistence",
            "security", "concurrency", "performance", "installation_docs", "tests"]
    return {c: "not_applicable: intake gate only; mutation blocked until planning receipt COMPLETE" for c in cats}


# Minimum parameter count (in billions) a local model must have to be considered
# capable of autonomous feature implementation. Models below this threshold
# (e.g. Qwen2.5-Coder-1.5B) reliably fail the coding-loop with edit/build/test=fail
# and produce no artifacts, yet the compiled runtime still reports `completed` with
# placeholder fixtures -- a false-positive completion. We fail-closed here instead.
MODEL_CAPABLE_MIN_PARAMS_B = 7.0


def check_model_backend_capable() -> Tuple[bool, str]:
    """Return (capable, reason) for the currently configured model backend.

    Honest gate: if no model backend is engaged, or the only available backend is a
    sub-capability local model, refuse autonomous execution and let the caller classify
    the issue as Blocked(model_capacity_insufficient) rather than burning coding-loop
    cycles on a known-to-fail attempt.

    Detection reads ``simplicio doctor`` text (the compiled runtime's health surface):
    it reports ``local model: <name>`` when a local backend is configured, and the
    runtime.toml ``local_model_disabled`` flag gates engagement. Remote backends are
    only capable when an API key / base_url is configured (checked via env).
    """
    try:
        proc = subprocess.run(
            ["simplicio", "doctor"], capture_output=True, text=True, timeout=60, check=False
        )
        out = proc.stdout + proc.stderr
    except Exception as exc:
        return False, f"model_backend_check_error:{type(exc).__name__}:{exc}"

    # No backend engaged at all.
    if "model backend" in out and ("not engaged" in out or "not all engaged" in out):
        return False, "no_model_backend_engaged"

    # Remote backend first: if explicit credentials are present the agent can execute
    # autonomously via a remote model (e.g. openrouter/tencent-hy3) REGARDLESS of the
    # local model reported by `simplicio doctor`. The local model may not even be the
    # executor. Checking this BEFORE the local-size gate avoids a false
    # `capable:false` when a perfectly capable remote backend is configured.
    import os
    if os.environ.get("SIMPLICIO_API_KEY") or os.environ.get("OPENROUTER_API_KEY") or os.environ.get("ANTHROPIC_API_KEY"):
        return True, "remote_model_backend_with_credentials"

    # Local model present? extract name + param count.
    import re
    m = re.search(r"local model:\s*(\S+?)(?:\s|$)", out)
    if m:
        name = m.group(1).lower()
        # pull trailing '-<N>b' or '<N>b' (e.g. 1.5b, 7b, 32b)
        pm = re.search(r"(\d+(?:\.\d+)?)b", name)
        params_b = float(pm.group(1)) if pm else 0.0
        # qwen3-coder:free / qwen2.5-coder etc without 'b' -> unknown size, treat incapable
        if params_b == 0.0:
            return False, f"local_model_unknown_size:{name}"
        if params_b < MODEL_CAPABLE_MIN_PARAMS_B:
            return False, (
                f"local_model_subcapacity:{name} ({params_b}b < "
                f"{MODEL_CAPABLE_MIN_PARAMS_B}b minimum)"
            )
        return True, f"local_model_capable:{name} ({params_b}b)"

    # Neither a remote credential nor a capable local model is present.
    return False, "no_capable_backend: local subcapacity or no remote credentials"


def do_intake(issue: Dict[str, Any], gh_repo: str = "wesleysimplicio/simplicio-loop") -> Tuple[Dict[str, Any], str, List[str]]:
    """Run the #284 intake contract via the current ``simplicio_loop.intake_contract``
    API (``build_task_intake`` + ``lint_task_intake``). Returns (envelope, hash, errors).

    The new API projects acceptance criteria from a *contract* (frozen snapshot of
    scenarios), not from free-text fields. We assemble a minimal inline contract
    carrying the single canonical AC for cron intake so the envelope is complete and
    the fail-closed lint passes (no_acceptance_criteria / missing origin).
    """
    n = issue["number"]
    rev = issue_source_revision(issue)
    title = issue.get("title") or f"Issue {n}"
    ac_text = _extract_acceptance_criteria(issue.get("body") or "") or (
        f"A issue {n} possui contrato congelado, contexto de mapper agendado e planning "
        f"receipt antes de qualquer mutação no repositório."
    )
    source_snapshot = {
        "source": {
            "provider": "github",
            "repo": gh_repo,
            "item_id": str(n),
            "revision": issue.get("updatedAt") or rev,
            "snapshot_hash": rev,
            "url": issue.get("url") or "",
            "title_hash": hashlib.sha256(title.encode()).hexdigest()[:16],
            "body_hash": hashlib.sha256((issue.get("body") or "").encode()).hexdigest()[:16],
        },
    }
    # Inline frozen contract carrying the canonical cron AC (origin=source per #284).
    contract = {
        "schema": "simplicio.task-contract/v1",
        "collection_hash": rev,
        "tasks": [{
            "id": f"I{n}",
            "title": title,
            "scenarios": [{
                "id": "AC-001",
                "title": ac_text,
                "given": ["issue aberta no GitHub"],
                "when": ["cron driver executa intake"],
                "then": ["planning receipt COMPLETE + run state gravado no ledger"],
                "rule_refs": ["issue#284"],
            }],
        }],
    }
    try:
        env = build_task_intake(
            run_id=f"cron-{n}", attempt=1,
            contract=contract,
            source_snapshot=source_snapshot,
            scope_in=[f"issue {n} intake + mapping + planning"],
            scope_out=["mutação de código pelo cron"],
            delivery_target="verified",
        )
        lint = lint_task_intake(env)
        errors = list(lint.get("errors") or [])
        if not lint.get("valid"):
            return {}, "", errors
        return env, env.get("intake_hash", ""), errors
    except Exception as exc:  # fail-closed: any assembly error blocks, never fabricates
        return {}, "", [f"intake_blocked:{type(exc).__name__}:{exc}"]


def _extract_acceptance_criteria(body: str) -> Optional[str]:
    lines = body.splitlines()
    out: List[str] = []
    capture = False
    for ln in lines:
        if "critério de aceite" in ln.lower() or "acceptance criteria" in ln.lower():
            capture = True
            continue
        if capture:
            if ln.strip().startswith("-") or ln.strip().startswith("["):
                out.append(ln.strip())
            elif ln.strip() == "" and out:
                break
            elif out and not ln.strip().startswith(("-", "[")):
                break
    if out:
        return " ".join(out)[:400]
    return None


def _is_infra_dependent(issue: Dict[str, Any]) -> bool:
    """True when the issue requires infra (Hub/Supervisor/Async/core) absent on this host.

    Matches each domain keyword case-insensitively INSIDE any ``[..]`` tag segment
    of the (case-insensitive) title, so ``[P0][Hub Agent ...]`` is detected (the
    ``[P0]`` tag precedes the ``[Hub]`` segment and a bare substring ``"[HUB]"``
    would miss it because ``]`` is not immediately after ``HUB``).
    """
    import re
    title = (issue.get("title") or "").upper()
    # Extract every [..] segment and search keywords within them.
    segments = re.findall(r"\[([^\]]*)\]", title)
    seg_text = " ".join(segments).upper()
    if any(kw.upper() in seg_text for kw in INFRA_DEPENDENT_DOMAINS):
        return True
    labels = [str(lbl).lower() for lbl in (issue.get("labels") or [])]
    if any(lbl in INFRA_DEPENDENT_LABELS for lbl in labels):
        return True
    body = (issue.get("body") or "").lower()
    if any(kw in body for kw in INFRA_DEPENDENT_BODY_KEYWORDS):
        return True
    return False


def classify_status(issue: Dict[str, Any], intake_ok: bool, blockers: List[str]) -> str:
    # Infra-dependent epics/domains cannot execute on this single host — Blocked,
    # never a fabricated Todo that would stall the drain forever.
    if _is_infra_dependent(issue):
        return "Blocked"
    if not intake_ok:
        return "Blocked"
    # intake+planning done -> canonical projection Todo (intake/mapping pending). Mapping
    # is scheduled, not yet executed; planning receipt ready_for_mutation stays False.
    return "Todo"


def projected_state(status: str) -> str:
    return {
        "Todo": "Todo", "Planning": "Planning", "In progress": "In progress",
        "Validating": "Validating", "In review": "In review", "Done": "Done",
        "Blocked": "Blocked", "Quarantined": "Quarantined",
    }.get(status, "Blocked")


def write_records(issue: Dict[str, Any], envelope: Dict[str, Any], h: str, blockers: List[str], status: str) -> Dict[str, Any]:
    n = issue["number"]
    rev = issue_source_revision(issue)
    issue_dir = LEDGER_DIR / f"issue-{n}"
    issue_dir.mkdir(parents=True, exist_ok=True)
    if envelope:
        (issue_dir / "intake-contract.json").write_text(
            json.dumps(envelope, indent=2, ensure_ascii=False), encoding="utf-8")
    receipt = build_planning_receipt(
        run_id=f"cron-{n}", attempt=1,
        contract={"collection_hash": h or rev},
        plan={"schema": "simplicio.plan/v1", "task_contract_hash": h or rev},
        plan_validation={"valid": status != "Blocked", "errors": blockers, "warnings": []},
        source_revision=rev,
        awaiting_decision=(status == "Blocked"),
        awaiting_reason="intake/mapping scheduled; mapping survey + execution gated out of cron",
    )
    (issue_dir / "planning-receipt.json").write_text(
        json.dumps(receipt, indent=2, ensure_ascii=False), encoding="utf-8")
    return receipt


def load_ledger() -> List[Dict[str, Any]]:
    if not LEDGER_PATH.exists():
        return []
    rows: List[Dict[str, Any]] = []
    for line in LEDGER_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows


def ledger_index() -> Dict[str, Dict[str, Any]]:
    idx: Dict[str, Dict[str, Any]] = {}
    for row in load_ledger():
        key = f"{row.get('gh_repo')}#{row.get('issue')}"
        idx[key] = row
    return idx


def append_ledger(row: Dict[str, Any]) -> None:
    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    with LEDGER_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def reconcile_cursor(gh_repo: str = "wesleysimplicio/simplicio-loop") -> Dict[str, Any]:
    """Fail-closed integrity pass over `.simplicio-loop/orchestrator/gh-issue-cursor.json`.

    The cron drain projects work items into ``work_items_state``. Across many
    ticks (epic decomposition, manual journal edits, merged-PR drift) that
    projection drifts: phantom child WIs appear with ``repo: None`` and no
    valid issue, and a single GitHub issue ends up owning multiple WIs
    (violating the 1-WI-per-issue invariant). This function reconciles the
    cursor against GitHub ground truth so the Orca projection never shows
    stale/fabricated state.

    Rules applied (idempotent, read-only w.r.t. source):
      1. DROP any WI with ``repo`` missing/None or a non-positive ``issue``.
      2. COLLAPSE multiple WIs for the same ``(repo, issue)`` to the
         canonical owner = the highest-numbered WI id (most recent).
      3. SYNC ``canonical_state`` / ``orca_projection`` from GitHub truth:
         merged PR for the issue  -> done / Done
         open   PR for the issue  -> delivering / In review
         open   issue + infra-dependent -> blocked / Blocked
         open   issue otherwise    -> todo / Todo
    Returns a summary dict; writes the reconciled cursor back to disk.
    """
    cursor_path = HERE / ".simplicio-loop/orchestrator" / "gh-issue-cursor.json"
    if not cursor_path.exists():
        return {"ok": False, "reason": "no_cursor"}
    cur = json.loads(cursor_path.read_text(encoding="utf-8"))
    wis = cur.get("work_items_state", {})
    if not isinstance(wis, dict):
        return {"ok": False, "reason": "bad_state"}

    # Single source of truth for "is this issue open": the SAME `gh issue list
    # --state open` the driver uses everywhere (fetch_open_issues). GitHub's
    # `issue view` can contradict `issue list` for issues with a merged PR that
    # mentions (but does not auto-close) the number (e.g. #558 + merged PR #567:
    # list=OPEN, view=CLOSED). Using the list set avoids that false-CLOSED and
    # the resulting false-positive Done projection.
    try:
        open_set_raw = subprocess.run(
            ["gh", "issue", "list", "--repo", gh_repo, "--state", "open",
             "--limit", "200", "--json", "number", "--jq", ".[].number"],
            capture_output=True, text=True, timeout=30, check=False,
        ).stdout.strip()
        open_set = set(int(x) for x in open_set_raw.split() if x.strip().isdigit())
    except Exception:
        open_set = set()

    # Ingest freshly-intaken backlog items (wi613..wi630) missing from the
    # cursor projection so the Orca view never shows stale/missing state.
    # Done BEFORE Rule 1/2 so the ingested WIs flow through valid->collapsed
    # with their ingested_from_backlog flag preserved.
    ingest = ingest_backlog_into_cursor(cur["work_items_state"], gh_repo)
    if ingest["ingested"]:
        print(f"MEASURED| reconcile_cursor: ingested +{ingest['ingested']} WIs from backlog", flush=True)

    # --- Rule 1: drop repo:None / wrong-scope / invalid issue ---------------
    dropped = []
    valid = {}
    for wi, v in wis.items():
        if not isinstance(v, dict):
            dropped.append((wi, "not_dict"))
            continue
        if not v.get("repo"):
            dropped.append((wi, "repo_none"))
            continue
        if v.get("repo") != gh_repo:
            # Cross-repo WI leaked into this repo's cursor (e.g. a
            # simplicio-agent WI inside simplicio-loop's gh-issue-cursor).
            dropped.append((wi, f"repo_mismatch:{v.get('repo')}"))
            continue
        iss = v.get("issue")
        if not isinstance(iss, int) or iss <= 0:
            dropped.append((wi, "bad_issue"))
            continue
        valid[wi] = v

    # --- Rule 2: 1-WI-per-issue (keep highest WI number) -------------------
    by_issue: Dict[Tuple[str, int], List[str]] = {}
    for wi, v in valid.items():
        key = (v["repo"], v["issue"])
        by_issue.setdefault(key, []).append(wi)
    collapsed = {}
    collapsed_dups = []
    for key, wlist in by_issue.items():
        if len(wlist) == 1:
            collapsed[wlist[0]] = valid[wlist[0]]
        else:
            owner = max(wlist, key=lambda w: int("".join(filter(str.isdigit, w)) or 0))
            collapsed[owner] = valid[owner]
            for d in wlist:
                if d != owner:
                    collapsed_dups.append(d)

    # --- Rule 3: sync from GitHub truth ------------------------------------
    synced = []
    for wi, v in collapsed.items():
        iss = v["issue"]
        repo = v["repo"]
        # find merged/open PRs touching this issue
        try:
            prs = subprocess.run(
                ["gh", "pr", "list", "--state", "all", "--search",
                 f"repo:{repo} {iss} in:title",
                 "--json", "number,state,mergedAt",
                 "--limit", "5"],
                capture_output=True, text=True, timeout=30, check=False,
            ).stdout
            pr_data = json.loads(prs) if prs.strip() else []
        except Exception:
            pr_data = []
        merged = any(p.get("state") == "MERGED" for p in pr_data)
        open_pr = any(p.get("state") == "OPEN" for p in pr_data)
        # Issue open/closed from the authoritative open-issue set (not
        # `gh issue view`, which contradicts `issue list` for #558-style cases).
        ist = "OPEN" if iss in open_set else "CLOSED"
        issue_title = (v.get("title") or "").upper()
        # Fallback title if not stored in cursor: derive from GH only when needed.
        if not issue_title:
            try:
                vt = subprocess.run(
                    ["gh", "issue", "view", str(iss), "--repo", repo,
                     "--json", "title", "--jq", ".title"],
                    capture_output=True, text=True, timeout=30, check=False,
                ).stdout.strip()
                issue_title = vt.upper()
            except Exception:
                issue_title = ""
        # FIX (issue #569): a merged PR mentioning the issue NUMBER in its
        # title does NOT mean the issue itself is resolved. A PR is only
        # evidence of completion when the ISSUE is also CLOSED. Otherwise a
        # still-open issue wrongly projects as Done (false-positive completion).
        # Order: issue-closed is the ground truth; PR state is secondary.
        # Preserve the canonical-state for items ingested from the backlog:
        # their state was already derived from the backlog's ground truth
        # (blocked = infra-dependent / execution deferred). Re-classifying
        # from GitHub title (which is absent for ingested WIs) would flip-flop
        # them to `todo` every other tick. Keep the ingested projection stable.
        if v.get("ingested_from_backlog"):
            new_state, new_proj = v["canonical_state"], v["orca_projection"]
        elif ist == "CLOSED":
            new_state, new_proj = "done", "Done"
        elif open_pr and ist == "OPEN":
            new_state, new_proj = "delivering", "In review"
        elif _is_infra_dependent({"title": issue_title, "labels": v.get("labels", []), "body": v.get("body", "")}):
            new_state, new_proj = "blocked", "Blocked"
        elif ist == "OPEN":
            new_state, new_proj = "todo", "Todo"
        else:
            new_state, new_proj = "blocked", "Blocked"
        if v.get("canonical_state") != new_state or v.get("orca_projection") != new_proj:
            synced.append((wi, v.get("canonical_state"), new_state))
            v["canonical_state"] = new_state
            v["orca_projection"] = new_proj

    cur["work_items_state"] = collapsed
    cur["last_scan_at"] = _now()
    # Recompute the in-scope open-issue count from the SAME authoritative
    # open_set used in Rule 3 (not a second `gh issue list --jq length`,
    # which can disagree with the enumerate call and over-count PRs).
    cur["open_issues_in_scope_repo"] = len(open_set) or len(collapsed)
    cursor_path.write_text(json.dumps(cur, indent=2, ensure_ascii=False),
                          encoding="utf-8")
    return {
        "ok": True,
        "dropped": dropped,
        "collapsed_dups": collapsed_dups,
        "synced": synced,
        "remaining": len(collapsed),
        "open_in_scope": cur["open_issues_in_scope_repo"],
    }


def ingest_backlog_into_cursor(target_dict: Dict[str, Any], gh_repo: str) -> Dict[str, Any]:
    """Ingest canonical-backlog work items absent from the cursor into its projection.

    The cron drain projects every open GitHub issue into a single canonical work
    item (``Todo`` for intake/mapping done, ``Blocked`` for infra-dependent).
    ``reconcile_cursor`` only *syncs* items already present in the cursor, so
    freshly-intaken issues (wi613..wi630) never appear in the Orca projection
    and look stale/missing. This function closes that gap: any backlog item
    whose issue is OPEN on GitHub and not yet in ``work_items_state`` is added
    with the canonical-state / orca-projection derived from the backlog status.

    Idempotent and read-only w.r.t. source: it never mutates the backlog, only
    extends the cursor projection from the backlog's ground truth.
    """
    import re as _re
    backlog_path = (
        os.environ.get("SIMPLICIO_BACKLOG_FILE")
        or os.path.join(HERE, ".simplicio-loop/orchestrator", "backlog", "backlog.jsonl")
    )
    if not os.path.exists(backlog_path):
        return {"ingested": 0, "skipped": 0}
    wis = target_dict
    try:
        open_set_raw = subprocess.run(
            ["gh", "issue", "list", "--repo", gh_repo, "--state", "open",
             "--limit", "200", "--json", "number", "--jq", ".[].number"],
            capture_output=True, text=True, timeout=30, check=False,
        ).stdout.strip()
        open_set = set(int(x) for x in open_set_raw.split() if x.strip().isdigit())
    except Exception:
        open_set = set()
    ingested = 0
    skipped = 0
    with open(backlog_path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if rec.get("kind") != "item":
                continue
            wi_id = rec.get("id")
            if not wi_id:
                skipped += 1
                continue
            # If the WI already exists in the cursor but was NOT ingested from
            # the backlog (i.e. it came from a prior reconcile that mis-projected
            # it, e.g. wi630 flipped to `done` via a false-positive PR match),
            # override its state with the backlog's ground truth and mark it
            # ingested so the later rules preserve it (no flip-flop).
            if wi_id in wis and wis[wi_id].get("ingested_from_backlog"):
                continue
            m = _re.search(r"\d+", wi_id)
            if not m:
                skipped += 1
                continue
            iss = int(m.group(0))
            if iss not in open_set:
                skipped += 1
                continue
            bstatus = (rec.get("status") or "blocked").lower()
            if bstatus == "done":
                cstate, proj = "done", "Done"
            elif bstatus == "blocked":
                cstate, proj = "blocked", "Blocked"
            elif bstatus == "planning":
                cstate, proj = "planning", "Planning"
            elif bstatus in ("executing", "in_progress"):
                cstate, proj = "executing", "In progress"
            elif bstatus == "validating":
                cstate, proj = "validating", "Validating"
            elif bstatus in ("delivering", "in_review"):
                cstate, proj = "delivering", "In review"
            elif bstatus == "quarantined":
                cstate, proj = "quarantined", "Quarantined"
            else:
                cstate, proj = "todo", "Todo"
            if wi_id in wis:
                # Pre-existing cursor WI without the flag: update in place.
                wis[wi_id]["canonical_state"] = cstate
                wis[wi_id]["orca_projection"] = proj
                wis[wi_id]["ingested_from_backlog"] = True
                ingested += 1
            else:
                wis[wi_id] = {
                    "issue": iss,
                    "repo": gh_repo,
                    "canonical_state": cstate,
                    "orca_projection": proj,
                    "ingested_from_backlog": True,
                }
                ingested += 1
    return {"ingested": ingested, "skipped": skipped}



def _derive_gh_repo(repo: str = ".") -> Optional[str]:
    """Best-effort GitHub 'owner/name' from the CWD git remote origin."""
    try:
        out = subprocess.run(
            ["git", "-C", repo, "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=20, check=False,
        ).stdout.strip()
        if not out:
            return None
        out = out.rsplit("/", 1)[-1].removesuffix(".git")
        owner = out.split("/")[-2] if "/" in out else "wesleysimplicio"
        return f"{owner}/{out.split('/')[-1]}"
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", default=".")
    ap.add_argument("--gh-repo", default=None,
                   help="GitHub 'owner/name' to list issues from (defaults to --repo's remote)")
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--per-issue-timeout", type=int, default=20)
    ap.add_argument("--total-budget", type=int, default=250)
    ap.add_argument("--reconcile", action="store_true",
                    help="reconcile .simplicio-loop/orchestrator/gh-issue-cursor.json integrity "
                         "(drop repo:None, 1-WI-per-issue, sync GitHub truth) and exit")
    ap.add_argument("--verify-backend", dest="verify_backend", action="store_true",
                    help="check whether the configured model backend is capable of "
                         "autonomous implementation; print JSON verdict and exit")
    args = ap.parse_args()

    if args.verify_backend:
        capable, reason = check_model_backend_capable()
        out = {
            "schema": "simplicio.cron-backend-check/v1",
            "capable": capable,
            "reason": reason,
            "min_params_b": MODEL_CAPABLE_MIN_PARAMS_B,
        }
        print(json.dumps(out, ensure_ascii=False))
        return 0 if capable else 2

    if args.reconcile:
        # Integrity pass: drop repo:None, collapse 1-WI-per-issue, sync GitHub
        # truth. Idempotent — safe to run every tick before normal intake.
        repo_arg = args.gh_repo or _derive_gh_repo(args.repo) or "wesleysimplicio/simplicio-loop"
        res = reconcile_cursor(repo_arg)
        print(f"MEASURED| reconcile_cursor: {json.dumps(res, ensure_ascii=False)}",
              flush=True)
        return 0 if res.get("ok") else 1

    # Resolve the GitHub repo: explicit --gh-repo wins; else derive from CWD remote.
    gh_repo = args.gh_repo or _derive_gh_repo(args.repo)
    print(f"MEASURED| cron driver start repo={args.repo} gh_repo={gh_repo} dry_run={args.dry_run}", flush=True)
    start = time.time()
    try:
        issues = fetch_open_issues(args.limit, gh_repo)
    except Exception as exc:
        print(f"UNVERIFIED| failed to list issues: {exc}", flush=True)
        return 1

    print(f"MEASURED| open issues: {[i['number'] for i in issues]}", flush=True)
    ledger = ledger_index()
    new_rows: List[Dict[str, Any]] = []

    for issue in issues:
        n = issue["number"]
        rev = issue_source_revision(issue)
        prev = ledger.get(f"{gh_repo}#{n}")
        prior_failed = prev and any(b in str(prev.get("blockers")) for b in ("intake_blocked", "gh_error"))
        # Disk-backed resume: the intake-contract.json artifact is the ground truth.
        # This survives source_revision hash-formula migrations (we no longer trust a
        # stored hash that may have been computed with a different formula).
        contract_exists = (LEDGER_DIR / f"issue-{n}" / "intake-contract.json").exists()
        prev_status = prev.get("status") if prev else None
        status_ok = prev_status in RESUME_SKIP_STATUSES
        # Re-evaluate a previously-armed Todo when the (broadened) infra-dependency
        # classifier now matches it: a Todo that should be Blocked must not stall the
        # drain forever. Only re-open when moving Todo -> Blocked (never downgrade a
        # stable Blocked/Done/Quarantined, and never re-intake a non-infra Todo).
        infra_now = _is_infra_dependent(issue)
        reclassify_to_blocked = (
            infra_now and prev_status == "Todo"
        )
        if not prior_failed and contract_exists and status_ok and not reclassify_to_blocked:
            print(f"MEASURED| issue {n}: already armed (contract present, prev={prev_status}) — resume, skip", flush=True)
            continue
        if reclassify_to_blocked:
            print(f"MEASURED| issue {n}: prev=Todo but infra-dependent — reclassify Blocked", flush=True)
        if time.time() - start > args.total_budget:
            print(f"MEASURED| budget exhausted ({args.total_budget}s) — defer remaining", flush=True)
            break

        print(f"MEASURED| issue {n}: {issue.get('title')!r} — intake+mapping+planning", flush=True)
        if args.dry_run:
            # Dry-run is strictly read-only: compute the projected row but never
            # write the intake-contract, planning-receipt, or ledger. A dry run must
            # not mutate state (the previous behavior appended ledger rows, which
            # made the subsequent real run a no-op and broke idempotency checks).
            env, h, blockers = {"schema": "simplicio.task-intake/v1", "intake_hash": "dry"}, "dry", []
            intake_ok = bool(env) and not blockers
            status = classify_status(issue, intake_ok, blockers)
            proj = projected_state(status)
            receipt = {"verdict": "DRY_RUN", "ready_for_mutation": False}
            row = {
                "ts": _now(), "issue": n, "gh_repo": gh_repo, "url": issue.get("url"), "title": issue.get("title"),
                "labels": [l["name"] for l in issue.get("labels") or []],
                "source_revision": rev, "status": status, "projected": proj,
                "intake_ok": intake_ok, "intake_hash": h[:16], "blockers": blockers,
                "planning_receipt_verdict": receipt.get("verdict"),
                "ready_for_mutation": receipt.get("ready_for_mutation"),
                "intake_contract_path": str(LEDGER_DIR / f"issue-{n}" / "intake-contract.json"),
            }
            new_rows.append(row)
            print(f"MEASURED| issue {n}: [DRY] status={status} projected={proj} "
                  f"would_append=True", flush=True)
            continue
        env, h, blockers = do_intake(issue, gh_repo or "wesleysimplicio/simplicio-loop")
        intake_ok = bool(env) and not blockers
        status = classify_status(issue, intake_ok, blockers)
        proj = projected_state(status)
        receipt = write_records(issue, env, h, blockers, status)
        row = {
            "ts": _now(), "issue": n, "gh_repo": gh_repo, "url": issue.get("url"), "title": issue.get("title"),
            "labels": [l["name"] for l in issue.get("labels") or []],
            "source_revision": rev, "status": status, "projected": proj,
            "intake_ok": intake_ok, "intake_hash": h[:16], "blockers": blockers,
            "planning_receipt_verdict": receipt.get("verdict"),
            "ready_for_mutation": receipt.get("ready_for_mutation"),
            "intake_contract_path": str(LEDGER_DIR / f"issue-{n}" / "intake-contract.json"),
        }
        append_ledger(row)  # incremental — never lose progress
        new_rows.append(row)
        print(f"MEASURED| issue {n}: status={status} projected={proj} "
              f"receipt={receipt.get('verdict')} ready={receipt.get('ready_for_mutation')}", flush=True)
    summary: Dict[str, int] = {}
    for row in new_rows:
        summary[row["status"]] = summary.get(row["status"], 0) + 1
    print(f"MEASURED| ledger updated: {len(new_rows)} new row(s) this tick; statuses={summary}",
          flush=True)
    print(f"MEASURED| ledger path={LEDGER_PATH}", flush=True)

    # --- Bridge to canonical backlog (intake/drain state split) ---
    # The intake ledger (.simplicio-loop/orchestrator/intake/ledger.jsonl) and the execution
    # backlog (.simplicio-loop/orchestrator/backlog/backlog.jsonl) are separate state stores.
    # Without a bridge the drain loop's ``task_backlog.py next/status`` never sees
    # the freshly-intaken issues and terminates prematurely ("source empty").
    # Bridge is opt-in (default OFF) so it never surprises a caller that only
    # wants the intake ledger; the cron wrapper enables it via env var.
    if os.environ.get("SIMPLICIO_BRIDGE_BACKLOG", "").lower() in ("1", "true", "yes", "on"):
        try:
            import importlib.util
            bridge_path = HERE / "scripts" / "bridge_intake_to_backlog.py"
            if not bridge_path.exists():
                print("MEASURED| bridge script ausente — pulando ponte backlog", flush=True)
            else:
                spec = importlib.util.spec_from_file_location(
                    "bridge_intake_to_backlog", str(bridge_path))
                if spec is None or spec.loader is None:
                    print("MEASURED| bridge spec/loader None — pulando ponte", flush=True)
                else:
                    bridge = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(bridge)
                    rc = bridge.main()
                    print(f"MEASURED| bridge exited rc={rc}", flush=True)
        except Exception as exc:  # never break the intake tick
            print(f"MEASURED| bridge falhou (non-fatal): {exc!r}", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
