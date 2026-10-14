"""Exportador opt-in do loop para o Langfuse (issue #1595).

Mapeamento: run = trace, tarefa = span, etapa/gate = span filho, gate = score, tokens so com
MEASURED. Lote de 60 s com fila em disco. Redacao antes de sair. Testado contra o servidor falso
``tests/_langfuse_fake_server.py`` (sem rede externa).
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import pytest

from tests._langfuse_fake_server import SCORES_PATH, TRACES_PATH, FakeLangfuse

SECRET_TOKEN = "sk-lf-leak-canary-7f3a9c2e"  # must never appear in any payload
RUN_ID = "run-1595-fixture"
T0 = 1_800_000_000  # run start, unix seconds
NOW = 1_800_000_000 + 600.0  # well past any batch window


def _report(
    tokens_source: str = "cli_measured", title: str = "Corrigir login"
) -> dict[str, Any]:
    return {
        "schema": "simplicio.execution-report/v1",
        "owner": "simplicio-loop",
        "run_id": RUN_ID,
        "repo": "/work/repo",
        "status": "CLOSED",
        "started_at_unix": T0,
        "finished_at_unix": T0 + 120,
        "wall_ms": 120_000,
        "tasks": [
            {
                "task_id": "T1",
                "issue": "1595",
                "title": title,
                "wall_ms": 90_000,
                "tokens": {
                    "tokens_in": 1200,
                    "tokens_out": 340,
                    "source": tokens_source,
                },
                "outcome": "COMPLETE",
                "agent": {
                    "role": "executor",
                    "model": "claude-sonnet-5-5",
                    "effort": "high",
                },
                "operators_used": ["simplicio-dev-cli"],
            }
        ],
        "consolidated": {},
    }


def _event(
    seq: int, kind: str, payload: dict[str, Any], task_id: str | None = "T1"
) -> dict[str, Any]:
    return {
        "schema": "simplicio.dashboard-event/v1",
        "event_id": f"evt-{seq}",
        "seq": seq,
        "ts": f"2026-10-09T10:00:{seq:02d}Z",
        "run_id": RUN_ID,
        "task_id": task_id,
        "scope": "loop",
        "source": "runner",
        "kind": kind,
        "phase": "verify",
        "lane": None,
        "iteration": 1,
        "severity": "info",
        "payload": payload,
        "refs": [],
        "producer_version": "test",
    }


def _events() -> list[dict[str, Any]]:
    return [
        _event(
            1,
            "gate_evaluated",
            {"gate": "tests", "passed": True, "prompt": f"usa {SECRET_TOKEN}"},
        ),
        _event(2, "gate_evaluated", {"gate": "lint", "passed": False}),
        _event(
            3,
            "decision_requested",
            {"reason": "escalation", "auth": f"Bearer {SECRET_TOKEN}"},
        ),
        _event(4, "run_finished", {"outcome": "COMPLETE"}, task_id=None),
    ]


def _repo(tmp_path: Path, report: dict[str, Any] | None = None) -> Path:
    repo = tmp_path / "repo"
    reports = repo / ".simplicio-loop" / "runtime" / "execution-reports"
    reports.mkdir(parents=True)
    (reports / f"{RUN_ID}.json").write_text(
        json.dumps(report or _report()), encoding="utf-8"
    )
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "events.jsonl").write_text(
        "\n".join(json.dumps(e) for e in _events()) + "\n", encoding="utf-8"
    )
    # A login file exists next to the loop state; the exporter must never read or send it.
    (repo / ".simplicio-loop" / "login.json").write_text(
        json.dumps({"access_token": SECRET_TOKEN}), encoding="utf-8"
    )
    return repo


def _enabled(**overrides: Any):
    from simplicio_loop.langfuse_export.config import load_config

    table = {"langfuse_enabled": True, "langfuse_batch_seconds": 60, **overrides}
    return load_config(table, env={})


def _env(host: str, fake: FakeLangfuse) -> dict[str, str]:
    return {
        "LANGFUSE_HOST": host,
        "LANGFUSE_PUBLIC_KEY": fake.public_key,
        "LANGFUSE_SECRET_KEY": fake.secret_key,
    }


# --- AC1: desligado por padrao -------------------------------------------------------------


def test_disabled_by_default_imports_nothing_and_sends_nothing(tmp_path, monkeypatch):
    from simplicio_loop.langfuse_export.config import load_config
    from simplicio_loop.langfuse_export.exporter import export_once

    monkeypatch.delitem(
        sys.modules, "simplicio_loop.langfuse_export.transport", raising=False
    )
    repo = _repo(tmp_path)
    result = export_once(repo, config=load_config({}, env={}), now=NOW)

    assert result == {"status": "disabled"}
    assert "simplicio_loop.langfuse_export.transport" not in sys.modules
    assert not (repo / ".simplicio-loop" / "langfuse").exists()


def test_config_defaults_and_validation():
    from simplicio_loop.langfuse_export.config import load_config

    cfg = load_config({}, env={})
    assert cfg.enabled is False
    assert cfg.capture_content is False
    assert cfg.batch_seconds == 60
    assert cfg.host == "https://cloud.langfuse.com"
    with pytest.raises(ValueError):
        load_config({"langfuse_batch_seconds": 0}, env={})
    with pytest.raises(TypeError):
        load_config({"langfuse_capture_content": "yes"}, env={})


def test_langfuse_dir_is_under_dot_simplicio_loop(tmp_path):
    from simplicio_loop.langfuse_export.exporter import langfuse_dir

    assert langfuse_dir(tmp_path) == tmp_path / ".simplicio-loop" / "langfuse"


# --- ids and mapping ------------------------------------------------------------------------


def test_ids_are_deterministic_hex_of_otel_width():
    from simplicio_loop.langfuse_export.ids import span_id, trace_id

    assert re.fullmatch(r"[0-9a-f]{32}", trace_id(RUN_ID))
    assert re.fullmatch(r"[0-9a-f]{16}", span_id(RUN_ID, "T1"))
    assert trace_id(RUN_ID) == trace_id(RUN_ID)
    assert span_id(RUN_ID, "T1") != span_id(RUN_ID, "T2")


def test_plan_maps_run_task_gate_and_measured_generation():
    from simplicio_loop.langfuse_export.mapping import plan

    p = plan(_report(), _events(), capture_content=False)
    by_name = {s.name: s for s in p.spans}
    root = by_name["simplicio-loop run"]
    task = by_name["task T1"]
    assert root.parent_id is None and task.parent_id == root.span_id
    assert {s.trace_id for s in p.spans} == {root.trace_id}

    gate_spans = [s for s in p.spans if s.name.startswith("gate ")]
    assert sorted(s.name for s in gate_spans) == ["gate lint", "gate tests"]
    assert all(s.parent_id == task.span_id for s in gate_spans)

    gens = [
        s
        for s in p.spans
        if s.attributes.get("langfuse.observation.type") == "generation"
    ]
    assert len(gens) == 1
    assert gens[0].attributes["langfuse.observation.model.name"] == "claude-sonnet-5-5"
    assert json.loads(gens[0].attributes["langfuse.observation.usage_details"]) == {
        "input": 1200,
        "output": 340,
    }

    scores = {s["name"]: s for s in p.scores}
    assert (
        scores["gate:tests"]["value"] == 1
        and scores["gate:tests"]["dataType"] == "BOOLEAN"
    )
    assert scores["gate:lint"]["value"] == 0
    assert all(s["traceId"] == root.trace_id for s in p.scores)


def test_unmeasured_tokens_never_become_usage():
    from simplicio_loop.langfuse_export.mapping import plan

    p = plan(_report(tokens_source="absent"), _events(), capture_content=False)
    assert not any(
        "langfuse.observation.usage_details" in s.attributes for s in p.spans
    )
    task = next(s for s in p.spans if s.name == "task T1")
    assert task.attributes["simplicio.tokens.status"] == "UNVERIFIED"


def test_content_is_stripped_unless_capture_is_on():
    from simplicio_loop.langfuse_export.mapping import plan

    off = json.dumps(
        plan(_report(), _events(), capture_content=False).spans, default=str
    )
    assert "usa " not in off  # the prompt text of the gate event is not sent
    on = json.dumps(plan(_report(), _events(), capture_content=True).spans, default=str)
    assert "usa " in on


def test_secrets_never_reach_any_payload():
    from simplicio_loop.langfuse_export.mapping import plan
    from simplicio_loop.langfuse_export.otlp import encode
    from simplicio_loop.langfuse_export.redact import scrub

    report = _report(title=f"Corrigir login com {SECRET_TOKEN}")
    p = plan(report, _events(), capture_content=True)
    body = json.dumps(
        {
            "traces": encode(scrub(p.spans, [SECRET_TOKEN])),
            "scores": scrub(p.scores, [SECRET_TOKEN]),
        }
    )
    assert SECRET_TOKEN not in body
    assert "[REDACTED" in body


# --- queue, batch and idempotency -----------------------------------------------------------


def test_outbox_keeps_order_acks_and_dead_letters(tmp_path):
    from simplicio_loop.langfuse_export.queue import Outbox

    box = Outbox(tmp_path / "queue", tmp_path / "dead")
    box.enqueue("traces", {"resourceSpans": [1]})
    box.enqueue("scores", {"scores": [2]})
    names = [item.kind for item in box.pending()]
    assert names == ["traces", "scores"]

    first = box.pending()[0]
    assert box.fail(first, max_attempts=2) is False
    assert box.fail(first, max_attempts=2) is True  # second failure: dead letter
    assert [i.kind for i in box.pending()] == ["scores"]
    assert list((tmp_path / "dead").iterdir())

    box.ack(box.pending()[0])
    assert box.pending() == []


def test_flush_waits_for_the_batch_window(tmp_path):
    from simplicio_loop.langfuse_export.exporter import export_once

    sent: list[str] = []

    def send(kind, body):
        from simplicio_loop.langfuse_export.transport import Result

        sent.append(kind)
        return Result(ok=True, retryable=False, status=200, error="")

    repo = _repo(tmp_path)
    cfg = _enabled(langfuse_batch_seconds=60)
    env = {"LANGFUSE_PUBLIC_KEY": "pk", "LANGFUSE_SECRET_KEY": "sk"}
    export_once(
        repo, config=cfg, env=env, run_dir=tmp_path / "run", now=T0 + 1.0, send=send
    )
    assert sent == []  # first flush is inside the window: items wait on disk
    export_once(
        repo, config=cfg, env=env, run_dir=tmp_path / "run", now=T0 + 61.0, send=send
    )
    assert sent == ["traces", "scores", "scores"]  # one score per request: two gates


def test_resending_the_same_run_does_not_duplicate(tmp_path):
    from simplicio_loop.langfuse_export.exporter import export_once
    from simplicio_loop.langfuse_export.transport import Result

    accepted: list[tuple[str, Any]] = []

    def send(kind, body):
        accepted.append((kind, body))
        return Result(ok=True, retryable=False, status=200, error="")

    repo = _repo(tmp_path)
    cfg = _enabled()
    env = {"LANGFUSE_PUBLIC_KEY": "pk", "LANGFUSE_SECRET_KEY": "sk"}
    kwargs = {
        "config": cfg,
        "env": env,
        "run_dir": tmp_path / "run",
        "send": send,
        "force": True,
    }
    export_once(repo, now=NOW, **kwargs)
    first = len(accepted)
    assert first > 0
    again = export_once(repo, now=NOW + 1000, **kwargs)
    assert len(accepted) == first  # same content: nothing new is queued or sent
    assert again["enqueued"] == 0


def test_network_drop_queues_then_delivers_without_duplicates(tmp_path):
    from simplicio_loop.langfuse_export.exporter import export_once

    repo = _repo(tmp_path)
    cfg = _enabled()
    with FakeLangfuse() as fake:
        env = _env(fake.host, fake)
        fake.mode = "drop"
        down = export_once(
            repo, config=cfg, env=env, run_dir=tmp_path / "run", now=NOW, force=True
        )
        assert down["sent"] == 0 and down["pending"] >= 1
        assert (repo / ".simplicio-loop" / "langfuse" / "queue").exists()

        fake.mode = "ok"
        up = export_once(
            repo,
            config=cfg,
            env=env,
            run_dir=tmp_path / "run",
            now=NOW + 120,
            force=True,
        )
        assert up["pending"] == 0
        traces = fake.accepted(TRACES_PATH)
        assert len(traces) == 1
        span_ids = [
            s["spanId"]
            for req in traces
            for rs in req["body"]["resourceSpans"]
            for ss in rs["scopeSpans"]
            for s in ss["spans"]
        ]
        assert len(span_ids) == len(set(span_ids))


# --- transport and credentials --------------------------------------------------------------


def test_http_export_reaches_the_fake_server_with_trace_spans_generation_and_scores(
    tmp_path,
):
    from simplicio_loop.langfuse_export.exporter import export_once

    repo = _repo(tmp_path)
    cfg = _enabled()
    with FakeLangfuse() as fake:
        result = export_once(
            repo,
            config=cfg,
            env=_env(fake.host, fake),
            run_dir=tmp_path / "run",
            now=NOW,
            force=True,
        )
        assert result["pending"] == 0
        traces = fake.accepted(TRACES_PATH)
        assert traces and all(r["auth_ok"] for r in traces)
        assert traces[0]["headers"]["x-langfuse-ingestion-version"] == "4"
        spans = [
            s
            for req in traces
            for rs in req["body"]["resourceSpans"]
            for ss in rs["scopeSpans"]
            for s in ss["spans"]
        ]
        assert len({s["traceId"] for s in spans}) == 1  # one run = one trace
        types = [
            next(
                (
                    a["value"]["stringValue"]
                    for a in s["attributes"]
                    if a["key"] == "langfuse.observation.type"
                ),
                "span",
            )
            for s in spans
        ]
        assert types.count("generation") == 1
        scores = [r["body"] for r in fake.accepted(SCORES_PATH)]
        assert sorted(s["name"] for s in scores) == ["gate:lint", "gate:tests"]
        assert {s["traceId"] for s in scores} == {spans[0]["traceId"]}


def test_missing_credentials_block_when_enabled(tmp_path):
    from simplicio_loop.langfuse_export.exporter import export_once

    repo = _repo(tmp_path)
    result = export_once(
        repo, config=_enabled(), env={}, run_dir=tmp_path / "run", now=NOW, force=True
    )
    assert result == {"status": "blocked", "reason": "missing_credentials"}
    assert not (repo / ".simplicio-loop" / "langfuse" / "queue").exists()


def test_credentials_file_must_be_0600(tmp_path):
    from simplicio_loop.langfuse_export.config import (
        CredentialFileError,
        resolve_credentials,
    )

    d = tmp_path / "langfuse"
    d.mkdir()
    f = d / "credentials.json"
    f.write_text(json.dumps({"public_key": "pk", "secret_key": "sk"}), encoding="utf-8")
    os.chmod(f, 0o644)
    with pytest.raises(CredentialFileError):
        resolve_credentials({}, d)
    os.chmod(f, 0o600)
    creds = resolve_credentials({}, d)
    assert creds is not None and creds.public_key == "pk"


def test_env_credentials_win_over_the_file(tmp_path):
    from simplicio_loop.langfuse_export.config import resolve_credentials

    creds = resolve_credentials(
        {"LANGFUSE_PUBLIC_KEY": "pk-env", "LANGFUSE_SECRET_KEY": "sk-env"}, tmp_path
    )
    assert (creds.public_key, creds.secret_key) == ("pk-env", "sk-env")


def test_http_error_text_never_carries_the_secret(tmp_path):
    from simplicio_loop.langfuse_export.transport import HttpTransport

    with FakeLangfuse(public_key="pk-right", secret_key="sk-right") as fake:
        bad = HttpTransport(
            fake.host, public_key="pk-right", secret_key="sk-wrong", timeout=5
        )
        result = bad.send("traces", {"resourceSpans": []})
        assert result.ok is False and result.retryable is False and result.status == 401
        assert "sk-wrong" not in result.error and "sk-right" not in result.error


def test_pending_marks_survive_a_crash_during_flush(tmp_path):
    from simplicio_loop.langfuse_export.exporter import export_once, langfuse_dir

    def crashing_send(kind, body):
        raise RuntimeError("process died mid-flush")

    repo = _repo(tmp_path)
    cfg = _enabled()
    env = {"LANGFUSE_PUBLIC_KEY": "pk", "LANGFUSE_SECRET_KEY": "sk"}
    with pytest.raises(RuntimeError):
        export_once(
            repo,
            config=cfg,
            env=env,
            run_dir=tmp_path / "run",
            now=NOW,
            send=crashing_send,
            force=True,
        )
    ledger = json.loads(
        (langfuse_dir(repo) / "ledger.json").read_text(encoding="utf-8")
    )
    assert ledger["pending"], (
        "queued rows must be recorded before any send, or a restart queues them again"
    )


# --- review fixes: each test below fails on the previous behaviour -----------------------------


def _bodies(fake: FakeLangfuse) -> str:
    return json.dumps([r["body"] for r in fake.requests if r.get("body") is not None])


def _spans(body: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        s
        for rs in body["resourceSpans"]
        for ss in rs["scopeSpans"]
        for s in ss["spans"]
    ]


def _env_for(fake: FakeLangfuse, secret: str | None = None) -> dict[str, str]:
    return {
        "LANGFUSE_HOST": fake.host,
        "LANGFUSE_PUBLIC_KEY": fake.public_key,
        "LANGFUSE_SECRET_KEY": secret or fake.secret_key,
    }


def test_wrong_keys_block_and_keep_every_request(tmp_path):
    from simplicio_loop.langfuse_export.exporter import export_once, langfuse_dir

    repo = _repo(tmp_path)
    cfg = _enabled()
    with FakeLangfuse() as fake:
        env = _env_for(fake, secret="sk-WRONG-1595")
        first = export_once(
            repo, config=cfg, env=env, run_dir=tmp_path / "run", now=NOW, force=True
        )
        assert first["blocking"] == "http 401"
        assert first["dead"] == 0 and first["pending"] >= 2
        assert not (langfuse_dir(repo) / "dead").exists()
        ledger = json.loads(
            (langfuse_dir(repo) / "ledger.json").read_text(encoding="utf-8")
        )
        assert ledger["rejected"] == {}

        env = _env_for(fake)
        second = export_once(
            repo,
            config=cfg,
            env=env,
            run_dir=tmp_path / "run",
            now=NOW + 120,
            force=True,
        )
        assert second["pending"] == 0 and second["blocking"] is None
        assert len(fake.accepted(TRACES_PATH)) == 1


def test_server_errors_are_retried_until_exhausted_then_not_resent(tmp_path):
    from simplicio_loop.langfuse_export.exporter import export_once, langfuse_dir

    repo = _repo(tmp_path)
    cfg = _enabled()
    with FakeLangfuse() as fake:
        fake.mode = 500
        env = _env_for(fake)
        for round_no in range(8):
            export_once(
                repo,
                config=cfg,
                env=env,
                run_dir=tmp_path / "run",
                now=NOW + round_no,
                force=True,
            )
        dead = sorted((langfuse_dir(repo) / "dead").glob("*.json"))
        assert dead and dead[0].name.endswith(".traces.json")
        assert json.loads(dead[0].read_text(encoding="utf-8"))["attempts"] == 8
        again = export_once(
            repo,
            config=cfg,
            env=env,
            run_dir=tmp_path / "run",
            now=NOW + 100,
            force=True,
        )
        assert (
            again["enqueued"] == 0
        )  # same content: the exhausted request is not queued again


@pytest.mark.parametrize("code", [429, 503])
def test_429_and_5xx_count_an_attempt_and_stay_queued(tmp_path, code):
    from simplicio_loop.langfuse_export.exporter import export_once

    repo = _repo(tmp_path)
    cfg = _enabled()
    with FakeLangfuse() as fake:
        fake.mode = code
        down = export_once(
            repo,
            config=cfg,
            env=_env_for(fake),
            run_dir=tmp_path / "run",
            now=NOW,
            force=True,
        )
        assert down["dead"] == 0 and down["pending"] >= 1 and down["blocking"] is None
        fake.mode = "ok"
        up = export_once(
            repo,
            config=cfg,
            env=_env_for(fake),
            run_dir=tmp_path / "run",
            now=NOW + 60,
            force=True,
        )
        assert up["pending"] == 0


@pytest.mark.parametrize("code", [400, 413])
def test_permanent_rejection_is_dead_lettered_and_never_resent(tmp_path, code):
    from simplicio_loop.langfuse_export.exporter import export_once, langfuse_dir

    repo = _repo(tmp_path)
    cfg = _enabled()
    with FakeLangfuse() as fake:
        fake.mode = code
        first = export_once(
            repo,
            config=cfg,
            env=_env_for(fake),
            run_dir=tmp_path / "run",
            now=NOW,
            force=True,
        )
        assert first["dead"] >= 1 and first["blocking"] is None
        assert list((langfuse_dir(repo) / "dead").glob("*.json"))
        fake.mode = "ok"
        again = export_once(
            repo,
            config=cfg,
            env=_env_for(fake),
            run_dir=tmp_path / "run",
            now=NOW + 60,
            force=True,
        )
        assert again["enqueued"] == 0
        assert fake.accepted(TRACES_PATH) == []


def test_garbled_response_is_retried_not_a_crash(tmp_path):
    from simplicio_loop.langfuse_export.exporter import export_once

    repo = _repo(tmp_path)
    cfg = _enabled()
    with FakeLangfuse() as fake:
        fake.mode = "garbage"
        down = export_once(
            repo,
            config=cfg,
            env=_env_for(fake),
            run_dir=tmp_path / "run",
            now=NOW,
            force=True,
        )
        assert down["pending"] >= 1 and down["dead"] == 0
        fake.mode = "ok"
        up = export_once(
            repo,
            config=cfg,
            env=_env_for(fake),
            run_dir=tmp_path / "run",
            now=NOW + 60,
            force=True,
        )
        assert up["pending"] == 0


def test_nested_content_is_digested_when_capture_is_off(tmp_path):
    from simplicio_loop.langfuse_export.exporter import export_once

    repo = _repo(tmp_path)
    nested = _event(
        9, "decision_requested", {"agent_ctx": {"prompt": "NESTED-TEXT-7731"}}
    )
    (tmp_path / "run" / "events.jsonl").write_text(
        json.dumps(nested) + "\n", encoding="utf-8"
    )
    with FakeLangfuse() as fake:
        export_once(
            repo,
            config=_enabled(),
            env=_env_for(fake),
            run_dir=tmp_path / "run",
            now=NOW,
            force=True,
        )
        assert "NESTED-TEXT-7731" not in _bodies(fake)
    with FakeLangfuse() as fake:
        export_once(
            repo,
            config=_enabled(langfuse_capture_content=True),
            env=_env_for(fake),
            run_dir=tmp_path / "run",
            now=NOW,
            force=True,
        )
        assert "NESTED-TEXT-7731" in _bodies(fake)


def test_secret_and_login_canary_never_reach_the_server(tmp_path):
    from simplicio_loop.langfuse_export.exporter import export_once

    canary = "plainsecretcanary42"  # no provider pattern: only the exact-value scrub can remove it
    repo = _repo(tmp_path)
    (tmp_path / "run" / "events.jsonl").write_text(
        json.dumps(
            _event(
                7,
                "gate_evaluated",
                {"gate": "tests", "passed": True, "prompt": f"use {canary}"},
            )
        )
        + "\n",
        encoding="utf-8",
    )
    with FakeLangfuse(secret_key=canary) as fake:
        export_once(
            repo,
            config=_enabled(langfuse_capture_content=True),
            env=_env_for(fake, secret=canary),
            run_dir=tmp_path / "run",
            now=NOW,
            force=True,
        )
        bodies = _bodies(fake)
    assert canary not in bodies
    assert (
        SECRET_TOKEN not in bodies
    )  # login.json holds it; the exporter never reads that file
    assert "[REDACTED]" in bodies


def test_unverified_label_survives_redaction(tmp_path):
    from simplicio_loop.langfuse_export.exporter import export_once

    repo = _repo(tmp_path, report=_report(tokens_source="absent"))
    with FakeLangfuse() as fake:
        export_once(
            repo,
            config=_enabled(),
            env=_env_for(fake),
            run_dir=tmp_path / "run",
            now=NOW,
            force=True,
        )
        spans = _spans(fake.accepted(TRACES_PATH)[0]["body"])
    task = next(s for s in spans if s["name"] == "task T1")
    attrs = {a["key"]: a["value"]["stringValue"] for a in task["attributes"]}
    assert attrs["simplicio.tokens.status"] == "UNVERIFIED"


def test_raw_title_is_not_sent_only_its_fingerprint(tmp_path):
    from simplicio_loop.langfuse_export.exporter import export_once

    report = _report(title="Titulo confidencial")
    report["tasks"][0]["title_fingerprint"] = "fp-7731abc"
    repo = _repo(tmp_path, report=report)
    with FakeLangfuse() as fake:
        export_once(
            repo,
            config=_enabled(),
            env=_env_for(fake),
            run_dir=tmp_path / "run",
            now=NOW,
            force=True,
        )
        bodies = _bodies(fake)
    assert "Titulo confidencial" not in bodies
    assert "fp-7731abc" in bodies


def test_chunks_split_at_200_spans(tmp_path):
    from simplicio_loop.langfuse_export.exporter import export_once

    report = _report(tokens_source="absent")
    report["tasks"] = [
        {
            "task_id": f"T{i}",
            "title": f"t{i}",
            "wall_ms": 1,
            "tokens": {"source": "absent"},
            "outcome": "COMPLETE",
            "agent": {"role": "executor", "model": "m", "effort": "high"},
        }
        for i in range(250)
    ]
    repo = _repo(tmp_path, report=report)
    with FakeLangfuse() as fake:
        export_once(
            repo,
            config=_enabled(),
            env=_env_for(fake),
            run_dir=tmp_path / "run",
            now=NOW,
            force=True,
        )
        requests = fake.accepted(TRACES_PATH)
    assert len(requests) == 2
    # root + 250 tasks + 2 gate spans of T1 (the fixture events)
    assert sum(len(_spans(r["body"])) for r in requests) == 253


def test_each_report_becomes_its_own_trace(tmp_path):
    from simplicio_loop.langfuse_export.exporter import export_once

    repo = _repo(tmp_path)
    second = _report()
    second["run_id"] = "run-1595-second"
    (
        repo
        / ".simplicio-loop"
        / "runtime"
        / "execution-reports"
        / "run-1595-second.json"
    ).write_text(json.dumps(second), encoding="utf-8")
    with FakeLangfuse() as fake:
        export_once(
            repo,
            config=_enabled(),
            env=_env_for(fake),
            run_dir=tmp_path / "run",
            now=NOW,
            force=True,
        )
        trace_ids = {
            s["traceId"] for r in fake.accepted(TRACES_PATH) for s in _spans(r["body"])
        }
    assert len(trace_ids) == 2


def test_events_of_another_run_stay_out_of_this_trace():
    from simplicio_loop.langfuse_export.mapping import plan

    other = _event(9, "decision_requested", {"marker": "OTHER-RUN-MARK"})
    other["run_id"] = "run-OTHER"
    p = plan(_report(), _events() + [other], capture_content=False)
    assert not any("OTHER-RUN-MARK" in str(s.events) for s in p.spans)


def test_a_report_without_start_time_is_refused():
    from simplicio_loop.langfuse_export.mapping import plan

    report = _report()
    del report["started_at_unix"]
    with pytest.raises(ValueError):
        plan(report, _events(), capture_content=False)


def test_plain_http_is_refused_for_remote_hosts():
    from simplicio_loop.langfuse_export.config import check_host, load_config
    from simplicio_loop.langfuse_export.transport import HttpTransport

    with pytest.raises(ValueError):
        load_config({"langfuse_host": "http://langfuse.example.com"}, env={})
    with pytest.raises(ValueError):
        HttpTransport("http://langfuse.example.com", public_key="pk", secret_key="sk")
    assert check_host("https://langfuse.example.com") == "https://langfuse.example.com"
    assert check_host("http://127.0.0.1:3000") == "http://127.0.0.1:3000"
