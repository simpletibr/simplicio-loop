from __future__ import annotations

import json
import subprocess
import sys

from simplicio.token_primitives import (
    ContextCache,
    build_retry_payload,
    evaluate_postconditions,
    git_diff_review,
    model_routing_decision,
    summarize_log,
)


def test_log_summary_keeps_errors_and_compacts_repetitive_output():
    log = "\n".join([f"debug line {i}" for i in range(200)])
    log += "\nERROR: build failed because app.py:7 is invalid\n"
    log += "\n".join([f"trace line {i}" for i in range(200)])

    result = summarize_log(log, max_chars=700)

    assert result["schema"] == "simplicio.log-summary/v1"
    assert result["original_chars"] > result["summary_chars"]
    assert result["summary_chars"] <= 700
    assert "ERROR: build failed" in result["summary"]
    assert "debug line 20" not in result["summary"]


def test_context_cache_hits_and_misses_by_content_hash(tmp_path):
    cache = ContextCache(tmp_path)

    written = cache.put("mapper", "context v1", {"files": 3})
    hit = cache.get("mapper", "context v1")
    miss = cache.get("mapper", "context v2")

    assert written["schema"] == "simplicio.context-cache/v1"
    assert hit["hit"] is True
    assert hit["summary"] == {"files": 3}
    assert miss["hit"] is False
    assert miss["reason"] == "hash_mismatch"
    assert not list(tmp_path.glob("*.tmp"))


def test_postconditions_evaluate_files_text_and_commands(tmp_path):
    (tmp_path / "app.py").write_text("TOKEN = 'ok'\n", encoding="utf-8")

    result = evaluate_postconditions(
        [
            {"type": "file_exists", "path": "app.py"},
            {"type": "contains", "path": "app.py", "text": "TOKEN"},
            {"type": "not_contains", "path": "app.py", "text": "SECRET"},
            {"type": "command", "cmd": [sys.executable, "-c", "raise SystemExit(0)"]},
        ],
        root=tmp_path,
    )

    assert result["schema"] == "simplicio.postconditions/v1"
    assert result["passed"] is True
    assert [row["passed"] for row in result["checks"]] == [True, True, True, True]


def test_retry_payload_uses_compact_failure_evidence():
    payload = build_retry_payload(
        reason="validation_failed",
        failure={"cmd": "pytest", "returncode": 1},
        log="line\n" * 500,
        max_log_chars=300,
    )

    assert payload["schema"] == "simplicio.retry/v1"
    assert payload["reason"] == "validation_failed"
    assert payload["failure"]["returncode"] == 1
    assert payload["log_summary"]["summary_chars"] <= 300
    assert "line\n" * 100 not in json.dumps(payload)


def test_model_routing_policy_selects_cheapest_sufficient_profile():
    mass = model_routing_decision(
        {
            "risk": "low",
            "work": "repetitive",
            "operation": "formatting",
            "changed_files": 8,
        }
    )
    deep = model_routing_decision(
        {
            "risk": "high",
            "work": "architecture",
            "ambiguous": True,
        }
    )

    assert mass["schema"] == "simplicio.model-routing/v1"
    assert mass["profile"] == "mass"
    assert mass["allow_delegation"] is False
    assert deep["profile"] == "deep"


def test_git_diff_review_returns_compact_machine_readable_evidence(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=tmp_path,
        check=True,
    )
    (tmp_path / "app.py").write_text("old\n", encoding="utf-8")
    subprocess.run(["git", "add", "app.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "seed"], cwd=tmp_path, check=True)
    (tmp_path / "app.py").write_text("new\n", encoding="utf-8")

    result = git_diff_review(tmp_path, max_patch_chars=500)

    assert result["schema"] == "simplicio.diff-review/v1"
    assert result["files_changed"] == ["app.py"]
    assert result["stats"][0]["path"] == "app.py"
    assert "-old" in result["patch"]
    assert "+new" in result["patch"]
