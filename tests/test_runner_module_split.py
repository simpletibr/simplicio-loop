"""Guards for the runner split (#1818): every runner module stays within the line limit, and every
module-level name recorded on main is still importable from its original module path."""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = REPO_ROOT / "simplicio_loop"
GOLDEN = REPO_ROOT / "tests" / "golden" / "runner_public_names.txt"
LINE_LIMIT = 1000


def _runner_module_paths() -> list[Path]:
    return sorted(PACKAGE_DIR.glob("runner*.py"))


@pytest.mark.parametrize("path", _runner_module_paths(), ids=lambda p: p.name)
def test_runner_module_is_within_line_limit(path: Path) -> None:
    lines = len(path.read_text(encoding="utf-8").splitlines())
    assert lines <= LINE_LIMIT, f"{path.name} has {lines} lines; the limit is {LINE_LIMIT}"


def test_every_recorded_runner_name_is_still_importable() -> None:
    entries = [line for line in GOLDEN.read_text(encoding="utf-8").splitlines() if line.strip()]
    missing = []
    for entry in entries:
        module_name, _, attr = entry.rpartition(".")
        module = importlib.import_module(module_name)
        if not hasattr(module, attr):
            missing.append(entry)
    assert not missing, f"{len(missing)} recorded runner names are no longer bound: {missing[:20]}"
