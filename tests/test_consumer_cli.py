import json
import os
from pathlib import Path

from simplicio_loop import consumer_cli


def test_resolve_all_allowlisted_scripts():
    resolved = [consumer_cli.resolve_script(name) for name in consumer_cli.available_scripts()]
    assert [path.stem for path in resolved] == list(consumer_cli.available_scripts())
    assert all(path.is_file() and path.is_absolute() for path in resolved)


def test_unknown_script_is_rejected(capsys):
    assert consumer_cli.main(["not-a-loop-script"]) == 2
    assert "reason_code=unknown_script" in capsys.readouterr().err


def test_first_turn_smoke_from_consumer_directory(tmp_path, monkeypatch):
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    monkeypatch.chdir(consumer)
    assert consumer_cli.main(["loop_progress", "emit", "--step", "preflight", "--status", "begin"]) == 0
    assert (consumer / ".simplicio-loop/orchestrator" / "loop" / "progress.jsonl").is_file()
    assert not (consumer / "scripts").exists()


def test_anchor_and_journal_use_consumer_repository(tmp_path):
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    assert consumer_cli.main([
        "--repo", str(consumer), "task_anchor", "set", "--item", "smoke",
        "--goal", "consumer target", "--ac", "target state exists",
    ]) == 0
    assert consumer_cli.main([
        "--repo", str(consumer), "loop_journal", "record", "--iteration", "1",
        "--action", "smoke", "--hypothesis", "resolver target", "--gate", "pass",
    ]) == 0
    loop_dir = consumer / ".simplicio-loop/orchestrator" / "loop"
    anchor = json.loads((loop_dir / "anchor.json").read_text(encoding="utf-8"))
    assert anchor["item"] == "smoke"
    assert (loop_dir / "journal.jsonl").is_file()


def test_windows_style_repo_path_is_bound_without_rewriting(monkeypatch, tmp_path):
    repo = tmp_path / "consumer with spaces"
    repo.mkdir()
    env = consumer_cli._script_environment(repo)
    assert env["SIMPLICIO_REPO"] == str(repo.resolve())
    assert env["SIMPLICIO_PROGRESS_DIR"].endswith(os.path.join(".simplicio-loop", "orchestrator", "loop"))


def test_missing_bundle_reports_resolved_path_and_install_fallback(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(consumer_cli, "_BUNDLED_SCRIPTS", tmp_path / "missing-bundle")
    assert consumer_cli.main(["loop_progress", "status"]) == 2
    error = capsys.readouterr().err
    assert "reason_code=bundled_script_missing" in error
    assert "resolved_package_path=" in error
    assert "python -m pip install --upgrade simplicio-loop" in error
