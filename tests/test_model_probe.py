"""Model-roles catalog probe (issue #1674)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from simplicio_loop import model_probe


def _which(name: str) -> str:
    return f"/usr/bin/{name}"


def _catalog() -> dict:
    return json.loads(model_probe.CATALOG.read_text(encoding="utf-8"))


def test_probe_accepts_model_on_exit_zero() -> None:
    row = model_probe.probe("grok", "execution", "grok-4.7", run=lambda _argv: (0, "ok"), which=_which)
    assert row["status"] == "accepted"
    assert row["reason_code"] == "ok"
    assert row["exit"] == 0
    assert row["command"] == "grok -m grok-4.7 -p 'reply with the single word ok'"


def test_probe_reports_refusal_reason_without_secret() -> None:
    output = (
        "Authorization: Bearer [REDACTED_SECRET]\n"
        "Couldn't set model 'grok-4.7': Invalid params: \"unknown model id\""
    )
    row = model_probe.probe("grok", "execution", "grok-4.7", run=lambda _argv: (1, output), which=_which)
    assert row["status"] == "refused"
    assert row["reason_code"] == "model_refused"
    assert row["exit"] == 1
    assert "unknown model id" in row["error"]
    assert "SECRET" not in row["error"]
    assert "SECRET" not in model_probe.redact(output)


def test_probe_classifies_codex_http_400_as_refused() -> None:
    output = "HTTP 400: The 'gpt-5.6-luna' model is not supported when using Codex with a ChatGPT account"
    row = model_probe.probe("codex", "execution", "gpt-5.6-luna", run=lambda _argv: (1, output), which=_which)
    assert row["reason_code"] == "model_refused"
    assert "not supported" in row["error"]


def test_probe_classifies_timeout_as_timeout() -> None:
    row = model_probe.probe("grok", "execution", "grok-4.7", run=lambda _argv: (-1, "timeout"), which=_which)
    assert row["status"] == "refused"
    assert row["reason_code"] == "timeout"


def test_run_cli_reports_a_hung_cli_as_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def hang(argv: list[str], **_kwargs: object) -> None:
        raise subprocess.TimeoutExpired(argv, 1)

    monkeypatch.setattr(model_probe.subprocess, "run", hang)
    assert model_probe.run_cli(["grok", "-m", "grok-4.7", "-p", "x"]) == (-1, "timeout")


def test_probe_skips_missing_cli_and_default_model() -> None:
    missing = model_probe.probe("grok", "execution", "grok-4.7", which=lambda _name: None)
    assert (missing["status"], missing["reason_code"]) == ("skipped", "cli_missing")
    default = model_probe.probe("opencode", "execution", "default", which=_which)
    assert (default["status"], default["reason_code"]) == ("skipped", "not_probeable")


def test_main_exit_code_follows_refusal(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    catalog = tmp_path / "roles.json"
    catalog.write_text(
        json.dumps({"families": {"grok": {"execution": {"model": "grok-4.7", "effort": "high"}}}}),
        encoding="utf-8",
    )
    refused = model_probe.main(
        ["--catalog", str(catalog)],
        run=lambda _argv: (1, 'Invalid params: "unknown model id"'),
        which=_which,
    )
    assert refused == 1
    assert "reason_code=model_refused" in capsys.readouterr().out
    accepted = model_probe.main(["--catalog", str(catalog)], run=lambda _argv: (0, "ok"), which=_which)
    assert accepted == 0


def test_is_listed_matches_whole_model_id() -> None:
    assert model_probe.is_listed("grok-4.7", "grok-4.7")
    assert model_probe.is_listed("grok-4.7", "grok-4.7 (default)")
    assert model_probe.is_listed("grok-4.7", "models: grok-4.7, grok-build")
    assert not model_probe.is_listed("grok-4", "grok-4.7 (default)")
    assert not model_probe.is_listed("grok-4.8", "grok-4.7 (default)")
    assert not model_probe.is_listed("grok-4", "grok-4x")
    assert not model_probe.is_listed("grok-4.7", "xgrok-4.7")
    assert not model_probe.is_listed("grok-4.7", "grok-4.7x")
    assert not model_probe.is_listed("grok-4.7", "grok-4.7-mini")


def test_every_catalog_role_has_a_probe_or_default_model() -> None:
    for family, by_role in _catalog()["families"].items():
        for role, spec in by_role.items():
            assert family in model_probe.COMMANDS or spec["model"] == "default", f"{family}/{role}"


@pytest.mark.skipif(shutil.which("grok") is None, reason="grok CLI not installed")
def test_grok_catalog_ids_are_accepted_by_grok_models() -> None:
    """grok/execution and grok/coordination models must be listed by `grok models`."""
    try:
        proc = subprocess.run(
            ["grok", "models"],
            capture_output=True,
            text=True,
            timeout=60,
            stdin=subprocess.DEVNULL,
            check=False,
        )
    except subprocess.TimeoutExpired:
        pytest.skip("`grok models` timed out after 60s")
    if proc.returncode != 0:
        detail = model_probe.redact(proc.stderr.strip())[:200]
        pytest.skip(f"`grok models` exited {proc.returncode}: {detail}")
    listing = f"{proc.stdout}\n{proc.stderr}"
    if "Available models" not in listing:  # a CLI without a login answers with exit 0 and no model list: that is not a missing id
        pytest.skip(f"`grok models` printed no model list (not logged in?): {model_probe.redact(listing.strip())[:120]}")
    missing = []
    for role in ("planning", "coordination", "execution"):
        spec = _catalog()["families"]["grok"][role]
        if not model_probe.is_listed(spec["model"], listing):
            missing.append(f"{role}={spec['model']}")
    assert not missing, f"grok catalog ids not listed by `grok models`: {missing}"


@pytest.mark.skipif(shutil.which("codex") is None, reason="codex CLI not installed")
def test_codex_catalog_models_are_in_the_codex_models_cache() -> None:
    """Each codex role model must be a slug in the codex models_cache."""
    models_cache = Path.home() / ".codex" / "models_cache.json"
    if not models_cache.exists():
        pytest.skip(f"codex models_cache not found at {models_cache}")

    try:
        cache_data = json.loads(models_cache.read_text(encoding="utf-8"))
        models = cache_data.get("models", [])
        model_slugs = [m.get("slug") for m in models if m.get("slug")]
    except (json.JSONDecodeError, TypeError):
        pytest.skip("codex models_cache is not readable or invalid")

    codex = _catalog()["families"]["codex"]
    expected = {"planning": "gpt-5.6-terra", "coordination": "gpt-5.5", "execution": "gpt-5.6-luna"}
    for role, model in expected.items():
        assert codex[role]["model"] == model, f"codex/{role}"
        assert model in model_slugs, f"codex/{role}={model} not in codex models cache: {model_slugs}"
