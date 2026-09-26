#!/usr/bin/env python3
"""Bridge intake-ledger work-items into the canonical task_backlog.jsonl.

The ``issue_cron_driver.py`` writes intake contracts + planning receipts into
``.simplicio-loop/orchestrator/intake/ledger.jsonl`` (one row per issue, ACCUMULATED across
all past cron runs) but does NOT append the corresponding work-item to
``.simplicio-loop/orchestrator/backlog/backlog.jsonl`` — the file ``task_backlog.py`` (and the
drain loop's ``next``/``status`` verbs) actually reads.  Without this bridge the
drain loop sees a stale/empty backlog and terminates prematurely even though
GitHub has open issues.

This script closes that gap.  Safety rules (learned the hard way):
  * The intake ledger is APPEND-ONLY and accumulates rows from every past run,
    including issues that are now CLOSED or belong to other repos.  We MUST NOT
    blindly append every ledger row — that would inflate the backlog with hundreds
    of stale items.
  * Only issues that are OPEN ON GITHUB RIGHT NOW are eligible.  We fetch the
    live open-issue set and intersect with the ledger before bridging.
  * Idempotent: items whose ``id`` already exists in the backlog are skipped.

We reuse ``task_backlog._load``/``_save`` so the on-disk format stays
byte-compatible with the rest of the runtime.
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import task_backlog as tb  # reuse _load / _save for schema compatibility

# Reuse the SAME infra-dependence heuristic the cron driver uses, so the bridge
# does not mark every issue Blocked. Import defensively (driver may be absent).
try:
    from issue_cron_driver import _is_infra_dependent as _driver_infra_dependent
except Exception:  # pragma: no cover - defensive
    _driver_infra_dependent = None

# Minimal local fallback: mirrors issue_cron_driver._is_infra_dependent's domain
# keywords + [..]-segment matching so the bridge stays correct even if the driver
# module is unavailable.
_INFRA_DEPENDENT_DOMAINS = (
    "EPIC", "HUB", "SUPERVISOR", "ASYNC", "ARCHITECTURE", "PERFORMANCE", "RELEASE TRAIN", "QUALITY",
)


def _is_infra_dependent_issue(title, labels=(), body=""):
    if _driver_infra_dependent is not None:
        try:
            return bool(_driver_infra_dependent(
                {"title": title, "labels": list(labels), "body": body}))
        except Exception:
            pass
    import re
    t = (title or "").upper()
    segments = re.findall(r"\[([^\]]*)\]", t)
    seg_text = " ".join(segments).upper()
    return any(kw.upper() in seg_text for kw in _INFRA_DEPENDENT_DOMAINS) or \
        any(lbl.lower() in ("hub", "supervisor", "async", "architecture", "epic",
                    "performance", "release-train", "infra", "blocked-infra")
            for lbl in (labels or ()))

LEDGER = os.path.join(REPO, ".simplicio-loop/orchestrator", "intake", "ledger.jsonl")
BACKLOG = tb.BACKLOG
GH_REPO = "wesleysimplicio/simplicio-loop"


def live_open_issues():
    """Return the set of issue numbers currently OPEN on GitHub."""
    try:
        out = subprocess.run(
            ["gh", "issue", "list", "--repo", GH_REPO, "--state", "open",
             "--limit", "200", "--json", "number"],
            capture_output=True, text=True, timeout=60,
        )
        if out.returncode != 0:
            print("MEASURED| bridge: gh issue list falhou (%d) — abortando" % out.returncode, flush=True)
            sys.exit(1)
        data = json.loads(out.stdout or "[]")
        return {int(d["number"]) for d in data}
    except Exception as e:  # pragma: no cover - defensive
        print("MEASURED| bridge: erro ao consultar GitHub: %s — abortando" % e, flush=True)
        sys.exit(1)


def load_ledger_rows():
    if not os.path.exists(LEDGER):
        return []
    rows = []
    with open(LEDGER, encoding="utf-8", errors="replace") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            try:
                rows.append(json.loads(s))
            except ValueError:
                continue
    return rows


def build_item(row):
    issue = row["issue"]
    title = row.get("title", "").strip()
    labels = row.get("labels", []) or []
    body = row.get("body", "") or ""
    wi_id = "wi%d" % issue
    goal = "[issue #%d] %s" % (issue, title)
    acs = [
        "A issue %d possui contrato congelado (intake-contract.json) com source_refs github:%s#%d"
        % (issue, GH_REPO, issue),
        "Contexto do repositorio agendado para mapeamento (simplicio-mapper) e persistido no item",
        "Criterios de aceitacao de planejamento congelados (escopo cron = apenas intake/mapping/planning)",
        "planning-receipt COMPLETE com mutation_authority valido registrado",
        "Transicao canonica valida para estado Planning documentada no ledger de intake",
    ]
    # Classify honestly: only mark Blocked when the issue truly requires infra
    # (Hub/Supervisor/Async/Rust) absent on this single host. Otherwise it is a
    # planning-ready item the drain loop MAY execute locally (Python-only work).
    infra_dep = _is_infra_dependent_issue(title, labels, body)
    if infra_dep:
        _status = "blocked"
        _blocked_reason = (
            "execution deferred fail-closed: requires multi-host/worktree "
            "infra not available on this single-host cron runner "
            "(enable a client-requested worktree host only if contracted)"
        )
        _reason_code = "infra-dependent"
        _ready = row.get("ready_for_mutation", False)
    else:
        _status = "planning"
        _blocked_reason = ""
        _reason_code = ""
        _ready = True
    return {
        "kind": "item",
        "id": wi_id,
        "goal": goal,
        "goal_fp": (row.get("intake_hash") or ("issue%d" % issue))[:12],
        "acs": acs,
        "status": _status,
        "skip_reason": "",
        "blocked_reason": _blocked_reason,
        "reason_code": _reason_code,
        "evidence": [
            "intake/issue-%d/intake-contract.json: source.item_id=%d" % (issue, issue),
            "intake/issue-%d/planning-receipt.json: verdict=%s"
            % (issue, row.get("planning_receipt_verdict", "UNKNOWN")),
        ],
        "done_criteria": 0,
        "total_criteria": len(acs),
        "depends_on": [],
        "related": [],
        "blocks": [],
        "priority": 100,
        "plan_files": [],
        "lease": {},
        "failures": [],
        "frozen_at": row.get("ts", ""),
        "source_refs": [
            {
                "path": "github:%s#%d" % (GH_REPO, issue),
                "abs_path": os.path.join(REPO, "github:%s#%d" % (GH_REPO, issue)),
                "exists": False,
            }
        ],
        "risks": [],
        "required_evidence": [],
        "estimate": None,
        "scheduling_hints": {},
        "run_dir": os.path.join(REPO, ".simplicio-loop/orchestrator", "backlog", "items", wi_id, "run"),
        "blocked_at": row.get("ts", "") if infra_dep else "",
        "intake_hash": row.get("intake_hash", ""),
        "planning_receipt_verdict": row.get("planning_receipt_verdict", "UNKNOWN"),
        "ready_for_mutation": _ready,
    }


def main(backlog_path=None):
    backlog_file = backlog_path or BACKLOG
    master, items = tb._load(backlog_file)
    if master is None:
        print("MEASURED| backlog master ausente — abortando bridge", flush=True)
        return 1
    existing = {it.get("id") for it in items if it.get("kind") == "item"}

    open_set = live_open_issues()
    print("MEASURED| bridge: %d issues abertas no GitHub agora" % len(open_set), flush=True)

    rows = load_ledger_rows()
    # index ledger by issue number, keep the LATEST row per issue
    latest = {}
    for row in rows:
        n = row.get("issue")
        if n is None:
            continue
        latest[n] = row

    added = 0
    skipped_stale = 0
    for n in sorted(latest.keys()):
        if n not in open_set:
            skipped_stale += 1
            continue  # closed / non-existent now — do NOT bridge stale rows
        wi_id = "wi%d" % n
        if wi_id in existing:
            continue  # idempotent
        item = build_item(latest[n])
        items.append(item)
        existing.add(wi_id)
        added += 1
        print("MEASURED| bridge: +%s (issue #%d) -> backlog" % (wi_id, n), flush=True)

    print("MEASURED| bridge: %d stale ledger rows ignoradas (issue fechada/inexistente)" % skipped_stale, flush=True)

    if added:
        master["revision"] = int(master.get("revision", 0)) + 1
        master["empty_polls"] = 0
        master["updated_at"] = master.get("updated_at", "")
        tb._save(master, items, path=backlog_file)
        print(
            "MEASURED| bridge: %d item(s) adicionado(s); backlog agora tem %d itens"
            % (added, sum(1 for it in items if it.get("kind") == "item")),
            flush=True,
        )
    else:
        print("MEASURED| bridge: nenhum item novo (idempotente + sem stale)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
