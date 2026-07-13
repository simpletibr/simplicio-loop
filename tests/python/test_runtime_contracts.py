from __future__ import annotations

import json
import logging
import re
import subprocess
from pathlib import Path

import pytest

from simplicio import cli
from simplicio import observability as obs
from simplicio.runtime_contracts import (
    doctor_contract,
    is_legacy_runtime_alias,
    runtime_verify_contract,
    task_contract,
    version_contract,
)


@pytest.fixture(autouse=True)
def _reset_logging_state():
    """Isolate each test from the module-level logger singleton (see
    `test_observability.py`'s identical fixture) — `configure_logging`
    deliberately only attaches its stderr handler once per process, so a
    stale handler bound to an earlier test's `capsys` stream would silently
    swallow/misroute stderr assertions here otherwise."""
    obs._configured = False
    obs._logger.handlers.clear()
    obs._logger.setLevel(logging.NOTSET)
    yield
    obs._configured = False
    obs._logger.handlers.clear()
    obs._logger.setLevel(logging.NOTSET)


def test_doctor_contract_resolves_published_prompt_and_sprint_entrypoints(tmp_path, monkeypatch):
    def fake_which(name: str):
        return {"simplicio-subagents": "/bin/simplicio-subagents", "sendsprint": "/bin/sendsprint"}.get(name)

    monkeypatch.setattr("simplicio.runtime_contracts.shutil.which", fake_which)
    result = doctor_contract(tmp_path)

    assert result["tools"]["simplicio-prompt"] == {
        "available": True,
        "path": "/bin/simplicio-subagents",
        "resolved_command": "simplicio-subagents",
    }
    assert result["tools"]["simplicio-sprint"] == {
        "available": True,
        "path": "/bin/sendsprint",
        "resolved_command": "sendsprint",
    }


def test_version_contract_exposes_canonical_capabilities(monkeypatch):
    monkeypatch.setattr("simplicio.runtime_contracts.__version__", "0.12.0")
    payload = version_contract()

    assert payload["schema"] == "simplicio.dev-cli.version/v1"
    assert payload["package"] == {"name": "simplicio-cli", "version": "0.12.0"}
    assert payload["identity"] == {
        "product": "simplicio-dev-cli",
        "role": "adapter",
        "family": "simplicio",
        "canonical_entrypoint": "simplicio-dev-cli",
    }
    assert "simplicio.task-spec/v2" in payload["capabilities"]
    assert "simplicio.dev-cli.patch-receipt/v1" in payload["capabilities"]
    assert "simplicio.dev-cli.task-batch/v1" in payload["capabilities"]
    assert "simplicio.prompt-envelope/v1" in payload["capabilities"]
    assert payload["compatibility"]["task_spec"]["minimum_consumer_major"] == 2
    assert payload["compatibility"]["runtime"] == {
        "product": "simplicio-runtime",
        "reserved_command": "simplicio",
        "reject_products": ["simplicio-agent", "hermes"],
        "diagnostic": (
            "Expected Simplicio Runtime on `simplicio`; if PATH resolves to "
            "Agent/Desktop, use `simplicio-agent` for that binary and point "
            "runtime consumers at the Rust runtime explicitly."
        ),
    }


def test_version_cli_supports_text_and_json(monkeypatch, capsys):
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")

    assert cli.main(["--version"]) == 0
    assert "simplicio-py 0.15.0" in capsys.readouterr().out

    assert cli.main(["version", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "simplicio.dev-cli.version/v1"
    assert payload["identity"]["product"] == "simplicio-dev-cli"
    assert payload["compatibility"]["runtime"]["reserved_command"] == "simplicio"


def test_doctor_contract_reports_ecosystem_tool_status(tmp_path, monkeypatch):
    def fake_which(name: str):
        return f"/bin/{name}" if name in {"simplicio-mapper", "simplicio-dev-cli", "simplicio-py"} else None

    monkeypatch.setattr("simplicio.runtime_contracts.shutil.which", fake_which)
    monkeypatch.setattr(
        "simplicio.runtime_contracts._package_version",
        lambda name: "1.2.3" if name == "simplicio-cli" else None,
    )

    result = doctor_contract(tmp_path)

    assert result["schema"] == "simplicio.dev-cli.doctor/v1"
    assert result["root"] == str(tmp_path)
    assert result["tools"]["simplicio-mapper"]["available"] is True
    assert result["tools"]["simplicio-dev-cli"]["available"] is True
    assert result["tools"]["simplicio-py"]["available"] is True
    assert result["tools"]["simplicio-sprint"]["available"] is False
    assert "simplicio" not in result["tools"]
    assert result["packages"]["simplicio-cli"]["version"] == "1.2.3"
    assert result["package"]["version"] == "1.2.3"
    assert result["identity"] == {
        "product": "simplicio-dev-cli",
        "role": "adapter",
        "family": "simplicio",
        "canonical_entrypoint": "simplicio-dev-cli",
    }
    assert result["entrypoints"] == {
        "adapter": "simplicio-dev-cli",
        "python_adapter": "simplicio-py",
        "reserved_runtime": "simplicio",
    }
    assert result["runtime"]["model"] == "openbmb/minicpm5:latest"


def test_doctor_contract_falls_back_to_local_version_for_editable_checkout(tmp_path, monkeypatch):
    monkeypatch.setattr("simplicio.runtime_contracts.shutil.which", lambda name: None)
    monkeypatch.setattr("simplicio.runtime_contracts._package_version", lambda name: None)

    result = doctor_contract(tmp_path)

    assert result["package"]["version"]
    assert result["packages"]["simplicio-cli"]["version"] == result["package"]["version"]


def test_task_contract_wraps_existing_task_result_for_runtime_handoff(tmp_path):
    result = task_contract(
        {
            "task_id": "src/app.py",
            "applied": True,
            "files_changed": ["src/app.py"],
            "warnings": [],
        },
        root=tmp_path,
    )

    assert result["schema"] == "simplicio.dev-cli.task/v1"
    assert result["root"] == str(tmp_path)
    assert result["task"]["task_id"] == "src/app.py"
    assert result["applied"] is True


def test_runtime_doctor_cli_outputs_json_contract(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")
    monkeypatch.setattr("simplicio.runtime_contracts.shutil.which", lambda name: None)

    code = cli.main(["runtime", "doctor", "--root", str(tmp_path), "--json"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "simplicio.dev-cli.doctor/v1"
    assert payload["root"] == str(tmp_path)


def test_smoke_cli_can_emit_stable_json(monkeypatch, capsys):
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")
    monkeypatch.setattr("simplicio.providers.info", lambda: "test-provider")
    monkeypatch.setattr("simplicio.providers.generate", lambda prompt: "OK simplicio connected.")

    code = cli.main(["smoke", "--json"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "simplicio.dev-cli.smoke/v1"
    assert payload["provider"] == "test-provider"
    assert payload["ok"] is True


# ── Issue #93: impact-test evidence in task_contract ─────────────────────


def test_task_contract_carries_impact_block_when_present():
    result = task_contract(
        {
            "task_id": "src/lib.py",
            "applied": True,
            "files_changed": ["src/lib.py"],
            "warnings": [],
            "impact": {
                "callers": ["src/caller.py"],
                "tests_run": ["tests/test_caller.py"],
                "result": "passed",
                "status": "verified",
            },
        },
    )

    assert "impact" in result
    assert result["impact"]["callers"] == ["src/caller.py"]
    assert result["impact"]["tests_run"] == ["tests/test_caller.py"]
    assert result["impact"]["result"] == "passed"
    assert result["impact"]["status"] == "verified"


def test_task_contract_carries_prompt_envelope_when_present():
    result = task_contract(
        {
            "task_id": "src/lib.py",
            "applied": True,
            "files_changed": ["src/lib.py"],
            "warnings": [],
            "prompt_envelope": {
                "schema": "simplicio.prompt-envelope/v1",
                "prefix_hash": "sha256:abc",
            },
        },
    )

    assert result["prompt_envelope"]["schema"] == "simplicio.prompt-envelope/v1"
    assert result["task"]["prompt_envelope"]["prefix_hash"] == "sha256:abc"


def test_task_contract_carries_verify_block_when_present():
    result = task_contract(
        {
            "task_id": "src/lib.py",
            "applied": True,
            "files_changed": ["src/lib.py"],
            "warnings": [],
            "verify": {
                "status": "verified",
                "receipt": {
                    "command": "pytest -q",
                    "exit_code": 0,
                    "receipt_digest": "digest",
                },
            },
        },
    )

    assert result["verify"]["status"] == "verified"
    assert result["verify"]["receipt"]["command"] == "pytest -q"
    assert result["task"]["verify"]["status"] == "verified"
    assert result["task"]["verify"]["receipt"]["command"] == "pytest -q"
    assert result["task"]["verify"]["receipt"]["receipt_digest"] == "digest"


def test_task_contract_omits_impact_block_when_absent():
    result = task_contract(
        {
            "task_id": "src/lib.py",
            "applied": True,
            "files_changed": ["src/lib.py"],
            "warnings": [],
        },
    )

    assert "impact" not in result


def test_task_contract_impact_block_shows_unverified_when_unknown():
    result = task_contract(
        {
            "task_id": "src/lib.py",
            "applied": True,
            "files_changed": ["src/lib.py"],
            "warnings": [],
            "impact": {"callers": [], "tests_run": [], "result": "unverified"},
        },
    )

    assert "impact" in result
    assert result["impact"]["result"] == "unverified"
    assert result["impact"]["status"] == "unverified"


# ── Issue #167: legacy alias (Hermes/Agent) compat warning ──────────────


def test_is_legacy_runtime_alias_matches_known_reject_products():
    assert is_legacy_runtime_alias("hermes") is True
    assert is_legacy_runtime_alias("simplicio-agent") is True
    assert is_legacy_runtime_alias("SIMPLICIO-AGENT") is True
    assert is_legacy_runtime_alias("simplicio-runtime") is False
    assert is_legacy_runtime_alias(None) is False
    assert is_legacy_runtime_alias("") is False


def _fake_completed(stdout: str) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=["stub"], returncode=0, stdout=stdout, stderr="")


def test_runtime_verify_contract_flags_legacy_alias(monkeypatch):
    monkeypatch.setattr("simplicio.runtime_contracts.shutil.which", lambda name: "/bin/simplicio")
    monkeypatch.setattr(
        "simplicio.runtime_contracts.subprocess.run",
        lambda *a, **k: _fake_completed(json.dumps({"runtime": "hermes", "status": "passed", "checks": []})),
    )

    payload = runtime_verify_contract()

    assert payload["reason"] == "wrong-runtime-product"
    assert payload["product"] == "hermes"
    assert payload["legacy_alias"] is True


def test_runtime_verify_contract_does_not_flag_unknown_product(monkeypatch):
    monkeypatch.setattr("simplicio.runtime_contracts.shutil.which", lambda name: "/bin/simplicio")
    monkeypatch.setattr(
        "simplicio.runtime_contracts.subprocess.run",
        lambda *a, **k: _fake_completed(
            json.dumps({"runtime": "some-other-tool", "status": "passed", "checks": []})
        ),
    )

    payload = runtime_verify_contract()

    assert payload["reason"] == "wrong-runtime-product"
    assert payload["legacy_alias"] is False


def test_runtime_verify_cli_warning_never_corrupts_json_stdout(monkeypatch, capsys):
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")
    monkeypatch.setattr("simplicio.runtime_contracts.shutil.which", lambda name: "/bin/simplicio")
    monkeypatch.setattr(
        "simplicio.runtime_contracts.subprocess.run",
        lambda *a, **k: _fake_completed(json.dumps({"runtime": "hermes", "status": "passed", "checks": []})),
    )

    code = cli.main(["runtime", "verify"])
    captured = capsys.readouterr()

    assert code == 1
    # stdout must stay pure JSON — the warning must never land there.
    payload = json.loads(captured.out)
    assert payload["legacy_alias"] is True
    assert "legacy runtime alias" not in captured.out
    assert "legacy runtime alias" in captured.err


def test_runtime_verify_cli_warning_omits_env_values_and_cli_args(monkeypatch, capsys):
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")
    secret_marker = "sk-super-secret-marker-should-never-leak-123"
    monkeypatch.setenv("SIMPLICIO_SECRET_PROBE", secret_marker)
    monkeypatch.setattr("simplicio.runtime_contracts.shutil.which", lambda name: "/bin/simplicio")
    monkeypatch.setattr(
        "simplicio.runtime_contracts.subprocess.run",
        lambda *a, **k: _fake_completed(json.dumps({"runtime": "hermes", "status": "passed", "checks": []})),
    )

    code = cli.main(["runtime", "verify", "--timeout", "7"])
    captured = capsys.readouterr()

    assert code == 1
    assert secret_marker not in captured.err
    assert secret_marker not in captured.out
    assert "--timeout" not in captured.err
    assert "SIMPLICIO_SECRET_PROBE" not in captured.err


def test_runtime_verify_cli_does_not_warn_for_real_runtime_product(monkeypatch, capsys):
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")
    monkeypatch.setattr("simplicio.runtime_contracts.shutil.which", lambda name: "/bin/simplicio")
    monkeypatch.setattr(
        "simplicio.runtime_contracts.subprocess.run",
        lambda *a, **k: _fake_completed(
            json.dumps({"runtime": "simplicio-runtime", "status": "passed", "checks": []})
        ),
    )

    cli.main(["runtime", "verify"])
    captured = capsys.readouterr()

    assert "legacy runtime alias" not in captured.err


# ── Issue #167: "Alias telemetry não contém conteúdo sensível" — repo-wide
# audit, not just the one stderr warning above (PR #173's scope). Every
# `emit_event`/`emit_data` call site in `simplicio/` that touches
# alias/legacy/Hermes data must never interpolate raw CLI args, prompt text,
# file contents, or env var *values* into the emitted payload/line. ──

_SIMPLICIO_SRC = Path(__file__).resolve().parents[2] / "simplicio"

# Terms that mark a source line as related to the Hermes/legacy-runtime-alias
# rebrand (issue #167). Kept in sync with `LEGACY_RUNTIME_ALIASES` /
# `is_legacy_runtime_alias` in `simplicio/runtime_contracts.py`.
_ALIAS_TERMS = re.compile(
    r"hermes|legacy_alias|legacy.?runtime.?alias|LEGACY_RUNTIME_ALIASES|reject_products", re.IGNORECASE
)

_EMIT_CALL = re.compile(r"\bemit_event\s*\(|\bemit_data\s*\(")


def _iter_python_files(root: Path):
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def test_alias_telemetry_audit_covers_every_emit_call_site_in_simplicio():
    """Repo-wide grep, done once here and pinned so it regresses loudly.

    As of issue #167 slice covering this AC, a full `grep -rniE
    "hermes|legacy.?alias|reject_products"` over `simplicio/` (excluding
    bytecode) turns up exactly two source files:

    - `simplicio/runtime_contracts.py` (the `LEGACY_RUNTIME_ALIASES` list,
      `is_legacy_runtime_alias()`, and the `reject_products`/`legacy_alias`
      contract fields).
    - `simplicio/commands/runtime.py` (the static
      `LEGACY_RUNTIME_ALIAS_WARNING` stderr-only warning, covered end-to-end
      by the tests above, including the secret-marker test).
    - `simplicio/plan_compiler/compat_adapter.py` (a docstring reference to
      the issue's invariant 6, "Compatibilidade Hermes fica em uma borda
      registrada" — prose only, not a telemetry call site).

    None of those three files calls `emit_event`/`emit_data` — the alias
    signal never reaches the JSONL telemetry sink
    (`simplicio/observability.py`'s `emit_event`), only a static,
    non-interpolated stderr string. This test pins that fact: if a future
    change adds alias/legacy/Hermes-related telemetry anywhere in
    `simplicio/`, this test must be updated (and a new secret-marker
    regression test added alongside it) rather than silently drifting.
    """
    hits: dict[str, list[int]] = {}
    for path in _iter_python_files(_SIMPLICIO_SRC):
        lines = path.read_text(encoding="utf-8").splitlines()
        matches = [i + 1 for i, line in enumerate(lines) if _ALIAS_TERMS.search(line)]
        if matches:
            hits[str(path.relative_to(_SIMPLICIO_SRC))] = matches

    assert set(hits) == {
        "runtime_contracts.py",
        "commands/runtime.py",
        "plan_compiler/compat_adapter.py",
    }, (
        f"alias/legacy/Hermes references found in unexpected files: {sorted(hits)}. "
        "If this is a new, legitimate call site, audit whether it calls "
        "emit_event/emit_data with sensitive interpolation and extend this test."
    )

    for relative_path in hits:
        source = (_SIMPLICIO_SRC / relative_path).read_text(encoding="utf-8")
        assert not _EMIT_CALL.search(source), (
            f"{relative_path} references alias/legacy/Hermes data AND calls "
            "emit_event/emit_data — this needs a dedicated secret-marker test "
            "asserting no raw CLI args/prompt/file contents/env values leak "
            "into the emitted record, per issue #167's "
            "'Alias telemetry não contém conteúdo sensível' AC."
        )


def test_alias_telemetry_audit_finds_no_emit_event_or_emit_data_call_sites_at_all():
    """Belt-and-suspenders: confirm neither of the two alias-aware modules
    imports `emit_event`/`emit_data` from `observability` either, so the
    absence of a direct call above isn't just a naming coincidence."""
    for relative_path in ("runtime_contracts.py", "commands/runtime.py", "plan_compiler/compat_adapter.py"):
        source = (_SIMPLICIO_SRC / relative_path).read_text(encoding="utf-8")
        assert "emit_event" not in source
        assert "emit_data" not in source
