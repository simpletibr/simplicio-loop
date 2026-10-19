"""A no-op install writes nothing, also when another host was installed after the one being rerun.

The ownership receipt used to carry the digest of the last plan, so rerunning `claude` after `codex` rewrote the receipt
although no file changed. The receipt now describes what is installed, so an identical rerun leaves it byte-identical.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from simplicio_loop.install.planner import apply_plan, plan_install


def make_bundle(root: Path) -> Path:
    skill = root / "skills" / "simplicio-loop"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("loop\n", encoding="utf-8")
    (root / "hooks").mkdir()
    (root / "hooks" / "loop_stop.py").write_text("# stop\n", encoding="utf-8")
    return root


def test_rerunning_an_earlier_host_after_another_host_changes_nothing(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    bundle = make_bundle(tmp_path / "bundle")
    apply_plan(plan_install(repo, host="claude"), bundle=bundle)
    apply_plan(plan_install(repo, host="codex"), bundle=bundle)
    receipt = repo / ".simplicio-loop" / "install-ownership.json"
    before = receipt.read_bytes()
    files = [path for path in repo.rglob("*") if path.is_file()]
    for path in files:
        os.utime(path, ns=(10**9, 10**9))

    result = apply_plan(plan_install(repo, host="claude"), bundle=bundle)

    assert result["up_to_date"] is True and result["written"] == 0
    assert receipt.read_bytes() == before, "the receipt was rewritten by a no-op install"
    assert {path.stat().st_mtime_ns for path in files} == {10**9}, "a file was rewritten by a no-op install"


def test_the_receipt_lists_every_host_installed_so_far(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    bundle = make_bundle(tmp_path / "bundle")
    apply_plan(plan_install(repo, host="claude"), bundle=bundle)
    apply_plan(plan_install(repo, host="codex"), bundle=bundle)
    receipt = json.loads((repo / ".simplicio-loop" / "install-ownership.json").read_text(encoding="utf-8"))
    assert "AGENTS.md" in [block["path"] for block in receipt["blocks"]]
    assert ".claude/skills/simplicio-loop/SKILL.md" in receipt["paths"]
