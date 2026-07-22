from __future__ import annotations

import json
import subprocess
import sys
import urllib.error
from pathlib import Path

import pytest

from scripts import verify_default_branch

ROOT = Path(__file__).resolve().parents[2]


def _github_fixture(default: str = "main", missing_sha: str | None = None):
    def fetch(url: str) -> dict:
        if url.endswith("/branches/main"):
            return {"name": "main", "commit": {"sha": None if missing_sha == "main" else "main-sha"}}
        if url.endswith("/branches/master"):
            return {
                "name": "master",
                "commit": {"sha": None if missing_sha == "master" else "master-sha"},
            }
        return {"default_branch": default}

    return fetch


def test_verify_accepts_main_and_records_both_branch_tips() -> None:
    ok, receipt = verify_default_branch.verify("owner/repo", fetch_json=_github_fixture())

    assert ok is True
    assert receipt == {
        "schema": "simplicio.default-branch-evidence/v1",
        "repository": "owner/repo",
        "expected_default": "main",
        "observed_default": "main",
        "compatibility_branch": "master",
        "branch_tips": {"main": "main-sha", "master": "master-sha"},
        "verified": True,
        "reasons": [],
    }


@pytest.mark.parametrize("default", ["master", None, ""])
def test_verify_rejects_any_default_other_than_main(default: str | None) -> None:
    ok, receipt = verify_default_branch.verify("owner/repo", fetch_json=_github_fixture(default))

    assert ok is False
    assert receipt["verified"] is False
    assert receipt["reasons"] == [f"default_branch is {default!r}, expected 'main'"]


def test_verify_rejects_a_branch_without_an_observable_sha() -> None:
    ok, receipt = verify_default_branch.verify("owner/repo", fetch_json=_github_fixture(missing_sha="master"))

    assert ok is False
    assert receipt["reasons"] == ["branch 'master' has no observable commit SHA"]


def test_fetch_json_uses_public_api_headers_and_parses_object(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: dict[str, object] = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self) -> bytes:
            return b'{"default_branch":"main"}'

    def urlopen(request, timeout):
        observed.update(url=request.full_url, user_agent=request.headers["User-agent"], timeout=timeout)
        return Response()

    monkeypatch.setattr(verify_default_branch.urllib.request, "urlopen", urlopen)

    assert verify_default_branch._fetch_json("https://example.test/repo") == {"default_branch": "main"}
    assert observed == {
        "url": "https://example.test/repo",
        "user_agent": "simplicio-default-branch-check",
        "timeout": 15,
    }


def test_fetch_json_rejects_a_non_object_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self) -> bytes:
            return b"[]"

    monkeypatch.setattr(verify_default_branch.urllib.request, "urlopen", lambda request, timeout: Response())

    with pytest.raises(ValueError, match="expected an object"):
        verify_default_branch._fetch_json("https://example.test/repo")


def test_main_prints_a_success_receipt(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    receipt = {"schema": verify_default_branch.SCHEMA, "verified": True}
    monkeypatch.setattr(verify_default_branch, "verify", lambda *args, **kwargs: (True, receipt))

    assert verify_default_branch.main(["--repository", "owner/repo"]) == 0
    assert json.loads(capsys.readouterr().out) == receipt


def test_main_turns_network_failure_into_a_safe_receipt(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    def fail(*args, **kwargs):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(verify_default_branch, "verify", fail)

    assert verify_default_branch.main(["--repository", "owner/repo"]) == 1
    captured = capsys.readouterr()
    receipt = json.loads(captured.err)
    assert receipt["verified"] is False
    assert receipt["repository"] == "owner/repo"
    assert "offline" in receipt["error"]


def test_cli_system_path_reports_the_live_repository_state() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/verify_default_branch.py"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    stream = result.stdout if result.returncode == 0 else result.stderr
    receipt = json.loads(stream)

    assert receipt["repository"] == "wesleysimplicio/simplicio-dev-cli"
    assert receipt["expected_default"] == "main"
    assert receipt["verified"] is (result.returncode == 0)
    if result.returncode == 0:
        assert receipt["observed_default"] == "main"
        assert receipt["branch_tips"]["main"]
        assert receipt["branch_tips"]["master"]
    else:
        assert receipt.get("reasons") or receipt.get("error")
