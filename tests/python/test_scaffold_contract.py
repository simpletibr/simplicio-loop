from __future__ import annotations

from simplicio.mapper_binding import build_mapper_binding
from simplicio.scaffold_contract import plan_scaffold


def _binding() -> dict:
    return build_mapper_binding("owner/repo", 1, "tree-1", {"src/app.py": "0" * 64})


def test_scaffold_plan_is_pure_and_bound_to_mapper_generation() -> None:
    first = plan_scaffold("python-package", "demo_pkg", mapper_binding=_binding())
    second = plan_scaffold("python-package", "demo_pkg", mapper_binding=_binding())
    assert first == second
    assert first["status"] == "planned"
    assert first["runtime_authorization_required"] is True
    assert first["mapper_binding"]["generation"] == "1"


def test_scaffold_rejects_unsupported_kind_and_unsafe_name() -> None:
    binding = _binding()
    assert plan_scaffold("unknown", "demo", mapper_binding=binding)["errors"][0]["code"] == "unsupported_scaffold"
    assert plan_scaffold("python-package", "../demo", mapper_binding=binding)["errors"][0]["code"] == "invalid_path"

