"""CLI-level coverage for `install_lib.py rollback <transaction_id> --target DIR` (#293 step 5).

Complements `tests/test_install_transaction.py` (in-process `install_executor` unit tests) with
subprocess-level tests of the actual command surface an operator would run by hand: apply with
`--transactional`, inspect the receipt, roll back, verify a clean error for a bogus id, verify
rollback never touches anything outside the receipt.
"""
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


def _env(home):
    env = dict(os.environ)
    env["HOME"] = str(home)
    return env


def _install(runtime, target, home, extra_args=None):
    args = [sys.executable, str(INSTALL_LIB), runtime, "--target", str(target),
            "--skip-operators", "--minimal", "--transactional"] + (extra_args or [])
    return subprocess.run(args, capture_output=True, text=True, cwd=str(target),
                          env=_env(home), timeout=120, stdin=subprocess.DEVNULL)


def _rollback(transaction_id, target, home):
    args = [sys.executable, str(INSTALL_LIB), "rollback", transaction_id, "--target", str(target)]
    return subprocess.run(args, capture_output=True, text=True, cwd=str(target),
                          env=_env(home), timeout=60, stdin=subprocess.DEVNULL)


def _receipt_ids(target):
    d = Path(target) / ".simplicio-loop" / "receipts"
    if not d.is_dir():
        return []
    return [p.stem for p in d.glob("*.json")]


def test_transactional_apply_produces_a_receipt_with_status_applied(tmp_path):
    target = tmp_path / "t1"
    target.mkdir()
    r = _install("claude", target, tmp_path / "home1")
    assert r.returncode == 0, r.stdout + r.stderr
    ids = _receipt_ids(target)
    assert len(ids) == 1
    receipt = json.loads((target / ".simplicio-loop" / "receipts" / (ids[0] + ".json")).read_text())
    assert receipt["schema"] == "simplicio.install-transaction/v1"
    assert receipt["status"] == "APPLIED"


def test_rollback_removes_everything_the_transaction_created(tmp_path):
    target = tmp_path / "t2"
    target.mkdir()
    home = tmp_path / "home2"
    r = _install("claude", target, home)
    assert r.returncode == 0, r.stdout + r.stderr
    for s in SKILLS:
        assert (target / ".claude" / "skills" / s).is_dir()

    transaction_id = _receipt_ids(target)[0]
    rb = _rollback(transaction_id, target, home)
    assert rb.returncode == 0, rb.stdout + rb.stderr
    payload = json.loads(rb.stdout)
    assert payload["status"] == "ROLLED_BACK"

    for s in SKILLS:
        assert not (target / ".claude" / "skills" / s).exists()
    assert not (target / "hooks").exists()
    assert not (target / ".claude" / "settings.json").exists()


def test_rollback_unknown_transaction_id_is_a_clean_error(tmp_path):
    target = tmp_path / "t3"
    target.mkdir()
    home = tmp_path / "home3"
    home.mkdir()
    rb = _rollback("install-totally-made-up-id", target, home)
    assert rb.returncode == 3, rb.stdout + rb.stderr
    assert "no install receipt" in rb.stdout.lower()
    assert "Traceback" not in rb.stderr


def test_forced_mid_install_failure_rolls_back_and_leaves_no_partial_skills(tmp_path):
    """Simulates the process dying mid-transaction via the test-only --test-fail-step hook and
    proves the installer's own exit path (not a second manual `rollback` call) already leaves a
    clean, receipted ROLLED_BACK state — no dangling skill/hook/script directories."""
    target = tmp_path / "t4"
    target.mkdir()
    home = tmp_path / "home4"
    r = _install("claude", target, home, extra_args=["--test-fail-step", "claude_settings"])
    assert r.returncode == 4, r.stdout + r.stderr
    assert "ROLLED_BACK" in r.stdout

    for s in SKILLS:
        assert not (target / ".claude" / "skills" / s).exists()
    assert not (target / "hooks").exists()
    assert not (target / "scripts").exists()
    assert not (target / ".claude" / "settings.json").exists()

    ids = _receipt_ids(target)
    assert len(ids) == 1
    receipt = json.loads((target / ".simplicio-loop" / "receipts" / (ids[0] + ".json")).read_text())
    assert receipt["status"] == "ROLLED_BACK"


def test_second_rollback_of_the_same_transaction_is_a_harmless_noop(tmp_path):
    target = tmp_path / "t5"
    target.mkdir()
    home = tmp_path / "home5"
    r = _install("claude", target, home)
    assert r.returncode == 0, r.stdout + r.stderr
    transaction_id = _receipt_ids(target)[0]

    rb1 = _rollback(transaction_id, target, home)
    rb2 = _rollback(transaction_id, target, home)
    assert rb1.returncode == 0 and rb2.returncode == 0
    assert json.loads(rb1.stdout)["status"] == "ROLLED_BACK"
    assert json.loads(rb2.stdout)["status"] == "ROLLED_BACK"


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _selfrun import run_module
    run_module(globals(), "test_install_rollback")
