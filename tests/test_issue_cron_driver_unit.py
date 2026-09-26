"""Unit tests for ``scripts/issue_cron_driver.classify_status`` and helpers.

Covers the broadened infra-dependency classifier (issue #495-#558 family):
AC1 prefix set, AC2 title prefix match, AC3 label match, AC4 body keyword
match, AC5 intake_ok=False short-circuit, AC6 non-infra Todo.
"""
from __future__ import annotations

import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "scripts", "issue_cron_driver.py")


def _load():
    spec = importlib.util.spec_from_file_location("issue_cron_driver", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


mod = _load()
classify_status = mod.classify_status
_is_infra_dependent = mod._is_infra_dependent


def _issue(title, labels=None, body=""):
    return {"title": title, "labels": labels or [], "body": body}


# AC1: prefix set covers Hub/Supervisor/Async/Architecture/Epic/Performance/ReleaseTrain
def test_prefix_set_covers_domains():
    for p in ("HUB", "SUPERVISOR", "ASYNC", "ARCHITECTURE",
              "EPIC", "PERFORMANCE", "RELEASE TRAIN"):
        assert p in mod.INFRA_DEPENDENT_DOMAINS, p


# AC2: title prefix -> Blocked
def test_title_prefix_blocked():
    for t in ("[Hub] Implementar daemon singleton",
              "[Supervisor] Backend Rust/Tokio",
              "[Async] Migrar subprocessos",
              "[Architecture] Centralizar processo",
              "[Epic] Criar serviço central de mapas",
              "[Performance] Tornar o núcleo assíncrono",
              "[P0][Release Train] Propagar versão",
              "[EPIC][P0] cross-cutting"):
        assert classify_status(_issue(t), True, []) == "Blocked", t


# AC3: label match -> Blocked
def test_label_blocked():
    for lbls in (["hub"], ["supervisor", "x"], ["async"], ["architecture"],
                  ["epic"], ["performance"], ["release-train"], ["infra"],
                  ["blocked-infra"]):
        assert classify_status(_issue("Qualquer título", lbls), True, []) == "Blocked", lbls


# AC4: body keyword -> Blocked
def test_body_keyword_blocked():
    for kw in ("requer infra", "infra ausente", "não presente neste host",
               "precisa de hub", "precisa de supervisor", "rust/tokio"):
        assert classify_status(_issue("Título", [], f"texto {kw} aqui"), True, []) == "Blocked", kw


# AC5: intake_ok=False -> Blocked (preserved behavior)
def test_intake_failure_blocked():
    assert classify_status(_issue("Título comum não-infra"), False, ["intake_blocked"]) == "Blocked"


# AC6: non-infra + intake_ok -> Todo
def test_non_infra_todo():
    assert classify_status(_issue("Corrigir typo no README"), True, []) == "Todo"
    assert classify_status(_issue("[Docs] Atualizar exemplo"), True, []) == "Todo"


# _is_infra_dependent helper correctness
def test_helper_combos():
    assert _is_infra_dependent(_issue("[Hub] x"))
    assert _is_infra_dependent(_issue("y", ["hub"]))
    assert _is_infra_dependent(_issue("z", [], "precisa de supervisor"))
    assert not _is_infra_dependent(_issue("Docs: fix typo", [], "sem palavra-chave"))


# --- reconcile_cursor integrity (issue: cursor drift / phantom WIs) ---------
import json
import tempfile
from pathlib import Path
from unittest import mock

reconcile_cursor = mod.reconcile_cursor


def _write_cursor(tmp, state):
    od = os.path.join(tmp, ".simplicio-loop/orchestrator")
    os.makedirs(od, exist_ok=True)
    p = os.path.join(od, "gh-issue-cursor.json")
    json.dump({"work_items_state": state, "last_scan_at": "2026-01-01T00:00:00Z"},
              open(p, "w"), ensure_ascii=False)
    return p


def _gh_json(stdout):
    return mock.Mock(stdout=stdout, stderr="", returncode=0)


def _patch_here(tmp):
    # HERE is a pathlib.Path in the module; patch it to point at tmp.
    return mock.patch.object(mod, "HERE", Path(tmp))


def test_reconcile_drops_repo_none_and_collapses():
    with tempfile.TemporaryDirectory() as tmp:
        state = {
            "wi-1": {"issue": 100, "repo": None, "canonical_state": "todo"},
            "wi-2": {"issue": 100, "repo": "o/r", "canonical_state": "todo"},
            "wi-3": {"issue": 100, "repo": "o/r", "canonical_state": "blocked"},
            "wi-4": {"issue": 0, "repo": "o/r", "canonical_state": "todo"},
            "wi-5": {"issue": 200, "repo": "o/r", "canonical_state": "todo"},
        }
        cur = _write_cursor(tmp, state)
        with _patch_here(tmp), \
             mock.patch("subprocess.run") as run:
            # PR list (all) + issue view, per WI; return empty/OPEN
            run.side_effect = [
                _gh_json("[]"), _gh_json("OPEN"),   # wi-2/3 -> collapse to wi-3
                _gh_json("[]"), _gh_json("OPEN"),   # wi-4 dropped (bad issue)
                _gh_json("[]"), _gh_json("OPEN"),   # wi-5
            ]
            res = reconcile_cursor("o/r")
        assert res["ok"]
        # wi-1 (repo None) and wi-4 (bad issue) dropped
        assert ("wi-1", "repo_none") in res["dropped"] or \
               any(d[0] == "wi-1" for d in res["dropped"])
        # wi-2 collapsed into wi-3 (higher number), wi-3 kept
        assert "wi-3" in res["remaining_keys"] if "remaining_keys" in res else True
        final = json.load(open(cur))["work_items_state"]
        assert "wi-1" not in final and "wi-4" not in final
        # only one WI owns issue 100
        owners_100 = [w for w, v in final.items() if v["issue"] == 100]
        assert len(owners_100) == 1
        assert owners_100[0] == "wi-3"


def test_reconcile_syncs_merged_pr_to_done():
    with tempfile.TemporaryDirectory() as tmp:
        state = {"wi-9": {"issue": 555, "repo": "o/r", "canonical_state": "validating",
                           "orca_projection": "Validating",
                           "title": "[Hub] x"}}
        cur = _write_cursor(tmp, state)
        with _patch_here(tmp), \
             mock.patch("subprocess.run") as run:
            run.side_effect = [
                _gh_json('[{"number":563,"state":"MERGED","mergedAt":"x"}]'),
                _gh_json("CLOSED"),
            ]
            res = reconcile_cursor("o/r")
        final = json.load(open(cur))["work_items_state"]["wi-9"]
        assert final["canonical_state"] == "done"
        assert final["orca_projection"] == "Done"
        assert ("wi-9", "validating", "done") in res["synced"]


def test_reconcile_syncs_open_pr_to_delivering():
    # FIX #569: reconcile now derives `ist` from the authoritative open-issue
    # set (gh issue list --state open) instead of `gh issue view`. The mock
    # order is: (1) open_set enumerate, (2) pr list. Issue-view is no longer
    # called for `ist` (title is already in the cursor, so no fallback either).
    with tempfile.TemporaryDirectory() as tmp:
        state = {"wi-8": {"issue": 558, "repo": "o/r", "canonical_state": "todo",
                           "orca_projection": "Todo", "title": "[Release Train] x"}}
        cur = _write_cursor(tmp, state)
        with _patch_here(tmp), \
             mock.patch("subprocess.run") as run:
            run.side_effect = [
                _gh_json('558'),  # open_set enumerate: 558 is OPEN -> ist=OPEN
                _gh_json('[{"number":567,"state":"OPEN","mergedAt":null}]'),  # pr list
            ]
            res = reconcile_cursor("o/r")
        final = json.load(open(cur))["work_items_state"]["wi-8"]
        assert final["canonical_state"] == "delivering"
        assert final["orca_projection"] == "In review"


def test_ingest_backlog_into_cursor_adds_missing_wi():
    # New backlog item (wi613, blocked) not yet in the cursor projection must
    # be ingested as blocked / Blocked with the ingested_from_backlog flag.
    with tempfile.TemporaryDirectory() as tmp:
        od = os.path.join(tmp, ".simplicio-loop/orchestrator")
        bl = os.path.join(od, "backlog")
        os.makedirs(bl, exist_ok=True)
        backlog = os.path.join(bl, "backlog.jsonl")
        with open(backlog, "w") as fh:
            fh.write(json.dumps({
                "kind": "item", "id": "wi613", "status": "blocked",
                "reason_code": "infra-dependent",
            }) + "\n")
        cur = {"work_items_state": {}}
        with mock.patch.object(mod, "HERE", Path(tmp)), \
             mock.patch("subprocess.run") as run:
            run.side_effect = [_gh_json("613")]  # open_set enumerate: 613 OPEN
            res = mod.ingest_backlog_into_cursor(cur["work_items_state"], "o/r")
        assert res["ingested"] == 1
        wi = cur["work_items_state"]["wi613"]
        assert wi["canonical_state"] == "blocked"
        assert wi["orca_projection"] == "Blocked"
        assert wi["ingested_from_backlog"] is True


def test_ingest_backlog_into_cursor_updates_stale_wi():
    # A pre-existing cursor WI without the flag must be updated in place from
    # the backlog ground truth (no flip-flop on the next reconcile).
    with tempfile.TemporaryDirectory() as tmp:
        od = os.path.join(tmp, ".simplicio-loop/orchestrator")
        bl = os.path.join(od, "backlog")
        os.makedirs(bl, exist_ok=True)
        backlog = os.path.join(bl, "backlog.jsonl")
        with open(backlog, "w") as fh:
            fh.write(json.dumps({
                "kind": "item", "id": "wi630", "status": "blocked",
                "reason_code": "infra-dependent",
            }) + "\n")
        cur = {"work_items_state": {
            "wi630": {"issue": 630, "repo": "o/r", "canonical_state": "done",
                      "orca_projection": "Done"}}}
        with mock.patch.object(mod, "HERE", Path(tmp)), \
             mock.patch("subprocess.run") as run:
            run.side_effect = [_gh_json("630")]  # open_set: 630 OPEN (not closed)
            res = mod.ingest_backlog_into_cursor(cur["work_items_state"], "o/r")
        assert res["ingested"] == 1
        wi = cur["work_items_state"]["wi630"]
        assert wi["canonical_state"] == "blocked"
        assert wi["orca_projection"] == "Blocked"
        assert wi["ingested_from_backlog"] is True


def test_ingest_backlog_into_cursor_skips_closed_issue():
    # A backlog item whose issue is CLOSED on GitHub must NOT be ingested.
    with tempfile.TemporaryDirectory() as tmp:
        od = os.path.join(tmp, ".simplicio-loop/orchestrator")
        bl = os.path.join(od, "backlog")
        os.makedirs(bl, exist_ok=True)
        backlog = os.path.join(bl, "backlog.jsonl")
        with open(backlog, "w") as fh:
            fh.write(json.dumps({
                "kind": "item", "id": "wi999", "status": "blocked",
                "reason_code": "infra-dependent",
            }) + "\n")
        cur = {"work_items_state": {}}
        with mock.patch.object(mod, "HERE", Path(tmp)), \
             mock.patch("subprocess.run") as run:
            run.side_effect = [_gh_json("")]  # open_set empty: 999 not open
            res = mod.ingest_backlog_into_cursor(cur["work_items_state"], "o/r")
        assert res["ingested"] == 0
        assert "wi999" not in cur["work_items_state"]


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
    # order is: (1) open_set enumerate, (2) pr list. Issue-view is no longer
    # called for `ist` (title is already in the cursor, so no fallback either).
    with tempfile.TemporaryDirectory() as tmp:
        state = {"wi-8": {"issue": 558, "repo": "o/r", "canonical_state": "todo",
                           "orca_projection": "Todo", "title": "[Release Train] x"}}
        cur = _write_cursor(tmp, state)
        with _patch_here(tmp), \
             mock.patch("subprocess.run") as run:
            run.side_effect = [
                _gh_json('558'),  # open_set enumerate: 558 is OPEN -> ist=OPEN
                _gh_json('[{"number":567,"state":"OPEN","mergedAt":null}]'),  # pr list
            ]
            res = reconcile_cursor("o/r")
        final = json.load(open(cur))["work_items_state"]["wi-8"]
        assert final["canonical_state"] == "delivering"
        assert final["orca_projection"] == "In review"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
