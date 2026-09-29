"""hooks/loop_stop.py new-file guard (issue #526 Etapa 4).

Fixture reproducing the exact real-world scenario from the issue: a delivery contract with the
3 restrictions that motivated this work (`open_pr: false`, `allow_new_files_in_repo: false`,
`allow_comments_in_code: false`) + a turn that creates `FooTests.cs` (a test file the client
explicitly forbids committing) -> the turn is BLOCKED with a reason that names the file.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_spec = importlib.util.spec_from_file_location("hooks.loop_stop", REPO_ROOT / "hooks" / "loop_stop.py")
loop_stop = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(loop_stop)

DELIVERY_CONTRACT_3_REAL_RESTRICTIONS = {
    "open_pr": False,
    "push_branch": True,
    "allow_new_files_in_repo": False,
    "allow_comments_in_code": False,
    "commit_message_convention": "#<issue> - <type>: <desc>",
}


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "a@b.c")
    git(repo, "config", "user.name", "tester")
    (repo / "RestEletDriverService.cs").write_text("public class RestEletDriverService {}\n",
                                                   encoding="utf-8")
    git(repo, "add", "RestEletDriverService.cs")
    git(repo, "commit", "-q", "-m", "init")
    return repo


def _load_delivery_contract_module(monkeypatch, repo: Path):
    """Import scripts/delivery_contract.py with its git-plumbing operating on `repo`."""
    scripts_dir = REPO_ROOT / "scripts"
    monkeypatch.syspath_prepend(str(scripts_dir))
    import delivery_contract as dc
    return dc


def test_new_file_guard_pure_function_blocks_on_footests(tmp_path, monkeypatch):
    """Direct unit check of `loop_stop.delivery_new_file_violation()`'s underlying primitive
    (`delivery_contract.new_file_guard`), against the real 3-restriction contract."""
    repo = make_repo(tmp_path)
    dc = _load_delivery_contract_module(monkeypatch, repo)
    baseline_path = tmp_path / "baseline.json"
    dc.capture_baseline(str(repo), str(baseline_path))

    # The turn creates the forbidden test file.
    (repo / "FooTests.cs").write_text(
        "public class FooTests { [Test] public void T() {} }\n", encoding="utf-8")

    anchor = {"item": "526", "goal": "Ship the TFS_326750 fix",
              "delivery": DELIVERY_CONTRACT_3_REAL_RESTRICTIONS}
    reason = dc.new_file_guard(anchor, root=str(repo), baseline_path=str(baseline_path))

    assert reason is not None, "expected the turn to be BLOCKED"
    assert "FooTests.cs" in reason
    assert "allow_new_files_in_repo" in reason


def test_new_file_guard_silent_when_file_was_already_present(tmp_path, monkeypatch):
    """A file that existed BEFORE the contract was frozen is never a violation."""
    repo = make_repo(tmp_path)
    (repo / "FooTests.cs").write_text("already here\n", encoding="utf-8")
    dc = _load_delivery_contract_module(monkeypatch, repo)
    baseline_path = tmp_path / "baseline.json"
    dc.capture_baseline(str(repo), str(baseline_path))  # captured AFTER FooTests.cs appeared

    anchor = {"delivery": DELIVERY_CONTRACT_3_REAL_RESTRICTIONS}
    reason = dc.new_file_guard(anchor, root=str(repo), baseline_path=str(baseline_path))
    assert reason is None


def test_loop_stop_delivery_new_file_violation_blocks(tmp_path, monkeypatch):
    """`hooks/loop_stop.py::delivery_new_file_violation()` against a real anchor.json + git repo,
    reproducing the exact issue scenario end-to-end through the hook's own entry point."""
    repo = make_repo(tmp_path)
    monkeypatch.chdir(repo)
    scripts_dir = REPO_ROOT / "scripts"
    monkeypatch.syspath_prepend(str(scripts_dir))
    import delivery_contract as dc

    loop_dir = repo / ".simplicio-loop/orchestrator" / "loop"
    loop_dir.mkdir(parents=True)
    anchor_path = loop_dir / "anchor.json"
    anchor = {"item": "526", "goal": "Ship the TFS_326750 fix", "goal_fp": "fp1",
              "criteria": [], "delivery": DELIVERY_CONTRACT_3_REAL_RESTRICTIONS}
    anchor_path.write_text(json.dumps(anchor), encoding="utf-8")

    baseline_path = loop_dir / "delivery_baseline.json"
    dc.capture_baseline(str(repo), str(baseline_path))
    monkeypatch.setattr(loop_stop, "ANCHOR", str(anchor_path))

    # No new file yet -> no violation.
    monkeypatch.setattr(dc, "DEFAULT_BASELINE", str(baseline_path))
    reason_clean = loop_stop.delivery_new_file_violation()
    assert reason_clean is None

    # The turn creates the forbidden test file.
    (repo / "FooTests.cs").write_text(
        "public class FooTests { [Test] public void T() {} }\n", encoding="utf-8")
    reason = loop_stop.delivery_new_file_violation()
    assert reason is not None
    assert "FooTests.cs" in reason


def test_loop_stop_main_blocks_the_turn_and_writes_handoff(tmp_path, monkeypatch):
    """Full `main()` pass: an active scratchpad + the 3-restriction delivery contract + a
    freshly-created `FooTests.cs` -> the turn is blocked, a handoff is written naming the file,
    and the loop does NOT re-feed."""
    repo = make_repo(tmp_path)
    monkeypatch.chdir(repo)
    scripts_dir = REPO_ROOT / "scripts"
    monkeypatch.syspath_prepend(str(scripts_dir))
    import delivery_contract as dc

    loop_dir = repo / ".simplicio-loop/orchestrator" / "loop"
    loop_dir.mkdir(parents=True)
    scratchpad = loop_dir / "scratchpad.md"
    scratchpad.write_text(
        "---\niteration: 1\nmax_iterations: 10\ncompletion_promise: null\n"
        "evidence_required: true\n---\nFix the cap mirroring bug.\n",
        encoding="utf-8",
    )
    anchor_path = loop_dir / "anchor.json"
    anchor = {"item": "526", "goal": "Ship the TFS_326750 fix", "goal_fp": "fp1",
              "criteria": [], "delivery": DELIVERY_CONTRACT_3_REAL_RESTRICTIONS}
    anchor_path.write_text(json.dumps(anchor), encoding="utf-8")
    baseline_path = loop_dir / "delivery_baseline.json"
    dc.capture_baseline(str(repo), str(baseline_path))

    monkeypatch.setattr(loop_stop, "SCRATCHPAD", str(scratchpad))
    monkeypatch.setattr(loop_stop, "ANCHOR", str(anchor_path))
    monkeypatch.setattr(loop_stop, "DONE_FLAG", str(loop_dir / "done.flag"))
    monkeypatch.setattr(loop_stop, "LEGACY_DONE_FLAG", str(loop_dir / "done"))
    monkeypatch.setattr(loop_stop, "LAST_RESP", str(loop_dir / "last_response.txt"))
    monkeypatch.setattr(loop_stop, "WATCHER_STATE", str(loop_dir / "watcher_state.json"))
    monkeypatch.setattr(loop_stop, "WATCHER_CHALLENGE", str(loop_dir / "watcher_challenge.json"))
    monkeypatch.setattr(loop_stop, "HANDOFF", str(loop_dir / "HANDOFF.md"))
    monkeypatch.setattr(loop_stop, "STOP_SIGNAL", str(repo / ".simplicio-loop/orchestrator" / "STOP"))
    monkeypatch.setattr(loop_stop, "SIMPLICIO_LOOP_SKILL_MARKER",
                        str(repo / "no-such-skill-marker.md"))  # no bound-operator requirement
    monkeypatch.setattr(dc, "DEFAULT_BASELINE", str(baseline_path))
    # Never touch the real network/CLI callouts from this test.
    monkeypatch.setattr(loop_stop, "_call_simplicio_checkpoint", lambda *_: None)
    monkeypatch.setattr(loop_stop, "_call_hierarchical_planner", lambda: None)
    monkeypatch.setattr(loop_stop, "refresh_cross_agent_wiki", lambda *_a, **_k: None)
    monkeypatch.setattr(sys, "stdin", type("F", (), {"read": staticmethod(lambda: "{}")})())

    # The turn creates the forbidden test file.
    (repo / "FooTests.cs").write_text(
        "public class FooTests { [Test] public void T() {} }\n", encoding="utf-8")

    with pytest.raises(SystemExit) as exc_info:
        loop_stop.main()

    assert (exc_info.value.code or 0) == 0  # fail-open transport: Stop hook always exits 0
    assert not scratchpad.exists(), "a blocked turn must clear the scratchpad (loop ends)"
    handoff_path = loop_dir / "HANDOFF.md"
    assert handoff_path.exists()
    handoff_text = handoff_path.read_text(encoding="utf-8")
    assert "FooTests.cs" in handoff_text
    assert "allow_new_files_in_repo" in handoff_text
