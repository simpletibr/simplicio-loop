from __future__ import annotations

import json
from pathlib import Path

import pytest

from simplicio_fast.cross_repo import (
    MAX_BYTES,
    CrossRepoError,
    load_stack_lock,
    receipt_json,
    validate_stack_lock,
)
from simplicio_fast.cross_repo_cli import main


def _sha(char: str, length: int) -> str:
    return char * length


def _member(repo: str, index: int, *, optional: bool = False) -> dict[str, object]:
    return {
        "repository": f"wesleysimplicio/{repo}",
        "commit": _sha("0123456789abcdef"[index], 40),
        "version": f"{index + 1}.0.0",
        "optional": optional,
    }


def _lock(profile: str = "loop-standalone") -> dict[str, object]:
    members = [
        _member("simplicio-mapper", 0),
        _member("simplicio-fast", 1),
        _member("simplicio-dev-cli", 2),
        _member("simplicio-loop", 3),
    ]
    if profile == "runtime-backed":
        members.append(_member("simplicio-runtime", 4))
    repos = [item["repository"] for item in members]
    contracts = [
        {
            "schema": "simplicio.fast.handoff/v1",
            "owner": "wesleysimplicio/simplicio-fast",
            "producer": "wesleysimplicio/simplicio-mapper",
            "consumers": ["wesleysimplicio/simplicio-fast", "wesleysimplicio/simplicio-loop"],
            "digest": "sha256:" + _sha("a", 64),
        },
        {
            "schema": "simplicio.fast.changeset/v2",
            "owner": "wesleysimplicio/simplicio-dev-cli",
            "producer": "wesleysimplicio/simplicio-fast",
            "consumers": ["wesleysimplicio/simplicio-dev-cli", "wesleysimplicio/simplicio-loop"],
            "digest": "sha256:" + _sha("b", 64),
        },
    ]
    routes = [
        {"source": repos[0], "target": repos[1], "kind": "context", "authority": "derived-projection"},
        {"source": repos[1], "target": repos[2], "kind": "changeset", "authority": "source-mutation"},
        {"source": repos[2], "target": repos[3], "kind": "receipt", "authority": "completion"},
    ]
    if profile == "runtime-backed":
        routes.append({"source": repos[3], "target": repos[4], "kind": "effect", "authority": "effect"})
    return {
        "schema": "simplicio.stack-lock/v1",
        "profile": profile,
        "members": members,
        "contracts": contracts,
        "required_contracts": ["simplicio.fast.handoff/v1", "simplicio.fast.changeset/v2"],
        "routes": routes,
    }


def test_standalone_lock_is_ready_and_deterministic() -> None:
    payload = _lock()
    first = validate_stack_lock(payload)
    second = validate_stack_lock(json.loads(json.dumps(payload)))
    assert first == second
    assert first["status"] == "ready"
    assert first["evidence"]["effect_and_policy_owner"] is None
    assert first["stack_lock_digest"].startswith("sha256:")


def test_runtime_backed_requires_runtime_and_records_owner() -> None:
    receipt = validate_stack_lock(_lock("runtime-backed"))
    assert receipt["evidence"]["effect_and_policy_owner"] == "wesleysimplicio/simplicio-runtime"


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (lambda p: p.update(schema="wrong/v1"), "stack_lock_schema_invalid"),
        (lambda p: p["members"].pop(1), "required_member_missing"),
        (lambda p: p["members"][1].update(commit="master"), "member_commit_unpinned"),
        (lambda p: p["members"].append(dict(p["members"][0])), "duplicate_member_repository"),
        (lambda p: p["contracts"][0].update(digest="sha256:not-a-digest"), "contract_digest_invalid"),
        (lambda p: p["required_contracts"].append("missing/v1"), "required_contract_missing"),
    ],
)
def test_invalid_lock_fails_closed(mutation, reason: str) -> None:
    payload = _lock()
    mutation(payload)
    with pytest.raises(CrossRepoError) as error:
        validate_stack_lock(payload)
    assert error.value.reason_code == reason


def test_fast_cannot_become_mutation_or_effect_authority() -> None:
    payload = _lock()
    payload["routes"].append({
        "source": "wesleysimplicio/simplicio-fast",
        "target": "wesleysimplicio/simplicio-loop",
        "kind": "effect",
        "authority": "effect",
    })
    with pytest.raises(CrossRepoError, match="authority_owner_invalid"):
        validate_stack_lock(payload)


def test_runtime_is_not_hidden_in_standalone() -> None:
    payload = _lock()
    payload["members"].append(_member("simplicio-runtime", 4))
    with pytest.raises(CrossRepoError, match="runtime_route_forbidden"):
        validate_stack_lock(payload)


def test_json_loader_rejects_non_json_and_non_object() -> None:
    with pytest.raises(CrossRepoError, match="manifest_json_invalid"):
        load_stack_lock(b"NaN")
    with pytest.raises(CrossRepoError, match="manifest_invalid"):
        load_stack_lock(b"[]")


def test_receipt_serialization_is_canonical() -> None:
    receipt = validate_stack_lock(_lock())
    encoded = receipt_json(receipt)
    assert encoded.endswith("\n")
    assert json.loads(encoded)["schema"] == "simplicio.fast.cross-repo-receipt/v1"
    assert encoded == receipt_json(json.loads(encoded))


def test_cli_emits_blocked_receipt_for_invalid_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "lock.json"
    path.write_text(json.dumps({"schema": "wrong/v1"}), encoding="utf-8")
    assert main(["validate", "--file", str(path)]) == 2
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "blocked"
    assert output["reason_code"] == "stack_lock_schema_invalid"


def test_cli_emits_ready_receipt(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "lock.json"
    path.write_text(json.dumps(_lock()), encoding="utf-8")
    assert main(["validate", "--file", str(path), "--profile", "loop-standalone"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "ready"


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (lambda p: p.update(profile=""), "profile_invalid"),
        (lambda p: p.update(profile="unknown"), "profile_invalid"),
        (lambda p: p["members"].__setitem__(1, "not-a-member"), "member_invalid"),
        (lambda p: p["members"][1].update(repository="other/repo"), "repository_invalid"),
        (lambda p: p["members"][1].update(version=""), "member_version_invalid"),
        (lambda p: p["members"][1].update(artifact_digest="sha256:" + "c" * 64), None),
        (lambda p: p["members"][1].update(optional="yes"), "member_optional_invalid"),
        (lambda p: p["contracts"].__setitem__(0, "not-a-contract"), "contract_invalid"),
        (lambda p: p["contracts"][0].update(consumers=[]), "contract_consumers_empty"),
        (lambda p: p["contracts"][0].update(consumers=["other/repo"]), "repository_invalid"),
        (lambda p: p["routes"].__setitem__(0, "not-a-route"), "route_invalid"),
        (lambda p: p["routes"][0].update(target="other/repo"), "repository_invalid"),
        (lambda p: p["routes"].append(dict(p["routes"][0])), "duplicate_route"),
    ],
)
def test_nested_lock_boundaries_fail_closed(mutation, reason: str | None) -> None:
    payload = _lock()
    mutation(payload)
    if reason is None:
        receipt = validate_stack_lock(payload)
        assert receipt["members"][1]["artifact_digest"] == "sha256:" + "c" * 64
    else:
        with pytest.raises(CrossRepoError) as error:
            validate_stack_lock(payload)
        assert error.value.reason_code == reason


def test_profile_and_shape_boundaries_fail_closed() -> None:
    with pytest.raises(CrossRepoError, match="manifest_invalid"):
        validate_stack_lock([])  # type: ignore[arg-type]
    with pytest.raises(CrossRepoError, match="profile_mismatch"):
        validate_stack_lock(_lock(), profile="runtime-backed")
    for field, reason in (("members", "members_invalid"), ("contracts", "contracts_invalid"), ("routes", "routes_invalid"), ("required_contracts", "required_contracts_invalid")):
        payload = _lock()
        payload[field] = "not-a-list"
        with pytest.raises(CrossRepoError, match=reason):
            validate_stack_lock(payload)

    payload = _lock()
    payload["members"] = []
    with pytest.raises(CrossRepoError, match="members_empty"):
        validate_stack_lock(payload)

    payload = _lock("runtime-backed")
    payload["members"] = payload["members"][:-1]
    with pytest.raises(CrossRepoError, match="runtime_member_required"):
        validate_stack_lock(payload)

    payload = _lock()
    payload["members"].append(_member("simplicio-runtime", 4))
    with pytest.raises(CrossRepoError, match="runtime_route_forbidden"):
        validate_stack_lock(payload)


def test_contract_and_authority_integrity_boundaries_fail_closed() -> None:
    payload = _lock()
    payload["contracts"].append(dict(payload["contracts"][0]))
    with pytest.raises(CrossRepoError, match="duplicate_contract_schema"):
        validate_stack_lock(payload)

    payload = _lock()
    payload["contracts"][0]["consumers"] = ["wesleysimplicio/simplicio-code"]
    with pytest.raises(CrossRepoError, match="contract_member_missing"):
        validate_stack_lock(payload)

    payload = _lock()
    payload["routes"][0]["authority"] = "source-mutation"
    with pytest.raises(CrossRepoError, match="authority_owner_invalid"):
        validate_stack_lock(payload)

    payload = _lock()
    payload["routes"][0]["target"] = "wesleysimplicio/simplicio-code"
    with pytest.raises(CrossRepoError, match="route_member_missing"):
        validate_stack_lock(payload)


def test_canonical_serializer_rejects_unsupported_or_oversized_values() -> None:
    with pytest.raises(CrossRepoError, match="manifest_not_json"):
        receipt_json({"unsupported": object()})  # type: ignore[arg-type]
    with pytest.raises(CrossRepoError, match="manifest_size_limit"):
        receipt_json({"large": "x" * (MAX_BYTES + 1)})
