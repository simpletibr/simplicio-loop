from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
for _local_module_root in (_REPO_ROOT / "scripts", _REPO_ROOT / "hooks"):
    _local_module_root = str(_local_module_root)
    if _local_module_root not in sys.path:
        sys.path.insert(0, _local_module_root)

from simplicio_loop.core_network_guard import install as install_core_network_guard


@pytest.fixture(autouse=True)
def disable_operator_bootstrap_network_by_default(monkeypatch) -> None:
    """Hermetic tests opt into the real bootstrap explicitly at their test seam."""
    monkeypatch.setenv("SIMPLICIO_LOOP_AUTO_BOOTSTRAP_OPERATORS", "0")


@pytest.fixture
def hermetic_hybrid_detection(monkeypatch) -> None:
    """The test does not see the host it runs under (Claude Code, OpenCode, ...) and never probes the real network.

    Hybrid mode picks its host from env markers and parent-process names, so a developer running the suite from inside a host
    would get that host's headless CLI called by a test that runs the default `simplicio-loop turbo` path (a task, no
    `--apply`, no `--provider`). Request this fixture in such a test; a hybrid test then sets the markers it needs.
    """
    from simplicio_loop import turbo_host_llm

    for item in turbo_host_llm.catalog():
        for rule in (item.get("detect") or {}).get("env") or []:
            monkeypatch.delenv(rule.partition("=")[0], raising=False)
    for name in (turbo_host_llm.LLM_ENV, turbo_host_llm.NESTED_ENV, turbo_host_llm.MODEL_ENV, turbo_host_llm.BUDGET_ENV,
                 turbo_host_llm.CALL_TIMEOUT_ENV, turbo_host_llm.PARALLEL_ENV):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(turbo_host_llm.PROBE_ENV, "0")
    monkeypatch.setattr(turbo_host_llm, "ancestor_names", lambda limit=12: [])


@pytest.fixture
def admitting_capacity(monkeypatch) -> None:
    """Pin the documented physical-admission profile so host disk or memory pressure cannot block a dispatch test.

    The thresholds stay ascending but sit just under 100 and the disk reserve is zero, so a host is refused
    only at 99.9% pressure instead of the 88% default. Subprocesses inherit it through the environment.
    """
    for name, value in (
        ("TARGET_PRESSURE_PERCENT", "99.1"), ("NO_NEW_PRESSURE_PERCENT", "99.3"),
        ("CHECKPOINT_PRESSURE_PERCENT", "99.5"), ("TERMINATE_PRESSURE_PERCENT", "99.9"),
        ("DISK_SUSPEND_PERCENT", "100"), ("DISK_SUSPEND_FLOOR_BYTES", "0"), ("DISK_RESERVE_BYTES", "0"),
    ):
        monkeypatch.setenv("SIMPLICIO_LOOP_" + name, value)


def pytest_configure(config) -> None:
    """Make `check.py --core-gate` unable to reach the real network.

    This is deliberately opt-in so normal pytest runs and tests which exercise
    local AF_UNIX IPC retain their native socket behaviour.
    """
    if os.environ.get("SIMPLICIO_CORE_NO_NETWORK") != "1":
        return
    install_core_network_guard()
