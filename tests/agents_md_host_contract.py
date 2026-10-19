"""The contract every AGENTS.md-surface host adapter (adapters/<host>/adapter.py) must meet.

A host is wired when its adapter ships code and its tests/host_<host>/ test calls this contract once with the
host's row. The checks are the honest minimum: the host is detected from the files its docs name, the loop is
self-paced, no native interception is claimed, and the lifecycle decisions fail closed.
"""
from __future__ import annotations

from pathlib import Path


def assert_self_paced_agents_md_host(row, tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    assert row.detect(empty)["detected"] is False

    project = tmp_path / "project"
    project.mkdir()
    (project / "AGENTS.md").write_text("# rules\n", encoding="utf-8")
    found = row.detect(project)
    assert found["detected"] is True
    assert "file:AGENTS.md" in found["signals"]

    for marker in row.markers:
        marked = tmp_path / ("marked" + marker.replace(".", "-"))
        (marked / marker).mkdir(parents=True)
        assert row.detect(marked)["detected"] is True, marker

    caps = row.capabilities(project)
    assert caps["schema"] == "simplicio.host-adapter/v1"
    assert caps["host"] == row.host
    assert caps["loop_drive"] == "self_paced"
    assert caps["self_paced"] is True
    assert caps["native_interception"] is False
    assert caps["stages"]["PreToolUse"]["supported"] is False
    assert caps["surfaces"]["entry"] == {
        "path": "AGENTS.md",
        "status": "VERIFIED" if row.entry_verified else "UNVERIFIED",
    }
    assert caps["source"] == row.source
    assert row.source.startswith("https://")

    assert row.verify_shipped_hooks(project)["claimed_native"] == []

    assert row.decide({"stage": "SessionStart"})["decision"] == "continue"
    assert row.decide({"stage": "Stop"})["decision"] == "continue"
    blocked = row.decide({"stage": "PreToolUse", "kind": "Write"})
    assert blocked["decision"] == "block"
    assert blocked["native_interception"] is False
    assert row.decide({"stage": "Stop"}, timeout=True)["decision"] == "block"
    assert row.decide({"stage": "Bogus"})["decision"] == "block"
