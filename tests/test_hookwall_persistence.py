import pytest

from simplicio_loop.hookwall_persistence import (
    HookwallEffectLedger,
    MapperHookwallEffectLedger,
)


def test_legacy_hookwall_name_is_mapper_facade():
    assert issubclass(HookwallEffectLedger, MapperHookwallEffectLedger)


def test_path_only_legacy_hookwall_is_fail_closed():
    with pytest.raises(RuntimeError, match="LEGACY_HOOKWALL_READ_ONLY"):
        HookwallEffectLedger("hookwall.sqlite3")
