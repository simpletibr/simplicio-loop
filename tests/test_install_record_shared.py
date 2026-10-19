"""One install-record lookup for every reader of the installed version and install kind, the daemon included.

``daemon/client.py`` puts its own checkout first on sys.path. An editable install leaves ``simplicio_loop.egg-info``
in that checkout: a build artifact with no ``direct_url.json`` and the artifact's version. A reader that takes the first
``importlib.metadata`` match then answers with the artifact, where the in-process run answers with the record pip
wrote. These tests put that stale artifact first on sys.path and expect each reader to give the pip record's answer.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from simplicio_loop import distribution as dist
from simplicio_loop import version_drift
from simplicio_loop.daemon.server import Daemon

PIP_VERSION = "3.49.0"  # what pip recorded for the running install
ARTIFACT_VERSION = "3.50.0"  # what the stale egg-info in the checkout says


def _build_stale_checkout(tmp_path: Path) -> tuple[Path, Path]:
    """What ``pip install -e`` leaves: an egg-info in the checkout, and in site-packages the dist-info pip wrote."""
    checkout = tmp_path / "checkout"
    egg_info = checkout / "simplicio_loop.egg-info"
    egg_info.mkdir(parents=True)
    (egg_info / "PKG-INFO").write_text(
        f"Metadata-Version: 2.1\nName: simplicio-loop\nVersion: {ARTIFACT_VERSION}\n", encoding="utf-8")
    site = tmp_path / "site-packages"
    record = site / f"simplicio_loop-{PIP_VERSION}.dist-info"
    record.mkdir(parents=True)
    (record / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: simplicio-loop\nVersion: {PIP_VERSION}\n", encoding="utf-8")
    (record / "direct_url.json").write_text(
        json.dumps({"url": checkout.as_uri(), "dir_info": {"editable": True}}), encoding="utf-8")
    return checkout, site


def _stale_egg_info_first(tmp_path: Path, monkeypatch) -> Path:
    checkout, site = _build_stale_checkout(tmp_path)
    monkeypatch.syspath_prepend(str(site))
    monkeypatch.syspath_prepend(str(checkout))  # the daemon's order: its checkout is searched first
    monkeypatch.delattr(sys, "frozen", raising=False)
    return checkout


def test_the_install_record_is_the_one_pip_wrote(tmp_path, monkeypatch):
    _stale_egg_info_first(tmp_path, monkeypatch)
    assert dist.install_record().version == PIP_VERSION


def test_editable_and_kind_come_from_the_pip_record(tmp_path, monkeypatch):
    _stale_egg_info_first(tmp_path, monkeypatch)
    assert dist.is_editable() is True
    assert dist.kind(checkout=False) == dist.SOURCE


def test_running_version_comes_from_the_pip_record(tmp_path, monkeypatch):
    _stale_egg_info_first(tmp_path, monkeypatch)
    assert version_drift.running_version() == PIP_VERSION


def test_package_dunder_version_comes_from_the_pip_record_in_a_fresh_process(tmp_path):
    checkout, site = _build_stale_checkout(tmp_path)
    code = (f"import sys; sys.path[:0] = [{str(checkout)!r}, {str(site)!r}]; "
            "import simplicio_loop; print(simplicio_loop.__version__)")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout
    assert out.strip() == PIP_VERSION


def test_daemon_status_version_comes_from_the_pip_record(tmp_path, monkeypatch):
    _stale_egg_info_first(tmp_path, monkeypatch)
    daemon = Daemon(tmp_path / "run", key="install-record", roots=[])
    assert daemon.status()["version"] == PIP_VERSION


def test_stack_manifest_reads_the_pip_record_for_simplicio_loop(tmp_path, monkeypatch):
    _stale_egg_info_first(tmp_path, monkeypatch)
    from simplicio_loop import stack_manifest
    assert stack_manifest._installed_version("simplicio-loop") == PIP_VERSION


def test_stack_lock_reads_the_pip_record_for_simplicio_loop(tmp_path, monkeypatch):
    _stale_egg_info_first(tmp_path, monkeypatch)
    from simplicio_loop import stack_lock
    assert stack_lock._distribution_version("simplicio-loop", "simplicio_loop") == PIP_VERSION


def test_ecosystem_doctor_reads_the_pip_record_for_simplicio_loop(tmp_path, monkeypatch):
    _stale_egg_info_first(tmp_path, monkeypatch)
    from simplicio_loop import ecosystem_doctor
    info = ecosystem_doctor._distribution("simplicio-loop")
    assert info["installed"] is True and info["version"] == PIP_VERSION


def test_runtime_identity_locates_the_distribution_by_the_pip_record(tmp_path, monkeypatch):
    _stale_egg_info_first(tmp_path, monkeypatch)
    from simplicio_loop import extension_handshake
    assert extension_handshake.runtime_identity()["distribution_path"] == str((tmp_path / "site-packages").resolve())
