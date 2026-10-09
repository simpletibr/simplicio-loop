"""Entry shim of the standalone binary (issue #1576).

One executable answers to several program names, like the console scripts of the wheel:

* ``simplicio-loop`` (and any other name, for example the long release asset name);
* ``simplicio-mapper``, ``simplicio-dev-cli``, ``simplicio-cli``, ``simplicio-py``.

The loop starts these operators, and itself, by name through ``PATH``. In a frozen build there
is no script directory, so ``prepare_environment`` makes a small per-user directory of links to
the executable and puts it first on ``PATH``. That directory is first on ``PATH``, so it must be
private: ``ensure_operator_dir`` refuses a link, a directory of another user, or any level that
the group or others can write, and then ``prepare_environment`` uses a new temporary directory.
The links keep the program name in ``argv[0]``, and ``dispatch`` picks the entry point from that
name. The entry points come from the ``console_scripts`` of the packaged ``simplicio-loop``
metadata, so ``pyproject.toml`` stays the only list.

The bundled programs start themselves through ``sys.executable``: the dashboard server is
``sys.executable -m simplicio_loop.dashboard.server``. ``adjust_child_environment`` marks such a child
with ``SIMPLICIO_LOOP_SELF_SPAWN``. Only a marked process runs ``-m MODULE``, ``-c CODE`` and ``FILE.py``
like python does. Without the mark, ``simplicio-loop fix.py`` is a task and never runs the file.
"""
from __future__ import annotations

import atexit
import hashlib
import importlib
import os
import re
import runpy
import shutil
import stat
import subprocess
import sys
import tempfile
from importlib import metadata
from pathlib import Path
from typing import Mapping, MutableMapping, Optional, Sequence

LOOP_NAME = "simplicio-loop"
OPERATOR_NAMES = ("simplicio-mapper", "simplicio-dev-cli", "simplicio-cli", "simplicio-py")
SELF_SPAWN = "SIMPLICIO_LOOP_SELF_SPAWN"
RESET_ENVIRONMENT = "PYINSTALLER_RESET_ENVIRONMENT"
LIBRARY_PATHS = ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH", "LIBPATH")
_SUFFIX = ".exe" if os.name == "nt" else ""


class UnsafeDirectory(OSError):
    """A directory of the link path is not private to this user."""


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


def _run_like_python(args: Sequence[str]) -> bool:
    """Run ``-m MODULE``, ``-c CODE`` or ``FILE.py`` as python does. False for any other arguments."""
    if len(args) >= 2 and args[0] == "-m":
        sys.argv = [args[1], *args[2:]]
        runpy.run_module(args[1], run_name="__main__", alter_sys=True)
    elif len(args) >= 2 and args[0] == "-c":
        sys.argv = ["-c", *args[2:]]
        exec(compile(args[1], "<string>", "exec"), {"__name__": "__main__"})  # noqa: S102
    elif args and args[0].endswith(".py") and os.path.isfile(args[0]):
        sys.argv = list(args)
        sys.path.insert(0, os.path.dirname(os.path.abspath(args[0])))
        runpy.run_path(args[0], run_name="__main__")
    else:
        return False
    return True


def dispatch(argv: Sequence[str], scripts: Optional[Mapping[str, str]] = None) -> int:
    """Run the program that ``argv[0]`` names, with ``sys.argv`` set like a console script.

    The mark of ``adjust_child_environment`` is read once and removed, so it never reaches the
    children of this process. An operator name never runs code, with or without the mark.
    """
    name = program_name(argv[0]) if argv else LOOP_NAME
    args = list(argv[1:])
    started_by_the_bundle = os.environ.pop(SELF_SPAWN, None) == "1"
    if started_by_the_bundle and name not in OPERATOR_NAMES and _run_like_python(args):
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


def _private_directory(path: Path, *, leaf: bool) -> None:
    """Make ``path`` or check it: a real directory of this user that the group and others cannot write.

    The leaf must be exactly 0700. A parent can be the state directory that other code of the loop
    made with a 002 umask, so it only loses the write bits of the group and others.
    """
    try:
        os.mkdir(path, 0o700)  # the umask can only close it further
    except FileExistsError:
        pass
    info = os.lstat(path)
    if stat.S_ISLNK(info.st_mode):
        raise UnsafeDirectory(f"{path} is a symbolic link")
    if not stat.S_ISDIR(info.st_mode):
        raise UnsafeDirectory(f"{path} is not a directory")
    if os.name == "nt":
        return
    if info.st_uid != os.geteuid():
        raise UnsafeDirectory(f"{path} belongs to another user")
    wanted = 0o700 if leaf else stat.S_IMODE(info.st_mode) & ~0o022
    if stat.S_IMODE(info.st_mode) != wanted:
        os.chmod(path, wanted)


def _purge(directory: Path, keep: set[str]) -> None:
    """Remove every entry that is not one of our links: this directory is first on ``PATH``."""
    for entry in list(os.scandir(directory)):
        if entry.name in keep:
            continue
        if entry.is_dir(follow_symlinks=False):
            raise UnsafeDirectory(f"{directory} has a directory inside: {entry.name}")
        os.unlink(entry.path)


def _link_names() -> set[str]:
    return {name + _SUFFIX for name in (LOOP_NAME, *OPERATOR_NAMES)}


def ensure_operator_dir(executable: os.PathLike[str] | str, home: Path) -> Path:
    """Make ``<home>/.simplicio-loop/bin/<key>/`` hold one link per program name, and nothing else.

    The key comes from the executable path. A new binary at the same path (an update) keeps
    the same links. Links that point elsewhere are repaired. Links that are right stay as they are.
    Raise ``UnsafeDirectory`` (an OSError) when a level of the path is not private to this user.
    """
    path = Path(os.path.abspath(executable))
    key = hashlib.sha256(os.fspath(path).encode()).hexdigest()[:12]
    home.mkdir(parents=True, exist_ok=True)
    state = home / ".simplicio-loop"
    binaries = state / "bin"
    directory = binaries / key
    _private_directory(state, leaf=False)
    _private_directory(binaries, leaf=False)
    _private_directory(directory, leaf=True)
    names = _link_names()
    _purge(directory, names)
    for name in names:  # the loop too: doctor, hooks and printed commands start it by name
        _link(directory / name, path)
    return directory


def _temporary_operator_dir(executable: os.PathLike[str] | str) -> Path:
    """A new private directory with the links, removed when the program ends."""
    directory = Path(tempfile.mkdtemp(prefix="simplicio-loop-bin-"))  # random name, mode 0700
    atexit.register(shutil.rmtree, directory, True)
    path = Path(os.path.abspath(executable))
    for name in _link_names():
        _link(directory / name, path)
    return directory


def prepare_environment(
    executable: os.PathLike[str] | str, environ: MutableMapping[str, str], home: Path
) -> Path:
    """Put the operator links first on ``environ['PATH']``. Child processes inherit them.

    When the directory in the home is not private or cannot be made, use a new temporary directory.
    Raise OSError when that also fails.
    """
    try:
        directory = ensure_operator_dir(executable, home)
    except OSError as error:
        print(f"simplicio-loop: using a private temporary directory for the operators: {error}", file=sys.stderr)
        directory = _temporary_operator_dir(executable)
    parts = [part for part in environ.get("PATH", "").split(os.pathsep) if part]
    if not parts or parts[0] != os.fspath(directory):
        environ["PATH"] = os.pathsep.join([os.fspath(directory), *parts])
    return directory


def _without_bundle_library_path(env: Mapping[str, str], bundle_dir: str) -> Optional[dict[str, str]]:
    """Copy ``env`` without the bundle directory on the library paths, or None when it is not there.

    The bootloader puts its temporary directory on ``LD_LIBRARY_PATH`` and keeps the old value in
    ``LD_LIBRARY_PATH_ORIG``. A system program such as git must load the libraries of the system,
    not the libz of the bundle, which goes away when the parent exits.
    """
    cleaned: Optional[dict[str, str]] = None
    for variable in LIBRARY_PATHS:
        parts = env.get(variable, "").split(os.pathsep)
        if bundle_dir not in parts:
            continue
        cleaned = dict(env) if cleaned is None else cleaned
        original = env.get(variable + "_ORIG")
        rest = original if original is not None else os.pathsep.join(part for part in parts if part and part != bundle_dir)
        if rest:
            cleaned[variable] = rest
        else:
            cleaned.pop(variable, None)
    return cleaned


def adjust_child_environment(executable: str, bundle_dir: Optional[str] = None) -> None:
    """Fix the environment of the children that this program starts (one-file builds).

    * A child that starts as ``executable`` shares the temporary directory of its parent, and the
      parent deletes it on exit. The dashboard server outlives its parent, so such a child gets
      ``PYINSTALLER_RESET_ENVIRONMENT`` and unpacks its own copy. It costs about one second, so only
      a child that starts as ``sys.executable`` pays it. The operators start by name, run short, and
      keep sharing the unpack of the parent. The bootloader removes the variable at start, so it goes
      into the environment of each such child, not into ``os.environ``. The child also gets the mark
      ``SIMPLICIO_LOOP_SELF_SPAWN``, which allows ``-m``, ``-c`` and ``FILE.py``.
    * No child keeps the temporary directory of the bundle on its library path (``bundle_dir``).
    """
    original = subprocess.Popen.__init__
    if getattr(original, "_simplicio_adjusted", False):
        return

    def init(self, args, *positional, **keywords):
        first = args if isinstance(args, (str, bytes, os.PathLike)) else (args[0] if args else None)
        own = (isinstance(first, str) and not keywords.get("shell")
               and os.path.normcase(first) == os.path.normcase(executable))
        base = os.environ if keywords.get("env") is None else keywords["env"]
        cleaned = _without_bundle_library_path(base, bundle_dir) if bundle_dir else None
        if own or cleaned is not None:
            env = dict(base) if cleaned is None else cleaned
            if own:
                env[RESET_ENVIRONMENT] = "1"
                env[SELF_SPAWN] = "1"
            keywords["env"] = env
        original(self, args, *positional, **keywords)

    init._simplicio_adjusted = True  # type: ignore[attr-defined]
    subprocess.Popen.__init__ = init  # type: ignore[method-assign]


def main(argv: Optional[Sequence[str]] = None) -> int:
    if getattr(sys, "frozen", False):
        adjust_child_environment(sys.executable, getattr(sys, "_MEIPASS", None))
        try:
            prepare_environment(sys.executable, os.environ, Path.home())
        except OSError as error:  # --version must work even then; the operators are missing
            print(f"simplicio-loop: cannot link the operators: {error}", file=sys.stderr)
    return dispatch(sys.argv if argv is None else list(argv))
