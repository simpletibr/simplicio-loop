"""Monorepo contract: mapper + dev-cli ship inside the ONE simplicio-loop wheel."""
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOTS = {
    "simplicio_loop": ROOT,
    "simplicio_mapper": ROOT / "packages" / "mapper",
    "simplicio": ROOT / "packages" / "dev-cli",
}
STANDALONE_LOOKUP = re.compile(
    r"""(?<![A-Za-z0-9_])_?(?:metadata\.)?(?:distribution_)?(?:version|distribution|requires)"""
    r"""\(\s*["']simplicio-(?:mapper|cli)["']"""
)
OPERATOR_SCRIPTS = ("simplicio-loop", "simplicio-mapper", "simplicio-dev-cli", "simplicio-cli", "simplicio-py")
JUNK = {".DS_Store", "README.md"}  # not runtime data


def test_no_source_resolves_the_retired_standalone_distributions():
    offenders = []
    for base in (ROOT / "simplicio_loop", ROOT / "packages/mapper/simplicio_mapper",
                 ROOT / "packages/dev-cli/simplicio", ROOT / "scripts", ROOT / "hooks"):
        for path in base.rglob("*.py"):
            if "_bundle" in path.parts:
                continue
            for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if STANDALONE_LOOKUP.search(line):
                    offenders.append(f"{path.relative_to(ROOT)}:{number}")
    assert offenders == [], "read the in-package __version__ instead: " + ", ".join(offenders)


def test_single_wheel_ships_every_package_file_and_operator_script(tmp_path):
    subprocess.run(
        [sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation", "-q",
         "-w", str(tmp_path), str(ROOT)],
        check=True, capture_output=True, text=True,
    )
    wheel = next(tmp_path.glob("simplicio_loop-*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        meta = next(archive.read(n).decode() for n in names if n.endswith(".dist-info/METADATA"))
        entry = next(archive.read(n).decode() for n in names if n.endswith(".dist-info/entry_points.txt"))
    requires = [line for line in meta.splitlines() if line.startswith("Requires-Dist:")]
    assert not [r for r in requires if re.match(r"Requires-Dist: simplicio-(cli|mapper)\b", r)]
    for script in OPERATOR_SCRIPTS:
        assert re.search(rf"^{re.escape(script)} = ", entry, re.M), script
    for package, base in PACKAGE_ROOTS.items():
        expected = set()
        for dirpath, dirnames, filenames in os.walk(base / package):
            dirnames[:] = [d for d in dirnames if d not in {"__pycache__", ".simplicio", ".simplicio-loop"}]  # run state
            for filename in filenames:
                if not filename.endswith((".pyc", ".pyo")) and filename not in JUNK:
                    expected.add(os.path.relpath(os.path.join(dirpath, filename), base).replace(os.sep, "/"))
        missing = sorted(expected - names)
        assert not missing, f"{package}: {len(missing)} files missing from the wheel, e.g. {missing[:5]}"


def test_subpackage_distributions_can_never_be_uploaded_on_their_own():
    for package in ("mapper", "dev-cli"):
        text = (ROOT / "packages" / package / "pyproject.toml").read_text(encoding="utf-8")
        assert '"Private :: Do Not Upload"' in text, package
