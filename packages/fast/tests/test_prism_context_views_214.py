from __future__ import annotations

import hashlib
import json

import pytest

from simplicio_fast.prism_context_views import (
    ContextAuthority,
    build_context_view,
    validate_context_view,
    ContextViewError,
)


def authority(*, roots=("a.py", "b.py")):
    return ContextAuthority(
        "loop-stage-agent",
        "fence-1",
        ("context:read",),
        roots,
    )


def test_context_view_deterministic_and_content_addressed():
    spans = [
        {"path": "b.py", "start": 1, "end": 2, "text": "bbb", "tokens": 10},
        {"path": "a.py", "start": 1, "end": 3, "text": "aaa", "tokens": 10},
    ]
    first = build_context_view(
        agent_id="agent-1",
        stage_id="execute",
        task_id="T1",
        generation_id="g1",
        spans=spans,
        budget_tokens=15,
        authority=authority(),
    )
    second = build_context_view(
        agent_id="agent-1",
        stage_id="execute",
        task_id="T1",
        generation_id="g1",
        spans=list(reversed(spans)),
        budget_tokens=15,
        authority=authority(),
    )
    assert first == second
    assert first["truncated"] is True
    assert (
        validate_context_view(first, authority=authority())["view_hash"]
        == first["view_hash"]
    )


def test_tamper_rejected():
    view = build_context_view(
        agent_id="a",
        stage_id="s",
        task_id="t",
        generation_id="g",
        spans=[{"path": "a.py", "start": 1, "end": 1, "text": "x", "tokens": 1}],
        authority=authority(roots=("a.py",)),
    )
    view["used_tokens"] = 999
    with pytest.raises(ContextViewError, match="tampered"):
        validate_context_view(view, authority=authority(roots=("a.py",)))


def test_authority_is_mandatory_and_cannot_be_embedded_by_attacker():
    kwargs = {
        "agent_id": "a",
        "stage_id": "s",
        "task_id": "t",
        "generation_id": "g",
        "spans": [{"path": "a.py", "text": "x", "tokens": 1}],
    }
    with pytest.raises(ContextViewError) as raised:
        build_context_view(**kwargs)
    assert raised.value.reason_code == "authority_required"

    view = build_context_view(**kwargs, authority=authority(roots=("a.py",)))
    with pytest.raises(ContextViewError) as raised:
        validate_context_view(view)
    assert raised.value.reason_code == "authority_required"


def test_path_escape_and_root_bypass_are_rejected():
    common = {
        "agent_id": "a",
        "stage_id": "s",
        "task_id": "t",
        "generation_id": "g",
    }
    with pytest.raises(ContextViewError) as escaped:
        build_context_view(
            **common,
            spans=[{"path": "../secret", "text": "x", "tokens": 1}],
            authority=authority(roots=("a.py",)),
        )
    assert escaped.value.reason_code == "path_escape"
    with pytest.raises(ContextViewError) as denied:
        build_context_view(
            **common,
            spans=[{"path": "private/key", "text": "x", "tokens": 1}],
            authority=authority(roots=("a.py",)),
        )
    assert denied.value.reason_code == "path_denied"


def test_rehashed_legacy_alias_cannot_override_deep_receipt():
    current_authority = authority(roots=("a.py",))
    view = build_context_view(
        agent_id="a",
        stage_id="s",
        task_id="t",
        generation_id="g",
        spans=[{"path": "a.py", "start": 1, "end": 2, "text": "x", "tokens": 1}],
        authority=current_authority,
    )
    view["spans"][0]["start"] = -999
    unsigned = {key: value for key, value in view.items() if key != "view_hash"}
    view["view_hash"] = hashlib.sha256(
        json.dumps(
            unsigned,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()
    with pytest.raises(ContextViewError) as raised:
        validate_context_view(view, authority=current_authority)
    assert raised.value.reason_code == "compatibility_binding_invalid"
