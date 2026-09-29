"""3.45.2 host mode: two commands. The invoking model plans and dev-cli applies. No provider call and no key."""
from __future__ import annotations

import io
import json
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from simplicio_loop import turbo_provider
from simplicio_loop.cli_impl import main as cli_main

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "bench" / "llm_ab" / "fixture_hard"
SOLUTION = ROOT / "tests" / "fixtures" / "llm_ab_hard_solution"
HIDDEN = ROOT / "bench" / "llm_ab" / "hidden" / "check_hard.py"
RULES = ("Write the plan from the file contents above; do not open, list or read other files; "
         "do not run tests yourself; run the command below once.")
FORMAT = {"operations": [{"path": "<repo-relative>", "find": "<exact text that occurs once; empty creates the file>",
                          "replace": "<new text>"}]}


def _seed(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE, repo)
    for args in (["init", "-q"], ["config", "user.email", "a@b.c"], ["config", "user.name", "a"],
                 ["add", "-A"], ["commit", "-qm", "seed"]):
        subprocess.run(["git", *args], cwd=repo, check=True)
    state = repo / ".simplicio-loop"
    state.mkdir(exist_ok=True)
    project = {"schema": "simplicio.project-map/v1", "product": "shop-utils",
               "files": [{"path": "inventory.py", "symbols": ["Inventory"]},
                         {"path": "shop/report.py", "symbols": ["summary"]},
                         {"path": "shop/invoice.py", "symbols": ["invoice_total"]}]}
    (state / "project-map.json").write_text(json.dumps(project), encoding="utf-8")
    return repo


def _solution_ops(repo: Path, rels):
    ops = []
    for rel in rels:
        old = (repo / rel).read_text(encoding="utf-8") if (repo / rel).is_file() else ""
        ops.append({"path": rel, "find": old, "replace": (SOLUTION / rel).read_text(encoding="utf-8")})
    return ops


@pytest.fixture
def host(monkeypatch):
    """Host mode never touches the provider, even when a key is present in the environment."""
    def boom(*args, **kwargs):
        raise AssertionError("host mode called the provider")

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-must-be-ignored")
    monkeypatch.setattr(turbo_provider, "complete", boom)
    monkeypatch.setattr(turbo_provider, "require_key", boom)
    monkeypatch.setattr("simplicio_loop.cli_impl._ensure_project_map", lambda root, **kwargs: None)


class _Stdin:
    """Standard input as the CLI sees it: raw bytes behind `.buffer`, and a terminal flag."""

    def __init__(self, data: bytes | str = b"", tty: bool = False) -> None:
        self.buffer = io.BytesIO(data.encode("utf-8") if isinstance(data, str) else data)
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty

    def read(self, *args):
        raise AssertionError("the plan is UTF-8 bytes: read stdin.buffer, not the locale-decoded text stream")


def _request(repo: Path, capsys, *extra: str):
    rc = cli_main(["turbo", "--repo", str(repo), *extra])
    return rc, json.loads(capsys.readouterr().out)


def _apply_stdin(repo: Path, capsys, monkeypatch, plan: bytes | str, *extra: str, tty: bool = False):
    monkeypatch.setattr(sys, "stdin", _Stdin(plan, tty))
    rc = cli_main(["turbo", "--repo", str(repo), "--apply", "-", *extra])
    return rc, json.loads(capsys.readouterr().out)


def _printed_command(apply: str) -> tuple[list[str], str]:
    """Split the printed apply command into the argv after `simplicio-loop` and its heredoc body placeholder."""
    first, placeholder, terminator = apply.split("\n")
    assert first.endswith(" <<'PLAN'") and terminator == "PLAN"
    argv = shlex.split(first.removesuffix(" <<'PLAN'"))
    assert argv[0] == "simplicio-loop"
    return argv[1:], placeholder


def _flat(text: str) -> str:
    return re.sub(r"\s+", "", text)


def test_the_request_is_compact_and_ends_with_the_one_apply_command(tmp_path, host, capsys):
    repo = _seed(tmp_path)
    rc, out = _request(repo, capsys, "--task", "Fix the two bugs in inventory.py.", "--verify", "pytest -q")
    assert rc == 0
    assert list(out) == ["schema", "status", "mode", "reason", "tasks", "map", "files", "format", "rules", "apply"]
    assert out["schema"] == "simplicio.turbo-request/v1" and out["status"] == "needs_plan" and out["mode"] == "host"
    assert out["reason"] == "hybrid_unavailable: no_host_detected"  # no host CLI to call: the two-command flow (3.47.0)
    assert out["tasks"] == ["Fix the two bugs in inventory.py."]
    assert out["files"] == {"inventory.py": (FIXTURE / "inventory.py").read_text(encoding="utf-8")}
    # One task: only its slice of the Mapper map.
    assert out["map"] == {"schema": "simplicio.project-map/v1", "product": "shop-utils",
                          "files": [{"path": "inventory.py", "symbols": ["Inventory"]}]}
    assert out["format"] == FORMAT and out["rules"] == RULES
    assert out["apply"] == (f"simplicio-loop turbo --repo {shlex.quote(str(repo.resolve()))} --apply - "
                            "--verify 'pytest -q' <<'PLAN'\n<JSON plan>\nPLAN")
    text = json.dumps(out)
    assert text.count("Fix the two bugs in inventory.py.") == 1  # one task list, not two
    assert "plan_path" not in out and "prompt" not in out and "You plan simplicio edits" not in text


def test_the_request_leaves_no_request_or_plan_file_in_the_repository(tmp_path, host, capsys):
    repo = _seed(tmp_path)
    _request(repo, capsys, "--task", "Fix the two bugs in inventory.py.")
    assert not (repo / ".simplicio-loop" / "turbo").exists()
    status = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=repo, capture_output=True,
                            text=True, check=True).stdout
    assert status == ""  # no tracked file was touched


def test_the_request_without_verify_prints_a_plain_apply_command(tmp_path, host, capsys):
    repo = _seed(tmp_path)
    rc, out = _request(repo, capsys, "--task", "Fix inventory.py")
    assert rc == 0
    assert out["apply"] == (f"simplicio-loop turbo --repo {shlex.quote(str(repo.resolve()))} --apply - <<'PLAN'"
                            "\n<JSON plan>\nPLAN")


def test_several_tasks_share_one_request_and_each_file_appears_once(tmp_path, host, capsys):
    rc, out = _request(_seed(tmp_path), capsys, "--task", "Create pricing.py with order_total as specified.",
                       "--task", "Fix the two bugs in inventory.py.", "--task", "Then tidy inventory.py")
    assert rc == 0
    assert out["tasks"] == ["Create pricing.py with order_total as specified.", "Fix the two bugs in inventory.py.",
                            "Then tidy inventory.py"]
    assert list(out["files"]) == ["inventory.py"]  # pricing.py does not exist yet: an empty find creates it
    assert [f["path"] for f in out["map"]["files"]] == ["inventory.py"]  # the slice follows every named file


def test_a_file_past_the_cap_is_cut_and_says_so(tmp_path, host, capsys):
    repo = _seed(tmp_path)
    (repo / "big.py").write_text("x = 1\n" * 3000, encoding="utf-8")
    rc, out = _request(repo, capsys, "--task", "Edit big.py")
    assert rc == 0 and out["files"]["big.py"].startswith("x = 1\n")
    assert len(out["files"]["big.py"]) < 6200 and "truncated" in out["files"]["big.py"].splitlines()[-1]


def test_the_request_without_a_task_is_blocked(tmp_path, host, capsys):
    rc, out = _request(_seed(tmp_path), capsys)
    assert rc == 2 and out["status"] == "blocked" and out["reason_code"] == "turbo_no_tasks" and out["mode"] == "host"


def test_the_printed_command_runs_as_printed_in_one_call(tmp_path, host, capsys, monkeypatch):
    repo = _seed(tmp_path)
    verify = f'"{sys.executable}" "{HIDDEN}" --stage 1 && "{sys.executable}" "{HIDDEN}" --stage 2'
    rc, request = _request(repo, capsys, "--task", "Create pricing.py with order_total as specified.",
                           "--task", "Fix the two bugs in inventory.py.", "--verify", verify)
    assert rc == 0 and len(request["tasks"]) == 2
    argv, placeholder = _printed_command(request["apply"])
    assert placeholder == "<JSON plan>"
    plan = json.dumps({"operations": _solution_ops(repo, ["pricing.py", "inventory.py"])})
    monkeypatch.setattr(sys, "stdin", _Stdin(plan))
    rc = cli_main(argv)  # the one call: the plan is the heredoc body
    out = json.loads(capsys.readouterr().out)
    assert rc == 0, out
    assert out["schema"] == "simplicio.turbo-run/v1" and out["mode"] == "host" and out["status"] == "ok"
    assert out["applied"] == ["pricing.py", "inventory.py"] and out["failed"] == []
    assert out["verify"]["passed"] is True


@pytest.mark.skipif(sys.platform == "win32", reason="the printed heredoc is POSIX shell syntax")
def test_the_printed_command_survives_a_real_shell_with_quotes_dollars_and_backticks(tmp_path, host, capsys):
    """`<<'PLAN'` is quoted, so the plan reaches stdin byte for byte: no expansion of $, backticks or quotes."""
    repo = _seed(tmp_path)
    rc, request = _request(repo, capsys, "--task", "Create note.py", "--verify", f'"{sys.executable}" -c "print(1)"')
    assert rc == 0
    tricky = 'print("it\'s $HOME `date` \\\\n ação")\n'
    plan = json.dumps({"operations": [{"path": "note.py", "find": "", "replace": tricky}]})
    script = request["apply"].replace("<JSON plan>", plan)
    shim = tmp_path / "bin"
    shim.mkdir()
    (shim / "simplicio-loop").write_text(
        f'#!/bin/sh\nexec "{sys.executable}" -c "import sys; from simplicio_loop.cli import main; sys.exit(main())" "$@"\n',
        encoding="utf-8")
    (shim / "simplicio-loop").chmod(0o755)
    env = {"PATH": f"{shim}:/usr/bin:/bin", "HOME": str(tmp_path), "LANG": "C"}
    proc = subprocess.run(["/bin/sh", "-c", script], cwd=tmp_path, env=env, capture_output=True, text=True,
                          timeout=120, check=False)
    out = json.loads(proc.stdout)
    assert proc.returncode == 0 and out["status"] == "ok" and out["applied"] == ["note.py"], (proc.stdout, proc.stderr)
    assert out["verify"]["passed"] is True
    assert (repo / "note.py").read_text(encoding="utf-8") == tricky


def test_apply_dash_reads_the_plan_from_stdin_as_utf8(tmp_path, host, capsys, monkeypatch):
    repo = _seed(tmp_path)
    text = "Olá, cadastro — ação\n"
    plan = json.dumps({"operations": [{"path": "notes.txt", "find": "", "replace": text}]}, ensure_ascii=False)
    rc, out = _apply_stdin(repo, capsys, monkeypatch, plan)
    assert rc == 0 and out["status"] == "ok" and out["applied"] == ["notes.txt"] and out["mode"] == "host"
    assert (repo / "notes.txt").read_text(encoding="utf-8") == text


@pytest.mark.parametrize("data", [b"", b"  \n\t\n"])
def test_an_empty_stdin_is_failed_with_a_typed_reason(tmp_path, host, capsys, monkeypatch, data):
    rc, out = _apply_stdin(_seed(tmp_path), capsys, monkeypatch, data)
    assert rc == 1 and out["status"] == "failed" and out["reason_code"] == "turbo_plan_missing"
    assert "stdin" in out["detail"] and "<<'PLAN'" in out["detail"]


def test_a_terminal_on_stdin_is_never_waited_on(tmp_path, host, capsys, monkeypatch):
    rc, out = _apply_stdin(_seed(tmp_path), capsys, monkeypatch, b'{"operations": []}', tty=True)
    assert rc == 1 and out["status"] == "failed" and out["reason_code"] == "turbo_plan_missing"
    assert "terminal" in out["detail"] and "<<'PLAN'" in out["detail"]
    assert sys.stdin.buffer.tell() == 0  # nothing was read


def test_a_closed_stdin_is_failed_with_a_typed_reason_too(tmp_path, host, capsys, monkeypatch):
    monkeypatch.setattr(sys, "stdin", None)  # `simplicio-loop turbo --apply - <&-`
    rc = cli_main(["turbo", "--repo", str(_seed(tmp_path)), "--apply", "-"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 1 and out["status"] == "failed" and out["reason_code"] == "turbo_plan_missing"
    assert "closed" in out["detail"]


def test_a_stdin_plan_that_is_not_utf8_is_malformed(tmp_path, host, capsys, monkeypatch):
    rc, out = _apply_stdin(_seed(tmp_path), capsys, monkeypatch, b'{"operations": [\xff\xfe]}')
    assert rc == 1 and out["status"] == "failed" and out["reason_code"] == "turbo_plan_malformed" and out["format"] == FORMAT


def test_a_find_that_does_not_match_fails_with_the_reason_and_an_excerpt(tmp_path, host, capsys, monkeypatch):
    repo = _seed(tmp_path)
    plan = json.dumps({"operations": [
        {"path": "inventory.py", "find": "class Inventory:\n    def nothing(self):\n        pass\n", "replace": "x\n"}]})
    rc, out = _apply_stdin(repo, capsys, monkeypatch, plan)
    assert rc == 1 and out["status"] == "failed" and out["mode"] == "host" and out["applied"] == []
    (entry,) = out["failed"]
    assert entry["path"] == "inventory.py" and entry["reason"]
    assert "class Inventory:" in entry["excerpt"] and len(entry["excerpt"]) <= 700
    assert out["verify"] is None
    assert (repo / "inventory.py").read_text(encoding="utf-8") == (FIXTURE / "inventory.py").read_text(encoding="utf-8")


def test_a_failing_verify_reports_failed_with_its_output(tmp_path, host, capsys, monkeypatch):
    repo = _seed(tmp_path)
    plan = json.dumps({"operations": [{"path": "notes.txt", "find": "", "replace": "hello\n"}]})
    rc, out = _apply_stdin(repo, capsys, monkeypatch, plan, "--verify",
                           f'"{sys.executable}" -c "print(1); raise SystemExit(3)"')
    assert rc == 1 and out["status"] == "failed" and out["applied"] == ["notes.txt"]
    assert out["verify"]["passed"] is False and out["verify"]["returncode"] == 3
    assert (repo / "notes.txt").read_text(encoding="utf-8") == "hello\n"


MALFORMED = [
    "not json at all",
    '{"operations": []}',
    '{"operations": [{"path": 3, "find": "", "replace": "x"}]}',
    '{"operations": [{"find": "", "replace": "x"}]}',
]


@pytest.mark.parametrize("text", MALFORMED)
def test_a_malformed_stdin_plan_is_failed_with_a_typed_reason(tmp_path, host, capsys, monkeypatch, text):
    rc, out = _apply_stdin(_seed(tmp_path), capsys, monkeypatch, text)
    assert rc == 1 and out["status"] == "failed" and out["reason_code"] == "turbo_plan_malformed" and out["detail"]


@pytest.mark.parametrize("text", MALFORMED)
def test_a_malformed_plan_file_is_failed_with_a_typed_reason(tmp_path, host, capsys, text):
    repo = _seed(tmp_path)
    (repo / "plan.json").write_text(text, encoding="utf-8")
    rc, out = _request(repo, capsys, "--apply", "plan.json")
    assert rc == 1 and out["status"] == "failed" and out["reason_code"] == "turbo_plan_malformed" and out["detail"]


def test_the_plan_file_form_is_the_same_code_path(tmp_path, host, capsys):
    repo = _seed(tmp_path)
    (repo / "plan.json").write_text(json.dumps({"operations": [
        {"path": "notes.txt", "find": "", "replace": "from a file\n"}]}), encoding="utf-8")
    rc, out = _request(repo, capsys, "--apply", "plan.json")
    assert rc == 0 and out["status"] == "ok" and out["applied"] == ["notes.txt"]
    assert (repo / "notes.txt").read_text(encoding="utf-8") == "from a file\n"


def test_a_missing_plan_file_is_failed_with_a_typed_reason(tmp_path, host, capsys):
    rc, out = _request(_seed(tmp_path), capsys, "--apply", "nowhere/plan.json")
    assert rc == 1 and out["status"] == "failed" and out["reason_code"] == "turbo_plan_missing"


def test_the_provider_is_an_explicit_opt_in_and_needs_its_key(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    rc, out = _request(_seed(tmp_path), capsys, "--provider", "openrouter", "--task", "fix inventory.py")
    assert rc == 2 and out["status"] == "blocked" and out["reason_code"] == "turbo_provider_key_missing"


def test_a_key_in_the_environment_does_not_turn_the_provider_on(tmp_path, host, capsys):
    rc, out = _request(_seed(tmp_path), capsys, "--task", "fix inventory.py")
    assert rc == 0 and out["status"] == "needs_plan"  # `host` makes any provider call raise


def test_turbo_help_describes_two_commands_stdin_and_a_provider_for_automation_only(capsys):
    with pytest.raises(SystemExit):
        cli_main(["turbo", "--help"])
    text = _flat(capsys.readouterr().out)
    for needle in ("--apply", "stdin", "needs_plan", "<<'PLAN'", "exactlytwocommands"):
        assert _flat(needle) in text, needle
    assert "--provider" in text and "OPENROUTER_API_KEY" in text and "deepseek/deepseek-v4.1-flash" in text
    assert _flat("headless automation only; agents invoking the skill must not use it") in text
