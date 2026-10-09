"""The installed watcher must not depend on the repo's `scripts/` directory (#1476).

`scripts/` does not ship in the wheel and the systemd unit has no WorkingDirectory, so
`simplicio_loop.watcher_github` has to work with the package alone. This runs a real
subprocess with cwd = an empty tmp dir and PYTHONPATH = a copy of ONLY `simplicio_loop/`
(no repo root, so `scripts` is not importable), with a fake `gh` executable on PATH.
"""
import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

FAKE_GH = '''#!{python}
import json, re, sys
STATE = {state!r}
argv = sys.argv[1:]
assert argv[0] == "api", argv
method = argv[argv.index("-X") + 1] if "-X" in argv else "GET"
path = next(a for a in argv if a.startswith("repos/"))
route, _, query = path.partition("?")
try:
    db = json.load(open(STATE))
except FileNotFoundError:
    db = {{"next": 1001, "comments": []}}
payload = sys.stdin.read() if "--input" in argv else ""

def out(obj):
    json.dump(db, open(STATE, "w"))
    print(json.dumps(obj))
    sys.exit(0)

m = re.fullmatch(r"repos/[^/]+/[^/]+/issues/(\\d+)/comments", route)
if m:
    if method == "POST":
        c = {{"id": db["next"], "body": json.loads(payload)["body"]}}
        db["next"] += 1
        db["comments"].append(c)
        out(c)
    out([] if "page=" in query and "page=1" not in query else db["comments"])
m = re.fullmatch(r"repos/[^/]+/[^/]+/issues/comments/(\\d+)", route)
if m:
    c = next(c for c in db["comments"] if c["id"] == int(m.group(1)))
    if method == "PATCH":
        c["body"] = json.loads(payload)["body"]
    out(c)
m = re.fullmatch(r"repos/[^/]+/[^/]+/issues/(\\d+)", route)
if m:
    out({{"number": int(m.group(1)), "title": "t", "body": "b", "state": "open",
         "html_url": "https://github.com/acme/widgets/issues/" + m.group(1),
         "labels": [], "assignees": [], "user": {{"login": "a"}},
         "created_at": "2026-10-01T00:00:00Z", "updated_at": "2026-10-01T00:00:00Z"}})
sys.stderr.write("unexpected gh call: %r" % (argv,))
sys.exit(2)
'''

DRIVER = textwrap.dedent('''
    import asyncio, json
    import simplicio_loop.watcher_github as w
    try:
        import scripts  # noqa: F401
        raise SystemExit("scripts must NOT be importable in this process")
    except ImportError:
        pass
    receipt = asyncio.run(w.post_status(repo="acme/widgets", issue="42", state="CLAIMED",
                                        agent_id="session-a"))
    print(json.dumps({"verified": receipt.get("verified"), "outcome": receipt.get("outcome")}))
''')


def test_post_status_works_with_only_the_package_on_path(tmp_path):
    site = tmp_path / "site"
    site.mkdir()
    shutil.copytree(REPO_ROOT / "simplicio_loop", site / "simplicio_loop",
                    ignore=shutil.ignore_patterns("__pycache__", "_bundle"))
    bindir = tmp_path / "bin"
    bindir.mkdir()
    gh = bindir / "gh"
    gh.write_text(FAKE_GH.format(python=sys.executable, state=str(tmp_path / "gh-state.json")))
    gh.chmod(0o755)
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    env = {"PATH": "%s%s%s" % (bindir, os.pathsep, os.environ.get("PATH", "")),
           "PYTHONPATH": str(site), "HOME": str(tmp_path), "PYTHONDONTWRITEBYTECODE": "1"}
    done = subprocess.run([sys.executable, "-c", DRIVER], cwd=str(cwd), env=env,
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout.strip().splitlines()[-1])["verified"] is True
    state = json.loads((tmp_path / "gh-state.json").read_text())
    assert len(state["comments"]) == 1
    assert "CLAIMED" in state["comments"][0]["body"]
