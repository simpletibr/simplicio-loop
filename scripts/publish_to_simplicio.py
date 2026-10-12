#!/usr/bin/env python3
"""Publish standalone simplicio-loop binary to simpletibr/simplicio public distribution.

This packages the loop into an opaque standalone executable (protecting the source code)
and stages it in the simpletibr/simplicio repository for distribution to public users.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SIMPLICIO_DIR = REPO_ROOT.parent / "simplicio"

TARGET_MAP = {
    ("darwin", "aarch64"): "simplicio-loop-macos-arm64",
    ("darwin", "x86_64"): "simplicio-loop-macos-x64",
    ("linux", "x86_64"): "simplicio-loop-linux-x64",
    ("windows", "x86_64"): "simplicio-loop-windows-x64.exe",
}


def compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def detect_target() -> str:
    import platform
    plat = sys.platform
    arch = platform.machine().lower()
    if arch in ("arm64", "aarch64"):
        arch_norm = "aarch64"
    elif arch in ("x86_64", "amd64"):
        arch_norm = "x86_64"
    else:
        arch_norm = arch

    if plat.startswith("linux"):
        os_norm = "linux"
    elif plat == "darwin":
        os_norm = "darwin"
    elif plat in ("win32", "cygwin", "msys"):
        os_norm = "windows"
    else:
        os_norm = plat

    target = TARGET_MAP.get((os_norm, arch_norm))
    if not target:
        raise RuntimeError(f"Unsupported OS/arch triplet: ({os_norm}, {arch_norm})")
    return target


def find_or_build_binary(dist_binary_dir: Path) -> Path:
    target = detect_target()
    candidates = list(dist_binary_dir.glob("simplicio-loop-v*-*"))
    candidates = [c for c in candidates if not c.name.endswith(".json") and not c.name.endswith(".txt")]
    if candidates:
        latest = sorted(candidates, key=lambda p: p.stat().st_mtime)[-1]
        print(f"[+] Found existing standalone binary: {latest}")
        return latest

    print("[*] No binary found in dist/binary/. Building now with build_binary.py...")
    subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "build_binary.py"), "--allow-dirty"], check=True)
    candidates = list(dist_binary_dir.glob("simplicio-loop-v*-*"))
    candidates = [c for c in candidates if not c.name.endswith(".json") and not c.name.endswith(".txt")]
    if not candidates:
        raise RuntimeError("Build finished but no binary was found in dist/binary/")
    return sorted(candidates, key=lambda p: p.stat().st_mtime)[-1]


def stage_in_simplicio_repo(binary_path: Path, simplicio_repo: Path, upload_gh: bool = False):
    if not simplicio_repo.is_dir():
        raise RuntimeError(f"simplicio repository directory not found at: {simplicio_repo}")

    target_name = detect_target()
    dest_path = simplicio_repo / target_name
    print(f"[*] Copying {binary_path.name} -> {dest_path}...")
    shutil.copy2(binary_path, dest_path)
    os.chmod(dest_path, 0o755)

    sha256 = compute_sha256(dest_path)
    print(f"[+] Staged {target_name} ({dest_path.stat().st_size} bytes, SHA256: {sha256})")

    # Update SHA256SUMS in simplicio repo
    sums_file = simplicio_repo / "SHA256SUMS"
    existing_lines = []
    if sums_file.exists():
        existing_lines = sums_file.read_text(encoding="utf-8").splitlines()

    new_line = f"{sha256} *{target_name}"
    updated = False
    new_lines = []
    for line in existing_lines:
        if target_name in line:
            new_lines.append(new_line)
            updated = True
        else:
            new_lines.append(line)
    if not updated:
        new_lines.append(new_line)

    sums_file.write_text(chr(10).join(new_lines) + chr(10), encoding="utf-8")
    print(f"[+] Updated {sums_file} with {target_name}")

    if upload_gh:
        print("[*] Uploading asset to latest GitHub Release of simpletibr/simplicio...")
        try:
            subprocess.run(["gh", "release", "upload", "-R", "simpletibr/simplicio", "latest", f"{dest_path}#{target_name}", "--clobber"], check=True)
            print("[+] Uploaded to simpletibr/simplicio latest release successfully.")
        except Exception as e:
            print(f"[!] Warning: gh release upload failed: {e}")


def main():
    parser = argparse.ArgumentParser(description="Publish simplicio-loop binary to simpletibr/simplicio distribution")
    parser.add_argument("--simplicio-dir", type=Path, default=DEFAULT_SIMPLICIO_DIR, help="Path to simpletibr/simplicio checkout")
    parser.add_argument("--upload-gh", action="store_true", help="Also upload asset to simpletibr/simplicio GitHub release via gh")
    args = parser.parse_args()

    binary_dir = REPO_ROOT / "dist" / "binary"
    binary_path = find_or_build_binary(binary_dir)
    stage_in_simplicio_repo(binary_path, args.simplicio_dir, upload_gh=args.upload_gh)
    print("[+] Publication process completed successfully.")


if __name__ == "__main__":
    main()
