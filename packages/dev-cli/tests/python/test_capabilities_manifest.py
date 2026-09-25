"""Tests for the static `simplicio-dev-cli capabilities` manifest.

Covers: the packaged JSON matches the live argparse surface byte-for-byte
(drift guard -- ``scripts/gen_capabilities_manifest.py`` is the only writer),
the in-process loader (`simplicio.capabilities.load_capabilities_manifest`)
returns the same document without a subprocess, the CLI fast path prints it
for both `capabilities` and `capabilities --json`, and that the manifest
covers what a caller (the host loop) actually needs to stop probing
`--help`/`edit --help`/`--version` per attempt: the `edit` command's
required flags and the minimal host edit-plan format.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path

from simplicio import cli
from simplicio.capabilities import load_capabilities_manifest
from simplicio.capabilities_introspect import build_capabilities_manifest

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO_ROOT / "simplicio" / "data" / "capabilities.json"


def _regenerate_from_live_parser() -> dict:
    parser = cli._build_parser()
    return build_capabilities_manifest(
        parser,
        package_name="simplicio-cli",
        package_version=json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))["package"]["version"],
        adapter_command="simplicio-dev-cli",
        python_adapter_command="simplicio-py",
    )


def test_packaged_manifest_matches_live_argparse_surface():
    """Drift guard: the packaged file is byte-identical to a fresh regeneration.

    Only the version is pinned to the packaged file's own value here (a
    version bump is orthogonal to command/flag drift and is covered by the
    package's own version-sync checks) -- everything else must match exactly.
    """
    on_disk = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    regenerated = _regenerate_from_live_parser()
    assert regenerated == on_disk, (
        "simplicio/data/capabilities.json is stale vs. the live argparse surface -- "
        "run `python3 scripts/gen_capabilities_manifest.py`"
    )


def test_manifest_covers_edit_command_and_minimal_plan_format():
    manifest = load_capabilities_manifest()
    assert manifest["schema"] == "simplicio.dev-cli.capabilities/v1"
    assert manifest["entrypoints"]["adapter"] == "simplicio-dev-cli"
    edit = manifest["commands"]["edit"]
    for required_flag in ("--plan", "--apply", "--dry-run", "--json", "--compile"):
        assert required_flag in edit["flags"], required_flag
    plan_format = manifest["edit_plan_formats"]["minimal_host_plan"]
    assert plan_format["operations"][0].keys() == {"path", "find", "replace"}
    assert manifest["edit_plan_formats"]["compiled_plan_schema"] == "simplicio.dev-cli.edit-plan/v1"


def test_load_capabilities_manifest_is_cached_and_in_process():
    """No subprocess: two in-process calls return the same object (lru_cache)."""
    first = load_capabilities_manifest()
    second = load_capabilities_manifest()
    assert first is second


def test_cli_capabilities_fast_path_json(capsys):
    rc = cli.main(["capabilities", "--json"])
    assert rc == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["schema"] == "simplicio.dev-cli.capabilities/v1"
    assert "edit" in payload["commands"]


def test_cli_capabilities_fast_path_human(capsys):
    rc = cli.main(["capabilities"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "simplicio.dev-cli.capabilities/v1" in out
    assert "edit" in out


def test_cli_capabilities_help_falls_through_to_argparse():
    buf = io.StringIO()
    with redirect_stdout(buf):
        try:
            cli.main(["capabilities", "--help"])
        except SystemExit as exc:
            assert exc.code == 0
    assert "usage: simplicio-py capabilities" in buf.getvalue()


def test_capabilities_subprocess_no_slower_than_version_probe():
    """Cheap-discovery requirement: capabilities must not be meaningfully
    slower than the existing --version fast path (both skip heavy imports).
    Generous bound to stay robust on loaded CI machines -- this guards
    against a regression that pulls capabilities back onto a heavy import
    path, not against ordinary process-start jitter.
    """
    version_argv = [sys.executable, "-m", "simplicio.cli", "--version"]
    capabilities_argv = [sys.executable, "-m", "simplicio.cli", "capabilities", "--json"]
    version_result = subprocess.run(version_argv, capture_output=True, text=True, timeout=10)
    capabilities_result = subprocess.run(capabilities_argv, capture_output=True, text=True, timeout=10)
    assert version_result.returncode == 0
    assert capabilities_result.returncode == 0
