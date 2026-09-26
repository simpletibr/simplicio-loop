"""Installed consumer entrypoint for the loop's bundled operational scripts.

The source checkout exposes ``scripts/*.py`` directly, but a consumer checkout only has the
installed ``simplicio-loop`` distribution.  This module is the one stable resolver for the
portable scripts that the skill documents.  It executes the packaged copies while binding their
state and subprocess cwd to the consumer repository, never to the installed package directory.
"""

from __future__ import annotations

import argparse
import os
import runpy
import sys
from pathlib import Path
from typing import Iterable


_BUNDLED_SCRIPTS = Path(__file__).resolve().parent / "_bundle" / "scripts"
_SCRIPT_NAMES = (
    "loop_progress",
    "operator_check",
    "task_anchor",
    "loop_journal",
    "worktree_cleanup",
)
_ALIASES = {name: name for name in _SCRIPT_NAMES}
_ALIASES.update({f"{name}.py": name for name in _SCRIPT_NAMES})


def available_scripts() -> tuple[str, ...]:
    """Return the allowlisted consumer-facing script names."""

    return _SCRIPT_NAMES


def resolve_script(name: str, bundled_scripts: Path | None = None) -> Path:
    """Resolve one allowlisted script without consulting the caller's working directory."""

    canonical = _ALIASES.get(name)
    if canonical is None:
        choices = ", ".join(_SCRIPT_NAMES)
        raise ValueError(f"unknown script {name!r}; choose one of: {choices}")
    root = Path(bundled_scripts) if bundled_scripts is not None else _BUNDLED_SCRIPTS
    path = (root / f"{canonical}.py").resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def _repo_root(value: str | os.PathLike[str] | None) -> Path:
    root = Path(value or os.getcwd()).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(root)
    return root


def _script_environment(repo: Path) -> dict[str, str]:
    """Bind all stateful scripts to ``repo`` while retaining caller configuration."""

    loop_dir = repo / ".simplicio-loop" / "orchestrator" / "loop"
    env = dict(os.environ)
    env["SIMPLICIO_REPO"] = str(repo)
    env.setdefault("SIMPLICIO_PROGRESS_DIR", str(loop_dir))
    env.setdefault("SIMPLICIO_ANCHOR_FILE", str(loop_dir / "anchor.json"))
    env.setdefault("SIMPLICIO_BACKLOG_FILE", str(loop_dir / "backlog.jsonl"))
    env.setdefault("SIMPLICIO_JOURNAL_FILE", str(loop_dir / "journal.jsonl"))
    return env


def _missing_install_message(path: Path) -> str:
    return (
        "CONSUMER_ENTRYPOINT_ERROR|reason_code=bundled_script_missing\n"
        f"resolved_package_path={path}\n"
        "install_command=python -m pip install --upgrade simplicio-loop\n"
        "hint=the installed package is incomplete; reinstall simplicio-loop and retry"
    )


def _run_script(script: Path, args: Iterable[str], repo: Path) -> int:
    old_argv = sys.argv
    old_env = os.environ.copy()
    script_dir = str(script.parent)
    sys.argv = [str(script), *list(args)]
    os.environ.clear()
    os.environ.update(_script_environment(repo))
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    try:
        runpy.run_path(str(script), run_name="__main__")
    except SystemExit as exc:
        code = exc.code
        return int(code) if isinstance(code, int) else 0
    finally:
        sys.argv = old_argv
        os.environ.clear()
        os.environ.update(old_env)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="simplicio-loop-tools",
        description="Run bundled simplicio-loop operational scripts from a consumer repository.",
    )
    parser.add_argument("--repo", default="", help="consumer repository (default: current directory)")
    parser.add_argument("script", nargs="?", help="one of: " + ", ".join(_SCRIPT_NAMES))
    parser.add_argument("script_args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if not args.script:
        parser.print_help()
        return 2
    try:
        repo = _repo_root(args.repo)
    except FileNotFoundError as exc:
        print(
            "CONSUMER_ENTRYPOINT_ERROR|reason_code=consumer_repository_missing\n"
            f"resolved_consumer_repository={exc.args[0]}",
            file=sys.stderr,
        )
        return 2
    try:
        script = resolve_script(args.script)
    except ValueError as exc:
        print(f"CONSUMER_ENTRYPOINT_ERROR|reason_code=unknown_script|{exc}", file=sys.stderr)
        return 2
    except FileNotFoundError as exc:
        print(_missing_install_message(Path(exc.args[0])), file=sys.stderr)
        return 2
    forwarded = list(args.script_args)
    if forwarded[:1] == ["--"]:
        forwarded = forwarded[1:]
    return _run_script(script, forwarded, repo)


if __name__ == "__main__":
    raise SystemExit(main())
