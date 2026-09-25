"""``edit --compile``: the host writes only find/replace ops; Dev CLI freezes the rest.

An LLM cannot hand-write the mapper binding and canonical digests an edit plan
requires. ``--compile OUT`` reads the minimal plan, pins the current file hashes
and tree into a mapper binding, writes the full plan, and never mutates.
"""

from __future__ import annotations

import json
import subprocess

from simplicio.cli import main


def _repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "ops.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"],
        check=True,
    )
    minimal = {
        "operations": [
            {
                "path": "ops.py",
                "find": "    return a + b\n",
                "replace": "    return a + b\n\n\ndef mul(a, b):\n    return a * b\n",
            }
        ]
    }
    (tmp_path / "ops.json").write_text(json.dumps(minimal), encoding="utf-8")
    return tmp_path


def _edit(*argv):
    return main(["edit", *argv])


def test_compiled_plan_applies_through_edit(tmp_path, capsys):
    repo = _repo(tmp_path)
    plan = repo / "plan.json"
    assert _edit("--root", str(repo), "--plan", str(repo / "ops.json"), "--compile", str(plan)) == 0
    capsys.readouterr()
    assert (repo / "ops.py").read_text() == "def add(a, b):\n    return a + b\n"  # compile never mutates
    compiled = json.loads(plan.read_text())
    assert compiled["schema"] == "simplicio.dev-cli.edit-plan/v1"
    assert compiled["touched_files"] == ["ops.py"]

    assert _edit("--root", str(repo), "--plan", str(plan), "--apply", "--json", "--no-runtime") == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "ok", result
    assert "def mul(a, b):" in (repo / "ops.py").read_text()


def test_drift_between_compile_and_apply_is_refused(tmp_path, capsys):
    repo = _repo(tmp_path)
    plan = repo / "plan.json"
    assert _edit("--root", str(repo), "--plan", str(repo / "ops.json"), "--compile", str(plan)) == 0
    (repo / "ops.py").write_text("def add(a, b):\n    return a + b\n# drift\n", encoding="utf-8")
    capsys.readouterr()
    assert _edit("--root", str(repo), "--plan", str(plan), "--apply", "--json", "--no-runtime") != 0
    assert "def mul" not in (repo / "ops.py").read_text()


def test_compile_rejects_an_anchor_that_does_not_match_once(tmp_path, capsys):
    repo = _repo(tmp_path)
    (repo / "ops.json").write_text(
        json.dumps({"operations": [{"path": "ops.py", "find": "missing", "replace": "x"}]}), encoding="utf-8"
    )
    code = _edit(
        "--root", str(repo), "--plan", str(repo / "ops.json"), "--compile", str(repo / "plan.json"), "--json"
    )
    payload = json.loads(capsys.readouterr().out)
    assert code != 0
    assert payload["errors"][0]["code"] == "missing_anchor"
    assert not (repo / "plan.json").exists()
