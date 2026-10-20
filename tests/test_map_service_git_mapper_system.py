"""System contract for map-service identity against the real Git and mapper CLIs."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from simplicio_loop.map_service import MapServiceRegistry, RepositoryIdentity

pytestmark = [
    pytest.mark.external_integration,
    pytest.mark.skipif(
        shutil.which("simplicio-mapper") is None,
        reason=(
            "EXTERNAL_INTEGRATION_UNAVAILABLE[installed_mapper]: "
            "the real mapper lane requires simplicio-mapper on PATH"
        ),
    ),
]


def _run(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args), cwd=str(cwd), check=True, capture_output=True, text=True,
        stdin=subprocess.DEVNULL,
    )


def test_real_git_and_mapper_artifacts_bind_to_protocol_identity() -> None:
    root = Path(__file__).resolve().parents[1]
    head = _run("git", "rev-parse", "HEAD", cwd=root).stdout.strip()
    _run("simplicio-mapper", "index", str(root), "--json", cwd=root)
    mapper = _run("simplicio-mapper", "inspect", str(root), "--json", cwd=root)
    inspection = json.loads(mapper.stdout)
    assert inspection["schema"] == "simplicio.map-inspection/v1"
    assert inspection["status"]["fresh"] is True

    registry = MapServiceRegistry()
    identity_key = registry.register(
        RepositoryIdentity(
            repository="simpletibr/simplicio-loop",
            canonical_root=str(root),
            base_sha=head,
            dirty=bool(_run("git", "status", "--porcelain", cwd=root).stdout.strip()),
            dirty_fingerprint=_run("git", "diff", "--no-ext-diff", cwd=root).stdout,
            mapper_config={"mapper_schema": inspection["status"]["schema"]},
        )
    )
    resolved = registry.resolve_repo(str(root / "simplicio_loop" / "map_service.py"))
    view = registry.build_canonical(
        identity_key,
        tree_hash=head,
        files=[str(root / "simplicio_loop" / "map_service.py")],
    )
    assert resolved.key == identity_key
    assert view.identity_key == identity_key
    assert view.mode == "canonical"
