"""Tests for #98 — `hooks/pre-commit.py` auto-syncing BOTH `plugin/` and
`simplicio_loop/_bundle/` on a staged source change, fail-open on sync failure, and sourcing its
watched-path list from `scripts/mirror_manifest.py` (zero duplication, #74).

These build a throwaway fixture repo (a REAL `git init`, not a mock) with real copies of
`hooks/pre-commit.py`, `scripts/mirror_manifest.py`, `scripts/sync_plugin.py`, and
`scripts/sync_bundle.py` from this repo, so the hook under test runs its actual logic — not a
stand-in — against a small, fast, disposable source tree.
"""
import os
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import mirror_manifest  # noqa: E402


def _write(path, content=""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _git(args, cwd):
    return subprocess.run(
        ["git"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=20,
        stdin=subprocess.DEVNULL,
    )


def _build_fixture_repo(root):
    """A minimal but real git repo with the pieces pre-commit.py needs: itself, the two
    syncers, mirror_manifest.py, and a tiny watched source tree."""
    # the hook + its real syncers + the single source of truth, copied verbatim from this repo
    os.makedirs(os.path.join(root, "hooks"), exist_ok=True)
    os.makedirs(os.path.join(root, "scripts"), exist_ok=True)
    shutil.copy2(os.path.join(REPO, "hooks", "pre-commit.py"),
                 os.path.join(root, "hooks", "pre-commit.py"))
    for name in ("mirror_manifest.py", "sync_plugin.py", "sync_bundle.py"):
        shutil.copy2(os.path.join(REPO, "scripts", name), os.path.join(root, "scripts", name))
    # a tiny watched source tree — one skill file is enough to exercise the full mirror
    _write(os.path.join(root, ".claude", "skills", "demo-skill", "SKILL.md"), "---\n---\nv1\n")
    _write(os.path.join(root, "hooks", "loop_stop.py"), "# stub\n")
    _write(os.path.join(root, "tests", "_selfrun.py"), "# stub\n")

    _git(["init", "-q"], root)
    _git(["config", "user.email", "test@example.com"], root)
    _git(["config", "user.name", "test"], root)
    _git(["add", "-A"], root)
    _git(["commit", "-q", "-m", "initial"], root)


def test_watched_source_dirs_is_the_single_source_of_truth(tmp_path=None):
    # #98 AC: mirror_manifest.py is the ONLY place the watched-path list lives — pre-commit.py
    # must import it, not hard-code its own copy.
    with open(os.path.join(REPO, "hooks", "pre-commit.py"), encoding="utf-8") as f:
        src = f.read()
    assert "from mirror_manifest import WATCHED_SOURCE_DIRS" in src, (
        "pre-commit.py must import WATCHED_SOURCE_DIRS from mirror_manifest.py, not "
        "hand-duplicate the watched path list")
    assert mirror_manifest.WATCHED_SOURCE_DIRS, "WATCHED_SOURCE_DIRS must be non-empty"


def test_sync_bundle_check_verb_runs_without_crashing():
    # System-level packaging invariant (mirrors test_sync_plugin_check_verb_runs_without_crashing
    # in test_system_check.py, but for the new _bundle/ syncer): --check must run to completion
    # and report drift as data, never a traceback.
    r = subprocess.run(
        [sys.executable, os.path.join(REPO, "scripts", "sync_bundle.py"), "--check"],
        capture_output=True,
        text=True,
        cwd=REPO,
        timeout=60,
        stdin=subprocess.DEVNULL,
    )
    assert "Traceback (most recent call last)" not in r.stderr, r.stderr
    assert r.returncode in (0, 1)
    assert "bundle sync:" in r.stdout


def test_precommit_hook_syncs_both_mirrors_and_stages_only_the_committed_one(tmp_path):
    root = str(tmp_path / "fixture_repo")
    _build_fixture_repo(root)

    # stage a real change under the watched .claude/skills tree
    _write(os.path.join(root, ".claude", "skills", "demo-skill", "SKILL.md"), "---\n---\nv2\n")
    _git(["add", "-A"], root)

    r = subprocess.run(
        [sys.executable, os.path.join(root, "hooks", "pre-commit.py")],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=60,
        stdin=subprocess.DEVNULL,
    )
    assert r.returncode == 0, "pre-commit hook must always exit 0 (fail-open):\n%s%s" % (
        r.stdout, r.stderr)

    plugin_skill = os.path.join(root, "plugin", "skills", "demo-skill", "SKILL.md")
    bundle_skill = os.path.join(root, "simplicio_loop", "_bundle", "skills", "demo-skill", "SKILL.md")
    assert os.path.exists(plugin_skill), "plugin/ mirror was not regenerated"
    assert os.path.exists(bundle_skill), "simplicio_loop/_bundle/ mirror was not regenerated (#98)"
    with open(plugin_skill, encoding="utf-8") as f:
        assert f.read() == "---\n---\nv2\n"
    with open(bundle_skill, encoding="utf-8") as f:
        assert f.read() == "---\n---\nv2\n"

    # the committed plugin/ mirror must be staged into the SAME commit, not left as untracked noise
    staged = _git(["diff", "--cached", "--name-only"], root).stdout
    assert "plugin/skills/demo-skill/SKILL.md" in staged
    # simplicio_loop/_bundle/ is gitignored since #1817: it is regenerated on disk but never staged
    assert "simplicio_loop/_bundle/" not in staged


def test_precommit_hook_ignores_unwatched_paths(tmp_path):
    # A staged change OUTSIDE every watched dir must not trigger a sync (or fail if it did) —
    # cheap confirmation the detector isn't just "always sync".
    root = str(tmp_path / "fixture_repo")
    _build_fixture_repo(root)
    _write(os.path.join(root, "README.md"), "unrelated change\n")
    _git(["add", "-A"], root)

    r = subprocess.run(
        [sys.executable, os.path.join(root, "hooks", "pre-commit.py")],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=60,
        stdin=subprocess.DEVNULL,
    )
    assert r.returncode == 0
    assert not os.path.exists(os.path.join(root, "plugin")), (
        "a change outside the watched dirs must not trigger a mirror sync")


def test_precommit_hook_fails_open_when_a_syncer_errors(tmp_path):
    # #98 AC: sync failure (e.g. python3/script unavailable or erroring) must NOT block the
    # commit — the hook exits 0 regardless, logging a warning; claims_audit/check.py remain the
    # backstop that catches the resulting drift later.
    root = str(tmp_path / "fixture_repo")
    _build_fixture_repo(root)
    # break sync_bundle.py so it errors instead of syncing
    _write(os.path.join(root, "scripts", "sync_bundle.py"), "import sys\nsys.exit(1)\n")

    _write(os.path.join(root, ".claude", "skills", "demo-skill", "SKILL.md"), "---\n---\nv3\n")
    _git(["add", "-A"], root)

    r = subprocess.run(
        [sys.executable, os.path.join(root, "hooks", "pre-commit.py")],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=60,
        stdin=subprocess.DEVNULL,
    )
    assert r.returncode == 0, "a broken syncer must still fail OPEN (exit 0):\n%s%s" % (
        r.stdout, r.stderr)
    # sync_plugin.py (the one NOT broken) must still have run and staged its output
    plugin_skill = os.path.join(root, "plugin", "skills", "demo-skill", "SKILL.md")
    assert os.path.exists(plugin_skill), (
        "a failure in one syncer must not skip the other (per-script fail-open)")


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _selfrun import run_module
    run_module(globals(), "test_precommit_bundle_sync")
