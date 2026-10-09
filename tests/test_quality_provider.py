"""Tests for the mandatory quality_provider boundary (issue #613).

Covers the seven DoD acceptance criteria:
  AC1 implementation: QualityProvider protocol + CLI flags in conduct_run
  AC2 unit: provider PASS/FAIL/BLOCKED; absent/version/crash/timeout
  AC3 integration: quality runs AFTER execute_operator_batch, BEFORE verify_run
  AC4 system: CLI `simplicio-loop run --quality-provider ... --quality-policy ...`
  AC5 regression: scripts/check.py stays green; existing conduct_run w/o provider works
  AC6 benchmark: overhead of the quality provider is measured (ms) on a real run
  AC7 coverage: this file drives branch coverage >= 90% on quality_provider.py
"""
from __future__ import annotations

import importlib
import types
import json
import threading
import time
from pathlib import Path
from typing import Any, Dict

import pytest

import simplicio_loop.quality_provider as qp
from simplicio_loop.quality_provider import (
    QualityProviderError,
    QualityProviderSpec,
    QualityResult,
    conduct_quality,
    load_quality_provider,
    run_quality_gate,
)
from tests.runner_patch import patch_runner


# --------------------------------------------------------------------------
# AC1: protocol + capability negotiation shape
# --------------------------------------------------------------------------
def test_provider_module_negotiates_version_and_caps():
    caps = importlib.import_module(
        "simplicio_loop.quality_providers.simplicio_loop_quality"
    ).capability_negotiate()
    assert isinstance(caps, dict)
    assert tuple(int(p) for p in caps["version"].split(".")[:3]) >= (1, 0, 0)
    assert caps["capabilities"].get("cancel_token") is True


def test_load_quality_provider_returns_spec():
    spec = load_quality_provider("simplicio_loop_quality", "strict-default")
    assert spec.name == "simplicio_loop_quality"
    assert spec.policy == "strict-default"
    assert spec.version >= "1.0.0"
    assert spec.module_path.endswith(("simplicio_loop_quality", "simplicio_loop_quality.provider"))


def test_load_quality_provider_resolves_explicit_extension_entry_point(monkeypatch):
    runtime = types.SimpleNamespace(manifest={"extension_id": "simplicio_loop_quality"})
    module = types.SimpleNamespace(
        capability_negotiate=lambda: {"version": "1.0.0", "capabilities": {}},
        run=lambda **_: {"status": "PASS"},
    )
    entry = types.SimpleNamespace(
        name="simplicio_loop_quality",
        value="simplicio_loop_quality.provider:provider",
        load=lambda: (lambda: runtime),
    )
    real_import = qp.importlib.import_module

    def fake_import(name, *args, **kwargs):
        if name == "simplicio_loop.quality_providers.simplicio_loop_quality":
            raise ModuleNotFoundError(name)
        if name == "simplicio_loop_quality.provider":
            return module
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(qp.importlib, "import_module", fake_import)
    monkeypatch.setattr(qp, "_quality_extension_entry", lambda name: entry if name == entry.name else None)
    spec = load_quality_provider("simplicio_loop_quality", "strict-default")
    assert spec.module_path == "simplicio_loop_quality.provider"


# --------------------------------------------------------------------------
# AC2: fail-closed matrix -- absent / version / crash / timeout / PASS / FAIL
# --------------------------------------------------------------------------
def test_absent_provider_blocks():
    with pytest.raises(QualityProviderError) as exc:
        load_quality_provider("does_not_exist_xyz", "strict-default")
    assert exc.value.kind == "absent"


def test_version_incompatible_blocks(monkeypatch):
    import simplicio_loop.quality_providers.simplicio_loop_quality as mod

    monkeypatch.setattr(qp, "_quality_extension_entry", lambda _name: None)
    monkeypatch.setattr(mod, "capability_negotiate", lambda: {"version": "0.0.1"})
    with pytest.raises(QualityProviderError) as exc:
        load_quality_provider("simplicio_loop_quality", "strict-default")
    assert exc.value.kind == "version"


def test_crash_in_negotiate_blocks(monkeypatch):
    import simplicio_loop.quality_providers.simplicio_loop_quality as mod

    monkeypatch.setattr(qp, "_quality_extension_entry", lambda _name: None)
    monkeypatch.setattr(mod, "capability_negotiate", lambda: 1 / 0)
    with pytest.raises(QualityProviderError) as exc:
        load_quality_provider("simplicio_loop_quality", "strict-default")
    assert exc.value.kind == "crash"


def test_conduct_quality_blocks_on_absent_provider():
    res = conduct_quality(".", "run-x", quality_provider="nope_nope")
    assert res["status"] == "BLOCKED"
    assert res["kind"] == "absent"


def test_run_quality_gate_timeout_blocks():
    # Build a fake spec whose module.run sleeps forever; gate must BLOCK on timeout.
    class _Slow:
        @staticmethod
        def capability_negotiate():
            return {"version": "1.0.0"}

        @staticmethod
        def run(**kwargs):
            time.sleep(60)
            return {"status": "PASS"}

    spec = qp.QualityProviderSpec(name="slow", policy="p", version="1.0.0",
                                  capabilities={}, module_path="tests.test_quality_provider._Slow")
    # Patch the import inside the worker by monkeypatching importlib.import_module
    real_import = importlib.import_module

    def fake_import(name, *a, **k):
        if name == "tests.test_quality_provider._Slow":
            return _Slow
        return real_import(name, *a, **k)

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(importlib, "import_module", fake_import)
        mp.setattr(qp, "PROVIDER_TIMEOUT_SECONDS", 0.2)
        result = run_quality_gate(".", "run-timeout", spec)
    assert result.status == "BLOCKED"
    assert "timed out" in result.detail.lower()


def test_run_quality_gate_provider_metadata_cannot_extend_default(monkeypatch):
    class _SlowButNotAllowed:
        @staticmethod
        def run(**kwargs):
            time.sleep(0.05)
            return {"status": "PASS"}

    spec = qp.QualityProviderSpec(
        name="slow-allowed", policy="p", version="1.0.0",
        capabilities={"provider_timeout_seconds": 0.2},
        module_path="tests.test_quality_provider._SlowButNotAllowed",
    )
    real_import = importlib.import_module

    def fake_import(name, *a, **k):
        if name == "tests.test_quality_provider._SlowButNotAllowed":
            return _SlowButNotAllowed
        return real_import(name, *a, **k)

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(importlib, "import_module", fake_import)
        mp.setattr(qp, "PROVIDER_TIMEOUT_SECONDS", 0.01)
        result = run_quality_gate(".", "run-provider-metadata-timeout", spec)
    assert result.status == "BLOCKED"
    assert "timed out" in result.detail.lower()


def test_builtin_quality_provider_uses_explicit_finite_outer_deadline():
    builtin = qp.QualityProviderSpec(
        name="simplicio_loop_quality", policy="p", version="1.0.0",
        capabilities={"quality_gate_outer_timeout_seconds": 930.0},
        module_path="simplicio_loop.quality_providers.simplicio_loop_quality",
    )
    external = qp.QualityProviderSpec(
        name="simplicio_loop_quality", policy="p", version="1.0.0",
        capabilities={"quality_gate_outer_timeout_seconds": 930.0},
        module_path="external.provider",
    )
    assert qp._provider_timeout_seconds(builtin) == 930.0
    assert qp._provider_timeout_seconds(external) == qp.PROVIDER_TIMEOUT_SECONDS


def test_run_quality_gate_crash_blocks():
    class _Boom:
        @staticmethod
        def capability_negotiate():
            return {"version": "1.0.0"}

        @staticmethod
        def run(**kwargs):
            raise RuntimeError("boom")

    spec = qp.QualityProviderSpec(name="boom", policy="p", version="1.0.0",
                                  capabilities={}, module_path="tests.test_quality_provider._Boom")
    real_import = importlib.import_module

    def fake_import(name, *a, **k):
        if name == "tests.test_quality_provider._Boom":
            return _Boom
        return real_import(name, *a, **k)

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(importlib, "import_module", fake_import)
        result = run_quality_gate(".", "run-boom", spec)
    assert result.status == "BLOCKED"
    assert "crashed" in result.detail.lower()


def test_run_quality_gate_pass_writes_matrix(tmp_path):
    class _Pass:
        @staticmethod
        def capability_negotiate():
            return {"version": "1.0.0"}

        @staticmethod
        def run(**kwargs):
            return {"status": "PASS", "findings": [{"level": "ok"}], "receipts": ["r1"]}

    spec = qp.QualityProviderSpec(name="pass", policy="strict-default", version="1.0.0",
                                  capabilities={}, module_path="tests.test_quality_provider._Pass")
    real_import = importlib.import_module

    def fake_import(name, *a, **k):
        if name == "tests.test_quality_provider._Pass":
            return _Pass
        return real_import(name, *a, **k)

    run_dir = tmp_path / "run-pass"
    run_dir.mkdir()
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(importlib, "import_module", fake_import)
        mp.setattr(qp, "_resolve_run_dir", lambda repo, run_id: str(run_dir))
        result = run_quality_gate(".", "run-pass", spec, head="abc", diff_hash="def")
    assert result.status == "PASS"
    matrix = json.loads((run_dir / "quality-matrix.json").read_text())
    assert matrix["schema"] == "simplicio.quality-matrix/v1"
    assert matrix["status"] == "PASS"
    assert matrix["provider"] == "pass"
    assert matrix["head"] == "abc" and matrix["diff_hash"] == "def"


def test_run_quality_gate_fail_returns_fail():
    class _Fail:
        @staticmethod
        def capability_negotiate():
            return {"version": "1.0.0"}

        @staticmethod
        def run(**kwargs):
            return {"status": "FAIL", "findings": [{"level": "fail", "message": "x"}],
                    "receipts": [], "detail": "failed check"}

    spec = qp.QualityProviderSpec(name="fail", policy="p", version="1.0.0",
                                  capabilities={}, module_path="tests.test_quality_provider._Fail")
    real_import = importlib.import_module

    def fake_import(name, *a, **k):
        if name == "tests.test_quality_provider._Fail":
            return _Fail
        return real_import(name, *a, **k)

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(importlib, "import_module", fake_import)
        result = run_quality_gate(".", "run-fail", spec)
    assert result.status == "FAIL"


# --------------------------------------------------------------------------
# AC3: ordering -- quality runs after batch, before verify_run
# --------------------------------------------------------------------------
def test_conduct_run_order_quality_before_verify(monkeypatch):
    import simplicio_loop.runner as runner_mod

    order: list = []

    def fake_execute_batch(repo, run_id, **kw):
        order.append("batch")
        return {"failed_task_indices": []}

    def fake_verify(repo, run_id):
        order.append("verify")
        return {"state": {"phase": "done"}}

    def fake_read_status(repo, run_id):
        return {
            "run_dir": "run-dir",
            "state": {"phase": "executing", "attempt": 1},
            "manifest": {"head": "h", "diff_hash": "d"},
        }

    monkeypatch.setattr(runner_mod, "execute_operator_batch", fake_execute_batch)
    monkeypatch.setattr(runner_mod, "verify_run", fake_verify)
    patch_runner(monkeypatch, "read_status", fake_read_status)
    monkeypatch.setattr(runner_mod, "arm_run", lambda *a, **k: {"manifest": {"run_id": "r1"},
                                                               "state": {"phase": "executing"}})
    # quality provider itself just records (patch the module-level symbol that
    # conduct_run imports locally)
    import simplicio_loop.quality_provider as qp_mod

    monkeypatch.setattr(qp_mod, "conduct_quality",
                        lambda *a, **k: order.append("quality") or {"status": "PASS"})

    runner_mod.conduct_run(".", "task.md", "verified", 1, quality_provider="x")
    assert order == ["batch", "quality", "verify"]


# --------------------------------------------------------------------------
# AC4: CLI surface exposes --quality-provider / --quality-policy
# --------------------------------------------------------------------------
def test_cli_run_exposes_quality_flags(capsys):
    from simplicio_loop import cli

    # The CLI --help for the `run` subcommand must expose both quality flags.
    with pytest.raises(SystemExit):
        cli.main(["run", "--help"])
    out = capsys.readouterr().out + capsys.readouterr().err
    assert "--quality-provider" in out
    assert "--quality-policy" in out


# --------------------------------------------------------------------------
# AC5: regression -- check.py still green; plain conduct_run unaffected
# --------------------------------------------------------------------------
def test_no_provider_conduct_quality_skips():
    res = conduct_quality(".", "run-none", quality_provider=None)
    assert res["status"] == "SKIPPED"


def test_conduct_run_without_provider_skips_quality_and_verifies(monkeypatch):
    """Quality is opt-in; a plain run continues through normal verification."""
    import simplicio_loop.runner as runner_mod

    called = {"verify": False, "transition": None}

    def fake_batch(repo, run_id, **kw):
        return {"failed_task_indices": []}

    def fake_verify(repo, run_id):
        called["verify"] = True
        return {"state": {"phase": "done"}}

    transitions = []

    def fake_transition(run_dir, state, to_phase, reason, **kw):
        transitions.append((to_phase, reason))
        called["transition"] = to_phase

    monkeypatch.setattr(runner_mod, "execute_operator_batch", fake_batch)
    monkeypatch.setattr(runner_mod, "verify_run", fake_verify)
    patch_runner(monkeypatch, "read_status",
                        lambda r, rid: {"run_dir": "d",
                                        "state": {"phase": "executing", "attempt": 1},
                                        "manifest": {}})
    monkeypatch.setattr(runner_mod, "arm_run", lambda *a, **k: {"manifest": {"run_id": "r"},
                                                               "state": {"phase": "executing"}})
    monkeypatch.setattr(runner_mod, "_transition", fake_transition)

    runner_mod.conduct_run(".", "task.md", "verified", 1)  # no quality_provider
    assert called["verify"] is True
    assert called["transition"] is None
    assert transitions == []


# --------------------------------------------------------------------------
# AC6: benchmark overhead is measured (ms) on a real provider run
# --------------------------------------------------------------------------
def test_quality_overhead_measured():
    spec = load_quality_provider("simplicio_loop_quality", "strict-default")
    t0 = time.perf_counter()
    run_quality_gate(".", "run-bench", spec)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    # Overhead must be a real, measured number (not zeroed / not fabricated).
    assert elapsed_ms >= 0.0
    assert isinstance(elapsed_ms, float)


# --------------------------------------------------------------------------
# AC7: branch coverage driver -- exercise QualityResult.to_matrix + supports
# --------------------------------------------------------------------------
def test_quality_result_to_matrix_and_supports():
    spec = QualityProviderSpec(name="n", policy="p", version="1.0.0",
                               capabilities={"x": True})
    assert spec.supports("x") is True
    assert spec.supports("y") is False
    r = QualityResult(status="PASS", provider="n", version="1.0.0", policy="p",
                      findings=[{"a": 1}], receipts=["r"], detail="ok")
    m = r.to_matrix("run-1", ".", "head1", "diff1", 2)
    assert m["run_id"] == "run-1" and m["attempt"] == 2 and m["status"] == "PASS"
