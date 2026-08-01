from __future__ import annotations

import hashlib
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from simplicio.changeset_v2 import adapt_changeset, execute_changeset, execute_changeset_bytes


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _changeset(operations, allowlist):
    return {
        "schema": "simplicio.fast.changeset/v2",
        "changeset_id": "cs-1",
        "correlation_id": "run-1",
        "generation": "gen-1",
        "allowlist": allowlist,
        "operations": operations,
    }


@pytest.mark.parametrize(
    ("operation", "files", "expected"),
    [
        (
            {"kind": "replace_range", "path": "a.txt", "start_line": 1, "end_line": 1, "text": "new\n"},
            {"a.txt": "old\n"},
            {"a.txt": "new\n"},
        ),
        ({"kind": "create", "path": "new.txt", "content": "made\n"}, {}, {"new.txt": "made\n"}),
        ({"kind": "delete", "path": "old.txt"}, {"old.txt": "gone\n"}, {"old.txt": None}),
        (
            {"kind": "move", "source": "a.txt", "target": "b.txt"},
            {"a.txt": "move\n"},
            {"a.txt": None, "b.txt": "move\n"},
        ),
        (
            {"kind": "json_patch", "path": "a.json", "patch": [{"op": "replace", "path": "/x", "value": 2}]},
            {"a.json": '{"x": 1}\n'},
            {"a.json": '{\n  "x": 2\n}\n'},
        ),
        (
            {
                "kind": "ast_patch",
                "path": "a.py",
                "patch": {"action": "rename_identifier", "from": "old", "to": "new"},
            },
            {"a.py": "old = 1\nprint(old)\n"},
            {"a.py": "new = 1\nprint(new)\n"},
        ),
    ],
)
def test_all_operation_types_apply_atomically(tmp_path, operation, files, expected):
    for path, content in files.items():
        (tmp_path / path).write_text(content, encoding="utf-8")
    allowlist = sorted(set(files) | set(expected))

    receipt = execute_changeset(_changeset([operation], allowlist), root=tmp_path, apply=True)

    assert receipt["status"] == "ok"
    assert receipt["applied"] is True
    assert receipt["correlation_id"] == "run-1"
    for path, content in expected.items():
        target = tmp_path / path
        assert (target.read_text(encoding="utf-8") if target.exists() else None) == content


def test_stale_generation_allowlist_hash_and_overlap_refuse_before_effect(tmp_path):
    target = tmp_path / "a.txt"
    target.write_text("a\nb\n", encoding="utf-8")
    base = _changeset(
        [
            {
                "kind": "replace_range",
                "path": "a.txt",
                "start_line": 1,
                "end_line": 2,
                "text": "x\n",
                "before_sha256": _sha("stale\n"),
            },
            {"kind": "replace_range", "path": "a.txt", "start_line": 2, "end_line": 2, "text": "y\n"},
        ],
        ["a.txt"],
    )

    stale = execute_changeset(base, root=tmp_path, apply=True, current_generation="gen-2")
    outside = execute_changeset({**base, "allowlist": ["other.txt"]}, root=tmp_path, apply=True)
    overlap = execute_changeset(base, root=tmp_path, apply=True)

    assert stale["errors"][0]["code"] == "stale_generation"
    assert outside["errors"][0]["code"] == "path_not_allowed"
    assert overlap["errors"][0]["code"] == "overlapping_operations"
    assert target.read_text(encoding="utf-8") == "a\nb\n"


def test_multi_file_validation_failure_rolls_back(tmp_path):
    (tmp_path / "a.txt").write_text("a\n", encoding="utf-8")
    changeset = _changeset(
        [
            {"kind": "replace_range", "path": "a.txt", "start_line": 1, "end_line": 1, "text": "changed\n"},
            {"kind": "create", "path": "b.txt", "content": "created\n"},
        ],
        ["a.txt", "b.txt"],
    )
    changeset["validation"] = [{"cmd": [sys.executable, "-c", "raise SystemExit(9)"]}]

    receipt = execute_changeset(changeset, root=tmp_path, apply=True)

    assert receipt["status"] == "refused"
    assert receipt["rollback"] == {
        "attempted": True,
        "succeeded": True,
        "reason": "validation-failed",
    }
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "a\n"
    assert not (tmp_path / "b.txt").exists()


def test_golden_fixture_and_dry_run(tmp_path):
    fixture = json.loads(
        (Path(__file__).parents[1] / "fixtures" / "changeset_v2" / "golden.json").read_text(encoding="utf-8")
    )
    (tmp_path / "app.py").write_text("old\n", encoding="utf-8")

    mechanical = adapt_changeset(fixture, current_generation="gen-1")
    receipt = execute_changeset(fixture, root=tmp_path)

    assert mechanical["schema"] == "simplicio.mechanical-edit/v1"
    assert receipt["dry_run"] is True
    assert receipt["applied"] is False
    assert (tmp_path / "app.py").read_text(encoding="utf-8") == "old\n"


@pytest.mark.parametrize("slots", [1, 5, 20])
def test_concurrent_dry_runs_are_isolated(tmp_path, slots):
    roots = []
    for index in range(slots):
        root = tmp_path / str(index)
        root.mkdir()
        (root / "app.py").write_text("old\n", encoding="utf-8")
        roots.append(root)
    changeset = _changeset(
        [{"kind": "replace_range", "path": "app.py", "start_line": 1, "end_line": 1, "text": "new\n"}],
        ["app.py"],
    )

    with ThreadPoolExecutor(max_workers=slots) as pool:
        receipts = list(pool.map(lambda root: execute_changeset(changeset, root=root), roots))

    assert all(receipt["status"] == "ok" and receipt["dry_run"] for receipt in receipts)
    assert all((root / "app.py").read_text(encoding="utf-8") == "old\n" for root in roots)


def test_corrupt_payload_and_effect_unknown_are_explicit(monkeypatch, tmp_path):
    from simplicio import changeset_v2

    invalid = changeset_v2.execute_changeset_json("{broken", root=tmp_path)
    monkeypatch.setattr(
        changeset_v2,
        "execute_plan",
        lambda *_args, **_kwargs: {
            "status": "effect_unknown",
            "applied": False,
            "files": [],
            "errors": [{"code": "runtime_transport_lost", "message": "outcome unknown"}],
        },
    )
    unknown = changeset_v2.execute_changeset(
        _changeset([{"kind": "create", "path": "a.txt", "content": "x"}], ["a.txt"]),
        root=tmp_path,
        apply=True,
    )

    assert invalid["errors"][0]["code"] == "invalid_json"
    assert unknown["effect_unknown"] is True
    assert unknown["status"] == "effect_unknown"


def test_fast_binary_schema_alias_is_rejected_from_json_adapter(tmp_path):
    changeset = _changeset(
        [{"kind": "create", "path": "legacy.txt", "content": "legacy"}],
        ["legacy.txt"],
    )
    changeset["schema"] = "simplicio.fast.binary-changeset/v1"
    receipt = execute_changeset(changeset, root=tmp_path, apply=True)
    assert receipt["status"] == "refused"
    assert receipt["errors"][0]["code"] == "incompatible_schema"
    assert not (tmp_path / "legacy.txt").exists()


def test_fast_binary_bytes_are_decoded_by_the_official_adapter(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(r"C:\Users\Z0059V7A\m\repos\simplicio-fast\src")
    import sys

    monkeypatch.delitem(sys.modules, "simplicio_fast", raising=False)
    from simplicio_fast.binary_changeset import BinaryChangeSet, ChangeOperation

    content = b"binary\n"
    changeset = BinaryChangeSet(
        repository=str(tmp_path.resolve()),
        base_generation="base",
        overlay_generation="overlay",
        attempt="attempt",
        worktree_id="slot-414",
        lease_id="lease-414",
        fencing_token="fence-414",
        allowed_paths=("binary.txt",),
        operations=(
            ChangeOperation.from_dict(
                {
                    "op": "create",
                    "path": "binary.txt",
                    "content_b64": __import__("base64").b64encode(content).decode(),
                    "after_sha256": __import__("hashlib").sha256(content).hexdigest(),
                }
            ),
        ),
    )

    receipt = execute_changeset_bytes(changeset.encode(), root=tmp_path, apply=True)

    assert receipt["status"] == "ok"
    assert receipt["input_format"] == "simplicio.fast.binary-changeset/v1"
    assert (tmp_path / "binary.txt").read_bytes() == content


def test_json_renamed_as_binary_is_rejected_without_json_decode(tmp_path):
    receipt = execute_changeset_bytes(b'{"schema":"simplicio.fast.binary-changeset/v1"}', root=tmp_path)

    assert receipt["status"] == "refused"
    assert receipt["errors"][0]["code"] == "binary_magic_invalid"
