"""Issue #1342: stable-first key order for loop JSON outputs."""
from __future__ import annotations

import json

from simplicio_loop import cli_impl, runner
from simplicio_loop.json_order import stable_first

VOLATILE = {"run_id", "created_at", "duration_ms", "receipt_path", "receipt_hash", "elapsed"}


def test_moves_volatile_to_end_preserving_order():
    payload = {"run_id": "r1", "status": "OK", "created_at": 1.0, "schema": "s/v1",
               "tasks": [], "receipt_path": "/x", "duration_ms": 3, "phase": "done"}
    out = stable_first(payload)
    assert list(out) == ["schema", "status", "tasks", "phase",
                         "run_id", "created_at", "receipt_path", "duration_ms"]
    assert out == payload


def test_recursive_dicts_and_lists():
    payload = {"schema": "s", "state": {"started_at": 1, "phase": "x"},
               "items": [{"elapsed": 2, "id": "a"}]}
    out = stable_first(payload)
    assert list(out["state"]) == ["phase", "started_at"]
    assert list(out["items"][0]) == ["id", "elapsed"]


def test_state_dir_path_values_are_volatile():
    out = stable_first({"schema": "s", "log": "/r/.simplicio-loop/runs/x/log", "ok": True})
    assert list(out) == ["schema", "ok", "log"]


def test_idempotent_and_values_unchanged():
    payload = {"b_at": 1, "schema": "s", "a": {"x_ms": 1, "y": 2}, "receipt_hash": "h"}
    once = stable_first(payload)
    assert stable_first(once) == once
    assert json.dumps(stable_first(once)) == json.dumps(once)
    assert once == payload


def test_schema_first_opt_out_keeps_leading_key():
    out = stable_first({"route": {}, "schema": "s", "run_id": "r"}, schema_first=False)
    assert list(out) == ["route", "schema", "run_id"]


def test_verify_prints_schema_first_run_id_after_stable(monkeypatch, capsys):
    fake = {"run_id": "r1", "verified_at": 5.0, "receipt_path": "/p",
            "status": "VERIFIED", "schema": "simplicio.verify/v1",
            "state": {"phase": "done", "updated_at": 1}, "verified": True}
    monkeypatch.setattr(runner, "verify_run", lambda repo, run_id: dict(fake))
    assert cli_impl.verify(".", "r1") == 0
    keys = list(json.loads(capsys.readouterr().out))
    assert keys[0] == "schema"
    stable = [k for k in keys if k not in VOLATILE and not k.endswith("_at")]
    assert keys.index("run_id") > max(keys.index(k) for k in stable)
