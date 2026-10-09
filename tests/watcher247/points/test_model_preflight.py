"""model_preflight (intake): the usable executor families, from exec_auth.check_all. It never blocks."""
import pytest

from simplicio_loop import exec_auth
from simplicio_loop.watcher247 import points


@pytest.fixture
def auth(monkeypatch):
    """Fake check_all: statuses by family; the families asked for are recorded."""
    asked = []
    statuses = {}

    async def check_all(families):
        asked.append(list(families))
        return [exec_auth.AuthCheckResult(f, statuses.get(f, "ok"), "" if statuses.get(f, "ok") == "ok" else "x")
                for f in families]

    monkeypatch.setattr(exec_auth, "check_all", check_all)
    monkeypatch.setenv("SIMPLICIO_EXECUTOR", "exec")
    monkeypatch.setenv("SIMPLICIO_EXEC_FAMILIES", "claude,codex,grok")
    return type("Auth", (), {"asked": asked, "statuses": statuses})


def test_registered_at_intake_and_not_blocking():
    [info] = [i for i in points.registered() if i.name == "model_preflight"]
    assert (info.stage, info.blocking, info.conditional) == ("intake", False, False)


def test_usable_families_are_the_evidence(point_contract, make_ctx, auth):
    auth.statuses.update({"codex": "login_missing", "grok": "cli_missing"})
    result = point_contract("model_preflight", make_ctx(), expect="ok")
    assert auth.asked == [["claude", "codex", "grok"]]
    assert result.evidence["usable"] == ["claude"]
    assert result.evidence["unusable"] == {"codex": "login_missing", "grok": "cli_missing"}


def test_no_usable_family_is_an_error_not_a_block(point_contract, make_ctx, auth):
    auth.statuses.update({"claude": "login_missing", "codex": "login_missing", "grok": "login_missing"})
    result = point_contract("model_preflight", make_ctx(), expect="error")
    assert result.reason_code == "no_usable_family"
    assert result.evidence["usable"] == []


def test_a_mode_without_exec_families_is_skipped(point_contract, make_ctx, auth, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_EXECUTOR", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    result = point_contract("model_preflight", make_ctx(), expect="skipped")
    assert result.reason_code == "no_exec_families"
    assert auth.asked == []


def test_an_invalid_executor_config_is_an_error(point_contract, make_ctx, auth, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_EXEC_FAMILIES", "nonsense")
    result = point_contract("model_preflight", make_ctx(), expect="error")
    assert result.reason_code == "executor_invalid"
