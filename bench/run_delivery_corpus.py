"""Run the deterministic, provider-free task-delivery corpus."""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from simplicio.execution_contract import ContractCompilationError, compile_execution_contract
from simplicio.task_spec import SourceRef, TaskSpecValidationError, parse_task_document

RESULTS_JSON = Path(__file__).resolve().parent / "results_delivery_corpus.json"
RESULTS_MD = Path(__file__).resolve().parent / "results_delivery_corpus.md"


@dataclass(frozen=True)
class CorpusCase:
    case_id: str
    text: str
    expected: str = "pass"


_VALID = """Sistema: PLANES
Funcionalidade: Ordenacao de linhas
Tipo: Evolucao

COMO analista, QUERO ordenar linhas, PARA analisar os dados.

1. Criterios de Aceite

Cenario 1: Ordenacao
  Dado que existem linhas
  Quando a tela for exibida
  Entao as linhas devem estar ordenadas [RN01]

2. Regras de Negocio

RN01 - Ordenar por data crescente.

3. Sinais de Impacto

Frontend: sim
Backend: nao
"""

_MINIMAL = """Sistema: app
Funcionalidade: endpoint
Tipo: Evolucao

COMO usuario, QUERO consultar dados, PARA tomar uma decisao.

1. Criterios de Aceite

Cenario 1: Consulta
  Dado que o recurso existe
  Quando eu consultar
  Entao recebo o recurso

2. Sinais de Impacto

Backend: sim
"""

_NEGATIVE = """texto sem sistema, funcionalidade ou criterios estruturados"""

CORPUS = (
    CorpusCase("planes-ordering", _VALID),
    CorpusCase("minimal-explicit-target", _MINIMAL),
    CorpusCase("full-stack-ambiguous", _VALID.replace("Backend: nao", "Backend: possivel")),
    CorpusCase(
        "ui-prototype-attachment", _VALID + "\n4. Prototipos\n\n![ui](https://example.invalid/ui.png)\n"
    ),
    CorpusCase("backend-only", _MINIMAL),
    CorpusCase("dag-batch", _VALID + "\n5. Dependencias\n\n- task-a\n- task-b depende de task-a\n"),
    CorpusCase("blocked-batch", _VALID + "\n5. Dependencias\n\n- task-a bloqueada por dependencia ausente\n"),
    CorpusCase(
        "nfr-missing-dependency",
        _VALID + "\n3. Requisitos Nao Funcionais\n\nDisponibilidade a definir.\n",
    ),
    CorpusCase("monorepo-multi-repo", _VALID + "\n6. Dependencias\n\n- repositorio web\n- repositorio api\n"),
    CorpusCase("contradictory-acceptance", _NEGATIVE, expected="fail"),
)


def run_corpus(cases: tuple[CorpusCase, ...] = CORPUS) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for case in cases:
        started = time.perf_counter()
        error = ""
        status = "passed"
        ac_count = 0
        try:
            document = parse_task_document(case.text, source=SourceRef(kind="corpus", locator=case.case_id))
            if len(document.tasks) != 1:
                raise ValueError(f"expected one task, got {len(document.tasks)}")
            task = document.tasks[0]
            ac_count = len(task.acceptance_criteria)
            compile_execution_contract(task)
        except (ContractCompilationError, TaskSpecValidationError, ValueError) as exc:
            status = "failed"
            error = str(exc)
        outcome_ok = (status == "passed") == (case.expected == "pass")
        rows.append(
            {
                "case_id": case.case_id,
                "expected": case.expected,
                "status": status,
                "outcome_ok": outcome_ok,
                "acceptance_criteria": ac_count,
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                "error": error,
            }
        )
    passed = sum(bool(row["outcome_ok"]) for row in rows)
    total = len(rows)
    return {
        "benchmark": "delivery-corpus",
        "schema": "simplicio.dev-cli.delivery-corpus/v1",
        "proof_kind": "deterministic-provider-free",
        "provider": "none",
        "runtime_identity_verified": False,
        "date": time.strftime("%Y-%m-%d"),
        "environment": {"python": sys.version.split()[0], "platform": platform.platform()},
        "matrix": {"cases": total, "expected_positive": sum(item.expected == "pass" for item in cases)},
        "metrics": {
            "outcome_accuracy": passed / total if total else 0.0,
            "cases_passed": passed,
            "cases_total": total,
        },
        "release_gates": {
            "deterministic_corpus_complete": passed == total,
            "runtime_identity_verified": False,
            "live_provider_matrix": False,
            "release_ready": False,
        },
        "missing_release_evidence": [
            "GPT-5.4 medium via Simplicio Runtime live lane",
            "runtime+loop+dev-cli cross-repo receipts",
            "Windows/Linux live matrix",
        ],
        "cases": rows,
    }


def write_reports(result: dict[str, Any], json_path: Path = RESULTS_JSON, md_path: Path = RESULTS_MD) -> None:
    json_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    summary = result["metrics"]
    md_path.write_text(
        "\n".join(
            [
                "# Delivery Corpus",
                "",
                f"- proof_kind: `{result['proof_kind']}`",
                f"- outcomes: {summary['cases_passed']}/{summary['cases_total']}",
                "- deterministic_corpus_complete: "
                f"`{result['release_gates']['deterministic_corpus_complete']}`",
                f"- release_ready: `{result['release_gates']['release_ready']}`",
                "",
                "The live provider/runtime lane is intentionally not inferred from this report.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-output", type=Path, default=RESULTS_JSON)
    parser.add_argument("--md-output", type=Path, default=RESULTS_MD)
    args = parser.parse_args(argv)
    result = run_corpus()
    write_reports(result, args.json_output, args.md_output)
    sys.stdout.write(json.dumps(result["metrics"], sort_keys=True) + "\n")
    return 0 if result["release_gates"]["deterministic_corpus_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
