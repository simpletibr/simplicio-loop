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

from simplicio_loop.hub_daemon import default_transport
from simplicio_loop.platform_capabilities import probe_af_unix, probe_hub_transport
from simplicio_loop.core_network_guard import install as install_core_network_guard


@pytest.fixture(autouse=True)
def disable_operator_bootstrap_network_by_default(monkeypatch) -> None:
    """Hermetic tests opt into the real bootstrap explicitly at their test seam."""
    monkeypatch.setenv("SIMPLICIO_LOOP_AUTO_BOOTSTRAP_OPERATORS", "0")


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


def _skip_when_unavailable(capability) -> None:
    if not capability.available:
        pytest.skip(
            "CAPABILITY_UNAVAILABLE[%s]: %s"
            % (capability.reason_code, capability.detail)
        )


@pytest.fixture
def require_af_unix() -> None:
    _skip_when_unavailable(probe_af_unix())


@pytest.fixture
def require_default_hub_transport() -> None:
    _skip_when_unavailable(probe_hub_transport(default_transport()))
