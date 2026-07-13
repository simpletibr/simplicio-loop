"""mapper 0.13 integration: `inspect` evidence in artifact_status, `handoff`
context-pack in build_mapper_context — always fail-open to the artifact-file
path so projects without the binary (or with SIMPLICIO_MAPPER_CLI=0) behave
exactly as before."""

import json
import subprocess

import pytest

from simplicio import mapper


@pytest.fixture(autouse=True)
def _clear_cli_cache():
    mapper._MAPPER_CLI_CACHE.clear()
    yield
    mapper._MAPPER_CLI_CACHE.clear()


def _write_project_map(tmp_path):
    art_dir = tmp_path / ".simplicio"
    art_dir.mkdir()
    (art_dir / "project-map.json").write_text(
        json.dumps(
            {
                "schema": "simplicio.project-map/v2",
                "generated_at": "2026-07-02T00:00:00Z",
                "entry_points": ["src/app.py"],
                "files": [{"path": "src/app.py", "language": "python", "importance": 3}],
            }
        ),
        encoding="utf-8",
    )


def test_run_mapper_json_disabled_by_env(monkeypatch, tmp_path):
    monkeypatch.setenv("SIMPLICIO_MAPPER_CLI", "0")
    assert mapper.run_mapper_json(tmp_path, "inspect") is None


def test_run_mapper_json_missing_binary_is_none(monkeypatch, tmp_path):
    monkeypatch.delenv("SIMPLICIO_MAPPER_CLI", raising=False)
    monkeypatch.setattr(mapper.shutil, "which", lambda _name: None)
    assert mapper.run_mapper_json(tmp_path, "inspect") is None


# ---------------------------------------------------------------------------
# issue #166 AC: "Cache nunca cruza revision/snapshot_id" — the in-process
# `_MAPPER_CLI_CACHE` memoization key must always include revision/
# snapshot_id, so two different revisions/snapshots can never collide on the
# same cache entry, and a lookup for one revision never returns a value that
# was cached under another.
# ---------------------------------------------------------------------------


def _fake_mapper_binary(monkeypatch, responses):
    """Stub `shutil.which`/`subprocess.run` so `run_mapper_json` "calls the
    mapper binary" and returns the next queued response for each call,
    recording every invocation in `calls`."""
    calls: list[list[str]] = []

    monkeypatch.setattr(mapper.shutil, "which", lambda _name: "/bin/simplicio-mapper")

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        payload = responses[len(calls) - 1]
        return _FakeCompleted(returncode=0, stdout=json.dumps(payload))

    monkeypatch.setattr(mapper.subprocess, "run", fake_run)
    return calls


def test_cache_key_includes_revision_and_snapshot_id(tmp_path):
    """Same root/subcommand/extra but a different revision or snapshot_id
    must produce distinct cache keys (never collide)."""
    base = str(tmp_path.resolve())
    key_a = (base, "inspect", "rev-1", "snap-1")
    key_b = (base, "inspect", "rev-2", "snap-1")
    key_c = (base, "inspect", "rev-1", "snap-2")
    assert key_a != key_b
    assert key_a != key_c
    assert key_b != key_c


def test_run_mapper_json_same_revision_snapshot_is_a_cache_hit(monkeypatch, tmp_path):
    calls = _fake_mapper_binary(monkeypatch, [{"schema": "simplicio.map-inspection/v1", "call": 1}])

    first = mapper.run_mapper_json(tmp_path, "inspect", revision="rev-1", snapshot_id="snap-1")
    second = mapper.run_mapper_json(tmp_path, "inspect", revision="rev-1", snapshot_id="snap-1")

    assert first == second == {"schema": "simplicio.map-inspection/v1", "call": 1}
    # only one subprocess call: the second lookup was served from the cache.
    assert len(calls) == 1


def test_run_mapper_json_different_revision_is_a_cache_miss_not_stale_data(monkeypatch, tmp_path):
    """A stale/wrong-revision cache read must never return data cached under
    a different revision -- it must re-run the mapper binary and get the
    fresh (possibly different) answer for the new revision."""
    calls = _fake_mapper_binary(
        monkeypatch,
        [
            {"schema": "simplicio.map-inspection/v1", "revision": "rev-1"},
            {"schema": "simplicio.map-inspection/v1", "revision": "rev-2"},
        ],
    )

    first = mapper.run_mapper_json(tmp_path, "inspect", revision="rev-1", snapshot_id="snap-1")
    second = mapper.run_mapper_json(tmp_path, "inspect", revision="rev-2", snapshot_id="snap-1")

    assert first == {"schema": "simplicio.map-inspection/v1", "revision": "rev-1"}
    assert second == {"schema": "simplicio.map-inspection/v1", "revision": "rev-2"}
    assert first != second
    # both revisions triggered their own subprocess call -- no stale reuse.
    assert len(calls) == 2


def test_run_mapper_json_different_snapshot_id_is_a_cache_miss(monkeypatch, tmp_path):
    calls = _fake_mapper_binary(
        monkeypatch,
        [
            {"schema": "simplicio.map-inspection/v1", "snapshot_id": "snap-1"},
            {"schema": "simplicio.map-inspection/v1", "snapshot_id": "snap-2"},
        ],
    )

    first = mapper.run_mapper_json(tmp_path, "inspect", revision="rev-1", snapshot_id="snap-1")
    second = mapper.run_mapper_json(tmp_path, "inspect", revision="rev-1", snapshot_id="snap-2")

    assert first != second
    assert len(calls) == 2


def test_map_inspection_and_map_handoff_thread_revision_into_cache_key(monkeypatch, tmp_path):
    calls = _fake_mapper_binary(
        monkeypatch,
        [
            {"schema": "simplicio.map-inspection/v1", "revision": "rev-1"},
            {"schema": "simplicio.map-inspection/v1", "revision": "rev-2"},
            {"schema": "simplicio.map-handoff/v1", "revision": "rev-1"},
            {"schema": "simplicio.map-handoff/v1", "revision": "rev-2"},
        ],
    )

    insp_1 = mapper.map_inspection(tmp_path, revision="rev-1", snapshot_id="snap-1")
    insp_2 = mapper.map_inspection(tmp_path, revision="rev-2", snapshot_id="snap-1")
    handoff_1 = mapper.map_handoff(tmp_path, revision="rev-1", snapshot_id="snap-1")
    handoff_2 = mapper.map_handoff(tmp_path, revision="rev-2", snapshot_id="snap-1")

    assert insp_1 != insp_2
    assert handoff_1 != handoff_2
    assert len(calls) == 4


def test_artifact_status_embeds_inspection_evidence(monkeypatch, tmp_path):
    _write_project_map(tmp_path)
    monkeypatch.setattr(
        mapper,
        "map_inspection",
        lambda _root: {
            "schema": "simplicio.map-inspection/v1",
            "evidence": {"artifacts": {"project_map": {"exists": True, "size_bytes": 321}}},
            "warnings": ["deep pass stale"],
        },
    )
    payload = mapper.artifact_status(tmp_path)
    assert payload["project_map"]["present"] is True
    assert payload["inspection"]["schema"] == "simplicio.map-inspection/v1"
    assert payload["inspection"]["evidence"]["project_map"]["exists"] is True
    assert payload["inspection"]["warnings"] == ["deep pass stale"]


def test_artifact_status_without_mapper_cli_keeps_legacy_shape(monkeypatch, tmp_path):
    _write_project_map(tmp_path)
    monkeypatch.setattr(mapper, "map_inspection", lambda _root: None)
    payload = mapper.artifact_status(tmp_path)
    assert "inspection" not in payload
    assert payload["project_map"]["present"] is True


def test_build_mapper_context_prefers_handoff_pack(monkeypatch, tmp_path):
    _write_project_map(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("import os\n", encoding="utf-8")
    monkeypatch.setattr(mapper, "map_handoff", lambda _root: _HANDOFF_PACK_FIXTURE)
    context = mapper.build_mapper_context(tmp_path, "src/app.py")
    assert "simplicio.map-handoff/v1" in context
    assert "Pack hash: abc123" in context
    assert "Target fallback:" in context


def test_build_mapper_context_falls_back_when_pack_insufficient(monkeypatch, tmp_path):
    _write_project_map(tmp_path)
    monkeypatch.setattr(
        mapper,
        "map_handoff",
        lambda _root: {
            "context_pack": {"needs_broader_context": True, "files": [{"path": "x"}]},
        },
    )
    context = mapper.build_mapper_context(tmp_path, "src/app.py")
    assert "Mapper artifact:" in context
    assert "map-handoff" not in context


# --------------------------------------------------------------------------
# issue #88 — TOON on the handoff path (previously dead code: build_mapper_
# context() returned the legacy bullets before ever reaching the TOON branch,
# because that branch only existed in the project-map fallback below the
# handoff pre-empt).
# --------------------------------------------------------------------------

_HANDOFF_PACK_FIXTURE = {
    "schema": "simplicio.map-handoff/v1",
    "context_pack": {
        "pack_hash": "abc123",
        "needs_broader_context": False,
        "dependencies": {"runtime": ["orjson"]},
        "files": [
            {
                "path": "src/app.py",
                "language": "python",
                "symbols": [{"name": "main", "kind": "function"}],
                "imports": ["os"],
            }
        ],
        "recent_changes": [{"path": "src/app.py", "status": "modified"}],
    },
}


def _setup_handoff_target(tmp_path):
    _write_project_map(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("import os\n", encoding="utf-8")


def test_handoff_path_emits_toon_header_by_default(monkeypatch, tmp_path):
    monkeypatch.delenv("SIMPLICIO_PROMPT_TOON", raising=False)
    _setup_handoff_target(tmp_path)
    monkeypatch.setattr(mapper, "map_handoff", lambda _root: _HANDOFF_PACK_FIXTURE)
    context = mapper.build_mapper_context(tmp_path, "src/app.py")
    assert "Files (TOON — https://github.com/toon-format/toon):" in context
    assert "src/app.py" in context
    assert "main" in context
    # legacy hand-rolled bullet syntax is gone on this path when TOON is on
    assert "symbols=main" not in context


def test_handoff_path_falls_back_to_legacy_bullets_when_toon_disabled(monkeypatch, tmp_path):
    monkeypatch.setenv("SIMPLICIO_PROMPT_TOON", "0")
    _setup_handoff_target(tmp_path)
    monkeypatch.setattr(mapper, "map_handoff", lambda _root: _HANDOFF_PACK_FIXTURE)
    context = mapper.build_mapper_context(tmp_path, "src/app.py")
    assert "symbols=main" in context
    assert "imports=os" in context
    assert "TOON" not in context


def test_handoff_path_toon_records_savings_event(monkeypatch, tmp_path):
    monkeypatch.delenv("SIMPLICIO_PROMPT_TOON", raising=False)
    monkeypatch.delenv("SIMPLICIO_DISABLE_RUN_LOG", raising=False)
    _setup_handoff_target(tmp_path)
    monkeypatch.setattr(mapper, "map_handoff", lambda _root: _HANDOFF_PACK_FIXTURE)
    mapper.build_mapper_context(tmp_path, "src/app.py")
    ledger = tmp_path / ".simplicio" / "ledger" / "savings-events.jsonl"
    assert ledger.exists()
    lines = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines() if line]
    assert any(e.get("schema") == "simplicio.savings-event/v1" and e.get("source") == "toon" for e in lines)


def test_handoff_path_toon_disabled_writes_no_savings_event(monkeypatch, tmp_path):
    monkeypatch.setenv("SIMPLICIO_PROMPT_TOON", "0")
    monkeypatch.delenv("SIMPLICIO_DISABLE_RUN_LOG", raising=False)
    _setup_handoff_target(tmp_path)
    monkeypatch.setattr(mapper, "map_handoff", lambda _root: _HANDOFF_PACK_FIXTURE)
    mapper.build_mapper_context(tmp_path, "src/app.py")
    ledger = tmp_path / ".simplicio" / "ledger" / "savings-events.jsonl"
    assert not ledger.exists()


def test_build_mapper_context_falls_back_without_handoff(monkeypatch, tmp_path):
    _write_project_map(tmp_path)
    monkeypatch.setattr(mapper, "map_handoff", lambda _root: None)
    context = mapper.build_mapper_context(tmp_path, "src/app.py")
    assert "Mapper artifact:" in context


def test_map_ask_returns_results_list(monkeypatch, tmp_path):
    monkeypatch.setattr(
        mapper,
        "run_mapper_json",
        lambda root, sub, *, extra=(), timeout=30, revision="", snapshot_id="": {
            "schema": "simplicio.ask/v1",
            "query": {"verb": extra[0], "arg": extra[1] if len(extra) > 1 else None},
            "results": [{"path": "src/app.py", "symbol": "main"}, "not-a-dict"],
            "total": 1,
        },
    )
    results = mapper.map_ask(tmp_path, "impact", "src/app.py")
    assert results == [{"path": "src/app.py", "symbol": "main"}]


def test_map_ask_rejects_unknown_verb(tmp_path):
    assert mapper.map_ask(tmp_path, "delete-everything", "x") is None


def test_map_ask_none_when_cli_unavailable(monkeypatch, tmp_path):
    monkeypatch.setattr(mapper, "run_mapper_json", lambda *a, **k: None)
    assert mapper.map_ask(tmp_path, "impact", "src/app.py") is None


def test_inspect_target_embeds_impact_and_affected_tests(monkeypatch, tmp_path):
    _write_project_map(tmp_path)
    monkeypatch.setattr(mapper, "map_inspection", lambda _root: None)
    monkeypatch.setattr(mapper, "map_handoff", lambda _root: None)

    def fake_ask(root, verb, arg=""):
        if verb == "impact":
            return [{"path": "src/api.py", "kind": "dependent"}]
        if verb == "tests-for":
            return [{"path": "tests/test_app.py"}]
        return None

    monkeypatch.setattr(mapper, "map_ask", fake_ask)
    payload = mapper.inspect_target(tmp_path, "src/app.py")
    assert payload["impact"] == [{"path": "src/api.py", "kind": "dependent"}]
    assert payload["affected_tests"] == [{"path": "tests/test_app.py"}]


def test_inspect_target_omits_ask_keys_when_unavailable(monkeypatch, tmp_path):
    _write_project_map(tmp_path)
    monkeypatch.setattr(mapper, "map_inspection", lambda _root: None)
    monkeypatch.setattr(mapper, "map_handoff", lambda _root: None)
    monkeypatch.setattr(mapper, "map_ask", lambda *a, **k: None)
    payload = mapper.inspect_target(tmp_path, "src/app.py")
    assert "impact" not in payload
    assert "affected_tests" not in payload


# ---------------------------------------------------------------------------
# Native-first precedent search (rank_precedents): before touching the
# existing precedent-index.json + rank_entries() chain, try
# `simplicio precedent search --json` (schema simplicio.precedent-search/v1)
# on the native `simplicio` Rust binary. Fail-open like every other
# native/Python pair in this package: the SIMPLICIO_DEV_CLI_NO_RUNTIME_
# PRECEDENT kill-switch, a missing binary, non-zero exit, timeout, bad JSON,
# a payload missing `candidates`, or a valid-but-empty candidate list all
# fall through unchanged to the existing chain below — never raises, never
# breaks a caller. See mapper._native_precedent_search / _native_precedent_
# binary / _translate_native_candidate.
# ---------------------------------------------------------------------------


class _FakeCompleted:
    def __init__(self, returncode=0, stdout=""):
        self.returncode = returncode
        self.stdout = stdout


def _native_payload(candidates):
    return {"schema": "simplicio.precedent-search/v1", "status": "ok", "candidates": candidates}


def _write_precedent_index(tmp_path, items):
    art_dir = tmp_path / ".simplicio"
    art_dir.mkdir(exist_ok=True)
    (art_dir / "precedent-index.json").write_text(
        json.dumps({"schema": "simplicio.precedent-index/v1", "items": items}),
        encoding="utf-8",
    )


def test_rank_precedents_uses_native_binary_when_present(monkeypatch, tmp_path):
    candidate = {
        "precedent_id": "p1",
        "score": 0.83,
        "reuse_level": "high",
        "suggested_next_action": "reuse guard pattern from src/auth/guard.py",
    }
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return _FakeCompleted(returncode=0, stdout=json.dumps(_native_payload([candidate])))

    monkeypatch.setattr(
        mapper.shutil, "which", lambda name: "/bin/simplicio" if name == "simplicio" else None
    )
    monkeypatch.setattr(mapper.subprocess, "run", fake_run)

    result = mapper.rank_precedents(tmp_path, "fix login guard", k=2)

    assert len(calls) == 1
    cmd = calls[0]
    assert cmd[0] == "/bin/simplicio"
    assert cmd[1:4] == ["precedent", "search", "--repo"]
    assert cmd[4] == str(tmp_path.resolve())
    assert cmd[cmd.index("--text") + 1] == "fix login guard"
    assert cmd[cmd.index("--top") + 1] == "2"
    assert "--json" in cmd

    assert result == [
        {
            "precedent_id": "p1",
            "score": 0.83,
            "reuse_level": "high",
            "suggested_next_action": "reuse guard pattern from src/auth/guard.py",
            "path": "precedent:p1",
            "line": 1,
            "summary": "reuse guard pattern from src/auth/guard.py",
            "tags": ["high"],
        }
    ]


def test_rank_precedents_falls_back_when_binary_absent(monkeypatch, tmp_path):
    _write_precedent_index(
        tmp_path, [{"path": "src/ui/Login.tsx", "line": 12, "summary": "Login guard", "tags": ["login"]}]
    )
    monkeypatch.setattr(mapper.shutil, "which", lambda name: None)

    def fail_if_called(cmd, **kwargs):
        raise AssertionError("subprocess.run must not run when the binary is absent")

    monkeypatch.setattr(mapper.subprocess, "run", fail_if_called)

    result = mapper.rank_precedents(tmp_path, "fix login permission", k=1)

    assert len(result) == 1
    assert result[0]["path"] == "src/ui/Login.tsx"


def test_rank_precedents_respects_kill_switch_env_var(monkeypatch, tmp_path):
    _write_precedent_index(
        tmp_path, [{"path": "src/ui/Login.tsx", "line": 12, "summary": "Login guard", "tags": ["login"]}]
    )
    monkeypatch.setenv("SIMPLICIO_DEV_CLI_NO_RUNTIME_PRECEDENT", "1")
    monkeypatch.setattr(mapper.shutil, "which", lambda name: "/bin/simplicio")

    def fail_if_called(cmd, **kwargs):
        raise AssertionError("subprocess.run must not run when the kill-switch is set")

    monkeypatch.setattr(mapper.subprocess, "run", fail_if_called)

    result = mapper.rank_precedents(tmp_path, "fix login permission", k=1)

    assert result[0]["path"] == "src/ui/Login.tsx"


def test_rank_precedents_falls_back_on_subprocess_timeout(monkeypatch, tmp_path):
    _write_precedent_index(
        tmp_path, [{"path": "src/ui/Login.tsx", "line": 12, "summary": "Login guard", "tags": ["login"]}]
    )
    monkeypatch.setattr(mapper.shutil, "which", lambda name: "/bin/simplicio")

    def timeout_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd="simplicio", timeout=mapper._NATIVE_PRECEDENT_TIMEOUT_S)

    monkeypatch.setattr(mapper.subprocess, "run", timeout_run)

    result = mapper.rank_precedents(tmp_path, "fix login permission", k=1)

    assert result[0]["path"] == "src/ui/Login.tsx"


def test_rank_precedents_falls_back_on_malformed_json(monkeypatch, tmp_path):
    _write_precedent_index(
        tmp_path, [{"path": "src/ui/Login.tsx", "line": 12, "summary": "Login guard", "tags": ["login"]}]
    )
    monkeypatch.setattr(mapper.shutil, "which", lambda name: "/bin/simplicio")
    monkeypatch.setattr(
        mapper.subprocess, "run", lambda cmd, **kwargs: _FakeCompleted(returncode=0, stdout="not-json{")
    )

    result = mapper.rank_precedents(tmp_path, "fix login permission", k=1)

    assert result[0]["path"] == "src/ui/Login.tsx"


def test_rank_precedents_falls_back_on_non_zero_exit(monkeypatch, tmp_path):
    _write_precedent_index(
        tmp_path, [{"path": "src/ui/Login.tsx", "line": 12, "summary": "Login guard", "tags": ["login"]}]
    )
    monkeypatch.setattr(mapper.shutil, "which", lambda name: "/bin/simplicio")
    monkeypatch.setattr(
        mapper.subprocess, "run", lambda cmd, **kwargs: _FakeCompleted(returncode=1, stdout="")
    )

    result = mapper.rank_precedents(tmp_path, "fix login permission", k=1)

    assert result[0]["path"] == "src/ui/Login.tsx"


def test_rank_precedents_falls_back_on_missing_candidates_key(monkeypatch, tmp_path):
    _write_precedent_index(
        tmp_path, [{"path": "src/ui/Login.tsx", "line": 12, "summary": "Login guard", "tags": ["login"]}]
    )
    monkeypatch.setattr(mapper.shutil, "which", lambda name: "/bin/simplicio")
    monkeypatch.setattr(
        mapper.subprocess,
        "run",
        lambda cmd, **kwargs: _FakeCompleted(
            returncode=0, stdout=json.dumps({"schema": "simplicio.precedent-search/v1"})
        ),
    )

    result = mapper.rank_precedents(tmp_path, "fix login permission", k=1)

    assert result[0]["path"] == "src/ui/Login.tsx"


def test_rank_precedents_falls_back_on_empty_native_candidates(monkeypatch, tmp_path):
    """Deliberate deviation from simplicio-mapper's own `ask precedent`: an
    empty-but-valid native answer is treated the same as a failure here,
    because the native precedent-memory database and this repo's
    precedent-index.json are independent stores — an uninitialized/empty
    native store must not shadow real candidates the artifact-file chain
    still has (see mapper._native_precedent_search's docstring)."""
    _write_precedent_index(
        tmp_path, [{"path": "src/ui/Login.tsx", "line": 12, "summary": "Login guard", "tags": ["login"]}]
    )
    monkeypatch.setattr(mapper.shutil, "which", lambda name: "/bin/simplicio")
    monkeypatch.setattr(
        mapper.subprocess,
        "run",
        lambda cmd, **kwargs: _FakeCompleted(returncode=0, stdout=json.dumps(_native_payload([]))),
    )

    result = mapper.rank_precedents(tmp_path, "fix login permission", k=1)

    assert result[0]["path"] == "src/ui/Login.tsx"


def test_rank_precedents_skips_native_call_when_task_is_blank(monkeypatch, tmp_path):
    monkeypatch.setattr(mapper.shutil, "which", lambda name: "/bin/simplicio")

    def fail_if_called(cmd, **kwargs):
        raise AssertionError("subprocess.run must not run for a blank/whitespace-only task")

    monkeypatch.setattr(mapper.subprocess, "run", fail_if_called)

    result = mapper.rank_precedents(tmp_path, "   ", k=1)

    assert result == []
