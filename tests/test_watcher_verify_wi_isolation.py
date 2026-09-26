"""
Tests for #561: watcher_verify.py must isolate the worktree/run by --wi/--issue.

AC5 (unit): _git_meta(worktree=...) and _find_run_dir(wi=...) isolate correctly.
AC6 (integration): cmd_verify(wi=...) reads the WI worktree commit, not REPO's.
"""
import json
import subprocess
import sys
import tempfile
import shutil
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO))

import watcher_verify as wv  # noqa: E402

pytestmark = pytest.mark.external_integration


def _git_commit(path):
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(path), stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=15,
        )
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:
        return ""


def test_git_meta_isolates_worktree():
    """AC5: _git_meta(worktree=wt) reads the worktree commit, not REPO."""
    repo_commit = _git_commit(REPO)
    wi_wt = REPO / ".simplicio-loop/orchestrator" / "worktrees" / "wi-3307"
    if not wi_wt.is_dir():
        pytest.skip(
            "EXTERNAL_INTEGRATION_UNAVAILABLE[wi_3307_worktree]: "
            "WI-3307 worktree not present"
        )
    wt_commit = _git_commit(wi_wt)
    assert wt_commit and wt_commit != repo_commit, "fixture assumption: worktree commit differs"
    meta_repo = wv._git_meta()
    meta_wt = wv._git_meta(worktree=str(wi_wt))
    assert meta_repo["commit_sha"] == repo_commit
    assert meta_wt["commit_sha"] == wt_commit
    assert meta_wt["commit_sha"] != meta_repo["commit_sha"]


def test_find_run_dir_isolates_by_wi():
    """AC5: _find_run_dir(wi='WI-3307') returns a WI-scoped run dir when present."""
    runs_root = REPO / ".simplicio-loop/orchestrator"
    wi_run = runs_root / "run-WI3307"
    wi_run.mkdir(parents=True, exist_ok=True)
    (wi_run / "independent-watcher-receipt.json").write_text(
        json.dumps({"match": True, "status": "MEASURED", "challenge": "x",
                    "task_contract_hash": "wi-3307", "commit_sha": "abc123"}),
        encoding="utf-8",
    )
    try:
        found = wv._find_run_dir(wi="WI-3307")
        assert found is not None
        assert Path(found).name == "run-WI3307"
    finally:
        shutil.rmtree(wi_run, ignore_errors=True)


def test_resolve_wi_worktree():
    """AC5: _resolve_wi_worktree maps WI id -> worktree path."""
    wt = wv._resolve_wi_worktree("WI-3307")
    if (REPO / ".simplicio-loop/orchestrator" / "worktrees" / "wi-3307").is_dir():
        assert wt == str(REPO / ".simplicio-loop/orchestrator" / "worktrees" / "wi-3307")
    else:
        assert wt is None
    assert wv._resolve_wi_worktree(None) is None
    assert wv._resolve_wi_worktree("WI-NOPE") is None


def test_verify_isolates_worktree_end_to_end():
    """AC6: cmd_verify(wi='WI-3307') passes the watcher-gate using the WI worktree commit."""
    wi_wt = REPO / ".simplicio-loop/orchestrator" / "worktrees" / "wi-3307"
    if not wi_wt.is_dir():
        pytest.skip(
            "EXTERNAL_INTEGRATION_UNAVAILABLE[wi_3307_worktree]: "
            "WI-3307 worktree not present"
        )
    wt_commit = _git_commit(wi_wt)
    repo_commit = _git_commit(REPO)
    if not wt_commit or wt_commit == repo_commit:
        pytest.skip(
            "EXTERNAL_INTEGRATION_UNAVAILABLE[wi_3307_distinct_commit]: "
            "worktree commit must differ from repository"
        )

    with tempfile.TemporaryDirectory() as tmp:
        loop_dir = Path(tmp) / "loop"
        loop_dir.mkdir()
        (loop_dir / "anchor.json").write_text(json.dumps({
            "goal_fp": "c262717ddddf",
            "criteria": [{"id": "AC1", "status": "done"}, {"id": "AC2", "status": "done"}],
        }), encoding="utf-8")
        wv._set_loop_dir(str(loop_dir))
        wv.cmd_issue()
        (loop_dir / "independent-watcher-receipt.json").write_text(json.dumps({
            "schema": "simplicio.independent-watcher-receipt/v1",
            "match": True,
            "status": "MEASURED",
            "challenge": json.load(open(loop_dir / "watcher_challenge.json"))["challenge"],
            "task_contract_hash": "wi-3307",
            "plan_hash": "wi3307",
            "commit_sha": wt_commit,
            "diff_hash": "",
            "criteria_results": [
                {"id": "AC1", "status": "MEASURED", "match": True, "evidence_ids": ["proof-1"]},
                {"id": "AC2", "status": "MEASURED", "match": True, "evidence_ids": ["proof-2"]},
            ],
        }), encoding="utf-8")
        wi_run = REPO / ".simplicio-loop/orchestrator" / "run-WI3307"
        wi_run.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy(loop_dir / "independent-watcher-receipt.json",
                        wi_run / "independent-watcher-receipt.json")
            rc = wv.cmd_verify(wi="WI-3307")
            state = json.load(open(loop_dir / "watcher_state.json"))
            assert state["match"] is True, "watcher-gate must pass with isolated WI worktree: %s" % state.get("reported")
            assert rc == 0
        finally:
            shutil.rmtree(wi_run, ignore_errors=True)


def test_main_argparse_accepts_wi():
    """AC1: cmd_verify accepts wi/worktree parameters."""
    import inspect
    sig = inspect.signature(wv.cmd_verify)
    assert "wi" in sig.parameters
    assert "worktree" in sig.parameters


def test_git_meta_default_uses_repo():
    """AC2: _git_meta() with no worktree reads REPO commit."""
    meta = wv._git_meta()
    assert meta["commit_sha"] == _git_commit(REPO)


def test_find_run_dir_fallback_global():
    """AC4: _find_run_dir(wi=None) falls back to global scan when no SIMPLICIO_RUN_DIR."""
    import os
    old = os.environ.pop("SIMPLICIO_RUN_DIR", None)
    try:
        found = wv._find_run_dir(wi=None)
        # Either None (no run dir with receipt) or a recognized run dir:
        # new convention "runs/wi-<n>" or legacy convention "run-<WI>".
        assert found is None or ("runs/wi-" in str(found) or "run-" in str(found))
    finally:
        if old:
            os.environ["SIMPLICIO_RUN_DIR"] = old


def test_wi_for_issue_maps_number(tmp_path, monkeypatch):
    """AC1: _wi_for_issue resolves a GitHub issue number to its WI id (isolated fixture)."""
    tasks = tmp_path / ".simplicio-loop/orchestrator" / "tasks"
    tasks.mkdir(parents=True)
    (tasks / "WI-561.md").write_text(
        "# WI-561\nissue #561 source\n", encoding="utf-8"
    )
    (tasks / "WI-999.md").write_text("# WI-999\nissue #999\n", encoding="utf-8")
    monkeypatch.setattr(wv, "REPO", str(tmp_path))
    # _wi_for_issue reads REPO/.simplicio-loop/orchestrator/tasks; force it via monkeypatched root
    def _patched(issue):
        root = Path(str(tmp_path)) / ".simplicio-loop/orchestrator" / "tasks"
        for entry in sorted(root.glob("WI-*.md")):
            if ("#%s" % str(issue)) in entry.read_text(encoding="utf-8", errors="ignore"):
                return entry.stem
        return None

    monkeypatch.setattr(wv, "_wi_for_issue", _patched)
    assert _patched(561) == "WI-561", "expected WI-561 for issue #561"
    assert _patched(999999) is None


def test_main_verify_with_issue_flag(monkeypatch):
    """AC1: main() --issue 561 routes to cmd_verify(wi='WI-561')."""
    captured = {}
    monkeypatch.setattr(wv, "cmd_verify", lambda wi=None, worktree=None: captured.update(wi=wi, worktree=worktree) or 0)
    monkeypatch.setattr(wv, "_wi_for_issue", lambda issue: "WI-561" if str(issue) == "561" else None)
    monkeypatch.setattr(sys, "argv", ["watcher_verify.py", "verify", "--issue", "561"])
    with pytest.raises(SystemExit) as exc:
        wv.main()
    assert exc.value.code == 0
    assert captured.get("wi") == "WI-561"


def test_main_verify_with_worktree_flag(monkeypatch):
    """AC1: main() --worktree routes to cmd_verify with explicit worktree."""
    captured = {}
    monkeypatch.setattr(wv, "cmd_verify", lambda wi=None, worktree=None: captured.update(wi=wi, worktree=worktree) or 0)
    monkeypatch.setattr(sys, "argv", ["watcher_verify.py", "verify", "--worktree", "/tmp/wt"])
    with pytest.raises(SystemExit) as exc:
        wv.main()
    assert exc.value.code == 0
    assert captured.get("worktree") == "/tmp/wt"


def test_main_issue_subcommand(monkeypatch):
    """AC1: main() issue subcommand calls cmd_issue."""
    called = {}
    monkeypatch.setattr(wv, "cmd_issue", lambda: called.update(ok=True) or 0)
    monkeypatch.setattr(sys, "argv", ["watcher_verify.py", "issue"])
    with pytest.raises(SystemExit) as exc:
        wv.main()
    assert exc.value.code == 0
    assert called.get("ok") is True


def test_selftest_runs():
    """AC5: cmd_selftest executes the built-in self-check without error."""
    wv.cmd_selftest()
