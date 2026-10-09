"""Entry shim of the standalone binary (issue #1576).

One executable answers to several program names, like the console scripts of the wheel:

* ``simplicio-loop`` (and any other name, for example the long release asset name);
* ``simplicio-mapper``, ``simplicio-dev-cli``, ``simplicio-cli``, ``simplicio-py``.

The loop starts these operators by name through ``PATH``. In a frozen build there is no
script directory, so ``prepare_environment`` makes a small per-user directory of links to
the executable and puts it first on ``PATH``. The links keep the program name in
``argv[0]``, and ``dispatch`` picks the entry point from that name. The entry points come from
the ``console_scripts`` of the packaged ``simplicio-loop`` metadata, so ``pyproject.toml``
stays the only list.

``simplicio-loop -m MODULE ...`` and ``simplicio-loop -c CODE ...`` run bundled code. The
bundled operators use ``sys.executable`` with these two flags.
"""
from __future__ import annotations

import hashlib
import importlib
import os
import re
import runpy
import shutil
import sys
from importlib import metadata
from pathlib import Path
from typing import Mapping, MutableMapping, Optional, Sequence

LOOP_NAME = "simplicio-loop"
OPERATOR_NAMES = ("simplicio-mapper", "simplicio-dev-cli", "simplicio-cli", "simplicio-py")
_SUFFIX = ".exe" if os.name == "nt" else ""


def program_name(argv0: str) -> str:
    """Return the program name in ``argv[0]``: no directory and no ``.exe`` suffix."""
    name = re.split(r"[\\/]", argv0)[-1].lower()
    return name[: -len(".exe")] if name.endswith(".exe") else name


def console_scripts() -> Mapping[str, str]:
    """Map each console script name to ``module:function`` from the packaged metadata."""
    entry_points = metadata.distribution(LOOP_NAME).entry_points
    return {entry.name: entry.value for entry in entry_points if entry.group == "console_scripts"}


def resolve_entry(name: str, scripts: Mapping[str, str]) -> str:
    """Return the entry point for a program name. An operator name selects the operator.

    Any other name is the loop, so the executable also works under its long release name.
    """
    return scripts[name] if name in OPERATOR_NAMES else scripts[LOOP_NAME]


def _call(spec: str) -> int:
    module, _, attribute = spec.partition(":")
    code = getattr(importlib.import_module(module), attribute)()
    return 0 if code is None else code


def dispatch(argv: Sequence[str], scripts: Optional[Mapping[str, str]] = None) -> int:
    """Run the program that ``argv[0]`` names, with ``sys.argv`` set like a console script."""
    name = program_name(argv[0]) if argv else LOOP_NAME
    args = list(argv[1:])
    if name not in OPERATOR_NAMES and len(args) >= 2 and args[0] in ("-m", "-c"):
        if args[0] == "-m":
            sys.argv = [args[1], *args[2:]]
            runpy.run_module(args[1], run_name="__main__", alter_sys=True)
        else:
            sys.argv = ["-c", *args[2:]]
            exec(compile(args[1], "<string>", "exec"), {"__name__": "__main__"})  # noqa: S102
        return 0
    sys.argv = [name, *args]
    return _call(resolve_entry(name, console_scripts() if scripts is None else scripts))


def _same_file(link: Path, executable: Path) -> bool:
    try:
        if os.path.samefile(link, executable):
            return True
        if link.is_symlink():
            return False
        a, b = link.stat(), executable.stat()
        return (a.st_size, a.st_mtime_ns) == (b.st_size, b.st_mtime_ns)  # a copy made by copy2
    except OSError:
        return False


def _link(link: Path, executable: Path) -> None:
    if _same_file(link, executable):
        return
    temporary = link.with_name(f".{link.name}.{os.getpid()}.tmp")
    temporary.unlink(missing_ok=True)
    for make in (os.symlink, os.link, shutil.copy2):  # Windows may refuse the first two
        try:
            make(executable, temporary)
            break
        except OSError:
            temporary.unlink(missing_ok=True)
    else:
        raise OSError(f"cannot link {link} to {executable}")
    os.replace(temporary, link)


def ensure_operator_dir(executable: os.PathLike[str] | str, home: Path) -> Path:
    """Make ``<home>/.simplicio-loop/bin/<key>/`` hold one link per operator name.

    The key comes from the executable path. A new binary at the same path (an update) keeps
    the same links. Links that point elsewhere are repaired. Links that are right stay as they are.
    """
    path = Path(os.path.abspath(executable))
    key = hashlib.sha256(os.fspath(path).encode()).hexdigest()[:12]
    directory = home / ".simplicio-loop" / "bin" / key
    directory.mkdir(parents=True, exist_ok=True)
    for name in OPERATOR_NAMES:
        _link(directory / (name + _SUFFIX), path)
    return directory


def prepare_environment(
    executable: os.PathLike[str] | str, environ: MutableMapping[str, str], home: Path
) -> Path:
    """Put the operator links first on ``environ['PATH']``. Child processes inherit them."""
    directory = ensure_operator_dir(executable, home)
    parts = [part for part in environ.get("PATH", "").split(os.pathsep) if part]
    if not parts or parts[0] != os.fspath(directory):
        environ["PATH"] = os.pathsep.join([os.fspath(directory), *parts])
    return directory


def main(argv: Optional[Sequence[str]] = None) -> int:
    if getattr(sys, "frozen", False):
        prepare_environment(sys.executable, os.environ, Path.home())
    return dispatch(sys.argv if argv is None else list(argv))
