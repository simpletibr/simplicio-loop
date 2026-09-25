from __future__ import annotations

import json

import pytest

from simplicio_loop import cli


class _ReadyFast:
    last_config = None

    def __init__(self, root, *, config, **_kwargs):
        self.root = root
        self.config = config
        type(self).last_config = config

    def prepare(self, task):
        return {"status": "READY", "generation": "g1", "context_hash": "ctx",
                "task": task,
                "loop_receipt": {"stage": "prepare", "receipt_hash": "sha256:ready"}}


def test_orient_prefers_fast_and_emits_bounded_receipt(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "FastLoopIntegration", _ReadyFast)
    assert cli.orient(str(tmp_path), "change app", "on", 1234, verbose=True) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "simplicio.loop-orient/v1"
    assert payload["status"] == "READY"
    assert payload["provider"] == "simplicio-fast"
    assert payload["local_llm"] is False
    assert payload["orient_receipt"] == payload["fast"]["loop_receipt"]
    assert payload["llm_orientation"]["schema"] == "simplicio.llm-max-speed-orientation/v1"
    assert payload["llm_orientation"]["context_route"]["bounded"] is True
    assert payload["llm_orientation"]["mutation_boundary"]["authorized"] is False
    assert payload["receipt"]["schema"] == "simplicio.loop-orient-receipt/v1"
    assert payload["receipt"]["provenance"]["generation"] == "g1"
    assert payload["receipt"]["provenance"]["context_hash"] == "ctx"
    assert payload["receipt"]["provenance"]["provider_payload_hash"].startswith("sha256:")
    expected_receipt = dict(payload["receipt"])
    receipt_hash = expected_receipt.pop("receipt_hash")
    assert receipt_hash == cli._orient_hash(expected_receipt)
    assert _ReadyFast.last_config.mode == "required"
    assert _ReadyFast.last_config.max_bytes == 1234
    assert _ReadyFast.last_config.engine == "auto"


def test_orient_json_carries_a_compact_command_card(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "FastLoopIntegration", _ReadyFast)
    assert cli.orient(str(tmp_path), "change app", "on", 1234, verbose=True) == 0
    payload = json.loads(capsys.readouterr().out)
    card = payload["commands"]
    assert card["schema"] == "simplicio.loop-command-card/v1"
    repo = str(tmp_path)
    assert card["prepare"] == f"simplicio-loop prepare --task tasks.md --repo {repo}"
    assert card["wave"] == f"simplicio-loop wave <run_id> --repo {repo}"
    assert card["verify"] == f"simplicio-loop verify <run_id> --repo {repo}"
    assert card["tick"] == f"simplicio-loop tick <run_id> --repo {repo} --task-index <N>"
    assert card["edit_plan_path"] == ".simplicio/loop-runs/<run_id>/edit-plan-<N>.json"
    assert card["edit_plan_format"] == {
        "operations": [{"path": "<repo-relative>", "find": "<exact text>", "replace": "<new text>"}]
    }
    assert "exactly once" in card["edit_plan_rule"]
    assert card["task_file_lanes"] == [
        "Independent verifier:", "Unit verifier:", "Integration verifier:",
        "System verifier:", "Regression verifier:", "Benchmark verifier:",
        "Coverage verifier:",
    ]
    assert card["waiver"] == {"type_line": "Type: Docs|Chore|Config", "tests_line": "Tests: none"}
    assert len(json.dumps(card, ensure_ascii=False).encode("utf-8")) < 1_500


def test_orient_exposes_explicit_engine_selection(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "FastLoopIntegration", _ReadyFast)
    assert cli.orient(str(tmp_path), "change app", "on", 1234, "rust") == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["fast_engine"] == "rust"
    assert _ReadyFast.last_config.engine == "rust"


def test_explicit_rust_does_not_fallback_to_mapper(tmp_path, monkeypatch, capsys):
    class _UnavailableRust(_ReadyFast):
        def prepare(self, task):
            return {"status": "FALLBACK", "reason": "rust_not_verified"}

    monkeypatch.setattr(cli, "FastLoopIntegration", _UnavailableRust)
    assert cli.orient(str(tmp_path), "change app", "auto", 1234, "rust") == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "BLOCKED"
    assert payload["fallback"] is False
    assert payload["fast_engine"] == "rust"
    assert _UnavailableRust.last_config.mode == "required"


def test_orient_auto_uses_mapper_fallback_with_reason(tmp_path, monkeypatch, capsys):
    class _FallbackFast(_ReadyFast):
        def prepare(self, task):
            return {"status": "FALLBACK", "reason": "doctor_failed"}

    monkeypatch.setattr(cli, "FastLoopIntegration", _FallbackFast)
    monkeypatch.setattr(cli, "_mapper_orient_fallback",
                        lambda root, task: {"status": "READY", "result": {"files": 1}})
    assert cli.orient(str(tmp_path), "change app", "auto", 2000, verbose=True) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "FALLBACK"
    assert payload["provider"] == "simplicio-mapper"
    assert payload["fallback_reason"] == "doctor_failed"
    assert payload["local_llm"] is False
    assert payload["llm_orientation"]["fallback_policy"]["auto"] == "mapper_read_only"
    assert payload["llm_orientation"]["request_policy"]["fallback_allowed"] is True
    assert payload["receipt"]["fallback"] is True
    assert payload["receipt"]["fallback_reason"] == "doctor_failed"
    assert payload["receipt"]["provenance"]["operator"] == "simplicio-mapper"


def test_orient_on_fails_closed_when_fast_is_unavailable(tmp_path, monkeypatch, capsys):
    class _UnavailableFast(_ReadyFast):
        def prepare(self, task):
            raise cli.FastIntegrationError("missing_operator")

    monkeypatch.setattr(cli, "FastLoopIntegration", _UnavailableFast)
    assert cli.orient(str(tmp_path), "change app", "on", 2000, verbose=True) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "BLOCKED"
    assert payload["fallback"] is False
    assert payload["fallback_reason"] == "missing_operator"
    assert payload["llm_orientation"]["request_policy"]["fallback_allowed"] is False
    assert payload["receipt"]["status"] == "BLOCKED"
    assert payload["receipt"]["fallback"] is False


def test_orient_receipt_is_deterministic_for_same_request(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "FastLoopIntegration", _ReadyFast)
    assert cli.orient(str(tmp_path), "change app", "on", 1234) == 0
    first = json.loads(capsys.readouterr().out)
    assert cli.orient(str(tmp_path), "change app", "on", 1234) == 0
    second = json.loads(capsys.readouterr().out)
    assert first["receipt"] == second["receipt"]


def test_orient_invalid_repo_still_emits_contract_and_receipt(tmp_path, capsys):
    missing = tmp_path / "missing"
    assert cli.orient(str(missing), "change app") == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "BLOCKED"
    assert payload["reason"] == "repo_or_task_invalid"
    assert payload["llm_orientation"]["schema"] == "simplicio.llm-max-speed-orientation/v1"
    assert payload["receipt"]["schema"] == "simplicio.loop-orient-receipt/v1"


def test_orient_invalid_budget_still_emits_contract_and_receipt(tmp_path, capsys):
    assert cli.orient(str(tmp_path), "change app", fast_context_budget=0) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "BLOCKED"
    assert payload["reason"] == "fast_context_budget_invalid"
    assert payload["llm_orientation"]["request_policy"]["context_budget_bytes"] == 0
    assert payload["receipt"]["status"] == "BLOCKED"


@pytest.mark.parametrize("mode", ["auto", "on", "off"])
def test_orient_help_exposes_fast_modes(mode):
    assert mode in {"auto", "on", "off"}


def test_orient_default_leads_with_context_not_policy_text(tmp_path, monkeypatch, capsys):
    """issue #1288 AC2: default output drops receipts/policy noise (llm_orientation)
    and leads with a bounded ``context`` summary instead."""
    monkeypatch.setattr(cli, "FastLoopIntegration", _ReadyFast)
    assert cli.orient(str(tmp_path), "change app", "on", 1234) == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert "\n{" not in out.strip()[1:]  # exactly one JSON document (issue #1288 AC4)
    assert "llm_orientation" not in payload
    assert "context" in payload
    assert payload["receipt"]["schema"] == "simplicio.loop-orient-receipt/v1"


def test_orient_verbose_restores_full_payload(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "FastLoopIntegration", _ReadyFast)
    assert cli.orient(str(tmp_path), "change app", "on", 1234, verbose=True) == 0
    payload = json.loads(capsys.readouterr().out)
    assert "llm_orientation" in payload
    assert "context" in payload


def test_orient_fallback_reason_reflects_real_nested_cause(tmp_path, monkeypatch, capsys):
    """issue #1288: a real ``FastLoopIntegration.prepare()`` FALLBACK result nests
    its reason under ``ingest``/``understanding`` (never a top-level ``reason``).
    orient() must surface that real cause instead of the generic
    ``fast_disabled_or_unavailable`` default."""

    class _NestedFallbackFast(_ReadyFast):
        def prepare(self, task):
            return {
                "schema": "simplicio.loop-fast-integration/v1",
                "status": "FALLBACK",
                "ingest": {
                    "status": "FALLBACK",
                    "fallback": True,
                    "reason": "mapper_handoff_unavailable: mapper crashed",
                },
                "understanding": {"status": "FALLBACK", "fallback": True,
                                   "reason": "mapper_handoff_unavailable: mapper crashed"},
            }

    monkeypatch.setattr(cli, "FastLoopIntegration", _NestedFallbackFast)
    monkeypatch.setattr(cli, "_mapper_orient_fallback",
                        lambda root, task: {"status": "READY", "result": {"files": 1}})
    assert cli.orient(str(tmp_path), "change app", "auto", 2000) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "FALLBACK"
    assert payload["fallback_reason"] != "fast_disabled_or_unavailable"
    assert payload["fallback_reason"] == "mapper_handoff_unavailable: mapper crashed"

def test_orient_cli_accepts_json_and_verbose_flags(tmp_path, monkeypatch, capsys):
    """issue #1288 AC4: ``--json`` must be accepted (it used to raise
    ``unrecognized arguments: --json``)."""
    monkeypatch.setattr(cli, "FastLoopIntegration", _ReadyFast)
    rc = cli.main(["orient", "--repo", str(tmp_path), "--task", "change app",
                   "--json", "--verbose"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "simplicio.loop-orient/v1"
    assert "llm_orientation" in payload


def test_orient_cli_fails_closed_without_mutable_authority(
    tmp_path, monkeypatch, capsys
):
    class _BlockedFast:
        def __init__(self, root, *, config, **_kwargs):
            self.root = root
            self.config = config

        def prepare(self, task):
            return {
                "schema": "simplicio.loop-fast-integration/v1",
                "status": "BLOCKED",
                "reason": "READ_ONLY_MUTATION_AUTHORITY",
                "blocked_preconditions": [
                    {
                        "reason": "READ_ONLY_MUTATION_AUTHORITY",
                        "next_surface": "orient",
                    }
                ],
                "plan": {
                    "schema": "simplicio.fast.plandag/v2",
                    "status": "BLOCKED",
                    "nodes": [{"id": "orient", "kind": "context"}],
                    "redacted_node_ids": ["modify", "refresh", "validate"],
                },
                "loop_receipt": {
                    "stage": "prepare",
                    "status": "BLOCKED",
                    "receipt_hash": "sha256:blocked",
                },
            }

    monkeypatch.setattr(cli, "FastLoopIntegration", _BlockedFast)
    assert cli.orient(str(tmp_path), "read-only qdot_i8 inspection", "on", 2000) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "BLOCKED"
    assert payload["provider"] == "simplicio-fast"
    assert payload["fast"]["reason"] == "READ_ONLY_MUTATION_AUTHORITY"
    assert payload["orient_receipt"] == payload["fast"]["loop_receipt"]
    assert payload["fast"]["plan"]["redacted_node_ids"] == [
        "modify", "refresh", "validate"
    ]
    assert "structured_patch" not in json.dumps(payload)


def test_orient_default_output_stays_bounded_when_fast_blocks(tmp_path, monkeypatch, capsys):
    """A BLOCKED Fast plan used to dump the raw understanding + plan (~670KB) on
    stdout. Default output keeps only the decision-relevant fields; --verbose
    keeps everything."""
    bulk = [{"file": f"f{i}.py", "content": "x" * 2000} for i in range(200)]

    class _BlockedBulkFast(_ReadyFast):
        def prepare(self, task):
            return {
                "schema": "simplicio.loop-fast-integration/v1",
                "status": "BLOCKED",
                "reason": "TARGET_CORRIDOR_MISMATCH",
                "blocked_preconditions": [{"code": "TARGET_CORRIDOR_MISMATCH"}],
                "intent_policy": {"explicit_targets": ["app.py"]},
                "understanding": {"schema": "u", "files": ["f0.py"], "terms": ["app"],
                                  "context": bulk, "selection": {"x": bulk}},
                "plan": {"schema": "p", "nodes": bulk},
            }

    monkeypatch.setattr(cli, "FastLoopIntegration", _BlockedBulkFast)
    monkeypatch.setattr(cli, "_mapper_orient_fallback",
                        lambda root, task: {"status": "READY", "result": {"files": 1}})
    cli.orient(str(tmp_path), "change app", "auto", 2000)
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert len(out) < 20_000, len(out)
    fast = payload["fast"]
    assert fast["understanding"]["files"] == ["f0.py"]
    assert fast["understanding"]["terms"] == ["app"]
    assert fast["blocked_preconditions"] == [{"code": "TARGET_CORRIDOR_MISMATCH"}]

    cli.orient(str(tmp_path), "change app", "auto", 2000, verbose=True)
    assert len(capsys.readouterr().out) > 200_000
