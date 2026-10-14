"""What the daemon may run and what it imports ahead of time (issue #1590)."""
from __future__ import annotations

import ast
import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from simplicio_loop.daemon import protocol, runner

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(not protocol.supported(), reason="needs AF_UNIX, fork and fd passing")


def test_the_program_table_is_the_console_scripts_of_pyproject():
    scripts = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["scripts"]
    assert runner.PROGRAMS["simplicio-mapper"] == scripts["simplicio-mapper"]
    assert runner.PROGRAMS["simplicio-dev-cli"] == scripts["simplicio-dev-cli"]
    # the console script is the thin client; the daemon runs the command surface behind it
    assert scripts["simplicio-loop"] == "simplicio_loop.daemon.client:main"
    assert runner.PROGRAMS["simplicio-loop"] == "simplicio_loop.cli:main"


def test_every_operator_the_hot_path_forks_is_in_the_table():
    from simplicio_loop import operator_exec

    assert set(operator_exec.WARM.values()) <= set(runner.PROGRAMS)


_READS = {"environ", "getenv", "getcwd", "cwd", "gettempdir", "expanduser", "home", "getuid", "geteuid", "getlogin",
          "gethostname", "argv"}


def _reads_process_state(node: ast.AST) -> bool:
    for found in ast.walk(node):
        if isinstance(found, ast.Attribute) and found.attr in _READS:
            return True
        if isinstance(found, ast.Name) and found.id in {"getenv", "gettempdir"}:
            return True
    return False


def _import_time_statements(body):
    """Statements that run when the module is imported: module and class level, decorators, default values."""
    for node in body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield from node.decorator_list
            yield from node.args.defaults
            yield from (d for d in node.args.kw_defaults if d is not None)
        elif isinstance(node, ast.ClassDef):
            yield from node.decorator_list
            yield from _import_time_statements(node.body)
        elif isinstance(node, ast.If):
            is_main = isinstance(node.test, ast.Compare) and "__main__" in ast.dump(node.test)
            if not is_main:
                yield node.test
                yield from _import_time_statements(node.body + node.orelse)
        elif isinstance(node, (ast.Try, ast.With, ast.For, ast.While)):
            for part in ("body", "orelse", "finalbody"):
                yield from _import_time_statements(getattr(node, part, []))
            for handler in getattr(node, "handlers", []):
                yield from _import_time_statements(handler.body)
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            yield node
        elif isinstance(node, ast.Expr) and not isinstance(node.value, ast.Constant):
            yield node


def test_preloaded_modules_do_not_read_the_environment_or_cwd_when_imported():
    """The daemon imports once, with its own environment; a value taken then would reach every later command."""
    code = (
        "import importlib, json, sys\n"
        "from simplicio_loop.daemon import runner\n"
        "for spec in runner.PROGRAMS.values():\n"
        "    importlib.import_module(spec.partition(':')[0])\n"
        "for name in runner.PRELOAD:\n"
        "    importlib.import_module(name)\n"
        "roots = ('simplicio_loop', 'simplicio_mapper', 'simplicio')\n"
        "print(json.dumps(sorted({m.__file__ for n, m in sys.modules.items() if m and getattr(m, '__file__', None) and n.partition('.')[0] in roots})))\n"
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=180)
    assert done.returncode == 0, done.stderr
    offenders = []
    for name in json.loads(done.stdout.splitlines()[-1]):
        if not name.endswith(".py"):
            continue
        tree = ast.parse(Path(name).read_text(encoding="utf-8"))
        for node in _import_time_statements(tree.body):
            if _reads_process_state(node):
                offenders.append(f"{name}:{node.lineno}")
    assert not offenders, "read at import time, so the daemon would freeze the value of its first caller:\n" + "\n".join(offenders)


def test_warm_name_only_for_this_environment_inside_a_daemon_command(monkeypatch, tmp_path):
    import sysconfig

    from simplicio_loop import operator_exec

    scripts = Path(sysconfig.get_path("scripts"))
    mine, foreign = scripts / "simplicio-mapper", tmp_path / "bin" / "simplicio-mapper"
    monkeypatch.setattr(protocol, "CURRENT", protocol.Current("/run", "key"))
    assert operator_exec.warm_name(str(mine)) == "simplicio-mapper"
    assert operator_exec.warm_name(str(scripts / "simplicio-py")) == "simplicio-dev-cli"
    assert operator_exec.warm_name(str(foreign)) is None  # another installation of the operator
    assert operator_exec.warm_name(str(scripts / "git")) is None  # not an operator
    monkeypatch.setattr(protocol, "CURRENT", None)
    assert operator_exec.warm_name(str(mine)) is None  # not inside a command the daemon runs
