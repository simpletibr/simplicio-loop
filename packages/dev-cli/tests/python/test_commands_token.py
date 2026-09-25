"""Unit tests for ``simplicio-py token`` subcommand dispatch
(simplicio/commands/token.py), previously covered only for `log-summary`
(34% line coverage) with `diff-review`, `postconditions`, `retry`,
`model-routing`, `context-cache get/put/invalidate`, the unsupported-command
branch, and the error-handling branch all untested.
"""

from __future__ import annotations

import argparse
import json

from simplicio.commands import token as token_cmd


def ns(**kwargs) -> argparse.Namespace:
    return argparse.Namespace(**kwargs)


def test_token_diff_review_dispatch(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    code = token_cmd.run(ns(token_cmd="diff-review", root=str(tmp_path), max_patch_chars=2000))
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert "schema" in payload


def test_token_postconditions_dispatch(tmp_path, capsys):
    checks_file = tmp_path / "checks.json"
    checks_file.write_text(json.dumps([{"kind": "file_exists", "path": "missing.txt"}]), encoding="utf-8")
    code = token_cmd.run(ns(token_cmd="postconditions", file=str(checks_file), root=str(tmp_path)))
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["passed"] is False
    assert len(payload["checks"]) == 1


def test_token_retry_dispatch(tmp_path, capsys):
    log_file = tmp_path / "log.txt"
    log_file.write_text("AssertionError: boom\n", encoding="utf-8")
    code = token_cmd.run(
        ns(
            token_cmd="retry",
            log_file=str(log_file),
            failure_json=json.dumps({"kind": "assertion"}),
            reason="test failed",
            max_log_chars=500,
        )
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["reason"] == "test failed"
    assert payload["failure"] == {"kind": "assertion"}


def test_token_retry_dispatch_without_log_or_failure(capsys):
    code = token_cmd.run(
        ns(token_cmd="retry", log_file=None, failure_json=None, reason="no evidence", max_log_chars=500)
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["failure"] == {}


def test_token_model_routing_dispatch(tmp_path, capsys):
    context_file = tmp_path / "ctx.json"
    context_file.write_text(json.dumps({"risk": "low", "work": "formatting"}), encoding="utf-8")
    code = token_cmd.run(ns(token_cmd="model-routing", file=str(context_file)))
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["profile"] == "mass"


def test_token_context_cache_put_then_get(tmp_path, capsys):
    content_file = tmp_path / "content.txt"
    content_file.write_text("hello world", encoding="utf-8")
    summary_file = tmp_path / "summary.json"
    summary_file.write_text(json.dumps({"note": "ok"}), encoding="utf-8")

    code = token_cmd.run(
        ns(
            token_cmd="context-cache",
            cache_cmd="put",
            root=str(tmp_path),
            key="k1",
            content_file=str(content_file),
            summary_file=str(summary_file),
        )
    )
    assert code == 0
    put_payload = json.loads(capsys.readouterr().out)
    assert put_payload["stored"] is True

    code = token_cmd.run(
        ns(
            token_cmd="context-cache",
            cache_cmd="get",
            root=str(tmp_path),
            key="k1",
            content_file=str(content_file),
        )
    )
    assert code == 0
    get_payload = json.loads(capsys.readouterr().out)
    assert get_payload["hit"] is True
    assert get_payload["summary"] == {"note": "ok"}


def test_token_context_cache_invalidate(tmp_path, capsys):
    content_file = tmp_path / "content.txt"
    content_file.write_text("x", encoding="utf-8")
    code = token_cmd.run(
        ns(
            token_cmd="context-cache",
            cache_cmd="invalidate",
            root=str(tmp_path),
            key="k1",
            content_file=None,
        )
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["removed"] == 0


def test_token_unsupported_command(capsys):
    code = token_cmd.run(ns(token_cmd="bogus"))
    assert code == 2
    assert "unsupported command" in capsys.readouterr().err


def test_token_command_handles_bad_json_gracefully(tmp_path, capsys):
    bad_file = tmp_path / "bad.json"
    bad_file.write_text("not json", encoding="utf-8")
    code = token_cmd.run(ns(token_cmd="model-routing", file=str(bad_file)))
    assert code == 2
    assert "token model-routing" in capsys.readouterr().err
