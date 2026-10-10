"""B1 (#1649): the code of a PR runs with a scrubbed environment, an empty HOME and, in the gate, inside bwrap or not at all."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from simplicio_loop.review_gate import diffs, gate, identity, isolation, mutation, redgreen
from simplicio_loop.review_gate.model import ERROR, FAIL, PASS
from simplicio_loop.watcher247 import sandbox
from tests.review_gate import scenario
from tests.watcher247.sandbox_rig import needs_bwrap, scratch

WORKER = identity.Agent("worker-1", "worker", "haiku-5.5", "local")
OLD = "def add(a, b):\n    return a\n"
NEW = "def add(a, b):\n    return a + b\n"
# A PR test that looks for what the watcher owns: it passes only when it finds none of it.
SPY = '''\
import os
from pathlib import Path

from mod import add

SECRETS = ("GH_TOKEN", "GITHUB_TOKEN", "ANTHROPIC_API_KEY", "SIMPLICIO_SECRET")


def test_the_child_sees_nothing_of_the_watcher():
    assert add(1, 2) == 3
    assert [name for name in SECRETS if name in os.environ] == []
    home = Path(os.path.expanduser("~"))
    assert not (home / ".simplicio" / "login.json").exists()
    assert not (home / ".config" / "gh" / "hosts.yml").exists()
    assert not any(home.glob(".*")) if home.is_dir() else True
'''


@pytest.fixture
def secrets(tmp_path, monkeypatch):
    """The environment and HOME of a watcher: tokens in the env, a login and a gh token file in HOME."""
    home = tmp_path / "service-home"
    (home / ".simplicio").mkdir(parents=True)
    (home / ".simplicio" / "login.json").write_text('{"token": "tok-1"}')
    (home / ".config" / "gh").mkdir(parents=True)
    (home / ".config" / "gh" / "hosts.yml").write_text("oauth_token: tok-2\n")
    monkeypatch.setenv("HOME", str(home))
    for name in ("GH_TOKEN", "GITHUB_TOKEN", "ANTHROPIC_API_KEY", "SIMPLICIO_SECRET"):
        monkeypatch.setenv(name, "ghp_" + name)
    return home


def _trees(tmp_path, test=SPY, base_mod=OLD, head_mod=NEW):
    for name, mod, text in (("base", base_mod, ""), ("head", head_mod, test)):
        (tmp_path / name / "tests").mkdir(parents=True)
        (tmp_path / name / "mod.py").write_text(mod)
        (tmp_path / name / "tests" / "test_mod.py").write_text(text)
    changes = [diffs.FileChange("tests/test_mod.py", "A", tuple(range(1, test.count("\n") + 1))), diffs.FileChange("mod.py", "M", (2,))]
    return tmp_path / "base", tmp_path / "head", changes


# --- child_env ----------------------------------------------------------------------------------------------------------

def test_child_env_is_the_allowlist_plus_extra_with_an_empty_home(secrets, monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setenv("LANG", "C.UTF-8")
    monkeypatch.setenv("SOME_OTHER", "x")
    env = isolation.child_env({"PYTHONPATH": ".", "HOME": "/root"})
    assert env == {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "HOME": str(isolation.NO_HOME), "SIMPLICIO_LOOP_DAEMON": "0",
                   "PYTHONPATH": ".", "PYTHONDONTWRITEBYTECODE": "1"}  # `extra` cannot move HOME; no token survives
    assert isolation.child_env(None, Path("/some/home"))["HOME"] == "/some/home"


# --- unit: redgreen and mutation scrub the env ----------------------------------------------------------------------------

def test_redgreen_runs_the_pr_tests_without_the_token_and_with_an_empty_home(secrets, tmp_path):
    base, head, changes = _trees(tmp_path)
    result = redgreen.check_redgreen(base, head, changes, python=sys.executable, env={"PYTHONPATH": "."})
    assert result.status == PASS, result.reasons  # head_failed would list the spy test if it had seen a secret


def test_redgreen_gives_the_child_the_home_it_was_told_to(secrets, tmp_path):
    shown = "import os\nfrom mod import add\n\n\ndef test_home():\n    assert add(1, 2) == 3 and os.environ['HOME'] == '/the/empty/home'\n"
    base, head, changes = _trees(tmp_path, shown)
    assert redgreen.check_redgreen(base, head, changes, python=sys.executable, env={"PYTHONPATH": "."}, home=Path("/the/empty/home")).status == PASS


def test_mutation_runs_the_unmutated_tree_and_every_mutant_without_the_token(secrets, tmp_path):
    root = tmp_path / "head"
    (root / "tests").mkdir(parents=True)
    (root / "app.py").write_text("def f(x, y):\n    return x == y\n")
    spy = ("import os\nfrom pathlib import Path\nfrom app import f\n\n\ndef test_f():\n"
           "    assert 'GH_TOKEN' not in os.environ and 'GITHUB_TOKEN' not in os.environ\n"
           "    assert not (Path(os.path.expanduser('~')) / '.simplicio' / 'login.json').exists()\n"
           "    assert f(1, 1) and not f(1, 2)\n")
    (root / "tests" / "test_app.py").write_text(spy)
    argv = [sys.executable, "-m", "pytest", "-q", "-x", "--tb=no", "-p", "no:cacheprovider", "-o", "addopts=", "tests"]
    result = mutation.check_mutation(root, [diffs.FileChange("app.py", "A", (2,))], argv, seed="s", env={"PYTHONPATH": "."})
    assert result.status == PASS, result.reasons  # with the token visible the unmutated run fails and the result is ERROR


def test_a_pr_test_that_writes_what_it_sees_leaves_nothing_of_the_watcher(secrets, tmp_path):
    """The reproduction of the audit: a PR test that records GH_TOKEN and `~` in a file."""
    record = tmp_path / "seen.json"
    test = ("import json, os\nfrom mod import add\n\n\ndef test_record():\n"
            f"    open({str(record)!r}, 'w').write(json.dumps([os.environ.get('GH_TOKEN'), os.path.expanduser('~'), "
            "os.path.exists(os.path.expanduser('~/.simplicio/login.json'))]))\n    assert add(1, 2) == 3\n")
    base, head, changes = _trees(tmp_path, test)
    redgreen.check_redgreen(base, head, changes, python=sys.executable, env={"PYTHONPATH": "."})
    assert json.loads(record.read_text()) == [None, str(isolation.NO_HOME), False]


# --- the wrapper is built for the tree it runs in --------------------------------------------------------------------------

def test_redgreen_builds_the_wrapper_of_each_run_for_that_run_s_tree(secrets, tmp_path):
    """`sandbox.wrap` does `--chdir <clone>`: a wrapper made for head would run the "main" pass inside the head tree."""
    base, head, changes = _trees(tmp_path)
    built: list[Path] = []

    def wrap_for(root):
        built.append(root)
        return lambda argv: argv

    result = redgreen.check_redgreen(base, head, changes, python=sys.executable, env={"PYTHONPATH": "."}, wrap_for=wrap_for)
    assert result.status == PASS and built == [head, base]


# --- the gate: jail or nothing ---------------------------------------------------------------------------------------------

def _input(repo, base, head, **kw):
    return gate.GateInput(repo=repo, pr=11, issue=None, issue_body="", pr_body="", base=base, head=head, author=WORKER, **kw)


def test_without_bwrap_the_gate_rejects_with_sandbox_unavailable_and_runs_nothing(tmp_path, monkeypatch):
    repo, base, head = scenario.make_repo(tmp_path, "good")
    monkeypatch.setattr(sandbox, "engine", lambda *a, **k: None)
    monkeypatch.setenv(sandbox.OPT_OUT, "1")  # the watcher's opt-out is not the gate's
    calls: list[list[str]] = []
    real = subprocess.run
    monkeypatch.setattr(subprocess, "run", lambda argv, *a, **k: calls.append([str(x) for x in argv]) or real(argv, *a, **k))
    report = gate.run_gate(_input(repo, base, head))
    assert not report.approved and [c.name for c in report.checks] == ["sandbox"]
    check = report.checks[0]
    assert check.status == ERROR and check.reasons[0].startswith("sandbox_unavailable: ") and check.measured["reason_code"] == "sandbox_unavailable"
    assert not any("pytest" in c or c[:3] == ["git", "worktree", "add"] for c in calls)  # not a test, not even a tree
    saved = json.loads((repo / ".simplicio-loop" / "review-gate" / f"pr-11-{head[:7]}.json").read_text())
    assert saved["approved"] is False and saved["checks"][0]["measured"]["reason_code"] == "sandbox_unavailable"


def test_the_gate_builds_its_jail_for_the_state_dir_and_the_interpreter_and_gives_the_checks_its_home_and_wrappers(tmp_path, monkeypatch):
    repo, base, head = scenario.make_repo(tmp_path, "notest")
    seen = {}

    def fake_jail(state_dir, python, **kw):
        seen["jail"] = (state_dir, python)
        return isolation.Jail(Path("/the/jail/home"), lambda root: seen.setdefault("roots", []).append(root) or (lambda argv: argv))

    monkeypatch.setattr(isolation, "make_jail", fake_jail)
    got = {}
    real_rg, real_mut = redgreen.check_redgreen, mutation.check_mutation
    monkeypatch.setattr(redgreen, "check_redgreen", lambda *a, **k: got.setdefault("redgreen", k) and real_rg(*a, **k))
    monkeypatch.setattr(mutation, "check_mutation", lambda *a, **k: got.setdefault("mutation", k) and real_mut(*a, **k))
    gate.run_gate(_input(repo, base, head))
    assert seen["jail"] == (repo / ".simplicio-loop" / "review-gate", sys.executable)
    assert got["redgreen"]["home"] == Path("/the/jail/home") == got["mutation"]["home"]
    assert callable(got["redgreen"]["wrap_for"]) and got["redgreen"]["wrap_for"](Path("/x"))(["a"]) == ["a"]
    state = repo / "elsewhere"
    state.mkdir()
    seen.clear()
    gate.run_gate(_input(repo, base, head, state_dir=state, python="/opt/py"))
    assert seen["jail"] == (state, "/opt/py")


def test_a_test_seam_wrap_for_still_gets_the_scrubbed_env(secrets, tmp_path):
    repo, base, head = scenario.make_repo(tmp_path, "good")
    report = gate.run_gate(_input(repo, base, head, wrap_for=scenario.UNSANDBOXED, n_mutants=2))
    assert next(c for c in report.checks if c.name == "redgreen").status == PASS


# --- real bwrap -------------------------------------------------------------------------------------------------------------

@needs_bwrap
def test_under_bwrap_the_child_sees_no_token_no_login_and_an_empty_home_and_writes_only_its_tree(monkeypatch):
    with scratch("gate-jail-") as tmp:
        home, root, state = tmp / "home", tmp / "head", tmp / "state"
        for d in (home / ".simplicio", home / ".config" / "gh", root, state):
            d.mkdir(parents=True)
        (home / ".simplicio" / "login.json").write_text("{}")
        (home / ".config" / "gh" / "hosts.yml").write_text("oauth_token: x\n")
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("GH_TOKEN", "ghp_secret")
        jail = isolation.make_jail(state, sys.executable)
        prog = ("import json, os, pathlib\n"
                f"def can_write(p):\n    try:\n        pathlib.Path(p).write_text('x'); return True\n    except OSError:\n        return False\n"
                f"print(json.dumps({{'token': os.environ.get('GH_TOKEN'), 'home': os.environ['HOME'], 'listing': sorted(os.listdir({str(home)!r})),"
                f" 'login': os.path.exists({str(home / '.simplicio' / 'login.json')!r}), 'gh': os.path.exists({str(home / '.config' / 'gh' / 'hosts.yml')!r}),"
                f" 'tree': can_write({str(root / 'w.txt')!r}), 'state': can_write({str(state / 'w.txt')!r}), 'cwd': os.getcwd()}}))\n")
        done = subprocess.run(jail.wrap_for(root)([sys.executable, "-c", prog]), cwd=root, env=isolation.child_env({}, jail.home),
                              capture_output=True, text=True, timeout=60)
        assert done.returncode == 0, done.stderr
        seen = json.loads(done.stdout)
        assert seen == {"token": None, "home": str(home), "listing": [], "login": False, "gh": False, "tree": True, "state": False, "cwd": str(root)}


@needs_bwrap
def test_under_bwrap_redgreen_runs_the_main_pass_in_the_main_tree_and_the_spy_sees_nothing(secrets):
    with scratch("gate-jail-") as tmp:
        base, head, changes = _trees(tmp)
        state = tmp / "state"
        state.mkdir()
        jail = isolation.make_jail(state, sys.executable)
        result = redgreen.check_redgreen(base, head, changes, python=sys.executable, env={"PYTHONPATH": "."}, wrap_for=jail.wrap_for, home=jail.home)
        assert result.status == PASS, result.reasons
        assert result.measured["red"] == ["tests/test_mod.py::test_the_child_sees_nothing_of_the_watcher"]  # red on main: it ran there


@needs_bwrap
def test_under_bwrap_the_whole_gate_approves_a_good_pr_with_the_default_jail(monkeypatch):
    with scratch("gate-jail-") as tmp:
        repo, base, head = scenario.make_repo(tmp, "good")
        monkeypatch.setenv("GH_TOKEN", "ghp_secret")
        report = gate.run_gate(_input(repo, base, head, n_mutants=3))
        assert {c.name: c.status for c in report.checks}["redgreen"] == PASS, [(c.name, c.reasons) for c in report.checks]
        assert {c.name: c.status for c in report.checks}["mutation"] == PASS


def test_make_jail_needs_bwrap_and_ignores_the_watcher_opt_out(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox, "engine", lambda *a, **k: None)
    monkeypatch.setenv(sandbox.OPT_OUT, "1")
    with pytest.raises(sandbox.SandboxUnavailable):
        isolation.make_jail(tmp_path, sys.executable)


def test_the_jail_wraps_with_bwrap_an_empty_home_and_the_tree_even_with_the_opt_out_set(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox, "engine", lambda *a, **k: "bwrap")
    monkeypatch.setenv(sandbox.OPT_OUT, "1")
    home, state = tmp_path / "home", tmp_path / "state"  # the state dir is beside HOME: one that holds HOME is refused (#1680)
    home.mkdir()
    state.mkdir()
    jail = isolation.make_jail(state, sys.executable, home=home)
    argv = jail.wrap_for(tmp_path / "head")(["python", "-c", "pass"])
    assert argv[0] == "bwrap" and argv[-3:] == ["python", "-c", "pass"]
    assert any(argv[i:i + 2] == ["--tmpfs", str(home)] for i in range(len(argv)))  # HOME is an empty tmpfs
    assert "--unshare-pid" in argv and "--die-with-parent" in argv
    assert argv[argv.index("--chdir") + 1] == str(tmp_path / "head")
    assert jail.home == home


def test_the_jail_refuses_a_state_dir_that_holds_the_home(tmp_path, monkeypatch):
    """A state dir that is HOME, or holds it, would give HOME back (#1680): the gate reports a sandbox error and runs nothing."""
    monkeypatch.setattr(sandbox, "engine", lambda *a, **k: "bwrap")
    home = tmp_path / "home"
    home.mkdir()
    for state in (tmp_path, home):
        with pytest.raises(sandbox.SandboxUnavailable, match="state dir"):
            isolation.make_jail(state, sys.executable, home=home)


def test_the_interpreter_of_a_venv_under_home_stays_visible_read_only_and_nothing_else_of_home_does(tmp_path):
    home = tmp_path / "home"
    (home / "proj" / ".venv" / "bin").mkdir(parents=True)
    (home / "proj" / ".venv" / "pyvenv.cfg").write_text("home = /usr/bin\n")
    (home / "proj" / ".venv" / "bin" / "python").write_text("")
    (home / ".ssh").mkdir()
    assert isolation._python_ro(str(home / "proj" / ".venv" / "bin" / "python"), home) == ("proj/.venv",)
    assert isolation._python_ro("/usr/bin/python3", home) == ()
