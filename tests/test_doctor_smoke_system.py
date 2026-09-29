"""#78: coverage for scripts/doctor.py — the stack-verifier with no built-in selftest.

doctor.py has no --target/--global: it always inspects the REAL home directory (read-only
unless --repair, which we never invoke here — no real pip installs / service wiring / network).
To keep results deterministic regardless of the host machine, every subprocess run below
overrides HOME to an empty tmp_path so the skills/hooks checks report a clean, reproducible
FAIL rather than depending on whatever happens to be installed on the box running the suite.
"""
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCTOR = os.path.join(REPO, "scripts", "doctor.py")


def _run_doctor(args, tmp_path, extra_env=None):
    env = dict(os.environ)
    env["HOME"] = str(tmp_path)
    # pathlib.Path.home() on Windows follows USERPROFILE/HOMEDRIVE/HOMEPATH,
    # not only HOME. Override all home selectors so the fresh-home fixture is
    # deterministic on every supported host.
    env["USERPROFILE"] = str(tmp_path)
    env["HOMEDRIVE"] = str(tmp_path.drive or "C:")
    env["HOMEPATH"] = str(tmp_path)[len(str(tmp_path.drive or "C:")):]
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("ANTHROPIC_API_KEY", None)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, DOCTOR] + args,
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        env=env,
        timeout=60,
        stdin=subprocess.DEVNULL,
        encoding="utf-8",
        errors="replace",
    )


def test_doctor_json_mode_is_well_formed_and_never_crashes(tmp_path):
    r = _run_doctor(["--json"], tmp_path)
    assert r.returncode in (0, 1), r.stdout + r.stderr
    items = json.loads(r.stdout)
    assert isinstance(items, list) and len(items) >= 5, items
    names = {it["name"] for it in items}
    assert "python3" in names
    for it in items:
        assert it["tier"] in ("REQUIRED", "RECOMMENDED", "OPTIONAL"), it
        assert it["status"] in ("ok", "warn", "fail"), it
        assert "repair" not in it, "the fixer callable must never leak into --json output"


def test_doctor_python_check_always_ok(tmp_path):
    # This suite already requires python3 >= 3.8 to run at all, so the python3 check must pass.
    r = _run_doctor(["--json"], tmp_path)
    items = json.loads(r.stdout)
    py = next(it for it in items if it["name"] == "python3")
    assert py["status"] == "ok", py


def test_doctor_fresh_home_reports_required_items_missing_and_exits_1(tmp_path):
    # An empty HOME has no ~/.claude/skills and no ~/.claude/hooks/loop_stop.py -> both REQUIRED
    # checks fail (never crash), so the overall exit code must be 1, never a traceback.
    r = _run_doctor(["--json"], tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    items = json.loads(r.stdout)
    skills = next(it for it in items if it["name"] == "skills (global)")
    hooks = next(it for it in items if "Stop wire" in it["name"])
    assert skills["status"] == "fail", skills
    assert hooks["status"] == "fail", hooks


def test_doctor_text_mode_prints_glyphs_and_summary(tmp_path):
    r = _run_doctor([], tmp_path)
    assert r.returncode in (0, 1), r.stdout + r.stderr
    assert "simplicio-loop doctor" in r.stdout
    assert "REQUIRED broken" in r.stdout or "all REQUIRED items healthy" in r.stdout


def test_doctor_exit_code_matches_required_fail_presence(tmp_path):
    r = _run_doctor(["--json"], tmp_path)
    items = json.loads(r.stdout)
    any_required_fail = any(it["tier"] == "REQUIRED" and it["status"] == "fail" for it in items)
    assert r.returncode == (1 if any_required_fail else 0)


def test_doctor_help_exits_cleanly(tmp_path):
    r = _run_doctor(["--help"], tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "--repair" in r.stdout and "--json" in r.stdout


def test_doctor_unknown_flag_is_a_clean_argparse_error_not_a_traceback(tmp_path):
    r = _run_doctor(["--bogus-flag"], tmp_path)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "Traceback" not in r.stderr
    assert "usage" in r.stderr.lower()


def test_doctor_has_no_remote_worker_check(tmp_path):
    r = _run_doctor(["--json"], tmp_path)
    names = [item["name"] for item in json.loads(r.stdout)]
    assert names and not any("remote worker" in name for name in names)


def test_doctor_never_invokes_repair_by_default(tmp_path):
    # Sanity: without --repair, doctor must be read-only. We assert this indirectly — running it
    # twice back-to-back on the same empty HOME must produce IDENTICAL required-item statuses
    # (a mutation, e.g. an accidental install, would change the second run's results).
    r1 = _run_doctor(["--json"], tmp_path)
    r2 = _run_doctor(["--json"], tmp_path)
    items1 = json.loads(r1.stdout)
    items2 = json.loads(r2.stdout)
    statuses1 = {it["name"]: it["status"] for it in items1}
    statuses2 = {it["name"]: it["status"] for it in items2}
    assert statuses1 == statuses2


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _selfrun import run_module
    run_module(globals(), "test_doctor_smoke")
