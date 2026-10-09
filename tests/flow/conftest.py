"""Shared fixtures for the end-to-end flow tests.

Everything real stays real: the Mapper (`simplicio-mapper`), the Dev CLI (`simplicio-dev-cli`) and
`simplicio-loop turbo` run as subprocesses from the dev venv. Only the three external edges are fake:

* GitHub: a `gh` script on PATH that answers from a JSON fixture and logs every call;
* the planner: a `claude` script on PATH that answers `auth status` and prints the plan as the real CLI's
  `--output-format json` envelope (the watcher's default executor is `exec`: an exec CLI plans, turbo applies);
* the git remote: a bare repository on disk, cloned with `file://`.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from simplicio_loop.watcher247 import sandbox

REPO_ROOT = Path(__file__).resolve().parents[2]
REPO_NAME = "simplicio-demo"
ORIGINAL_APP = 'def greet():\n    return "hello"\n'
ISSUE_NUMBER = 7
ISSUE_TITLE = "Trocar a saudacao para hi"
ISSUE_BODY = 'Em src/app.py, greet() deve retornar "hi" em vez de "hello".'
LOOP_TOML = 'enabled = true\nverify = "python3 -m pytest -q"\n'  # repo_opted_in needs the literal `enabled`; the watcher verifies with `verify`
# The planner answer: one find/replace on an exact, unique span of the seed file.
PLAN = {"operations": [{"path": "src/app.py", "find": 'return "hello"', "replace": 'return "hi"'}]}


def git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-c", "user.name=seed", "-c", "user.email=seed@example.invalid", *args],
        cwd=cwd, check=True, capture_output=True, text=True,
    )
    return result.stdout


def make_remote(base: Path) -> Path:
    """A bare `origin` whose `main` holds the seed project: app code, config and the opt-in file."""
    seed = base / "seed"
    seed.mkdir(parents=True)
    git(seed, "init", "-q", "-b", "main")
    (seed / "src").mkdir()
    (seed / "src" / "app.py").write_text(ORIGINAL_APP)
    (seed / "pyproject.toml").write_text('[project]\nname = "simplicio-demo"\nversion = "0.0.0"\n')
    # A real test suite, so `verify` in loop.toml (python3 -m pytest -q) passes before the PR is opened.
    (seed / "pytest.ini").write_text("[pytest]\npythonpath = src\n")
    (seed / ".gitignore").write_text("__pycache__/\n.pytest_cache/\n")
    (seed / "tests").mkdir()
    (seed / "tests" / "test_app.py").write_text("from app import greet\n\n\ndef test_greet_is_text():\n    assert isinstance(greet(), str)\n")
    (seed / ".simplicio").mkdir()
    (seed / ".simplicio" / "loop.toml").write_text(LOOP_TOML)
    git(seed, "add", "-A")
    git(seed, "commit", "-q", "-m", "seed")
    bare = base / "remotes" / f"{REPO_NAME}.git"
    bare.parent.mkdir(parents=True)
    git(base, "clone", "-q", "--bare", str(seed), str(bare))
    return bare


FAKE_GH = '''#!{python}
import base64, json, os, subprocess, sys
fx = json.load(open(os.environ["FAKE_GH_FIXTURES"]))
log = os.environ["FAKE_GH_LOG"]
args = sys.argv[1:]


def seen_calls():
    return [json.loads(line) for line in open(log)] if os.path.exists(log) else []


def latest_comment_body(comment_id):
    bodies = [c["body"] for c in seen_calls() if c.get("comment_id") == comment_id and c.get("method") in ("POST", "PATCH")]
    return bodies[-1] if bodies else ""


def record(**fields):
    with open(log, "a") as fh:
        fh.write(json.dumps({{"argv": args, **fields}}) + "\\n")


def opt(name):
    return args[args.index(name) + 1] if name in args else None


def api_body():
    if "--input" in args:  # gh api --input - : the JSON body arrives on stdin
        return json.loads(sys.stdin.read())["body"]
    return next(a.split("=", 1)[1] for a in args if a.startswith("body="))


if args[:2] == ["repo", "list"]:
    record()
    print(json.dumps(fx["repos"]))
elif args[:2] == ["issue", "list"]:
    record()
    print(json.dumps(fx["issues"].get(opt("--repo"), [])))
elif args[:2] == ["issue", "comment"]:
    number = int(args[2])
    seen = [json.loads(line) for line in open(log)] if os.path.exists(log) else []
    comment_id = 1 + sum(1 for c in seen if c["argv"][:2] == ["issue", "comment"])
    record(number=number, repo=opt("--repo"), body=opt("--body"), comment_id=comment_id)
    print(f"https://github.com/{{opt('--repo')}}/issues/{{number}}#issuecomment-{{comment_id}}")
elif args[:2] == ["api", "user"]:  # the account the watcher posts and merges as
    record()
    print(fx.get("login", "squad-bot"))
elif args[0] == "api":
    path = next(a for a in args[1:] if a.startswith("repos/"))
    method = opt("-X") or "GET"
    if method == "GET" and path.endswith("/contents/.simplicio/loop.toml"):
        record(path=path)
        print(base64.b64encode(fx["loop_toml"].encode()).decode())
    elif method == "GET" and "/issues/comments/" in path:
        comment_id = int(path.rsplit("/", 1)[1])
        record(path=path)
        print(json.dumps(dict(id=comment_id, body=latest_comment_body(comment_id))))
    elif method == "GET" and "/issues/" in path and path.rsplit("/", 1)[1].isdigit():
        number = int(path.rsplit("/", 1)[1])
        record(path=path)
        issue = next(i for rows in fx["issues"].values() for i in rows if i["number"] == number)
        print(json.dumps(dict(issue, author_association=issue["authorAssociation"])))
    elif method == "GET" and "/issues/" in path and "/comments" in path:
        number = path.split("/issues/")[1].split("/")[0]
        created = [c["comment_id"] for c in seen_calls()
                   if c.get("method") == "POST" and c["path"].endswith("/issues/" + number + "/comments")]
        rows = [dict(id=cid, body=latest_comment_body(cid)) for cid in created]  # PATCHes show through
        record(path=path)
        print(json.dumps(rows))
    elif method == "POST" and path.endswith("/comments"):
        body = api_body()
        comment_id = 1 + sum(1 for c in seen_calls() if c.get("method") == "POST")
        record(method=method, path=path, body=body, comment_id=comment_id)
        print(json.dumps(dict(id=comment_id)))
    elif method == "PATCH" and "/issues/comments/" in path:
        body = api_body()
        comment_id = int(path.rsplit("/", 1)[1])
        record(method=method, path=path, body=body, comment_id=comment_id)
        print(json.dumps(dict(id=comment_id)))
    else:
        print("unsupported gh api call: " + " ".join(args), file=sys.stderr)
        sys.exit(2)
elif args[:2] == ["repo", "clone"]:
    slug, dest = args[2], args[3]
    subprocess.run(["git", "clone", "-q", "--depth", "1", "file://" + fx["remotes"][slug.split("/")[-1]], dest],
                   check=True)
    record(slug=slug)
elif args[:2] == ["pr", "list"]:
    record()
    print("[]")
elif args[:2] == ["pr", "create"]:
    record(repo=opt("--repo"), base=opt("--base"), head=opt("--head"), title=opt("--title"), body=opt("--body"))
    number = 100 + int(opt("--head").rpartition("-")[2]) if fx.get("distinct_prs") else 1
    print(f"https://github.com/{{opt('--repo')}}/pull/{{number}}")
elif args[:2] == ["pr", "view"]:  # the squad review and the squad gate: the approval is whatever was posted on the PR
    number = int(args[2])
    record(pr=number)
    posted = [c["body"] for c in seen_calls()
              if c.get("method") == "POST" and c.get("path", "").endswith("/issues/%d/comments" % number)]
    print(json.dumps(dict(
        files=[dict(path="src/app.py")], headRefOid="head%d" % number,
        commits=[dict(oid="c%d" % number, committedDate="2026-10-01T00:00:00Z", messageHeadline="loop: change")],
        comments=[dict(id=i, createdAt="2026-10-02T00:00:00Z", body=b, author=dict(login=fx.get("approval_author") or fx.get("login", "squad-bot")),
                       authorAssociation="OWNER") for i, b in enumerate(posted)])))
elif args[:2] == ["pr", "merge"]:
    record(merge=int(args[2]), argv=args)
else:
    print("unsupported gh call: " + " ".join(args), file=sys.stderr)
    sys.exit(2)
'''

# The watcher runs its subprocesses with a scrubbed env (PATH only), so the checkout paths and the fake
# planner's log are baked into these shims instead of travelling through PYTHONPATH or the environment.
SHIM = '''#!{python}
import sys
for _path in {paths!r}:
    sys.path.insert(0, _path)
from {module} import main
raise SystemExit(main())
'''

# The planner CLI of the default executor (`exec`, family claude). Like the real one it answers `auth status`
# (the preflight) and, for `-p <prompt> --output-format json`, prints the envelope {{"result": "<plan json>"}}.
FAKE_CLAUDE = '''#!{python}
import json, sys
args = sys.argv[1:]
if args[:2] == ["auth", "status"]:
    raise SystemExit(0)
with open({log!r}, "a") as fh:
    fh.write(json.dumps(args) + "\\n")
print(json.dumps({{"result": json.dumps({plan!r})}}))
'''


def write_shim(path: Path, paths: list[Path], module: str) -> None:
    path.write_text(SHIM.format(python=sys.executable, paths=[str(p) for p in paths], module=module))
    path.chmod(0o755)


@pytest.fixture(scope="module")
def flow_base(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("flow")


@pytest.fixture(scope="module")
def remote_bare(flow_base: Path) -> Path:
    return make_remote(flow_base)


@pytest.fixture(scope="module")
def planner_log(flow_base: Path) -> Path:
    """One JSON line (the argv) per prompt the fake `claude` planner answered."""
    return flow_base / "planner-calls.jsonl"


@pytest.fixture(scope="module")
def fake_gh_env(flow_base: Path, remote_bare: Path, planner_log: Path):
    """PATH with the fake `gh` and the venv binaries, plus the env the watcher and turbo subprocesses need."""
    bin_dir = flow_base / "bin"
    bin_dir.mkdir(exist_ok=True)
    gh = bin_dir / "gh"
    gh.write_text(FAKE_GH.format(python=sys.executable))
    gh.chmod(0o755)
    # The watcher and turbo must run THIS checkout, never a `simplicio-loop`, `simplicio-mapper` or
    # `simplicio-dev-cli` installed on the host: each name on PATH is a shim over the checkout's code.
    write_shim(bin_dir / "simplicio-loop", [REPO_ROOT], "simplicio_loop.cli")
    write_shim(bin_dir / "simplicio-mapper", [REPO_ROOT / "packages" / "mapper"], "simplicio_mapper.cli")
    write_shim(bin_dir / "simplicio-dev-cli", [REPO_ROOT / "packages" / "dev-cli"], "simplicio.cli")
    # The default executor tries claude, codex, grok and gemini in order: this `claude` comes first on PATH and
    # is the only family enabled, so a real CLI installed on the host is never spawned.
    claude = bin_dir / "claude"
    claude.write_text(FAKE_CLAUDE.format(python=sys.executable, log=str(planner_log), plan=PLAN))
    claude.chmod(0o755)
    fixtures = {
        "repos": [{"name": REPO_NAME, "isArchived": False, "defaultBranchRef": {"name": "main"}}],
        "issues": {f"simpletibr/{REPO_NAME}": [{
            "number": ISSUE_NUMBER, "title": ISSUE_TITLE, "body": ISSUE_BODY,
            "createdAt": "2026-10-08T12:00:00Z", "labels": [{"name": "loop:auto"}],
            "author": {"login": "wesleysimplicio"}, "authorAssociation": "MEMBER",
        }]},
        "remotes": {REPO_NAME: str(remote_bare)},
        "loop_toml": LOOP_TOML,
    }
    fixtures_path = flow_base / "gh-fixtures.json"
    fixtures_path.write_text(json.dumps(fixtures))
    env = {
        "PATH": f"{bin_dir}{os.pathsep}{Path(sys.executable).parent}{os.pathsep}{os.environ.get('PATH', '')}",
        "PYTHONPATH": str(REPO_ROOT),
        # The sandbox (bwrap) has its own tests (#1494); here it would hide the shims under /tmp.
        "SIMPLICIO_247_ALLOW_UNSANDBOXED": "1",
        "SIMPLICIO_EXEC_FAMILIES": "claude",
        "FAKE_GH_FIXTURES": str(fixtures_path),
        "FAKE_GH_LOG": str(flow_base / "gh-calls.jsonl"),
        "GIT_TERMINAL_PROMPT": "0",
    }
    return env


@pytest.fixture(scope="module")
def flow_env(fake_gh_env, flow_base: Path):
    """Apply the fake environment to this process too (the watcher runs in-process)."""
    with pytest.MonkeyPatch.context() as patch:
        for key, value in fake_gh_env.items():
            patch.setenv(key, value)
        patch.setenv("GH_TOKEN", "ghp_FAKEflow0000000000000000000000000")  # the tick idles without a GitHub token
        # bwrap mounts a tmpfs over /tmp and would hide the shims; the sandbox has its own tests (#1494).
        patch.setattr(sandbox, "engine", lambda *_args, **_kwargs: None)
        yield fake_gh_env


def run_cli(args: list[str], cwd: Path, env: dict[str, str], stdin: str | None = None) -> subprocess.CompletedProcess:
    """Run a real `simplicio-loop` subcommand the way a host skill does, from this checkout (never the PATH binary)."""
    return subprocess.run(
        [sys.executable, "-m", "simplicio_loop.cli", *args], cwd=cwd, env={**os.environ, **env}, input=stdin,
        capture_output=True, text=True, timeout=600, check=False,
    )


def last_json(text: str) -> dict:
    """The turbo document is the last top-level JSON line on stdout (nested schemas sit inside it)."""
    lines = [line for line in text.splitlines() if line.startswith("{")]
    return json.loads(lines[-1])
