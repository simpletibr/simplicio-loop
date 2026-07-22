"""Unit, integration, system and regression coverage for issue #265."""

from __future__ import annotations

import json
import urllib.error
from pathlib import Path

import pytest

from scripts import meta_issue_audit
from scripts.meta_issue_audit import REQUIRED_SECTIONS, build_audit, fetch_issues, main, render_markdown


def _issue(number: int, *, state: str = "open", body: str = "") -> dict[str, object]:
    return {
        "number": number,
        "title": f"[P1] Test issue {number}",
        "body": body,
        "state": state,
        "state_reason": "completed" if state == "closed" else None,
        "created_at": f"2026-01-{number:02d}T00:00:00Z",
        "updated_at": f"2026-02-{number:02d}T00:00:00Z",
        "closed_at": None,
        "html_url": f"https://github.com/o/r/issues/{number}",
        "labels": [{"name": "quality"}],
        "milestone": None,
    }


def test_build_audit_orders_and_normalizes_every_issue() -> None:
    audit = build_audit([_issue(2, body="Depends on #1"), _issue(1)], "o/r")

    assert [item["number"] for item in audit["issues"]] == [1, 2]
    assert audit["summary"]["issues_total"] == 2
    assert audit["summary"]["issues_with_all_review_sections"] == 2
    assert set(audit["issues"][0]["review"]) == set(REQUIRED_SECTIONS)
    assert audit["dependency_matrix"] == [{"issue": 2, "depends_on_or_references": [1]}]


def test_audit_fails_closed_for_open_or_under_evidenced_history() -> None:
    audit = build_audit([_issue(1), _issue(2, state="closed", body="implemented")], "o/r")

    assert audit["issues"][0]["closure_decision"] == "NEEDS-IMPLEMENTATION"
    assert audit["issues"][1]["closure_decision"] == "HISTORICAL-EVIDENCE-GAP"


def test_closed_issue_needs_implementation_tests_and_evidence() -> None:
    body = "Implemented in PR #9 / commit abc. pytest and E2E logs plus benchmark receipt attached."
    audit = build_audit([_issue(1, state="closed", body=body)], "o/r")

    assert audit["issues"][0]["closure_decision"] == "CLOSE-READY"
    assert audit["issues"][0]["references"] == [9]


def test_security_and_unmeasured_claim_regression() -> None:
    body = "Coverage is 99%. token sk-abcdefghijklmnopqrstuvwxyz123456."
    issue = build_audit([_issue(1, state="closed", body=body)], "o/r")["issues"][0]

    assert issue["possible_secrets"]
    assert issue["unmeasured_claims"] == ["Coverage is 99%. token sk-abcdefghijklmnopqrstuvwxyz123456."]
    assert issue["closure_decision"] != "CLOSE-READY"


def test_markdown_contains_inventory_and_all_required_sections() -> None:
    report = render_markdown(build_audit([_issue(1)], "o/r"))

    assert "## Inventário" in report
    assert "## Matriz resumida" in report
    for section in REQUIRED_SECTIONS:
        assert f"#### {section}" in report


def test_offline_cli_writes_and_checks_reports(tmp_path: Path) -> None:
    source = tmp_path / "issues.json"
    json_output = tmp_path / "audit.json"
    md_output = tmp_path / "audit.md"
    source.write_text(json.dumps([_issue(1)]), encoding="utf-8")
    args = [
        "--input",
        str(source),
        "--repository",
        "o/r",
        "--json-output",
        str(json_output),
        "--markdown-output",
        str(md_output),
    ]

    assert main(args) == 0
    assert main([*args, "--check"]) == 0
    md_output.write_text("stale", encoding="utf-8")
    assert main([*args, "--check"]) == 1


class _Response:
    def __init__(self, payload: object, link: str = "") -> None:
        self.payload = json.dumps(payload).encode()
        self.headers = {"Link": link}

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self, *_args) -> bytes:
        return self.payload


def test_fetch_issues_retries_paginates_and_excludes_pull_requests(monkeypatch) -> None:
    responses: list[object] = [
        urllib.error.URLError("injected timeout"),
        _Response(
            [_issue(2), {**_issue(9), "pull_request": {}}],
            '<https://api.github.test/page=2>; rel="next", <x>; rel="last"',
        ),
        _Response([_issue(1)]),
    ]

    def fake_urlopen(*_args, **_kwargs):
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(meta_issue_audit.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(meta_issue_audit.time, "sleep", lambda _seconds: None)

    assert [item["number"] for item in fetch_issues("o/r")] == [1, 2]


def test_fetch_issues_rejects_invalid_payload_and_exhausted_retry(monkeypatch) -> None:
    monkeypatch.setattr(
        meta_issue_audit.urllib.request, "urlopen", lambda *_args, **_kwargs: _Response({"bad": True})
    )
    with pytest.raises(ValueError, match="must be a list"):
        fetch_issues("o/r")

    def unavailable(*_args, **_kwargs):
        raise TimeoutError("injected")

    monkeypatch.setattr(meta_issue_audit.urllib.request, "urlopen", unavailable)
    monkeypatch.setattr(meta_issue_audit.time, "sleep", lambda _seconds: None)
    with pytest.raises(TimeoutError, match="injected"):
        fetch_issues("o/r", retries=1)


@pytest.mark.parametrize(
    ("title", "expected_component", "expected_risk"),
    [
        ("security docs", "docs", "high"),
        ("migration integration", "cross-cutting", "medium"),
        ("plain change", "cross-cutting", "low"),
    ],
)
def test_classification_fallbacks(title: str, expected_component: str, expected_risk: str) -> None:
    issue = _issue(1)
    issue["title"] = title
    issue["labels"] = []
    result = build_audit([issue], "o/r")["issues"][0]

    assert result["classification"]["component"] == expected_component
    assert result["classification"]["risk"] == expected_risk
