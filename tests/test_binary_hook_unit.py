"""The PyInstaller hook of the standalone binary, run with a fake PyInstaller (issue #1576)."""
from __future__ import annotations

import runpy
import sys
import types
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[1] / "packaging" / "binary" / "hooks" / "hook-simplicio_loop.py"


def _tree(base: Path) -> None:
    files = {
        "simplicio_loop/__init__.py": "", "simplicio_loop/cli.py": "", "simplicio_loop/dashboard/__init__.py": "",
        "simplicio_loop/dashboard/server.py": "", "simplicio_loop/dashboard/static/app.js": "",
        "simplicio_loop/_bundle/hooks/guard.py": "",          # no __init__.py in _bundle: data
        "simplicio_loop/loose/script.py": "",                 # no __init__.py in loose: data
        "simplicio_loop/dashboard/helper/part.py": "",        # dashboard is a package, helper is not: data
        "simplicio_mapper/__init__.py": "", "simplicio_mapper/contracts/a.json": "{}",
        "simplicio/__init__.py": "", "simplicio/templates/app.py": "",
    }
    for name, text in files.items():
        (base / name).parent.mkdir(parents=True, exist_ok=True)
        (base / name).write_text(text)


@pytest.fixture
def hook(tmp_path, monkeypatch):
    _tree(tmp_path)
    metadata = tmp_path / "dist-info"
    metadata.mkdir()
    for name in ("METADATA", "entry_points.txt", "top_level.txt", "WHEEL", "RECORD", "INSTALLER",
                 "direct_url.json", "uv_cache.json"):
        (metadata / name).write_text("x")

    def collect_data_files(package, include_py_files=False):
        assert include_py_files is True
        root = tmp_path / package
        return [(str(path), str(Path(package) / path.relative_to(root).parent))
                for path in sorted(root.rglob("*")) if path.is_file()]

    fake = types.ModuleType("PyInstaller.utils.hooks")
    fake.collect_data_files = collect_data_files
    fake.collect_submodules = lambda package: [package, package + ".sub"]
    fake.copy_metadata = lambda name: [(str(path), "dist-info") for path in sorted(metadata.iterdir())]
    fake.get_package_paths = lambda package: (str(tmp_path), str(tmp_path / package))
    for name in ("PyInstaller", "PyInstaller.utils"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    monkeypatch.setitem(sys.modules, "PyInstaller.utils.hooks", fake)
    return runpy.run_path(str(HOOK)), tmp_path


def test_every_submodule_of_the_three_packages_is_asked_for_not_listed_by_hand(hook):
    namespace, _ = hook
    assert namespace["hiddenimports"] == [
        "simplicio_loop", "simplicio_loop.sub", "simplicio_mapper", "simplicio_mapper.sub",
        "simplicio", "simplicio.sub"]


def test_only_the_metadata_the_program_reads_is_bundled(hook):
    namespace, _ = hook
    kept = sorted(Path(source).name for source, target in namespace["datas"] if target == "dist-info")
    assert kept == ["METADATA", "WHEEL", "entry_points.txt", "top_level.txt"]  # no path of the builder


def test_python_files_that_are_data_ship_as_files_and_modules_do_not(hook):
    namespace, base = hook
    shipped = sorted(str(Path(source).relative_to(base)) for source, target in namespace["datas"] if target != "dist-info")
    assert shipped == [
        "simplicio/templates/app.py", "simplicio_loop/_bundle/hooks/guard.py", "simplicio_loop/dashboard/helper/part.py",
        "simplicio_loop/dashboard/static/app.js", "simplicio_loop/loose/script.py", "simplicio_mapper/contracts/a.json"]


def test_the_sysconfig_data_of_the_build_python_is_left_out(hook):
    namespace, _ = hook
    import sysconfig
    assert namespace["excludedimports"] == [sysconfig._get_sysconfigdata_name()]
