#!/usr/bin/env python3
"""Build the standalone ``simplicio-loop`` executable with PyInstaller (issue #1576).

One executable holds the loop, the mapper and the dev-cli. It runs with no Python installed.
Build it with an interpreter that has the wheel installed (not an editable install) and PyInstaller::

    python3 -m venv /tmp/slb && /tmp/slb/bin/python -m pip install . pyinstaller
    /tmp/slb/bin/python scripts/build_binary.py

Output, per the release contract of issue #1575::

    dist/binary/simplicio-loop-v<version>-<os>-<arch>[.exe]
    dist/binary/SHA256SUMS            lines of "<64 hex>  <file name>"

The tool does not cross-compile. Run it on each OS and architecture. After that, put the
assets of all platforms in one directory and run ``--checksums-only DIR``.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import tomllib
from importlib import metadata
from pathlib import Path
from typing import Mapping, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
PACKAGING = ROOT / "packaging" / "binary"
ENTRY = PACKAGING / "entry.py"
HOOKS_DIR = PACKAGING / "hooks"

PROGRAM = "simplicio-loop"
SUMS_NAME = "SHA256SUMS"
OS_NAMES = ("linux", "darwin", "windows")
ARCHES = ("x86_64", "aarch64")
MODES = ("onefile", "onedir")
# Dev and test dependencies must not reach the executable. The build interpreter should not have
# them either; this list is the second guard.
EXCLUDED_MODULES = (
    "pytest", "_pytest", "pytest_cov", "coverage", "setuptools", "pkg_resources", "wheel", "pip",
    "cryptography", "tkinter",
)

_VERSION = r"[0-9][0-9A-Za-z.+_]*"
_VERSION_RE = re.compile(rf"^{_VERSION}$")
_ASSET_RE = re.compile(
    rf"^{PROGRAM}-v(?P<version>{_VERSION})-(?P<os>{'|'.join(OS_NAMES)})-(?P<arch>{'|'.join(ARCHES)})(?P<exe>\.exe)?$"
)
_SUMS_LINE_RE = re.compile(r"^(?P<digest>[0-9a-f]{64})  (?P<name>[^\s/\\*][^/\\]*)$")


class BuildError(RuntimeError):
    """The build cannot continue. The message says what to change."""


def detect_os(platform_name: Optional[str] = None) -> str:
    name = sys.platform if platform_name is None else platform_name
    if name.startswith("linux"):
        return "linux"
    if name == "darwin":
        return "darwin"
    if name in ("win32", "cygwin", "msys"):
        return "windows"
    raise BuildError(f"unsupported platform {name!r}; the release contract has {', '.join(OS_NAMES)}")


def detect_arch(machine: Optional[str] = None) -> str:
    name = (platform.machine() if machine is None else machine).lower()
    if name in ("x86_64", "amd64"):
        return "x86_64"
    if name in ("aarch64", "arm64"):
        return "aarch64"
    raise BuildError(f"unsupported machine {name!r}; the release contract has {', '.join(ARCHES)}")


def binary_name(version: str, os_name: str, arch: str) -> str:
    if not _VERSION_RE.match(version):
        raise BuildError(f"version {version!r} cannot be part of a file name")
    if os_name not in OS_NAMES or arch not in ARCHES:
        raise BuildError(f"os {os_name!r} or arch {arch!r} is outside the release contract")
    return f"{PROGRAM}-v{version}-{os_name}-{arch}" + (".exe" if os_name == "windows" else "")


def parse_asset_name(name: str) -> Optional[tuple[str, str, str]]:
    """Return ``(version, os, arch)`` for a release asset name, or ``None`` for any other name."""
    match = _ASSET_RE.match(name)
    if match is None or bool(match["exe"]) != (match["os"] == "windows"):
        return None
    return match["version"], match["os"], match["arch"]


def project_version(root: Path = ROOT) -> str:
    return tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def format_sha256sums(digests: Mapping[str, str]) -> str:
    return "".join(f"{digest}  {name}\n" for name, digest in sorted(digests.items()))


def parse_sha256sums(text: str) -> dict[str, str]:
    digests: dict[str, str] = {}
    for line in text.splitlines():
        match = _SUMS_LINE_RE.match(line)
        if match is None:
            raise BuildError(f"bad {SUMS_NAME} line {line!r}; expected '<64 lower-case hex>  <file name>'")
        if match["name"] in digests:
            raise BuildError(f"{SUMS_NAME} lists {match['name']} twice")
        digests[match["name"]] = match["digest"]
    return digests


def write_checksums(directory: Path, version: Optional[str] = None) -> Path:
    """Write ``SHA256SUMS`` for every release asset in ``directory`` (of one version, if given)."""
    digests = {}
    for path in sorted(directory.iterdir()):
        parsed = parse_asset_name(path.name)
        if path.is_file() and parsed is not None and (version is None or parsed[0] == version):
            digests[path.name] = sha256_file(path)
    if not digests:
        raise BuildError(f"no release asset in {directory}")
    target = directory / SUMS_NAME
    target.write_text(format_sha256sums(digests), encoding="utf-8", newline="\n")
    return target


def pyinstaller_command(
    *, python: str, mode: str, dist: Path, work: Path, spec: Optional[Path] = None,
) -> list[str]:
    if mode not in MODES:
        raise BuildError(f"mode {mode!r} is not one of {', '.join(MODES)}")
    command = [
        python, "-m", "PyInstaller", "--noconfirm", "--clean", "--noupx", f"--{mode}",
        "--name", PROGRAM, "--distpath", str(dist), "--workpath", str(work),
        "--specpath", str(spec or work), "--additional-hooks-dir", str(HOOKS_DIR),
    ]
    for module in EXCLUDED_MODULES:
        command += ["--exclude-module", module]
    return [*command, str(ENTRY)]


def build_environment(base: Mapping[str, str], epoch: int) -> dict[str, str]:
    env = {key: value for key, value in base.items() if key not in ("PYTHONPATH", "PYTHONHOME")}
    env.update(SOURCE_DATE_EPOCH=str(epoch), PYTHONHASHSEED="0", TZ="UTC")
    return env


def _git(root: Path, *args: str) -> str:
    try:
        result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=60,
                                stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as error:
        raise BuildError(f"git {' '.join(args)} failed: {error}") from error
    if result.returncode != 0:
        raise BuildError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def check_clean_tree(root: Path, allow_dirty: bool) -> None:
    if allow_dirty:
        return
    changes = _git(root, "status", "--porcelain").strip()
    if changes:
        raise BuildError(
            "the working tree is dirty; commit the changes or pass --allow-dirty:\n" + changes[:2000]
        )


def source_date_epoch(root: Path) -> int:
    """``SOURCE_DATE_EPOCH`` when set (reproducible-builds.org), else the time of the last commit."""
    given = os.environ.get("SOURCE_DATE_EPOCH", "").strip()
    if given:
        if not given.isdigit():
            raise BuildError(f"SOURCE_DATE_EPOCH={given!r} is not a number of seconds")
        return int(given)
    return int(_git(root, "log", "-1", "--format=%ct").strip())


def check_installed_package(version: str, root: Path) -> None:
    """The executable must contain the installed wheel of THIS tree, not another copy."""
    try:
        installed = metadata.version(PROGRAM)
    except metadata.PackageNotFoundError as error:
        raise BuildError("simplicio-loop is not installed here; run: python -m pip install . pyinstaller") from error
    if installed != version:
        raise BuildError(
            f"the installed simplicio-loop is {installed} but this tree is {version}; "
            "run: python -m pip install --force-reinstall --no-deps ."
        )
    spec = importlib.util.find_spec("simplicio_loop")
    origin = Path(spec.origin).resolve() if spec and spec.origin else None
    if origin is None or root.resolve() in origin.parents:
        raise BuildError("simplicio_loop is imported from the source tree; install the wheel: python -m pip install .")


def _pyinstaller_version() -> str:
    try:
        return metadata.version("pyinstaller")
    except metadata.PackageNotFoundError as error:
        raise BuildError("PyInstaller is not installed here; run: python -m pip install pyinstaller") from error


def build(args: argparse.Namespace) -> dict:
    root = ROOT
    tree_version = project_version(root)
    if args.version not in (None, tree_version):
        raise BuildError(f"--version {args.version} is not the version of this tree ({tree_version})")
    out_dir, work = Path(args.out).resolve(), Path(args.work).resolve()
    os_name, arch = detect_os(), detect_arch()
    asset = binary_name(tree_version, os_name, arch)
    check_clean_tree(root, args.allow_dirty)
    check_installed_package(tree_version, root)
    pyinstaller = _pyinstaller_version()
    epoch = source_date_epoch(root)
    work_run = work / "pyinstaller"
    dist = work / "dist"
    command = pyinstaller_command(python=args.python, mode=args.mode, dist=dist, work=work_run)
    if args.dry_run:
        return {"command": command, "asset": asset, "source_date_epoch": epoch}

    for path in (work_run, dist):
        shutil.rmtree(path, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    log = work / "pyinstaller.log"
    started = time.monotonic()
    # cwd is the work directory, so the source tree is never on sys.path by accident.
    with log.open("w", encoding="utf-8") as handle:
        result = subprocess.run(command, cwd=work, env=build_environment(os.environ, epoch), stdin=subprocess.DEVNULL,
                                stdout=handle, stderr=subprocess.STDOUT)
    seconds = round(time.monotonic() - started, 1)
    if result.returncode != 0:
        tail = "\n".join(log.read_text(encoding="utf-8", errors="replace").splitlines()[-15:])
        raise BuildError(f"PyInstaller failed with exit code {result.returncode}; log {log}:\n{tail}")

    built = dist / (PROGRAM + (".exe" if os_name == "windows" else ""))
    if args.mode == "onedir":
        target = out_dir / (asset.removesuffix(".exe") + ".onedir")
        shutil.rmtree(target, ignore_errors=True)
        shutil.move(str(dist / PROGRAM), target)
        return {"asset": target.name, "mode": args.mode, "seconds": seconds, "pyinstaller": pyinstaller,
                "source_date_epoch": epoch, "log": str(log)}
    target = out_dir / asset
    target.unlink(missing_ok=True)
    shutil.move(str(built), target)
    target.chmod(0o755)
    sums = write_checksums(out_dir, tree_version)
    return {
        "asset": asset, "mode": args.mode, "path": str(target), "bytes": target.stat().st_size,
        "sha256": sha256_file(target), "sha256sums": str(sums), "seconds": seconds,
        "pyinstaller": pyinstaller, "source_date_epoch": epoch, "log": str(log),
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="build_binary", description=__doc__.split("\n\n")[0])
    parser.add_argument("--tool", choices=("pyinstaller",), default="pyinstaller",
                        help="packaging tool (the only one measured and kept; see docs/RELEASE.md)")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--onefile", dest="mode", action="store_const", const="onefile",
                       help="one executable: the release asset (default)")
    group.add_argument("--onedir", dest="mode", action="store_const", const="onedir",
                       help="a directory with the executable and its libraries; starts faster, is not a release asset")
    parser.add_argument("--version", help="assert the version to package; default: the version in pyproject.toml")
    parser.add_argument("--out", default=str(ROOT / "dist" / "binary"), help="output directory")
    parser.add_argument("--work", default=str(ROOT / "build" / "binary"), help="PyInstaller work directory")
    parser.add_argument("--python", default=sys.executable, help="interpreter with the wheel and PyInstaller installed")
    parser.add_argument("--allow-dirty", action="store_true", help="build although tracked files have changes")
    parser.add_argument("--dry-run", action="store_true", help="print the PyInstaller command and stop")
    parser.add_argument("--checksums-only", metavar="DIR",
                        help="write SHA256SUMS for the release assets already in DIR, then stop")
    parser.set_defaults(mode="onefile")
    args = parser.parse_args(argv)
    try:
        if args.checksums_only:
            sums = write_checksums(Path(args.checksums_only), args.version)
            print(json.dumps({"sha256sums": str(sums), "entries": parse_sha256sums(sums.read_text(encoding="utf-8"))}))
            return 0
        print(json.dumps(build(args), indent=2))
    except BuildError as error:
        print(f"build_binary: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
