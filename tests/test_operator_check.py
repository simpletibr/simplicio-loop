import json
import subprocess
import time
from pathlib import Path

import pytest

from scripts import operator_check


# --------------------------------------------------------------------------
# should_upgrade — pure TTL decision
# --------------------------------------------------------------------------

def test_no_prior_check_recommends_upgrade(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_OPERATOR_ALWAYS_LATEST", "0")
    cache = tmp_path / "operator-check.json"
    decision = operator_check.should_upgrade(cache, binaries=())
    assert decision["should_upgrade"] is True
    assert decision["reason"] == "no prior check recorded"


def test_missing_binary_recommends_upgrade_even_within_ttl(tmp_path):
    cache = tmp_path / "operator-check.json"
    operator_check.record_check(cache, {"simplicio-mapper": "0.23.1"})
    decision = operator_check.should_upgrade(
        cache, binaries=("definitely-not-a-real-binary-xyz",)
    )
    assert decision["should_upgrade"] is True
    assert "binary missing" in decision["reason"]


def test_fresh_check_within_ttl_does_not_recommend_upgrade(tmp_path):
    cache = tmp_path / "operator-check.json"
    operator_check.record_check(cache, {"simplicio-mapper": "0.23.1"})
    decision = operator_check.should_upgrade(cache, ttl_days=7, binaries=())
    assert decision["should_upgrade"] is False
    assert "within TTL" in decision["reason"]


def test_expired_check_recommends_upgrade(tmp_path):
    cache = tmp_path / "operator-check.json"
    now = time.time()
    operator_check.record_check(cache, {"simplicio-mapper": "0.23.1"}, now=now - 8 * 86400)
    decision = operator_check.should_upgrade(cache, ttl_days=7, binaries=(), now=now)
    assert decision["should_upgrade"] is True
    assert "ttl expired" in decision["reason"]


def test_configurable_ttl_changes_the_boundary(tmp_path):
    cache = tmp_path / "operator-check.json"
    now = time.time()
    operator_check.record_check(cache, {"simplicio-mapper": "0.23.1"}, now=now - 2 * 86400)
    # default 7-day TTL: 2 days old is still fresh
    assert operator_check.should_upgrade(cache, ttl_days=7, binaries=(), now=now)["should_upgrade"] is False
    # a 1-day TTL makes the same 2-day-old check stale
    assert operator_check.should_upgrade(cache, ttl_days=1, binaries=(), now=now)["should_upgrade"] is True


def test_corrupt_cache_is_treated_as_no_prior_check(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_OPERATOR_ALWAYS_LATEST", "0")
    cache = tmp_path / "operator-check.json"
    cache.write_text("{not json", encoding="utf-8")
    decision = operator_check.should_upgrade(cache, binaries=())
    assert decision["should_upgrade"] is True
    assert decision["reason"] == "no prior check recorded"


# --------------------------------------------------------------------------
# maybe_upgrade — the AC: within TTL, NEVER touches the network
# --------------------------------------------------------------------------

def test_maybe_upgrade_within_ttl_never_calls_upgrade_fn(tmp_path):
    """The core Etapa 6 AC: a preflight whose check is inside the TTL must not touch the
    network. We prove it by making the network path explode if it's ever invoked — the test
    only passes if that function is never called."""
    cache = tmp_path / "operator-check.json"
    operator_check.record_check(cache, {"simplicio-mapper": "0.23.1"})

    def _network_call_should_never_happen():
        raise AssertionError("upgrade_fn invoked despite a fresh TTL — network touched")

    result = operator_check.maybe_upgrade(
        cache, ttl_days=7, binaries=(), upgrade_fn=_network_call_should_never_happen,
    )
    assert result["should_upgrade"] is False
    assert result["upgraded"] is False
    assert result["upgrade_error"] is None


def test_maybe_upgrade_within_ttl_does_not_touch_subprocess(tmp_path, monkeypatch):
    """Same guarantee at the subprocess layer directly: with network mocked 'off' (raises if
    called), a within-TTL preflight must not attempt subprocess.run at all."""
    cache = tmp_path / "operator-check.json"
    operator_check.record_check(cache, {"simplicio-mapper": "0.23.1"})

    def _blocked_run(*_args, **_kwargs):
        raise AssertionError("subprocess.run invoked — network mocked disabled but was hit")

    monkeypatch.setattr(subprocess, "run", _blocked_run)
    result = operator_check.maybe_upgrade(cache, ttl_days=7, binaries=(),
                                         upgrade_fn=operator_check.run_pip_upgrade)
    assert result["upgraded"] is False
    assert result["should_upgrade"] is False


def test_default_upgrade_requests_both_direct_operator_packages(monkeypatch):
    captured = {}

    def _run(argv, **_kwargs):
        captured["argv"] = argv
        return subprocess.CompletedProcess(args=argv, returncode=0)

    monkeypatch.setattr(operator_check.subprocess, "run", _run)
    operator_check.run_pip_upgrade()
    assert "simplicio-cli" in captured["argv"]
    assert "simplicio-mapper" in captured["argv"]
    assert "simplicio-fast" not in captured["argv"]
    assert "simplicio-loop" in captured["argv"]


def test_maybe_upgrade_past_ttl_does_invoke_upgrade_fn(tmp_path):
    cache = tmp_path / "operator-check.json"
    now = time.time()
    operator_check.record_check(cache, {"simplicio-mapper": "0.23.1"}, now=now - 8 * 86400)
    calls = []

    def _fake_upgrade():
        calls.append(1)
        return subprocess.CompletedProcess(args=[], returncode=0)

    result = operator_check.maybe_upgrade(
        cache, ttl_days=7, binaries=(), upgrade_fn=_fake_upgrade, now=now,
    )
    assert calls == [1]
    assert result["upgraded"] is True
    # a successful upgrade re-records the check, resetting the TTL window
    refreshed = operator_check.should_upgrade(cache, ttl_days=7, binaries=(), now=now)
    assert refreshed["should_upgrade"] is False


def test_maybe_upgrade_missing_binary_invokes_upgrade_fn_even_within_ttl(tmp_path):
    cache = tmp_path / "operator-check.json"
    operator_check.record_check(cache, {"simplicio-mapper": "0.23.1"})
    calls = []

    def _fake_upgrade():
        calls.append(1)
        return subprocess.CompletedProcess(args=[], returncode=0)

    result = operator_check.maybe_upgrade(
        cache, ttl_days=7, binaries=("definitely-not-a-real-binary-xyz",),
        upgrade_fn=_fake_upgrade,
    )
    assert calls == [1]
    assert result["should_upgrade"] is True


def test_maybe_upgrade_records_check_even_on_upgrade_failure(tmp_path):
    """Best-effort/offline-safe: a failed upgrade attempt still updates last_checked so the
    loop doesn't hammer pip every single iteration until the TTL window naturally advances."""
    cache = tmp_path / "operator-check.json"
    now = time.time()
    operator_check.record_check(cache, {"simplicio-mapper": "0.23.1"}, now=now - 8 * 86400)

    def _failing_upgrade():
        raise OSError("network unreachable")

    result = operator_check.maybe_upgrade(
        cache, ttl_days=7, binaries=(), upgrade_fn=_failing_upgrade, now=now,
    )
    assert result["upgraded"] is False
    assert result["upgrade_error"] == "network unreachable"
    refreshed = operator_check.should_upgrade(cache, ttl_days=7, binaries=(), now=now)
    assert refreshed["should_upgrade"] is False


# --------------------------------------------------------------------------
# Per-run version pin
# --------------------------------------------------------------------------

def _scratchpad(tmp_path: Path) -> Path:
    path = tmp_path / "scratchpad.md"
    path.write_text(
        "---\niteration: 1\nmax_iterations: 20\ncompletion_promise: null\n"
        "evidence_required: true\nmode: converge\nstarted_at: \"2026-07-18T00:00:00Z\"\n"
        "---\n\ndo the thing\n",
        encoding="utf-8",
    )
    return path


def test_pin_versions_writes_into_frontmatter(tmp_path):
    scratchpad = _scratchpad(tmp_path)
    assert operator_check.pin_versions(
        scratchpad, {"simplicio-mapper": "0.23.1", "simplicio-dev-cli": "0.16.1"}
    )
    text = scratchpad.read_text(encoding="utf-8")
    assert "operator_versions:" in text
    assert text.startswith("---")
    # required fields survive untouched (contracts/loop-execution/v1/schema.json)
    assert "iteration: 1" in text
    assert "do the thing" in text


def test_pin_versions_is_write_once_per_run(tmp_path):
    scratchpad = _scratchpad(tmp_path)
    assert operator_check.pin_versions(scratchpad, {"simplicio-mapper": "0.23.1"})
    # a second pin attempt (e.g. a later iteration re-running preflight) must NOT overwrite
    assert operator_check.pin_versions(scratchpad, {"simplicio-mapper": "9.9.9"}) is False
    assert operator_check.read_pinned_versions(scratchpad) == {"simplicio-mapper": "0.23.1"}


def test_read_pinned_versions_returns_none_when_never_pinned(tmp_path):
    scratchpad = _scratchpad(tmp_path)
    assert operator_check.read_pinned_versions(scratchpad) is None


def test_check_pin_mismatch_is_empty_when_never_pinned(tmp_path):
    scratchpad = _scratchpad(tmp_path)
    assert operator_check.check_pin_mismatch(scratchpad, {"simplicio-mapper": "9.9.9"}) == []


def test_check_pin_mismatch_warns_without_upgrading(tmp_path):
    scratchpad = _scratchpad(tmp_path)
    operator_check.pin_versions(scratchpad, {"simplicio-mapper": "0.23.1"})
    warnings = operator_check.check_pin_mismatch(scratchpad, {"simplicio-mapper": "0.24.0"})
    assert len(warnings) == 1
    assert "0.23.1" in warnings[0]
    assert "0.24.0" in warnings[0]
    # the pin itself must be untouched by a mismatch check — never a silent upgrade
    assert operator_check.read_pinned_versions(scratchpad) == {"simplicio-mapper": "0.23.1"}


def test_check_pin_mismatch_is_silent_when_versions_agree(tmp_path):
    scratchpad = _scratchpad(tmp_path)
    operator_check.pin_versions(scratchpad, {"simplicio-mapper": "0.23.1"})
    assert operator_check.check_pin_mismatch(scratchpad, {"simplicio-mapper": "0.23.1"}) == []


def test_pin_versions_rejects_scratchpad_without_frontmatter(tmp_path):
    scratchpad = tmp_path / "scratchpad.md"
    scratchpad.write_text("no frontmatter here\n", encoding="utf-8")
    assert operator_check.pin_versions(scratchpad, {"simplicio-mapper": "0.23.1"}) is False


def test_pin_versions_preserves_scratchpad_bytes_outside_pin_line(tmp_path):
    scratchpad = _scratchpad(tmp_path)
    before_body = scratchpad.read_text(encoding="utf-8").split("---", 2)[2]
    operator_check.pin_versions(scratchpad, {"simplicio-mapper": "0.23.1"})
    after_body = scratchpad.read_text(encoding="utf-8").split("---", 2)[2]
    assert before_body == after_body


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def test_cli_should_upgrade_json(tmp_path, capsys):
    cache = tmp_path / "operator-check.json"
    assert operator_check.main(
        ["should-upgrade", "--cache", str(cache), "--json"]
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == operator_check.SCHEMA
    assert payload["should_upgrade"] is True


def test_cli_record_then_should_upgrade(tmp_path, capsys):
    cache = tmp_path / "operator-check.json"
    operator_check.main([
        "record", "--cache", str(cache), "--versions",
        json.dumps({"simplicio-mapper": "0.23.1"}),
    ])
    capsys.readouterr()
    assert operator_check.main([
        "should-upgrade", "--cache", str(cache), "--json", "--binary", "python3",
        "--ttl-days", "7",
    ]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["should_upgrade"] is False


def test_cli_pin_and_check_pin(tmp_path, capsys):
    scratchpad = _scratchpad(tmp_path)
    assert operator_check.main([
        "pin", "--scratchpad", str(scratchpad), "--versions",
        json.dumps({"simplicio-mapper": "0.23.1"}),
    ]) == 0
    capsys.readouterr()
    assert operator_check.main([
        "check-pin", "--scratchpad", str(scratchpad), "--versions",
        json.dumps({"simplicio-mapper": "0.24.0"}), "--json",
    ]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["warnings"]) == 1


def test_cli_help_exits_zero(capsys):
    with pytest.raises(SystemExit) as raised:
        operator_check.main(["--help"])
    assert raised.value.code == 0
    assert "should-upgrade" in capsys.readouterr().out


def test_selftest_passes():
    assert operator_check.main(["selftest"]) == 0
