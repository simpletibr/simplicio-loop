from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_integrity_module():
    path = ROOT / "scripts" / "integrity_check.py"
    spec = importlib.util.spec_from_file_location("integrity_check", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_integrity_check_script_runs(capsys):
    mod = _load_integrity_module()
    code = mod.main(["--check"])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "pass: release integrity" in out


def test_legacy_script_delegates_to_canonical_gate(monkeypatch):
    mod = _load_integrity_module()
    observed = []

    def canonical(argv):
        observed.append(argv)
        return 7

    monkeypatch.setattr(mod._CANONICAL, "main", canonical)
    assert mod.main(["--check", "--json"]) == 7
    assert observed == [["--check", "--json", "--root", str(ROOT)]]


def test_legacy_evaluate_is_the_canonical_receipt():
    mod = _load_integrity_module()
    receipt = mod.evaluate(ROOT)
    assert receipt["schema"] == mod.SCHEMA
    assert receipt["status"] == "pass"
    assert {check["name"] for check in receipt["checks"]} >= {
        "policy_schema",
        "native_ownership",
        "default_branch_policy",
    }
