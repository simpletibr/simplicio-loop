"""Closed model-response contracts and the task scope (issue #1612)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from simplicio_loop import plan_scope as ps

FIXTURES = Path(__file__).resolve().parent.parent / "contracts" / "structured-output" / "v1" / "fixtures"


def _fixtures(kind: str, flavor: str):
    return sorted(p for p in FIXTURES.glob(f"{kind}.{flavor}.*"))


def _scope(*paths: str, dirs=(), max_lines: int = ps.MAX_FILE_LINES) -> ps.TaskScope:
    return ps.TaskScope(paths=frozenset(paths), dirs=tuple(dirs), criteria=("c1",), max_lines=max_lines)


def _plan(*ops: dict) -> str:
    return json.dumps({"operations": list(ops)})


def _codes(result) -> list[str]:
    return [v.split(":", 1)[0] for v in result.violations]


@pytest.mark.parametrize("path", _fixtures("plan", "valid") + _fixtures("verdict", "valid"), ids=lambda p: p.name)
def test_valid_fixtures_pass_the_schema(path):
    kind = path.name.split(".", 1)[0]
    assert ps.validate_response(path.read_text(encoding="utf-8"), kind) == []


@pytest.mark.parametrize("path", _fixtures("plan", "invalid") + _fixtures("verdict", "invalid"), ids=lambda p: p.name)
def test_invalid_fixtures_fail_with_the_named_code(path):
    kind, _, code = path.name.split(".")[0:3]
    violations = ps.validate_response(path.read_text(encoding="utf-8"), kind)
    assert violations and violations[0].startswith(code), violations


def test_every_schema_is_closed_and_bounded():
    for name, schema in ps.RESPONSE_SCHEMAS.items():
        stack = [schema]
        while stack:
            node = stack.pop()
            if node.get("type") == "object":
                assert node.get("additionalProperties") is False, name
            if node.get("type") == "string":
                assert "maxLength" in node, name
            if node.get("type") == "array":
                assert "maxItems" in node, name
                stack.append(node["items"])
            stack.extend(node.get("properties", {}).values())


def test_prose_around_the_json_is_rejected_and_counted():
    text = 'Sure! {"operations":[{"path":"a.py","find":"","replace":"x"}]} done.'
    result = ps.check_response(text, _scope("a.py"), Path("."))
    assert not result.ok and "extra_prose" in _codes(result) and result.prose_chars > 0


def test_one_enclosing_code_fence_is_framing_not_prose():
    text = '```json\n{"operations":[{"path":"a.py","find":"","replace":"x"}]}\n```'
    result = ps.check_response(text, _scope("a.py"), Path("."))
    assert result.ok, result.violations


def test_extra_field_is_rejected_with_its_pointer():
    text = '{"operations":[{"path":"a.py","find":"","replace":"x","why":"y"}]}'
    result = ps.check_response(text, _scope("a.py"), Path("."))
    assert result.violations == ["extra_field:/operations/0/why"]


def test_operation_outside_the_scope_is_rejected():
    result = ps.check_response(_plan({"path": "other.py", "find": "", "replace": "x"}), _scope("a.py"), Path("."))
    assert result.violations == ["out_of_scope:other.py"] and not result.ok


def test_in_scope_file_and_dir_prefix_pass():
    plan = _plan({"path": "a.py", "find": "", "replace": "x"}, {"path": "pkg/b.py", "find": "", "replace": "y"})
    assert ps.check_response(plan, _scope("a.py", dirs=("pkg/",)), Path(".")).ok


def test_the_model_cannot_widen_the_scope():
    scope = _scope("a.py")
    ps.check_response(_plan({"path": "z.py", "find": "", "replace": "x"}), scope, Path("."))
    assert scope.paths == frozenset({"a.py"})
    with pytest.raises(AttributeError):
        scope.paths = frozenset({"z.py"})  # frozen


def test_companion_test_widening_is_explicit_and_audited(tmp_path):
    scope = _scope("simplicio_loop/mod.py")
    plan = _plan({"path": "tests/test_mod.py", "find": "", "replace": "def test_x(): pass\n"})
    result = ps.check_response(plan, scope, tmp_path)
    assert result.ok and result.widenings == [{"path": "tests/test_mod.py", "rule": "companion_test"}]


def test_unrelated_test_file_is_not_a_companion(tmp_path):
    plan = _plan({"path": "tests/test_other.py", "find": "", "replace": "x"})
    assert _codes(ps.check_response(plan, _scope("simplicio_loop/mod.py"), tmp_path)) == ["out_of_scope"]


def test_split_module_is_allowed_only_when_the_line_limit_forces_it(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "big.py").write_text("x\n" * 95, encoding="utf-8")
    (tmp_path / "pkg" / "small.py").write_text("x\n" * 10, encoding="utf-8")
    new = _plan({"path": "pkg/part.py", "find": "", "replace": "y = 1\n"})
    forced = ps.check_response(new, _scope("pkg/big.py", max_lines=100), tmp_path)
    assert forced.ok and forced.widenings == [{"path": "pkg/part.py", "rule": "split_for_line_limit"}]
    free = ps.check_response(new, _scope("pkg/small.py", max_lines=100), tmp_path)
    assert _codes(free) == ["out_of_scope"]


def test_file_above_the_line_limit_is_rejected_for_create_and_edit(tmp_path):
    (tmp_path / "a.py").write_text("x\n" * 8, encoding="utf-8")
    create = _plan({"path": "n.py", "find": "", "replace": "y\n" * 11})
    assert ps.check_response(create, _scope("n.py", max_lines=10), tmp_path).violations == ["lines_over_limit:n.py:11"]
    edit = _plan({"path": "a.py", "find": "x\n", "replace": "x\n" * 5})
    assert ps.check_response(edit, _scope("a.py", max_lines=10), tmp_path).violations == ["lines_over_limit:a.py:12"]
    assert ps.check_response(edit, _scope("a.py", max_lines=12), tmp_path).ok


def test_git_dir_path_is_out_of_scope_even_inside_a_dir_prefix(tmp_path):
    plan = _plan({"path": "pkg/../.git/hooks/pre-commit", "find": "", "replace": "x"})
    assert not ps.check_response(plan, _scope(dirs=("pkg/",)), tmp_path).ok


def test_retry_once_then_needs_human():
    assert ps.next_action(1) == "retry"
    assert ps.next_action(2) == "needs_human"
    assert ps.next_action(50) == "needs_human"


def test_retry_message_is_deterministic_and_bounded():
    violations = [f"out_of_scope:f{i}.py" for i in range(40)]
    text = ps.retry_message(violations)
    assert text == ps.retry_message(violations)
    assert text.count("\n") <= ps.MAX_REPORTED + 2 and "out_of_scope:f0.py" in text


def test_scope_from_tasks_uses_target_context_named_paths_and_criteria(tmp_path):
    tasks = [{"index": 1, "text": "fix a.py", "target": "a.py", "context": ["b.py"]}]
    scope = ps.scope_from_tasks(tasks, named_paths=["c.py"], criteria=["AC 1"])
    assert scope.paths == frozenset({"a.py", "b.py", "c.py"}) and scope.criteria == ("AC 1",)
    assert scope.max_lines == ps.MAX_FILE_LINES


def test_counters_split_the_three_rejection_kinds():
    got = ps.counters(["out_of_scope:a.py", "extra_field:/x", "extra_field:/y", "extra_prose:3", "lines_over_limit:a:9"])
    assert got == {"out_of_scope": 1, "extra_field": 2, "extra_prose": 1, "other": 1}


def test_module_never_writes_the_runtime_state_dir():
    source = Path(ps.__file__).read_text(encoding="utf-8").replace(".simplicio-loop", "")
    assert ".simplicio/" not in source and '".simplicio"' not in source
