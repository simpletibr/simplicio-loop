from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path


HOOK = Path(__file__).parents[1] / "hooks" / "loop_stop.py"


def load_hook():
    spec = importlib.util.spec_from_file_location("loop_stop_delivery_contract", HOOK)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        stdin=subprocess.DEVNULL,
        check=True,
        capture_output=True,
    )


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "loop-stop@example.invalid")
    git(repo, "config", "user.name", "loop-stop fixture")
    (repo / "file.py").write_text("value = 1\n", encoding="utf-8")
    git(repo, "add", "file.py")
    git(repo, "commit", "-q", "-m", "init")
    state = repo / ".simplicio-loop/orchestrator" / "loop"
    state.mkdir(parents=True)
    (state / "anchor.json").write_text(json.dumps({"delivery": {
        "schema": "simplicio.delivery-contract/v1",
        "open_pr": False,
        "push_branch": True,
        "allow_new_files_in_repo": False,
        "allow_comments_in_code": False,
        "commit_message_convention": "#<id> - fix: <desc>",
    }}), encoding="utf-8")
    return repo


def test_stop_guard_records_baseline_then_blocks_new_file(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    hook = load_hook()
    assert hook._delivery_stop_guard(str(repo), 1) is None
    (repo / "FooTests.cs").write_text("class FooTests {}\n", encoding="utf-8")
    reason = hook._delivery_stop_guard(str(repo), 2)
    assert reason is not None
    assert "new files" in reason
    journal = repo / ".simplicio-loop/orchestrator" / "loop" / "journal.jsonl"
    assert "delivery contract guard" in journal.read_text(encoding="utf-8")


def test_stop_guard_blocks_added_python_comment(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    hook = load_hook()
    assert hook._delivery_stop_guard(str(repo), 1) is None
    (repo / "file.py").write_text("# forbidden\nvalue = 2\n", encoding="utf-8")
    reason = hook._delivery_stop_guard(str(repo), 2)
    assert reason is not None
    assert "new code comments" in reason


def test_stop_guard_allows_non_code_comment_when_contract_is_strict(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    hook = load_hook()
    assert hook._delivery_stop_guard(str(repo), 1) is None
    anchor = repo / ".simplicio-loop/orchestrator" / "loop" / "anchor.json"
    payload = json.loads(anchor.read_text(encoding="utf-8"))
    payload["delivery"]["allow_new_files_in_repo"] = True
    anchor.write_text(json.dumps(payload), encoding="utf-8")
    (repo / "README.md").write_text("# documentation\n", encoding="utf-8")
    assert hook._delivery_stop_guard(str(repo), 2) is None
