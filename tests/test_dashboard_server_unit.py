'''Pure helper unit tests for the dashboard server (TDD red, no sockets).

The server module is imported inside each test so this file collects before it exists.
'''
import hmac
from pathlib import Path

import pytest

CSP = "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'"
TOKEN = 'correct-horse-battery-staple'
LOCAL = {'Host': '127.0.0.1:8765', 'Origin': 'http://127.0.0.1:8765'}


def _server():
    from simplicio_loop.dashboard import server
    return server


def test_token_is_compared_with_hmac_compare_digest(monkeypatch):
    server = _server()
    calls = []
    real = hmac.compare_digest

    def spy(a, b):
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr(hmac, 'compare_digest', spy)
    assert server.token_matches(TOKEN, TOKEN) is True
    assert server.token_matches('wrong', TOKEN) is False
    assert calls


@pytest.mark.parametrize('query, headers', [
    ({'t': TOKEN}, {}),
    ({}, {'Authorization': 'Bearer ' + TOKEN}),
    ({}, {'X-Simplicio-Token': TOKEN}),
])
def test_token_is_accepted_from_query_bearer_or_custom_header(query, headers):
    server = _server()
    assert server.extract_token(query, headers) == TOKEN


def test_missing_token_extracts_nothing():
    server = _server()
    assert not server.extract_token({}, {})


@pytest.mark.parametrize('query, headers', [
    ({'t': TOKEN}, {}),
    ({}, {'Authorization': 'Bearer ' + TOKEN}),
    ({}, {'X-Simplicio-Token': TOKEN}),
])
def test_each_token_source_passes_the_guard(query, headers):
    server = _server()
    assert server.guard('GET', '/api/runs', {**LOCAL, **headers}, query, TOKEN) == 200


@pytest.mark.parametrize('query, headers', [
    ({}, {}),
    ({'t': 'nope'}, {}),
    ({}, {'Authorization': 'Bearer nope'}),
    ({}, {'X-Simplicio-Token': 'nope'}),
])
def test_missing_or_wrong_token_is_401(query, headers):
    server = _server()
    assert server.guard('GET', '/api/runs', {**LOCAL, **headers}, query, TOKEN) == 401


def test_health_is_exempt_from_the_token():
    server = _server()
    assert server.guard('GET', '/api/health', dict(LOCAL), {}, TOKEN) == 200


@pytest.mark.parametrize('host', ['evil.example', '127.0.0.1.nip.io', 'localhost.evil.example'])
def test_foreign_host_is_403(host):
    server = _server()
    assert server.guard('GET', '/api/health', {'Host': host}, {}, TOKEN) == 403


@pytest.mark.parametrize('host', ['127.0.0.1:8765', 'localhost:8765'])
def test_loopback_hosts_are_allowed(host):
    server = _server()
    assert server.guard('GET', '/api/health', {'Host': host}, {}, TOKEN) == 200


def test_host_is_checked_before_origin_and_token():
    server = _server()
    headers = {'Host': 'evil.example', 'Origin': 'https://evil.example'}
    assert server.guard('GET', '/api/runs', headers, {}, TOKEN) == 403


def test_origin_is_checked_before_token():
    server = _server()
    foreign = {'Host': '127.0.0.1:8765', 'Origin': 'https://evil.example'}
    assert server.guard('GET', '/api/runs', foreign, {}, TOKEN) == 403
    assert server.guard('GET', '/api/runs', foreign, {'t': TOKEN}, TOKEN) == 403


def test_absent_origin_and_loopback_origin_are_allowed():
    server = _server()
    assert server.guard('GET', '/api/health', {'Host': '127.0.0.1:8765'}, {}, TOKEN) == 200
    assert server.guard('GET', '/api/health', dict(LOCAL), {}, TOKEN) == 200


def test_security_headers_are_exact():
    server = _server()
    headers = server.security_headers()
    assert headers['Content-Security-Policy'] == CSP
    assert headers['X-Content-Type-Options'] == 'nosniff'
    assert headers['Referrer-Policy'] == 'no-referrer'
    assert headers['Cache-Control'] == 'no-store'


def test_no_cors_allow_origin_header_anywhere():
    server = _server()
    assert not any(name.lower() == 'access-control-allow-origin' for name in server.security_headers())
    source = Path(server.__file__).read_text(encoding='utf-8')
    assert 'Access-Control-Allow-Origin' not in source
