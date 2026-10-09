"""Shared fixtures for the end-to-end flow tests.

Everything real stays real: the Mapper (`simplicio-mapper`), the Dev CLI (`simplicio-dev-cli`) and
`simplicio-loop turbo` run as subprocesses from the dev venv. Only the three external edges are fake:

* GitHub: a `gh` script on PATH that answers from a JSON fixture and logs every call;
* the model: a localhost HTTP server speaking the OpenRouter chat shape, reached by the turbo
  subprocess through a `sitecustomize` that points `turbo_provider.API_URL` at it;
* the git remote: a bare repository on disk, cloned with `file://`.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
REPO_NAME = "simplicio-demo"
ORIGINAL_APP = 'def greet():\n    return "hello"\n'
ISSUE_NUMBER = 7
ISSUE_TITLE = "Trocar a saudacao para hi"
ISSUE_BODY = 'Em src/app.py, greet() deve retornar "hi" em vez de "hello".'
LOOP_TOML = "enabled = true\n"  # intake_gate.repo_opted_in needs this literal
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
elif args[0] == "api":
    path = next(a for a in args[1:] if a.startswith("repos/"))
    method = opt("-X") or "GET"
    if method == "GET" and path.endswith("/contents/.simplicio/loop.toml"):
        record(path=path)
        print(base64.b64encode(fx["loop_toml"].encode()).decode())
    elif method == "GET" and "/issues/" in path and path.rsplit("/", 1)[1].isdigit():
        number = int(path.rsplit("/", 1)[1])
        record(path=path)
        issue = next(i for rows in fx["issues"].values() for i in rows if i["number"] == number)
        print(json.dumps(dict(issue, author_association=issue["authorAssociation"])))
    elif method == "GET" and "/issues/" in path and "/comments" in path:
        number = path.split("/issues/")[1].split("/")[0]
        rows = [dict(id=c["comment_id"], body=c["body"]) for c in seen_calls()
                if c.get("method") == "POST" and c["path"].endswith("/issues/" + number + "/comments")]
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
    print(f"https://github.com/{{opt('--repo')}}/pull/1")
else:
    print("unsupported gh call: " + " ".join(args), file=sys.stderr)
    sys.exit(2)
'''

SITECUSTOMIZE = '''import os
_url = os.environ.get("SIMPLICIO_FLOW_MODEL_URL")
if _url:
    import simplicio_loop.turbo_provider as _provider
    _provider.API_URL = _url
'''


class _Planner(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        self.server.calls.append(self.path)
        reply = {
            "model": "fake-planner",
            "choices": [{"message": {"role": "assistant", "content": json.dumps(PLAN)}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        data = json.dumps(reply).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_args) -> None:
        return


@pytest.fixture(scope="module")
def flow_base(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("flow")


@pytest.fixture(scope="module")
def remote_bare(flow_base: Path) -> Path:
    return make_remote(flow_base)


@pytest.fixture(scope="module")
def fake_model(flow_base: Path):
    """Localhost planner; `calls` records every request it answered."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Planner)
    server.calls = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield {"url": f"http://127.0.0.1:{server.server_address[1]}/api/v1/chat/completions", "server": server}
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture(scope="module")
def fake_gh_env(flow_base: Path, remote_bare: Path, fake_model):
    """PATH with the fake `gh` and the venv binaries, plus the env the watcher and turbo subprocesses need."""
    bin_dir = flow_base / "bin"
    bin_dir.mkdir(exist_ok=True)
    gh = bin_dir / "gh"
    gh.write_text(FAKE_GH.format(python=sys.executable))
    gh.chmod(0o755)
    # The watcher and turbo must run THIS checkout, never a stale `simplicio-loop` on the host PATH.
    shim = bin_dir / "simplicio-loop"
    shim.write_text(
        f"#!{sys.executable}\n"
        "import sys\n"
        f"sys.path.insert(0, {str(REPO_ROOT)!r})\n"
        "from simplicio_loop.cli import main\n"
        "raise SystemExit(main())\n"
    )
    shim.chmod(0o755)
    hook_dir = flow_base / "pyhook"
    hook_dir.mkdir(exist_ok=True)
    (hook_dir / "sitecustomize.py").write_text(SITECUSTOMIZE)
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
        "PYTHONPATH": str(hook_dir),
        "SIMPLICIO_FLOW_MODEL_URL": fake_model["url"],
        "OPENROUTER_API_KEY": "flow-test-key",
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
        yield fake_gh_env


def run_cli(args: list[str], cwd: Path, env: dict[str, str], stdin: str | None = None) -> subprocess.CompletedProcess:
    """Run a real `simplicio-loop` subcommand the way a host skill does."""
    return subprocess.run(
        ["simplicio-loop", *args], cwd=cwd, env={**os.environ, **env}, input=stdin,
        capture_output=True, text=True, timeout=600, check=False,
    )


def last_json(text: str) -> dict:
    """The turbo document is the last top-level JSON line on stdout (nested schemas sit inside it)."""
    lines = [line for line in text.splitlines() if line.startswith("{")]
    return json.loads(lines[-1])
