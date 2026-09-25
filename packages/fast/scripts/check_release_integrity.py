"""Fail-closed release metadata, ownership, and branch-policy gate."""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import subprocess
import tomllib
from typing import Any


SCHEMA = "simplicio.fast.release-integrity/v1"
POLICY_SCHEMA = "simplicio.fast.release-policy/v1"


def _check(
    checks: list[dict[str, Any]], name: str, passed: bool, **detail: Any
) -> None:
    checks.append({"name": name, "status": "pass" if passed else "fail", **detail})


def _package_version(init_path: Path) -> str | None:
    try:
        tree = ast.parse(init_path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return None
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "__version__"
                for target in node.targets
            )
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            return node.value.value
    return None


def _remote_default_branch(root: Path) -> tuple[str | None, str | None]:
    try:
        result = subprocess.run(
            ["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return None, type(error).__name__
    if result.returncode != 0:
        return None, "origin_head_unavailable"
    value = result.stdout.strip()
    return (value.removeprefix("origin/") or None), None


def evaluate(root: Path) -> dict[str, Any]:
    root = root.resolve()
    checks: list[dict[str, Any]] = []
    try:
        policy = json.loads(
            (root / "src/simplicio_fast/release_policy.json").read_text(
                encoding="utf-8"
            )
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        policy = {}
    _check(checks, "policy_schema", policy.get("schema") == POLICY_SCHEMA)
    try:
        root_policy = json.loads(
            (root / "release-policy.json").read_text(encoding="utf-8")
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        root_policy = None
    _check(checks, "policy_mirror", root_policy == policy)
    _check(
        checks,
        "canonical_sources",
        policy.get("version_source") == "pyproject.toml"
        and policy.get("dependency_source") == "pyproject.toml",
    )

    try:
        project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))[
            "project"
        ]
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError, KeyError, TypeError):
        project = {}
    version = project.get("version")
    dependencies = project.get("dependencies")
    dependencies = dependencies if isinstance(dependencies, list) else []
    optional = project.get("optional-dependencies")
    optional = optional if isinstance(optional, dict) else {}
    integration_extra = policy.get("integration_extra")
    integrated_dependencies = (
        optional.get(integration_extra, [])
        if isinstance(integration_extra, str)
        else []
    )
    integrated_dependencies = (
        integrated_dependencies if isinstance(integrated_dependencies, list) else []
    )
    package_version = _package_version(root / "src/simplicio_fast/__init__.py")
    _check(
        checks,
        "package_version",
        isinstance(version, str) and version == package_version,
        expected=version,
        observed=package_version,
    )

    try:
        readme = (root / "README.md").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        readme = ""
    version_badge = f"version-{version}-" if isinstance(version, str) else ""
    _check(
        checks,
        "readme_version",
        bool(version_badge)
        and version_badge in readme
        and f"Version {version}" in readme,
        expected=version,
    )
    try:
        changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        changelog = ""
    _check(
        checks,
        "changelog_version",
        isinstance(version, str) and f"## {version} " in changelog,
        expected=version,
    )
    dependency_count = len(dependencies)
    integrated_count = len(integrated_dependencies)
    _check(
        checks,
        "readme_dependencies",
        f"core_runtime_dependencies-{dependency_count}-" in readme
        and f"{dependency_count} core runtime dependencies" in readme
        and f"integrated_extra_dependencies-{integrated_count}-" in readme
        and f"{integrated_count} integrated extra dependencies" in readme,
        expected={"core": dependency_count, "integrated": integrated_count},
    )

    expected_branch = policy.get("default_branch")
    observed_branch, branch_reason = _remote_default_branch(root)
    branch_ok = isinstance(expected_branch, str) and (
        observed_branch == expected_branch or observed_branch is None
    )
    _check(
        checks,
        "default_branch_policy",
        branch_ok,
        expected=expected_branch,
        observed=observed_branch,
        reason=branch_reason,
    )

    failures = [item["name"] for item in checks if item["status"] != "pass"]
    return {
        "schema": SCHEMA,
        "status": "pass" if not failures else "fail",
        "root": str(root),
        "version": version,
        "runtime_dependencies": dependencies,
        "integrated_dependencies": integrated_dependencies,
        "checks": checks,
        "failures": failures,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    receipt = evaluate(args.root)
    if args.json:
        print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    else:
        print(f"{receipt['status']}: release integrity")
        for item in receipt["checks"]:
            print(f"{item['status']:>4} {item['name']}")
    return int(args.check and receipt["status"] != "pass")


if __name__ == "__main__":
    raise SystemExit(main())
