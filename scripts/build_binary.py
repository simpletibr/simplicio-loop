#!/usr/bin/env python3
"""Build the standalone ``simplicio-loop`` executable with PyInstaller (issue #1576).

One executable holds the loop, the mapper and the dev-cli. It runs with no Python installed.
The build makes the wheel of THIS tree itself, so the executable holds that wheel by construction::

    python3 scripts/build_binary.py            # needs network: pip downloads the dependencies

The steps, all under ``--work``: export the sources of the tree (``HEAD`` of a git checkout, a copy
otherwise), build a wheel from that export, make a new venv from ``--python``, install exactly that
wheel and a pinned PyInstaller in it, run PyInstaller from that venv, and check ``--version`` of the result.

Output, per the release contract of issue #1575::

    dist/binary/simplicio-loop-v<version>-<os>-<arch>[.exe]
    dist/binary/SHA256SUMS            lines of "<64 hex>  <file name>"

The tool does not cross-compile. Run it on each OS and architecture. After that, put the
assets of all platforms in one directory and run ``--checksums-only DIR``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import tomllib
from pathlib import Path
from typing import Mapping, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
PACKAGING = ROOT / "packaging" / "binary"
ENTRY = PACKAGING / "entry.py"
HOOKS_DIR = PACKAGING / "hooks"
RUNNER = PACKAGING / "pyinstaller_run.py"
# The runner patches an internal of PyInstaller (the order of base_library.zip), so the version is pinned.
PYINSTALLER_VERSION = "6.22.3"

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
        python, str(RUNNER), "--noconfirm", "--clean", "--noupx", f"--{mode}",
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


def export_source(root: Path, dest: Path) -> str:
    """Put a clean copy of the sources in ``dest``. Return where it comes from.

    A git checkout gives ``HEAD`` as a detached worktree: no build output of earlier builds, no local
    changes, and a ``.git`` so the build stamp of the mapper can record the commit. A tree without git (the
    copy of the release rehearsal) is copied without build output.
    """
    if (root / ".git").exists():
        _git(root, "worktree", "add", "--detach", str(dest), "HEAD")
        return "HEAD " + _git(dest, "rev-parse", "HEAD").strip()
    skip = shutil.ignore_patterns(".git", "build", "dist", "__pycache__", "*.egg-info")
    shutil.copytree(root, dest, ignore=skip)
    return "copy"


def release_source(root: Path, dest: Path) -> None:
    """Remove what ``export_source`` made, and the worktree entry of git."""
    if (dest / ".git").exists():
        try:
            _git(root, "worktree", "remove", "--force", str(dest))
        except BuildError:
            pass
    shutil.rmtree(dest, ignore_errors=True)
    if (root / ".git").exists():
        try:
            _git(root, "worktree", "prune")
        except BuildError:
            pass


def _venv_python(venv: Path, os_name: str) -> str:
    return str(venv / ("Scripts" if os_name == "windows" else "bin") / ("python.exe" if os_name == "windows" else "python"))


def _run(run, command, *, env: Mapping[str, str], cwd: Path, log: Path, label: str) -> subprocess.CompletedProcess:
    """Run one build command. Its output goes to the log; a failure shows the end of the log."""
    result = run([str(part) for part in command], cwd=cwd, env=dict(env), stdin=subprocess.DEVNULL,
                 capture_output=True, text=True)
    with log.open("a", encoding="utf-8") as handle:
        handle.write(f"$ {' '.join(map(str, command))}\n{result.stdout}{result.stderr}\n")
    if result.returncode != 0:
        tail = "\n".join((result.stdout + result.stderr).strip().splitlines()[-15:])
        raise BuildError(f"{label} failed with exit code {result.returncode}; log {log}:\n{tail}")
    return result


def build(args: argparse.Namespace, run=subprocess.run) -> dict:
    root = ROOT
    tree_version = project_version(root)
    if args.version not in (None, tree_version):
        raise BuildError(f"--version {args.version} is not the version of this tree ({tree_version})")
    out_dir, work = Path(args.out).resolve(), Path(args.work).resolve()
    os_name, arch = detect_os(), detect_arch()
    asset = binary_name(tree_version, os_name, arch)
    check_clean_tree(root, args.allow_dirty)
    epoch = source_date_epoch(root)
    source, wheels, venv, dist, scratch = (work / name for name in ("src", "wheel", "venv", "dist", "pyinstaller"))
    python = _venv_python(venv, os_name)
    wheel_command = [python, "-m", "pip", "wheel", "--no-deps", "--disable-pip-version-check", "-w", wheels, source]
    install_command = [python, "-m", "pip", "install", "--disable-pip-version-check", "--no-input",
                       "<the wheel>", f"pyinstaller=={PYINSTALLER_VERSION}"]
    pyinstaller_cmd = pyinstaller_command(python=python, mode=args.mode, dist=dist, work=scratch)
    if args.dry_run:
        return {"commands": [[args.python, "-m", "venv", venv], wheel_command, install_command, pyinstaller_cmd],
                "asset": asset, "source_date_epoch": epoch}

    work.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    release_source(root, source)  # what a failed earlier build left
    for path in (wheels, venv, dist, scratch):
        shutil.rmtree(path, ignore_errors=True)
    log = work / "build.log"
    log.write_text("", encoding="utf-8")
    env = build_environment(os.environ, epoch)
    started = time.monotonic()
    origin = export_source(root, source)
    try:
        _run(run, [args.python, "-m", "venv", venv], env=env, cwd=work, log=log, label="making the venv")
        _run(run, wheel_command, env=env, cwd=work, log=log, label="building the wheel of this tree")
        built_wheels = list(wheels.glob("*.whl"))
        if len(built_wheels) != 1:
            raise BuildError(f"expected one wheel in {wheels}, found {len(built_wheels)}")
        wheel = built_wheels[0]
        install_command[install_command.index("<the wheel>")] = str(wheel)
        _run(run, install_command, env=env, cwd=work, log=log, label="installing the wheel and PyInstaller")
        _run(run, pyinstaller_cmd, env=env, cwd=work, log=log, label="PyInstaller")
    finally:
        release_source(root, source)
    seconds = round(time.monotonic() - started, 1)

    if args.mode == "onedir":
        target = out_dir / (asset.removesuffix(".exe") + ".onedir")
        shutil.rmtree(target, ignore_errors=True)
        shutil.move(str(dist / PROGRAM), target)
        return {"asset": target.name, "mode": args.mode, "seconds": seconds, "source": origin,
                "source_date_epoch": epoch, "log": str(log)}
    built = dist / (PROGRAM + (".exe" if os_name == "windows" else ""))
    built.chmod(0o755)
    shown = run([str(built), "--version"], cwd=work, env=env, capture_output=True, text=True, timeout=300,
                stdin=subprocess.DEVNULL)
    if shown.returncode != 0 or shown.stdout.strip() != f"{PROGRAM} {tree_version}":
        raise BuildError(f"the executable printed {shown.stdout.strip()!r} for --version, expected "
                         f"'{PROGRAM} {tree_version}'; nothing was published")
    partial = out_dir / f".{asset}.partial"
    shutil.move(str(built), partial)
    os.replace(partial, out_dir / asset)  # the asset appears whole or not at all
    target = out_dir / asset
    sums = write_checksums(out_dir, tree_version)
    return {
        "asset": asset, "mode": args.mode, "path": str(target), "bytes": target.stat().st_size,
        "sha256": sha256_file(target), "sha256sums": str(sums), "seconds": seconds,
        "pyinstaller": PYINSTALLER_VERSION, "source": origin, "source_date_epoch": epoch, "log": str(log),
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
    parser.add_argument("--work", default=str(ROOT / "build" / "binary"),
                        help="work directory: the export, the wheel, the new venv and the PyInstaller files")
    parser.add_argument("--python", default=sys.executable, help="interpreter that makes the build venv")
    parser.add_argument("--allow-dirty", action="store_true",
                        help="build although tracked files have changes (the build uses HEAD, not the changes)")
    parser.add_argument("--dry-run", action="store_true", help="print the build commands and stop")
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
