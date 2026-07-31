from types import SimpleNamespace

from simplicio.execution_receipts import execution_mode_blocker


def test_incompatible_runtime_blocker_is_actionable_and_retryable():
    profile = SimpleNamespace(
        reason_code="INCOMPATIBLE_RUNTIME",
        runtime={
            "reason": "capability-handshake-missing",
            "capability": "simplicio.effect-transaction/v1",
            "capability_available": False,
            "version": "3.5.0",
        },
    )

    blocker = execution_mode_blocker(profile)

    assert blocker["retryable"] is True
    assert blocker["missing_capabilities"] == ["simplicio.effect-transaction/v1"]
    assert blocker["runtime_version"] == "3.5.0"
    assert blocker["compatible_dev_cli_version"] == ">=0.18.1"
    assert "runtime verify --json" in blocker["next_action"]


def test_unknown_execution_blocker_remains_fail_closed():
    profile = SimpleNamespace(reason_code="INTEGRATED_KILLED", runtime={})

    blocker = execution_mode_blocker(profile)

    assert blocker["retryable"] is False
    assert blocker["next_action"] is None
