import pytest

from simplicio_loop.runtime_effect_adapter import EffectRequest, RuntimeEffectAdapter, RuntimeEffectError


def request():
    return EffectRequest("C:/repo", "run:task:attempt", ("repo:src",), "lease-1", 3)


def test_standalone_profile_is_explicit_and_never_fakes_runtime_delivery():
    receipt = RuntimeEffectAdapter(profile="standalone").call(request(), "simplicio_status", {})
    assert receipt["status"] == "UNAVAILABLE"
    assert receipt["result"]["reason"] == "standalone_profile"
    assert receipt["executor"] == "standalone"


def test_execute_is_always_standalone_and_preserves_effect_identity():
    receipt = RuntimeEffectAdapter().execute(request(), ["pytest", "-q"])
    assert receipt["profile"] == "standalone"
    assert receipt["status"] == "UNAVAILABLE"
    assert receipt["lease_id"] == "lease-1"
    assert receipt["fencing_token"] == 3


def test_unsupported_profile_and_effect_identity_are_rejected():
    with pytest.raises(RuntimeEffectError, match="unsupported execution profile"):
        RuntimeEffectAdapter(profile="runtime-backed")
    with pytest.raises(RuntimeEffectError, match="lease"):
        EffectRequest("C:/repo", "key", ("repo:src",), "", 0)
