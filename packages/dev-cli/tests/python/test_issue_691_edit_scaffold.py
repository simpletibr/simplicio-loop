from __future__ import annotations

import hashlib
import json
import time

import pytest

from simplicio.mapper_binding import build_mapper_binding
from simplicio.mechanical_edit import (
    EDIT_PLAN_SCHEMA,
    EDIT_RECEIPT_SCHEMA,
    TextEdit,
    apply_text_edits,
    build_edit_plan,
    execute_plan,
)
from simplicio.scaffold_contract import SCAFFOLD_RECEIPT_SCHEMA, plan_scaffold, scaffold_receipt


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _binding(files: dict[str, str], generation: str = "generation-1") -> dict:
    return build_mapper_binding(
        "owner/repo", generation, f"tree-{generation}", {k: _sha(v) for k, v in files.items()}
    )


def _redigest(plan: dict) -> dict:
    plan = dict(plan)
    body = {key: value for key, value in plan.items() if key != "plan_digest"}
    plan["plan_digest"] = hashlib.sha256(
        json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return plan


def test_text_edit_is_single_anchor_atomic_and_byte_stable() -> None:
    files = {"src/app.py": "hello\n", "src/other.py": "stable\n"}
    edits = [
        TextEdit("src/app.py", "hello", "goodbye", _sha("hello\n")),
        TextEdit("src/other.py", "missing", "changed"),
    ]

    with pytest.raises(ValueError) as caught:
        apply_text_edits(files, edits, mapper_binding=_binding(files))
    assert caught.value.args[0]["code"] == "missing_anchor"
    assert files == {"src/app.py": "hello\n", "src/other.py": "stable\n"}

    valid = [edits[0]]
    first, receipt = apply_text_edits(files, valid, mapper_binding=_binding(files))
    second, receipt_again = apply_text_edits(files, valid, mapper_binding=_binding(files))
    assert first == second == {"src/app.py": "goodbye\n", "src/other.py": "stable\n"}
    assert receipt.to_dict() == receipt_again.to_dict()
    assert receipt.schema == EDIT_RECEIPT_SCHEMA
    assert receipt.to_json() == json.dumps(
        receipt.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    assert TextEdit("a.txt", "a", "b").to_dict() == {"path": "a.txt", "find": "a", "replace": "b"}
    assert TextEdit("a.txt", "a", "b", _sha("a")).to_dict()["expected_sha256"] == _sha("a")


def test_text_edit_serializer_without_binding_and_input_mapping_are_stable() -> None:
    files = {"a.txt": "a\n"}
    updated, receipt = apply_text_edits(files, [TextEdit("a.txt", "a", "b")])
    assert updated == {"a.txt": "b\n"}
    assert files == {"a.txt": "a\n"}
    assert "mapper_binding" not in receipt.to_dict()


@pytest.mark.parametrize(
    ("files", "edits", "code"),
    [
        ({"a\\b.txt": "", "a/b.txt": ""}, [], "invalid_path"),
        ({"a.txt": b"a"}, [], "invalid_schema"),
        ({"a.txt": "a"}, [object()], "invalid_schema"),
        ({"a.txt": "a"}, [TextEdit("missing.txt", "a", "b")], "missing_target"),
        ({"a.txt": "a"}, [TextEdit("a.txt", "", "b")], "invalid_schema"),
        ({"a.txt": "a"}, [TextEdit("a.txt", "a", 1)], "invalid_schema"),
        ({"a.txt": "a"}, [TextEdit("a.txt", "a", "b", "bad")], "invalid_schema"),
        ({"a.txt": "a"}, [TextEdit(None, "a", "b")], "invalid_path"),  # type: ignore[arg-type]
    ],
)
def test_text_edit_kernel_rejects_invalid_inputs(files, edits, code) -> None:
    with pytest.raises(ValueError) as caught:
        apply_text_edits(files, edits)
    assert caught.value.args[0]["code"] == code


def test_text_edit_kernel_rejects_invalid_mapper_observation() -> None:
    with pytest.raises(ValueError) as caught:
        apply_text_edits({"a.txt": "a"}, [TextEdit("a.txt", "a", "b")], mapper_binding={"bad": True})
    assert caught.value.args[0]["code"] == "invalid_mapper_binding"

    with pytest.raises(ValueError) as caught:
        apply_text_edits(
            {"a.txt": "changed"},
            [TextEdit("a.txt", "changed", "new")],
            mapper_binding=_binding({"a.txt": "original"}),
        )
    assert caught.value.args[0]["code"] == "hash_drift"


@pytest.mark.parametrize(
    ("source", "find", "code"),
    [("x x\n", "x", "ambiguous_anchor"), ("x\n", "y", "missing_anchor")],
)
def test_text_edit_conflicts_are_typed(source: str, find: str, code: str) -> None:
    with pytest.raises(ValueError) as caught:
        apply_text_edits({"a.txt": source}, [TextEdit("a.txt", find, "z")])
    assert caught.value.args[0]["code"] == code


def test_text_edit_expected_hash_drift_is_fail_closed() -> None:
    with pytest.raises(ValueError) as caught:
        apply_text_edits(
            {"a.txt": "current\n"},
            [TextEdit("a.txt", "current", "new", _sha("stale\n"))],
        )
    assert caught.value.args[0]["code"] == "hash_drift"


def test_text_edit_normalizes_portable_paths_and_line_endings() -> None:
    updated, receipt = apply_text_edits(
        {"src\\app.txt": "old\r\n"},
        [TextEdit("src/app.txt", "old", "new", _sha("old\r\n"))],
    )
    assert updated == {"src/app.txt": "new\r\n"}
    assert receipt.edits[0].path == "src/app.txt"
    assert receipt.edits[0].before_sha256 == _sha("old\r\n")


def test_mapper_binding_uses_exact_cross_platform_source_bytes() -> None:
    files = {"src/app.txt": "old\r\n"}
    binding = _binding(files)
    updated, receipt = apply_text_edits(
        files,
        [TextEdit("src\\app.txt", "old", "new")],
        mapper_binding=binding,
    )
    assert updated == {"src/app.txt": "new\r\n"}
    assert receipt.edits[0].before_sha256 == _sha("old\r\n")


def test_text_edit_rejects_workspace_escape_in_pure_kernel() -> None:
    with pytest.raises(ValueError) as caught:
        apply_text_edits({"safe.txt": "safe\n"}, [TextEdit("..\\secret.txt", "x", "y")])
    assert caught.value.args[0]["code"] == "invalid_path"


def test_edit_plan_binds_mapper_provenance_and_execute_detects_drift(tmp_path) -> None:
    target = tmp_path / "app.py"
    target.write_text("old\n", encoding="utf-8")
    binding = _binding({"app.py": "old\n"})
    plan = build_edit_plan([TextEdit("app.py", "old", "new", _sha("old\n"))], mapper_binding=binding)
    assert plan["schema"] == EDIT_PLAN_SCHEMA
    assert plan["mapper_binding"]["repository_id"] == "owner/repo"
    assert plan["mapper_binding"]["generation"] == "generation-1"
    assert plan == build_edit_plan([TextEdit("app.py", "old", "new", _sha("old\n"))], mapper_binding=binding)

    target.write_text("drifted\n", encoding="utf-8")
    result = execute_plan(plan, root=tmp_path, apply=True, allow_native=False)
    assert result["schema"] == EDIT_RECEIPT_SCHEMA
    assert result["status"] == "refused"
    assert result["errors"][0]["code"] == "hash_drift"
    assert target.read_text(encoding="utf-8") == "drifted\n"


def test_edit_receipt_marks_mapper_refresh_only_for_effective_byte_changes(tmp_path) -> None:
    target = tmp_path / "app.py"
    target.write_text("old\n", encoding="utf-8")
    binding = _binding({"app.py": "old\n"})

    noop_plan = build_edit_plan([TextEdit("app.py", "old", "old")], mapper_binding=binding)
    noop = execute_plan(noop_plan, root=tmp_path, apply=False, allow_native=False)
    assert noop["noop"] is True
    assert noop["mapper_refresh"]["status"] == "not_required"
    assert noop["mapper_refresh"]["changed_paths"] == []

    changed_plan = build_edit_plan([TextEdit("app.py", "old", "new")], mapper_binding=binding)
    changed = execute_plan(changed_plan, root=tmp_path, apply=False, allow_native=False)
    assert changed["noop"] is False
    assert changed["mapper_refresh"]["status"] == "required"
    assert changed["mapper_refresh"]["changed_paths"] == ["app.py"]
    assert changed["receipt_digest"]


def test_edit_plan_is_atomic_when_a_later_file_conflicts(tmp_path) -> None:
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("one\n", encoding="utf-8")
    second.write_text("two two\n", encoding="utf-8")
    binding = _binding({"first.txt": "one\n", "second.txt": "two two\n"})
    plan = build_edit_plan(
        [TextEdit("first.txt", "one", "ONE"), TextEdit("second.txt", "two", "TWO")],
        mapper_binding=binding,
    )

    result = execute_plan(plan, root=tmp_path, apply=True, allow_native=False)
    assert result["status"] == "refused"
    assert result["errors"][0]["code"] == "ambiguous_anchor"
    assert first.read_text(encoding="utf-8") == "one\n"
    assert second.read_text(encoding="utf-8") == "two two\n"


def test_edit_plan_rejects_mapper_unbound_target() -> None:
    with pytest.raises(ValueError) as caught:
        build_edit_plan(
            [TextEdit("src/app.py", "old", "new")],
            mapper_binding=_binding({"README.md": "readme\n"}),
        )
    assert caught.value.args[0]["code"] == "missing_target"


@pytest.mark.parametrize(
    "edits",
    [
        [],
        [object()],
        [TextEdit("app.py", "", "new")],
        [TextEdit("app.py", "old", 1)],
        [TextEdit("app.py", "old", "new", "bad")],
        [TextEdit("app.py", "old", "new", _sha("other\n"))],
    ],
)
def test_edit_plan_builder_rejects_invalid_edit_inputs(edits) -> None:
    with pytest.raises(ValueError) as caught:
        build_edit_plan(edits, mapper_binding=_binding({"app.py": "old\n"}))
    assert caught.value.args[0]["code"] in {"invalid_schema", "hash_drift"}


def test_edit_plan_allows_ordered_single_anchor_edits_on_one_file() -> None:
    binding = _binding({"app.py": "old\n"})
    plan = build_edit_plan(
        [TextEdit("app.py", "old", "middle"), TextEdit("app.py", "middle", "new")],
        mapper_binding=binding,
    )
    assert "expected_sha256" in plan["operations"][0]
    assert "expected_sha256" not in plan["operations"][1]
    updated, _ = apply_text_edits(
        {"app.py": "old\n"},
        [TextEdit("app.py", "old", "middle"), TextEdit("app.py", "middle", "new")],
        mapper_binding=binding,
    )
    assert updated == {"app.py": "new\n"}


def test_edit_plan_rejects_workspace_escape_before_effect(tmp_path) -> None:
    outside = tmp_path.parent / "691-outside.txt"
    outside.write_text("secret\n", encoding="utf-8")
    binding = _binding({"safe.txt": "safe\n"})
    plan = {
        "schema": EDIT_PLAN_SCHEMA,
        "mapper_binding": binding,
        "operations": [
            {"op": "replace_anchor", "path": "../691-outside.txt", "find": "secret", "replace": "x"}
        ],
        "touched_files": ["../691-outside.txt"],
    }
    result = execute_plan(plan, root=tmp_path, apply=True, allow_native=False)
    assert result["status"] == "refused"
    assert result["errors"][0]["code"] in {"invalid_path", "unsafe_path"}
    assert outside.read_text(encoding="utf-8") == "secret\n"


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("mapper_binding", None, "invalid_mapper_binding"),
        ("mapper_binding_digest", "0" * 64, "invalid_mapper_binding"),
        ("runtime_authorization_required", False, "invalid_authorization"),
        # issue #1331: `create_file` became a supported canonical op (edit
        # plans can now create files); an op name outside that list is what
        # still exercises `unsupported_operation`.
        ("operations", [{"op": "insert_before", "path": "app.py", "anchor": "old", "text": "new"}],
         "unsupported_operation"),
        ("touched_files", ["other.py"], "invalid_schema"),
        (
            "operations",
            [{"op": "replace_anchor", "path": "src\\app.py", "find": "old", "replace": "new"}],
            "invalid_path",
        ),
    ],
)
def test_edit_plan_validation_is_fail_closed(tmp_path, field, value, code) -> None:
    target = tmp_path / "app.py"
    target.write_text("old\n", encoding="utf-8")
    plan = build_edit_plan(
        [TextEdit("app.py", "old", "new")],
        mapper_binding=_binding({"app.py": "old\n"}),
    )
    plan[field] = value
    result = execute_plan(plan, root=tmp_path, apply=True, allow_native=False)
    assert result["status"] == "refused"
    assert code in {error["code"] for error in result["errors"]}
    assert target.read_text(encoding="utf-8") == "old\n"


@pytest.mark.parametrize(
    ("operation", "code"),
    [
        ({"op": "replace_anchor", "path": "app.py", "find": "", "replace": "new"}, "invalid_schema"),
        ({"op": "replace_anchor", "path": "app.py", "find": "old", "replace": 1}, "invalid_schema"),
        (
            {
                "op": "replace_anchor",
                "path": "app.py",
                "find": "old",
                "replace": "new",
                "expected_sha256": "bad",
            },
            "invalid_schema",
        ),
    ],
)
def test_edit_plan_anchor_schema_is_checked_before_effect(tmp_path, operation, code) -> None:
    target = tmp_path / "app.py"
    target.write_text("old\n", encoding="utf-8")
    plan = _redigest(
        {
            "schema": EDIT_PLAN_SCHEMA,
            "touched_files": ["app.py"],
            "operations": [operation],
            "mapper_binding": _binding({"app.py": "old\n"}),
            "mapper_binding_digest": _binding({"app.py": "old\n"})["binding_digest"],
            "runtime_authorization_required": True,
        }
    )
    result = execute_plan(plan, root=tmp_path, apply=True, allow_native=False)
    assert result["status"] == "refused"
    assert result["errors"][0]["code"] == code
    assert target.read_text(encoding="utf-8") == "old\n"


def test_edit_plan_rejects_empty_canonical_operation_list(tmp_path) -> None:
    target = tmp_path / "app.py"
    target.write_text("old\n", encoding="utf-8")
    binding = _binding({"app.py": "old\n"})
    plan = _redigest(
        {
            "schema": EDIT_PLAN_SCHEMA,
            "touched_files": [],
            "operations": [],
            "mapper_binding": binding,
            "mapper_binding_digest": binding["binding_digest"],
            "runtime_authorization_required": True,
        }
    )
    result = execute_plan(plan, root=tmp_path, apply=True, allow_native=False)
    assert result["status"] == "refused"
    assert result["errors"][0]["code"] == "invalid_schema"


def test_edit_command_uses_dev_cli_kernel_for_canonical_plan(tmp_path, monkeypatch, capsys) -> None:
    from simplicio import cli

    target = tmp_path / "app.py"
    target.write_text("old\n", encoding="utf-8")
    plan = build_edit_plan(
        [TextEdit("app.py", "old", "new", _sha("old\n"))],
        mapper_binding=_binding({"app.py": "old\n"}),
    )
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")
    monkeypatch.setattr("simplicio.commands.edit._runtime_edit_binary", lambda: "/bin/simplicio")

    assert (
        cli.main(
            [
                "edit",
                "--root",
                str(tmp_path),
                "--plan",
                str(plan_path),
                "--apply",
                "--json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == EDIT_RECEIPT_SCHEMA
    assert payload["applied"] is True
    assert target.read_text(encoding="utf-8") == "new\n"


def test_scaffold_plans_cover_required_stacks_and_are_stable() -> None:
    binding = _binding({"README.md": "readme\n"})
    expected = {
        "rust-crate": {"demo/Cargo.toml", "demo/src/lib.rs"},
        "rust-binary": {"demo/Cargo.toml", "demo/src/main.rs"},
        "python-package": {"demo/pyproject.toml", "demo/demo/__init__.py"},
        "node-package": {"demo/package.json", "demo/src/index.js"},
    }
    for kind, paths in expected.items():
        first = plan_scaffold(kind, "demo", mapper_binding=binding)
        second = plan_scaffold(kind, "demo", mapper_binding=binding)
        assert first == second
        assert first["status"] == "planned"
        assert {row["path"] for row in first["operations"]} == paths
        assert first["mapper_binding"]["generation"] == "generation-1"
        assert first["runtime_authorization_required"] is True


def test_scaffold_rejects_unsupported_and_unsafe_inputs() -> None:
    binding = _binding({"README.md": "readme\n"})
    assert (
        plan_scaffold("go-module", "demo", mapper_binding=binding)["errors"][0]["code"]
        == "unsupported_scaffold"
    )
    assert (
        plan_scaffold("rust-crate", "../demo", mapper_binding=binding)["errors"][0]["code"] == "invalid_path"
    )


def test_scaffold_receipt_is_versioned_and_keeps_mapper_provenance() -> None:
    plan = plan_scaffold("rust-crate", "demo", mapper_binding=_binding({"README.md": "readme\n"}))
    receipt = scaffold_receipt(plan)
    assert receipt["schema"] == SCAFFOLD_RECEIPT_SCHEMA
    assert receipt["status"] == "planned"
    assert receipt["mapper_binding"]["generation"] == "generation-1"
    assert receipt == scaffold_receipt(plan)


def test_text_edit_kernel_benchmark_stays_bounded() -> None:
    started = time.perf_counter()
    for _ in range(100):
        updated, _ = apply_text_edits({"app.py": "old\n"}, [TextEdit("app.py", "old", "new")])
        assert updated["app.py"] == "new\n"
    per_call = (time.perf_counter() - started) / 100
    assert per_call < 0.01
