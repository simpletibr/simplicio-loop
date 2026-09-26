from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

HOOK = Path(__file__).parents[1] / "hooks" / "action_gate.py"


def load_hook():
    spec = importlib.util.spec_from_file_location("action_gate_issue526", HOOK)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    module._runtime_gate_escalation = lambda command: None
    return module


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def make_repo(tmp_path: Path, text: str = "ok") -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "action-gate@example.invalid")
    git(repo, "config", "user.name", "action-gate fixture")
    (repo / "file.txt").write_text(text, encoding="utf-8")
    git(repo, "add", "file.txt")
    git(repo, "commit", "-q", "-m", "init")
    return repo


def freeze_delivery(repo: Path, **overrides) -> None:
    state = repo / ".simplicio-loop/orchestrator" / "loop"
    state.mkdir(parents=True)
    contract = {
        "schema": "simplicio.delivery-contract/v1",
        "open_pr": False,
        "push_branch": True,
        "allow_new_files_in_repo": True,
        "allow_comments_in_code": True,
        "commit_message_convention": "#<id> - fix: <desc>",
    }
    contract.update(overrides)
    (state / "anchor.json").write_text(json.dumps({"delivery": contract}), encoding="utf-8")


def test_push_from_worktree_scans_push_range(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    (repo / "file.txt").write_text("AKIAQRSTUVWX01234567", encoding="utf-8")
    git(repo, "add", "file.txt")
    git(repo, "commit", "-q", "-m", "secret")
    hook = load_hook()
    verdict = hook.gate_command('cd "%s" && git push origin feature' % repo)
    assert verdict["action"] == "block"
    assert "push diff" in verdict["reason"]
    assert str(repo) in verdict["reason"]


def test_clean_push_is_deterministic_five_times(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, "safe")
    (repo / "file.txt").write_text("safe-2", encoding="utf-8")
    git(repo, "add", "file.txt")
    git(repo, "commit", "-q", "-m", "safe")
    hook = load_hook()
    verdicts = [
        hook.gate_command('cd "%s" && git push origin feature' % repo)
        for _ in range(5)
    ]
    assert verdicts == [{"action": "allow", "reason": ""}] * 5


def test_git_c_resolves_effective_repo_for_push(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    (repo / "file.txt").write_text("AKIAQRSTUVWX01234567", encoding="utf-8")
    git(repo, "add", "file.txt")
    git(repo, "commit", "-q", "-m", "secret")
    hook = load_hook()
    command = 'git -C "%s" push origin feature' % repo
    assert hook._effective_command_cwd(command) == str(repo)
    diff = hook._push_diff(hook._effective_command_cwd(command))
    assert diff is not None and "AKIA" in diff


def test_commit_still_scans_staged_diff(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    (repo / "new.txt").write_text("AKIAQRSTUVWX01234567", encoding="utf-8")
    git(repo, "add", "new.txt")
    hook = load_hook()
    verdict = hook.gate_command('cd "%s" && git commit -m secret' % repo)
    assert verdict["action"] == "block"
    assert "staged diff" in verdict["reason"]


def test_delivery_contract_blocks_new_staged_file(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    freeze_delivery(repo, allow_new_files_in_repo=False)
    (repo / "new.py").write_text("value = 1\n", encoding="utf-8")
    git(repo, "add", "new.py")
    hook = load_hook()
    verdict = hook.gate_command('cd "%s" && git commit -m new' % repo)
    assert verdict["action"] == "block"
    assert "forbids new files" in verdict["reason"]
    assert str(repo) in verdict["reason"]


def test_delivery_contract_blocks_new_code_comment(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    freeze_delivery(repo, allow_comments_in_code=False)
    (repo / "file.py").write_text("# forbidden comment\nvalue = 1\n", encoding="utf-8")
    git(repo, "add", "file.py")
    hook = load_hook()
    verdict = hook.gate_command('cd "%s" && git commit -m comment' % repo)
    assert verdict["action"] == "block"
    assert "forbids new code comments" in verdict["reason"]


def test_delivery_contract_invalid_state_is_fail_closed(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    freeze_delivery(repo, unknown=True)
    (repo / "file.txt").write_text("safe-2", encoding="utf-8")
    git(repo, "add", "file.txt")
    hook = load_hook()
    verdict = hook.gate_command('cd "%s" && git commit -m invalid' % repo)
    assert verdict["action"] == "block"
    assert "invalid frozen delivery contract" in verdict["reason"]
