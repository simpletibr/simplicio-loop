import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from simplicio_loop.task_contract import ROUTING_ROLES, compile_task, validate_contract

MINIMAL_BASE = """Sistema: PLANES
Funcionalidade: Tela de Modelagem
Tipo: Evolução

COMO analista,
QUERO ordenar linhas,
PARA facilitar a análise.

1. Critérios de Aceite

Cenário 1: Caso simples
  Dado que existe uma linha
  Quando a tela for exibida
  Então a linha aparece [RN01]

2. Regras de Negócio

RN01 – Regra simples de exibição.
"""

ROUTING_SECTION = """
9. Roteamento

Papel: reviewer
Capacidades obrigatórias: coding, patch
Capacidades preferenciais: tests, review
Providers permitidos: anthropic
Providers proibidos: local-devcli
Budget tokens: 150000
Budget USD: 3.50
Budget segundos: 600
Política de fallback: fallback_route
Máximo de routes: 4
Review independente: sim
"""


def test_routing_defaults_when_section_absent():
    contract = compile_task(MINIMAL_BASE)
    routing = contract["routing"]
    assert routing["state"] == "unspecified"
    assert routing["role"] == "executor"
    assert routing["fallback_policy"] == "block"
    assert routing["max_routes"] == 1
    assert routing["independent_review"] is False
    assert routing["budget"]["state"] == "unspecified"

    result = validate_contract(contract)
    assert any("routing" in w for w in result["warnings"])


def test_routing_section_is_parsed():
    contract = compile_task(MINIMAL_BASE + ROUTING_SECTION)
    routing = contract["routing"]
    assert routing["state"] == "declared"
    assert routing["role"] == "reviewer"
    assert routing["role"] in ROUTING_ROLES
    assert routing["required_capabilities"] == ["coding", "patch"]
    assert routing["preferred_capabilities"] == ["tests", "review"]
    assert routing["allowed_providers"] == ["anthropic"]
    assert routing["denied_providers"] == ["local-devcli"]
    assert routing["budget"] == {"tokens": 150000, "usd": 3.5, "seconds": 600, "state": "declared"}
    assert routing["fallback_policy"] == "fallback_route"
    assert routing["max_routes"] == 4
    assert routing["independent_review"] is True


def test_routing_unknown_role_falls_back_to_default_role():
    text = MINIMAL_BASE + "\n9. Roteamento\n\nPapel: astronaut\n"
    contract = compile_task(text)
    assert contract["routing"]["role"] == "executor"


def test_routing_section_is_excluded_from_raw_sections_dump():
    contract = compile_task(MINIMAL_BASE + ROUTING_SECTION)
    names = {section["name"] for section in contract["raw_sections"]}
    assert "routing" not in names


def test_routing_hash_changes_when_routing_section_changes():
    contract1 = compile_task(MINIMAL_BASE)
    contract2 = compile_task(MINIMAL_BASE + ROUTING_SECTION)
    assert contract1["contract_hash"] != contract2["contract_hash"]
