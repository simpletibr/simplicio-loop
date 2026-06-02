import subprocess
import sys

from simplicio.pipeline_fixers import (
    MissingCargoCrateFixer,
    MissingGoModuleFixer,
    MissingNpmPackageFixer,
    MissingPipPackageFixer,
    RuffFormatFixer,
    try_static_fixers,
)


def _ok(argv):
    return subprocess.CompletedProcess(argv, 0, "", "")


def test_missing_pip_package_fixer_updates_pyproject_and_installs(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "demo"\ndependencies = [\n  "httpx>=0.27",\n]\n',
        encoding="utf-8",
    )
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return _ok(argv)

    result = MissingPipPackageFixer().try_fix(
        "ModuleNotFoundError: No module named 'fastapi'",
        tmp_path,
        runner=fake_run,
    )

    assert result.applied is True
    assert result.fixer == "missing-pip-package"
    assert '"fastapi",' in pyproject.read_text(encoding="utf-8")
    assert calls[0][0] == [sys.executable, "-m", "pip", "install", "fastapi"]


def test_missing_pip_package_fixer_rejects_unsafe_package(tmp_path):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return _ok(argv)

    result = MissingPipPackageFixer().try_fix(
        "ModuleNotFoundError: No module named '../secret'",
        tmp_path,
        runner=fake_run,
    )

    assert result.applied is False
    assert calls == []


def test_missing_npm_package_fixer_detects_pnpm_and_installs_package(tmp_path):
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    (tmp_path / "pnpm-lock.yaml").write_text("", encoding="utf-8")
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return _ok(argv)

    result = MissingNpmPackageFixer().try_fix(
        "Error: Cannot find module '@radix-ui/react-dialog/dist/index.js'",
        tmp_path,
        runner=fake_run,
    )

    assert result.applied is True
    assert result.fixer == "missing-npm-package"
    assert calls[0][0] == ["pnpm", "add", "@radix-ui/react-dialog"]


def test_ruff_format_fixer_runs_format_and_fix_on_python_target(tmp_path):
    target = tmp_path / "src" / "bad.py"
    target.parent.mkdir()
    target.write_text("def broken():\nprint('x')\n", encoding="utf-8")
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        if argv[:2] == ["ruff", "format"]:
            target.write_text("def broken():\n    print('x')\n", encoding="utf-8")
        return _ok(argv)

    result = RuffFormatFixer().try_fix(
        'IndentationError: expected an indented block\n  File "src/bad.py", line 2',
        tmp_path,
        runner=fake_run,
    )

    normalized = [[part.replace("\\", "/") for part in call[0]] for call in calls]
    assert result.applied is True
    assert normalized == [
        ["ruff", "format", "src/bad.py"],
        ["ruff", "check", "--fix", "src/bad.py"],
    ]
    assert "    print" in target.read_text(encoding="utf-8")


def test_missing_go_module_fixer_runs_go_get(tmp_path):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return _ok(argv)

    result = MissingGoModuleFixer().try_fix(
        "main.go:5:2: no required module provides package "
        "github.com/gin-gonic/gin; to add it:",
        tmp_path,
        runner=fake_run,
    )

    assert result.applied is True
    assert result.fixer == "missing-go-module"
    assert calls[0][0] == ["go", "get", "github.com/gin-gonic/gin"]


def test_missing_go_module_fixer_rejects_stdlib_and_unsafe(tmp_path):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return _ok(argv)

    result = MissingGoModuleFixer().try_fix(
        'cannot find package "../secret"',
        tmp_path,
        runner=fake_run,
    )

    assert result.applied is False
    assert calls == []


def test_missing_cargo_crate_fixer_runs_cargo_add(tmp_path):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return _ok(argv)

    result = MissingCargoCrateFixer().try_fix(
        "error[E0433]: failed to resolve: use of undeclared crate or module `serde_json`",
        tmp_path,
        runner=fake_run,
    )

    assert result.applied is True
    assert result.fixer == "missing-cargo-crate"
    assert calls[0][0] == ["cargo", "add", "serde_json"]


def test_missing_cargo_crate_fixer_rejects_std_module(tmp_path):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return _ok(argv)

    result = MissingCargoCrateFixer().try_fix(
        "error[E0433]: failed to resolve: use of undeclared crate or module `std`",
        tmp_path,
        runner=fake_run,
    )

    assert result.applied is False
    assert calls == []


def test_try_static_fixers_dispatches_go_and_cargo(tmp_path):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return _ok(argv)

    go_result = try_static_fixers(
        "no required module provides package github.com/google/uuid",
        tmp_path,
        runner=fake_run,
    )
    cargo_result = try_static_fixers(
        "use of undeclared crate or module `tokio`",
        tmp_path,
        runner=fake_run,
    )

    assert go_result.fixer == "missing-go-module"
    assert cargo_result.fixer == "missing-cargo-crate"
    assert ["go", "get", "github.com/google/uuid"] in calls
    assert ["cargo", "add", "tokio"] in calls


def test_try_static_fixers_returns_clear_no_match(tmp_path):
    result = try_static_fixers("AssertionError: expected 200 got 201", tmp_path)

    assert result.applied is False
    assert result.fixer == "none"
