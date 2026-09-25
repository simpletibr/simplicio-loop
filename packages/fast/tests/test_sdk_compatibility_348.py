import pytest

from simplicio_fast.compatibility import (
    CompatibilityError,
    compatibility_manifest,
    evaluate_compatibility,
)
from simplicio_fast.sdk import ProjectionSDK


def test_compatibility_manifest_is_machine_readable_and_fail_closed() -> None:
    manifest = compatibility_manifest()
    assert manifest["current_version"] == "1.0"
    assert manifest["rules"] == {
        "exact": "accept",
        "reader_upgrade_same_major": "accept_legacy_minor",
        "reader_downgrade_same_major": "reject_requires_migration",
        "future_major": "reject",
        "older_major": "reject",
    }
    assert manifest["rollback"] == "reuse_only_a_previously_validated_contract_version"


@pytest.mark.parametrize(
    ("producer", "consumer", "action", "reason"),
    [
        ("1.0", "1.0", "accept", "compatibility_exact"),
        ("v1.0", "1.1", "accept", "compatibility_upgrade_legacy_minor"),
        ("1.1", "1.0", "reject", "compatibility_downgrade_requires_migration"),
        ("2.0", "1.0", "reject", "compatibility_future_major"),
        ("1.0", "2.0", "reject", "compatibility_older_major"),
    ],
)
def test_upgrade_downgrade_and_major_behavior_is_deterministic(
    producer: str, consumer: str, action: str, reason: str
) -> None:
    decision = evaluate_compatibility(producer, consumer)
    assert decision.action == action
    assert decision.reason_code == reason
    assert decision.as_dict()["contract"] == "simplicio.fast.sdk/v1"


def test_invalid_version_has_stable_reason_code() -> None:
    with pytest.raises(CompatibilityError, match="compatibility_version_invalid"):
        evaluate_compatibility("1")


def test_sdk_capabilities_expose_compatibility_policy() -> None:
    compatibility = ProjectionSDK("repo").capabilities()["compatibility"]
    assert compatibility["schema"] == "simplicio.fast.sdk-compatibility/v1"
    assert compatibility["rules"]["future_major"] == "reject"
