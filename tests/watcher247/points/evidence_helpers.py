"""Shared by the evidence points tests: a real tmp git repo, a fake worker script and the no-bwrap test mode."""
import subprocess
import textwrap
from pathlib import Path


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
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


def fake_worker(path: Path, *, exit_code: int, produces: str | None) -> Path:
    """A script with the CLI shape of the real workers: records argv/env in --out, exits `exit_code`.

    `produces` is the file name written into --out on exit 0 (None writes nothing). It also exports FE_RE,
    as scripts/web_verify.py does, because the point imports the pattern from the script.
    """
    path.write_text(textwrap.dedent(f"""\
        import json, os, re, sys
        FE_RE = re.compile(r"\\.(tsx|jsx|vue|svelte|css|scss|html)$", re.I)
        if __name__ == "__main__":
            argv = sys.argv[1:]
            out = argv[argv.index("--out") + 1]
            os.makedirs(out, exist_ok=True)
            with open(os.path.join(out, "argv.json"), "w") as f:
                json.dump({{"argv": argv, "gh_token": os.environ.get("GH_TOKEN")}}, f)
            produces = {produces!r}
            if {exit_code} == 0 and produces:
                name = produces.replace("ISSUE", argv[argv.index("--issue") + 1])
                with open(os.path.join(out, name), "wb") as f:
                    f.write(b"x")
            print("fake worker", argv)
            sys.exit({exit_code})
        """))
    return path
