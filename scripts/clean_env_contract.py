#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
PYPROJECT = REPO / "pyproject.toml"
CLI = REPO / "simplicio_loop" / "cli.py"
BUNDLE_ROOT = REPO / "simplicio_loop" / "_bundle"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _parse_pyproject_contract(text: str) -> dict:
    dep_match = re.search(r'(?ms)^\s*dependencies\s*=\s*\[(.*?)\]', text)
    deps = re.findall(r'"([^"]+)"', dep_match.group(1)) if dep_match else []
    script_match = re.search(r'(?m)^\s*simplicio-loop\s*=\s*"([^"]+)"', text)
    package_data_match = re.search(r'(?m)^\s*simplicio_loop\s*=\s*\[(.*?)\]', text)
    package_data = re.findall(r'"([^"]+)"', package_data_match.group(1)) if package_data_match else []
    requires_python = re.search(r'(?m)^\s*requires-python\s*=\s*"([^"]+)"', text)
    return {
        "dependencies": deps,
        "script_entrypoint": script_match.group(1) if script_match else "",
        "package_data": package_data,
        "requires_python": requires_python.group(1) if requires_python else "",
    }


def evaluate_contract() -> dict:
    text = _read(PYPROJECT)
    meta = _parse_pyproject_contract(text)
    checks = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    add("pyproject.exists", PYPROJECT.exists(), str(PYPROJECT))
    add("dependency.no_external_operators",
        not any(dep.startswith(("simplicio-cli", "simplicio-mapper")) for dep in meta["dependencies"]),
        "mapper and dev-cli are bundled; no simplicio-cli/simplicio-mapper dependency")
    add("entrypoint.cli", meta["script_entrypoint"] == "simplicio_loop.cli:main",
        meta["script_entrypoint"] or "missing")
    add("package_data.bundle", "_bundle/**/*" in meta["package_data"], ", ".join(meta["package_data"]) or "missing")
    add("cli.module.exists", CLI.exists(), str(CLI))
    add("bundle.root.exists", BUNDLE_ROOT.exists(), str(BUNDLE_ROOT))
    add("bundle.skill.exists", (BUNDLE_ROOT / "skills" / "simplicio-loop" / "SKILL.md").exists(),
        str(BUNDLE_ROOT / "skills" / "simplicio-loop" / "SKILL.md"))
    add(
        "python.requires_311",
        meta["requires_python"].startswith(">=3.11"),
        meta["requires_python"] or "missing",
    )

    ok = all(item["ok"] for item in checks)
    return {"ok": ok, "checks": checks}


def cmd_check(_args: list[str]) -> int:
    payload = evaluate_contract()
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 1


def cmd_selftest(_args: list[str]) -> int:
    payload = evaluate_contract()
    assert any(row["name"] == "entrypoint.cli" and row["ok"] for row in payload["checks"])
    assert any(row["name"] == "bundle.skill.exists" and row["ok"] for row in payload["checks"])
    print("selftest: PASS clean-env-contract")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(argv or sys.argv[1:])
    if not argv or argv[0] not in {"check", "selftest"}:
        print("unknown command '%s'. choices: check selftest" % (argv[0] if argv else ""))
        return 2
    if argv[0] == "check":
        return cmd_check(argv[1:])
    return cmd_selftest(argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
