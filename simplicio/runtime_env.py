"""Project runtime helpers for shell-based verify commands."""

from __future__ import annotations

import os
import re
import shlex
import sys
from pathlib import Path

_NODE_COMMAND_RE = re.compile(r"(^|[;&|({]\s*)(corepack|ng|node|npm|npx|pnpm|yarn)\b")
_DOTENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def wrap_project_command(root: str | os.PathLike[str], command: str) -> str:
    """Prefix Node commands with the project-pinned nvm runtime when available."""
    if not command or not _NODE_COMMAND_RE.search(command):
        return command
    if "nvm use" in command or "NVM_DIR" in command:
        return command

    project_root = Path(root)
    nvmrc = project_root / ".nvmrc"
    if not nvmrc.is_file():
        return command

    nvm_dir = Path(os.environ.get("NVM_DIR", Path.home() / ".nvm"))
    nvm_sh = nvm_dir / "nvm.sh"
    if not nvm_sh.is_file():
        return command

    return f". {shlex.quote(str(nvm_sh))} >/dev/null 2>&1 && nvm use >/dev/null && {command}"


def prepare_project_command(
    root: str | os.PathLike[str],
    command: str,
    extra_args: list[str] | None = None,
) -> tuple[list[str] | str, bool]:
    """Prepare a project command for ``subprocess.run``.

    Returns ``(cmd, use_shell)``. Prefers argv execution, but preserves shell
    execution for wrapped Node commands or explicit shell syntax. On Windows,
    translates a small set of POSIX-only helpers used by this repo's tests
    (``true`` / ``false`` / ``grep -q``) into portable Python invocations.
    """

    extra_args = list(extra_args or [])
    wrapped = wrap_project_command(root, command.strip())
    portable = _portable_windows_command(command.strip(), extra_args)
    if portable is not None:
        return portable, False
    if wrapped != command.strip() or _needs_shell(wrapped):
        return wrapped if not extra_args else " ".join([wrapped, *extra_args]), True
    argv = shlex.split(command, posix=True)
    if len(argv) == 1:
        return " ".join([command, *extra_args]), True
    return argv + extra_args, False


def _needs_shell(command: str) -> bool:
    return any(token in command for token in ("&&", "||", "|", ";", ">", "<", "$(", "`"))


def _portable_windows_command(command: str, extra_args: list[str]) -> list[str] | None:
    if os.name != "nt":
        return None
    argv = shlex.split(command, posix=True)
    if not argv:
        return None
    if argv[0] == "true":
        return [sys.executable, "-c", "raise SystemExit(0)", *extra_args]
    if argv[0] == "false":
        return [sys.executable, "-c", "raise SystemExit(1)", *extra_args]
    if len(argv) >= 4 and argv[0] == "grep" and argv[1] == "-q":
        pattern = argv[2]
        target = argv[3]
        return [
            sys.executable,
            "-c",
            (
                "from pathlib import Path; import sys; "
                "text = Path(sys.argv[2]).read_text(encoding='utf-8', errors='ignore'); "
                "raise SystemExit(0 if sys.argv[1] in text else 1)"
            ),
            pattern,
            target,
            *extra_args,
        ]
    return None


def parse_env_file(path: str | os.PathLike[str]) -> dict[str, str]:
    """Parse KEY=VALUE dotenv files without evaluating them as shell code."""
    env: dict[str, str] = {}
    for line_number, raw_line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            raise ValueError(f"invalid env line {line_number}: missing '='")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not _DOTENV_KEY_RE.match(key):
            raise ValueError(f"invalid env line {line_number}: invalid key {key!r}")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        env[key] = value
    return env


def shell_export_lines(values: dict[str, str]) -> list[str]:
    """Render dotenv values as shell-safe exports."""
    return [f"export {key}={shlex.quote(value)}" for key, value in sorted(values.items())]
