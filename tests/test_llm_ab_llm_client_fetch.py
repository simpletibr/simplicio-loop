"""TDD unit tests for bench/llm_ab/llm_client.py's real-cost fetch helpers:

``fetch_json`` (generic GET), ``fetch_model_pricing`` (public /models) and
``fetch_generation_stats`` (per-call /generation, needs a key, retries once
on 404). No real network call here -- ``urllib.request.urlopen`` is
monkeypatched with an in-memory fake response, so these stay pure unit
tests; the two real read-only GETs used to seed this feature were run
manually against the live API (see bench/llm_ab/README.md).
"""
import io
import json
import os
import sys
import urllib.error

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "bench", "llm_ab"))

import llm_client as lc  # noqa: E402


class FakeResponse(io.BytesIO):
    def __init__(self, body: bytes, status: int = 200):
        super().__init__(body)
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _install_keys(tmp_path, monkeypatch):
    keys_file = tmp_path / "keys.env"
    keys_file.write_text("OR_KEY_NORMAL=k-normal\nOR_KEY_SIMPLICIO=k-simplicio\n")
    monkeypatch.setenv(lc.KEYS_PATH_ENV, str(keys_file))


def test_fetch_json_returns_status_and_parsed_body(monkeypatch):
    body = json.dumps({"ok": True}).encode()
    monkeypatch.setattr(lc.urllib.request, "urlopen", lambda req, timeout: FakeResponse(body, 200))
    status, parsed, raw = lc.fetch_json("https://example.com/x")
    assert status == 200
    assert parsed == {"ok": True}
    assert raw == body.decode()


def test_fetch_json_http_error_returns_status_and_body(monkeypatch):
    def raise_http_error(req, timeout):
        raise urllib.error.HTTPError(
            "https://example.com/x", 404, "Not Found", {}, io.BytesIO(b'{"error":"nope"}')
        )

    monkeypatch.setattr(lc.urllib.request, "urlopen", raise_http_error)
    status, parsed, raw = lc.fetch_json("https://example.com/x")
    assert status == 404
    assert parsed == {"error": "nope"}


def test_fetch_json_network_error_returns_none_status(monkeypatch):
    def boom(req, timeout):
        raise OSError("network down")

    monkeypatch.setattr(lc.urllib.request, "urlopen", boom)
    status, parsed, raw = lc.fetch_json("https://example.com/x")
    assert status is None
    assert parsed is None
    assert "network down" in raw


def test_fetch_json_bad_json_body_parsed_is_none(monkeypatch):
    monkeypatch.setattr(lc.urllib.request, "urlopen", lambda req, timeout: FakeResponse(b"not json", 200))
    status, parsed, raw = lc.fetch_json("https://example.com/x")
    assert status == 200
    assert parsed is None
    assert raw == "not json"


def test_fetch_model_pricing_uses_public_models_endpoint(monkeypatch):
    body = json.dumps({
        "data": [{"id": lc.MODEL, "pricing": {"prompt": "0.00000014", "completion": "0.00000042"}}]
    }).encode()
    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        return FakeResponse(body, 200)

    monkeypatch.setattr(lc.urllib.request, "urlopen", fake_urlopen)
    pricing = lc.fetch_model_pricing()
    assert seen["url"] == lc.MODELS_URL
    assert pricing["available"] is True
    assert pricing["prompt"] == 0.00000014


def test_fetch_model_pricing_no_error_when_endpoint_down(monkeypatch):
    def boom(req, timeout):
        raise OSError("down")

    monkeypatch.setattr(lc.urllib.request, "urlopen", boom)
    pricing = lc.fetch_model_pricing()
    assert pricing["available"] is False


def test_fetch_generation_stats_sends_bearer_and_id(tmp_path, monkeypatch):
    _install_keys(tmp_path, monkeypatch)
    body = json.dumps({"data": {"total_cost": 0.0002}}).encode()
    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        seen["auth"] = req.get_header("Authorization")
        return FakeResponse(body, 200)

    monkeypatch.setattr(lc.urllib.request, "urlopen", fake_urlopen)
    stats = lc.fetch_generation_stats("normal", "gen-123")
    assert "gen-123" in seen["url"]
    assert seen["auth"] == "Bearer k-normal"
    assert stats["available"] is True
    assert stats["total_cost"] == 0.0002


def test_fetch_generation_stats_retries_once_after_404(tmp_path, monkeypatch):
    _install_keys(tmp_path, monkeypatch)
    calls = {"n": 0}
    sleeps = []

    def fake_urlopen(req, timeout):
        calls["n"] += 1
        if calls["n"] == 1:
            raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, io.BytesIO(b"{}"))
        return FakeResponse(json.dumps({"data": {"total_cost": 0.0001}}).encode(), 200)

    monkeypatch.setattr(lc.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(lc.time, "sleep", lambda s: sleeps.append(s))
    stats = lc.fetch_generation_stats("normal", "gen-slow", retry_delay=1.0)
    assert calls["n"] == 2
    assert sleeps == [1.0]
    assert stats["available"] is True


def test_fetch_generation_stats_gives_up_after_second_404(tmp_path, monkeypatch):
    _install_keys(tmp_path, monkeypatch)

    def always_404(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, io.BytesIO(b"{}"))

    monkeypatch.setattr(lc.urllib.request, "urlopen", always_404)
    monkeypatch.setattr(lc.time, "sleep", lambda s: None)
    stats = lc.fetch_generation_stats("normal", "gen-missing")
    assert stats == {"available": False}


def test_fetch_generation_stats_never_raises_key_into_stats(tmp_path, monkeypatch):
    _install_keys(tmp_path, monkeypatch)
    monkeypatch.setattr(lc.urllib.request, "urlopen", lambda req, timeout: FakeResponse(b"{}", 200))
    stats = lc.fetch_generation_stats("normal", "gen-1")
    assert "k-normal" not in json.dumps(stats)


@pytest.mark.parametrize("arm", ["normal", "simplicio"])
def test_fetch_generation_stats_uses_the_right_arm_key(tmp_path, monkeypatch, arm):
    _install_keys(tmp_path, monkeypatch)
    seen = {}

    def fake_urlopen(req, timeout):
        seen["auth"] = req.get_header("Authorization")
        return FakeResponse(b'{"data": {}}', 200)

    monkeypatch.setattr(lc.urllib.request, "urlopen", fake_urlopen)
    lc.fetch_generation_stats(arm, "gen-1")
    expected = "k-normal" if arm == "normal" else "k-simplicio"
    assert seen["auth"] == f"Bearer {expected}"
