import json
from pathlib import Path
import subprocess
import sys
import tomllib

import pytest


ROOT = Path(__file__).resolve().parents[1]
PROJECT_VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
    "project"
]["version"]


def _probe(expression: str) -> dict[str, object]:
    result = subprocess.run(
        [sys.executable, "-c", expression],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
        env={"PYTHONPATH": str(ROOT / "src")},
    )
    return json.loads(result.stdout)


def test_package_import_does_not_load_heavy_implementations():
    receipt = _probe(
        "import json,sys,simplicio_fast;"
        "print(json.dumps({'version':simplicio_fast.__version__,"
        "'loaded':sorted(name for name in sys.modules "
        "if name.startswith('simplicio_fast.'))}))"
    )
    assert receipt == {"version": PROJECT_VERSION, "loaded": []}


@pytest.mark.parametrize(
    "symbol,module",
    [
        ("PrismArena", "simplicio_fast.prism_arena"),
        ("RuntimeFastBackend", "simplicio_fast.runtime_backend"),
        ("WorkspaceStore", "simplicio_fast.workspace"),
    ],
)
def test_public_symbols_load_only_their_own_dependency_path(symbol, module):
    receipt = _probe(
        "import json,sys,simplicio_fast;"
        f"getattr(simplicio_fast,{symbol!r});"
        "print(json.dumps({'loaded':sorted(name for name in sys.modules "
        "if name.startswith('simplicio_fast.'))}))"
    )
    assert module in receipt["loaded"]


def test_unknown_attribute_remains_fail_closed():
    import simplicio_fast

    with pytest.raises(AttributeError):
        simplicio_fast.not_a_public_contract
