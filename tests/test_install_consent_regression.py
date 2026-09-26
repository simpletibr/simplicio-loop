"""Regression coverage for the #293 consent-gating fixes made this round:

1. The legacy (non-transactional) `install_lib.py main()` flow used to call `setup_monitor(not
   minimal)` — i.e. it registered the capture proxy / wired provider base URLs / opened the
   dashboard BY DEFAULT, with `--minimal` as the only opt-out. That directly contradicted #293
   AC1 ("O modo padrão é mínimo e não cria serviços, não altera proxy/base URL global e não abre
   browser."). It now requires the EXPLICIT `--with-service` (or `--full-stack`) flag.

2. `install_plan.build_plan(mode="full-stack")` used to silently grant the `service`/`proxy`
   permissions the mode requires just because `mode == "full-stack"` was chosen — the mode name
   alone was treated as consent, contradicting #293 step 2.4 ("impedir que ... serviço ou proxy
   sejam inferidos silenciosamente"). It now stays BLOCKED until `--with-service` AND
   `--with-proxy` are ALSO passed explicitly.

3. `install_executor.apply(mode="full-stack", ...)` now has a real, distinct file-effect surface
   (copies `engine/`+`app/`) instead of being functionally identical to `minimal`/`runtime`.

SAFETY: every subprocess invocation below passes --skip-operators (+ --minimal where the test
is not specifically exercising the --with-service gate) and redirects HOME/APPDATA into tmp_path,
so nothing here can register a real systemd unit, Windows Startup shim, or launchd agent, or
rewrite the real host's OPENAI_BASE_URL/ANTHROPIC_BASE_URL. `setup_monitor()`'s own subprocess
calls are `check=False` best-effort against install_services.py, which itself only ever touches
the redirected HOME/APPDATA — never the real host.
"""
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


sys.path.insert(0, str(SCRIPTS))
install_lib = _load("install_lib", "install_lib.py")
install_plan = _load("install_plan", "install_plan.py")
install_executor = _load("install_executor", "install_executor.py")

build_plan = install_plan.build_plan


def _safe_env(tmp_home):
    env = dict(os.environ)
    env["PATH"] = "/usr/bin:/bin"
    env["HOME"] = str(tmp_home)
    env["APPDATA"] = str(tmp_home / "AppData" / "Roaming")
    env["XDG_CONFIG_HOME"] = str(tmp_home / ".config")
    env["SIMPLICIO_NO_BROWSER"] = "1"
    return env


# ── 1. legacy flow: setup_monitor() consent gate ────────────────────────────────────────────────

def test_setup_monitor_is_off_by_default_no_flags_at_all(tmp_path):
    target = tmp_path / "project"
    target.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    r = subprocess.run(
        [sys.executable, str(SCRIPTS / "install_lib.py"), "claude", "--target", str(target),
         "--skip-operators"],  # deliberately NO --minimal, NO --with-service: the true default
        capture_output=True, text=True, timeout=120, env=_safe_env(home),
        stdin=subprocess.DEVNULL,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert "token monitor SKIPPED" in r.stdout, \
        "the default (no flags) install must SKIP the capture proxy/service/browser: %r" % r.stdout
    # No systemd unit / Startup shim landed in the redirected HOME/APPDATA either.
    assert not (home / ".config" / "systemd").exists()
    assert not (home / "AppData").exists()


@pytest.mark.external_integration
def test_setup_monitor_runs_only_with_explicit_with_service_flag(tmp_path):
    target = tmp_path / "project"
    target.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    r = subprocess.run(
        [sys.executable, str(SCRIPTS / "install_lib.py"), "claude", "--target", str(target),
         "--skip-operators", "--with-service"],
        capture_output=True, text=True, timeout=120, env=_safe_env(home),
        stdin=subprocess.DEVNULL,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert "token monitor SKIPPED" not in r.stdout
    assert "token capture: always-on proxy" in r.stdout


def test_explicit_minimal_flag_still_skips_even_if_with_service_also_passed(tmp_path):
    # --minimal remains an unconditional opt-out, same as before this round.
    target = tmp_path / "project"
    target.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    r = subprocess.run(
        [sys.executable, str(SCRIPTS / "install_lib.py"), "claude", "--target", str(target),
         "--skip-operators", "--minimal", "--with-service"],
        capture_output=True, text=True, timeout=120, env=_safe_env(home),
        stdin=subprocess.DEVNULL,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert "token monitor SKIPPED" in r.stdout


def test_setup_monitor_function_no_op_when_disabled(monkeypatch):
    calls = []
    monkeypatch.setattr(install_lib.subprocess, "run", lambda *a, **k: calls.append(a))
    install_lib.setup_monitor(False)
    assert calls == [], "setup_monitor(False) must not shell out to any service manager"


# ── 2. planner: full-stack mode no longer silently infers consent ──────────────────────────────

def test_full_stack_mode_alone_is_blocked_without_explicit_consent(tmp_path):
    plan = build_plan("claude", mode="full-stack", scope="project", target=str(tmp_path))
    assert plan["status"] == "BLOCKED"
    assert "full_stack_confirmation" in plan["blocked_reasons"]
    assert "service" in plan["permissions_required"]
    assert "proxy" in plan["permissions_required"]


def test_full_stack_mode_with_only_one_of_the_two_flags_stays_blocked(tmp_path):
    plan = build_plan("claude", mode="full-stack", scope="project", target=str(tmp_path),
                      with_service=True, with_proxy=False)
    assert plan["status"] == "BLOCKED"
    plan2 = build_plan("claude", mode="full-stack", scope="project", target=str(tmp_path),
                       with_service=False, with_proxy=True)
    assert plan2["status"] == "BLOCKED"


def test_full_stack_mode_with_both_explicit_flags_is_planned(tmp_path):
    plan = build_plan("claude", mode="full-stack", scope="project", target=str(tmp_path),
                      with_service=True, with_proxy=True)
    assert plan["status"] == "PLANNED"
    assert plan["blocked_reasons"] == []


def test_minimal_and_runtime_and_ci_modes_never_require_full_stack_confirmation(tmp_path):
    for mode in ("minimal", "runtime", "ci"):
        plan = build_plan("claude", mode=mode, scope="project", target=str(tmp_path))
        assert plan["status"] == "PLANNED", (mode, plan)
        assert plan["blocked_reasons"] == []


# ── 3. executor: full-stack has a real, distinct file surface ──────────────────────────────────

def test_full_stack_apply_is_blocked_without_consent_and_mutates_nothing(tmp_path):
    target = tmp_path / "project"
    target.mkdir()
    receipt = install_executor.apply("claude", target=str(target), is_global=False,
                                     mode="full-stack")
    assert receipt["status"] == "BLOCKED"
    assert not (target / ".claude").exists()
    assert not (target / ".simplicio-loop").exists()


@pytest.mark.external_integration
def test_full_stack_apply_with_consent_copies_engine_and_app(tmp_path, monkeypatch):
    # #293 gap 1: with_service=True now ALSO runs a real "service" step (install_executor.py
    # shells out to install_services.py) — redirect HOME/APPDATA/XDG_CONFIG_HOME into tmp_path
    # first (same safety pattern as every subprocess invocation in this file) so this in-process
    # apply() call can never register a real systemd unit / Windows Startup shim on the host
    # actually running the test suite.
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("APPDATA", str(home / "AppData" / "Roaming"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("SIMPLICIO_NO_BROWSER", "1")
    # Distinct, unlikely-to-collide port — avoids fighting a real dev proxy that may already be
    # bound to the module's own default (8788) on the host running this test.
    monkeypatch.setenv("SIMPLICIO_PROXY_PORT", "18799")
    target = tmp_path / "project"
    target.mkdir()
    receipt = install_executor.apply("claude", target=str(target), is_global=False,
                                     mode="full-stack", with_service=True, with_proxy=True)
    assert receipt["status"] == "APPLIED"
    assert (target / "engine" / "simplicio_engine.py").is_file()
    assert (target / "app" / "simplicio_tray.py").is_file()
    steps = {s["step"] for s in receipt["steps"]}
    assert "full_stack" in steps
    import platform as _platform
    if _platform.system() in ("Linux", "Windows"):
        # Only these two OSes have a concrete file the executor registers/backs up (#293 gap 1);
        # macOS stays the documented separate `setup_simplicio.sh` (launchd) path.
        assert "service" in steps
        service_step = next(s for s in receipt["steps"] if s["step"] == "service")
        # The service step actually registered something under the REDIRECTED home, never the
        # real host's Startup folder / systemd --user dir.
        assert str(home) in service_step["path"]


def test_minimal_and_runtime_and_ci_apply_never_copy_engine_or_app(tmp_path):
    for mode in ("minimal", "runtime", "ci"):
        target = tmp_path / ("project_%s" % mode)
        target.mkdir()
        receipt = install_executor.apply("claude", target=str(target), is_global=False, mode=mode)
        assert receipt["status"] == "APPLIED", (mode, receipt)
        assert not (target / "engine").exists(), mode
        assert not (target / "app").exists(), mode
        steps = {s["step"] for s in receipt["steps"]}
        assert "full_stack" not in steps, mode


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _selfrun import run_module
    run_module(globals(), "test_install_consent")
