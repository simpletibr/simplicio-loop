'''Regression tests for Dashboard remote access and Tailscale (#1807).

DOD Layer 1.3:
- Issue #1807: remote access over Tailscale returns 403 with no documented path.
'''
import http.client
import json
import subprocess
import sys
from pathlib import Path

import pytest

from simplicio_loop.dashboard import cli, server

TOKEN = 'remote-token-secret-98765'


def _request_host(port: int, host_header: str, token: str | None = None, origin: str | None = None) -> tuple[int, str]:
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
    headers = {'Host': host_header}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    if origin:
        headers['Origin'] = origin
    try:
        conn.request('GET', '/api/runs', headers=headers)
        resp = conn.getresponse()
        return resp.status, resp.read().decode('utf-8', errors='replace')
    finally:
        conn.close()


def test_tailscale_domain_allowed_with_valid_token(tmp_path):
    '''Issue #1807: domains ending with .ts.net are allowed when a valid token is provided.'''
    handle = server.start(repo_root=tmp_path, host='127.0.0.1', port=0, token=TOKEN)
    try:
        # With valid token and .ts.net Host header: status 200
        status, body = _request_host(handle.port, 'mybox.tailscale01.ts.net:8765', token=TOKEN)
        assert status == 200, f'Expected 200 for Tailscale host, got {status}: {body}'
        assert 'runs' in json.loads(body)

        # Host without port (e.g. through reverse proxy / Tailscale serve): status 200
        status2, body2 = _request_host(handle.port, 'mybox.tailscale01.ts.net', token=TOKEN)
        assert status2 == 200, f'Expected 200 for Tailscale host without port, got {status2}: {body2}'

        # Without token, authentication is still enforced: status 401
        status_unauth, _ = _request_host(handle.port, 'mybox.tailscale01.ts.net:8765', token=None)
        assert status_unauth == 401
    finally:
        handle.stop()


def test_allow_host_flag_permits_custom_hostname(tmp_path):
    '''Issue #1807: --allow-host <hostname> permits specified host header with valid token.'''
    allowed = ['custom.internal.corp', 'my-laptop:9999']
    handle = server.start(repo_root=tmp_path, host='127.0.0.1', port=0, token=TOKEN, allowed_hosts=allowed)
    try:
        # Configured host with valid token -> 200
        status, body = _request_host(handle.port, 'custom.internal.corp', token=TOKEN)
        assert status == 200, f'Expected 200 for allowed host, got {status}: {body}'

        status_with_port, body_p = _request_host(handle.port, 'custom.internal.corp:8765', token=TOKEN)
        assert status_with_port == 200, f'Expected 200 for allowed host with port, got {status_with_port}: {body_p}'

        # Unconfigured host -> 403
        status_forbidden, _ = _request_host(handle.port, 'unauthorized.corp', token=TOKEN)
        assert status_forbidden == 403
    finally:
        handle.stop()


def test_unauthorized_host_returns_403_with_explanatory_body(tmp_path):
    '''Issue #1807: Unauthorized host returns HTTP 403 with explanatory error message.'''
    handle = server.start(repo_root=tmp_path, host='127.0.0.1', port=0, token=TOKEN)
    try:
        status, body = _request_host(handle.port, 'attacker.evil.example', token=TOKEN)
        assert status == 403
        expected_msg = 'Host header not allowed; use 127.0.0.1, an SSH tunnel, or configure --allow-host'
        assert expected_msg in body, f'Expected explanatory message in 403 response, got: {body}'
        payload = json.loads(body)
        assert payload['error'] == expected_msg
    finally:
        handle.stop()


def test_tailscale_https_origin_allowed(tmp_path):
    '''Issue #1807: Tailscale HTTPS Origin (e.g. from Tailscale Serve/Funnel) is allowed.'''
    handle = server.start(repo_root=tmp_path, host='127.0.0.1', port=0, token=TOKEN)
    try:
        status, body = _request_host(
            handle.port,
            'node.ts.net',
            token=TOKEN,
            origin='https://node.ts.net'
        )
        assert status == 200, f'Expected 200 for HTTPS Origin matching Host, got {status}: {body}'
    finally:
        handle.stop()


def test_help_documents_remote_access(capsys):
    '''Issue #1807: --help must document remote access paths and --allow-host.'''
    with pytest.raises(SystemExit) as exc:
        cli.main(['--help'])
    assert exc.value.code == 0
    captured = capsys.readouterr().out
    assert '--allow-host' in captured
    assert 'Tailscale' in captured or 'remote access' in captured.lower()


def test_readme_documents_remote_access():
    '''Issue #1807: README.md must document remote access options.'''
    readme = Path(__file__).resolve().parents[2] / 'README.md'
    content = readme.read_text(encoding='utf-8')
    assert 'Tailscale' in content
    assert '--allow-host' in content
    assert 'SSH tunnel' in content
