"""Additional unit coverage for simplicio/ecosystem.py.

Covers the previously-uncovered branches: pyproject dep-name parsing
(both the tomllib and regex-fallback paths), tracked_packages dedup,
check() reason strings, ensure_latest's real pip invocation + subprocess
error handling, HOOK_GUARD / SKIP_AUTO_INIT / already-ran short-circuits
in maybe_run_session_start, and PyPI cache read/write helpers.
"""

from __future__ import annotations

import importlib
import json
import subprocess

import pytest

import simplicio.ecosystem as eco


def _reload():
    module = importlib.reload(eco)
    if hasattr(module, module._SENTINEL_NAME):
        delattr(module, module._SENTINEL_NAME)
    return module


# ---------------------------------------------------------------------------
# _pyproject_dep_names / tracked_packages
# ---------------------------------------------------------------------------


def test_pyproject_dep_names_via_tomllib(tmp_path, monkeypatch):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[project]
dependencies = ["numpy>=2.1.0", "httpx>=0.28.1"]

[project.optional-dependencies]
test = ["pytest>=8"]
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(eco, "_pyproject_path", lambda: pyproject)
    names = eco._pyproject_dep_names()
    assert "numpy" in names
    assert "httpx" in names
    assert "pytest" in names


def test_pyproject_dep_names_regex_fallback(tmp_path, monkeypatch):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        'dependencies = ["numpy>=2.1.0"]\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(eco, "_pyproject_path", lambda: pyproject)

    import builtins

    real_import = builtins.__import__

    def _fake_import(name, *a, **k):
        if name == "tomllib":
            raise ImportError("no tomllib")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    names = eco._pyproject_dep_names()
    assert "numpy" in names


def test_pyproject_dep_names_no_pyproject(monkeypatch):
    monkeypatch.setattr(eco, "_pyproject_path", lambda: None)
    assert eco._pyproject_dep_names() == []


def test_pyproject_dep_names_read_error(tmp_path, monkeypatch):
    missing = tmp_path / "nope.toml"
    monkeypatch.setattr(eco, "_pyproject_path", lambda: missing)
    assert eco._pyproject_dep_names() == []


def test_tracked_packages_dedups_ecosystem_names(monkeypatch):
    monkeypatch.setattr(eco, "_pyproject_dep_names", lambda: ["simplicio-prompt", "numpy"])
    names = eco.tracked_packages()
    assert names.count("simplicio-prompt") == 1
    assert "numpy" in names
    assert tuple(names[: len(eco.ECOSYSTEM)]) == eco.ECOSYSTEM


# ---------------------------------------------------------------------------
# check() reason strings
# ---------------------------------------------------------------------------


def test_check_reason_below_floor(monkeypatch):
    monkeypatch.setattr(eco, "_installed_version", lambda name: "0.9.0")
    monkeypatch.setattr(eco, "_read_floor", lambda name: "1.0.0")
    monkeypatch.setattr(eco, "_pypi_latest", lambda name, refresh=False: "1.2.0")

    statuses = eco.check(("simplicio-prompt",))
    assert statuses[0].needs_upgrade is True
    assert "pyproject floor" in statuses[0].reason


def test_check_reason_below_latest_not_floor(monkeypatch):
    monkeypatch.setattr(eco, "_installed_version", lambda name: "1.0.0")
    monkeypatch.setattr(eco, "_read_floor", lambda name: "1.0.0")
    monkeypatch.setattr(eco, "_pypi_latest", lambda name, refresh=False: "1.2.0")

    statuses = eco.check(("simplicio-prompt",))
    assert statuses[0].needs_upgrade is True
    assert "< latest" in statuses[0].reason


def test_check_up_to_date(monkeypatch):
    monkeypatch.setattr(eco, "_installed_version", lambda name: "1.2.0")
    monkeypatch.setattr(eco, "_read_floor", lambda name: "1.0.0")
    monkeypatch.setattr(eco, "_pypi_latest", lambda name, refresh=False: "1.2.0")

    statuses = eco.check(("simplicio-prompt",))
    assert statuses[0].needs_upgrade is False
    assert statuses[0].reason == ""


def test_dep_status_to_dict_roundtrips():
    status = eco.DepStatus("pkg", "1.0.0", "1.0.0", "1.1.0", True, "stale")
    d = status.to_dict()
    assert d["name"] == "pkg"
    assert d["needs_upgrade"] is True


# ---------------------------------------------------------------------------
# ensure_latest — real pip path + error handling
# ---------------------------------------------------------------------------


def test_ensure_latest_no_drift_returns_empty(monkeypatch):
    monkeypatch.delenv("SIMPLICIO_NO_AUTO_UPGRADE", raising=False)
    monkeypatch.setattr(eco, "check", lambda packages: [])
    assert eco.ensure_latest() == []


def test_ensure_latest_invokes_pip_successfully(monkeypatch):
    monkeypatch.delenv("SIMPLICIO_NO_AUTO_UPGRADE", raising=False)
    monkeypatch.setattr(
        eco,
        "check",
        lambda packages: [eco.DepStatus("simplicio-prompt", "1.0.0", "1.1.0", "1.1.0", True, "x")],
    )
    calls = []
    monkeypatch.setattr(
        eco.subprocess,
        "run",
        lambda cmd, **kwargs: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0),
    )
    result = eco.ensure_latest()
    assert result == ["simplicio-prompt"]
    assert calls and calls[0][-1] == "simplicio-prompt"


def test_ensure_latest_pip_raises_returns_empty(monkeypatch):
    monkeypatch.delenv("SIMPLICIO_NO_AUTO_UPGRADE", raising=False)
    monkeypatch.setattr(
        eco,
        "check",
        lambda packages: [eco.DepStatus("simplicio-prompt", "1.0.0", "1.1.0", "1.1.0", True, "x")],
    )

    def _boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="pip", timeout=1)

    monkeypatch.setattr(eco.subprocess, "run", _boom)
    result = eco.ensure_latest()
    assert result == []


def test_ensure_latest_respects_no_auto_upgrade_env(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_NO_AUTO_UPGRADE", "1")
    assert eco.ensure_latest() == []


def test_ensure_latest_force_overrides_no_auto_upgrade(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_NO_AUTO_UPGRADE", "1")
    monkeypatch.setattr(eco, "check", lambda packages: [])
    assert eco.ensure_latest(force=True) == []


# ---------------------------------------------------------------------------
# maybe_run_session_start short-circuits
# ---------------------------------------------------------------------------


def test_maybe_run_session_start_hook_guard(monkeypatch):
    module = _reload()
    monkeypatch.setenv("SIMPLICIO_AUTO_UPGRADE", "1")
    monkeypatch.setenv("SIMPLICIO_HOOK_GUARD", "1")
    calls = []
    monkeypatch.setattr(module, "ensure_latest", lambda: calls.append(True) or [])
    module.maybe_run_session_start()
    assert calls == []


def test_maybe_run_session_start_skip_auto_init(monkeypatch):
    module = _reload()
    monkeypatch.delenv("SIMPLICIO_HOOK_GUARD", raising=False)
    monkeypatch.setenv("SIMPLICIO_AUTO_UPGRADE", "1")
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")
    calls = []
    monkeypatch.setattr(module, "ensure_latest", lambda: calls.append(True) or [])
    module.maybe_run_session_start()
    assert calls == []


def test_maybe_run_session_start_only_once_per_process(monkeypatch):
    module = _reload()
    monkeypatch.delenv("SIMPLICIO_HOOK_GUARD", raising=False)
    monkeypatch.delenv("SIMPLICIO_SKIP_AUTO_INIT", raising=False)
    monkeypatch.delenv("SIMPLICIO_NO_AUTO_UPGRADE", raising=False)
    monkeypatch.setenv("SIMPLICIO_AUTO_UPGRADE", "1")
    calls = []
    monkeypatch.setattr(module, "ensure_latest", lambda: calls.append(True) or [])

    module.maybe_run_session_start()
    module.maybe_run_session_start()

    assert calls == [True]


def test_maybe_run_session_start_logs_when_upgraded(monkeypatch, caplog):
    module = _reload()
    monkeypatch.delenv("SIMPLICIO_HOOK_GUARD", raising=False)
    monkeypatch.delenv("SIMPLICIO_SKIP_AUTO_INIT", raising=False)
    monkeypatch.delenv("SIMPLICIO_NO_AUTO_UPGRADE", raising=False)
    monkeypatch.setenv("SIMPLICIO_AUTO_UPGRADE", "1")
    monkeypatch.setattr(module, "ensure_latest", lambda: ["simplicio-prompt"])

    with caplog.at_level("INFO", logger="simplicio"):
        module.maybe_run_session_start()

    assert "auto-upgraded" in caplog.text


# ---------------------------------------------------------------------------
# PyPI cache helpers
# ---------------------------------------------------------------------------


def test_cache_path_uses_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("SIMPLICIO_CACHE_DIR", str(tmp_path))
    assert eco._cache_path() == tmp_path / "pypi_versions.json"


def test_read_pypi_cache_missing_file_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(eco, "_cache_path", lambda: tmp_path / "nope.json")
    assert eco._read_pypi_cache() == {}


def test_read_pypi_cache_invalid_json_returns_empty(tmp_path, monkeypatch):
    cache_file = tmp_path / "pypi_versions.json"
    cache_file.write_text("not json", encoding="utf-8")
    monkeypatch.setattr(eco, "_cache_path", lambda: cache_file)
    assert eco._read_pypi_cache() == {}


def test_read_pypi_cache_non_dict_returns_empty(tmp_path, monkeypatch):
    cache_file = tmp_path / "pypi_versions.json"
    cache_file.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    monkeypatch.setattr(eco, "_cache_path", lambda: cache_file)
    assert eco._read_pypi_cache() == {}


def test_write_pypi_cache_roundtrips(tmp_path, monkeypatch):
    cache_file = tmp_path / "sub" / "pypi_versions.json"
    monkeypatch.setattr(eco, "_cache_path", lambda: cache_file)
    eco._write_pypi_cache({"pkg": {"version": "1.0.0", "ts": 0}})
    assert json.loads(cache_file.read_text(encoding="utf-8")) == {"pkg": {"version": "1.0.0", "ts": 0}}


def test_write_pypi_cache_swallows_oserror(monkeypatch):
    def _boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(eco.Path, "mkdir", _boom)
    eco._write_pypi_cache({"pkg": {"version": "1.0.0"}})  # must not raise


def test_pypi_latest_uses_fresh_cache(monkeypatch, tmp_path):
    cache_file = tmp_path / "pypi_versions.json"
    cache_file.write_text(
        json.dumps({"simplicio-prompt": {"version": "9.9.9", "ts": __import__("time").time()}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(eco, "_cache_path", lambda: cache_file)

    def _boom(*a, **k):
        raise AssertionError("should not hit network when cache is fresh")

    monkeypatch.setattr(eco.urllib.request, "urlopen", _boom)
    assert eco._pypi_latest("simplicio-prompt") == "9.9.9"


def test_pypi_latest_falls_back_to_stale_cache_on_network_error(monkeypatch, tmp_path):
    cache_file = tmp_path / "pypi_versions.json"
    cache_file.write_text(
        json.dumps({"simplicio-prompt": {"version": "1.2.3", "ts": 0}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(eco, "_cache_path", lambda: cache_file)

    def _boom(*a, **k):
        raise OSError("network unreachable")

    monkeypatch.setattr(eco.urllib.request, "urlopen", _boom)
    assert eco._pypi_latest("simplicio-prompt") == "1.2.3"


def test_pypi_latest_returns_none_on_error_with_no_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(eco, "_cache_path", lambda: tmp_path / "nope.json")

    def _boom(*a, **k):
        raise OSError("network unreachable")

    monkeypatch.setattr(eco.urllib.request, "urlopen", _boom)
    assert eco._pypi_latest("simplicio-prompt") is None


def test_version_lt_unparseable_returns_false():
    assert eco._version_lt("not-a-version", "1.0.0") is False


def test_version_lt_none_inputs():
    assert eco._version_lt(None, "1.0.0") is False
    assert eco._version_lt("1.0.0", None) is False
