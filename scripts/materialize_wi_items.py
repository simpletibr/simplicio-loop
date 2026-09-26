#!/usr/bin/env python3
"""Materialize canonical work-item state for recently opened GitHub issues.

For each issue in the given range that has an intake contract + planning receipt
but no ``.simplicio-loop/orchestrator/backlog/items/wiNNN/`` trio (anchor + mapping + run state),
create the trio from the intake artifacts. This closes the gap between the
issue cursor projection (``gh-issue-cursor.json``) and the execution
source-of-truth (``items/wiNNN/``) so the canonical lifecycle (intake ->
mapping -> planning -> executing -> validating -> watching -> delivering ->
done) has a real on-disk home for every work item.

Deterministic + idempotent: re-running never overwrites an existing trio, only
fills missing ones. Classifies infra-dependent issues as ``blocked`` (with a
documented reason) and the rest as ``planning`` (ready for local or
client-requested worktree execution — Orca is never assumed).
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import issue_cron_driver as drv  # reuse _is_infra_dependent

INTAKE_DIR = os.path.join(REPO, ".simplicio-loop/orchestrator", "intake")
ITEMS_DIR = os.path.join(REPO, ".simplicio-loop/orchestrator", "backlog", "items")
GH_REPO = "wesleysimplicio/simplicio-loop"


def _ts():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def live_open(limit=200):
    out = subprocess.run(
        ["gh", "issue", "list", "--repo", GH_REPO, "--state", "open",
         "--limit", str(limit), "--json", "number,title,labels,body"],
        capture_output=True, text=True, timeout=60,
    )
    if out.returncode != 0:
        return {}
    import json as _j
    return {int(d["number"]): d for d in _j.loads(out.stdout or "[]")}


def materialize(issue_num, issue_meta):
    wi_id = "wi%d" % issue_num
    item_dir = os.path.join(ITEMS_DIR, wi_id)
    anchor_path = os.path.join(item_dir, "anchor.json")
    mapping_path = os.path.join(item_dir, "mapping.json")
    state_path = os.path.join(item_dir, "run", "state.json")
    if os.path.exists(anchor_path) and os.path.exists(mapping_path) and os.path.exists(state_path):
        return "skip-existing"

    contract_path = os.path.join(INTAKE_DIR, "issue-%d" % issue_num, "intake-contract.json")
    if not os.path.exists(contract_path):
        return "skip-no-intake"
    contract = json.load(open(contract_path, encoding="utf-8"))

    os.makedirs(os.path.join(item_dir, "run"), exist_ok=True)

    title = (contract.get("source", {}).get("title_hash") and issue_meta.get("title")) or \
            "issue %d" % issue_num
    goal = "[issue #%d] %s" % (issue_num, issue_meta.get("title", "Issue %d" % issue_num))

    # Acceptance criteria carried from the intake contract (frozen snapshot).
    acs = []
    for t in contract.get("acceptance_criteria", []):
        acs.append({
            "id": t.get("id", "AC"),
            "text": t.get("text", ""),
            "status": "pending",
        })
    # Always add the 7 DoD dimensions as structural ACs (per simplicio-loop skill).
    dod = [
        "Implementacao presente e funcionando",
        "Testes unitarios cobrindo a logica nova/alterada",
        "Testes de integracao contra colaboradores reais",
        "Testes de sistema end-to-end pela superficie CLI/API",
        "Testes de regressao (suite existente verde)",
        "Benchmark de performance para hot paths (se aplicavel)",
        "Cobertura >= 85% (alvo 90%) nos arquivos tocados",
    ]
    for i, d in enumerate(dod, 1):
        acs.append({"id": "DoD-%d" % i, "text": d, "status": "pending"})

    anchor = {
        "schema": "simplicio.task-anchor/v1",
        "item": wi_id,
        "goal": goal,
        "goal_fp": (contract.get("intake_hash") or ("issue%d" % issue_num))[:12],
        "frozen_at": _ts(),
        "criteria": [
            {"id": a["id"], "text": a["text"], "verify": "", "status": "pending",
             "evidence": "", "verified_at": ""}
            for a in acs
        ],
    }

    infra = drv._is_infra_dependent(issue_meta) if issue_meta else True
    mapping = {
        "schema": "simplicio.task-mapping/v1",
        "item_id": wi_id,
        "mapped_at": _ts(),
        "repo_context": {
            "project_map": ".simplicio-loop/project-map.json",
            "call_graph": ".simplicio-loop/call-graph.json",
            "architecture_inventory": ".simplicio-loop/architecture-inventory.json",
            "worktree": ".simplicio-loop/orchestrator/worktrees/%s" % wi_id,
        },
        "scope": goal,
        "impact_files": [],
        "mapper_version": "0.19.0",
    }

    if infra:
        status = "blocked"
        phase = "blocked"
        blocked_reason = (
            "execution deferred fail-closed: requires multi-host/worktree "
            "infra (Hub/Supervisor/Async) absent on this single host; "
            "do not assume Orca — only enable a client-requested host integration"
        )
    else:
        status = "planning"
        phase = "planning"
        blocked_reason = ""

    state = {
        "schema": "simplicio.backlog-item-state/v1",
        "item_id": wi_id,
        "phase": phase,
        "status": status,
        "blocked_reason": blocked_reason,
        "updated_at": _ts(),
    }

    with open(anchor_path, "w", encoding="utf-8") as f:
        json.dump(anchor, f, indent=2, ensure_ascii=False)
    with open(mapping_path, "w", encoding="utf-8") as f:
        json.dump(mapping, f, indent=2, ensure_ascii=False)
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    return status


def main():
    open_issues = live_open()
    created = 0
    skipped = 0
    blocked = 0
    for n in sorted(open_issues.keys()):
        if not (613 <= n <= 640):
            continue
        meta = open_issues[n]
        res = materialize(n, meta)
        if res in ("skip-existing", "skip-no-intake"):
            skipped += 1
            print("MEASURED| %d: %s" % (n, res), flush=True)
        else:
            created += 1
            if res == "blocked":
                blocked += 1
            print("MEASURED| wi%d (issue #%d): materializado -> %s" % (n, n, res), flush=True)
    print("MEASURED| resumo: %d criados (%d blocked), %d skip" % (created, blocked, skipped), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
