"""`python -m simplicio_loop.review_gate`: exit code, JSON, the comment text and the gh calls (Parte de #1649)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from simplicio_loop.review_gate import cli
from tests.review_gate import scenario

ROOT = Path(__file__).resolve().parents[2]
ISSUE = "Limitar.\n\n- [ ] `clamp` existe em `mod.py`\n"
PR = "Entrega `clamp`.\n\nParte de #7\n"


def _argv(tmp_path, repo, base, head, *extra, bodies=True):
    argv = ["--repo", str(repo), "--pr", "11", "--issue", "7", "--base", base, "--head", head, "--author", "worker-1", *extra]
    if bodies:
        (tmp_path / "issue.md").write_text(ISSUE, encoding="utf-8")
        (tmp_path / "pr.md").write_text(PR, encoding="utf-8")
        argv += ["--issue-body-file", str(tmp_path / "issue.md"), "--pr-body-file", str(tmp_path / "pr.md")]
    return argv


@pytest.fixture
def notest(tmp_path):
    """A head the gate rejects without running a test: fast. (tmp_path, repo, base, head)"""
    (tmp_path / "w").mkdir()
    return (tmp_path, *scenario.make_repo(tmp_path / "w", "notest"))


def test_a_rejected_pr_exits_1_and_prints_the_rejection_comment(notest, capsys):
    tmp, repo, base, head = notest
    code = cli.main(_argv(tmp, repo, base, head))
    out = capsys.readouterr().out
    assert code == 1
    assert out.splitlines()[0] == "REVISÃO AUTOMÁTICA: REPROVADA (nível 1)"
    assert "- autor: worker-1 (worker, unknown, local)" in out and "- revisor automatico: review-gate/auto" in out
    assert "- redgreen: fail" in out and "mudanca de producao sem teste novo" in out
    assert "git diff " + base[:7] + "..." + head[:7] in out and "mutacao: amostra de 12 mutantes" in out


def test_json_prints_a_parseable_report_with_approved_false_and_the_same_exit_code(notest, capsys):
    tmp, repo, base, head = notest
    code = cli.main(_argv(tmp, repo, base, head, "--json"))
    data = json.loads(capsys.readouterr().out)
    assert code == 1 and data["approved"] is False and data["schema"] == "simplicio.review-gate/v1"
    assert data["pr"] == 11 and data["issue"] == 7 and data["head"] == head and data["level"] == "T1"
    assert [c["name"] for c in data["checks"]][:2] == ["redgreen", "mutation"]
    saved = repo / ".simplicio-loop" / "review-gate" / f"pr-11-{head[:7]}.json"
    assert json.loads(saved.read_text(encoding="utf-8")) == data


def test_author_options_reach_the_identity_check(notest, capsys):
    tmp, repo, base, head = notest
    cli.main(_argv(tmp, repo, base, head, "--json", "--author", "review-gate/auto", "--author-role", "automatic-reviewer",
                   "--author-model", "m1", "--host", "h1"))
    identity = next(c for c in json.loads(capsys.readouterr().out)["checks"] if c["name"] == "identity")
    assert identity["status"] == "fail" and "auto-aprovacao" in identity["reasons"][0]
    assert identity["measured"]["author"] == {"agent_id": "review-gate/auto", "role": "automatic-reviewer", "model": "m1", "host": "h1"}


def test_mutants_and_min_kill_reach_the_gate(notest, capsys, monkeypatch):
    tmp, repo, base, head = notest
    seen = {}
    real = cli.gate.run_gate

    def spy(inp):
        seen.update(n=inp.n_mutants, kill=inp.min_kill, pr=inp.pr, issue=inp.issue, issue_body=inp.issue_body, pr_body=inp.pr_body,
                    repo=inp.repo, base=inp.base, head=inp.head)
        return real(inp)

    monkeypatch.setattr(cli.gate, "run_gate", spy)
    cli.main(_argv(tmp, repo, base, head, "--mutants", "3", "--min-kill", "0.9"))
    assert "mutacao: amostra de 3 mutantes" in capsys.readouterr().out
    assert seen == {"n": 3, "kill": 0.9, "pr": 11, "issue": 7, "issue_body": ISSUE, "pr_body": PR, "repo": repo.resolve(), "base": base, "head": head}


def test_an_approved_pr_exits_0_and_prints_the_approval_line(tmp_path, capsys, monkeypatch):
    repo, base, head = scenario.make_repo(tmp_path, "good")
    from simplicio_loop.review_gate import model

    ok = tuple(model.CheckResult(n, model.PASS) for n in ("redgreen", "mutation"))  # the gate itself is covered by test_gate.py
    monkeypatch.setattr(cli.gate, "run_gate", lambda inp: model.GateReport(inp.pr, inp.issue, inp.head, model.Level.T1, ok, False, 1.0))
    code = cli.main(_argv(tmp_path, repo, base, head))
    out = capsys.readouterr().out
    assert code == 0 and out.splitlines()[0] == "REVISÃO AUTOMÁTICA: APROVADA (nível 1)"


# depende de usage/coverage corrigidos
def test_end_to_end_good_pr_exits_0_with_the_approval_comment(tmp_path, capsys):
    repo, base, head = scenario.make_repo(tmp_path, "good")
    code = cli.main(_argv(tmp_path, repo, base, head))
    out = capsys.readouterr().out
    assert code == 0, out
    assert out.splitlines()[0] == "REVISÃO AUTOMÁTICA: APROVADA (nível 1)"


def test_without_a_body_file_the_issue_and_pr_bodies_come_from_gh(notest, monkeypatch, capsys):
    tmp, repo, base, head = notest
    calls = []

    real_run = subprocess.run

    def fake(argv, **kw):
        if argv[0] != "gh":  # `subprocess` is one module: the gate's own git calls go through
            return real_run(argv, **kw)
        calls.append((argv, kw))
        return subprocess.CompletedProcess(argv, 0, stdout=json.dumps({"body": f"body of {argv[1]} {argv[3]}"}), stderr="")

    seen = {}
    real = cli.gate.run_gate
    monkeypatch.setattr(subprocess, "run", fake)
    monkeypatch.setattr(cli.gate, "run_gate", lambda inp: (seen.update(issue=inp.issue_body, pr=inp.pr_body), real(inp))[1])
    cli.main(_argv(tmp, repo, base, head, "--gh-repo", "org/name", bodies=False))
    assert seen == {"issue": "body of issue 7", "pr": "body of pr 11"}
    assert [c[0] for c in calls] == [["gh", "issue", "view", "7", "--json", "body", "--repo", "org/name"],
                                     ["gh", "pr", "view", "11", "--json", "body", "--repo", "org/name"]]
    assert all(c[1]["timeout"] == 60 and c[1]["capture_output"] and c[1]["text"] for c in calls)


def test_gh_without_gh_repo_does_not_pass_repo_and_without_issue_is_empty(monkeypatch):
    calls = []
    monkeypatch.setattr(cli.subprocess, "run", lambda argv, **kw: calls.append(argv) or subprocess.CompletedProcess(argv, 0, stdout='{"body": null}', stderr=""))
    assert cli._gh_body("pr", 5, None) == "" and calls == [["gh", "pr", "view", "5", "--json", "body"]]
    assert cli._gh_body("issue", None, "org/name") == "" and len(calls) == 1  # no number, no gh call


def test_a_failing_gh_stops_with_the_cause(monkeypatch):
    monkeypatch.setattr(cli.subprocess, "run", lambda argv, **kw: subprocess.CompletedProcess(argv, 1, stdout="", stderr="HTTP 404: Not Found\n"))
    with pytest.raises(SystemExit) as caught:
        cli._gh_body("issue", 7, "org/name")
    assert str(caught.value) == "gh issue view 7 failed: HTTP 404: Not Found"


def test_a_failing_gh_shows_only_the_last_200_chars_of_its_complaint(monkeypatch):
    monkeypatch.setattr(cli.subprocess, "run", lambda argv, **kw: subprocess.CompletedProcess(argv, 1, stdout="", stderr="z" * 300 + "END\n"))
    with pytest.raises(SystemExit) as caught:
        cli._gh_body("pr", 7, None)
    assert str(caught.value) == "gh pr view 7 failed: " + "z" * 197 + "END"


def test_a_body_file_wins_over_gh(tmp_path, monkeypatch):
    def forbidden(*a, **kw):
        raise AssertionError("gh must not run when a file is given")

    monkeypatch.setattr(cli.subprocess, "run", forbidden)
    (tmp_path / "b.md").write_text("from file é", encoding="utf-8")
    assert cli._text(str(tmp_path / "b.md"), "issue", 7, None) == "from file é"


def test_python_dash_m_runs_the_module():
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    done = subprocess.run([sys.executable, "-m", "simplicio_loop.review_gate", "--help"], capture_output=True, text=True, env=env, timeout=60, check=False)
    assert done.returncode == 0 and done.stdout.startswith("usage: python -m simplicio_loop.review_gate")
    assert "--pr-body-file" in done.stdout and "--min-kill" in done.stdout
    bare = subprocess.run([sys.executable, "-m", "simplicio_loop.review_gate"], capture_output=True, text=True, env=env, timeout=60, check=False)
    assert bare.returncode == 2 and "--repo" in bare.stderr  # argparse: missing required arguments


def _fake_gate(monkeypatch, seen):
    from simplicio_loop.review_gate import model

    def run(inp):
        seen["inp"] = inp
        return model.GateReport(inp.pr, inp.issue, inp.head, model.Level.T1, (model.CheckResult("redgreen", model.PASS),), False, 0.0)

    monkeypatch.setattr(cli.gate, "run_gate", run)


def test_defaults_of_the_options(tmp_path, monkeypatch, capsys):
    seen = {}
    _fake_gate(monkeypatch, seen)
    (tmp_path / "pr.md").write_text("pr", encoding="utf-8")
    assert cli.main(["--repo", str(tmp_path), "--pr", "4", "--base", "b" * 40, "--head", "h" * 40, "--pr-body-file", str(tmp_path / "pr.md")]) == 0
    inp = seen["inp"]
    assert inp.author == cli.identity.Agent("unknown", "worker", "unknown", "local")
    assert (inp.n_mutants, inp.min_kill, inp.issue, inp.issue_body, inp.pr_body) == (12, 0.6, None, "", "pr")
    assert "git diff bbbbbbb...hhhhhhh" in capsys.readouterr().out


def test_a_relative_repo_is_resolved_before_the_gate_runs(tmp_path, monkeypatch):
    seen = {}
    _fake_gate(monkeypatch, seen)
    (tmp_path / "w" / "clone").mkdir(parents=True)
    (tmp_path / "w" / "pr.md").write_text("x", encoding="utf-8")
    monkeypatch.chdir(tmp_path / "w")
    cli.main(["--repo", "clone", "--pr", "4", "--base", "b", "--head", "h", "--pr-body-file", "pr.md"])
    assert seen["inp"].repo == (tmp_path / "w" / "clone").resolve() and seen["inp"].repo.is_absolute()


def test_repo_pr_base_and_head_are_required(capsys):
    with pytest.raises(SystemExit) as caught:
        cli.main([])
    assert caught.value.code == 2
    assert "the following arguments are required: --repo, --pr, --base, --head" in capsys.readouterr().err
