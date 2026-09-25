"""Cross-package e2e: Mapper's public ``handoff`` verb -> Fast integrated ingest.

Regression coverage for the documented agent workflow
(``simplicio-mapper scan`` -> ``simplicio-mapper handoff --json`` -> Fast
``ingest --mapper-mode integrated``), which never calls the internal
``simplicio-mapper snapshot build``. Before the mapper-side fix, ``handoff``
never materialized the canonical ``.simplicio/context-snapshot.json`` Fast
reads symbol ids from, so this flow failed closed with
``mapper_artifact_missing: context_snapshot`` even though ``handoff --json``
reported ``ready: true``. This test exercises the flow both without and
with ``--goal`` (task-aware handoff must not starve the canonical snapshot
of symbol nodes either -- ``mapper_id_missing``).

Skipped when the ``simplicio-mapper`` binary is not on PATH -- it is
installed in this project's own venv/CI image, so the skip only guards
environments that deliberately do not install the optional Mapper operator.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

FAST_ROOT = Path(__file__).resolve().parents[1]

MAPPER_BIN = shutil.which("simplicio-mapper")

pytestmark = pytest.mark.skipif(
    MAPPER_BIN is None,
    reason="simplicio-mapper binary is required for this documented cross-package flow",
)


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _make_repo(root: Path) -> None:
    root.mkdir()
    (root / "mathx").mkdir()
    (root / "mathx" / "__init__.py").write_text("", encoding="utf-8")
    (root / "mathx" / "ops.py").write_text(
        "def double(x):\n"
        "    return x * 2\n\n\n"
        "def triple(x):\n"
        "    return x * 3\n\n\n"
        "def square(x):\n"
        "    return x * x\n",
        encoding="utf-8",
    )
    (root / "tests").mkdir()
    (root / "tests" / "test_ops.py").write_text(
        "from mathx.ops import double\n\n\ndef test_double():\n    assert double(2) == 4\n",
        encoding="utf-8",
    )
    _git(root, "init", "--quiet", "-b", "main")
    _git(root, "config", "user.email", "fast-tests@example.invalid")
    _git(root, "config", "user.name", "Fast tests")
    _git(root, "add", "-A")
    _git(root, "commit", "--quiet", "-m", "fixture")


def _mapper(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    assert MAPPER_BIN is not None
    return subprocess.run(
        [MAPPER_BIN, *args],
        cwd=root,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )


def _run_fast(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    source_path = str(FAST_ROOT / "src")
    environment["PYTHONPATH"] = ":".join(
        part for part in (source_path, environment.get("PYTHONPATH")) if part
    )
    return subprocess.run(
        [sys.executable, "-m", "simplicio_fast.cli", *args],
        cwd=root,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )


def _scan_and_handoff(root: Path, *, goal: str | None) -> dict[str, object]:
    scan = _mapper(root, "scan", str(root), "--sync")
    assert scan.returncode == 0, scan.stderr

    handoff_args = ["handoff", str(root), "--json"]
    if goal:
        handoff_args += ["--goal", goal]
    handoff = _mapper(root, *handoff_args)
    assert handoff.returncode == 0, handoff.stderr
    envelope = json.loads(handoff.stdout)
    assert envelope.get("schema") == "simplicio.map-handoff/v1"
    assert envelope.get("ready") is True, envelope.get("reason")
    return envelope


@pytest.mark.parametrize("goal", [None, "fix double square in mathx"])
def test_scan_then_public_handoff_feeds_fast_integrated_ingest(
    tmp_path: Path, goal: str | None
) -> None:
    root = tmp_path / "repo"
    _make_repo(root)

    envelope = _scan_and_handoff(root, goal=goal)

    # The public handoff envelope must point Fast at canonical artifacts
    # that actually exist on disk -- not just claim readiness.
    snapshot_path = root / ".simplicio" / "context-snapshot.json"
    assert snapshot_path.is_file(), (
        "handoff must materialize the canonical context snapshot Fast needs"
    )
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert snapshot.get("schema") == "simplicio.context-snapshot/v1"
    symbol_node_ids = [
        node.get("id")
        for node in snapshot.get("graph", {}).get("nodes", [])
        if isinstance(node, dict) and str(node.get("id", "")).startswith("symbol:")
    ]
    assert symbol_node_ids, "canonical snapshot must retain symbol nodes, not just files"

    external_handoff = tmp_path / f"mapper-handoff-{goal is not None}.json"
    external_handoff.write_text(json.dumps(envelope, sort_keys=True) + "\n", encoding="utf-8")
    output_snapshot = tmp_path / f"fast-{goal is not None}.sfast"

    ingest = _run_fast(
        root,
        "ingest",
        str(root),
        "--output",
        str(output_snapshot),
        "--mapper-mode",
        "integrated",
        "--mapper-handoff",
        str(external_handoff),
        "--json",
    )
    assert ingest.returncode == 0, ingest.stderr + ingest.stdout
    payload = json.loads(ingest.stdout)
    assert payload["schema"] == "simplicio.fast.ingest/v2"
    assert payload["mapper"]["mode"] == "integrated"
    symbol_names = {
        str(item.get("name") or "") for item in payload["mapper"]["artifacts"]
    }
    assert "context_snapshot" in symbol_names
