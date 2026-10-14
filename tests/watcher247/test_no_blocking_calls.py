"""Guard (#1548): the 24/7 watcher is asyncio-native, so no module under watcher247/ may block the event loop.

A call to subprocess.run/Popen/check_output/check_call/call, time.sleep, requests.* or urllib.request.urlopen is
refused unless (file, function) is in ALLOWED with the reason it is safe. Subprocesses go through `proc.run`;
HTTP and blocking file work go through `asyncio.to_thread`. AST only: nothing is imported.
"""
import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2] / "simplicio_loop" / "watcher247"
FORBIDDEN = {
    "subprocess.run", "subprocess.Popen", "subprocess.check_output", "subprocess.check_call", "subprocess.call",
    "time.sleep", "urllib.request.urlopen", "os.system",
}
ALLOWED = {
    ("subscription.py", "_http_json_sync"): "runs only in a worker thread: http_json calls it through asyncio.to_thread",
}


def _aliases(tree: ast.Module) -> dict[str, str]:
    """local name -> dotted module path, for `import x.y as z` and `from x import y as z`."""
    names: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names[alias.asname or alias.name.split(".")[0]] = alias.name if alias.asname else alias.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for alias in node.names:
                names[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return names


def _dotted(func: ast.expr, aliases: dict[str, str]) -> str | None:
    parts: list[str] = []
    while isinstance(func, ast.Attribute):
        parts.append(func.attr)
        func = func.value
    if not isinstance(func, ast.Name):
        return None
    return ".".join([aliases.get(func.id, func.id), *reversed(parts)])


def _is_blocking(dotted: str | None) -> bool:
    return dotted is not None and (dotted in FORBIDDEN or dotted.startswith("requests."))


class _Finder(ast.NodeVisitor):
    def __init__(self, aliases: dict[str, str]) -> None:
        self.aliases = aliases
        self.scope: list[str] = []
        self.found: list[tuple[str, int, str]] = []  # (function, line, call)

    def _enter(self, node) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    visit_FunctionDef = visit_AsyncFunctionDef = _enter

    def visit_Call(self, node: ast.Call) -> None:
        dotted = _dotted(node.func, self.aliases)
        if _is_blocking(dotted):
            self.found.append((self.scope[0] if self.scope else "<module>", node.lineno, dotted))
        self.generic_visit(node)


def blocking_calls(source: str) -> list[tuple[str, int, str]]:
    tree = ast.parse(source)
    finder = _Finder(_aliases(tree))
    finder.visit(tree)
    return finder.found


def _violations(files: dict[str, str]) -> list[str]:
    return [f"{rel}:{line} {function}() calls {call}" for rel, source in files.items()
            for function, line, call in blocking_calls(source) if (rel, function) not in ALLOWED]


def _watcher_sources() -> dict[str, str]:
    return {path.relative_to(ROOT).as_posix(): path.read_text(encoding="utf-8") for path in sorted(ROOT.rglob("*.py"))}


def test_the_watcher_makes_no_blocking_calls_outside_the_allowlist():
    assert _violations(_watcher_sources()) == [], (
        "a blocking call stalls the whole tick: use proc.run (subprocess) or asyncio.to_thread, "
        "or add (file, function) to ALLOWED with the reason it is safe")


def test_every_allowlist_entry_is_still_needed():
    sources = _watcher_sources()
    used = {(rel, function) for rel, source in sources.items() for function, _, _ in blocking_calls(source)}
    assert set(ALLOWED) <= used, f"stale allowlist entries: {sorted(set(ALLOWED) - used)}"
    assert all(reason.strip() for reason in ALLOWED.values())


@pytest.mark.parametrize("source", [
    "import subprocess\ndef f():\n    subprocess.run(['x'])\n",
    "import subprocess as sp\nasync def f():\n    sp.check_output(['x'])\n",
    "from subprocess import Popen\ndef f():\n    Popen(['x'])\n",
    "import subprocess\nsubprocess.call(['x'])\n",
    "import time\nasync def f():\n    time.sleep(1)\n",
    "from time import sleep as nap\nasync def f():\n    nap(1)\n",
    "import requests\ndef f():\n    requests.get('http://x')\n",
    "import urllib.request\ndef f():\n    urllib.request.urlopen('http://x')\n",
    "from urllib import request\ndef f():\n    request.urlopen('http://x')\n",
    "from urllib.request import urlopen\ndef f():\n    urlopen('http://x')\n",
])
def test_the_guard_catches_each_blocking_shape(source):
    assert _violations({"new_module.py": source}), source


def test_the_guard_allows_the_async_forms():
    assert _violations({"ok.py": (
        "import asyncio\nimport subprocess\nfrom . import proc\n"
        "async def f():\n    await proc.run(['x'])\n    await asyncio.sleep(1)\n    await asyncio.to_thread(len, 'x')\n"
        "def g() -> subprocess.CompletedProcess:\n    return subprocess.CompletedProcess([], 0)\n"
        "async def h():\n    return await asyncio.create_subprocess_exec('x')\n")}) == []
