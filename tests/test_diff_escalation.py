import json
import subprocess
import sys
import pytest
from pathlib import Path

from scripts import diff_escalation


def test_files_threshold_promotes_with_numeric_reason():
    result = diff_escalation.evaluate(
        "fast-path", ["a.py", "b.py", "c.py"], 3, 0, [], []
    )
    assert result["mode"] == "converge"
    assert result["promoted"] is True
    assert "diff 3 files > 2" in result["reason"]


def test_lines_threshold_promotes_with_numeric_reason():
    result = diff_escalation.evaluate("fast-path", ["a.py"], 81, 0, [], [])
    assert result["mode"] == "converge"
    assert "diff 81 lines > 80" in result["reason"]


def test_new_file_promotes():
    result = diff_escalation.evaluate("fast-path", ["a.py", "new.py"], 1, 1, ["new.py"], [])
    assert result["promoted"] is True
    assert "new file: new.py" in result["reason"]


def test_sensitive_surface_promotes():
    result = diff_escalation.evaluate(
        "fast-path", ["src/schema.sql"], 1, 1, [], ["src/schema.sql"]
    )
    assert result["promoted"] is True
    assert "sensitive surface: src/schema.sql" in result["reason"]


def test_budget_remains_fast_path():
    result = diff_escalation.evaluate("fast-path", ["a.py"], 40, 40, [], [])
    assert result["mode"] == "fast-path"
    assert result["promoted"] is False
    assert result["reason"] == "within budget: diff 1 files, 80 lines"


def test_converge_never_demotes():
    result = diff_escalation.evaluate("converge", ["a.py"], 0, 0, [], [])
    assert result["mode"] == "converge"
    assert result["monotonic"] is True
    assert result["promoted"] is False


def test_fingerprint_is_deterministic():
    args = ("fast-path", ["b.py", "a.py"], 2, 3, [], [])
    assert diff_escalation.evaluate(*args)["fingerprint"] == diff_escalation.evaluate(*args)["fingerprint"]


def test_parse_numstat_handles_binary_and_rename():
    rows = diff_escalation.parse_numstat("2\t3\tsrc/a.py\n-\t-\timage.bin\n1\t0\told.py => new.py\n")
    assert rows == [
        {"path": "src/a.py", "added": 2, "deleted": 3},
        {"path": "image.bin", "added": 0, "deleted": 0},
        {"path": "new.py", "added": 1, "deleted": 0},
    ]


def test_preserve_anchor_criteria_and_route(tmp_path):
    anchor = tmp_path / "anchor.json"
    original = {
        "item": "526",
        "goal": "frozen",
        "criteria": [{"id": "AC1", "status": "pending"}],
        "route_mode": {"mode": "fast-path", "justification": "initial"},
    }
    anchor.write_text(json.dumps(original), encoding="utf-8")
    result = diff_escalation.evaluate("fast-path", ["a.py", "b.py", "c.py"], 0, 0, [], [])
    assert diff_escalation.record_anchor(anchor, result)
    updated = json.loads(anchor.read_text(encoding="utf-8"))
    assert updated["goal"] == "frozen"
    assert updated["criteria"] == original["criteria"]
    assert updated["route_mode"]["mode"] == "converge"
    assert updated["route_mode"]["diff_escalation"]["fingerprint"] == result["fingerprint"]


def test_journal_records_promotion_and_fingerprint(tmp_path):
    journal = tmp_path / "journal.jsonl"
    result = diff_escalation.evaluate("fast-path", ["a.py", "b.py", "c.py"], 0, 0, [], [])
    assert diff_escalation.record_journal(journal, result, 2)
    row = json.loads(journal.read_text(encoding="utf-8").splitlines()[0])
    assert row["fingerprint"] == result["fingerprint"]
    assert row["source"] == "diff_escalation"


def test_preserve_scratchpad_bytes(tmp_path):
    scratchpad = tmp_path / "scratchpad.md"
    scratchpad.write_bytes(b"frozen\r\nstate\r\n")
    before = scratchpad.read_bytes()
    anchor = tmp_path / "anchor.json"
    anchor.write_text(json.dumps({"criteria": []}), encoding="utf-8")
    result = diff_escalation.evaluate("fast-path", ["a.py", "b.py", "c.py"], 0, 0, [], [])
    diff_escalation.record_anchor(anchor, result)
    diff_escalation.record_journal(tmp_path / "journal.jsonl", result, 1)
    assert scratchpad.read_bytes() == before




def test_status_paths_tracks_added_and_renamed():
    changed, new = diff_escalation._status_paths(" M tracked.py\nA  added.py\n?? loose.py\nR  old.py -> new.py\n")
    assert changed == ["added.py", "loose.py", "new.py", "tracked.py"]
    assert new == ["added.py", "loose.py"]


def test_snapshot_uses_status_and_numstat(monkeypatch, tmp_path):
    def fake_git(_root, args):
        if args[0] == "status":
            return " M src/app.py\n?? notes.txt\n"
        return "4\t2\tsrc/app.py\n"

    monkeypatch.setattr(diff_escalation, "_git", fake_git)
    snapshot = diff_escalation.read_git_snapshot(tmp_path)
    assert snapshot["changed_files"] == ["notes.txt", "src/app.py"]
    assert snapshot["added_lines"] == 4
    assert snapshot["deleted_lines"] == 2
    assert snapshot["new_files"] == ["notes.txt"]


def test_anchor_failures_and_non_promotion_are_explicit(tmp_path):
    result = diff_escalation.evaluate("fast-path", ["a.py"], 1, 1, [], [])
    assert diff_escalation.record_anchor(tmp_path / "missing.json", result) is False
    broken = tmp_path / "broken.json"
    broken.write_text("[]", encoding="utf-8")
    assert diff_escalation.record_anchor(broken, result) is False
    assert diff_escalation.record_journal(tmp_path / "journal.jsonl", result, 1) is False


def test_main_records_measured_json(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        diff_escalation,
        "read_git_snapshot",
        lambda root, baseline: {
            "changed_files": ["a.py", "b.py", "c.py"],
            "added_lines": 0,
            "deleted_lines": 0,
            "new_files": [],
            "sensitive_files": [],
        },
    )
    anchor = tmp_path / "anchor.json"
    anchor.write_text(json.dumps({"criteria": []}), encoding="utf-8")
    assert diff_escalation.main([
        "--root", str(tmp_path),
        "--anchor", "anchor.json",
        "--journal", "journal.jsonl",
        "--iteration", "3",
    ]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == diff_escalation.SCHEMA
    assert payload["measured"] is True
    assert payload["anchor_updated"] is True
    assert payload["journal_recorded"] is True
def _git(root, *args):
    try:
        return subprocess.run(
            ["git", *args],
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except OSError as exc:
        if getattr(exc, "winerror", None) == 6:
            pytest.skip("Windows subprocess handle exhaustion (WinError 6)")
        raise
def test_integration_reads_git_status_and_updates_anchor(tmp_path):
    assert _git(tmp_path, "init", "-q").returncode == 0
    (tmp_path / "tracked.py").write_text("one\n", encoding="utf-8")
    assert _git(tmp_path, "add", "tracked.py").returncode == 0
    assert _git(
        tmp_path,
        "-c", "user.name=Test",
        "-c", "user.email=test@example.invalid",
        "commit", "-m", "init", "-q",
    ).returncode == 0
    (tmp_path / "tracked.py").write_text("one\ntwo\n", encoding="utf-8")
    (tmp_path / "new.py").write_text("new\n", encoding="utf-8")
    snapshot = diff_escalation.read_git_snapshot(tmp_path)
    assert "tracked.py" in snapshot["changed_files"]
    assert "new.py" in snapshot["new_files"]
    result = diff_escalation.evaluate(
        "fast-path",
        snapshot["changed_files"],
        snapshot["added_lines"],
        snapshot["deleted_lines"],
        snapshot["new_files"],
        snapshot["sensitive_files"],
    )
    assert result["mode"] == "converge"
    anchor = tmp_path / "anchor.json"
    anchor.write_text(json.dumps({"criteria": [{"id": "AC1"}]}), encoding="utf-8")
    assert diff_escalation.record_anchor(anchor, result)
    assert json.loads(anchor.read_text(encoding="utf-8"))["route_mode"]["mode"] == "converge"


def test_cli_emits_measured_json(capsys):
    with pytest.raises(SystemExit) as raised:
        diff_escalation.main(["--help"])
    assert raised.value.code == 0
    assert "--baseline" in capsys.readouterr().out


def test_snapshot_ignores_loop_bookkeeping_and_verifier_byproducts(tmp_path):
    """dev-cli writes .simplicio/events.jsonl + ledger on every apply and a
    check leaves __pycache__/.pytest_cache; none is the user's diff, so a
    one-line fast-path edit must stay fast-path."""
    run = lambda *a: subprocess.run(["git", *a], cwd=tmp_path, check=True, capture_output=True)
    run("init", "-q")
    (tmp_path / "page.html").write_text("<p>a</p>\n")
    run("add", "-A")
    run("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "seed")
    (tmp_path / "page.html").write_text("<p>b</p>\n")
    (tmp_path / ".simplicio" / "ledger").mkdir(parents=True)
    (tmp_path / ".simplicio" / "events.jsonl").write_text("{}\n")
    (tmp_path / ".simplicio" / "ledger" / "savings-events.jsonl").write_text("{}\n")
    (tmp_path / "tests" / "__pycache__").mkdir(parents=True)
    (tmp_path / "tests" / "__pycache__" / "c.pyc").write_bytes(b"\0")
    (tmp_path / ".pytest_cache").mkdir()
    (tmp_path / ".pytest_cache" / "x").write_text("x")
    snap = diff_escalation.read_git_snapshot(tmp_path)
    assert snap["changed_files"] == ["page.html"]
    assert snap["new_files"] == []
