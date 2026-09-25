"""Tests for `simplicio.cli._extract_global_verbosity` (issue #106).

A leading `--quiet`/`-q`/`--verbose`/`-v`, appearing before the subcommand
token, configures the shared `simplicio` logger without disturbing any
subcommand-local flag of the same name (e.g. `detect --quiet`,
`score-skill --verbose`), which remain untouched further down argv.
"""

from simplicio.cli import _extract_global_verbosity


def test_no_flags_passthrough():
    quiet, verbose, remaining = _extract_global_verbosity(["detect", "--prompt", "x"])
    assert quiet is False
    assert verbose is False
    assert remaining == ["detect", "--prompt", "x"]


def test_leading_quiet_is_consumed():
    quiet, verbose, remaining = _extract_global_verbosity(["--quiet", "detect"])
    assert quiet is True
    assert verbose is False
    assert remaining == ["detect"]


def test_leading_short_flags_are_consumed():
    quiet, verbose, remaining = _extract_global_verbosity(["-q", "-v", "task"])
    assert quiet is True
    assert verbose is True
    assert remaining == ["task"]


def test_subcommand_local_quiet_is_not_consumed():
    # `detect --quiet` — the --quiet here belongs to the `detect` subcommand
    # (comes after the first positional token) and must reach it unchanged.
    quiet, verbose, remaining = _extract_global_verbosity(["detect", "--quiet"])
    assert quiet is False
    assert remaining == ["detect", "--quiet"]


def test_subcommand_local_verbose_is_not_consumed():
    quiet, verbose, remaining = _extract_global_verbosity(["score-skill", "myskill", "--verbose"])
    assert verbose is False
    assert remaining == ["score-skill", "myskill", "--verbose"]


def test_empty_argv():
    quiet, verbose, remaining = _extract_global_verbosity([])
    assert (quiet, verbose, remaining) == (False, False, [])
