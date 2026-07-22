import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("meta_issue_audit", ROOT / "scripts" / "meta_issue_audit.py")
audit = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(audit)


def issue(number: int, *, state: str = "open", body: str = "") -> dict:
    return {
        "number": number,
        "title": f"Issue {number}",
        "state": state,
        "created_at": f"2026-01-{number:02d}T00:00:00Z",
        "updated_at": f"2026-02-{number:02d}T00:00:00Z",
        "closed_at": None if state == "open" else f"2026-03-{number:02d}T00:00:00Z",
        "html_url": f"https://github.com/example/repo/issues/{number}",
        "body": body,
        "labels": [{"name": "P0"}],
        "user": {"login": "author"},
    }


class MetaIssueAuditUnitTest(unittest.TestCase):
    def test_inventory_is_chronological_and_has_complete_review_contract(self) -> None:
        payload = audit.build_audit([issue(2), issue(1, state="closed")], repository="example/repo")
        self.assertEqual([item["number"] for item in payload["issues"]], [1, 2])
        self.assertEqual(payload["summary"], {"total": 2, "open": 1, "closed": 1})
        self.assertEqual(payload["schema"], "simplicio.meta-issue-audit/v1")
        for item in payload["issues"]:
            self.assertEqual(list(item["review"]), audit.REQUIRED_SECTIONS)
            self.assertEqual(len(item["test_flow"]), 9)
            self.assertTrue(item["evidence"]["required"])
            self.assertIn(item["closure_decision"], {"KEEP_OPEN", "REVIEW_CLOSED"})

    def test_refs_dependencies_and_sensitive_values_are_handled(self) -> None:
        body = "Depends on #1 and https://github.com/acme/runtime/issues/9\nTOKEN=ghp_abcdefghijklmnopqrstuvwxyz123456"
        item = audit.build_audit([issue(2, body=body)], repository="example/repo")["issues"][0]
        self.assertEqual(item["dependencies"]["local_issues"], [1])
        self.assertEqual(item["dependencies"]["cross_repository"], ["https://github.com/acme/runtime/issues/9"])
        self.assertNotIn("ghp_", json.dumps(item))
        self.assertTrue(item["security"]["redactions_applied"])

    def test_pull_requests_are_excluded_and_duplicates_rejected(self) -> None:
        pull = issue(3)
        pull["pull_request"] = {"url": "https://api.github.com/pulls/3"}
        payload = audit.build_audit([issue(1), pull], repository="example/repo")
        self.assertEqual(payload["summary"]["total"], 1)
        with self.assertRaisesRegex(ValueError, "duplicate issue number"):
            audit.build_audit([issue(1), issue(1)], repository="example/repo")

    def test_fetch_reports_timeout_with_page_context(self) -> None:
        with mock.patch.object(audit.urllib.request, "urlopen", side_effect=TimeoutError("timed out")):
            with self.assertRaisesRegex(RuntimeError, "page 1.*timed out"):
                audit.fetch_issues("example/repo", timeout=0.01)

    def test_fetch_paginates_and_rejects_non_array(self) -> None:
        class Response(io.StringIO):
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                self.close()

        pages = [Response(json.dumps([issue(index) for index in range(1, 101)])), Response(json.dumps([issue(101)]))]
        with mock.patch.object(audit.urllib.request, "urlopen", side_effect=pages) as opened:
            self.assertEqual(len(audit.fetch_issues("example/repo")), 101)
            self.assertEqual(opened.call_count, 2)
        with mock.patch.object(audit.urllib.request, "urlopen", return_value=Response("{}")):
            with self.assertRaisesRegex(RuntimeError, "non-array"):
                audit.fetch_issues("example/repo")

    def test_existing_sections_and_same_repository_refs_are_preserved(self) -> None:
        body = "# Context\nObserved problem.\n# Objective\nMeasured goal.\n# Out of scope\nNo UI.\nSee https://github.com/example/repo/issues/7"
        item = audit.build_audit([issue(2, body=body)], repository="example/repo")["issues"][0]
        self.assertEqual(item["review"]["context_and_problem"], "Observed problem.")
        self.assertEqual(item["review"]["objective"], "Measured goal.")
        self.assertEqual(item["review"]["out_of_scope"], "No UI.\nSee https://github.com/example/repo/issues/7")
        self.assertEqual(item["dependencies"]["local_issues"], [7])


class MetaIssueAuditIntegrationTest(unittest.TestCase):
    def test_committed_system_inventory_covers_every_accessible_issue(self) -> None:
        payload = json.loads((ROOT / "docs/evidence/issue-328-meta-audit.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["summary"], {"total": 178, "open": 3, "closed": 175})
        self.assertEqual(payload["issues"][0]["number"], 5)
        self.assertEqual(payload["issues"][-1]["number"], 328)
        self.assertEqual(len({item["number"] for item in payload["issues"]}), 178)
        self.assertTrue(all(list(item["review"]) == audit.REQUIRED_SECTIONS for item in payload["issues"]))

    def test_cli_reads_export_writes_json_and_check_replays(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "issues.json"
            output = Path(tmp) / "audit.json"
            source.write_text(json.dumps([issue(1), issue(2, state="closed")]), encoding="utf-8")
            command = [
                sys.executable,
                "scripts/meta_issue_audit.py",
                "--input",
                str(source),
                "--repository",
                "example/repo",
                "--output",
                str(output),
            ]
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(output.read_text())["summary"]["total"], 2)
            check = subprocess.run(command + ["--check"], cwd=ROOT, capture_output=True, text=True, check=False)
            self.assertEqual(check.returncode, 0, check.stderr)
            source.write_text(json.dumps([issue(1)]), encoding="utf-8")
            stale = subprocess.run(command + ["--check"], cwd=ROOT, capture_output=True, text=True, check=False)
            self.assertEqual(stale.returncode, 1)
            self.assertIn("out of date", stale.stderr)

    def test_invalid_export_fails_without_overwriting_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "issues.json"
            output = Path(tmp) / "audit.json"
            source.write_text("{}", encoding="utf-8")
            output.write_text("sentinel", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, "scripts/meta_issue_audit.py", "--input", str(source), "--output", str(output)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 2)
            self.assertEqual(output.read_text(), "sentinel")

    def test_main_directly_covers_write_check_and_fetch_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "issues.json"
            output = Path(tmp) / "audit.json"
            source.write_text(json.dumps([issue(1)]), encoding="utf-8")
            args = ["--input", str(source), "--repository", "example/repo", "--output", str(output)]
            self.assertEqual(audit.main(args), 0)
            self.assertEqual(audit.main(args + ["--check"]), 0)
            source.write_text("[]", encoding="utf-8")
            self.assertEqual(audit.main(args + ["--check"]), 1)
            with mock.patch.object(audit, "fetch_issues", return_value=[issue(1)]) as fetch:
                self.assertEqual(
                    audit.main(["--fetch", "--repository", "example/repo", "--output", str(output), "--timeout", "0.5"]),
                    0,
                )
                fetch.assert_called_once_with("example/repo", timeout=0.5)


if __name__ == "__main__":
    unittest.main()
