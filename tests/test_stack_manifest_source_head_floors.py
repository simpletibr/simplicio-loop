from __future__ import annotations

from pathlib import Path

from simplicio_loop import stack_manifest as manifest


SOURCE_HEAD_FALLBACK_FLOORS = {
    "simplicio-mapper": "0.26.34",
    "simplicio-fast": "2.0.35",
    "simplicio-cli": "0.18.16",
    "simplicio-loop": "3.43.16",
}


def test_fallback_floors_match_source_head_train_without_metadata(monkeypatch) -> None:
    monkeypatch.setattr(manifest, "_pyproject_path", lambda: Path("/missing/pyproject.toml"))
    monkeypatch.setattr(manifest, "_declared_dependency_specs", lambda: {})
    monkeypatch.setattr(manifest, "_installed_version", lambda _name: None)

    expected_components = [
        (name, role, SOURCE_HEAD_FALLBACK_FLOORS[name])
        for name, role in manifest._COMPONENT_ROLES
    ]

    assert manifest._FALLBACK_FLOORS == SOURCE_HEAD_FALLBACK_FLOORS
    assert manifest._train_components() == expected_components
