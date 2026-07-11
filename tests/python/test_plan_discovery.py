"""Real integration tests for issue #117 autonomous orientation.

These exercise ``simplicio.plan_discovery.build_plan_preview`` end-to-end with
a fake mapper ``ask`` backend, proving the planner discovers layers and flows
from evidence instead of guessing a single backend target.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from simplicio.commands import intake as intake_cmd
from simplicio.execution_contract import compile_execution_contracts
from simplicio.plan_discovery import PlanDiscoveryError, build_plan_preview
from simplicio.task_spec import parse_task_document


def _write_mapper_artifacts(root: Path, *, files: list[dict], precedents: list[dict]) -> None:
    simplicio_dir = root / ".simplicio"
    simplicio_dir.mkdir(parents=True, exist_ok=True)
    (simplicio_dir / "project-map.json").write_text(
        json.dumps(
            {
                "schema": "simplicio.project-map/v1",
                "generated_at": "2026-07-11T00:00:00Z",
                "files": files,
                "precedents": precedents,
            }
        ),
        encoding="utf-8",
    )
    (simplicio_dir / "precedent-index.json").write_text(
        json.dumps({"schema": "simplicio.precedent-index/v1", "items": precedents}),
        encoding="utf-8",
    )


def _ns(**kwargs: object) -> argparse.Namespace:
    return argparse.Namespace(**kwargs)


def test_frontend_only_plan_classifies_ui_layer_without_backend_flag(tmp_path, monkeypatch) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "order.tsx").write_text("export const Order = () => null;", encoding="utf-8")
    _write_mapper_artifacts(
        tmp_path,
        files=[
            {
                "path": "src/order.tsx",
                "language": "tsx",
                "file_hash": "a" * 64,
                "size_bytes": 30,
                "git_status": "clean",
                "roles": ["entry_point"],
                "exports": ["Order"],
                "importance": 0.9,
            }
        ],
        precedents=[{"id": "prec-1", "path": "src/order.tsx", "line": 1, "summary": "order list"}],
    )

    def fake_map_ask(_root, verb, arg=""):
        if arg != "src/order.tsx":
            return []
        return {
            "impact": [{"why": "screen renders the ordered list"}],
            "tests-for": [{"test_path": "src/order.test.tsx"}],
            "callers": [],
            "flows": [],
            "rules": [{"rule": "preserve backend order"}],
        }[verb]

    monkeypatch.setattr("simplicio.plan_discovery.map_ask", fake_map_ask)
    monkeypatch.setattr("simplicio.mapper.map_ask", fake_map_ask)

    text = """System: APP
Feature: Order list
Type: Enhancement

AS A user
I WANT to see ordered rows
SO THAT I can read them

Acceptance Criteria
Scenario 1: ordered
  Given rows
  When the screen renders
  Then they appear ordered [RN01]

Business Rules
RN01 - keep backend order

Impact Signals
Frontend: yes
Backend: no
"""
    doc = parse_task_document(text)
    contracts = compile_execution_contracts(doc)
    preview = build_plan_preview(tmp_path, doc.tasks[0], contracts[0])

    assert preview["status"] == "planned"
    assert preview["execution_plan"]["slices"][0]["layer"] == "ui"
    assert preview["execution_plan"]["slices"][0]["targets"] == ["src/order.tsx"]
    assert preview["execution_plan"]["slices"][0]["acceptance_criteria"] == ["AC1"]


def test_full_stack_plan_links_ui_state_and_api_via_measured_flow(tmp_path, monkeypatch) -> None:
    for path in ("src/ui.tsx", "src/state/orderStore.ts", "src/api/order.py"):
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text("pass", encoding="utf-8")
    _write_mapper_artifacts(
        tmp_path,
        files=[
            {
                "path": "src/ui.tsx",
                "language": "tsx",
                "file_hash": "1" * 64,
                "git_status": "clean",
                "roles": ["entry_point"],
                "exports": ["UI"],
                "importance": 0.95,
            },
            {
                "path": "src/state/orderStore.ts",
                "language": "ts",
                "file_hash": "2" * 64,
                "git_status": "clean",
                "roles": [],
                "exports": ["useOrder"],
                "importance": 0.9,
            },
            {
                "path": "src/api/order.py",
                "language": "py",
                "file_hash": "3" * 64,
                "git_status": "clean",
                "roles": [],
                "exports": ["order"],
                "importance": 0.9,
            },
        ],
        precedents=[{"id": "prec-1", "path": "src/api/order.py", "line": 1, "summary": "api order"}],
    )

    def fake_map_ask(_root, verb, arg=""):
        order = ["src/ui.tsx", "src/state/orderStore.ts", "src/api/order.py"]
        if arg not in order:
            return []
        if verb == "flows":
            return [
                {"name": "modeling-ordering", "targets": order, "why": "UI consumes state which calls API order"}
            ]
        if verb == "tests-for":
            return [{"test_path": f"tests/test_{arg.split('/')[-1].replace('.', '_')}.py"}]
        if verb == "callers":
            return [{"caller": "src/api/router.py"}] if arg == "src/api/order.py" else []
        if verb == "impact":
            return [{"why": f"change lands in {arg}"}]
        if verb == "rules":
            return [{"rule": "order ascending"}]
        return []

    monkeypatch.setattr("simplicio.plan_discovery.map_ask", fake_map_ask)
    monkeypatch.setattr("simplicio.mapper.map_ask", fake_map_ask)

    text = """System: PLANES
Feature: Ordering
Type: Enhancement

AS A analyst
I WANT ordered lines
SO THAT I read them

Acceptance Criteria
Scenario 1: ordered
  Given lines
  When shown
  Then ordered [RN01]

Business Rules
RN01 - ascending

Impact Signals
Frontend: yes
Backend: yes
"""
    doc = parse_task_document(text)
    contracts = compile_execution_contracts(doc)
    preview = build_plan_preview(tmp_path, doc.tasks[0], contracts[0])

    assert preview["status"] == "planned"
    plan = preview["execution_plan"]
    layers = {slice_["targets"][0]: slice_["layer"] for slice_ in plan["slices"]}
    assert layers["src/ui.tsx"] == "ui"
    assert layers["src/state/orderStore.ts"] == "state"
    assert layers["src/api/order.py"] == "api"
    assert plan["flows"]
    flow_targets = set().union(*(set(f["targets"]) for f in plan["flows"]))
    assert {"src/ui.tsx", "src/api/order.py"}.issubset(flow_targets)


def test_frontend_possible_without_measured_target_fails_closed(tmp_path, monkeypatch) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "api.py").write_text("def order(): pass", encoding="utf-8")
    _write_mapper_artifacts(
        tmp_path,
        files=[
            {
                "path": "src/api.py",
                "language": "py",
                "file_hash": "1" * 64,
                "git_status": "clean",
                "roles": ["entry_point"],
                "exports": ["order"],
                "importance": 0.9,
            }
        ],
        precedents=[],
    )

    def fake_map_ask(_root, verb, arg=""):
        if arg != "src/api.py":
            return []
        return {
            "impact": [{"why": "api orders"}],
            "tests-for": [{"test_path": "tests/test_api.py"}],
            "callers": [],
            "flows": [],
            "rules": [{"rule": "ascending"}],
        }[verb]

    monkeypatch.setattr("simplicio.plan_discovery.map_ask", fake_map_ask)
    monkeypatch.setattr("simplicio.mapper.map_ask", fake_map_ask)

    text = """System: APP
Feature: Ordering
Type: Enhancement

AS A user
I WANT ordered output
SO THAT I read it

Acceptance Criteria
Scenario 1: ordered
  Given data
  When returned
  Then ordered [RN01]

Business Rules
RN01 - ascending

Impact Signals
Frontend: possible
Backend: yes
"""
    doc = parse_task_document(text)
    contracts = compile_execution_contracts(doc)
    preview = build_plan_preview(tmp_path, doc.tasks[0], contracts[0])

    assert preview["status"] == "blocked"
    assert any("frontend" in item.lower() for item in preview["blockers"])


def test_intake_plan_only_emits_plan_hash_and_pack_hash(tmp_path, monkeypatch, capsys) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("def greet(): pass", encoding="utf-8")
    _write_mapper_artifacts(
        tmp_path,
        files=[
            {
                "path": "src/app.py",
                "language": "py",
                "file_hash": "0" * 64,
                "git_status": "clean",
                "roles": ["entry_point"],
                "exports": ["greet"],
                "importance": 0.95,
            }
        ],
        precedents=[{"id": "prec-1", "path": "src/app.py", "line": 1, "summary": "greet helper"}],
    )

    def fake_map_ask(_root, verb, arg=""):
        if arg != "src/app.py":
            return []
        return {
            "impact": [{"caller": "src/app.py", "why": "entry point"}],
            "tests-for": [{"test_path": "tests/test_app.py"}],
            "callers": [],
            "flows": [],
            "rules": [{"rule": "keep local"}],
        }[verb]

    monkeypatch.setattr("simplicio.plan_discovery.map_ask", fake_map_ask)
    monkeypatch.setattr("simplicio.mapper.map_ask", fake_map_ask)

    code = intake_cmd.run(
        _ns(
            text="""System: APP
Feature: Add farewell helper
Type: Enhancement
AS A maintainer
I WANT to add a farewell helper
SO THAT greetings live together

Acceptance Criteria
Scenario 1: helper exists
  Given the greetings module
  When I request a farewell
  Then a farewell helper is returned [RN01]

Business Rules
RN01 - Keep helpers together.

Impact Signals
Backend: yes
""",
            file=None,
            stdin=False,
            source_url=None,
            validate_only=False,
            contract=False,
            execution_mode=False,
            plan_only=True,
            json=True,
            root=str(tmp_path),
        )
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "planned"
    plan = payload["execution_plan"]
    assert "plan_hash" in plan
    assert "pack_hash" in plan
    assert plan["slices"][0]["targets"] == ["src/app.py"]


def test_missing_project_map_blocks_with_recovery_action(tmp_path) -> None:
    doc = parse_task_document(
        """System: APP
Feature: Nothing
Type: Enhancement

AS A user
I WANT nothing
SO THAT ok

Acceptance Criteria
Scenario 1: ok
  Given x
  When y
  Then z [RN01]

Business Rules
RN01 - ok

Impact Signals
Backend: yes
"""
    )
    contracts = compile_execution_contracts(doc)
    with pytest.raises(PlanDiscoveryError, match="project-map"):
        build_plan_preview(tmp_path, doc.tasks[0], contracts[0])
