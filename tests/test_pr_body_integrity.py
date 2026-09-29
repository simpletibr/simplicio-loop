import json
import subprocess

import pytest

from simplicio_loop.delivery_agent import (
    DeliveryAgentError,
    GitHubDeliveryAdapter,
    build_pr_body_integrity,
    verify_pr_body_integrity,
)


BODY = (
    "## Café 😀\r\n"
    "\r\n"
    "Paragraph with [a link](https://example.test).\r\n"
    "\r\n"
    "- first\r\n"
    "- second\r\n"
    "\r\n"
    "| a | b |\r\n"
    "| --- | --- |\r\n"
    "| 1 | 2 |\r\n"
    "\r\n"
    "```python\r\n"
    "print('ok')\r\n"
    "```\r\n"
)

BODY_HTML = (
    "<h2>Café 😀</h2><p>Paragraph with "
    '<a href="https://example.test">a link</a>.</p>'
    "<ul><li>first</li><li>second</li></ul>"
    "<table><tr><th>a</th><th>b</th></tr><tr><td>1</td><td>2</td></tr></table>"
    "<pre><code>print('ok')\n</code></pre>"
)


def test_integrity_contract_normalizes_line_endings_and_checks_rendered_shape():
    expected = build_pr_body_integrity(BODY)
    result = verify_pr_body_integrity(expected, BODY.replace("\r\n", "\n"), BODY_HTML)

    assert expected["schema"] == "simplicio.pr-body-integrity/v1"
    assert expected["markdown"]["heading_count"] == 1
    assert expected["markdown"]["list_item_count"] == 2
    assert result["ok"] is True
    assert result["errors"] == []


def test_integrity_contract_fails_closed_on_raw_or_rendered_drift():
    expected = build_pr_body_integrity(BODY)

    raw_drift = verify_pr_body_integrity(expected, BODY.replace("second", "changed"), BODY_HTML)
    rendered_drift = verify_pr_body_integrity(expected, BODY, "<p>tampered</p>")

    assert raw_drift["ok"] is False
    assert "canonical_body_hash_mismatch" in raw_drift["errors"]
    assert rendered_drift["ok"] is False
    assert "rendered_structure_mismatch" in rendered_drift["errors"]


def test_integrity_contract_rejects_unsafe_text():
    with pytest.raises(DeliveryAgentError) as exc_info:
        build_pr_body_integrity("bad\x00body")
    assert exc_info.value.reason_code == "pr_body_integrity"


class FakeGitHub:
    def __init__(self, *, existing=False):
        self.calls = []
        self.existing = existing
        self.body = "old\n" if existing else ""
        self.body_html = "<p>old</p>" if existing else ""

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        if argv[1:3] == ["pr", "list"]:
            rows = [{"number": 77, "url": "https://example.test/pull/77", "state": "OPEN"}] if self.existing else []
            return subprocess.CompletedProcess(argv, 0, json.dumps(rows), "")
        if argv[1:3] in (["pr", "create"], ["pr", "edit"]):
            body_path = argv[argv.index("--body-file") + 1]
            with open(body_path, encoding="utf-8", newline="") as handle:
                self.body = handle.read()
            self.body_html = BODY_HTML
            stdout = "https://example.test/pull/77\n" if argv[2] == "create" else ""
            return subprocess.CompletedProcess(argv, 0, stdout, "")
        if argv[1:3] == ["pr", "view"]:
            return subprocess.CompletedProcess(
                argv,
                0,
                json.dumps({
                    "number": 77,
                    "url": "https://example.test/pull/77",
                    "state": "OPEN",
                    "body": self.body,
                    "bodyHTML": self.body_html,
                }),
                "",
            )
        raise AssertionError(argv)


def test_adapter_uses_body_file_and_requeries_created_pr():
    runner = FakeGitHub()
    adapter = GitHubDeliveryAdapter(repo="owner/name", runner=runner)

    result = adapter.create_or_update_pr(branch="feat/x", base="main", title="title", body=BODY)

    create_call = next(call for call in runner.calls if call[1:3] == ["pr", "create"])
    assert "--body" not in create_call
    assert "--body-file" in create_call
    assert result["body_integrity"]["ok"] is True
    assert any(call[1:3] == ["pr", "view"] for call in runner.calls)


def test_adapter_repairs_existing_pr_body_before_confirming():
    runner = FakeGitHub(existing=True)
    adapter = GitHubDeliveryAdapter(repo="owner/name", runner=runner)

    result = adapter.create_or_update_pr(branch="feat/x", base="main", title="title", body=BODY)

    assert any(call[1:3] == ["pr", "edit"] for call in runner.calls)
    assert result["body_integrity"]["ok"] is True

