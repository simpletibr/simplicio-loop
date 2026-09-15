"""Governed local fallback for the native release workflow (issue #229).

The workflow is the contract. This runner mirrors its build, staging, manifest,
verification, archive, and ``gh release`` stages while continuing per target so
an unavailable cross toolchain cannot result in a fabricated binary.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
from dataclasses import dataclass
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_native_manifest import build_manifest  # noqa: E402
from scripts.verify_fast_core_bundle import verify as verify_core  # noqa: E402
from scripts.verify_native_bundle import verify as verify_native  # noqa: E402


SCHEMA = "simplicio.fast.manual-native-release/v1"
ABI_DIR = "simplicio.fast-native_v1"
CORE_DIR = "simplicio.fast-core_v1"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class Target:
    platform: str
    triple: str
    compatibility_filename: str
    core_filename: str
    linker: str = ""


TARGETS = {
    item.platform: item
    for item in (
        Target(
            "linux-x86_64",
            "x86_64-unknown-linux-gnu",
            "simplicio-fast-native",
            "simplicio-fast-rs",
        ),
        Target(
            "linux-aarch64",
            "aarch64-unknown-linux-gnu",
            "simplicio-fast-native",
            "simplicio-fast-rs",
            "aarch64-linux-gnu-gcc",
        ),
        Target(
            "macos-aarch64",
            "aarch64-apple-darwin",
            "simplicio-fast-native",
            "simplicio-fast-rs",
        ),
        Target(
            "windows-x86_64",
            "x86_64-pc-windows-msvc",
            "simplicio-fast-native.exe",
            "simplicio-fast-rs.exe",
        ),
    )
}


def _run(
    command: list[str], *, cwd: Path, env: dict[str, str] | None = None
) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as error:
        return {
            "command": command,
            "returncode": 127,
            "stdout": "",
            "stderr": str(error),
        }
    return {
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def _tail(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "command": result["command"],
        "returncode": result["returncode"],
        "stdout_tail": result["stdout"][-4000:],
        "stderr_tail": result["stderr"][-4000:],
    }


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _git_value(root: Path, *args: str) -> str:
    result = _run(["git", *args], cwd=root)
    if result["returncode"]:
        raise RuntimeError(result["stderr"].strip() or "git command failed")
    return result["stdout"].strip()


def _version(root: Path, requested: str | None) -> str:
    if requested:
        return requested
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r"^version\s*=\s*\"([^\"]+)\"", pyproject, re.MULTILINE)
    if not match:
        raise RuntimeError("package version is missing from pyproject.toml")
    return match.group(1)


def _toolchain(root: Path) -> str:
    result = _run(["rustc", "--version"], cwd=root)
    return (
        result["stdout"].strip() if result["returncode"] == 0 else "rustc unavailable"
    )


def _host_triple(root: Path) -> str:
    result = _run(["rustc", "-vV"], cwd=root)
    for line in result["stdout"].splitlines():
        if line.startswith("host:"):
            return line.split(":", 1)[1].strip()
    return ""


def _installed_targets(root: Path) -> set[str]:
    result = _run(["rustup", "target", "list", "--installed"], cwd=root)
    return set(result["stdout"].split()) if result["returncode"] == 0 else set()


def _zig_linker(
    root: Path, target: Target, build_root: Path
) -> tuple[str, Path | None]:
    zig = shutil.which("zig")
    if not zig or not target.triple.endswith("unknown-linux-gnu"):
        return target.linker, None
    arch = "aarch64" if target.triple.startswith("aarch64") else "x86_64"
    wrapper = build_root / f"zig-{arch}-linker.cmd"
    wrapper.write_text(
        f'@echo off\r\n"{zig}" cc -target {arch}-linux-gnu %*\r\n',
        encoding="utf-8",
    )
    return str(wrapper), wrapper


def _builder(target: Target) -> str:
    if target.triple != "x86_64-pc-windows-msvc":
        cross = shutil.which("cross")
        if cross:
            return cross
    cargo = shutil.which("cargo")
    if not cargo:
        raise RuntimeError("cargo is unavailable")
    return cargo


def _build_crate(
    root: Path,
    target: Target,
    manifest: Path,
    *,
    env: dict[str, str],
    log: list[dict[str, Any]],
) -> bool:
    builder = _builder(target)
    command = [
        builder,
        "build",
        "--release",
        "--locked",
        "--target",
        target.triple,
        "--manifest-path",
        str(manifest),
    ]
    result = _run(command, cwd=root, env=env)
    log.append(_tail(result))
    return result["returncode"] == 0


def _engine_manifest(
    root: Path, *, version: str, target: Target, source_commit: str
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    command = [
        "cargo",
        "run",
        "--locked",
        "--quiet",
        "--manifest-path",
        "rust/simplicio-fast-core/Cargo.toml",
        "--",
        "--version",
        "--json",
    ]
    result = _run(command, cwd=root)
    if result["returncode"]:
        return None, _tail(result)
    try:
        manifest = json.loads(result["stdout"].strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        return None, _tail(result)
    if manifest.get("version") != version:
        return None, {**_tail(result), "reason": "engine manifest version mismatch"}
    manifest["manual_release"] = {
        "source_commit": source_commit,
        "target": target.platform,
        "target_runtime_probe": "host"
        if target.triple == _host_triple(root)
        else "UNVERIFIED: cross-target executable was not run on this host",
    }
    return manifest, _tail(result)


def _target_root(output_root: Path, target: Target) -> Path:
    return output_root / target.platform


def _verified_target(
    root: Path, output_root: Path, target: Target, version: str
) -> dict[str, Any]:
    staged = _target_root(output_root, target)
    native = verify_native(
        staged, expected_platform=target.platform, expected_version=version
    )
    core = verify_core(
        staged / CORE_DIR / target.core_filename,
        staged / CORE_DIR / "engine-manifest.json",
        expected_version=version,
    )
    return {
        "platform": target.platform,
        "native": native,
        "core": core,
        "status": "pass"
        if native["status"] == "pass" and core["status"] == "pass"
        else "fail",
    }


def build_target(
    root: Path,
    output_root: Path,
    target: Target,
    *,
    version: str,
    source_commit: str,
    force: bool,
) -> dict[str, Any]:
    staged = _target_root(output_root, target)
    if not force and staged.exists():
        existing = _verified_target(root, output_root, target, version)
        manifest_path = staged / ABI_DIR / "manifest.json"
        if (
            existing["status"] == "pass"
            and manifest_path.is_file()
            and json.loads(manifest_path.read_text(encoding="utf-8")).get(
                "source_commit"
            )
            == source_commit
        ):
            return {
                "platform": target.platform,
                "status": "idempotent",
                "verification": existing,
            }

    logs: list[dict[str, Any]] = []
    build_root = output_root / ".build"
    build_root.mkdir(parents=True, exist_ok=True)
    linker, wrapper = _zig_linker(root, target, build_root)
    env = os.environ.copy()
    if linker:
        env[f"CARGO_TARGET_{target.triple.upper().replace('-', '_')}_LINKER"] = linker
    installed = _installed_targets(root)
    if target.triple not in installed and target.triple != _host_triple(root):
        add = _run(["rustup", "target", "add", target.triple], cwd=root, env=env)
        logs.append(_tail(add))
        if add["returncode"]:
            return {
                "platform": target.platform,
                "status": "UNVERIFIED",
                "reason": "target toolchain unavailable",
                "logs": logs,
            }

    compatibility_ok = _build_crate(
        root, target, root / "native/fast-native/Cargo.toml", env=env, log=logs
    )
    core_ok = _build_crate(
        root, target, root / "rust/simplicio-fast-core/Cargo.toml", env=env, log=logs
    )
    if not compatibility_ok or not core_ok:
        return {
            "platform": target.platform,
            "status": "UNVERIFIED",
            "reason": "cargo build failed",
            "logs": logs,
        }

    compatibility_source = (
        root
        / "native/fast-native/target"
        / target.triple
        / "release"
        / target.compatibility_filename
    )
    # The core crate belongs to rust/Cargo.toml's workspace, so Cargo places
    # its artifacts in the workspace target directory.
    core_source = (
        root / "rust/target" / target.triple / "release" / target.core_filename
    )
    compatibility_dest = staged / ABI_DIR / target.compatibility_filename
    core_dest = staged / CORE_DIR / target.core_filename
    compatibility_dest.parent.mkdir(parents=True, exist_ok=True)
    core_dest.parent.mkdir(parents=True, exist_ok=True)
    if not compatibility_source.is_file() or not core_source.is_file():
        return {
            "platform": target.platform,
            "status": "UNVERIFIED",
            "reason": "cargo did not produce both binaries",
            "logs": logs,
        }
    shutil.copy2(compatibility_source, compatibility_dest)
    shutil.copy2(core_source, core_dest)
    manifest = build_manifest(
        compatibility_dest,
        platform=target.platform,
        version=version,
        source_commit=source_commit,
        toolchain=_toolchain(root),
    )
    _write_json(staged / ABI_DIR / "manifest.json", manifest)
    engine_manifest, probe = _engine_manifest(
        root, version=version, target=target, source_commit=source_commit
    )
    logs.append(probe)
    if engine_manifest is None:
        return {
            "platform": target.platform,
            "status": "UNVERIFIED",
            "reason": "core manifest probe failed",
            "logs": logs,
        }
    _write_json(staged / CORE_DIR / "engine-manifest.json", engine_manifest)
    verification = _verified_target(root, output_root, target, version)
    return {
        "platform": target.platform,
        "status": verification["status"],
        "verification": verification,
        "logs": logs,
        "linker_wrapper": str(wrapper) if wrapper else None,
    }


def build(
    root: Path,
    output_root: Path,
    *,
    version: str,
    source_commit: str,
    platforms: Iterable[str],
    force: bool,
) -> dict[str, Any]:
    if not SHA_RE.fullmatch(source_commit):
        raise ValueError("source_commit must be a 40-character lowercase commit SHA")
    results = [
        build_target(
            root,
            output_root,
            TARGETS[platform],
            version=version,
            source_commit=source_commit,
            force=force,
        )
        for platform in platforms
    ]
    receipt = {
        "schema": SCHEMA,
        "operation": "build",
        "version": version,
        "source_commit": source_commit,
        "output_root": str(output_root),
        "targets": results,
        "verified_platforms": [
            item["platform"]
            for item in results
            if item["status"] in {"pass", "idempotent"}
        ],
        "unverified_platforms": [
            item["platform"] for item in results if item["status"] == "UNVERIFIED"
        ],
    }
    _write_json(output_root / "manual-native-release.json", receipt)
    return receipt


def _tar_bytes(directory: Path) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.GNU_FORMAT) as archive:
        paths = sorted(
            directory.rglob("*"),
            key=lambda path: path.relative_to(directory).as_posix(),
        )
        for path in paths:
            relative = path.relative_to(directory).as_posix()
            info = archive.gettarinfo(str(path), arcname=relative)
            info.uid = info.gid = 0
            info.uname = info.gname = "root"
            info.mtime = 0
            if info.isfile():
                info.mode = 0o755 if os.access(path, os.X_OK) else 0o644
                with path.open("rb") as handle:
                    archive.addfile(info, handle)
            else:
                archive.addfile(info)
    return buffer.getvalue()


def archive(
    root: Path, output_root: Path, *, version: str, platforms: Iterable[str]
) -> dict[str, Any]:
    archives: list[dict[str, Any]] = []
    for platform in platforms:
        target = TARGETS[platform]
        staged = _target_root(output_root, target)
        verification = _verified_target(root, output_root, target, version)
        if verification["status"] != "pass":
            continue
        content = gzip.compress(_tar_bytes(staged), compresslevel=9, mtime=0)
        destination = output_root / f"simplicio-fast-engines-{platform}.tar.gz"
        destination.write_bytes(content)
        second = gzip.compress(_tar_bytes(staged), compresslevel=9, mtime=0)
        archives.append(
            {
                "platform": platform,
                "path": str(destination),
                "sha256": hashlib.sha256(content).hexdigest(),
                "size": len(content),
                "deterministic": content == second,
            }
        )
    receipt = {
        "schema": SCHEMA,
        "operation": "archive",
        "version": version,
        "archives": archives,
        "unverified_platforms": [
            platform
            for platform in platforms
            if platform not in {item["platform"] for item in archives}
        ],
    }
    _write_json(output_root / "manual-native-archives.json", receipt)
    return receipt


def publish(root: Path, output_root: Path, *, tag: str, repo: str) -> dict[str, Any]:
    receipt_path = output_root / "manual-native-archives.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    paths = [item["path"] for item in receipt["archives"]]
    if not paths:
        raise RuntimeError("no verified archives are available for publication")
    view = _run(
        ["gh", "release", "view", tag, "--repo", repo, "--json", "tagName,assets,url"],
        cwd=root,
    )
    if view["returncode"]:
        create = _run(
            [
                "gh",
                "release",
                "create",
                tag,
                "--repo",
                repo,
                "--verify-tag",
                "--generate-notes",
            ],
            cwd=root,
        )
        if create["returncode"]:
            raise RuntimeError(create["stderr"].strip() or "gh release create failed")
    upload = _run(
        ["gh", "release", "upload", tag, *paths, "--repo", repo, "--clobber"], cwd=root
    )
    if upload["returncode"]:
        raise RuntimeError(upload["stderr"].strip() or "gh release upload failed")
    final = _run(
        ["gh", "release", "view", tag, "--repo", repo, "--json", "tagName,assets,url"],
        cwd=root,
    )
    if final["returncode"]:
        raise RuntimeError(
            final["stderr"].strip() or "gh release view failed after upload"
        )
    payload = json.loads(final["stdout"])
    uploaded_names = {item["name"] for item in payload.get("assets", [])}
    expected_names = {Path(path).name for path in paths}
    missing = sorted(expected_names - uploaded_names)
    result = {
        "schema": SCHEMA,
        "operation": "publish",
        "tag": tag,
        "repo": repo,
        "release": payload,
        "uploaded": sorted(expected_names),
        "missing": missing,
        "status": "pass" if not missing else "fail",
    }
    _write_json(output_root / "manual-native-publish.json", result)
    if missing:
        raise RuntimeError(f"release assets missing after upload: {missing}")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "archive", "publish", "run"))
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output-root", type=Path, default=None)
    parser.add_argument("--version")
    parser.add_argument("--source-commit")
    parser.add_argument(
        "--platform", action="append", choices=tuple(TARGETS), dest="platforms"
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--tag", default="v2.0.23")
    parser.add_argument("--repo", default="wesleysimplicio/simplicio-fast")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    version = _version(root, args.version)
    output_root = (
        args.output_root or root / "dist" / "manual-native" / version
    ).resolve()
    platforms = args.platforms or list(TARGETS)
    source_commit = args.source_commit or _git_value(root, "rev-parse", "HEAD")
    if args.command == "build":
        result = build(
            root,
            output_root,
            version=version,
            source_commit=source_commit,
            platforms=platforms,
            force=args.force,
        )
    elif args.command == "archive":
        result = archive(root, output_root, version=version, platforms=platforms)
    elif args.command == "publish":
        result = publish(root, output_root, tag=args.tag, repo=args.repo)
    else:
        build(
            root,
            output_root,
            version=version,
            source_commit=source_commit,
            platforms=platforms,
            force=args.force,
        )
        archive_receipt = archive(
            root, output_root, version=version, platforms=platforms
        )
        if not archive_receipt["archives"]:
            result = archive_receipt
        else:
            result = publish(root, output_root, tag=args.tag, repo=args.repo)
    print(
        json.dumps(result, sort_keys=True, separators=(",", ":"))
        if args.json
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
