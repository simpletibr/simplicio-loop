"""#1817: simplicio_loop/_bundle/ is a build-time artifact, not committed duplication.

The bundle is generated from the canonical sources (scripts/sync_bundle.py) by the wheel build
(setup.py build_py) and by the source-tree materialisation below. It must never be tracked in git,
and the wheel must still ship it.
"""
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BUNDLE_PREFIX = "simplicio_loop/_bundle/"
REQUIRED_IN_WHEEL = (
    "simplicio_loop/_bundle/skills/simplicio-loop/SKILL.md",
    "simplicio_loop/_bundle/hooks/loop_stop.py",
    "simplicio_loop/_bundle/scripts/loop_journal.py",
    "simplicio_loop/_bundle/host-rules/simplicio-loop-operator-flow.md",
)


def _git(*args):
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True)


def _is_git_checkout():
    return shutil.which("git") is not None and _git("rev-parse", "--git-dir").returncode == 0


def test_bundle_is_not_tracked_in_git():
    if not _is_git_checkout():
        pytest.skip("no git checkout here: the tracking rule cannot be checked from a source archive")
    tracked = _git("ls-files", "--", "simplicio_loop/_bundle").stdout.split()
    assert tracked == [], f"{len(tracked)} _bundle files are still committed, e.g. {tracked[:3]}"


def test_bundle_is_gitignored():
    if not _is_git_checkout():
        pytest.skip("no git checkout here: gitignore cannot be checked from a source archive")
    probe = BUNDLE_PREFIX + "hooks/loop_stop.py"
    assert _git("check-ignore", "-q", probe).returncode == 0, f"{probe} must be gitignored"


def _checkout_without_bundle(dest):
    """A copy of the source tree that lacks simplicio_loop/_bundle, as a fresh clone does, so the build
    must generate the bundle itself (the working tree's copy, once materialised, would hide a missing step)."""
    skipped = {".git", "build", "dist", ".venv", "__pycache__"}
    bundle_parent = ROOT / "simplicio_loop"

    def ignore(directory, names):
        out = {n for n in names if n in skipped or n.endswith(".egg-info")}
        if Path(directory).resolve() == bundle_parent:
            out.add("_bundle")
        return out

    shutil.copytree(ROOT, dest, ignore=ignore)
    return dest


def test_built_wheel_contains_the_generated_bundle(tmp_path):
    try:
        import build  # noqa: F401
    except ImportError:
        pytest.skip("`build` is not importable, so the wheel cannot be built here")
    checkout = _checkout_without_bundle(tmp_path / "checkout")
    assert not (checkout / "simplicio_loop" / "_bundle").exists()
    out = tmp_path / "dist"
    subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(out), str(checkout)],
        check=True, capture_output=True, text=True, timeout=900,
    )
    wheel = next(out.glob("simplicio_loop-*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
    missing = [n for n in REQUIRED_IN_WHEEL if n not in names]
    assert not missing, f"wheel is missing generated bundle files: {missing}"
    bundle = [n for n in names if n.startswith(BUNDLE_PREFIX)]
    assert len(bundle) > 100, f"only {len(bundle)} bundle files in the wheel"
