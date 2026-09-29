"""Core-gate isolation and claims-audit command-line contracts."""
from __future__ import annotations

import sys
import time

from scripts import check
from scripts.check_runtime import CommandResult


def test_core_gate_adds_no_network_env_to_every_bounded_phase(monkeypatch) -> None:
    calls = []

    def fake_run(*_args, **kwargs):
        calls.append(kwargs)
        return CommandResult(0)

    monkeypatch.setattr(check, "_runtime_run_bounded", fake_run)
    check._core_deadline = time.monotonic() + 10
    try:
        for phase in check.PHASE_TIMEOUT_SECONDS:
            check._run_bounded([sys.executable, "-c", "pass"], phase=phase)
    finally:
        check._core_deadline = None

    assert len(calls) == len(check.PHASE_TIMEOUT_SECONDS)
    assert all(call["env"]["SIMPLICIO_CORE_NO_NETWORK"] == "1" for call in calls)


def test_every_bounded_phase_used_by_check_has_a_timeout() -> None:
    """`scripts/check.py` runs each phase through run_bounded, which looks its timeout up by name."""
    import re
    from pathlib import Path

    source = Path(check.__file__).read_text(encoding="utf-8")
    phases = set(re.findall(r'phase="([a-z_]+)"', source))
    assert "contract_headers" in phases
    assert not sorted(phases - set(check.PHASE_TIMEOUT_SECONDS))


def test_claims_audit_receives_core_argv_only_from_core_gate(monkeypatch) -> None:
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return CommandResult(0)

    monkeypatch.setattr(check, "_run_bounded", fake_run)
    check._core_deadline = time.monotonic() + 10
    try:
        assert check.run_audit().ok
    finally:
        check._core_deadline = None
    assert calls[0][0][-1] == "--core"
    assert calls[0][1]["phase"] == "claims_audit"

    calls.clear()
    assert check.run_audit().ok
    assert "--core" not in calls[0][0]


def test_claims_audit_cli_enables_core_mode(monkeypatch, capsys) -> None:
    import scripts.claims_audit as claims_audit

    observed = []

    def check_core_mode():
        observed.append(claims_audit.CORE_MODE)
        return True, "ok"

    monkeypatch.setattr(claims_audit, "CHECKS", [("1 core-mode", check_core_mode)])
    monkeypatch.setattr(sys, "argv", ["claims_audit.py", "--core"])
    try:
        claims_audit.main()
    except SystemExit as exc:
        assert exc.code == 0
    assert observed == [True]
    assert "claims-audit: PASS (1/1)" in capsys.readouterr().out
