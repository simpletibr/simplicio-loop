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


def _lines(n: int, *, eol: str = "\n", final: bool = True) -> str:
    return eol.join("x" for _ in range(n)) + (eol if final else "")


def _add(path: str, text: str) -> dict:
    return {"path": path, "find": "", "replace": text}


def test_several_operations_on_one_file_are_added_together(tmp_path):
    (tmp_path / "a.py").write_text(_lines(4000), encoding="utf-8")
    ops = [_add("a.py", _lines(4900)), _add("a.py", _lines(4900))]
    held = ps.check_operations(ops, _scope("a.py"), tmp_path)
    assert held.violations == ["lines_over_limit:a.py:13800"] and held.operations == []
    assert ps.check_operations(ops[:1], _scope("a.py"), tmp_path).ok


@pytest.mark.parametrize("second,ok", [(3999, True), (4000, True), (4001, False)])
def test_8999_9000_9001_across_two_operations(tmp_path, second, ok):
    held = ps.check_operations([_add("n.py", _lines(5000)), _add("n.py", _lines(second))], _scope("n.py"), tmp_path)
    assert held.ok is ok, held.violations
    if not ok:
        assert held.violations == [f"lines_over_limit:n.py:{5000 + second}"]


def test_two_creations_of_one_new_file_are_added_together(tmp_path):
    ops = [_add("n.py", _lines(8000)), _add("n.py", _lines(8000))]
    assert ps.check_operations(ops, _scope("n.py"), tmp_path).violations == ["lines_over_limit:n.py:16000"]


def test_the_running_total_is_kept_per_file(tmp_path):
    assert ps.check_operations([_add("a.py", _lines(8000)), _add("b.py", _lines(8000))], _scope("a.py", "b.py"), tmp_path).ok


def test_an_edit_after_an_addition_works_on_the_running_text(tmp_path):
    ops = [_add("n.py", _lines(8000)), {"path": "n.py", "find": _lines(7000), "replace": "y\n"}]
    assert ps.check_operations(ops, _scope("n.py"), tmp_path).ok


def test_crlf_and_a_missing_final_newline_count_as_lines(tmp_path):
    crlf = [_add("n.py", _lines(5000, eol="\r\n")), _add("n.py", _lines(4001, eol="\r\n"))]
    assert ps.check_operations(crlf, _scope("n.py"), tmp_path).violations == ["lines_over_limit:n.py:9001"]
    bare = [_add("n.py", _lines(5000)), _add("n.py", _lines(4001, final=False))]
    assert ps.check_operations(bare, _scope("n.py"), tmp_path).violations == ["lines_over_limit:n.py:9001"]
    fits = [_add("n.py", _lines(5000, eol="\r\n")), _add("n.py", _lines(4000, final=False))]
    assert ps.check_operations(fits, _scope("n.py"), tmp_path).ok


def _link(tmp_path, name, target):
    (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / name).symlink_to(target)


def test_a_symlink_in_the_scope_that_points_at_a_file_outside_it_is_refused(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "b.py").write_text("x = 1\n", encoding="utf-8")
    _link(tmp_path, "src/lb.py", "../b.py")
    held = ps.check_operations([_add("src/lb.py", "y = 2\n")], _scope("src/lb.py"), tmp_path)
    assert held.violations == ["symlink_target:src/lb.py"] and held.operations == []
    assert (tmp_path / "b.py").read_text(encoding="utf-8") == "x = 1\n"


def test_a_symlink_to_a_file_that_is_in_the_scope_is_still_refused(tmp_path):
    (tmp_path / "real.py").write_text("x = 1\n", encoding="utf-8")
    _link(tmp_path, "link.py", "real.py")
    held = ps.check_operations([_add("link.py", "y = 2\n")], _scope("link.py", "real.py"), tmp_path)
    assert held.violations == ["symlink_target:link.py"]
    assert ps.check_operations([_add("real.py", "y = 2\n")], _scope("link.py", "real.py"), tmp_path).ok


def test_a_path_below_a_symlinked_directory_is_refused(tmp_path):
    (tmp_path / "src").mkdir()
    _link(tmp_path, "lib", "src")
    held = ps.check_operations([_add("lib/new.py", "y = 2\n")], _scope(dirs=("lib/",)), tmp_path)
    assert held.violations == ["symlink_target:lib/new.py"]
    assert ps.check_operations([_add("src/new.py", "y = 2\n")], _scope(dirs=("src/",)), tmp_path).ok


def test_a_dangling_symlink_is_refused(tmp_path):
    _link(tmp_path, "gone.py", "nowhere.py")
    assert _codes(ps.check_operations([_add("gone.py", "y\n")], _scope("gone.py"), tmp_path)) == ["symlink_target"]


def test_the_violation_of_a_symlink_names_its_path():
    assert ps.violation_path("symlink_target:src/lb.py") == "src/lb.py"


def test_a_dir_prefix_needs_its_slash(tmp_path):
    scope = _scope(dirs=("lib/",))
    assert _codes(ps.check_operations([_add("libx/y.py", "y\n")], scope, tmp_path)) == ["out_of_scope"]
    assert ps.check_operations([_add("lib/y.py", "y\n")], scope, tmp_path).ok
    assert not scope.contains("lib")


def test_an_echoed_piece_of_model_text_is_cut_and_redacted():
    secret = "sk-" + "A" * 3000
    text = ps.retry_message([f"extra_field:/operations/0/{secret}", f"out_of_scope:{secret}"])
    assert secret not in text and "AAAA" * 30 not in text and "sk-A" not in text
    assert all(len(line) <= ps.ECHO_CHARS + 40 for line in text.splitlines()[1:])
    assert "[REDACTED" in text and ps.retry_message(["out_of_scope:a.py"]).endswith("out_of_scope:a.py")


def test_a_long_field_name_is_cut_with_an_ellipsis_in_the_violation_and_the_message():
    name = "f" * 3000
    result = ps.check_response('{"operations":[{"path":"a.py","find":"","replace":"x","%s":1}]}' % name, _scope("a.py"), Path("."))
    [violation] = result.violations
    assert len(violation) == ps.ECHO_CHARS and violation.startswith("extra_field:/operations/0/ffff") and violation.endswith("…")
    assert name not in ps.retry_message(result.violations)


def test_a_short_secret_in_a_path_is_redacted_too():
    token = "ghp_" + "Qw3rTy9uIo" * 3 + "Zx1234"
    assert token not in ps.retry_message([f"out_of_scope:dir/{token}.py"])


def test_module_never_writes_the_runtime_state_dir():
    source = Path(ps.__file__).read_text(encoding="utf-8").replace(".simplicio-loop", "")
    assert ".simplicio/" not in source and '".simplicio"' not in source
