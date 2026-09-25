"""verify must work in any target repository, not only in simplicio-loop itself."""
from __future__ import annotations

from pathlib import Path

from simplicio_loop import runner


def test_watcher_script_comes_from_the_loop_package_not_the_target_repo(tmp_path):
    script = runner._watcher_script()
    assert script.is_file()
    assert script.name == "watcher_verify.py"
    assert tmp_path not in script.parents
    assert Path(runner.__file__).resolve().parent in script.resolve().parents or \
        Path(runner.__file__).resolve().parent.parent in script.resolve().parents
