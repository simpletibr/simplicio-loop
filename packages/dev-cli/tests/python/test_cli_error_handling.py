"""Coverage for `simplicio.cli.main`'s top-level error/cancellation handling.

Issue #200: the dispatch try/except in `cli.main` is the single place that
turns an in-flight command's `KeyboardInterrupt` (user cancel), a
`BrokenPipeError` (downstream reader went away, e.g. `| head`), or any other
uncaught exception into a stable process exit code. None of that translation
had a direct test before this file — subcommand tests exercise their own
success/failure paths, but nothing simulated a command blowing up mid-flight
to prove `main()` itself degrades gracefully instead of a raw traceback (or,
worse, a non-2xx-shaped exit code) reaching the caller.
"""

from __future__ import annotations

import pytest

from simplicio import cli


def _boom(*_args, **_kwargs):
    raise RuntimeError("boom from a fake command handler")


def test_keyboard_interrupt_during_dispatch_exits_130(monkeypatch):
    """Ctrl-C mid-command must map to the POSIX SIGINT convention (130),
    not propagate as a traceback nor collapse into the generic error path."""
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")

    def fake_run(_a):
        raise KeyboardInterrupt()

    monkeypatch.setattr("simplicio.commands.status.run", fake_run)

    code = cli.main(["status"])

    assert code == 130


def test_broken_pipe_during_dispatch_exits_130(monkeypatch):
    """`simplicio-py status | head -1` closing its read end mid-write must
    not surface as an unhandled error; it maps to the same 130 code as an
    interactive cancel."""
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")

    def fake_run(_a):
        raise BrokenPipeError()

    monkeypatch.setattr("simplicio.commands.status.run", fake_run)

    code = cli.main(["status"])

    assert code == 130


def test_generic_exception_exits_1_with_friendly_message(monkeypatch, capsys):
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")
    monkeypatch.setattr("simplicio.commands.status.run", _boom)

    code = cli.main(["status"])

    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert "simplicio-py: error: boom from a fake command handler" in captured.err
    assert "Traceback" not in captured.err


def test_verbose_flag_reraises_instead_of_swallowing(monkeypatch):
    """`--verbose`/`-v` is documented (see `_extract_global_verbosity`) as an
    escape hatch for debugging: with it set, the generic-exception branch
    must re-raise the underlying error rather than print-and-exit, so a
    caller running under a debugger/traceback collector still sees it."""
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")
    monkeypatch.setattr("simplicio.commands.status.run", _boom)

    with pytest.raises(RuntimeError, match="boom from a fake command handler"):
        cli.main(["--verbose", "status"])


def test_ecosystem_check_failure_is_swallowed_and_does_not_block_dispatch(monkeypatch, capsys):
    """The session-start freshness check is explicitly best-effort (see the
    inner try/except around `maybe_run_session_start` in `cli.main`): if it
    blows up we must still dispatch the real subcommand rather than fail the
    whole invocation."""
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")

    def fake_maybe_run_session_start():
        raise RuntimeError("network unreachable")

    monkeypatch.setattr(
        "simplicio.ecosystem.maybe_run_session_start",
        fake_maybe_run_session_start,
    )

    code = cli.main(["status", "--json"])

    captured = capsys.readouterr()
    assert code == 0
    assert "ecosystem check skipped" in captured.err
    assert '"schema": "simplicio.dev-cli.status/v1"' in captured.out
