"""The planner's raw reply is kept per step (#1644): redacted before it is cut, bounded, written before the apply."""
import json
import re

import pytest

from simplicio_loop.watcher247 import config, raw_log
from simplicio_loop.watcher247.raw_log import RAW_LOG_CHARS, clip

from .fakes import baseline, issue, run_tick
from .test_host_mode import OK, PLAN, REPO, HostRun, checkout, cli_dir  # noqa: F401  (cli_dir is a fixture)

SK = "sk-" + "A1b2C3d4E5" * 3
GHP = "ghp_" + "Qw3rTy9uIo" * 3 + "Zx1234"


def test_secrets_are_redacted_in_every_shape():
    raw = f"key {SK} token {GHP} header Authorization: Bearer abcdefghij0123456789xyz\nAPI_KEY=supersecretvalue99 end"
    out = clip(raw)
    for leaked in (SK, GHP, "abcdefghij0123456789xyz", "supersecretvalue99"):
        assert leaked not in out
    assert "REDACTED" in out and out.startswith("key ") and out.rstrip().endswith("end")


def test_a_secret_crossing_the_cut_does_not_leak():
    for pad in range(RAW_LOG_CHARS - 40, RAW_LOG_CHARS + 5):  # the secret starts before, at and after the cut
        out = clip("x" * pad + " " + SK + " tail")
        assert "sk-" not in out and "A1b2C3d4E5" not in out, pad


def test_a_huge_reply_is_cut_with_the_count_of_what_was_dropped():
    raw = "line of the model\n" * 5000
    out = clip(raw)
    assert out.startswith("line of the model\n") and len(out) < RAW_LOG_CHARS + 80
    assert out.endswith(f"\n[truncado: {len(raw) - RAW_LOG_CHARS} caracteres]\n")


def test_a_reply_at_the_limit_is_kept_whole():
    assert clip("y" * RAW_LOG_CHARS) == "y" * RAW_LOG_CHARS


def test_no_reply_says_why(tmp_path):
    assert "timeout" in clip(None, "timeout")
    raw_log.write(tmp_path / "deep" / "x.raw.log", None, "cli_missing")
    assert "cli_missing" in (tmp_path / "deep" / "x.raw.log").read_text()


def _stub(cli_dir, source):
    claude = cli_dir / "claude"
    claude.write_text("#!/usr/bin/env python3\nimport json, sys\nif sys.argv[1:2] == ['auth']:\n    sys.exit(0)\n" + source)


def _raw_logs():
    return sorted(config.LOGS.glob(f"{REPO}-7-*-s*.raw.log"))


def test_the_raw_text_lands_before_the_apply_and_is_redacted(env, cli_dir):
    _stub(cli_dir, f"print('thinking with {SK} then:')\nprint(json.dumps({{'result': json.dumps({PLAN!r})}}))\n")
    fake = env(HostRun({REPO: [issue(7)]}))
    baseline()
    checkout()
    run_tick()
    [path] = _raw_logs()
    assert path.name == f"{REPO}-7-1-s1.raw.log"
    text = path.read_text()
    assert "thinking with" in text and "operations" in text and SK not in text and "REDACTED" in text
    assert (config.LOGS / f"{REPO}-7-1-s1.log").exists() and fake.turbo_stdin  # the apply log still exists, beside it


def test_an_empty_plan_still_leaves_the_raw_file(env, cli_dir):
    _stub(cli_dir, f"print('I could not plan this. {GHP}')\n")
    env(HostRun({REPO: [issue(7)]}))
    baseline()
    checkout()
    run_tick()
    paths = _raw_logs()
    assert paths and all("I could not plan this." in p.read_text() and GHP not in p.read_text() for p in paths)


def test_a_failed_planner_leaves_the_raw_file_with_stdout_and_stderr(env, cli_dir):
    _stub(cli_dir, "print('partial answer')\nsys.stderr.write('quota exceeded for sk-" + "Z9" * 15 + "')\nsys.exit(3)\n")
    env(HostRun({REPO: [issue(7)]}))
    baseline()
    checkout()
    run_tick()
    [path] = _raw_logs()
    text = path.read_text()
    assert "partial answer" in text and "quota exceeded" in text and "Z9Z9Z9" not in text
