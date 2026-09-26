"""issue #1331: a minimal host plan operation with ``find: ""`` against a
path that does not yet exist creates that file -- the same semantics
``simplicio-loop apply``'s in-memory ``validate_ops`` already promises
(SKILL.md), which ``edit --compile``/``--apply`` did not honor before this
change (it rejected any empty ``find`` outright).
"""
from __future__ import annotations

import subprocess

from simplicio.commands.edit import compile_host_plan
from simplicio.mechanical_edit import execute_plan


def _git_init(repo):
    subprocess.run(["git", "init", "-q"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=str(repo), check=True)
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=str(repo), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=str(repo), check=True)


def test_compile_host_plan_creates_new_path_with_empty_find(tmp_path):
    _git_init(tmp_path)
    plan = {"operations": [{"path": "new_module.py", "find": "", "replace": "VALUE = 1\n"}]}
    compiled, errors = compile_host_plan(str(tmp_path), plan)
    assert errors == []
    assert compiled is not None
    ops = compiled["operations"]
    assert len(ops) == 1
    assert ops[0]["op"] == "create_file"
    assert ops[0]["path"] == "new_module.py"
    assert ops[0]["text"] == "VALUE = 1\n"


def test_compile_host_plan_blocks_empty_find_against_existing_nonempty_file(tmp_path):
    _git_init(tmp_path)
    (tmp_path / "existing.py").write_text("already here\n", encoding="utf-8")
    plan = {"operations": [{"path": "existing.py", "find": "", "replace": "overwritten\n"}]}
    compiled, errors = compile_host_plan(str(tmp_path), plan)
    assert compiled is None
    assert errors and errors[0]["code"] == "create_target_exists"


def test_compile_and_apply_end_to_end_creates_file_on_disk(tmp_path):
    _git_init(tmp_path)
    plan = {"operations": [{"path": "tests/test_new.py", "find": "", "replace": "def test_x():\n    assert True\n"}]}
    compiled, errors = compile_host_plan(str(tmp_path), plan)
    assert errors == []
    result = execute_plan(compiled, root=str(tmp_path), apply=True, allow_native=False)
    assert result["applied"] is True, result
    created = tmp_path / "tests" / "test_new.py"
    assert created.is_file()
    assert created.read_text(encoding="utf-8") == "def test_x():\n    assert True\n"


def test_mixed_create_and_edit_operations_in_one_plan(tmp_path):
    _git_init(tmp_path)
    (tmp_path / "existing.py").write_text("BEFORE\n", encoding="utf-8")
    plan = {
        "operations": [
            {"path": "existing.py", "find": "BEFORE\n", "replace": "AFTER\n"},
            {"path": "brand_new.py", "find": "", "replace": "NEW = True\n"},
        ]
    }
    compiled, errors = compile_host_plan(str(tmp_path), plan)
    assert errors == []
    ops_by_path = {op["path"]: op for op in compiled["operations"]}
    assert ops_by_path["existing.py"]["op"] == "replace_anchor"
    assert ops_by_path["brand_new.py"]["op"] == "create_file"
