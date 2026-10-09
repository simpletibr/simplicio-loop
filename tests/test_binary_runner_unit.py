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


def _dist_info(root: Path) -> Path:
    info = root / "x-1.0.dist-info"
    (info / "licenses").mkdir(parents=True)
    for name in ("METADATA", "entry_points.txt", "WHEEL", "top_level.txt", "RECORD", "INSTALLER", "direct_url.json",
                 "REQUESTED", "uv_cache.json", "future-record.json"):
        (info / name).write_text("x")
    (info / "licenses" / "LICENSE").write_text("MIT")
    return info


def test_the_metadata_of_a_distribution_keeps_what_the_program_reads_and_the_licenses(tmp_path):
    """PyInstaller returns the whole dist-info directory as one entry. RECORD and direct_url.json hold the
    path of the machine that built the executable, so the runner lists the wanted files one by one."""
    info = _dist_info(tmp_path)
    egg = tmp_path / "old.egg-info"
    egg.write_text("an egg file is not a directory")
    wrapped = runner.trimmed_copy_metadata(lambda name, recursive=False: [(str(info), info.name), (str(egg), egg.name)])

    entries = wrapped("x")

    assert sorted((Path(source).relative_to(tmp_path).as_posix(), target) for source, target in entries) == [
        ("old.egg-info", "old.egg-info"),
        ("x-1.0.dist-info/METADATA", "x-1.0.dist-info"),
        ("x-1.0.dist-info/WHEEL", "x-1.0.dist-info"),
        ("x-1.0.dist-info/entry_points.txt", "x-1.0.dist-info"),
        ("x-1.0.dist-info/licenses/LICENSE", "x-1.0.dist-info/licenses"),
        ("x-1.0.dist-info/top_level.txt", "x-1.0.dist-info"),
    ]


def test_the_wrapper_passes_the_recursive_flag_on(tmp_path):
    seen = []
    wrapped = runner.trimmed_copy_metadata(lambda name, recursive=False: seen.append((name, recursive)) or [])
    wrapped("pkg", recursive=True)
    wrapped("other")
    assert seen == [("pkg", True), ("other", False)]
