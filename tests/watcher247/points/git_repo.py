"""A throwaway git repo for the PR-quality points (judge, sibling_search): real git, no fakes."""
import subprocess
from pathlib import Path


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=repo, capture_output=True, text=True, check=True)
    return done.stdout


def init_repo(root: Path, files: dict[str, str]) -> Path:
    """A repo with one commit holding `files`."""
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-q", "-b", "main")
    write(root, files)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "base")
    return root


def write(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
