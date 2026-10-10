"""`simplicio-loop handoff check` and the ceiling of the default branch (#1608, part B)."""
from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path

import pytest

from simplicio_loop import cli_impl, handoff_cli
from simplicio_loop.input_ceiling import CeilingConfigError, DEFAULT_CEILING, ENV_NAME, TOML_KEY

GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false"]


# --- ceiling_from: pure ------------------------------------------------------------------------------------------------

def test_default_when_nothing_is_set():
    assert handoff_cli.ceiling_from({}, {}) == DEFAULT_CEILING == 98_000


def test_config_key_sets_the_ceiling():
    assert handoff_cli.ceiling_from({TOML_KEY: 50_000}, {}) == 50_000


def test_environment_wins_over_the_config():
    assert handoff_cli.ceiling_from({TOML_KEY: 50_000}, {ENV_NAME: "70000"}) == 70_000


def test_it_reads_only_what_it_is_given(monkeypatch):
    monkeypatch.setenv(ENV_NAME, "123")
    assert handoff_cli.ceiling_from({}, {}) == DEFAULT_CEILING


@pytest.mark.parametrize("raw", ["", "0", "-5", "abc", "1.5", "98000\n", " 98000", "1000001", "99999999"])
def test_a_bad_environment_value_fails_loud_even_with_a_good_config(raw):
    with pytest.raises(CeilingConfigError):
        handoff_cli.ceiling_from({TOML_KEY: 50_000}, {ENV_NAME: raw})


@pytest.mark.parametrize("value", [0, -1, True, 1.5, "98000", None, 1_000_001, [98000]])
def test_a_bad_config_value_fails_loud_without_falling_back(value):
    with pytest.raises(CeilingConfigError):
        handoff_cli.ceiling_from({TOML_KEY: value}, {})


def test_the_limits_of_the_range_are_accepted():
    assert handoff_cli.ceiling_from({TOML_KEY: 1}, {}) == 1
    assert handoff_cli.ceiling_from({TOML_KEY: 1_000_000}, {}) == 1_000_000


# --- the config comes from the default branch, never from the local clone --------------------------------------------

def git(cwd, *args):
    return subprocess.run(GIT + list(args), cwd=cwd, check=True, capture_output=True, text=True).stdout


def make_clone(tmp_path, toml):
    origin, seed, clone = tmp_path / "origin.git", tmp_path / "seed", tmp_path / "clone"
    git(tmp_path, "init", "--bare", "-b", "main", str(origin))
    git(tmp_path, "init", "-b", "main", str(seed))
    (seed / "README.md").write_text("x\n", encoding="utf-8")
    if toml is not None:
        (seed / ".simplicio-loop").mkdir()
        (seed / ".simplicio-loop" / "loop.toml").write_text(toml, encoding="utf-8")
    git(seed, "add", "-A")
    git(seed, "commit", "-m", "seed")
    git(seed, "remote", "add", "origin", str(origin))
    git(seed, "push", "origin", "main")
    git(tmp_path, "clone", str(origin), str(clone))
    return clone


def run(capsys, *argv):
    code = cli_impl.main(["handoff", *argv])
    out = capsys.readouterr()
    return code, out.out, out.err


def check(capsys, repo, total, added=None):
    argv = ["check", "--repo", str(repo), "--input-tokens", str(total), "--cache-read", "0", "--cache-write", "0"]
    if added is not None:
        argv += ["--added-file", str(added)]
    code, out, err = run(capsys, *argv)
    return code, (json.loads(out) if out else None), err


@pytest.fixture(autouse=True)
def no_env(monkeypatch):
    monkeypatch.delenv(ENV_NAME, raising=False)


def test_the_ceiling_is_the_one_in_the_default_branch(tmp_path, capsys):
    clone = make_clone(tmp_path, "%s = 50000\n" % TOML_KEY)
    code, out, _ = check(capsys, clone, 46_000)
    assert out["ceiling"] == 50_000 and out["status"] == "handoff" and code == 3


def test_a_local_edit_of_the_config_cannot_raise_the_ceiling(tmp_path, capsys):
    clone = make_clone(tmp_path, "%s = 50000\n" % TOML_KEY)
    toml = clone / ".simplicio-loop" / "loop.toml"
    toml.write_text("%s = 900000\n" % TOML_KEY, encoding="utf-8")  # uncommitted edit
    assert check(capsys, clone, 46_000)[1]["ceiling"] == 50_000
    git(clone, "commit", "-am", "raise the ceiling")  # committed on the local branch, not pushed
    assert check(capsys, clone, 46_000)[1]["ceiling"] == 50_000


def test_a_default_branch_without_the_file_means_the_default_ceiling(tmp_path, capsys):
    clone = make_clone(tmp_path, None)
    (clone / ".simplicio-loop").mkdir()
    (clone / ".simplicio-loop" / "loop.toml").write_text("%s = 10\n" % TOML_KEY, encoding="utf-8")
    out = check(capsys, clone, 10)[1]
    assert out["ceiling"] == DEFAULT_CEILING and out["status"] == "ok"


def test_a_default_branch_without_the_key_means_the_default_ceiling(tmp_path, capsys):
    clone = make_clone(tmp_path, "other = 1\n")
    assert check(capsys, clone, 10)[1]["ceiling"] == DEFAULT_CEILING


def test_a_broken_config_in_the_default_branch_fails_loud(tmp_path, capsys):
    clone = make_clone(tmp_path, "%s = 'lots'\n" % TOML_KEY)
    code, out, err = check(capsys, clone, 10)
    assert code == 2 and out is None
    assert json.loads(err)["reason_code"] == "ceiling_invalid"


def test_a_toml_syntax_error_in_the_default_branch_fails_loud(tmp_path, capsys):
    clone = make_clone(tmp_path, "this is = = not toml\n")
    code, out, err = check(capsys, clone, 10)
    assert code == 2 and json.loads(err)["reason_code"] == "ceiling_invalid"


def test_the_environment_wins_and_needs_no_git(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv(ENV_NAME, "1000")
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    code, out, _ = check(capsys, plain, 950)
    assert out["ceiling"] == 1000 and out["status"] == "handoff" and code == 3


def test_without_a_default_branch_and_without_env_it_fails_loud(tmp_path, capsys):
    plain = tmp_path / "plain"
    git(tmp_path, "init", "-b", "main", str(plain))
    code, out, err = check(capsys, plain, 10)
    assert code == 2 and out is None
    assert json.loads(err)["reason_code"] == "default_branch_unresolved"


# --- check: the projection of the NEXT request --------------------------------------------------------------------------

@pytest.fixture
def small(monkeypatch):
    monkeypatch.setenv(ENV_NAME, "1000")


def usage(capsys, new, read, write, *extra):
    code, out, err = run(capsys, "check", "--input-tokens", str(new), "--cache-read", str(read),
                         "--cache-write", str(write), *extra)
    return code, (json.loads(out) if out else None), err


@pytest.mark.parametrize("new,read,write,status,code", [
    (100, 799, 0, "ok", 0),            # 899 of 1000: under 90%
    (100, 800, 0, "handoff", 3),       # 900 = 90%
    (1, 0, 999, "handoff", 3),         # a cache write counts
    (1000, 0, 0, "handoff", 3),        # the ceiling itself is still allowed
    (1, 1000, 0, "over", 4),           # 1001
    (0, 0, 1001, "over", 4),
])
def test_the_status_uses_the_total_prompt_and_the_exit_code_follows(capsys, small, new, read, write, status, code):
    got_code, out, _ = usage(capsys, new, read, write)
    assert (got_code, out["status"]) == (code, status)
    assert out["tokens"] == new + read + write
    assert out["ceiling"] == 1000 and out["soft_limit"] == 900
    assert out["headroom"] == 1000 - (new + read + write)


def test_cache_reads_and_writes_are_not_dropped(capsys, small):
    assert usage(capsys, 1, 0, 0)[1]["status"] == "ok"
    assert usage(capsys, 1, 899, 0)[1]["status"] == "handoff"
    assert usage(capsys, 1, 0, 899)[1]["status"] == "handoff"


def test_a_measured_count_is_labelled_measured_and_has_a_measured_base(capsys, small):
    out = usage(capsys, 100, 200, 300)[1]
    assert out["basis"] == "MEASURED" and out["measured_base"] == 600
    assert out["tokens"] == 600 + out["estimated_tokens"] and out["estimated_tokens"] == 0


def test_the_text_to_be_added_is_projected_on_top_of_the_measured_total(capsys, small, tmp_path):
    added = tmp_path / "added.txt"
    added.write_text("word " * 800, encoding="utf-8")
    code, out, _ = usage(capsys, 100, 200, 0, "--added-file", str(added))
    assert out["basis"] == "MEASURED" and out["measured_base"] == 300
    assert out["estimated_tokens"] > 300 and out["tokens"] == 300 + out["estimated_tokens"]
    assert out["status"] == "over" and code == 4


def test_the_added_text_can_come_from_stdin(capsys, small, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("word " * 800))
    out = usage(capsys, 100, 200, 0, "--added-file", "-")[1]
    assert out["estimated_tokens"] > 300


def test_no_usage_means_estimated_from_the_prompt_text(capsys, small, tmp_path):
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("word " * 1000, encoding="utf-8")
    code, out, _ = run(capsys, "check", "--prompt-file", str(prompt))
    out = json.loads(out)
    assert out["basis"] == "ESTIMATED" and out["measured_base"] is None
    assert out["estimator"] == "conservative-v2" and out["tokens"] == out["estimated_tokens"] > 300
    assert out["status"] == "over" and code == 4


@pytest.mark.parametrize("argv", [
    ["check"],                                                                            # nothing
    ["check", "--input-tokens", "1", "--cache-read", "1"],                                # a counter missing
    ["check", "--input-tokens", "1", "--cache-read", "1", "--cache-write", "1", "--prompt-file", "x"],
    ["check", "--input-tokens", "-1", "--cache-read", "0", "--cache-write", "0"],        # negative
    ["check", "--input-tokens", "0", "--cache-read", "0", "--cache-write", "0"],         # a zero prompt is no measurement
])
def test_bad_usage_input_fails_loud_and_prints_no_verdict(capsys, small, argv):
    code, out, err = run(capsys, *argv)
    assert code == 2 and out == ""
    assert json.loads(err)["status"] == "error"


def test_added_text_is_for_the_measured_counters_only(capsys, small, tmp_path):
    prompt = tmp_path / "p.txt"
    prompt.write_text("hello", encoding="utf-8")
    code, out, err = run(capsys, "check", "--prompt-file", str(prompt), "--added-file", str(prompt))
    assert code == 2 and out == "" and json.loads(err)["reason_code"] == "usage_invalid"


def test_an_unreadable_added_file_fails_loud(capsys, small, tmp_path):
    code, out, err = usage(capsys, 1, 1, 1, "--added-file", str(tmp_path / "missing.txt"))
    assert code == 2 and out is None and json.loads(err)["reason_code"] == "handoff_input_invalid"
