from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.check_effect_boundary import (
    BASELINE_SHA256,
    inventory_digest,
    mutation_inventory,
)
from scripts.check_effect_boundary import main as guard_main
from simplicio import pipeline
from simplicio.commands import edit as edit_cmd
from simplicio.commands import run as run_cmd
from simplicio.execution_mode import negotiate_execution_mode
from simplicio.standalone_migration import (
    clear_effect_unknown,
    effect_unknown_pending,
    migration_phase,
    mutation_receipt,
    mutation_route_for_mode,
    record_effect_unknown,
    standalone_policy,
    standalone_policy_for_root,
)


def test_shadow_preserves_legacy_compatibility_by_default():
    policy = standalone_policy({})

    assert policy.phase == "shadow"
    assert policy.write_allowed is True
    assert policy.legacy_opt_in is False
    assert policy.reason_code == "LEGACY_STANDALONE_SHADOW"


@pytest.mark.parametrize("phase", ["opt_in", "warning"])
def test_migration_window_requires_explicit_legacy_opt_in(monkeypatch, phase):
    monkeypatch.setenv("SIMPLICIO_STANDALONE_MIGRATION_PHASE", phase)
    assert standalone_policy().write_allowed is False

    monkeypatch.setenv("SIMPLICIO_ENABLE_LEGACY_STANDALONE_WRITE", "1")
    policy = standalone_policy()
    assert policy.write_allowed is True
    assert policy.reason_code == "LEGACY_STANDALONE_OPTED_IN"


@pytest.mark.parametrize("phase", ["read_only", "removed", "invalid"])
def test_terminal_phases_fail_closed_even_with_opt_in(monkeypatch, phase):
    monkeypatch.setenv("SIMPLICIO_STANDALONE_MIGRATION_PHASE", phase)
    monkeypatch.setenv("SIMPLICIO_ENABLE_LEGACY_STANDALONE_WRITE", "1")

    policy = standalone_policy()

    assert policy.write_allowed is False
    assert policy.reason_code == "LEGACY_STANDALONE_READ_ONLY"
    if phase == "invalid":
        assert migration_phase() == "read_only"


def test_empty_explicit_phase_fails_closed(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_STANDALONE_MIGRATION_PHASE", "")

    assert migration_phase() == "read_only"
    assert standalone_policy().write_allowed is False


def test_effect_unknown_forbids_legacy_fallback(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_ENABLE_LEGACY_STANDALONE_WRITE", "1")

    policy = standalone_policy(previous_effect_outcome="effect_unknown")

    assert policy.write_allowed is False
    assert policy.reason_code == "EFFECT_UNKNOWN_RECONCILIATION_REQUIRED"


def test_effect_unknown_lock_survives_invocations_until_verified_reconciliation(tmp_path):
    record_effect_unknown(str(tmp_path))

    assert effect_unknown_pending(str(tmp_path)) is True
    assert standalone_policy_for_root(str(tmp_path)).write_allowed is False
    with pytest.raises(ValueError, match="reconciliation proof"):
        clear_effect_unknown(str(tmp_path), runtime_reconciled=False)
    assert effect_unknown_pending(str(tmp_path)) is True

    clear_effect_unknown(str(tmp_path), runtime_reconciled=True)
    assert effect_unknown_pending(str(tmp_path)) is False


def test_auto_fails_closed_in_opt_in_phase_until_legacy_flag(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_STANDALONE_MIGRATION_PHASE", "opt_in")
    handshake = {"verified": False, "capabilities": [], "reason": "runtime-absent"}

    blocked = negotiate_execution_mode("auto", runtime_handshake=handshake)
    assert blocked.effective_mode == "blocked"
    assert blocked.reason_code == "LEGACY_STANDALONE_OPT_IN_REQUIRED"

    monkeypatch.setenv("SIMPLICIO_ENABLE_LEGACY_STANDALONE_WRITE", "true")
    monkeypatch.setenv("SIMPLICIO_ALLOW_STANDALONE_FALLBACK", "true")
    compatible = negotiate_execution_mode("auto", runtime_handshake=handshake)
    assert compatible.effective_mode == "standalone"
    assert compatible.standalone_policy["legacy_opt_in"] is True


def test_explicit_standalone_cannot_bypass_effect_unknown(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_ENABLE_LEGACY_STANDALONE_WRITE", "1")

    profile = negotiate_execution_mode(
        "standalone",
        runtime_handshake={"verified": False, "capabilities": []},
        previous_effect_outcome="effect_unknown",
    )

    assert profile.effective_mode == "blocked"
    assert profile.reason_code == "EFFECT_UNKNOWN_RECONCILIATION_REQUIRED"


def test_read_only_mode_still_allows_non_mutating_dry_run(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_STANDALONE_MIGRATION_PHASE", "read_only")

    profile = negotiate_execution_mode(
        "auto",
        runtime_handshake={"verified": False, "capabilities": []},
        read_only=True,
    )

    assert profile.effective_mode == "standalone"
    assert profile.reason_code == "AUTO_READ_ONLY"


@pytest.mark.parametrize("mode", ["auto", "integrated"])
def test_eligible_runtime_never_dispatches_for_dry_run(mode, monkeypatch):
    class ProductSink:
        pass

    context = {"schema": "simplicio.context-snapshot/v1", "snapshot_id": "snapshot"}
    monkeypatch.setattr("simplicio.execution_mode.RuntimeEffectSink", ProductSink)
    monkeypatch.setattr(
        "simplicio.execution_mode.load_mapper_context",
        lambda *_args, **_kwargs: SimpleNamespace(payload_bytes=b"context"),
    )
    monkeypatch.setenv("SIMPLICIO_EXECUTION_ROLLOUT", "default")
    profile = negotiate_execution_mode(
        mode,
        runtime_handshake={
            "verified": True,
            "capabilities": ["simplicio.effect-transaction/v1"],
        },
        context_snapshot=context,
        effect_sink=ProductSink(),
        read_only=True,
    )

    assert profile.effective_mode == "standalone"
    assert profile.reason_code in {"AUTO_READ_ONLY", "INTEGRATED_READ_ONLY"}


def test_receipts_distinguish_legacy_from_runtime():
    legacy = mutation_receipt("legacy_standalone", entrypoint="task", policy=standalone_policy())
    runtime = mutation_receipt("runtime_effect_api", entrypoint="edit")

    assert legacy["legacy"] is True
    assert legacy["runtime_gated"] is False
    assert runtime["legacy"] is False
    assert runtime["runtime_gated"] is False
    assert runtime["route"] == "runtime_effect_api"

    verified = mutation_receipt("runtime_effect_api", entrypoint="task", runtime_gate_verified=True)
    assert verified["runtime_gated"] is True


def test_task_patch_receipt_is_always_marked_legacy():
    pipeline._remember_patch_receipt({"transaction_id": "local-1"})

    assert pipeline._LAST_PATCH_RECEIPT is not None
    route = pipeline._LAST_PATCH_RECEIPT["mutation_route"]
    assert route["route"] == "legacy_standalone"
    assert route["runtime_gated"] is False
    pipeline._remember_patch_receipt(None)


def test_effective_modes_map_to_stable_mutation_routes():
    assert mutation_route_for_mode("integrated") == "runtime_effect_api"
    assert mutation_route_for_mode("standalone") == "legacy_standalone"
    assert mutation_route_for_mode("blocked") == "blocked"


def _plan(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema": "simplicio.mechanical-edit/v1",
                "operations": [{"op": "create_file", "path": "product.txt", "text": "changed\n"}],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_edit_apply_is_refused_without_opt_in_and_does_not_mutate(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SIMPLICIO_STANDALONE_MIGRATION_PHASE", "opt_in")
    args = argparse.Namespace(
        root=str(tmp_path),
        plan=str(_plan(tmp_path / "plan.json")),
        apply=True,
        json=True,
    )

    code = edit_cmd.run_mechanical_edit(args)
    payload = json.loads(capsys.readouterr().out)

    assert code == 1
    assert payload["errors"][0]["code"] == "LEGACY_STANDALONE_OPT_IN_REQUIRED"
    assert payload["mutation_receipt"]["route"] == "blocked"
    assert payload["mutation_receipt"]["runtime_gated"] is False
    assert not (tmp_path / "product.txt").exists()


def test_edit_opt_in_keeps_offline_legacy_compatibility(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SIMPLICIO_STANDALONE_MIGRATION_PHASE", "opt_in")
    monkeypatch.setenv("SIMPLICIO_ENABLE_LEGACY_STANDALONE_WRITE", "1")
    args = argparse.Namespace(
        root=str(tmp_path),
        plan=str(_plan(tmp_path / "plan.json")),
        apply=True,
        json=True,
    )

    code = edit_cmd.run_mechanical_edit(args)
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["mutation_receipt"]["route"] == "legacy_standalone"
    assert (tmp_path / "product.txt").read_text(encoding="utf-8") == "changed\n"


def test_native_multi_file_apply_is_refused_before_any_subprocess(tmp_path, monkeypatch):
    calls = []
    args = argparse.Namespace(root=str(tmp_path), apply=True)
    plans = [
        {"file": "one.txt", "operations": [{"op": "append", "text": "one"}]},
        {"file": "two.txt", "operations": [{"op": "append", "text": "two"}]},
    ]
    monkeypatch.setattr(
        edit_cmd.subprocess,
        "run",
        lambda *a, **k: calls.append((a, k)),
    )

    result = edit_cmd._run_native_edit_plans("simplicio", plans, args)

    assert result["status"] == "refused"
    assert result["errors"][0]["code"] == "RUNTIME_ATOMIC_MULTI_FILE_REQUIRED"
    assert calls == []


def test_ambiguous_native_edit_records_lock_and_blocks_next_attempt(tmp_path, monkeypatch, capsys):
    args = argparse.Namespace(root=str(tmp_path), apply=True)
    plan = [{"file": "one.txt", "operations": [{"op": "append", "text": "one"}]}]
    monkeypatch.setattr(
        edit_cmd.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="not-json", stderr=""),
    )

    result = edit_cmd._run_native_edit_plans("simplicio", plan, args)

    assert result["status"] == "effect_unknown"
    assert effect_unknown_pending(str(tmp_path)) is True

    code = edit_cmd.run_edit(
        argparse.Namespace(
            root=str(tmp_path),
            plan="-",
            apply=True,
            json=True,
            no_runtime=False,
        )
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload["errors"][0]["code"] == "EFFECT_UNKNOWN_RECONCILIATION_REQUIRED"


def test_feature_mode_guard_emits_blocked_route_without_running_planner(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SIMPLICIO_STANDALONE_MIGRATION_PHASE", "opt_in")
    monkeypatch.setattr(
        "simplicio.runtime_contracts.runtime_verify_contract",
        lambda: {"verified": False, "capabilities": [], "reason": "runtime-absent"},
    )
    args = SimpleNamespace(root=str(tmp_path), mode="auto", scope="feature", json=True)

    guarded = run_cmd._mode_guard(args)

    assert guarded is not None
    assert guarded[0]["warnings"] == ["LEGACY_STANDALONE_OPT_IN_REQUIRED"]
    events = [
        json.loads(line)
        for line in (tmp_path / ".simplicio" / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    route = next(event for event in events if event["event"] == "mutation_route_selected")
    assert route["payload"]["entrypoint"] == "feature"
    assert set(route["payload"]) == {
        "entrypoint",
        "legacy_opt_in",
        "migration_phase",
        "reason_code",
        "route",
        "schema",
    }


def test_guard_inventory_is_deterministic_and_detects_new_write(tmp_path):
    package = tmp_path / "simplicio"
    package.mkdir()
    source = package / "sample.py"
    source.write_text(
        "from pathlib import Path\ndef mutate(path):\n    Path(path).write_text('x', encoding='utf-8')\n",
        encoding="utf-8",
    )

    before = mutation_inventory(tmp_path)
    before_digest = inventory_digest(before)
    source.write_text(
        source.read_text(encoding="utf-8") + "def mutate_again(path):\n    Path(path).unlink()\n",
        encoding="utf-8",
    )
    after = mutation_inventory(tmp_path)

    assert before == [
        {
            "path": "simplicio/sample.py",
            "scope": "mutate",
            "primitive": "write_text",
            "count": 1,
        }
    ]
    assert inventory_digest(after) != before_digest


def test_guard_detects_imported_and_assigned_mutation_aliases(tmp_path):
    package = tmp_path / "simplicio"
    package.mkdir()
    (package / "aliases.py").write_text(
        "from os import remove as erase\n"
        "from pathlib import Path\n"
        "from subprocess import run as execute\n"
        "delete = erase\n"
        "def mutate(path):\n"
        "    writer = Path(path).write_text\n"
        "    delete(path)\n"
        "    writer('x', encoding='utf-8')\n"
        "    execute(['git', 'apply'])\n",
        encoding="utf-8",
    )

    inventory = mutation_inventory(tmp_path)

    assert {row["primitive"] for row in inventory} == {"remove", "run", "write_text"}


def test_repository_effect_boundary_inventory_matches_baseline():
    root = Path(__file__).parents[2]

    assert inventory_digest(mutation_inventory(root)) == BASELINE_SHA256


def test_effect_boundary_guard_cli_passes_repository_and_reports_mismatch(tmp_path, capsys):
    root = Path(__file__).parents[2]
    assert guard_main(["--root", str(root)]) == 0
    assert "guard passed" in capsys.readouterr().out

    package = tmp_path / "simplicio"
    package.mkdir()
    (package / "sample.py").write_text(
        "def mutate(path):\n"
        "    with open(path, mode='a', encoding='utf-8') as handle:\n"
        "        handle.write('x')\n",
        encoding="utf-8",
    )
    assert guard_main(["--root", str(tmp_path), "--inventory"]) == 1
    output = capsys.readouterr().out
    assert '"primitive": "open:write"' in output
    assert "guard failed" in output


def test_approved_runtime_effect_boundary_is_excluded(tmp_path):
    boundary = tmp_path / "simplicio" / "plan_compiler"
    boundary.mkdir(parents=True)
    (boundary / "runtime_effect_sink.py").write_text(
        "from pathlib import Path\nPath('receipt').write_text('ok')\n",
        encoding="utf-8",
    )

    assert mutation_inventory(tmp_path) == []


def test_approved_hbp_effect_boundary_is_excluded(tmp_path):
    boundary = tmp_path / "simplicio"
    boundary.mkdir(parents=True)
    (boundary / "hbp.py").write_text(
        "from pathlib import Path\nPath('hbp-inbox.bin').write_bytes(b'HBP1')\n",
        encoding="utf-8",
    )

    assert mutation_inventory(tmp_path) == []
