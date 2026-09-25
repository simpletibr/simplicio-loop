#!/usr/bin/env python3
"""Single source of truth + mechanical apply for every version surface in simplicio-fast.

Supports:
    python3 scripts/version_sync.py check
    python3 scripts/version_sync.py apply --version X.Y.Z
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from pathlib import Path
import tomllib
from typing import Any

SCHEMA = "simplicio.fast.version-sync/v1"
VERSION_RE = re.compile(
    r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<prerelease>[0-9a-zA-Z.-]+))?(?:\+(?P<build>[0-9a-zA-Z.-]+))?$"
)


def _validate_version(version: str) -> str:
    if not VERSION_RE.match(version or ""):
        raise ValueError(f"Version {version!r} is not a valid semantic version (X.Y.Z)")
    return version


def get_current_versions(root: Path) -> dict[str, str | None]:
    versions: dict[str, str | None] = {}

    # 1. pyproject.toml
    try:
        data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        versions["pyproject"] = data.get("project", {}).get("version")
    except Exception:
        versions["pyproject"] = None

    # 2. src/simplicio_fast/__init__.py
    try:
        init_content = (root / "src/simplicio_fast/__init__.py").read_text(encoding="utf-8")
        match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', init_content)
        versions["package"] = match.group(1) if match else None
    except Exception:
        versions["package"] = None

    # 3. rust/simplicio-fast-core/Cargo.toml
    try:
        cargo_core = tomllib.loads(
            (root / "rust/simplicio-fast-core/Cargo.toml").read_text(encoding="utf-8")
        )
        versions["rust_core"] = cargo_core.get("package", {}).get("version")
    except Exception:
        versions["rust_core"] = None

    # 4. rust/Cargo.lock
    try:
        cargo_lock = tomllib.loads((root / "rust/Cargo.lock").read_text(encoding="utf-8"))
        versions["rust_lock"] = next(
            (
                pkg["version"]
                for pkg in cargo_lock.get("package", [])
                if pkg.get("name") == "simplicio-fast-core"
            ),
            None,
        )
    except Exception:
        versions["rust_lock"] = None

    # 5. README.md
    try:
        readme = (root / "README.md").read_text(encoding="utf-8")
        badge_match = re.search(r"version-([0-9]+\.[0-9]+\.[0-9]+[^\s-]*)-", readme)
        versions["readme_badge"] = badge_match.group(1) if badge_match else None
        text_match = re.search(r"Version ([0-9]+\.[0-9]+\.[0-9]+[^\s\"]*)", readme)
        versions["readme_text"] = text_match.group(1) if text_match else None
    except Exception:
        versions["readme_badge"] = None
        versions["readme_text"] = None

    return versions


def apply_version(root: Path, version: str) -> dict[str, Any]:
    _validate_version(version)
    current = get_current_versions(root)
    old_version = current.get("pyproject") or "unknown"
    changed_files: list[str] = []

    # 1. pyproject.toml
    pyproject_path = root / "pyproject.toml"
    text = pyproject_path.read_text(encoding="utf-8")
    new_text, count = re.subn(
        r'(?m)^(version\s*=\s*)["\'][^"\']+["\']',
        rf'\g<1>"{version}"',
        text,
        count=1,
    )
    if count == 0:
        raise ValueError(f"No version line found in {pyproject_path}")
    if new_text != text:
        pyproject_path.write_text(new_text, encoding="utf-8")
        changed_files.append(str(pyproject_path.relative_to(root)))

    # 2. src/simplicio_fast/__init__.py
    init_path = root / "src/simplicio_fast/__init__.py"
    text = init_path.read_text(encoding="utf-8")
    new_text, count = re.subn(
        r'(?m)^(__version__\s*=\s*)["\'][^"\']+["\']',
        rf'\g<1>"{version}"',
        text,
        count=1,
    )
    if count == 0:
        raise ValueError(f"No __version__ line found in {init_path}")
    if new_text != text:
        init_path.write_text(new_text, encoding="utf-8")
        changed_files.append(str(init_path.relative_to(root)))

    # 3. rust/simplicio-fast-core/Cargo.toml
    cargo_core_path = root / "rust/simplicio-fast-core/Cargo.toml"
    text = cargo_core_path.read_text(encoding="utf-8")
    new_text, count = re.subn(
        r'(?m)^(version\s*=\s*)["\'][^"\']+["\']',
        rf'\g<1>"{version}"',
        text,
        count=1,
    )
    if count == 0:
        raise ValueError(f"No version line found in {cargo_core_path}")
    if new_text != text:
        cargo_core_path.write_text(new_text, encoding="utf-8")
        changed_files.append(str(cargo_core_path.relative_to(root)))

    # 4. Cargo lockfiles
    for lock_rel in ("rust/Cargo.lock", "native/fast-native/Cargo.lock"):
        cargo_lock_path = root / lock_rel
        if cargo_lock_path.exists():
            text = cargo_lock_path.read_text(encoding="utf-8")
            pattern = r'(\[\[package\]\]\s*\nname\s*=\s*"simplicio-fast-core"\s*\nversion\s*=\s*)"[^"]+"'
            new_text, count = re.subn(
                pattern,
                rf'\g<1>"{version}"',
                text,
                count=1,
            )
            if count and new_text != text:
                cargo_lock_path.write_text(new_text, encoding="utf-8")
                changed_files.append(str(cargo_lock_path.relative_to(root)))

    # 5. README.md
    readme_path = root / "README.md"
    if readme_path.exists():
        text = readme_path.read_text(encoding="utf-8")
        new_text = re.sub(r"version-[0-9]+\.[0-9]+\.[0-9]+[^\s-]*-", f"version-{version}-", text)
        new_text = re.sub(r"Version [0-9]+\.[0-9]+\.[0-9]+[^\s\"]*", f"Version {version}", new_text)
        if new_text != text:
            readme_path.write_text(new_text, encoding="utf-8")
            changed_files.append(str(readme_path.relative_to(root)))

    # 6. CHANGELOG.md
    changelog_path = root / "CHANGELOG.md"
    if changelog_path.exists():
        text = changelog_path.read_text(encoding="utf-8")
        if f"## {version} " not in text:
            today = datetime.date.today().isoformat()
            if "## Unreleased" in text:
                new_text = text.replace("## Unreleased", f"## {version} - {today}")
            else:
                new_text = f"# Changelog\n\n## {version} - {today}\n\n" + text.removeprefix("# Changelog\n\n")
            if new_text != text:
                changelog_path.write_text(new_text, encoding="utf-8")
                changed_files.append(str(changelog_path.relative_to(root)))

    return {
        "status": "applied",
        "previous_version": old_version,
        "new_version": version,
        "changed_files": changed_files,
    }


def check_version(root: Path) -> dict[str, Any]:
    current = get_current_versions(root)
    pyproject_version = current.get("pyproject")
    if not pyproject_version:
        return {"status": "fail", "reason": "pyproject.toml has no version", "surfaces": current}

    mismatches = {k: v for k, v in current.items() if v != pyproject_version}
    status = "pass" if not mismatches else "fail"
    return {
        "status": status,
        "version": pyproject_version,
        "mismatches": mismatches,
        "surfaces": current,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Version sync tool for simplicio-fast")
    parser.add_argument("--root", type=Path, default=Path("."))
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    check_parser = subparsers.add_parser("check", help="Check version consistency across surfaces")
    check_parser.add_argument("--json", action="store_true")

    apply_parser = subparsers.add_parser("apply", help="Apply version bump across surfaces")
    apply_parser.add_argument("--version", required=True, help="New semver version (X.Y.Z)")
    apply_parser.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    root = args.root.resolve()

    if args.subcommand == "check":
        res = check_version(root)
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            print(f"Version check: {res['status']} (version: {res.get('version')})")
            if res.get("mismatches"):
                print("Mismatches found:")
                for k, v in res["mismatches"].items():
                    print(f"  {k}: {v} != {res.get('version')}")
        return 0 if res["status"] == "pass" else 1

    if args.subcommand == "apply":
        res = apply_version(root, args.version)
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            print(f"Applied version {res['new_version']} (was {res['previous_version']})")
            print("Changed files:")
            for f in res["changed_files"]:
                print(f"  - {f}")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
