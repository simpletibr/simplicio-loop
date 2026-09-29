"""Regression tests for the compact LLM-facing Prism surface."""

from simplicio_loop.capability_catalog import load_catalog
from simplicio_loop.route import route


def test_catalog_exposes_stable_skills_and_schema() -> None:
    catalog = load_catalog()
    assert catalog["schema"] == "simplicio.capability-catalog/v1"
    assert catalog["language"] == "en"
    assert catalog["instruction_language"] == "en"
    assert len(catalog["capabilities"]) == 12
    assert not any(item["component"] == "fast" for item in catalog["capabilities"])
    assert not any(item["component"] == "runtime" for item in catalog["capabilities"])
    assert "simplicio-fast" not in catalog["skills"]
    assert "simplicio-runtime" not in catalog["skills"]
    assert catalog["skills"] == sorted(catalog["skills"])
    assert catalog["load_policy"] == "index-first, skill-on-demand"


def test_prism_routes_portuguese_sprint_issue_to_full_stack() -> None:
    result = route(
        "Portfolio Intake Agent delegando lifecycle e completion ao Loop; "
        "validar Mapper, Dev CLI e abrir PR"
    )
    assert result["schema"] == "simplicio.route/v1"
    assert result["language"] == "en"
    assert result["instruction_language"] == "en"
    assert result["intent"] == "orchestrate"
    assert result["unresolved"] == []
    assert result["skills_to_load"] == [
        "simplicio-dev-cli", "simplicio-loop", "simplicio-mapper"
    ]
    assert result["selected_capabilities"][-1] == "loop.complete"
    assert {adapter["component"] for adapter in result["existing_adapters"]} == {
        "mapper", "dev-cli", "loop"
    }


def test_prism_closes_dependency_gaps_for_validation() -> None:
    result = route("validar os testes do repositório")
    assert result["intent"] == "validate"
    selected = result["selected_capabilities"]
    assert selected.index("dev-cli.preflight") < selected.index("dev-cli.tests")
    assert selected.index("dev-cli.tests") < selected.index("dev-cli.evidence")


def test_governance_wording_never_routes_to_a_runtime_capability() -> None:
    result = route("authorize the policy gate and reconcile execution through the runtime gate")
    assert result["intent"] != "govern"
    assert not any(item.startswith("runtime.") for item in result["selected_capabilities"])
    assert "runtime" not in {adapter["component"] for adapter in result["existing_adapters"]}
    assert result["unresolved"] == []

