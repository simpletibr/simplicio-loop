from __future__ import annotations

import hashlib

from simplicio.mapper_binding import (
    MAPPER_BINDING_SCHEMA,
    build_mapper_binding,
    canonical_mapper_binding,
    validate_mapper_binding,
    verify_mapper_sources,
)
from simplicio.mechanical_edit import execute_plan
from simplicio.plan_compiler import derive_ad_hoc_edit


def _binding() -> dict:
    return build_mapper_binding(
        "wesleysimplicio/example",
        7,
        "tree-7",
        {"src/app.py": hashlib.sha256(b"print(1)\\n").hexdigest()},
    )


def test_binding_is_canonical_and_self_verifying() -> None:
    binding = _binding()
    assert binding["schema"] == MAPPER_BINDING_SCHEMA
    assert canonical_mapper_binding(dict(reversed(list(binding.items())))) == binding
    assert validate_mapper_binding(binding) == []


def test_binding_detects_missing_and_hash_drift_without_editing() -> None:
    binding = _binding()
    errors = verify_mapper_sources(binding, {"src/app.py": "0" * 64})
    assert [row["code"] for row in errors] == ["hash_drift"]
    errors = verify_mapper_sources(binding, {})
    assert [row["code"] for row in errors] == ["missing_target"]


def test_binding_rejects_workspace_escape_and_tampering() -> None:
    binding = _binding()
    invalid = {**binding, "source_hashes": {"../secret": "0" * 64}}
    assert validate_mapper_binding(invalid)
    tampered = {**binding, "generation": "8"}
    assert any("binding_digest" in error for error in validate_mapper_binding(tampered))


def test_derived_edit_carries_mapper_binding_and_can_require_it() -> None:
    result = derive_ad_hoc_edit(
        {
            "intent": "replace greeting",
            "operations": [{"kind": "replace", "target": "src/app.py", "old": "a", "new": "b"}],
            "mapper_binding": _binding(),
            "require_mapper_binding": True,
        }
    )
    assert result["status"] == "derived"
    assert result["proposal"]["mapper_binding_digest"] == _binding()["binding_digest"]
    assert result["receipt"]["mapper_binding"]["generation"] == "7"


def test_mechanical_plan_refuses_mapper_hash_drift(tmp_path) -> None:
    target = tmp_path / "src" / "app.py"
    target.parent.mkdir()
    target.write_text("a\n", encoding="utf-8")
    binding = build_mapper_binding(
        "owner/repo", 7, "tree-7", {"src/app.py": hashlib.sha256(b"old\n").hexdigest()}
    )
    plan = {
        "schema": "simplicio.mechanical-edit/v1",
        "touched_files": ["src/app.py"],
        "operations": [
            {"op": "replace_range", "path": "src/app.py", "start_line": 1, "end_line": 1, "text": "b\n"}
        ],
        "mapper_binding": binding,
    }
    result = execute_plan(plan, root=tmp_path, apply=True, allow_native=False)
    assert result["status"] == "refused"
    assert result["errors"][0]["code"] == "hash_drift"
    assert target.read_text(encoding="utf-8") == "a\n"
