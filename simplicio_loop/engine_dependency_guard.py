"""Static dependency firewall for the canonical Python Loop engine."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

SCHEMA = "simplicio.loop-engine-dependency-firewall/v1"
STANDALONE_SCHEMA = "simplicio.loop-engine-standalone-proof/v1"
FORBIDDEN_PREFIXES = (
    "simplicio_runtime",
    "simplicio_runtime_internal",
)


@dataclass(frozen=True)
class DependencyViolation:
    path: str
    line: int
    module: str

    def to_dict(self) -> dict[str, object]:
        return {"path": self.path, "line": self.line, "module": self.module}


def _module_name(node: ast.AST) -> str:
    if isinstance(node, ast.Import):
        return ",".join(alias.name for alias in node.names)
    if isinstance(node, ast.ImportFrom):
        return "." * node.level + (node.module or "")
    return ""


def scan_core_imports(package_root: str | Path) -> tuple[DependencyViolation, ...]:
    """Return forbidden Runtime/internal imports found under one core package."""
    root = Path(package_root).resolve()
    if not root.is_dir():
        raise ValueError(f"core package does not exist: {root}")
    violations: list[DependencyViolation] = []
    for path in sorted(root.rglob("*.py")):
        if any(part in {"__pycache__", "_bundle"} for part in path.parts):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError) as exc:
            raise ValueError(f"cannot parse core module {path}: {exc}") from exc
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            module = _module_name(node)
            if any(module == prefix or module.startswith(prefix + ".")
                   for prefix in FORBIDDEN_PREFIXES):
                violations.append(DependencyViolation(
                    path=path.relative_to(root).as_posix(), line=int(node.lineno), module=module,
                ))
    return tuple(violations)


def assert_core_dependency_firewall(package_root: str | Path) -> None:
    violations = scan_core_imports(package_root)
    if violations:
        details = "; ".join(
            f"{item.path}:{item.line} imports {item.module}" for item in violations
        )
        raise RuntimeError(f"{SCHEMA} violation: {details}")


def standalone_import_proof(
    package_root: str | Path,
    modules: Sequence[str] = (
        "simplicio_loop.engine_boundary",
        "simplicio_loop.engine_router",
        "simplicio_loop.engine_dependency_guard",
        "simplicio_loop.prism_scheduler",
        "simplicio_loop.prism_reducer",
        "simplicio_loop.delivery",
    ),
) -> dict[str, Any]:
    """Import the canonical Python path in a child process without Runtime.

    The child process installs an import blocker before loading the modules and
    reports any forbidden modules that nevertheless appear in ``sys.modules``.
    This is intentionally a process-level proof: a static AST scan cannot
    detect an indirect import or a packaging/environment leak.
    """
    root = Path(package_root).resolve()
    if not root.is_dir():
        raise ValueError(f"core package does not exist: {root}")
    assert_core_dependency_firewall(root)
    requested = tuple(dict.fromkeys(str(module) for module in modules))
    if not requested:
        raise ValueError("at least one module is required")
    script = r'''
import importlib
import json
import sys

FORBIDDEN = ("simplicio_runtime", "simplicio_runtime_internal")

class RuntimeImportBlocker:
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == name or fullname.startswith(name + ".") for name in FORBIDDEN):
            raise ImportError("standalone proof blocked forbidden module: " + fullname)
        return None

sys.meta_path.insert(0, RuntimeImportBlocker())
modules = json.loads(sys.argv[1])
loaded = []
try:
    for name in modules:
        importlib.import_module(name)
        loaded.append(name)
    forbidden_loaded = sorted(
        name for name in sys.modules
        if any(name == prefix or name.startswith(prefix + ".") for prefix in FORBIDDEN)
    )
    print(json.dumps({"ok": not forbidden_loaded, "loaded": loaded,
                      "forbidden_loaded": forbidden_loaded}, sort_keys=True))
except Exception as exc:
    print(json.dumps({"ok": False, "loaded": loaded, "forbidden_loaded": [],
                      "error": f"{type(exc).__name__}: {exc}"}, sort_keys=True))
    raise
'''
    env = dict(os.environ)
    env["PYTHONPATH"] = str(root.parent)
    env["SIMPLICIO_EXECUTION_PROFILE"] = "standalone"
    result = subprocess.run(
        [sys.executable, "-c", script, json.dumps(list(requested))],
        cwd=str(root.parent), env=env, stdin=subprocess.DEVNULL,
        capture_output=True, text=True, check=False,
    )
    raw = result.stdout.strip().splitlines()
    child = json.loads(raw[-1]) if raw and raw[-1].startswith("{") else {
        "ok": False, "loaded": [], "forbidden_loaded": [],
        "error": (result.stderr.strip() or "standalone probe produced no receipt"),
    }
    payload: dict[str, Any] = {
        "schema": STANDALONE_SCHEMA,
        "status": "PASS" if result.returncode == 0 and child.get("ok") else "FAIL",
        "package_root": str(root),
        "modules": list(requested),
        "loaded_modules": child.get("loaded", []),
        "forbidden_modules_loaded": child.get("forbidden_loaded", []),
        "runtime_import_blocked": True,
        "error": child.get("error"),
    }
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    payload["receipt_hash"] = "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()
    return payload


__all__ = [
    "SCHEMA", "FORBIDDEN_PREFIXES", "DependencyViolation",
    "scan_core_imports", "assert_core_dependency_firewall", "standalone_import_proof",
]
