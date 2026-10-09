"""A test must never run the Simplicio Runtime against this checkout (#1574).

The Runtime writes its baseline map and a full-tree `baseline-build-*` scratch into
`<git-common-dir>/simplicio/map`, shared by EVERY worktree of the repository. Squads run these tests
in many worktrees at once; a Runtime call that is cut short by a timeout leaves the scratch and lock
behind (102 directories, 6.8 GB measured). The conftest guard makes that spawn impossible; the
PLANES installed e2e runs against a throwaway repository instead of ROOT.
"""

from __future__ import annotations

import inspect
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "planes_installed_e2e.py"


def _fake_runtime(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    binary = directory / "simplicio"
    binary.write_text(f"#!{sys.executable}\nprint('{{}}')\n", encoding="utf-8")
    binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
    return binary


def test_spawning_the_runtime_with_this_checkout_as_repo_is_refused(tmp_path, runtime_never_targets_the_real_repo):
    runtime = _fake_runtime(tmp_path / "bin")
    with pytest.raises(AssertionError, match="real repository"):
        subprocess.run([str(runtime), "runtime", "map", "--repo", str(ROOT), "--json"], check=False)
    assert len(runtime_never_targets_the_real_repo) == 1
    runtime_never_targets_the_real_repo.clear()


def test_spawning_the_runtime_from_inside_this_checkout_is_refused(tmp_path, runtime_never_targets_the_real_repo):
    runtime = _fake_runtime(tmp_path / "bin")
    with pytest.raises(AssertionError, match="real repository"):
        subprocess.run([str(runtime), "map"], cwd=str(ROOT / "tests"), check=False)
    runtime_never_targets_the_real_repo.clear()


def test_a_worktree_sibling_of_this_checkout_is_protected_through_the_shared_common_dir(tmp_path):
    from tests.conftest import _protected_checkout_roots  # noqa: PLC0415

    roots = _protected_checkout_roots()
    assert os.path.realpath(str(ROOT)) in roots


def test_runtime_subcommands_that_never_map_are_not_policed(tmp_path):
    """The action gate runs `simplicio hbp append` with the checkout as cwd on every blocked edit."""
    runtime = _fake_runtime(tmp_path / "bin")
    result = subprocess.run([str(runtime), "hbp", "append", "--topic", "x"], cwd=str(ROOT), capture_output=True, text=True)
    assert result.returncode == 0


def test_a_temporary_repository_is_fine(tmp_path):
    runtime = _fake_runtime(tmp_path / "bin")
    repo = tmp_path / "repo"
    repo.mkdir()
    result = subprocess.run([str(runtime), "map", "--repo", str(repo)], capture_output=True, text=True)
    assert result.returncode == 0


def test_other_binaries_are_not_policed_by_this_guard():
    result = subprocess.run([sys.executable, "-c", "print(1)"], cwd=str(ROOT), capture_output=True, text=True)
    assert result.stdout.strip() == "1"


def test_the_planes_e2e_script_takes_the_repository_to_map_as_an_argument():
    source = SCRIPT.read_text(encoding="utf-8")
    assert '"--repo"' in source
    assert '"--repo", str(ROOT)' not in source
    assert 'str(ROOT), "--task-file"' not in source, "orient/handoff must not target ROOT"


def test_planes_e2e_never_writes_into_the_checkout(tmp_path):
    """Run the script's hops against a throwaway repository: nothing may appear under ROOT/.git/simplicio."""
    import shutil

    if not all(shutil.which(name) for name in ("simplicio-mapper", "simplicio-dev-cli", "simplicio-loop", "simplicio")):
        pytest.skip("EXTERNAL_INTEGRATION_UNAVAILABLE[installed_e2e]: installed toolchain missing")
    repo = tmp_path / "repo"
    repo.mkdir()
    for command in (["init", "-q"], ["config", "user.email", "t@example.com"], ["config", "user.name", "t"]):
        subprocess.run(["git", *command], cwd=repo, check=True)
    (repo / "app.py").write_text("def app():\n    return 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=repo, check=True)
    before = _simplicio_state(ROOT)
    # The first hops already fail when the installed toolchain is stale; what matters is the target.
    subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(repo), "--json"], cwd=tmp_path,
        capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=180,
    )
    assert _simplicio_state(ROOT) == before


def _simplicio_state(root: Path) -> set[str]:
    common = Path(subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=root,
        capture_output=True, text=True, check=True,
    ).stdout.strip()) / "simplicio" / "map"
    return {entry.name for entry in common.iterdir()} if common.is_dir() else set()


def test_a_relative_argument_is_resolved_against_the_childs_cwd_not_pytests(tmp_path):
    """`--task "see docs/x.md"` with cwd in a temp repo is fine even though pytest runs inside ROOT."""
    runtime = _fake_runtime(tmp_path / "bin")
    repo = tmp_path / "repo"
    repo.mkdir()
    result = subprocess.run(
        [str(runtime), "plan", "--task", "see docs/x.md", "--repo", "."], cwd=str(repo), capture_output=True, text=True,
    )
    assert result.returncode == 0


def test_a_relative_repo_that_resolves_into_this_checkout_is_still_refused(tmp_path, runtime_never_targets_the_real_repo):
    runtime = _fake_runtime(tmp_path / "bin")
    with pytest.raises(AssertionError, match="real repository"):
        subprocess.run([str(runtime), "map", "--repo", "tests"], cwd=str(ROOT), check=False)
    runtime_never_targets_the_real_repo.clear()


def test_the_guard_keeps_the_signature_of_the_popen_it_wraps(runtime_never_targets_the_real_repo):
    """``core_network_guard`` binds a positional ``Popen(args, bufsize, executable, ...)`` call against the
    signature of the class it wraps. A guard that shows ``(args, *a, **kw)`` hides ``executable``, so a
    positional ``-S`` interpreter child slipped past the core gate (test_check_reason_summary_unit)."""
    guarded = subprocess.Popen
    wrapped = guarded.__mro__[1]
    assert guarded is not wrapped
    assert inspect.signature(guarded) == inspect.signature(wrapped)
    assert inspect.signature(guarded.__init__) == inspect.signature(wrapped.__init__)
