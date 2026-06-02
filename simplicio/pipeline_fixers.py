"""Mechanical fixes for common verify-loop failures."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
import sys
from typing import Callable, Iterable


Runner = Callable[..., subprocess.CompletedProcess]


@dataclass
class FixerResult:
    fixer: str
    applied: bool
    details: str


class StaticFixer(ABC):
    name: str
    pattern: re.Pattern[str]

    def matches(self, log: str) -> bool:
        return bool(self.pattern.search(log or ""))

    @abstractmethod
    def try_fix(self, log: str, project_dir: Path, runner: Runner | None = None) -> FixerResult:
        raise NotImplementedError


def _run(argv: list[str], project_dir: Path, runner: Runner | None, timeout: int = 120) -> subprocess.CompletedProcess:
    run = runner or subprocess.run
    return run(
        argv,
        cwd=str(project_dir),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _ok(result: subprocess.CompletedProcess) -> bool:
    return getattr(result, "returncode", 1) == 0


def _safe_python_package(raw: str) -> str | None:
    candidate = raw.strip().split(".", 1)[0].replace("_", "-")
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", candidate):
        return candidate
    return None


def _safe_node_package(raw: str) -> str | None:
    spec = raw.strip()
    if not spec or spec.startswith((".", "/", "\\")):
        return None
    parts = spec.split("/")
    if spec.startswith("@") and len(parts) >= 2:
        candidate = "/".join(parts[:2])
    else:
        candidate = parts[0]
    if re.fullmatch(r"(@[A-Za-z0-9._-]+/[A-Za-z0-9._-]+|[A-Za-z0-9._-]+)", candidate):
        return candidate
    return None


def _safe_go_module(raw: str) -> str | None:
    spec = raw.strip().strip('"').strip("'")
    if not spec or spec.startswith((".", "/", "\\")):
        return None
    # Go import paths look like host/owner/repo; require a dot or slash so a
    # bare standard-library name (already shipped with the toolchain) is never
    # passed to `go get`.
    if "." not in spec.split("/", 1)[0] and "/" not in spec:
        return None
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._~/-]*", spec):
        return spec
    return None


_RUST_STD_MODULES = {"crate", "self", "super", "std", "core", "alloc"}


def _safe_cargo_crate(raw: str) -> str | None:
    candidate = raw.strip().strip("`")
    if not candidate or candidate in _RUST_STD_MODULES:
        return None
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", candidate):
        return candidate
    return None


def _dependency_name(spec: str) -> str:
    name = re.split(r"\s*(?:[<>=!~]=?|;|\[)", spec.strip(), maxsplit=1)[0]
    return name.replace("_", "-").lower()


def _declares_dependency(lines: Iterable[str], package: str) -> bool:
    wanted = package.replace("_", "-").lower()
    for line in lines:
        for dep in re.findall(r'"([^"]+)"|\'([^\']+)\'', line):
            value = dep[0] or dep[1]
            if _dependency_name(value) == wanted:
                return True
    return False


def _find_project_section(lines: list[str]) -> tuple[int, int] | None:
    start = None
    for idx, line in enumerate(lines):
        if line.strip() == "[project]":
            start = idx
            break
    if start is None:
        return None
    end = len(lines)
    for idx in range(start + 1, len(lines)):
        stripped = lines[idx].strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            end = idx
            break
    return start, end


def _add_pyproject_dependency(pyproject: Path, package: str) -> bool:
    if not pyproject.exists():
        pyproject.write_text(
            f'[project]\ndependencies = [\n  "{package}",\n]\n',
            encoding="utf-8",
        )
        return True

    original = pyproject.read_text(encoding="utf-8")
    lines = original.splitlines()
    section = _find_project_section(lines)
    if section is None:
        addition = ["", "[project]", "dependencies = [", f'  "{package}",', "]"]
        pyproject.write_text(original.rstrip() + "\n" + "\n".join(addition) + "\n", encoding="utf-8")
        return True

    start, end = section
    project_lines = lines[start:end]
    if _declares_dependency(project_lines, package):
        return False

    dep_idx = None
    for idx in range(start + 1, end):
        if re.match(r"\s*dependencies\s*=\s*\[", lines[idx]):
            dep_idx = idx
            break

    if dep_idx is None:
        insertion = ["dependencies = [", f'  "{package}",', "]"]
        lines[start + 1:start + 1] = insertion
        pyproject.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return True

    if "]" in lines[dep_idx]:
        before, after = lines[dep_idx].split("[", 1)
        body, _closing = after.split("]", 1)
        existing = [item.strip() for item in body.split(",") if item.strip()]
        existing.append(f'"{package}"')
        lines[dep_idx] = before + "[" + ", ".join(existing) + "]"
        pyproject.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return True

    close_idx = None
    for idx in range(dep_idx + 1, end):
        if lines[idx].strip() == "]":
            close_idx = idx
            break
    if close_idx is None:
        return False

    indent = re.match(r"^(\s*)", lines[close_idx - 1] if close_idx > dep_idx + 1 else "  ").group(1)
    item_indent = indent or "  "
    lines.insert(close_idx, f'{item_indent}"{package}",')
    pyproject.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return True


class MissingPipPackageFixer(StaticFixer):
    name = "missing-pip-package"
    pattern = re.compile(r"ModuleNotFoundError:\s+No module named ['\"]([^'\"]+)['\"]", re.I)

    def try_fix(self, log: str, project_dir: Path, runner: Runner | None = None) -> FixerResult:
        match = self.pattern.search(log or "")
        package = _safe_python_package(match.group(1)) if match else None
        if not package:
            return FixerResult(self.name, False, "no safe Python package found")

        try:
            result = _run([sys.executable, "-m", "pip", "install", package], project_dir, runner)
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            return FixerResult(self.name, False, f"pip install failed: {exc}")
        if not _ok(result):
            tail = ((result.stdout or "") + (result.stderr or ""))[-400:]
            return FixerResult(self.name, False, f"pip install {package} failed: {tail}")
        pyproject = project_dir / "pyproject.toml"
        changed = _add_pyproject_dependency(pyproject, package)
        action = "added to pyproject.toml and installed" if changed else "already declared; installed"
        return FixerResult(self.name, True, f"{action} {package}")


class MissingNpmPackageFixer(StaticFixer):
    name = "missing-npm-package"
    pattern = re.compile(
        r"(?:Cannot find module|Module not found:\s+Can't resolve)\s+['\"]([^'\"]+)['\"]",
        re.I,
    )

    def try_fix(self, log: str, project_dir: Path, runner: Runner | None = None) -> FixerResult:
        match = self.pattern.search(log or "")
        package = _safe_node_package(match.group(1)) if match else None
        if not package:
            return FixerResult(self.name, False, "no safe npm package found")

        package_manager = _detect_package_manager(project_dir)
        argv = _package_install_command(package_manager, package)
        try:
            result = _run(argv, project_dir, runner)
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            return FixerResult(self.name, False, f"{package_manager} install failed: {exc}")
        if not _ok(result):
            tail = ((result.stdout or "") + (result.stderr or ""))[-400:]
            return FixerResult(self.name, False, f"{package_manager} install {package} failed: {tail}")
        return FixerResult(self.name, True, f"installed {package} with {package_manager}")


def _detect_package_manager(project_dir: Path) -> str:
    if (project_dir / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (project_dir / "yarn.lock").exists():
        return "yarn"
    return "npm"


def _package_install_command(package_manager: str, package: str) -> list[str]:
    if package_manager == "npm":
        return ["npm", "install", package]
    return [package_manager, "add", package]


class MissingGoModuleFixer(StaticFixer):
    name = "missing-go-module"
    pattern = re.compile(
        r"(?:no required module provides package|cannot find package)\s+[\"']?"
        r"([A-Za-z0-9][A-Za-z0-9._~/-]*)",
        re.I,
    )

    def try_fix(self, log: str, project_dir: Path, runner: Runner | None = None) -> FixerResult:
        match = self.pattern.search(log or "")
        module = _safe_go_module(match.group(1)) if match else None
        if not module:
            return FixerResult(self.name, False, "no safe Go module found")

        try:
            result = _run(["go", "get", module], project_dir, runner)
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            return FixerResult(self.name, False, f"go get failed: {exc}")
        if not _ok(result):
            tail = ((result.stdout or "") + (result.stderr or ""))[-400:]
            return FixerResult(self.name, False, f"go get {module} failed: {tail}")
        return FixerResult(self.name, True, f"go get {module} (go.mod updated)")


class MissingCargoCrateFixer(StaticFixer):
    name = "missing-cargo-crate"
    pattern = re.compile(
        r"(?:use of undeclared crate or module|maybe a missing crate)\s+`([A-Za-z0-9_][A-Za-z0-9_-]*)`",
        re.I,
    )

    def try_fix(self, log: str, project_dir: Path, runner: Runner | None = None) -> FixerResult:
        match = self.pattern.search(log or "")
        crate = _safe_cargo_crate(match.group(1)) if match else None
        if not crate:
            return FixerResult(self.name, False, "no safe Cargo crate found")

        try:
            result = _run(["cargo", "add", crate], project_dir, runner)
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            return FixerResult(self.name, False, f"cargo add failed: {exc}")
        if not _ok(result):
            tail = ((result.stdout or "") + (result.stderr or ""))[-400:]
            return FixerResult(self.name, False, f"cargo add {crate} failed: {tail}")
        return FixerResult(self.name, True, f"cargo add {crate} (Cargo.toml updated)")


class RuffFormatFixer(StaticFixer):
    name = "ruff-format"
    pattern = re.compile(r"\b(?:SyntaxError|IndentationError)\b", re.I)

    def try_fix(self, log: str, project_dir: Path, runner: Runner | None = None) -> FixerResult:
        if not self.matches(log):
            return FixerResult(self.name, False, "no syntax or indentation failure found")
        target = _python_error_target(log, project_dir)
        if target is None:
            return FixerResult(self.name, False, "could not identify a Python target file")

        rel_target = str(target.relative_to(project_dir.resolve()))
        try:
            format_result = _run(["ruff", "format", rel_target], project_dir, runner, timeout=60)
            check_result = _run(["ruff", "check", "--fix", rel_target], project_dir, runner, timeout=60)
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            return FixerResult(self.name, False, f"ruff failed: {exc}")
        if _ok(format_result) and _ok(check_result):
            return FixerResult(self.name, True, f"ran ruff format and ruff check --fix on {rel_target}")
        tail = (
            (format_result.stdout or "")
            + (format_result.stderr or "")
            + (check_result.stdout or "")
            + (check_result.stderr or "")
        )[-400:]
        return FixerResult(self.name, False, f"ruff could not fix {rel_target}: {tail}")


def _python_error_target(log: str, project_dir: Path) -> Path | None:
    candidates = []
    candidates.extend(re.findall(r'File "([^"]+\.py)", line \d+', log or ""))
    candidates.extend(re.findall(r"(^|\s)([^\s:]+\.py):\d+(?::\d+)?", log or "", flags=re.M))
    for candidate in candidates:
        raw = candidate[-1] if isinstance(candidate, tuple) else candidate
        path = Path(raw)
        if not path.is_absolute():
            path = project_dir / path
        try:
            resolved = path.resolve()
            root = project_dir.resolve()
            resolved.relative_to(root)
        except (OSError, ValueError):
            continue
        if resolved.suffix == ".py" and resolved.exists():
            return resolved
    return None


STATIC_FIXERS: list[StaticFixer] = [
    MissingPipPackageFixer(),
    MissingNpmPackageFixer(),
    MissingGoModuleFixer(),
    MissingCargoCrateFixer(),
    RuffFormatFixer(),
]


def try_static_fixers(log: str, project_dir: str | Path, runner: Runner | None = None) -> FixerResult:
    root = Path(project_dir)
    for fixer in STATIC_FIXERS:
        if not fixer.matches(log):
            continue
        result = fixer.try_fix(log, root, runner=runner)
        if result.applied:
            return result
        return result
    return FixerResult("none", False, "no static fixer matched")
