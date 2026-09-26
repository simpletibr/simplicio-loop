"""Unit tests for `scripts/install_executor.py` — the transactional executor half of #293
("separar planner e executor"). Exercises `apply()`/`rollback()` directly (in-process, not via
subprocess) so failure injection (`fail_step=`) can prove mid-transaction rollback without
needing to actually crash a child process.
"""
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # so the module's own `import install_lib` etc. resolve
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


sys.path.insert(0, str(SCRIPTS))
install_lib = _load("install_lib", "install_lib.py")
install_plan = _load("install_plan", "install_plan.py")
install_executor = _load("install_executor", "install_executor.py")

SKILLS = install_lib.SKILLS


def test_apply_creates_every_expected_file_and_writes_applied_receipt(tmp_path):
    target = tmp_path / "project"
    target.mkdir()
    receipt = install_executor.apply("claude", target=str(target), is_global=False)

    assert receipt["status"] == "APPLIED"
    for s in SKILLS:
        assert (target / ".claude" / "skills" / s).is_dir()
    assert (target / "hooks" / "loop_stop.py").is_file()
    assert (target / "scripts" / "install_lib.py").is_file()
    assert (target / ".claude" / "settings.json").is_file()

    receipt_path = target / ".simplicio-loop" / "receipts" / (receipt["transaction_id"] + ".json")
    assert receipt_path.is_file()
    on_disk = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert on_disk["status"] == "APPLIED"
    assert on_disk["steps"], "receipt must record every applied step"
    for step in on_disk["steps"]:
        assert step["hash_after"] is not None


def test_apply_is_idempotent_on_second_run(tmp_path):
    target = tmp_path / "project"
    target.mkdir()
    r1 = install_executor.apply("claude", target=str(target), is_global=False)
    r2 = install_executor.apply("claude", target=str(target), is_global=False)
    assert r1["status"] == r2["status"] == "APPLIED"
    for s in SKILLS:
        assert (target / ".claude" / "skills" / s).is_dir()


def test_blocked_plan_never_persists_a_transaction(tmp_path, monkeypatch):
    target = tmp_path / "project"
    target.mkdir()

    def _blocked_plan(*args, **kwargs):
        plan = install_plan.build_plan(*args, **kwargs)
        plan["status"] = "BLOCKED"
        plan["permissions_required"] = ["break_system_packages"]
        return plan

    monkeypatch.setattr(install_executor, "build_plan", _blocked_plan)
    receipt = install_executor.apply("claude", target=str(target), is_global=False)
    assert receipt["status"] == "BLOCKED"
    assert not (target / ".claude").exists(), "a BLOCKED plan must not mutate anything"
    assert not (target / ".simplicio-loop").exists(), "a BLOCKED plan must not persist a transaction"


def test_mid_transaction_failure_rolls_back_everything_already_applied(tmp_path):
    target = tmp_path / "project"
    target.mkdir()
    try:
        install_executor.apply("claude", target=str(target), is_global=False,
                              fail_step="claude_settings")
        assert False, "expected InstallTransactionError"
    except install_executor.InstallTransactionError as e:
        receipt = e.receipt
    assert receipt["status"] == "ROLLED_BACK"

    # Every path the earlier steps (skills/hooks/scripts) created must be gone — no leftover
    # skill trees, no leftover hooks/scripts dirs. Only the receipt (and any now-empty parent
    # dirs os.makedirs created along the way) may remain.
    for s in SKILLS:
        assert not (target / ".claude" / "skills" / s).exists()
    assert not (target / "hooks").exists()
    assert not (target / "scripts").exists()
    assert not (target / ".claude" / "settings.json").exists()

    on_disk = json.loads(
        (target / ".simplicio-loop" / "receipts" / (receipt["transaction_id"] + ".json"))
        .read_text(encoding="utf-8"))
    assert on_disk["status"] == "ROLLED_BACK"
    assert "error" in on_disk


def test_rollback_of_a_pre_existing_path_restores_it_byte_for_byte(tmp_path):
    target = tmp_path / "project"
    target.mkdir()
    existing_skill = target / ".claude" / "skills" / "simplicio-loop"
    existing_skill.mkdir(parents=True)
    marker = existing_skill / "PRE_EXISTING_MARKER.md"
    marker.write_text("this file predates the install and must survive rollback", encoding="utf-8")

    receipt = install_executor.apply("claude", target=str(target), is_global=False)
    assert receipt["status"] == "APPLIED"
    assert (existing_skill / "SKILL.md").is_file(), "install should have copied into the existing dir"

    rolled_back = install_executor.rollback(receipt["transaction_id"], str(target))
    assert rolled_back["status"] == "ROLLED_BACK"

    # The pre-existing skill directory is restored to EXACTLY what it was before — the marker
    # survives, and the newly-copied SKILL.md is gone again.
    assert marker.is_file()
    assert marker.read_text(encoding="utf-8") == \
        "this file predates the install and must survive rollback"
    assert not (existing_skill / "SKILL.md").exists()

    # Freshly-created effects (hooks/scripts dirs, settings.json, the other 5 skill dirs that
    # did NOT pre-exist) must be removed entirely.
    assert not (target / "hooks").exists()
    assert not (target / "scripts").exists()
    assert not (target / ".claude" / "settings.json").exists()
    for s in SKILLS:
        if s == "simplicio-loop":
            continue
        assert not (target / ".claude" / "skills" / s).exists()


def test_rollback_is_idempotent(tmp_path):
    target = tmp_path / "project"
    target.mkdir()
    receipt = install_executor.apply("claude", target=str(target), is_global=False)
    first = install_executor.rollback(receipt["transaction_id"], str(target))
    second = install_executor.rollback(receipt["transaction_id"], str(target))
    assert first["status"] == second["status"] == "ROLLED_BACK"


def test_rollback_of_unknown_transaction_raises(tmp_path):
    import pytest
    target = tmp_path / "project"
    target.mkdir()
    with pytest.raises(FileNotFoundError):
        install_executor.rollback("install-does-not-exist", str(target))


def test_cli_transactional_install_and_rollback_round_trip(tmp_path):
    import subprocess

    target = tmp_path / "project"
    target.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    env = dict(__import__("os").environ)
    env["HOME"] = str(home)

    r = subprocess.run(
        [sys.executable, str(SCRIPTS / "install_lib.py"), "claude", "--target", str(target),
         "--skip-operators", "--minimal", "--transactional"],
        capture_output=True, text=True, timeout=60, env=env, stdin=subprocess.DEVNULL,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert (target / ".claude" / "skills" / "simplicio-loop").is_dir()

    receipts_dir = target / ".simplicio-loop" / "receipts"
    transaction_id = next(receipts_dir.glob("*.json")).stem

    r2 = subprocess.run(
        [sys.executable, str(SCRIPTS / "install_lib.py"), "rollback", transaction_id,
         "--target", str(target)],
        capture_output=True, text=True, timeout=60, env=env, stdin=subprocess.DEVNULL,
    )
    assert r2.returncode == 0, r2.stdout + r2.stderr
    assert not (target / ".claude" / "skills" / "simplicio-loop").exists()
    assert not (target / "hooks").exists()


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _selfrun import run_module
    run_module(globals(), "test_install_transaction")
