"""orient (brief and non-brief) must BLOCK quickly with a typed reason_code
when `--repo` (or cwd) is not inside a git work tree (issue #1318 cause 4:
an `orient` run outside a repo scanned `/root` for 163.7s). No Mapper
survey, no lexical file walk -- just a fast, typed refusal.
"""
from __future__ import annotations

import json
import time

from simplicio_loop import cli_impl


def test_orient_core_blocks_fast_on_non_git_dir(tmp_path):
    started = time.monotonic()
    payload, code = cli_impl._orient_core(
        tmp_path, "Edit a.html", None, verbose=True,
    )
    elapsed = time.monotonic() - started
    assert code == 2
    assert payload["status"] == "BLOCKED"
    assert payload["reason_code"] == "not_a_git_repo"
    assert elapsed < 2.0, elapsed


def test_orient_brief_blocks_fast_on_non_git_dir(tmp_path):
    started = time.monotonic()
    payload = cli_impl.orient_brief(tmp_path, ["Edit a.html"])
    elapsed = time.monotonic() - started
    assert payload["status"] == "BLOCKED"
    assert payload["reason_code"] == "not_a_git_repo"
    assert elapsed < 2.0, elapsed


def test_orient_cli_non_git_dir_prints_typed_reason(tmp_path, capsys):
    rc = cli_impl.orient(str(tmp_path), "Edit a.html")
    assert rc == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "BLOCKED"
    assert payload["reason_code"] == "not_a_git_repo"


def test_orient_git_repo_is_unaffected(tmp_path):
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "a.html").write_text("<html></html>", encoding="utf-8")
    payload, code = cli_impl._orient_core(
        tmp_path, "Edit a.html", None, verbose=True,
    )
    assert payload.get("reason_code") != "not_a_git_repo"
