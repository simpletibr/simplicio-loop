"""Teste de fumaca do Langfuse local (issue #1611), contra um servidor falso que tambem responde leituras.

O servidor falso imita o caminho de leitura do Langfuse v4: ``GET /api/public/v2/observations`` e
``GET /api/public/v3/scores`` (os endpoints ``/traces`` e ``/v2/scores`` saem do v4). A ingestao do
Langfuse e assincrona; ``hide_polls`` imita isso. Nada aqui toca a rede externa nem o Docker.
"""

from __future__ import annotations

import base64
import json
import re
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

import langfuse_smoke as smoke

REPO = Path(__file__).resolve().parents[1]
PK = "pk-lf-smoke-test-1611"
SK = "sk-lf-smoke-canary-1611"
TRACES_PATH = "/api/public/otel/v1/traces"
SCORES_PATH = "/api/public/scores"
OBSERVATIONS_PATH = "/api/public/v2/observations"
SCORES_READ_PATH = "/api/public/v3/scores"
EXPECTED_OBSERVATIONS = {
    "simplicio-loop run",
    "task T1",
    "generation T1",
    "gate tests",
    "gate lint",
}


class ReadableFake:
    """Langfuse v4 falso: guarda spans OTLP e scores e responde as leituras com os mesmos nomes do v4."""

    def __init__(
        self,
        *,
        hide_polls: int = 0,
        store_posts: bool = True,
        hide_scores: bool = False,
        ignore_filters: bool = False,
        flip: dict[str, bool] | None = None,
        generation_type: str = "GENERATION",
        secret_key: str = SK,
        read_status: int | None = None,
    ) -> None:
        self.read_status = read_status
        self.hide_polls = hide_polls
        self.store_posts = store_posts
        self.hide_scores = hide_scores
        self.ignore_filters = ignore_filters
        self.flip = flip or {}
        self.generation_type = generation_type
        self.secret_key = secret_key
        self.observations: list[dict[str, Any]] = []
        self.scores: list[dict[str, Any]] = []
        self.gets: list[dict[str, Any]] = []
        self.posts: list[dict[str, Any]] = []
        self.observation_polls = 0
        self._server: ThreadingHTTPServer | None = None

    @property
    def host(self) -> str:
        assert self._server is not None
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    @property
    def expected_auth(self) -> str:
        return "Basic " + base64.b64encode(f"{PK}:{self.secret_key}".encode()).decode()

    def preload_decoy(self, trace_id: str) -> None:
        """A complete trace of an older run: it must never satisfy the check of a new run."""
        for name in EXPECTED_OBSERVATIONS:
            kind = "GENERATION" if name.startswith("generation") else "SPAN"
            self.observations.append(
                {"id": f"decoy-{name}", "traceId": trace_id, "name": name, "type": kind}
            )
        for name, value in (("gate:tests", True), ("gate:lint", False)):
            self.scores.append(
                {"id": f"decoy-{name}", "traceId": trace_id, "name": name, "value": value}
            )

    def _store_spans(self, body: dict[str, Any]) -> None:
        for resource in body["resourceSpans"]:
            for scope in resource["scopeSpans"]:
                for span in scope["spans"]:
                    attrs = {
                        a["key"]: a["value"]["stringValue"] for a in span["attributes"]
                    }
                    kind = attrs.get("langfuse.observation.type", "span").upper()
                    if kind == "GENERATION":
                        kind = self.generation_type
                    self.observations.append(
                        {
                            "id": span["spanId"],
                            "traceId": span["traceId"],
                            "name": span["name"],
                            "type": kind,
                            "parentObservationId": span.get("parentSpanId"),
                        }
                    )

    def _store_score(self, body: dict[str, Any]) -> None:
        name = body["name"]
        value = self.flip.get(name, bool(body["value"]))
        self.scores.append(
            {
                "id": body["id"],
                "traceId": body["traceId"],
                "name": name,
                "value": value,
                "dataType": body["dataType"],
            }
        )

    def start(self) -> ReadableFake:
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args: Any) -> None:
                return

            def _reply(self, status: int, payload: Any) -> None:
                raw = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_POST(self) -> None:
                raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                auth_ok = self.headers.get("Authorization") == outer.expected_auth
                outer.posts.append({"path": self.path, "auth_ok": auth_ok})
                if not auth_ok:
                    return self._reply(401, {"message": "unauthorized"})
                body = json.loads(raw)
                if outer.store_posts and self.path == TRACES_PATH:
                    outer._store_spans(body)
                elif outer.store_posts and self.path == SCORES_PATH:
                    outer._store_score(body)
                self._reply(200, {"id": body.get("id", "")} if "id" in body else {})

            def do_GET(self) -> None:
                parts = urlsplit(self.path)
                query = {k: v[0] for k, v in parse_qs(parts.query).items()}
                auth_ok = self.headers.get("Authorization") == outer.expected_auth
                outer.gets.append({"path": parts.path, "query": query, "auth_ok": auth_ok})
                if not auth_ok:
                    return self._reply(401, {"message": "unauthorized"})
                trace = query.get("traceId")
                if outer.read_status is not None:
                    return self._reply(outer.read_status, {"message": "read refused"})
                if parts.path == OBSERVATIONS_PATH:
                    outer.observation_polls += 1
                    visible = outer.observation_polls > outer.hide_polls
                    rows = outer.observations if visible else []
                elif parts.path == SCORES_READ_PATH:
                    visible = (
                        outer.observation_polls > outer.hide_polls
                        and not outer.hide_scores
                    )
                    rows = outer.scores if visible else []
                else:
                    return self._reply(404, {"message": "not found"})
                if trace and not outer.ignore_filters:
                    rows = [r for r in rows if r["traceId"] == trace]
                self._reply(200, {"data": rows, "meta": {}})

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return self

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None


class Clock:
    """Relogio e sleep falsos: o polling roda ate o prazo sem esperar de verdade."""

    def __init__(self) -> None:
        self.t = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.t += seconds


@pytest.fixture
def make_fake():
    made: list[ReadableFake] = []

    def make(**kwargs: Any) -> ReadableFake:
        fake = ReadableFake(**kwargs).start()
        made.append(fake)
        return fake

    yield make
    for fake in made:
        fake.stop()


def _run(fake: ReadableFake, *, timeout: float = 30.0, poll: float = 2.0):
    clock = Clock()
    result = smoke.run_smoke(
        fake.host, PK, SK, timeout=timeout, poll=poll, sleep=clock.sleep, clock=clock
    )
    return result, clock


# --- caminho feliz --------------------------------------------------------------------------


def test_ok_when_trace_spans_and_gate_scores_arrive(make_fake):
    fake = make_fake()
    result, _ = _run(fake)
    assert result["status"] == "OK", result
    assert result["reason"] == "arrived"
    assert {o["name"] for o in fake.observations} == EXPECTED_OBSERVATIONS
    assert {s["name"]: s["value"] for s in fake.scores} == {
        "gate:tests": True,
        "gate:lint": False,
    }
    assert all(p["auth_ok"] for p in fake.posts) and len(fake.posts) == 3
    # the reads use Basic auth too and ask for the run's own trace
    assert fake.gets and all(g["auth_ok"] for g in fake.gets)
    assert {g["path"] for g in fake.gets} == {OBSERVATIONS_PATH, SCORES_READ_PATH}
    assert all(g["query"].get("traceId") == result["trace_id"] for g in fake.gets)
    assert "fromStartTime" in next(
        g for g in fake.gets if g["path"] == OBSERVATIONS_PATH
    )["query"]


def test_generation_observation_has_generation_type(make_fake):
    fake = make_fake(generation_type="SPAN")
    result, _ = _run(fake, timeout=6.0)
    assert result["status"] == "FAILED"
    assert result["missing"] == ["observation generation T1 (expected GENERATION, got SPAN)"]


def test_polls_until_asynchronous_ingestion_makes_the_data_visible(make_fake):
    fake = make_fake(hide_polls=3)
    result, clock = _run(fake)
    assert result["status"] == "OK", result
    assert fake.observation_polls == 4
    assert clock.sleeps == [2.0, 2.0, 2.0]
    assert result["waited_seconds"] == pytest.approx(6.0)


def test_each_run_uses_a_fresh_trace_id(make_fake):
    fake = make_fake()
    first, _ = _run(fake)
    second, _ = _run(fake)
    assert first["status"] == second["status"] == "OK"
    assert first["trace_id"] != second["trace_id"]
    assert first["run_id"] != second["run_id"]
    assert {o["traceId"] for o in fake.observations} == {
        first["trace_id"],
        second["trace_id"],
    }


# --- nunca finge sucesso --------------------------------------------------------------------


def test_data_that_never_arrives_is_failed_after_the_deadline(make_fake):
    fake = make_fake(store_posts=False)
    result, clock = _run(fake, timeout=10.0, poll=2.0)
    assert result["status"] == "FAILED"
    assert result["reason"] == "not_arrived"
    assert set(result["missing"]) >= {f"observation {n}" for n in EXPECTED_OBSERVATIONS}
    assert clock.t >= 10.0


def test_scores_that_never_arrive_are_failed_even_if_spans_did(make_fake):
    fake = make_fake(hide_scores=True)
    result, _ = _run(fake, timeout=6.0)
    assert result["status"] == "FAILED"
    assert result["reason"] == "not_arrived"
    assert sorted(result["missing"]) == ["score gate:lint", "score gate:tests"]


def test_a_gate_score_with_the_wrong_value_is_failed(make_fake):
    fake = make_fake(flip={"gate:lint": True})
    result, _ = _run(fake, timeout=6.0)
    assert result["status"] == "FAILED"
    assert result["missing"] == ["score gate:lint (expected False, got True)"]


def test_a_complete_trace_of_an_older_run_does_not_satisfy_the_check(make_fake):
    for ignore_filters in (False, True):
        fake = make_fake(store_posts=False, ignore_filters=ignore_filters)
        fake.preload_decoy("0" * 32)
        result, _ = _run(fake, timeout=6.0)
        assert result["status"] == "FAILED", (ignore_filters, result)
        assert result["reason"] == "not_arrived"


def test_server_without_the_v4_read_api_is_failed_at_once(make_fake):
    fake = make_fake(read_status=404)
    result, clock = _run(fake, timeout=60.0)
    assert result["status"] == "FAILED"
    assert result["reason"] == "read_refused"
    assert OBSERVATIONS_PATH in result["detail"] and "404" in result["detail"]
    assert clock.sleeps == []


def test_wrong_keys_are_failed_as_export_blocked_without_reading(make_fake):
    fake = make_fake(secret_key="sk-lf-other-secret-1611")
    result, _ = _run(fake)
    assert result["status"] == "FAILED"
    assert result["reason"] == "export_blocked"
    assert fake.gets == []
    assert SK not in json.dumps(result)


def test_unreachable_server_is_failed_not_ok():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    clock = Clock()
    result = smoke.run_smoke(
        f"http://127.0.0.1:{port}",
        PK,
        SK,
        timeout=5.0,
        poll=1.0,
        sleep=clock.sleep,
        clock=clock,
    )
    assert result["status"] == "FAILED"
    assert result["reason"] == "export_incomplete"
    assert SK not in json.dumps(result)


def test_cleartext_http_to_a_remote_host_is_refused_before_any_request():
    result = smoke.run_smoke("http://langfuse.example.test:3000", PK, SK)
    assert result["status"] == "FAILED"
    assert result["reason"] == "host_not_allowed"


# --- linha de comando: UNVERIFIED sai 0, FAILED sai 1 ----------------------------------------


def _main(capsys, argv: list[str], env: dict[str, str], which=lambda _name: None):
    code = smoke.main(argv, env=env, which=which)
    out = capsys.readouterr()
    lines = out.out.strip().splitlines()
    assert len(lines) == 1, out.out
    return code, json.loads(lines[0]), out


def test_no_docker_and_no_host_is_unverified_and_exits_zero(capsys):
    code, verdict, _ = _main(capsys, [], env={}, which=lambda _n: None)
    assert code == 0
    assert verdict["status"] == "UNVERIFIED"
    assert verdict["reason"] == "docker_not_installed"
    assert verdict["detail"]


def test_docker_present_but_no_host_is_unverified_with_its_own_reason(capsys):
    code, verdict, _ = _main(capsys, [], env={}, which=lambda _n: "/usr/bin/docker")
    assert code == 0
    assert verdict["status"] == "UNVERIFIED"
    assert verdict["reason"] == "langfuse_host_not_set"
    assert "LANGFUSE_HOST" in verdict["detail"]


def test_host_without_keys_is_unverified_and_exits_zero(capsys):
    env = {"LANGFUSE_HOST": "http://127.0.0.1:3000"}
    code, verdict, _ = _main(capsys, [], env=env)
    assert code == 0
    assert verdict["status"] == "UNVERIFIED"
    assert verdict["reason"] == "missing_credentials"


def test_cli_against_the_fake_prints_one_ok_line_and_leaks_no_key(make_fake, capsys):
    fake = make_fake()
    env = {
        "LANGFUSE_HOST": fake.host,
        "LANGFUSE_PUBLIC_KEY": PK,
        "LANGFUSE_SECRET_KEY": SK,
    }
    code, verdict, out = _main(capsys, ["--timeout", "5", "--poll", "0.05"], env=env)
    assert code == 0
    assert verdict["status"] == "OK"
    assert verdict["host"] == fake.host
    assert SK not in out.out + out.err


def test_cli_failure_exits_one_and_leaks_no_key(make_fake, capsys):
    fake = make_fake(store_posts=False)
    env = {
        "LANGFUSE_HOST": fake.host,
        "LANGFUSE_PUBLIC_KEY": PK,
        "LANGFUSE_SECRET_KEY": SK,
    }
    code, verdict, out = _main(capsys, ["--timeout", "0.3", "--poll", "0.05"], env=env)
    assert code == 1
    assert verdict["status"] == "FAILED"
    assert SK not in out.out + out.err


# --- sem dado do dono, sem chave, com a receita ----------------------------------------------


def test_fixture_and_script_carry_no_key_and_no_owner_data(tmp_path):
    source = (REPO / "scripts" / "langfuse_smoke.py").read_text(encoding="utf-8")
    assert not re.search(r"\b[ps]k-lf-[A-Za-z0-9]{6,}", source)
    fixture = tmp_path / "fixture"
    repo, run_dir = smoke.build_fixture(fixture, "smoke-run-x", 1_800_000_000.0)
    text = "".join(p.read_text(encoding="utf-8") for p in fixture.rglob("*") if p.is_file())
    assert "/smoke/fixture" in text
    for owner_marker in ("/root", "/projetos", "@gmail", "simpletibr", str(tmp_path)):
        assert owner_marker not in text, owner_marker
    assert repo.is_dir() and (run_dir / "events.jsonl").is_file()


def test_recipe_doc_has_the_steps_the_issue_asks_for():
    doc = (REPO / "docs" / "LANGFUSE_LOCAL.md").read_text(encoding="utf-8")
    assert "```mermaid" in doc
    for needle in (
        "git clone",
        "docker compose up",
        "docker compose down -v",
        "LANGFUSE_HOST",
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_SECRET_KEY",
        "langfuse_enabled",
        "scripts/langfuse_smoke.py",
        "UNVERIFIED",
    ):
        assert needle in doc, needle
    assert not re.search(r"\b[ps]k-lf-[0-9a-f]{8,}", doc), "doc must hold no key value"
