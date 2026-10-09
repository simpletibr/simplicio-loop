"""model_preflight (intake): the usable executor families, taken from the result of host_mode.choose (no re-probe).

The tick calls choose once per tick, which probes every family; the point only reads that result. It never blocks.
"""
import asyncio

import pytest

from simplicio_loop import exec_auth
from simplicio_loop.watcher247 import host_mode, points

ENV = {"SIMPLICIO_EXECUTOR": "exec", "SIMPLICIO_EXEC_FAMILIES": "claude,codex,grok"}


@pytest.fixture
def auth(monkeypatch):
    """Fake check_all (statuses by family, calls counted) and a host_mode with no earlier auth result."""
    statuses, calls = {}, []

    async def check_all(families):
        calls.append(list(families))
        return [exec_auth.AuthCheckResult(f, statuses.get(f, "ok"), "" if statuses.get(f, "ok") == "ok" else "x")
                for f in families]

    monkeypatch.setattr(exec_auth, "check_all", check_all)
    monkeypatch.setattr(host_mode, "_LAST_AUTH", [])
    return type("Auth", (), {"calls": calls, "statuses": statuses,
                             "choose": staticmethod(lambda env=ENV: asyncio.run(host_mode.choose(dict(env))))})


def test_registered_at_intake_and_not_blocking():
    [info] = [i for i in points.registered() if i.name == "model_preflight"]
    assert (info.stage, info.blocking, info.conditional) == ("intake", False, False)


def test_usable_families_are_those_of_the_choose_result(point_contract, make_ctx, auth):
    auth.statuses.update({"codex": "login_missing", "grok": "cli_missing"})
    auth.choose()
    result = point_contract("model_preflight", make_ctx(family="claude"), expect="ok")
    assert result.evidence["usable"] == ["claude"]
    assert result.evidence["unusable"] == {"codex": "login_missing", "grok": "cli_missing"}


def test_the_point_never_probes_again(point_contract, make_ctx, auth):
    auth.choose()
    point_contract("model_preflight", make_ctx(), expect="ok")
    point_contract("model_preflight", make_ctx(), expect="ok")
    assert auth.calls == [["claude", "codex", "grok"]]  # only choose probed


def test_no_usable_family_is_an_error_not_a_block(point_contract, make_ctx, auth):
    auth.statuses.update({"claude": "login_missing", "codex": "login_missing", "grok": "login_missing"})
    auth.choose()
    result = point_contract("model_preflight", make_ctx(), expect="error")
    assert result.reason_code == "no_usable_family"
    assert result.evidence["usable"] == []


def test_without_a_choose_result_it_is_skipped(point_contract, make_ctx, auth):
    result = point_contract("model_preflight", make_ctx(), expect="skipped")
    assert result.reason_code == "no_auth_result"
    assert auth.calls == []


def test_the_evidence_names_the_family_the_tick_picked(point_contract, make_ctx, auth):
    auth.choose()
    result = point_contract("model_preflight", make_ctx(family="claude"), expect="ok")
    assert result.evidence["selected"] == "claude"
