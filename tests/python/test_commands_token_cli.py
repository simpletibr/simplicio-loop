"""CLI-wrapper coverage for `simplicio token ...` (`simplicio/commands/token.py`).

`tests/python/test_token_primitives.py` already exercises the underlying
`simplicio.token_primitives` functions directly, but nothing drove them
through `cli.main(["token", ...])` — so the wrapper's own branching (which
subcommand maps to which primitive, the `--file -` / stdin plumbing via
`read_text_source`, the shared `except (OSError, json.JSONDecodeError,
ValueError)` error path, and the `context-cache get|put|invalidate` dispatch)
had zero direct coverage. Issue #200 asks for configuration/error-handling
coverage on every public command, so this file closes that gap.
"""

from __future__ import annotations

import json

import pytest

from simplicio import cli


def test_log_summary_reads_file_and_emits_json(tmp_path, capsys):
    log_file = tmp_path / "run.log"
    log_file.write_text("line one\nERROR: boom\nline three\n", encoding="utf-8")

    code = cli.main(["token", "log-summary", "--file", str(log_file)])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "simplicio.log-summary/v1"
    assert any("ERROR" in line for line in payload["summary"].splitlines())


def test_log_summary_reads_stdin_by_default(monkeypatch, capsys):
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO("hello from stdin\n"))

    code = cli.main(["token", "log-summary"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert "hello from stdin" in payload["summary"]


def test_log_summary_missing_file_exits_2_with_stderr(tmp_path, capsys):
    # `read_text_source` (shared by every `token` subcommand that reads a
    # `--file`) raises `SystemExit(2)` directly rather than routing through
    # `commands/token.py`'s own `except (OSError, ...)` clause, so this exits
    # the process with code 2 instead of `cli.main` returning it.
    missing = tmp_path / "does-not-exist.log"

    with pytest.raises(SystemExit) as exc:
        cli.main(["token", "log-summary", "--file", str(missing)])

    captured = capsys.readouterr()
    assert exc.value.code == 2
    assert captured.out == ""
    assert "cannot read" in captured.err


def test_diff_review_reports_no_git_repo(tmp_path, capsys):
    # tmp_path is not a git repo, so diff-review should degrade gracefully
    # rather than crash — it must still return a stable JSON payload.
    code = cli.main(["token", "diff-review", "--root", str(tmp_path)])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "simplicio.diff-review/v1"


def test_postconditions_reads_json_checks_from_file(tmp_path, capsys):
    checks_file = tmp_path / "checks.json"
    checks_file.write_text(json.dumps([{"type": "file_exists", "path": "README.md"}]), encoding="utf-8")
    (tmp_path / "README.md").write_text("hi\n", encoding="utf-8")

    code = cli.main(["token", "postconditions", "--file", str(checks_file), "--root", str(tmp_path)])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "simplicio.postconditions/v1"
    assert payload["checks"][0]["passed"] is True


def test_postconditions_invalid_json_exits_2(tmp_path, capsys):
    checks_file = tmp_path / "checks.json"
    checks_file.write_text("{not valid json", encoding="utf-8")

    code = cli.main(["token", "postconditions", "--file", str(checks_file), "--root", str(tmp_path)])

    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert "simplicio-py token postconditions:" in captured.err


def test_retry_builds_payload_from_reason_and_failure_json(capsys):
    code = cli.main(
        [
            "token",
            "retry",
            "--reason",
            "flaky assertion",
            "--failure-json",
            json.dumps({"file": "test_x.py", "line": 12}),
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "simplicio.retry/v1"
    assert payload["reason"] == "flaky assertion"


def test_retry_invalid_failure_json_exits_2(capsys):
    code = cli.main(["token", "retry", "--reason", "x", "--failure-json", "{bad"])

    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert "simplicio-py token retry:" in captured.err


def test_retry_reads_log_from_file_when_given(tmp_path, capsys):
    log_file = tmp_path / "attempt.log"
    log_file.write_text("assertion failed at line 42\n", encoding="utf-8")

    code = cli.main(
        [
            "token",
            "retry",
            "--reason",
            "assertion",
            "--log-file",
            str(log_file),
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert "assertion failed" in payload["log_summary"]["summary"]


def test_model_routing_reads_json_payload(tmp_path, capsys):
    routing_file = tmp_path / "routing.json"
    routing_file.write_text(json.dumps({"task_kind": "edit", "complexity": "low"}), encoding="utf-8")

    code = cli.main(["token", "model-routing", "--file", str(routing_file)])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "simplicio.model-routing/v1"


def test_model_routing_invalid_json_exits_2(tmp_path, capsys):
    routing_file = tmp_path / "routing.json"
    routing_file.write_text("not json at all", encoding="utf-8")

    code = cli.main(["token", "model-routing", "--file", str(routing_file)])

    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert "simplicio-py token model-routing:" in captured.err


def test_context_cache_get_reports_miss_then_put_then_hit(tmp_path, capsys):
    content_file = tmp_path / "content.txt"
    content_file.write_text("some context body", encoding="utf-8")

    code = cli.main(
        [
            "token",
            "context-cache",
            "get",
            "--root",
            str(tmp_path),
            "--key",
            "my-key",
            "--content-file",
            str(content_file),
        ]
    )
    assert code == 0
    miss_payload = json.loads(capsys.readouterr().out)
    assert miss_payload["hit"] is False

    summary_file = tmp_path / "summary.json"
    summary_file.write_text(json.dumps({"headline": "ok"}), encoding="utf-8")
    code = cli.main(
        [
            "token",
            "context-cache",
            "put",
            "--root",
            str(tmp_path),
            "--key",
            "my-key",
            "--content-file",
            str(content_file),
            "--summary-file",
            str(summary_file),
        ]
    )
    assert code == 0
    capsys.readouterr()

    code = cli.main(
        [
            "token",
            "context-cache",
            "get",
            "--root",
            str(tmp_path),
            "--key",
            "my-key",
            "--content-file",
            str(content_file),
        ]
    )
    assert code == 0
    hit_payload = json.loads(capsys.readouterr().out)
    assert hit_payload["hit"] is True
    assert hit_payload["summary"] == {"headline": "ok"}


def test_context_cache_invalidate_clears_entry(tmp_path, capsys):
    content_file = tmp_path / "content.txt"
    content_file.write_text("body", encoding="utf-8")
    summary_file = tmp_path / "summary.json"
    summary_file.write_text(json.dumps({"headline": "ok"}), encoding="utf-8")

    cli.main(
        [
            "token",
            "context-cache",
            "put",
            "--root",
            str(tmp_path),
            "--key",
            "k",
            "--content-file",
            str(content_file),
            "--summary-file",
            str(summary_file),
        ]
    )
    capsys.readouterr()

    code = cli.main(["token", "context-cache", "invalidate", "--root", str(tmp_path), "--key", "k"])
    assert code == 0
    capsys.readouterr()

    code = cli.main(
        [
            "token",
            "context-cache",
            "get",
            "--root",
            str(tmp_path),
            "--key",
            "k",
            "--content-file",
            str(content_file),
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["hit"] is False


def test_context_cache_put_missing_summary_file_exits_2(tmp_path, capsys):
    content_file = tmp_path / "content.txt"
    content_file.write_text("body", encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "token",
                "context-cache",
                "put",
                "--root",
                str(tmp_path),
                "--key",
                "k",
                "--content-file",
                str(content_file),
                "--summary-file",
                str(tmp_path / "missing-summary.json"),
            ]
        )

    captured = capsys.readouterr()
    assert exc.value.code == 2
    assert captured.out == ""
    assert "cannot read" in captured.err
