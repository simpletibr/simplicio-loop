"""Unit tests for ``scripts/bridge_intake_to_backlog.py``.

Covers the intake→backlog bridge safety rules (issue #GAP-intake-backlog):
AC1: only issues OPEN on GitHub right now are bridged (stale ledger rows ignored)
AC2: idempotent — an already-present WI is not duplicated
AC3: built item matches the canonical task_backlog item schema (kind/id/acs/status)
AC4: a simulated closed issue in the ledger is NOT bridged even if present in ledger

Tests pass an explicit ``backlog_path`` to ``main()`` so they NEVER touch the
real ``.simplicio-loop/orchestrator/backlog/backlog.jsonl`` on disk.
"""
from __future__ import annotations

import importlib.util
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "scripts", "bridge_intake_to_backlog.py")


def _load():
    spec = importlib.util.spec_from_file_location("bridge_intake_to_backlog", SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mod = _load()


def _write_master(path):
    master = {"kind": "master", "schema": "simplicio.backlog/v2", "goal": "x",
              "revision": 1, "empty_polls": 3, "updated_at": "2026-01-01T00:00:00Z"}
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(master) + "\n")


def test_build_item_schema():
    """AC3: build_item produces a canonical item dict."""
    row = {
        "issue": 612,
        "title": "[P0][Quality] Eliminar bypass de done",
        "ts": "2026-07-20T00:00:00Z",
        "intake_hash": "abc123def456",
        "planning_receipt_verdict": "COMPLETE",
        "ready_for_mutation": True,
    }
    item = mod.build_item(row)
    assert item["kind"] == "item"
    assert item["id"] == "wi612"
    assert item["goal"].startswith("[issue #612]")
    assert item["status"] == "blocked"
    assert len(item["acs"]) == 5
    assert item["source_refs"][0]["path"] == "github:wesleysimplicio/simplicio-loop#612"


def test_ignores_stale_ledger_rows(tmp_path):
    """AC1+AC4: rows for CLOSED/nonexistent issues are not bridged."""
    fake_ledger = tmp_path / "ledger.jsonl"
    rows = [
        {"issue": 612, "title": "open issue", "ts": "2026-07-20T00:00:00Z",
         "intake_hash": "h1", "planning_receipt_verdict": "COMPLETE",
         "ready_for_mutation": True},
        {"issue": 9999, "title": "closed long ago", "ts": "2026-01-01T00:00:00Z",
         "intake_hash": "h2", "planning_receipt_verdict": "COMPLETE",
         "ready_for_mutation": True},
    ]
    fake_ledger.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    mod.LEDGER = str(fake_ledger)
    fake_backlog = tmp_path / "backlog.jsonl"
    _write_master(str(fake_backlog))
    mod.live_open_issues = lambda: {612}

    mod.main(backlog_path=str(fake_backlog))

    lines = [l for l in fake_backlog.read_text(encoding="utf-8").splitlines() if l.strip()]
    items = [json.loads(l) for l in lines if json.loads(l).get("kind") == "item"]
    ids = {it["id"] for it in items}
    assert "wi612" in ids, "open issue must be bridged"
    assert "wi9999" not in ids, "stale closed issue must NOT be bridged"
    assert len(items) == 1


def test_idempotent_on_existing(tmp_path):
    """AC2: an already-present WI is not duplicated."""
    fake_ledger = tmp_path / "ledger.jsonl"
    rows = [{"issue": 612, "title": "open", "ts": "2026-07-20T00:00:00Z",
             "intake_hash": "h1", "planning_receipt_verdict": "COMPLETE",
             "ready_for_mutation": True}]
    fake_ledger.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    mod.LEDGER = str(fake_ledger)

    fake_backlog = tmp_path / "backlog.jsonl"
    master = {"kind": "master", "schema": "simplicio.backlog/v2", "goal": "x",
              "revision": 1, "empty_polls": 3, "updated_at": "2026-01-01T00:00:00Z"}
    existing = {"kind": "item", "id": "wi612", "goal": "[issue #612] open",
                "acs": ["x"], "status": "blocked"}
    with open(str(fake_backlog), "w", encoding="utf-8") as f:
        f.write(json.dumps(master) + "\n" + json.dumps(existing) + "\n")
    mod.live_open_issues = lambda: {612}

    mod.main(backlog_path=str(fake_backlog))
    lines = [l for l in fake_backlog.read_text(encoding="utf-8").splitlines() if l.strip()]
    items = [json.loads(l) for l in lines if json.loads(l).get("kind") == "item"]
    wi612 = [it for it in items if it["id"] == "wi612"]
    assert len(wi612) == 1, "wi612 must appear exactly once (no duplication)"
