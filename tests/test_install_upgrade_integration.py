"""#293 §4: manifest/version reconciliation + a real N-1 -> N upgrade test.

`scripts/install_executor.py` now persists `.simplicio-loop/manifest.json`
(`simplicio.install-manifest/v1`) on every successful `apply()`, recording the resolved
version and the exact skill set that transaction installed. A SUBSEQUENT `apply()` diffs the
skill set it is about to install against the skill set the PRIOR manifest recorded, and removes
(as a tracked, rollback-eligible step) any skill directory that existed under the old release but
is no longer part of the current declared set — the "eliminar extras inexistentes" / "testar
upgrade N-1 -> N" requirement.

These tests exercise `install_executor.apply()` directly (in-process), simulating an N-1 release
by manually seeding a target with a manifest + an extra "leftover" skill directory that predates
the current release's skill list, then upgrading to N (the real, current `install_lib.SKILLS`)
and asserting: the leftover is gone, the manifest reflects the new version/skill set, and a
rollback of the upgrade transaction restores the leftover exactly as it was.
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
    sys.modules[name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


sys.path.insert(0, str(SCRIPTS))
install_lib = _load("install_lib", "install_lib.py")
install_plan = _load("install_plan", "install_plan.py")
install_executor = _load("install_executor", "install_executor.py")

CURRENT_SKILLS = install_lib.SKILLS
STALE_SKILL_NAME = "simplicio-legacy-extra"


def _seed_n_minus_1(target):
    """Simulate a target that already went through an N-1 install: a manifest naming an OLDER
    version + an OLDER skill set that includes one skill the CURRENT release no longer declares,
    plus that skill's directory actually present on disk (as a real N-1 install would have left
    it) with a marker file inside so we can prove its content, not just its presence."""
    manifest_dir = target / ".simplicio-loop"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    old_skills = list(CURRENT_SKILLS) + [STALE_SKILL_NAME]
    (manifest_dir / "manifest.json").write_text(json.dumps({
        "schema": "simplicio.install-manifest/v1",
        "version": "0.0.1-old",
        "skills": old_skills,
        "runtime": "claude",
        "updated_at": "2020-01-01T00:00:00Z",
    }), encoding="utf-8")
    stale_dir = target / ".claude" / "skills" / STALE_SKILL_NAME
    stale_dir.mkdir(parents=True, exist_ok=True)
    (stale_dir / "SKILL.md").write_text("# stale N-1 skill, must not survive upgrade to N\n",
                                        encoding="utf-8")
    return old_skills


def test_stale_skills_helper_diffs_against_prior_manifest(tmp_path):
    target = tmp_path / "project"
    target.mkdir()
    _seed_n_minus_1(target)
    stale = install_executor._stale_skills(str(target), CURRENT_SKILLS)
    assert stale == [STALE_SKILL_NAME]


def test_apply_reconciles_stale_skill_and_writes_new_manifest(tmp_path):
    target = tmp_path / "project"
    target.mkdir()
    _seed_n_minus_1(target)
    stale_dir = target / ".claude" / "skills" / STALE_SKILL_NAME
    assert stale_dir.is_dir(), "fixture sanity: stale N-1 skill must exist before upgrade"

    receipt = install_executor.apply("claude", target=str(target), is_global=False)

    assert receipt["status"] == "APPLIED"
    assert receipt["reconciled_stale_skills"] == [STALE_SKILL_NAME]
    assert receipt["previous_version"] == "0.0.1-old"
    assert receipt["resolved_version"], "resolved (new) version must be recorded"

    assert not stale_dir.exists(), "N-1 leftover skill must not survive the upgrade to N"
    for s in CURRENT_SKILLS:
        assert (target / ".claude" / "skills" / s / "SKILL.md").is_file(), \
            "%s must still be installed after upgrade" % s

    manifest = json.loads((target / ".simplicio-loop" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema"] == "simplicio.install-manifest/v1"
    assert manifest["previous_version"] == "0.0.1-old"
    assert manifest["version"] == receipt["resolved_version"]
    assert sorted(manifest["skills"]) == sorted(CURRENT_SKILLS)
    assert STALE_SKILL_NAME not in manifest["skills"]
    assert manifest["reconciled_stale_skills"] == [STALE_SKILL_NAME]


def test_reinstalling_n_again_is_idempotent_no_further_reconciliation(tmp_path):
    target = tmp_path / "project"
    target.mkdir()
    _seed_n_minus_1(target)
    install_executor.apply("claude", target=str(target), is_global=False)

    # Re-running the SAME (current) install again must not try to reconcile anything further —
    # the manifest already only names the current skill set.
    receipt2 = install_executor.apply("claude", target=str(target), is_global=False)
    assert receipt2["status"] == "APPLIED"
    assert receipt2["reconciled_stale_skills"] == []
    assert receipt2["previous_version"] == receipt2["resolved_version"]
    for s in CURRENT_SKILLS:
        assert (target / ".claude" / "skills" / s / "SKILL.md").is_file()


def test_rollback_of_upgrade_transaction_restores_stale_skill_and_prior_manifest(tmp_path):
    target = tmp_path / "project"
    target.mkdir()
    _seed_n_minus_1(target)
    stale_dir = target / ".claude" / "skills" / STALE_SKILL_NAME

    receipt = install_executor.apply("claude", target=str(target), is_global=False)
    assert not stale_dir.exists()

    rolled_back = install_executor.rollback(receipt["transaction_id"], str(target))
    assert rolled_back["status"] == "ROLLED_BACK"

    assert stale_dir.is_dir(), "rollback of the upgrade must restore the N-1 leftover skill"
    assert (stale_dir / "SKILL.md").read_text(encoding="utf-8").startswith("# stale N-1 skill")

    manifest = json.loads((target / ".simplicio-loop" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == "0.0.1-old", \
        "rollback must restore the PRIOR manifest, not leave the new version recorded"
    assert STALE_SKILL_NAME in manifest["skills"]


if __name__ == "__main__":
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _selfrun import run_module
    run_module(globals(), "test_install_upgrade")
