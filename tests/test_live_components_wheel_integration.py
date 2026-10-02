"""Integration: the Simplicio Live kit and its catalog ship inside the wheel (issue #1399)."""
from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

from simplicio_loop.dashboard import STATIC_DIR

ROOT = Path(__file__).resolve().parents[1]


def test_wheel_ships_every_static_dashboard_file(tmp_path):
    subprocess.run(
        [sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation", "-q", "-w", str(tmp_path), str(ROOT)],
        check=True, capture_output=True, text=True,
    )
    wheel = next(tmp_path.glob("simplicio_loop-*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
    expected = {
        "simplicio_loop/dashboard/" + p.relative_to(STATIC_DIR.parent).as_posix()
        for p in STATIC_DIR.rglob("*") if p.is_file()
    }
    assert "simplicio_loop/dashboard/static/components/index.js" in expected
    assert "simplicio_loop/dashboard/static/components.html" in expected
    assert "simplicio_loop/dashboard/static/components/fonts/atkinson-hyperlegible-next-450-750.woff2" in expected
    assert "simplicio_loop/dashboard/phase_meta.py" in names
    missing = sorted(expected - names)
    assert not missing, missing
