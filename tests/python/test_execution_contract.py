from __future__ import annotations

from dataclasses import FrozenInstanceError
from hashlib import sha256
import json

import pytest

from simplicio.execution_contract import (
    ContractCompilationError,
    EvidenceReceipt,
    ExecutionBlockedError,
    SourceDriftError,
    compile_execution_contract,
    compile_execution_contracts,
)

PLANES_SOURCE = """Sistema: PLANES
Funcionalidade: Tela de Modelagem - Ordenacao de linhas
Tipo: Evolucao

Cenario 1: Estrutural aparece primeiro [RN01]
Cenario 2: Temporal e modelagem ordenados por data de inicio [RN02]
Cenario 3: Temporal e modelagem se misturam pela data [RN02]
Cenario 4: Ordenacao por usina em ordem alfabetica [RN03]
Cenario 5: Regras de ordenacao combinadas [RN01][RN02][RN03]

RN01 - Dentro de cada usina, a linha estrutural aparece primeiro e e unica por usina.
RN02 - Temporais e modelagem sao ordenadas por data de inicio, da mais antiga para a mais nova.
RN03 - Usinas devem ser exibidas em ordem alfabetica.

Nenhum requisito nao-funcional identificado na entrada - validar com o time.
Backend: Possivel - a definir.
"""


def _span(start: int, end: int) -> dict[str, int]:
    return {"start": start, "end": end, "start_line": 1, "end_line": 1}


def _planes_task() -> dict:
    acceptance_criteria = [
        {
            "id": "AC1",
            "title": "Estrutural aparece primeiro",
            "given": "a usina possui linhas estrutural, temporal e modelagem",
            "when": "a tela de modelagem for exibida",
            "then": "a linha estrutural aparece primeiro",
            "business_rule_refs": ["RN01"],
            "source_span": _span(1, 20),
            "original_text": "Cenario 1: Estrutural aparece primeiro [RN01]",
        },
        {
            "id": "AC2",
            "title": "Temporal e modelagem ordenados por data",
            "given": "existem varias linhas temporais e de modelagem",
            "when": "a tela de modelagem for exibida",
            "then": "as linhas sao ordenadas por data de inicio, da mais antiga para a mais nova",
            "business_rule_refs": ["RN02"],
            "source_span": _span(21, 40),
            "original_text": "Cenario 2: Temporal e modelagem por data [RN02]",
        },
        {
            "id": "AC3",
            "title": "Subtipos se misturam pela data",
            "given": "modelagem inicia antes de uma temporal",
            "when": "a tela for exibida",
            "then": "modelagem aparece antes, independentemente do subtipo",
            "business_rule_refs": ["RN02"],
            "source_span": _span(41, 60),
            "original_text": "Cenario 3: Temporal e modelagem se misturam [RN02]",
        },
        {
            "id": "AC4",
            "title": "Usinas em ordem alfabetica",
            "given": "existem varias usinas",
            "when": "a tela for exibida",
            "then": "as usinas aparecem em ordem alfabetica",
            "business_rule_refs": ["RN03"],
            "source_span": _span(61, 80),
            "original_text": "Cenario 4: Usinas em ordem alfabetica [RN03]",
        },
        {
            "id": "AC5",
            "title": "Regras combinadas",
            "given": "existem varias usinas e linhas",
            "when": "a tela for exibida",
            "then": "ordena usina, estrutural primeiro e demais linhas por data",
            "business_rule_refs": ["RN01", "RN02", "RN03"],
            "source_span": _span(81, 100),
            "original_text": "Cenario 5: Regras combinadas [RN01][RN02][RN03]",
        },
    ]
    return {
        "schema": "simplicio.task-spec/v2",
        "task_id": "planes-modeling-line-order",
        "source": {
            "kind": "text",
            "locator": "inline",
            "span": _span(0, len(PLANES_SOURCE)),
            "original_text": PLANES_SOURCE,
        },
        "source_hash": sha256(PLANES_SOURCE.strip().encode()).hexdigest(),
        "language": "pt-BR",
        "system": "PLANES",
        "functionality": "Tela de Modelagem - Ordenacao de linhas",
        "task_type": "Evolucao",
        "narrative": {
            "as_a": "analista do ONS",
            "i_want": "linhas ordenadas por tipo e data",
            "so_that": "a visualizacao siga uma ordem logica",
        },
        "acceptance_criteria": acceptance_criteria,
        "business_rules": [
            {
                "id": "RN01",
                "text": "Estrutural aparece primeiro; e unica por usina.",
                "source_span": _span(101, 120),
                "original_text": "RN01 - estrutural primeiro",
            },
            {
                "id": "RN02",
                "text": "Temporal e modelagem ordenam juntas por data de inicio crescente.",
                "source_span": _span(121, 140),
                "original_text": "RN02 - data crescente",
            },
            {
                "id": "RN03",
                "text": "Usinas aparecem em ordem alfabetica.",
                "source_span": _span(141, 160),
                "original_text": "RN03 - ordem alfabetica",
            },
        ],
        "non_functional_requirements": [
            {
                "text": "Nenhum requisito nao-funcional identificado - validar com o time",
                "source_span": _span(161, 180),
            }
        ],
        "prototypes": [{"text": "referencia visual do item fora de ordem"}],
        "attachments": [],
        "navigation": ["Menu", "Estudo", "Tela de Modelagem"],
        "dependencies": [],
        "impact_signals": {
            "frontend": {"status": "yes", "text": "ajuste na ordenacao"},
            "backend": {"status": "possible", "hypothesis": True, "text": "a definir"},
            "database": {"status": "no", "text": "sem impacto"},
        },
        "additional_information": ["Problema observado em producao"],
        "uncertainties": [],
        "human_gates": [],
        "source_span": _span(0, len(PLANES_SOURCE)),
        "original_text": PLANES_SOURCE,
    }


def test_planes_contract_preserves_requirements_and_combined_order() -> None:
    contract = compile_execution_contract(_planes_task())

    assert contract.schema == "simplicio.execution-contract/v1"
    assert [criterion.id for criterion in contract.acceptance_criteria] == [
        "AC1",
        "AC2",
        "AC3",
        "AC4",
        "AC5",
    ]
    assert [rule.id for rule in contract.business_rules] == ["RN01", "RN02", "RN03"]
    assert contract.acceptance_criteria[-1].business_rule_refs == ("RN01", "RN02", "RN03")
    assert all(criterion.verification_intents for criterion in contract.acceptance_criteria)
    for criterion in contract.acceptance_criteria:
        for intent in criterion.verification_intents:
            assert intent.positive
            assert intent.negative
            assert intent.edge
            assert intent.is_executable


def test_execution_contract_preserves_complete_task_spec_boundary_losslessly() -> None:
    task = _planes_task()
    task["verification_commands"] = [{"command": "pytest -q", "verifier": "pytest", "timeout_s": 42}]
    task["future_additive_field"] = {"owner": "loop", "enabled": True}
    expected = {**task, "schema": "simplicio.task-spec/v2"}

    contract = compile_execution_contract(task)
    payload = contract.to_dict()
    canonical = json.dumps(expected, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    assert payload["task_spec"] == expected
    assert payload["task_spec_hash"] == sha256(canonical.encode("utf-8")).hexdigest()
    assert contract.to_dict(include_contract_hash=False)["task_spec"] == expected
    assert payload["task_spec"]["verification_commands"] == task["verification_commands"]
    assert payload["task_spec"]["future_additive_field"] == task["future_additive_field"]


def test_planes_contract_surfaces_unspecified_decisions_and_hypotheses() -> None:
    contract = compile_execution_contract(_planes_task())
    gate_ids = {gate.id for gate in contract.human_gates if gate.blocking}

    assert {
        "decision-date-tie",
        "decision-date-missing-invalid",
        "decision-alphabetical-collation",
        "decision-multiple-structural",
        "nfr-validation-required",
        "impact-backend-undecided",
    } <= gate_ids
    assert any(hypothesis.subject == "impact.backend" for hypothesis in contract.hypotheses)
    assert contract.execution_ready is False
    with pytest.raises(ExecutionBlockedError):
        contract.assert_executable()


def test_placeholder_criteria_and_test_commands_are_rejected_in_execution_mode() -> None:
    task = _planes_task()
    task["criteria"] = "- true state\n- false state"
    task["test_command"] = "echo 'configure SIMPLICIO_TEST_CMD'"

    with pytest.raises(ContractCompilationError) as exc_info:
        compile_execution_contract(task, execution_mode=True)

    assert "placeholder criteria" in str(exc_info.value)
    assert "placeholder test command" in str(exc_info.value)


def test_traceability_json_has_full_chain_and_unreceipted_claims_stay_unverified() -> None:
    contract = compile_execution_contract(_planes_task())
    payload = contract.to_dict()
    ac5 = next(row for row in payload["traceability_matrix"] if row["acceptance_criterion"] == "AC5")

    assert ac5["business_rules"] == ["RN01", "RN02", "RN03"]
    assert set(ac5) >= {
        "acceptance_criterion",
        "business_rules",
        "files",
        "tests",
        "evidence",
        "status",
    }
    assert ac5["status"] == "UNVERIFIED"
    assert contract.claim_status("AC5") == "UNVERIFIED"

    measured = contract.with_receipt(
        "AC5",
        EvidenceReceipt(
            id="receipt-ac5-e2e",
            kind="test-output",
            uri="test-results/planes-ac5.json",
            digest="sha256:abc123",
        ),
        files=("src/modeling/order.ts",),
        tests=("tests/e2e/modeling-order.spec.ts::combined",),
    )
    assert measured.claim_status("AC5") == "MEASURED"
    assert contract.claim_status("AC5") == "UNVERIFIED"


@pytest.mark.parametrize("missing", ["RN02", "AC3"])
def test_source_coverage_turns_red_when_a_declared_rule_or_scenario_is_removed(missing: str) -> None:
    task = _planes_task()
    if missing.startswith("RN"):
        task["business_rules"] = [rule for rule in task["business_rules"] if rule["id"] != missing]
    else:
        task["acceptance_criteria"] = [ac for ac in task["acceptance_criteria"] if ac["id"] != missing]

    contract = compile_execution_contract(task)

    assert contract.execution_ready is False
    assert any(
        gate.id == f"source-coverage-{missing.lower()}" and gate.blocking for gate in contract.human_gates
    )


def test_source_hash_is_frozen_and_drift_requires_reanchor() -> None:
    contract = compile_execution_contract(_planes_task())

    assert contract.source_matches(PLANES_SOURCE)
    assert not contract.source_matches(PLANES_SOURCE + "\ntexto alterado")
    with pytest.raises(SourceDriftError):
        contract.assert_source_current(PLANES_SOURCE + "\ntexto alterado")
    with pytest.raises(FrozenInstanceError):
        contract.task_id = "changed"  # type: ignore[misc]


def test_duck_typed_task_and_document_batch_are_supported() -> None:
    class TaskSpec:
        def to_dict(self) -> dict:
            return _planes_task()

    contract = compile_execution_contract(TaskSpec())
    contracts = compile_execution_contracts(
        {"schema": "simplicio.task-spec/v2", "tasks": [_planes_task(), _planes_task()]}
    )

    assert contract.task_id == "planes-modeling-line-order"
    assert len(contracts) == 2
    assert all(item.task_id == "planes-modeling-line-order" for item in contracts)


def test_real_task_spec_parser_output_compiles_without_adapter() -> None:
    from simplicio.task_spec import parse_task_document

    raw = """Sistema: PLANES
Funcionalidade: Tela de Modelagem - Ordenacao
Tipo: Evolucao

1. Criterios de Aceite
Cenario 1: Estrutural primeiro
  Dado que existem linhas
  Quando a tela abrir
  Entao a estrutural aparece primeiro [RN01]

2. Regras de Negocio
RN01 - Estrutural aparece primeiro.
"""
    task_spec = parse_task_document(raw).tasks[0]

    contract = compile_execution_contract(task_spec)

    assert [criterion.id for criterion in contract.acceptance_criteria] == ["AC1"]
    assert [rule.id for rule in contract.business_rules] == ["RN01"]
    assert contract.source_matches(raw.replace("\n", "\r\n"))


def test_missing_fields_and_conflicting_ids_become_blocking_human_gates() -> None:
    task = _planes_task()
    task["system"] = None
    task["narrative"] = {}
    duplicate = dict(task["acceptance_criteria"][0])
    duplicate["then"] = "a linha estrutural aparece por ultimo"
    task["acceptance_criteria"].append(duplicate)

    contract = compile_execution_contract(task)
    gate_ids = {gate.id for gate in contract.human_gates if gate.unresolved}

    assert "missing-field-system" in gate_ids
    assert "missing-field-narrative-as-a" in gate_ids
    assert "missing-field-narrative-i-want" in gate_ids
    assert "missing-field-narrative-so-that" in gate_ids
    assert "contradiction-ac1" in gate_ids
