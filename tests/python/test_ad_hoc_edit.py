from simplicio.plan_compiler import derive_ad_hoc_edit


def test_contractless_replace_is_bounded_and_deterministic() -> None:
    payload = {
        "intent": "replace the greeting",
        "operations": [{"kind": "replace", "target": "src/app.py", "old": "hello", "new": "hi"}],
    }

    first = derive_ad_hoc_edit(payload)
    second = derive_ad_hoc_edit(dict(payload))

    assert first == second
    assert first["status"] == "derived"
    assert first["contract_origin"] == "derived"
    assert first["proposal"]["write_set"] == ["src/app.py"]
    assert first["proposal"]["effect"]["kind"] == "write"
    assert "lease" in first["proposal"]["runtime_binding_required"]
    assert first["verification_plan"]["acceptance_criteria_refs"] == ["edit-bounded"]


def test_contractless_operations_are_sorted_and_hash_preconditioned() -> None:
    payload = {
        "intent": "update two files",
        "targets": ["z.txt", "a.txt"],
        "operations": [
            {"kind": "replace", "target": "z.txt", "old": "z", "new": "Z"},
            {"kind": "delete", "target": "a.txt", "old": "a"},
        ],
    }

    result = derive_ad_hoc_edit(payload)

    assert result["status"] == "derived"
    assert result["proposal"]["write_set"] == ["a.txt", "z.txt"]
    assert result["proposal"]["preconditions"][0].startswith("content_sha256:a.txt:")


def test_contractless_traversal_is_blocked_with_stable_reason() -> None:
    result = derive_ad_hoc_edit(
        {"intent": "edit", "operations": [{"target": "../secret.txt", "old": "x", "new": "y"}]}
    )

    assert result["status"] == "blocked"
    assert result["reason_codes"] == ["AMBIGUOUS_TARGET"]


def test_contractless_missing_target_is_blocked_without_guessing() -> None:
    result = derive_ad_hoc_edit(
        {"intent": "edit", "operations": [{"old": "x", "new": "y"}]}
    )

    assert result["status"] == "blocked"
    assert result["reason_codes"] == ["AMBIGUOUS_TARGET"]


def test_contractless_missing_precondition_is_blocked() -> None:
    result = derive_ad_hoc_edit(
        {"intent": "edit", "operations": [{"target": "src/app.py", "new": "y"}]}
    )

    assert result["status"] == "blocked"
    assert result["reason_codes"] == ["PRECONDITION_REQUIRED"]
