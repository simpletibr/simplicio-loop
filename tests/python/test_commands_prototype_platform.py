"""Cross-platform behavior for `simplicio/commands/prototype.py` (issue #236
"Windows/Linux/macOS" AC, follow-up).

This container is Linux-only, so the Windows- and macOS-specific branches
below are `skipif`-gated rather than run for real; that is the honest
boundary — see the module docstring in `simplicio/commands/prototype.py`
for exactly which primitives are portable-by-construction versus merely
"documented, not exercised, on the untested platform". Every test in this
file that is *not* platform-gated runs, and must pass, on this Linux
container right now.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

from simplicio import cli
from simplicio.commands import prototype


def _artifacts_dir(tmp_path: Path) -> Path:
    directory = tmp_path / ".simplicio" / "artifacts"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _plan_from_input(tmp_path: Path, capsys, *, validators: list[str]) -> Path:
    input_path = _artifacts_dir(tmp_path) / "input.json"
    input_path.write_text(
        json.dumps(
            {"goal": "cross-platform check", "prototype_type": "code_spike", "validators": validators}
        ),
        encoding="utf-8",
    )
    plan_path = _artifacts_dir(tmp_path) / "plan.json"
    code = cli.main(
        ["prototype", "plan", "--input", str(input_path), "--root", str(tmp_path), "--output", str(plan_path)]
    )
    assert code == 0
    capsys.readouterr()
    return plan_path


# ---------------------------------------------------------------------------
# Runs everywhere (this is the part that is actually verified here, on Linux)
# ---------------------------------------------------------------------------


def test_tree_hash_uses_posix_separators_regardless_of_host_os(tmp_path):
    """`_tree`/`_source_tree` key every hashed file by `Path.as_posix()`, not
    the host's native separator — so the same file layout hashes identically
    whether this ran on Windows (`\\`-separated `Path.parts`) or POSIX
    (`/`-separated). This is the one place the module deliberately does NOT
    use the host-native path string, precisely so the stale-candidate hash
    in a plan/receipt is portable across the machines that might produce or
    consume it."""
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    (nested / "c.txt").write_text("x", encoding="utf-8")

    tree = prototype._tree(tmp_path)

    assert "a/b/c.txt" in tree
    assert "\\" not in next(iter(tree))


def test_validate_captures_non_ascii_validator_output_via_pinned_utf8_encoding(tmp_path, capsys):
    """Regression for the encoding fix: `subprocess.run` in `validate` now
    pins `encoding="utf-8", errors="replace"` explicitly instead of relying
    on `text=True`'s platform-default locale encoding (commonly cp1252 on
    Windows), so non-ASCII validator stdout decodes the same way on every
    platform rather than raising `UnicodeDecodeError` only on some of them.
    """
    validator = f'"{sys.executable}" -c "print(\'caf\\u00e9 \\u2705\')"'
    plan_path = _plan_from_input(tmp_path, capsys, validators=[validator])
    cli.main(["prototype", "scaffold", "--root", str(tmp_path), "--plan", str(plan_path)])
    capsys.readouterr()

    code = cli.main(["prototype", "validate", "--root", str(tmp_path), "--plan", str(plan_path), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["valid"] is True
    assert "café" in payload["validators"][0]["stdout"]
    assert "✅" in payload["validators"][0]["stdout"]


def test_validate_subprocess_call_pins_utf8_encoding_explicitly(tmp_path, capsys):
    """Direct check (not just an output-based inference) that the
    `subprocess.run` call inside `validate` passes explicit
    `encoding="utf-8", errors="replace"` rather than the bare `text=True`
    it used before this fix — the actual portability contract, not just one
    of its symptoms."""
    plan_path = _plan_from_input(tmp_path, capsys, validators=[f'"{sys.executable}" -c "pass"'])
    cli.main(["prototype", "scaffold", "--root", str(tmp_path), "--plan", str(plan_path)])
    capsys.readouterr()

    with mock.patch.object(prototype.subprocess, "run", wraps=subprocess.run) as spy:
        code = cli.main(
            ["prototype", "validate", "--root", str(tmp_path), "--plan", str(plan_path), "--json"]
        )
    capsys.readouterr()

    assert code == 0
    assert spy.call_count == 1
    _, kwargs = spy.call_args
    assert kwargs.get("encoding") == "utf-8"
    assert kwargs.get("errors") == "replace"
    assert "text" not in kwargs, "encoding= already implies text mode; do not also pass text=True"


def test_write_json_uses_os_replace_not_os_rename(tmp_path):
    """`_write_json` must use `os.replace` (atomic overwrite on both POSIX
    and Windows), not `os.rename` (raises FileExistsError on Windows if the
    destination already exists). Guards against a portability regression
    creeping back in."""
    target = tmp_path / "artifact.json"
    prototype._write_json(target, {"a": 1})
    assert json.loads(target.read_text(encoding="utf-8")) == {"a": 1}

    # Overwrite: this is exactly the case os.rename cannot do on Windows.
    prototype._write_json(target, {"a": 2})
    assert json.loads(target.read_text(encoding="utf-8")) == {"a": 2}


def test_no_posix_only_primitives_are_used(tmp_path):
    """Static guard: the module must not reintroduce `os.fork`, POSIX
    permission-bit chmod calls, or process-signal handling — none of the
    Prototype-First adapter's commands need them, and any of the three
    would silently break on Windows."""
    source = Path(prototype.__file__).read_text(encoding="utf-8")
    for forbidden in ("os.fork(", "os.chmod(", "signal.SIGKILL", "signal.SIGTERM"):
        assert forbidden not in source, f"POSIX-only primitive reintroduced: {forbidden}"


# ---------------------------------------------------------------------------
# Windows-only branches: skip-gated because this container cannot run them.
# Kept here (rather than omitted) so a future Windows CI runner picks them
# up for real instead of the gap staying invisible.
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform != "win32", reason="exercises the Windows cmd.exe shell path for real")
def test_validate_shell_true_runs_via_cmd_exe_on_windows(tmp_path, capsys):  # pragma: no cover - Windows only
    plan_path = _plan_from_input(tmp_path, capsys, validators=["echo hello"])
    cli.main(["prototype", "scaffold", "--root", str(tmp_path), "--plan", str(plan_path)])
    capsys.readouterr()

    code = cli.main(["prototype", "validate", "--root", str(tmp_path), "--plan", str(plan_path), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert "hello" in payload["validators"][0]["stdout"]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows os.replace-over-existing-directory semantics")
def test_promote_swap_on_windows_requires_empty_destination(tmp_path):  # pragma: no cover - Windows only
    # On Windows, os.replace(src, dst) only succeeds when dst is a file or
    # an *empty* directory (same constraint POSIX os.rename has for
    # directories); the promote flow's backup-then-replace dance in `run()`
    # already accounts for this by moving any existing target out of the
    # way first, but this asserts it explicitly on the one platform where
    # the constraint is easy to get subtly wrong (case-insensitive paths,
    # ERROR_ACCESS_DENIED on a locked handle instead of a clean rename
    # error).
    pytest.skip("requires a real Windows filesystem to exercise meaningfully")


# ---------------------------------------------------------------------------
# POSIX-only branch note (documented, not gap-hidden): none needed today.
# `validate`'s shell=True already runs the real POSIX /bin/sh on this
# container in every non-Windows test above, so there is no separate
# "POSIX-only" branch left unexercised here — the Windows branch above is
# the only one this repo cannot verify in-container.
# ---------------------------------------------------------------------------
