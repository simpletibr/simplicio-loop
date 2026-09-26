"""System-level "clean environment" proof for #293: install, verify, forcibly fail mid-install,
and roll back — all against a disposable target directory + disposable HOME + a PATH stripped of
everything except core utils, so nothing here can read or write real host state (no real pip
install, no real `~/.claude`, no real service).

Note on file placement: the issue's plan lists `tests/system/test_clean_install.py`. This repo's
actual system-test convention (see `tests/test_system_check.py`, `tests/test_system_276_e2e.py`)
is a flat `tests/test_system_*.py` file, because `scripts/check.py`'s own test runner globs
`tests/test_*.py` non-recursively (glob.glob, no `**`) — a `tests/system/` subdirectory would be
invisible to `python3 scripts/check.py --tests-only` even though a bare `pytest tests/` would
still find it via recursive discovery. Matching the existing flat convention keeps this test
wired into the same local gate as everything else.

This does NOT spin up a real venv/container (out of scope for a fast local gate) — it proves the
"clean environment" property the way the rest of this repo's system tests do: full isolation via
tmp_path + a throwaway HOME + a stripped PATH, driving the real CLI entrypoints as subprocesses,
never mocking install_lib/install_executor internals.
"""
import ast
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALL_LIB = ROOT / "scripts" / "install_lib.py"
SKILLS = ["simplicio-tasks", "simplicio-loop", "simplicio-orient",
          "simplicio-review", "simplicio-compress", "simplicio-learn",
          "simplicio-autoresearch"]


def _clean_env(home):
    """A PATH with no simplicio*/pip/uv/az shims and a throwaway HOME — the closest a fast local
    test can get to "a clean machine that has never seen simplicio-loop before"."""
    env = dict(os.environ)
    env["PATH"] = os.path.dirname(sys.executable)  # only the interpreter itself stays reachable
    env["HOME"] = str(home)
    return env


def _snapshot(target):
    return sorted(str(p.relative_to(target)).replace(os.sep, "/") for p in Path(target).rglob("*"))


def test_clean_install_then_smoke_check_then_uninstall_leaves_no_trace(tmp_path):
    target = tmp_path / "clean_target"
    target.mkdir()
    home = tmp_path / "clean_home"
    home.mkdir()
    baseline = _snapshot(target)
    assert baseline == [], "the clean target must start genuinely empty"

    # 1. dry-run first — the documented "show me before you touch anything" step.
    dry = subprocess.run(
        [sys.executable, str(INSTALL_LIB), "claude", "--target", str(target), "--dry-run"],
        capture_output=True, text=True, timeout=60, env=_clean_env(home),
        stdin=subprocess.DEVNULL,
    )
    assert dry.returncode == 0, dry.stdout + dry.stderr
    plan = json.loads(dry.stdout)
    assert plan["status"] == "PLANNED"
    assert _snapshot(target) == baseline, "dry-run must not mutate the clean target"

    # 2. real transactional install into the SAME clean target.
    apply = subprocess.run(
        [sys.executable, str(INSTALL_LIB), "claude", "--target", str(target),
         "--skip-operators", "--minimal", "--transactional"],
        capture_output=True, text=True, timeout=120, env=_clean_env(home),
        stdin=subprocess.DEVNULL,
    )
    assert apply.returncode == 0, apply.stdout + apply.stderr

    for s in SKILLS:
        skill_md = target / ".claude" / "skills" / s / "SKILL.md"
        assert skill_md.is_file(), "%s not installed cleanly" % s

    # 3a. smoke test (issue #293 step 6, baseline): every installed .py hook/worker must at
    # least PARSE — proof the copy landed intact, not truncated/corrupted, on a machine with
    # none of this repo's own tooling pre-installed.
    checked = 0
    for py_file in (target / "hooks").glob("*.py"):
        ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        checked += 1
    for py_file in (target / "scripts").glob("install_*.py"):
        ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        checked += 1
    assert checked >= 5, "expected to smoke-check several installed worker scripts"

    # 3b. richer smoke (issue #293 step 6, the actual ask): don't just parse — RUN the
    # installed copies for real and assert on their real output. `--help`/doctor/preflight and a
    # real minimal task (`task_anchor.py selftest`), all against THIS clean target's copies.
    sys.path.insert(0, str(ROOT / "scripts"))
    import install_post_smoke  # noqa: E402  (imported late: keeps this file import-light otherwise)
    smoke = install_post_smoke.run_post_install_smoke(str(target))
    assert smoke["ok"], smoke

    receipts = list((target / ".simplicio-loop" / "receipts").glob("*.json"))
    assert len(receipts) == 1
    receipt = json.loads(receipts[0].read_text(encoding="utf-8"))
    assert receipt["status"] == "APPLIED"

    # 4. uninstall == rollback the transaction. The clean target must return to baseline (plus
    # the now-empty .simplicio-loop bookkeeping dir — the receipt of what happened is legitimately
    # kept, only the installed content is undone).
    rb = subprocess.run(
        [sys.executable, str(INSTALL_LIB), "rollback", receipt["transaction_id"],
         "--target", str(target)],
        capture_output=True, text=True, timeout=60, env=_clean_env(home),
        stdin=subprocess.DEVNULL,
    )
    assert rb.returncode == 0, rb.stdout + rb.stderr
    assert json.loads(rb.stdout)["status"] == "ROLLED_BACK"

    remaining_content = [p for p in _snapshot(target) if not p.startswith(".simplicio-loop")]
    assert remaining_content == [], \
        "uninstall must not leave any installed content behind: %r" % remaining_content


def test_forced_failure_mid_install_leaves_a_genuinely_clean_target(tmp_path):
    """The other half of "comprovada em ambientes limpos": a transaction that dies partway
    through (simulated via the test-only --test-fail-step hook, standing in for a real crash —
    disk full, killed process, etc.) must leave the SAME clean target it started from, not a
    half-installed mess with no way back."""
    target = tmp_path / "clean_target_fail"
    target.mkdir()
    home = tmp_path / "clean_home_fail"
    home.mkdir()
    baseline = _snapshot(target)

    r = subprocess.run(
        [sys.executable, str(INSTALL_LIB), "claude", "--target", str(target),
         "--skip-operators", "--minimal", "--transactional",
         "--test-fail-step", "claude_settings"],
        capture_output=True, text=True, timeout=120, env=_clean_env(home),
        stdin=subprocess.DEVNULL,
    )
    assert r.returncode == 4, r.stdout + r.stderr
    assert "ROLLED_BACK" in r.stdout

    for s in SKILLS:
        assert not (target / ".claude" / "skills" / s).exists(), \
            "%s must not survive a rolled-back transaction" % s
    assert not (target / "hooks").exists()
    assert not (target / "scripts").exists()
    assert not (target / ".claude" / "settings.json").exists()

    receipts = list((target / ".simplicio-loop" / "receipts").glob("*.json"))
    assert len(receipts) == 1
    receipt = json.loads(receipts[0].read_text(encoding="utf-8"))
    assert receipt["status"] == "ROLLED_BACK"
    assert receipt.get("error")

    remaining_content = [p for p in _snapshot(target) if not p.startswith(".simplicio-loop")]
    assert remaining_content == baseline, \
        "a rolled-back mid-transaction failure must leave the target exactly as clean as before"


def test_clean_install_survives_unicode_and_spaces_in_target_path(tmp_path):
    """#293 "Testes obrigatórios > Sistema": "caminhos com espaços e Unicode". A target directory
    whose name has embedded spaces AND non-ASCII characters (accents + CJK) must install,
    smoke-check, and roll back exactly like the plain-ASCII clean target above — proves the
    executor's hashing/backup/receipt path-handling (`_hash_path`, `install-mutations.json`
    normalization) doesn't choke on paths that aren't just `[a-zA-Z0-9_/]`."""
    target = tmp_path / "clean tärget with späces 目录 293"
    target.mkdir()
    home = tmp_path / "clean home"
    home.mkdir()
    baseline = _snapshot(target)
    assert baseline == []

    apply = subprocess.run(
        [sys.executable, str(INSTALL_LIB), "claude", "--target", str(target),
         "--skip-operators", "--minimal", "--transactional"],
        capture_output=True, text=True, timeout=120, env=_clean_env(home),
        stdin=subprocess.DEVNULL,
    )
    assert apply.returncode == 0, apply.stdout + apply.stderr

    for s in SKILLS:
        skill_md = target / ".claude" / "skills" / s / "SKILL.md"
        assert skill_md.is_file(), "%s not installed cleanly into a unicode/space path" % s

    receipts = list((target / ".simplicio-loop" / "receipts").glob("*.json"))
    assert len(receipts) == 1
    receipt = json.loads(receipts[0].read_text(encoding="utf-8"))
    assert receipt["status"] == "APPLIED"

    rb = subprocess.run(
        [sys.executable, str(INSTALL_LIB), "rollback", receipt["transaction_id"],
         "--target", str(target)],
        capture_output=True, text=True, timeout=60, env=_clean_env(home),
        stdin=subprocess.DEVNULL,
    )
    assert rb.returncode == 0, rb.stdout + rb.stderr
    assert json.loads(rb.stdout)["status"] == "ROLLED_BACK"

    remaining_content = [p for p in _snapshot(target) if not p.startswith(".simplicio-loop")]
    assert remaining_content == [], \
        "rollback of a unicode/space-path install must leave no installed content behind: %r" \
        % remaining_content


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _selfrun import run_module
    run_module(globals(), "test_system_clean_install")
