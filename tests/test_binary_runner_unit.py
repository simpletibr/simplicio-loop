"""The two repairs of packaging/binary/pyinstaller_run.py, run with fakes (no PyInstaller needed)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

RUNNER = Path(__file__).resolve().parents[1] / "packaging" / "binary" / "pyinstaller_run.py"
spec = importlib.util.spec_from_file_location("pyinstaller_run", RUNNER)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def test_base_library_zip_entries_are_written_sorted_by_name():
    seen = []
    create = runner.sorted_base_library_zip(lambda filename, toc, cache=None: seen.append((filename, toc, cache)))
    create("base.zip", [("os", "/a", "PYMODULE"), ("abc", "/b", "PYMODULE"), ("codecs", "/c", "PYMODULE")], {"k": 1})
    assert seen == [("base.zip", [("abc", "/b", "PYMODULE"), ("codecs", "/c", "PYMODULE"), ("os", "/a", "PYMODULE")],
                     {"k": 1})]


def test_the_install_records_of_a_distribution_stay_out_of_the_bundle():
    files = {("/site/x-1.dist-info/" + name, "x-1.dist-info") for name in (
        "METADATA", "entry_points.txt", "WHEEL", "top_level.txt", "RECORD", "INSTALLER", "direct_url.json",
        "REQUESTED", "uv_cache.json")}
    wrapped = runner.without_install_records(lambda self: files)
    kept = sorted(Path(source).name for source, target in wrapped(object()))
    assert kept == ["METADATA", "WHEEL", "entry_points.txt", "top_level.txt"]
