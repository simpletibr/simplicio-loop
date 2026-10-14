"""The command written into ``test_result``, ``lint_result`` and ``coverage_result`` events is scrubbed (issue #1565).

``quality_events._command`` used to cut the raw command to its limit and nothing more, so a token typed on a check's
command line (``pytest --token X``, ``curl -u user:pass``) reached ``events.jsonl``. It now goes through the same
``runs.redact_command`` the ``command_started`` event uses, scrubbing first and cutting after. Only fake secrets here.
"""
from __future__ import annotations

import json
import time

import pytest

from simplicio_loop import quality_events as qe
from tests._secret_corpus import SECRET_CORPUS

PYTEST_OUT = "==== 3 failed, 10 passed in 1.23s ===="
RUFF_OUT = "src/a.py:3:1: E501 line too long\nFound 1 error.\n"
COVERAGE_OUT = "Name   Stmts   Miss  Cover\nsrc/a.py   10   2   80%\nTOTAL   10   2   80%\n"

# kind -> (event kind, output that the matching parser recognises)
KINDS = {
    "tests": ("test_result", PYTEST_OUT),
    "lint": ("lint_result", RUFF_OUT),
    "coverage": ("coverage_result", COVERAGE_OUT),
}
ORDINARY = [
    "python3 -m pytest -q -p no:cacheprovider tests/test_dashboard_lane_extras_unit.py",
    "PYTHONPATH=/tmp/x/648e9aed/scratchpad/rev1560 python3 -m pytest -q tests/flow",
    "ruff check . && mypy --strict simplicio_loop",
    "git checkout -b feat/x && git push -u origin feat/x",
    "docker run -p 8080:80 -u 1000:1000 img",
    "git log 122df7e5c0a4d7f6c0e8a1b2c3d4e5f60718293a..HEAD",
    "pytest --cov=simplicio_loop --cov-report=term-missing -q",
]


@pytest.fixture
def run_env(tmp_path, monkeypatch):
    monkeypatch.delenv("SIMPLICIO_DASHBOARD_EVENTS", raising=False)
    monkeypatch.delenv("SIMPLICIO_ITERATION", raising=False)
    monkeypatch.chdir(tmp_path)
    run = tmp_path / "run"
    run.mkdir()
    return run, {"SIMPLICIO_RUN_DIR": str(run)}


def _payload(which: str, command: str) -> dict:
    if which == "tests":
        return qe.parse_tests(command, PYTEST_OUT, 1, None)
    if which == "lint":
        return qe.parse_lint(command, RUFF_OUT, 1)
    return qe.parse_coverage(command, COVERAGE_OUT)


@pytest.mark.parametrize("which", sorted(KINDS))
@pytest.mark.parametrize(("command", "secret"), SECRET_CORPUS)
def test_no_secret_of_the_hostile_corpus_reaches_the_events_file(run_env, which, command, secret):
    run, env = run_env
    kind, output = KINDS[which]
    written = qe.emit_check("T1", command, output, "", 1, 0.5, env=env)
    assert [evt["kind"] for evt in written] == [kind]
    raw = (run / "events.jsonl").read_text(encoding="utf-8")
    assert secret not in raw
    assert secret not in written[0]["payload"]["command"]


@pytest.mark.parametrize("which", sorted(KINDS))
@pytest.mark.parametrize("command", ORDINARY)
def test_an_ordinary_command_is_written_as_it_is(which, command):
    assert _payload(which, command)["command"] == command


@pytest.mark.parametrize("which", sorted(KINDS))
def test_a_secret_cut_by_the_length_cap_is_scrubbed_first(which):
    """Cutting first would leave ``hun`` (too short to match) of a password the 500-character cap splits."""
    command = "a" * (qe.COMMAND_MAX - 13) + " password=hunter2hunter2 " + "b" * 400
    found = _payload(which, command)["command"]
    assert "hun" not in found and "hunter2" not in found
    assert len(found) <= qe.COMMAND_MAX


@pytest.mark.parametrize("which", sorted(KINDS))
def test_a_secret_split_by_the_scan_window_leaves_no_head_behind(which):
    key = "-----BEGIN RSA PRIVATE KEY-----\n" + "K" * 4000 + "\n-----END RSA PRIVATE KEY----- "
    command = key + "y" * (4096 - len(key) - 3) + " sk-" + "QQQQ" * 20
    assert "sk-" not in _payload(which, command)["command"]


@pytest.mark.parametrize("which", sorted(KINDS))
@pytest.mark.parametrize("hostile", ["password-" * 500, "a-" * 2048, "PaSsWoRd-ToKeN-" * 270, "Bearer " * 600, "a@" * 2000])
def test_a_hostile_command_never_stalls_the_parser(which, hostile):
    began = time.monotonic()
    _payload(which, hostile)
    assert time.monotonic() - began < 1.0


@pytest.mark.parametrize("which", sorted(KINDS))
def test_a_scrubber_that_fails_never_breaks_the_payload_nor_leaks_the_command(which, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("scrubber on fire")
    monkeypatch.setattr(qe, "redact_command", boom)
    payload = _payload(which, "tool --token ghp_FAKEabcdefghijklmnopqrstuvwxyz0123456789")
    assert payload is not None and payload["command"] == ""


def test_a_scrubber_that_fails_still_emits_the_event_without_the_command(run_env, monkeypatch):
    run, env = run_env

    def boom(*args, **kwargs):
        raise RuntimeError("scrubber on fire")
    monkeypatch.setattr(qe, "redact_command", boom)
    written = qe.emit_check("T1", "pytest --token hunter2hunter2", PYTEST_OUT, "", 1, 0.5, env=env)
    assert [evt["kind"] for evt in written] == ["test_result"]
    raw = (run / "events.jsonl").read_text(encoding="utf-8")
    assert "hunter2hunter2" not in raw
    assert json.loads(raw.splitlines()[0])["payload"]["command"] == ""


def test_the_tool_name_still_comes_from_the_command_after_the_scrub():
    assert qe.parse_lint("flake8 --token hunter2hunter2 src", "src/a.py:3:1: E501 too long\n", 1)["tool"] == "flake8"
    assert qe.parse_lint("ruff check --token hunter2hunter2 src", RUFF_OUT, 1)["tool"] == "ruff"


def test_a_command_that_cannot_be_printed_never_breaks_the_payload():
    class Unprintable:
        def __str__(self):
            raise RuntimeError("no text")
    assert qe.parse_tests(Unprintable(), PYTEST_OUT, 1, None)["command"] == ""
    assert qe.parse_tests(None, PYTEST_OUT, 1, None)["command"] == ""
    assert qe.parse_tests(b"pytest -q", PYTEST_OUT, 1, None)["command"] == "pytest -q"
