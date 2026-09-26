"""Release-gate coverage for critical defensive branches."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from simplicio import doctor
from simplicio import execution_contract as ec
from simplicio import mechanical_edit as me


def test_doctor_renderers_cover_all_human_states(capsys, tmp_path) -> None:
    spec = SimpleNamespace(
        label="Model",
        model_id="model/id",
        repo_id="repo/id",
        filename="model.gguf",
        size_gb_q4=1.5,
        notes="notes",
    )
    profile = SimpleNamespace(
        os_name="macOS",
        apple_silicon=True,
        gpu_name="M4",
        ram_gb=32,
        vram_gb=16,
        detected_via={"ram": "test", "gpu": "test"},
        tier="high",
    )
    for installed, can_download, reason in (
        (True, True, "ready"),
        (False, True, "download"),
        (False, False, "too small"),
    ):
        doctor._render_human(
            SimpleNamespace(
                spec=spec,
                can_run=installed,
                can_download=can_download,
                installed=installed,
                reason=reason,
            ),
            profile,
        )

    statuses = [
        SimpleNamespace(name="current", installed="1", floor="1", latest="1", needs_upgrade=False),
        SimpleNamespace(name="behind", installed="1", floor="1", latest="2", needs_upgrade=True),
    ]
    doctor._render_ecosystem(statuses, [])
    doctor._render_ecosystem(statuses, ["behind"])
    doctor._render_ecosystem(statuses[:1], [])
    doctor._render_events({"exists": False, "path": "events"})
    doctor._render_events(
        {
            "exists": True,
            "path": "events",
            "count": 1,
            "recent": [{"ts": "now", "event": "ok", "payload": {"x": 1}}],
        }
    )
    doctor._render_mapper_versions(
        {
            "mapper": {
                "installed": None,
                "declared_range": None,
                "tested_against": None,
                "tested_against_reason": "no lock",
                "unavailable_reason": "offline",
            },
            "drift": {"has_drift": True, "kind": "stale", "reason": "old"},
        }
    )
    doctor._render_mapper_versions(
        {
            "mapper": {
                "installed": "1",
                "declared_range": ">=1",
                "tested_against": "1",
                "tested_against_reason": "",
                "unavailable_reason": "offline",
            },
            "drift": {"has_drift": False, "kind": None, "reason": ""},
        }
    )
    doctor._render_native_delegation({"exists": False, "verbs": {}, "path": "events"})
    doctor._render_native_delegation(
        {
            "exists": True,
            "path": "events",
            "native_pct": 50.0,
            "total": 2,
            "verbs": {"edit": {"native": 1, "python": 1, "total": 2, "native_pct": 50.0}},
        }
    )
    doctor._render_hub_status({"mode": "off", "identity_complete": False, "local_scheduler_allowed": True})
    assert "dependency freshness" in capsys.readouterr().out


def test_doctor_freshness_upgrade_rechecks(monkeypatch) -> None:
    calls: list[bool] = []
    monkeypatch.setattr(doctor, "tracked_packages", lambda: ["pkg"])
    monkeypatch.setattr(
        doctor, "eco_check", lambda packages, refresh=False: calls.append(refresh) or ["status"]
    )
    monkeypatch.setattr(doctor, "eco_ensure_latest", lambda force, packages: ["pkg"])
    assert doctor._ecosystem_freshness(refresh=True, upgrade=True) == (["status"], ["pkg"])
    assert calls == [True, True]


def test_doctor_main_covers_json_and_human_storage_routes(monkeypatch, tmp_path, capsys) -> None:
    spec = SimpleNamespace(
        label="Model",
        model_id="model/id",
        repo_id="repo/id",
        filename="model.gguf",
        size_gb_q4=1.5,
        notes="notes",
    )
    profile = SimpleNamespace(
        os_name="Windows",
        apple_silicon=False,
        gpu_name="",
        ram_gb=16,
        vram_gb=0,
        detected_via={"ram": "test", "gpu": "test"},
        tier="mid",
    )
    result = SimpleNamespace(
        spec=spec,
        can_run=False,
        can_download=False,
        installed=False,
        reason="disabled",
        to_dict=lambda: {"schema": "simplicio.doctor/v1", "can_run": False},
    )
    storage = {
        "mapper_store": {"ready": True, "reason": "ready", "version": "0.26.9"},
        "route": {"selected": "mapper", "reason": "capability"},
        "side_effects": {"writes": 0},
        "legacy": {"index.sqlite3": {"present": False}},
    }
    monkeypatch.setattr(doctor, "detect", lambda: profile)
    monkeypatch.setattr(doctor, "ensure_recommended", lambda _: result)
    monkeypatch.setattr(doctor, "events_summary", lambda *args, **kwargs: {"exists": False, "path": "events"})
    monkeypatch.setattr(
        doctor, "native_delegation_summary", lambda _: {"exists": False, "verbs": {}, "path": "events"}
    )
    monkeypatch.setattr(
        doctor.HubTaskAdapter,
        "create",
        classmethod(
            lambda cls: SimpleNamespace(
                doctor_status=lambda: {
                    "mode": "off",
                    "identity_complete": False,
                    "local_scheduler_allowed": True,
                }
            )
        ),
    )
    monkeypatch.setattr(
        doctor,
        "versions_report",
        lambda *, refresh=False: {
            "mapper": {
                "installed": "0.26.9",
                "declared_range": ">=0.26",
                "tested_against": "0.26.9",
                "tested_against_reason": "",
                "unavailable_reason": "offline",
            },
            "drift": {"has_drift": False, "kind": None, "reason": ""},
        },
    )
    monkeypatch.setattr("simplicio.store_adapter.storage_capabilities", lambda _: storage)

    assert doctor.main(["--json", "--no-check-updates", "--storage", "--root", str(tmp_path)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["storage"] == storage

    assert doctor.main(["--no-check-updates", "--storage", "--root", str(tmp_path)]) == 0
    assert "storage capabilities (read-only):" in capsys.readouterr().out


def _native_payload(path: Path, **updates):
    payload = {
        "schema": me.NATIVE_EDIT_RESULT_SCHEMA,
        "status": "ok",
        "file": str(path),
        "changed": True,
        "dry_run": False,
        "operations_applied": 2,
        "before_sha256": "before",
        "after_sha256": "after",
    }
    payload.update(updates)
    return payload


def test_mechanical_native_translation_and_fallbacks(tmp_path, monkeypatch) -> None:
    target = tmp_path / "a.py"
    target.write_text("a", encoding="utf-8")
    assert me._translate_native_result([], tmp_path) is None
    assert me._translate_native_result({"schema": "wrong"}, tmp_path) is None
    assert me._translate_native_result(_native_payload(target, status="checks_failed"), tmp_path) is None
    assert me._translate_native_result(_native_payload(target, changed="yes"), tmp_path) is None
    assert me._translate_native_result(_native_payload(tmp_path.parent / "x"), tmp_path) is None

    result = me._translate_native_result(
        _native_payload(target, status="skipped", post_edit_skipped_reason="reason"),
        tmp_path,
    )
    assert result is None
    noop = me._translate_native_result(
        _native_payload(
            target,
            before_sha256="same",
            after_sha256="same",
            changed=False,
            dry_run=True,
        ),
        tmp_path,
    )
    assert noop and noop["noop"] is True and noop["applied"] is False

    monkeypatch.setenv("SIMPLICIO_DEV_CLI_NO_RUNTIME_EDIT", "1")
    assert me._native_edit_binary() is None
    monkeypatch.delenv("SIMPLICIO_DEV_CLI_NO_RUNTIME_EDIT")
    monkeypatch.setattr(me.shutil, "which", lambda _: None)
    assert me._try_native_edit({}, tmp_path, apply=False) is None


def test_mechanical_text_json_ast_and_filesystem_helpers(tmp_path, monkeypatch) -> None:
    for operation, expected in (
        ({"op": "replace_range", "path": "a", "start_line": 1, "text": "x\n"}, "x\nb\n"),
        ({"op": "delete_range", "path": "a", "start_line": 1}, "b\n"),
        ({"op": "insert_before", "path": "a", "line": 1, "text": "x\n"}, "x\na\nb\n"),
        ({"op": "insert_after", "path": "a", "line": 1, "text": "x\n"}, "a\nx\nb\n"),
    ):
        snapshot = {"a": b"a\nb\n"}
        me._apply_text_operation(snapshot, operation)
        assert snapshot["a"].decode() == expected
    with pytest.raises(me.MechanicalEditError, match="invalid line range"):
        me._apply_text_operation(
            {"a": b"a\n"},
            {"op": "replace_range", "path": "a", "start_line": 9, "end_line": 9, "text": "x\n"},
        )

    snapshot = {"data.json": b'{"items":[1],"old":1}'}
    me._apply_json_patch(
        snapshot,
        {
            "path": "data.json",
            "patch": [
                {"op": "add", "path": "/items/-", "value": 2},
                {"op": "replace", "path": "/items/0", "value": 3},
                {"op": "remove", "path": "/old"},
                {"op": "add", "path": "/new", "value": 4},
            ],
        },
    )
    assert json.loads(snapshot["data.json"]) == {"items": [3, 2], "new": 4}
    with pytest.raises(me.MechanicalEditError, match="root JSON pointer"):
        me._apply_json_patch_row({}, {"op": "add", "path": "", "value": 1})
    with pytest.raises(me.MechanicalEditError, match="invalid json patch row"):
        me._apply_json_patch_row({}, {"op": "move", "path": "/x"})
    with pytest.raises(me.MechanicalEditError) as invalid_json:
        me._apply_json_patch({"x": b"{"}, {"path": "x", "patch": []})
    assert invalid_json.value.code == "invalid_json_file"
    with pytest.raises(me.MechanicalEditError, match="must be a list"):
        me._apply_json_patch({"x": b"{}"}, {"path": "x", "patch": {}})
    with pytest.raises(me.MechanicalEditError, match="row must be object"):
        me._apply_json_patch({"x": b"{}"}, {"path": "x", "patch": ["bad"]})

    source = {"a.py": b"value = 1\nprint(value)\n"}
    me._apply_ast_patch(
        source,
        {"path": "a.py", "patch": {"action": "rename_identifier", "from": "value", "to": "item"}},
    )
    assert b"item" in source["a.py"]
    for patch, message in (
        ({"action": "other"}, "only Python"),
        ({"action": "rename_identifier", "from": 1, "to": "x"}, "needs from/to"),
    ):
        with pytest.raises(me.MechanicalEditError, match=message):
            me._apply_ast_patch({"a.py": b"x=1"}, {"path": "a.py", "patch": patch})
    with pytest.raises(me.MechanicalEditError) as ast_error:
        me._apply_ast_patch(
            # An unclosed bracket, not an unterminated string literal: since
            # Python 3.12's tokenizer changes (also present on this 3.11
            # install), an unterminated string emits an ERRORTOKEN and
            # returns normally instead of raising `tokenize.TokenError` —
            # only a genuinely incomplete multi-line statement (unbalanced
            # brackets/parens) still does, which is what `_apply_ast_patch`'s
            # `except tokenize.TokenError` clause actually guards against.
            {"a.py": b"("},
            {
                "path": "a.py",
                "patch": {"action": "rename_identifier", "from": "x", "to": "y"},
            },
        )
    assert ast_error.value.code == "ast_patch_failed"

    assert me._decode_for_diff(b"\xff") == "<binary>\n"
    assert "a/x" in me._build_diff({"x": None}, {"x": b"new\n"})
    assert me._selected_range("a\nb\n", {"line": 2}) == "b\n"
    assert me._contract_hash("a\r\n") == me._contract_hash("a\n")
    assert me._contract_hash(b"\xff") == me.sha256_text(b"\xff")
    assert me._normalize_patch_text("x\ny\n", "a\r\n") == "x\r\ny\r\n"

    (tmp_path / "old").write_text("old", encoding="utf-8")
    backups = me._backup_existing(tmp_path, {"old": b"x", "new": None})
    me._write_snapshot(tmp_path, {"old": None, "new": b"new"})
    assert not (tmp_path / "old").exists()
    me._restore(tmp_path, backups)
    assert (tmp_path / "old").read_text() == "old"
    assert not (tmp_path / "new").exists()
    with pytest.raises(me.MechanicalEditError, match="unsafe"):
        me._safe_path(tmp_path, "../escape")


def test_mechanical_validation_and_result_helpers(tmp_path, monkeypatch) -> None:
    assert me.execute_plan_json("{", root=tmp_path)["errors"][0]["code"] == "invalid_json"
    assert me.execute_plan_json("[]", root=tmp_path)["status"] == "refused"
    rows = me._run_validation([{"cmd": "bad"}, "skip"], tmp_path)
    assert rows[0]["passed"] is False
    monkeypatch.setattr(
        me.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="ok", stderr=""),
    )
    assert me._run_validation([{"cmd": ["check"]}], tmp_path)[0]["passed"] is True
    monkeypatch.setattr(me.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(OSError("x")))
    assert "x" in me._run_validation([{"cmd": ["check"]}], tmp_path)[0]["error"]
    assert me._run_validation(None, tmp_path) == []
    assert me._file_hash_rows({"a": b"1", "b": None}, {"a": b"2", "b": None})[0]["path"] == "a"
    refused = me._refused([{"code": "x"}], root=tmp_path, files=[{"path": "a"}])
    assert refused["status"] == "refused" and refused["files"]


@dataclass
class _ContractInput:
    task_id: str = "T1"
    original_text: str = "Scenario 2: missing\nRN9 - missing"


def test_execution_contract_helper_edges() -> None:
    assert ec._as_mapping(_ContractInput())["task_id"] == "T1"
    assert ec._as_mapping(SimpleNamespace(to_dict=lambda: {"x": 1})) == {"x": 1}
    with pytest.raises(ec.ContractCompilationError):
        ec._as_mapping(object())
    assert ec._items(None) == [] and ec._items("x") == ["x"]
    assert ec._text({"description": " x "}, "description") == "x"
    assert ec._text(1, "x") == ""
    assert ec._verification_kinds({"impact_signals": {"frontend": True}, "prototypes": [1]}) == (
        "unit",
        "integration",
        "e2e",
        "visual",
    )

    gates: list[ec.HumanGate] = []
    ec._compile_acceptance_criteria(
        {
            "acceptance_criteria": [
                {"id": "AC1", "title": "one"},
                {"id": "AC1", "title": "two"},
                {"id": "AC1", "title": "one"},
            ]
        },
        gates,
    )
    assert any(gate.id == "contradiction-ac1" for gate in gates)
    missing: list[ec.HumanGate] = []
    assert ec._compile_acceptance_criteria({}, missing) == ()
    assert missing[0].id == "missing-acceptance-criteria"

    gates = []
    ec._compile_requirements(
        [{"id": "RN1", "text": "one"}, {"id": "RN1", "text": "two"}],
        "business_rule",
        "RN",
        gates,
    )
    assert gates

    gates = []
    hypotheses: list[ec.Hypothesis] = []
    ec._semantic_gates(
        "Ordenar data alfabeticamente; linha estrutural unica",
        (ec.Requirement("NFR1", "nfr", "validar", None, "validar"),),
        {"impact_signals": {"backend": {"status": "possible", "text": "maybe"}}},
        gates,
        hypotheses,
    )
    ids = {gate.id for gate in gates}
    assert {
        "decision-date-tie",
        "decision-date-missing-invalid",
        "decision-alphabetical-collation",
        "decision-multiple-structural",
        "nfr-validation-required",
        "impact-backend-undecided",
    } <= ids
    assert hypotheses

    ec._source_coverage_gates("Scenario 2:\nRN9 - rule", (), (), gates)
    assert {"source-coverage-ac2", "source-coverage-rn9"} <= {gate.id for gate in gates}
    ec._input_gates(
        {
            "human_gates": ["Approve?"],
            "uncertainties": [{"id": "U1", "text": "Unknown", "blocking": False}],
        },
        gates,
    )
    ec._missing_field_gates({}, gates)
    assert ec._placeholder_errors({"criteria": "-", "verify": "echo todo"})
