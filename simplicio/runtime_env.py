"""Project runtime helpers for shell-based verify commands."""

from __future__ import annotations

import os
import re
import shlex
from pathlib import Path


_NODE_COMMAND_RE = re.compile(r"(^|[;&|({]\s*)(corepack|ng|node|npm|npx|pnpm|yarn)\b")


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
