from __future__ import annotations

import tomllib
from pathlib import Path

from simplicio_loop import stack_manifest as manifest


ROOT = Path(__file__).parents[1]

# Monorepo: mapper and dev-cli are bundled into the single simplicio-loop wheel, so the
# source-head train is one component whose floor is the loop's own release version
# (scripts/version_sync.py keeps _FALLBACK_FLOORS in step with pyproject.toml).
SOURCE_HEAD_FALLBACK_FLOORS = {
    "simplicio-loop": tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]["version"],
}


def test_fallback_floors_match_source_head_train_without_metadata(monkeypatch) -> None:
    monkeypatch.setattr(manifest, "_pyproject_path", lambda: Path("/missing/pyproject.toml"))
    monkeypatch.setattr(manifest, "_installed_version", lambda _name: None)

    expected_components = [
        (name, role, SOURCE_HEAD_FALLBACK_FLOORS[name])
        for name, role in manifest._COMPONENT_ROLES
    ]

    assert [name for name, _role in manifest._COMPONENT_ROLES] == ["simplicio-loop"]
    assert manifest._FALLBACK_FLOORS == SOURCE_HEAD_FALLBACK_FLOORS
    assert manifest._train_components() == expected_components
