"""Unit tests closing coverage gaps in small, previously-0%-covered modules:
``cache_cli.py`` (the `simplicio-py cache` subcommand), ``utils/cache.py``
(disk-memoization decorator), ``utils/http_client.py`` (shared httpx
client), ``provider_cache_receipt.py`` (cache-receipt bookkeeping helpers),
and the ``file``/``test`` subcommand dispatchers in ``commands/file.py`` /
``commands/test.py``. These are thin, self-contained modules with no
existing test file (per the coverage report: 0% line coverage each).
"""

from __future__ import annotations

import argparse
import json

from simplicio import cache_cli
from simplicio.commands import file as file_cmd
from simplicio.commands import test as test_cmd
from simplicio.utils import cache as utils_cache
from simplicio.utils import http_client


def ns(**kwargs) -> argparse.Namespace:
    return argparse.Namespace(**kwargs)


# --------------------------------------------------------------------------- #
# cache_cli.py
# --------------------------------------------------------------------------- #


def test_cache_cli_stats_json(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SIMPLICIO_CACHE_DIR", str(tmp_path))
    code = cache_cli.main(["stats", "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["entries"] == 0
    assert payload["size_bytes"] == 0
    assert payload["root"] == str(tmp_path)
    assert payload["enabled"] is True


def test_cache_cli_stats_text(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SIMPLICIO_CACHE_DIR", str(tmp_path))
    code = cache_cli.main(["stats"])
    assert code == 0
    out = capsys.readouterr().out
    assert "simplicio-py cache stats" in out
    assert "entries" in out


def test_cache_cli_clear_without_force_refuses(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SIMPLICIO_CACHE_DIR", str(tmp_path))
    code = cache_cli.main(["clear"])
    assert code == 2
    assert "refusing to clear without --force" in capsys.readouterr().err


def test_cache_cli_clear_with_force(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SIMPLICIO_CACHE_DIR", str(tmp_path))
    code = cache_cli.main(["clear", "--force"])
    assert code == 0
    assert "cleared" in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# utils/cache.py
# --------------------------------------------------------------------------- #


def test_memoize_disk_caches_across_calls(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_CACHE_DIR", str(tmp_path))
    utils_cache._caches.clear()
    calls = []

    @utils_cache.memoize_disk(namespace="test_ns")
    def expensive(x):
        calls.append(x)
        return x * 2

    assert expensive(3) == 6
    assert expensive(3) == 6
    # second call with the same args is served from disk cache, not re-run
    assert calls == [3]
    assert expensive(4) == 8
    assert calls == [3, 4]


def test_utils_cache_clear_removes_entries(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_CACHE_DIR", str(tmp_path))
    utils_cache._caches.clear()

    @utils_cache.memoize_disk(namespace="clear_ns")
    def fn(x):
        return x

    fn(1)
    fn(2)
    removed = utils_cache.clear("clear_ns")
    assert removed == 2


def test_utils_cache_get_cache_returns_none_without_diskcache(monkeypatch):
    monkeypatch.setattr(utils_cache, "_HAS_DISKCACHE", False)
    assert utils_cache.get_cache("anything") is None
    assert utils_cache.clear("anything") == 0


def test_memoize_disk_noop_when_diskcache_unavailable(monkeypatch, tmp_path):
    monkeypatch.setenv("SIMPLICIO_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(utils_cache, "_HAS_DISKCACHE", False)

    @utils_cache.memoize_disk(namespace="disabled_ns")
    def fn(x):
        return x + 1

    # decorator degrades to the plain function when diskcache is unavailable
    assert fn(1) == 2


# --------------------------------------------------------------------------- #
# utils/http_client.py
# --------------------------------------------------------------------------- #


def test_http_client_returns_singleton(monkeypatch):
    http_client._close()
    c1 = http_client.client()
    c2 = http_client.client()
    assert c1 is c2
    http_client._close()


def test_http_client_config_reads_env(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_HTTP_MAX_CONN", "5")
    monkeypatch.setenv("SIMPLICIO_HTTP_KEEPALIVE", "2")
    cfg = http_client._config()
    assert cfg["limits"].max_connections == 5
    assert cfg["limits"].max_keepalive_connections == 2
    assert cfg["follow_redirects"] is True


def test_http_client_post_json_uses_shared_client(monkeypatch):
    http_client._close()

    captured = {}

    class FakeResponse:
        content = b'{"ok": true}'

        def raise_for_status(self):
            return None

    class FakeClient:
        def post(self, url, *, content, headers, timeout):
            captured["url"] = url
            captured["content"] = content
            captured["headers"] = headers
            return FakeResponse()

    monkeypatch.setattr(http_client, "client", lambda: FakeClient())
    result = http_client.post_json("https://example.invalid/v1", {"a": 1})
    assert result == {"ok": True}
    assert captured["url"] == "https://example.invalid/v1"
    assert captured["headers"]["Content-Type"] == "application/json"


def test_http_client_close_is_idempotent():
    http_client._close()
    http_client._close()  # second close on an already-closed client is a no-op
    assert http_client._client is None


# --------------------------------------------------------------------------- #
# provider_cache_receipt.py
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# commands/file.py and commands/test.py dispatchers
# --------------------------------------------------------------------------- #


def test_file_command_dispatches_read(monkeypatch):
    called = {}

    def fake_read(a):
        called["a"] = a
        return 0

    monkeypatch.setattr("simplicio.commands.file_read.run", fake_read)
    code = file_cmd.run(ns(file_cmd="read"))
    assert code == 0
    assert "a" in called


def test_file_command_unsupported_subcommand(capsys):
    code = file_cmd.run(ns(file_cmd="bogus"))
    assert code == 2
    assert "unsupported command" in capsys.readouterr().err


def test_test_command_dispatches_run_and_strips_leading_dashdash(monkeypatch):
    captured = {}

    def fake_run(a, extra_args):
        captured["cmd"] = a.cmd
        captured["extra_args"] = extra_args
        return 0

    monkeypatch.setattr("simplicio.commands.test_run.run", fake_run)
    code = test_cmd.run(ns(test_cmd="run", test_program="pytest", extra_args=["--", "-k", "foo"]))
    assert code == 0
    assert captured["cmd"] == "pytest"
    assert captured["extra_args"] == ["-k", "foo"]


def test_test_command_unsupported_subcommand(capsys):
    code = test_cmd.run(ns(test_cmd="bogus"))
    assert code == 2
    assert "unsupported command" in capsys.readouterr().err
