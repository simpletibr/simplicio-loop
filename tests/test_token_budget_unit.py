"""Token/Context Budget Guard (#121) — proves the guard reports sizes and FAILS on a regression.

The guard estimates tokens for SKILL.md/AGENTS.md/the largest scripts, compares against
the committed baseline (`scripts/token_budget_baseline.json`), and must FAIL when a tracked
artifact grows past its threshold — the acceptance test explicitly asked for: "editing SKILL.md to
add 2000 words makes the guard fail with a clear message."
"""
import json
import os
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUARD = os.path.join(REPO, "scripts", "token_budget.py")
SKILL_MD = os.path.join(REPO, ".claude", "skills", "simplicio-loop", "SKILL.md")
BASELINE = os.path.join(REPO, "scripts", "token_budget_baseline.json")


def _run(args, cwd=None):
    return subprocess.run([sys.executable, GUARD] + args, capture_output=True, text=True,
                          cwd=cwd or REPO, stdin=subprocess.DEVNULL)


def test_baseline_is_committed_and_readable():
    assert os.path.exists(BASELINE), "scripts/token_budget_baseline.json must be committed"
    with open(BASELINE, encoding="utf-8") as f:
        data = json.load(f)
    assert "artifacts" in data and data["artifacts"], "baseline must list tracked artifacts"
    assert ".claude/skills/simplicio-loop/SKILL.md" in data["artifacts"]


def test_report_passes_against_committed_baseline():
    r = _run([])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "token-budget: PASS" in r.stdout
    # Readable output: shows estimated tokens + delta vs baseline for the tracked artifacts.
    assert "SKILL.md" in r.stdout
    assert "baseline" in r.stdout


def test_check_mode_is_quiet_on_pass():
    r = _run(["--check"])
    assert r.returncode == 0
    assert r.stdout.strip() == "", "quiet --check mode should print nothing on a passing run"


def test_regression_fails_with_a_clear_message():
    """Adding ~2000 words to SKILL.md must make the guard FAIL with a readable message.

    Runs against a scratch copy of the whole repo tree the guard cares about, so the real
    checked-in SKILL.md is never touched by this test.
    """
    with tempfile.TemporaryDirectory() as scratch:
        # Mirror only what token_budget.py reads: the baseline + the tracked artifacts, rooted the
        # same way relative to scripts/token_budget.py's REPO (its own parent dir).
        scripts_dir = os.path.join(scratch, "scripts")
        os.makedirs(scripts_dir)
        for name in ("token_budget.py", "token_budget_baseline.json"):
            with open(os.path.join(REPO, "scripts", name), "rb") as src, \
                 open(os.path.join(scripts_dir, name), "wb") as dst:
                dst.write(src.read())

        skill_dir = os.path.join(scratch, ".claude", "skills", "simplicio-loop")
        os.makedirs(skill_dir)
        with open(SKILL_MD, "rb") as src:
            original = src.read()
        padded = original + ("\n\n" + (" padding" * 2000) + "\n").encode("utf-8")
        with open(os.path.join(skill_dir, "SKILL.md"), "wb") as dst:
            dst.write(padded)

        r = subprocess.run([sys.executable, os.path.join(scripts_dir, "token_budget.py"),
                            "--check"], capture_output=True, text=True, cwd=scratch,
                           stdin=subprocess.DEVNULL)
        assert r.returncode == 1, "adding 2000 words to SKILL.md must fail the guard: " + r.stdout
        assert "FAIL" in r.stdout
        assert "SKILL.md" in r.stdout
        assert "threshold" in r.stdout


def test_update_baseline_writes_valid_json(tmp_path):
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "token_budget.py").write_bytes(open(GUARD, "rb").read())
    skill_dir = tmp_path / ".claude" / "skills" / "simplicio-loop"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("hello world\n" * 10, encoding="utf-8")

    r = subprocess.run([sys.executable, str(scripts_dir / "token_budget.py"),
                        "--update-baseline"], capture_output=True, text=True, cwd=str(tmp_path),
                       stdin=subprocess.DEVNULL)
    assert r.returncode == 0, r.stdout + r.stderr
    baseline_path = scripts_dir / "token_budget_baseline.json"
    assert baseline_path.exists()
    with open(baseline_path, encoding="utf-8") as f:
        data = json.load(f)
    assert data["estimator"]
    assert ".claude/skills/simplicio-loop/SKILL.md" in data["artifacts"]


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _selfrun import run_module
    run_module(globals(), "test_token_budget")
