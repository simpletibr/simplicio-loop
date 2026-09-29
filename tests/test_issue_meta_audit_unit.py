import io
import json
import urllib.error
from unittest.mock import patch

from scripts import issue_meta_audit as audit


def compliant_issue(number=1):
    sections = {
        "Contexto e problema": "Falha de orquestração.",
        "Objetivo": "Eliminar 100% das perdas.",
        "Fora de escopo": "Interface gráfica.",
        "Entradas, saídas e contratos": "Entrada evento; saída receipt.",
        "Dependências e ordem": "Depende de acme/core#2.",
        "Passo a passo implementável": "1. Implementar.\n2. Verificar.",
        "Fluxo de testes": "Caminho principal, retry, replay, checkpoint, concorrência, cancelamento, crash, idempotência, backpressure, custo, recuperação; falha, timeout e entrada inválida.",
        "Critérios de aceite verificáveis": "100% dos casos passam em <= 10 ms.",
        "Evidências obrigatórias": "PR e commit, logs, evidências, benchmark 8 ms.",
        "Riscos, rollback e decisão de encerramento": "Rollback para versão anterior.",
    }
    return {"number": number, "title": "[P1][queue] test", "state": "open",
            "created_at": f"2026-01-{number:02d}T00:00:00Z", "labels": [{"name": "risk:high"}],
            "body": "\n\n".join(f"## {key}\n{value}" for key, value in sections.items())}


def test_compliant_issue_is_ready_and_extracts_reference():
    result = audit.audit_issue(compliant_issue())
    assert result["decision"] == "READY"
    assert result["findings"] == []
    assert result["references"] == [2]


def test_missing_contract_is_fail_closed_without_leaking_secret():
    issue = {"number": 9, "title": "vague", "state": "closed", "created_at": "2020", "labels": [],
             "body": "## Objetivo\nmelhorar\npassword=" + "supersecretvalue"}
    result = audit.audit_issue(issue)
    assert result["decision"] == "NEEDS-IMPLEMENTATION"
    assert "failed_check:no_secret_or_pii_examples" in result["findings"]
    assert "contexto e problema" in result["missing_sections"]


class Response:
    def __init__(self, payload, link=""):
        self.payload = payload
        self.headers = {"Link": link}

    def read(self):
        return json.dumps(self.payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None


def test_fetch_retries_and_follows_link_without_auth_in_error():
    calls = []
    responses = [urllib.error.HTTPError("https://x?token=" + "ghp_" + "abcdefghijklmnopqrstuvwxyz", 503, "bad", {}, io.BytesIO()),
                 Response([compliant_issue(1)], '<https://next>; rel="next"'), Response([compliant_issue(2)])]

    def opener(request, timeout):
        calls.append((request.full_url, timeout))
        value = responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    items, errors = audit.fetch_issues("acme/repo", opener=opener, sleep=lambda _: None)
    assert [item["number"] for item in items] == [1, 2]
    assert errors == []
    assert calls[-1][0] == "https://next"


def test_report_excludes_prs_orders_oldest_and_records_counts():
    newer, older = compliant_issue(2), compliant_issue(1)
    newer["pull_request"] = {"url": "x"}
    report = audit.build_report([newer, older], repo="acme/repo")
    assert report["summary"] == {
        "accessible_records": 2, "issues": 1, "pull_requests_excluded": 1,
        "conforming": 1, "conformance_percent": 100.0, "by_state": {"open": 1},
        "by_label": {"risk:high": 1},
        "grouping": {"component": {"queue": 1}, "risk": {"high": 1}, "priority": {"P1": 1}},
        "fetch_complete": True, "ready": True,
    }


def test_fetch_max_pages_and_empty_inventory_are_not_ready():
    response = Response([compliant_issue()], '<https://next>; rel="next"')
    _, errors = audit.fetch_issues("acme/repo", max_pages=1, opener=lambda *_args, **_kwargs: response)
    assert errors == ["pagination exceeded max-pages=1"]
    assert not audit.build_report([], repo="acme/repo")["summary"]["ready"]


def test_fetch_rejects_permanent_http_and_non_list_payload():
    def denied(*_args, **_kwargs):
        raise urllib.error.HTTPError("https://x", 404, "missing", {}, io.BytesIO())

    assert audit.fetch_issues("x/y", opener=denied)[1] == ["fetch page 1: HTTP 404"]
    assert audit.fetch_issues("x/y", opener=lambda *_args, **_kwargs: Response({"bad": True}))[1] == [
        "fetch page 1: response is not a list"
    ]


def test_fetch_exhausts_network_retries_and_sanitizes_token():
    sleeps = []

    def unavailable(*_args, **_kwargs):
        raise OSError("failed " + "ghp_" + "abcdefghijklmnopqrstuvwxyz")

    _, errors = audit.fetch_issues("x/y", opener=unavailable, sleep=sleeps.append)
    assert sleeps == [1, 2, 4]
    assert errors == ["fetch page 1: failed [REDACTED]"]


def test_fetch_sends_optional_token_without_printing_it():
    captured = []

    def opener(request, **_kwargs):
        captured.append(request.get_header("Authorization"))
        return Response([])

    with patch.dict("os.environ", {"GH_TOKEN": "private-token"}, clear=True):
        assert audit.fetch_issues("x/y", opener=opener) == ([], [])
    assert captured == ["Bearer private-token"]
