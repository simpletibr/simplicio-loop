"""Gap tests for simplicio_loop runtime_never_targets_the_real_repo guard (#1574)."""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _fake_runtime(directory: Path) -> Path:
    """Create a fake simplicio binary that just outputs '{}'."""
    directory.mkdir(parents=True, exist_ok=True)
    binary = directory / "simplicio"
    binary.write_text(f"#!{sys.executable}\nimport json\nprint(json.dumps({{}}))\n", encoding="utf-8")
    binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
    return binary


def test_c1_runtime_context_command_targeting_real_repo_is_refused(tmp_path, runtime_never_targets_the_real_repo):
    """A Runtime call with 'context' subcommand targeting the real repo is refused.
    
    The conftest fixture runtime_never_targets_the_real_repo checks if the runtime
    is spawned with a mapping subcommand (including 'context') that targets the real repo.
    
    Mutant: remove 'context' from MAPPING_SUBCOMMANDS in tests/conftest.py.
    """
    runtime = _fake_runtime(tmp_path / "bin")
    
    with pytest.raises(AssertionError, match="real repository"):
        subprocess.run([str(runtime), "context", "--task", "x"], cwd=str(ROOT), check=False)
    
    assert len(runtime_never_targets_the_real_repo) == 1
    runtime_never_targets_the_real_repo.clear()


def test_c2_runtime_with_repo_space_parameter_is_refused(tmp_path, runtime_never_targets_the_real_repo):
    """A Runtime call with --repo parameter (space-separated) targeting the real repo is refused.
    
    The guard's target_of function extracts the repo from both "--repo value" and "--repo=value" formats.
    This test verifies the space-separated format is handled.
    
    Mutant: In conftest, delete the branch that handles "--repo=" format.
    If only the "--repo" (space-separated) format extraction is present, this test still works.
    """
    runtime = _fake_runtime(tmp_path / "bin")
    
    with pytest.raises(AssertionError, match="real repository"):
        subprocess.run(
            [str(runtime), "map", "--repo", str(ROOT)],
            cwd=str(ROOT / "tests"),
            check=False
        )
    
    assert len(runtime_never_targets_the_real_repo) == 1
    runtime_never_targets_the_real_repo.clear()


def test_c2b_the_equals_form_of_repo_is_refused_even_when_the_cwd_is_elsewhere(
    tmp_path, runtime_never_targets_the_real_repo
):
    """`--repo=<checkout>` from a temp cwd: only the `--repo=` branch of `target_of` can see the target.

    Mutant: delete the `if item.startswith("--repo=")` branch in tests/conftest.py (the space-separated
    form test above passes without it because its cwd is already inside the checkout).
    """
    runtime = _fake_runtime(tmp_path / "bin")
    workdir = tmp_path / "elsewhere"
    workdir.mkdir()
    with pytest.raises(AssertionError, match="real repository"):
        subprocess.run([str(runtime), "map", f"--repo={ROOT}"], cwd=str(workdir), check=False)
    assert len(runtime_never_targets_the_real_repo) == 1
    runtime_never_targets_the_real_repo.clear()
