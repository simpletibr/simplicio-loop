"""Unit tests for `simplicio_loop.intake` (issue #1312, generic task intake).

TDD: these are written before `simplicio_loop/intake.py` exists / is complete.
One fixture per tracker export shape, plus CSV, Markdown, --map, dependency
extraction, and malformed-input handling.
"""
from __future__ import annotations

import json
import textwrap

import pytest

from simplicio_loop import intake


REQUIRED_KEYS = {"id", "title", "body", "labels", "depends_on", "source", "url"}


def _assert_shape(item):
    assert REQUIRED_KEYS.issubset(item.keys())
    assert isinstance(item["labels"], list)
    assert isinstance(item["depends_on"], list)


# ---------------------------------------------------------------------------
# JSON container shapes
# ---------------------------------------------------------------------------

def test_json_array_root():
    text = json.dumps([{"number": 1, "title": "A", "body": "", "labels": [], "html_url": "u"}])
    items = intake.normalize(text, "json")
    assert len(items) == 1
    _assert_shape(items[0])


@pytest.mark.parametrize("wrapper_key", ["items", "issues", "data", "value", "nodes"])
def test_json_object_wrappers(wrapper_key):
    text = json.dumps({wrapper_key: [{"number": 1, "title": "A"}]})
    items = intake.normalize(text, "json")
    assert len(items) == 1
    _assert_shape(items[0])


def test_json_malformed_raises_typed_error():
    with pytest.raises(intake.IntakeError) as excinfo:
        intake.normalize("{not json", "json")
    assert excinfo.value.reason_code


def test_json_unrecognized_shape_raises_typed_error():
    with pytest.raises(intake.IntakeError) as excinfo:
        intake.normalize(json.dumps({"foo": "bar"}), "json")
    assert excinfo.value.reason_code == "unrecognized_json_shape"


# ---------------------------------------------------------------------------
# Tracker auto-detection fixtures
# ---------------------------------------------------------------------------

def test_github_fixture():
    text = json.dumps([
        {
            "number": 42,
            "title": "Fix the thing",
            "body": "Something is broken.\nDepends on #7",
            "labels": [{"name": "bug"}, {"name": "P1"}],
            "html_url": "https://github.com/o/r/issues/42",
        },
        {
            "number": 7,
            "title": "Root cause",
            "body": "Investigate root cause.",
            "labels": [],
            "html_url": "https://github.com/o/r/issues/7",
        },
    ])
    items = intake.normalize(text, "json", source_label="github")
    assert len(items) == 2
    first = items[0]
    _assert_shape(first)
    assert first["id"] == "42"
    assert first["title"] == "Fix the thing"
    assert first["labels"] == ["bug", "P1"]
    assert first["url"] == "https://github.com/o/r/issues/42"
    assert "7" in first["depends_on"]


def test_jira_fixture_issuelinks_blocked_by():
    text = json.dumps([
        {
            "key": "ABC-10",
            "fields": {
                "summary": "Ship the feature",
                "description": "Full description here.",
                "labels": ["backend", "urgent"],
                "issuelinks": [
                    {
                        "type": {"name": "Blocks", "inward": "is blocked by", "outward": "blocks"},
                        "inwardIssue": {"key": "ABC-3"},
                    }
                ],
            },
        },
        {
            "key": "ABC-3",
            "fields": {"summary": "Prerequisite work", "description": "", "labels": []},
        },
    ])
    items = intake.normalize(text, "json", source_label="jira")
    first = items[0]
    _assert_shape(first)
    assert first["id"] == "ABC-10"
    assert first["title"] == "Ship the feature"
    assert first["labels"] == ["backend", "urgent"]
    assert "ABC-3" in first["depends_on"]


def test_linear_fixture():
    text = json.dumps([
        {
            "identifier": "ENG-12",
            "title": "Build the widget",
            "description": "Widget description.",
            "labels": {"nodes": [{"name": "feature"}]},
            "url": "https://linear.app/team/issue/ENG-12",
            "relations": {"nodes": [{"type": "blocked_by", "relatedIssue": {"identifier": "ENG-9"}}]},
        },
        {
            "identifier": "ENG-9",
            "title": "Dependency",
            "description": "",
            "labels": {"nodes": []},
            "url": "https://linear.app/team/issue/ENG-9",
        },
    ])
    items = intake.normalize(text, "json", source_label="linear")
    first = items[0]
    _assert_shape(first)
    assert first["id"] == "ENG-12"
    assert first["labels"] == ["feature"]
    assert "ENG-9" in first["depends_on"]


def test_clickup_fixture():
    text = json.dumps([
        {
            "id": "861u9j63p",
            "name": "Ship dashboard",
            "description": "Dashboard rollout.",
            "tags": [{"name": "design"}],
            "url": "https://app.clickup.com/t/861u9j63p",
            "dependencies": [{"depends_on": "861u9j111"}],
        },
        {
            "id": "861u9j111",
            "name": "Design assets",
            "description": "",
            "tags": [],
            "url": "https://app.clickup.com/t/861u9j111",
        },
    ])
    items = intake.normalize(text, "json", source_label="clickup")
    first = items[0]
    _assert_shape(first)
    assert first["id"] == "861u9j63p"
    assert first["labels"] == ["design"]
    assert "861u9j111" in first["depends_on"]


def test_gitlab_fixture():
    text = json.dumps([
        {
            "iid": 5,
            "title": "Refactor module",
            "description": "Needs a refactor.",
            "labels": ["tech-debt"],
            "web_url": "https://gitlab.com/o/r/-/issues/5",
        }
    ])
    items = intake.normalize(text, "json", source_label="gitlab")
    first = items[0]
    _assert_shape(first)
    assert first["id"] == "5"
    assert first["labels"] == ["tech-debt"]
    assert first["url"] == "https://gitlab.com/o/r/-/issues/5"


def test_azure_devops_fixture():
    text = json.dumps([
        {
            "id": 100,
            "url": "https://dev.azure.com/o/p/_workitems/edit/100",
            "fields": {
                "System.Title": "Do the thing",
                "System.Description": "Body text.",
                "System.Tags": "one; two",
            },
        }
    ])
    items = intake.normalize(text, "json", source_label="azure")
    first = items[0]
    _assert_shape(first)
    assert first["id"] == "100"
    assert first["title"] == "Do the thing"
    assert first["labels"] == ["one", "two"]


# ---------------------------------------------------------------------------
# --map override
# ---------------------------------------------------------------------------

def test_map_override_dotted_path():
    text = json.dumps([{"custom_id": "X-1", "headline": "Custom title", "notes": "the body"}])
    field_map = intake.parse_field_map(["id=custom_id", "title=headline", "body=notes"])
    items = intake.normalize(text, "json", field_map=field_map)
    first = items[0]
    _assert_shape(first)
    assert first["id"] == "X-1"
    assert first["title"] == "Custom title"
    assert first["body"] == "the body"


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------

def test_csv_basic():
    text = textwrap.dedent(
        """\
        id,title,body,labels,depends_on
        1,First task,do a thing,bug;p1,
        2,Second task,do another thing,,1
        """
    )
    items = intake.normalize(text, "csv")
    assert len(items) == 2
    _assert_shape(items[0])
    assert items[0]["labels"] == ["bug", "p1"]
    assert items[1]["depends_on"] == ["1"]


def test_csv_empty_raises_typed_error():
    with pytest.raises(intake.IntakeError) as excinfo:
        intake.normalize("", "csv")
    assert excinfo.value.reason_code


# ---------------------------------------------------------------------------
# Markdown (existing tasks.md grammar passes through)
# ---------------------------------------------------------------------------

MARKDOWN_SAMPLE = """System: calc
Feature: TASK-1: add mul(a, b)
Type: Feature

1. Acceptance Criteria
Scenario 1: mul multiplies two numbers — returns 12 for mul(3, 4)

6. Dependencies
TASK-0
"""


def test_markdown_passthrough():
    items = intake.normalize(MARKDOWN_SAMPLE, "markdown")
    assert len(items) == 1
    first = items[0]
    _assert_shape(first)
    assert any("task-0" in dep.lower() for dep in first["depends_on"])
    assert first["source"] == "markdown"


def test_markdown_no_tasks_raises_typed_error():
    with pytest.raises(intake.IntakeError) as excinfo:
        intake.normalize("just some prose, no grammar here", "markdown")
    assert excinfo.value.reason_code


# ---------------------------------------------------------------------------
# render_tasks_markdown / build_backlog_items
# ---------------------------------------------------------------------------

def test_render_tasks_markdown_compiles_and_wires_dependencies():
    from simplicio_loop import task_contract

    items = intake.normalize(
        json.dumps(
            [
                {"number": 1, "title": "Base work", "body": "Do base work.", "labels": [], "html_url": "u1"},
                {
                    "number": 2,
                    "title": "Depends on base",
                    "body": "Needs base.\nDepends on #1",
                    "labels": [],
                    "html_url": "u2",
                },
            ]
        ),
        "json",
        source_label="github",
    )
    rendered = intake.render_tasks_markdown(items)
    compiled = task_contract.compile_many(rendered, source_path="tasks.md")
    assert compiled["task_count"] == 2
    for task in compiled["tasks"]:
        verdict = task_contract.validate_contract(task)
        assert verdict["errors"] == []
    second_deps = compiled["tasks"][1]["dependencies"]["items"]
    assert any("task 1" in dep.lower() for dep in second_deps)


def test_build_backlog_items_shape():
    items = intake.normalize(
        json.dumps([{"number": 1, "title": "A", "body": "b", "labels": [], "html_url": "u"}]),
        "json",
        source_label="github",
    )
    backlog_items = intake.build_backlog_items(items, "tasks.md")
    assert backlog_items
    entry = backlog_items[0]
    assert entry["id"]
    assert entry["goal"]
    assert isinstance(entry["acs"], list) and entry["acs"]
    assert entry["plan_files"] == ["tasks.md"]
