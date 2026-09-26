from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from simplicio import pipeline
from simplicio.cli import main
from simplicio.commands import intake as intake_cmd
from simplicio.commands import intake as intake_module
from simplicio.task_spec import (
    TASK_SPEC_SCHEMA,
    SourceRef,
    TaskSpecValidationError,
    parse_task_document,
)

PLANES = """Sistema: PLANES
Funcionalidade: Tela de Modelagem — Ordenação de linhas
Tipo: Evolução

COMO analista do ONS,
QUERO que as linhas sejam ordenadas por tipo e data,
PARA que a visualização siga uma ordem lógica.

1. Critérios de Aceite

Cenário 1: Estrutural aparece primeiro
  Dado que a usina possui linhas do tipo estrutural, temporal e modelagem
  Quando a tela de modelagem for exibida
  Então a linha do tipo estrutural deve aparecer primeiro [RN01]

Cenário 2: Temporal e modelagem ordenados por data de início
  Dado que a usina possui múltiplas linhas dos tipos temporal e modelagem
  Quando a tela de modelagem for exibida
  Então as linhas devem ser ordenadas do mais antigo para o mais novo [RN02]

Cenário 3: Temporal e modelagem se misturam pela data
  Dado que há uma temporal em 01/08 e uma modelagem em 01/07
  Quando a tela de modelagem for exibida
  Então a modelagem deve aparecer antes da temporal [RN02]

Cenário 4: Ordenação por usina em ordem alfabética
  Dado que existem múltiplas usinas
  Quando a tela for exibida
  Então as usinas devem estar em ordem alfabética [RN03]

Cenário 5: Regras de ordenação combinadas
  Dado que existem múltiplas usinas com múltiplas linhas
  Quando a tela for exibida
  Então deve respeitar usina, estrutural e data [RN01][RN02][RN03]

2. Regras de Negócio

RN01 – Dentro de cada usina, a linha estrutural aparece primeiro.
RN02 – Temporal e modelagem são ordenadas por data de início.
RN03 – As usinas são exibidas em ordem alfabética.

3. Requisitos Não Funcionais

Nenhum requisito não-funcional identificado — validar com o time.

4. Protótipos

![ordenação](https://example.invalid/prototipo.png)

5. Acesso

Menu > Estudo > Tela de Modelagem

6. Dependências

Nenhuma dependência identificada — validar com o time.

7. Sinais de Impacto

Frontend: ✓ (ajuste na listagem)
Backend: Possível (a ordenação pode vir do backend — a definir)
Banco: ✗
Integrações: ✗

8. Informações Adicionais

- O problema foi identificado no PMO de Julho em Produção.
- Sem pendências.
"""


def ns(**kwargs: object) -> argparse.Namespace:
    return argparse.Namespace(**kwargs)


def test_planes_golden_preserves_ac_rules_hypotheses_and_human_gates() -> None:
    document = parse_task_document(PLANES, source=SourceRef(kind="argument"))
    payload = document.to_dict()

    assert payload["schema"] == TASK_SPEC_SCHEMA
    assert payload["compatibility"]["minimum_consumer_major"] == 2
    assert payload["compatibility"]["consumers"] == [
        "simplicio-runtime",
        "simplicio-loop",
        "simplicio-mcp",
    ]
    assert len(payload["tasks"]) == 1
    task = payload["tasks"][0]
    assert task["schema"] == TASK_SPEC_SCHEMA
    assert task["system"] == "PLANES"
    assert task["functionality"] == "Tela de Modelagem — Ordenação de linhas"
    assert task["task_type"] == "Evolução"
    assert task["language"] == "pt-BR"
    assert [criterion["id"] for criterion in task["acceptance_criteria"]] == [
        "AC1",
        "AC2",
        "AC3",
        "AC4",
        "AC5",
    ]
    assert [rule["id"] for rule in task["business_rules"]] == ["RN01", "RN02", "RN03"]
    assert task["acceptance_criteria"][4]["business_rule_refs"] == ["RN01", "RN02", "RN03"]
    assert task["impact_signals"]["backend"]["status"] == "possible"
    assert task["impact_signals"]["backend"]["hypothesis"] is True
    assert task["impact_signals"]["frontend"]["status"] == "yes"
    assert task["impact_signals"]["banco"]["status"] == "no"
    assert len(task["uncertainties"]) == 3
    assert len(task["human_gates"]) == 3
    assert task["prototypes"][0]["references"] == ["https://example.invalid/prototipo.png"]
    assert task["attachments"][0]["references"] == ["https://example.invalid/prototipo.png"]
    assert task["navigation"][0]["text"] == "Menu > Estudo > Tela de Modelagem"
    assert task["original_text"] == PLANES

    ac_span = task["acceptance_criteria"][0]["source_span"]
    assert PLANES[ac_span["start"] : ac_span["end"]] == task["acceptance_criteria"][0]["original_text"]
    assert parse_task_document(PLANES).tasks[0].source_hash == document.tasks[0].source_hash


def test_three_cards_produce_three_ordered_task_specs_with_own_hashes() -> None:
    raw = """# Delivery backlog

## Card 1
Funcionalidade: Login
COMO usuário
QUERO entrar
PARA acessar o sistema

## Card 2
Feature: Search
AS A visitor
I WANT to search
SO THAT I find content

## Card 3
Funcionalidade: Exportação
COMO analista
QUERO exportar CSV
PARA analisar offline
"""
    document = parse_task_document(raw)

    assert len(document.tasks) == 3
    assert [task.functionality for task in document.tasks] == ["Login", "Search", "Exportação"]
    assert [task.language for task in document.tasks] == ["pt-BR", "en", "pt-BR"]
    assert len({task.source_hash for task in document.tasks}) == 3
    assert [task.source_span["start"] for task in document.tasks] == sorted(
        task.source_span["start"] for task in document.tasks
    )
    for task in document.tasks:
        span = task.source_span
        assert raw[span["start"] : span["end"]] == task.original_text


def test_minimal_card_and_missing_sections_are_valid() -> None:
    document = parse_task_document("Funcionalidade: Atualizar título\nTipo: Evolução\n")
    task = document.tasks[0]

    assert task.functionality == "Atualizar título"
    assert task.acceptance_criteria == []
    assert task.business_rules == []
    assert task.non_functional_requirements == []


def test_english_gwt_and_attachment_are_preserved() -> None:
    raw = """System: PORTAL
Feature: Download invoice
Type: Enhancement
AS A customer
I WANT to download an invoice
SO THAT I can archive it

Acceptance Criteria
Scenario 1: PDF download
  Given a paid invoice
  When I select download
  Then a PDF is returned [RN01]

Business Rules
RN01 - Only paid invoices are downloadable.

Attachments
[invoice sample](https://example.invalid/invoice.pdf)

Dependencies
- Possible billing API contract, to be confirmed
"""
    task = parse_task_document(raw).tasks[0]

    assert task.language == "en"
    assert task.acceptance_criteria[0]["given"] == "a paid invoice"
    assert task.business_rules[0]["id"] == "RN01"
    assert task.attachments[0]["references"] == ["https://example.invalid/invoice.pdf"]
    assert task.dependencies[0]["kind"] == "inferred"
    assert task.dependencies[0]["hypothesis"] is True
    assert task.uncertainties[0]["marker"] == "to be confirmed"


@pytest.mark.parametrize("encoding", ["utf-8-sig", "cp1252"])
def test_file_input_supports_utf8_and_windows_encoding(tmp_path, capsys, encoding: str) -> None:
    path = tmp_path / f"task-{encoding}.md"
    path.write_bytes("Funcionalidade: Revisão\r\nTipo: Evolução\r\n".encode(encoding))

    code = intake_cmd.run(
        ns(
            text=None,
            file=str(path),
            stdin=False,
            source_url=None,
            validate_only=True,
            json=True,
        )
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["valid"] is True
    assert payload["task_count"] == 1
    task = payload["task_spec"]["tasks"][0]
    assert task["functionality"] == "Revisão"
    assert task["source"]["encoding"] == ("utf-8" if encoding == "utf-8-sig" else "cp1252")


def test_url_input_fetches_task_and_preserves_source_metadata(monkeypatch, capsys) -> None:
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return b"Funcionalidade: URL task\nTipo: Evolu\xe7\xe3o\n"

    def fake_urlopen(request, *, timeout):
        assert request.full_url == "https://example.invalid/task.md"
        assert timeout == 10
        return Response()

    monkeypatch.setattr(intake_module, "urlopen", fake_urlopen)
    code = intake_module.run(
        ns(
            text=None,
            file=None,
            stdin=False,
            url="https://example.invalid/task.md",
            source_url=None,
            validate_only=True,
            json=True,
        )
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    task = payload["task_spec"]["tasks"][0]
    assert task["functionality"] == "URL task"
    assert task["source"]["kind"] == "url"
    assert task["source"]["locator"] == "https://example.invalid/task.md"
    assert task["source"]["encoding"] == "cp1252"


def test_url_input_rejects_non_http_scheme(capsys) -> None:
    code = intake_module.run(
        ns(
            text=None,
            file=None,
            stdin=False,
            url="file:///tmp/task.md",
            source_url=None,
            validate_only=True,
            json=True,
        )
    )

    assert code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["valid"] is False
    assert "absolute http:// or https://" in payload["errors"][0]


def test_cli_accepts_complete_task_without_target_criteria_or_stack(capsys) -> None:
    code = main(["intake", PLANES, "--validate-only", "--json"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["valid"] is True
    assert len(payload["task_spec"]["tasks"][0]["acceptance_criteria"]) == 5


def test_intake_can_compile_execution_contract_json(capsys) -> None:
    code = intake_cmd.run(
        ns(
            text="Funcionalidade: Atualizar título\nTipo: Evolução\n",
            file=None,
            stdin=False,
            source_url=None,
            validate_only=False,
            contract=True,
            execution_mode=False,
            json=True,
        )
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "simplicio.intake-result/v1"
    assert payload["contracts"][0]["schema"] == "simplicio.execution-contract/v1"
    assert payload["contracts"][0]["execution_ready"] is False


def test_intake_plan_only_is_blocked_without_mapper_and_never_dispatches(capsys) -> None:
    code = intake_cmd.run(
        ns(
            text="Funcionalidade: Atualizar título\nTipo: Evolução\n",
            file=None,
            stdin=False,
            source_url=None,
            validate_only=False,
            contract=False,
            execution_mode=False,
            plan_only=True,
            json=True,
        )
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "simplicio.plan-preview/v1"
    assert payload["dispatch"] is False
    assert payload["mutated"] is False
    assert payload["status"] == "blocked"
    assert payload["task_batch"]["task_count"] == 1
    assert payload["task_batch"]["tasks"][0]["id"] == payload["task_spec"]["tasks"][0]["task_id"]


def test_intake_plan_only_emits_multi_task_batch_preview_with_dependency_edges(capsys) -> None:
    raw = """## Card 1
Funcionalidade: Login
Tipo: Evolução

## Card 2
Funcionalidade: Reports
Tipo: Evolução

Dependências
- depends on: Login
"""
    code = intake_cmd.run(
        ns(
            text=raw,
            file=None,
            stdin=False,
            source_url=None,
            validate_only=False,
            contract=False,
            execution_mode=False,
            plan_only=True,
            json=True,
        )
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    first_id = payload["task_spec"]["tasks"][0]["task_id"]
    assert payload["task_batch"]["task_count"] == 2
    assert payload["task_batch"]["ready"] == [first_id]
    assert payload["task_batch"]["tasks"][1]["depends_on"] == [first_id]


def test_intake_can_persist_frozen_batch_for_later_resume(tmp_path, capsys) -> None:
    raw = """## Card 1
Funcionalidade: Login
Tipo: Evolução

## Card 2
Funcionalidade: Reports
Tipo: Evolução

Dependências
- depends on: Login
"""
    batch_path = tmp_path / ".simplicio-loop" / "task_batch.json"
    code = intake_cmd.run(
        ns(
            text=raw,
            file=None,
            stdin=False,
            source_url=None,
            validate_only=False,
            contract=True,
            execution_mode=False,
            plan_only=False,
            batch_path=str(batch_path),
            json=True,
        )
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["batch_path"] == str(batch_path.resolve())
    persisted = json.loads(batch_path.read_text(encoding="utf-8"))
    assert persisted["schema"] == "simplicio.dev-cli.task-batch/v1"
    assert [task["status"] for task in persisted["tasks"]] == ["pending", "pending"]


def test_malformed_input_is_actionable_and_never_calls_generation(monkeypatch, capsys) -> None:
    called = False

    def fail_if_called(*args: object, **kwargs: object) -> str:
        nonlocal called
        called = True
        raise AssertionError("LLM/operator generation must not run during intake")

    monkeypatch.setattr(pipeline, "generate", fail_if_called)
    code = intake_cmd.run(
        ns(
            text="## Card 1\n",
            file=None,
            stdin=False,
            source_url=None,
            validate_only=True,
            json=True,
        )
    )

    assert code == 2
    assert called is False
    payload = json.loads(capsys.readouterr().out)
    assert payload["valid"] is False
    assert "no recognizable functionality" in " ".join(payload["errors"])
    assert payload["required_schema"] == TASK_SPEC_SCHEMA
    assert payload["print_contract_example"] == "simplicio-py intake --print-contract-example"


def test_empty_and_ambiguous_sources_fail_with_actionable_diagnostics(capsys) -> None:
    with pytest.raises(TaskSpecValidationError, match="input is empty"):
        parse_task_document("")

    code = intake_cmd.run(
        ns(
            text="Funcionalidade: X",
            file="task.md",
            stdin=False,
            source_url=None,
            validate_only=False,
            json=True,
        )
    )
    assert code == 2
    payload = json.loads(capsys.readouterr().out)
    assert "choose exactly one input source" in payload["errors"][0]


def test_incomplete_gwt_and_duplicate_ac_ids_are_rejected() -> None:
    incomplete = """Feature: Search
Acceptance Criteria
Scenario 1: Search works
  Given indexed content
  When I search
"""
    with pytest.raises(TaskSpecValidationError, match="without complete Given/When/Then"):
        parse_task_document(incomplete)

    duplicate = """Feature: Search
Acceptance Criteria
Scenario 1: Search works
  Given indexed content
  When I search
  Then results appear
Scenario 1: Search remains stable
  Given indexed content
  When I search again
  Then results appear again
"""
    with pytest.raises(TaskSpecValidationError, match="duplicate acceptance criterion IDs"):
        parse_task_document(duplicate)


def test_crlf_acceptance_source_span_preserves_exact_original_bytes() -> None:
    raw = (
        "Feature: Search\r\nAcceptance Criteria\r\nScenario 1: Search works\r\n"
        "  Given indexed content\r\n  When I search\r\n  Then results appear\r\n"
    )
    criterion = parse_task_document(raw).tasks[0].acceptance_criteria[0]
    span = criterion["source_span"]

    assert criterion["original_text"].count("\r\n") == 3
    assert raw[span["start"] : span["end"]] == criterion["original_text"]


def _write_mapper_artifacts(root: Path, *, files: list[dict], precedents: list[dict]) -> None:
    simplicio_dir = root / ".simplicio-loop"
    simplicio_dir.mkdir(parents=True, exist_ok=True)
    (simplicio_dir / "project-map.json").write_text(
        json.dumps(
            {
                "schema": "simplicio.project-map/v1",
                "version": 1,
                "generated_at": "2026-07-11T00:00:00.000Z",
                "product": {"name": "fixture", "stack": "python", "project_mode": "root"},
                "files": files,
                "entry_points": [item["path"] for item in files],
                "test_files": [],
                "config_files": [],
                "modules": [{"name": "src", "files": [item["path"] for item in files], "roles": ["source"]}],
                "recent_changes": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (simplicio_dir / "precedent-index.json").write_text(
        json.dumps(
            {
                "schema": "simplicio.precedent-index/v1",
                "version": 1,
                "generated_at": "2026-07-11T00:00:00.000Z",
                "items": precedents,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_intake_plan_only_discovers_execution_plan_without_target_or_stack(
    tmp_path, monkeypatch, capsys
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text(
        """def greet(name: str) -> str:
    return f'hello, {name}'
""",
        encoding="utf-8",
    )
    _write_mapper_artifacts(
        tmp_path,
        files=[
            {
                "path": "src/app.py",
                "language": "python",
                "file_hash": "0" * 64,
                "size_bytes": 64,
                "git_status": "clean",
                "roles": ["entry_point"],
                "exports": ["greet", "farewell"],
                "importance": 0.95,
            }
        ],
        precedents=[
            {
                "id": "prec-1",
                "path": "src/app.py",
                "line": 1,
                "summary": "greet helper lives here",
            }
        ],
    )

    def fake_map_ask(_root, verb, arg=""):
        if arg != "src/app.py":
            return []
        return {
            "impact": [{"caller": "src/app.py"}],
            "tests-for": [{"test_path": "tests/test_app.py"}],
            "callers": [],
            "flows": [],
            "rules": [{"rule": "farewell helper remains local"}],
        }[verb]

    monkeypatch.setattr("simplicio.plan_discovery.map_ask", fake_map_ask)
    monkeypatch.setattr("simplicio.mapper.map_ask", fake_map_ask)
    code = intake_cmd.run(
        ns(
            text="""System: APP
Feature: Add farewell helper
Type: Enhancement
AS A maintainer
I WANT to add a farewell helper
SO THAT greetings and farewells live together

Acceptance Criteria
Scenario 1: helper exists
  Given the greetings module
  When I request a farewell
  Then a farewell helper is returned [RN01]

Business Rules
RN01 - Keep greeting and farewell helpers in the same module.

Impact Signals
Backend: ✓
Frontend: ✗
""",
            file=None,
            stdin=False,
            source_url=None,
            validate_only=False,
            contract=False,
            execution_mode=False,
            plan_only=True,
            json=True,
            root=str(tmp_path),
        )
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "planned"
    assert payload["execution_plan"]["schema"] == "simplicio.orientation-plan/v1"
    assert payload["execution_plan"]["slices"][0]["targets"] == ["src/app.py"]
    assert payload["execution_plan"]["slices"][0]["verify_command"] == "pytest tests/test_app.py"
    assert payload["task_batch"]["task_count"] == 1


def test_intake_plan_only_fails_closed_when_target_discovery_is_ambiguous(
    tmp_path, monkeypatch, capsys
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "billing.py").write_text(
        """def download_invoice():
    return b''
""",
        encoding="utf-8",
    )
    (tmp_path / "src" / "invoice.py").write_text(
        """def download_invoice():
    return b''
""",
        encoding="utf-8",
    )
    _write_mapper_artifacts(
        tmp_path,
        files=[
            {
                "path": "src/billing.py",
                "language": "python",
                "file_hash": "1" * 64,
                "size_bytes": 64,
                "git_status": "clean",
                "roles": ["entry_point"],
                "exports": ["download_invoice"],
                "importance": 0.90,
            },
            {
                "path": "src/invoice.py",
                "language": "python",
                "file_hash": "2" * 64,
                "size_bytes": 64,
                "git_status": "clean",
                "roles": ["entry_point"],
                "exports": ["download_invoice"],
                "importance": 0.90,
            },
        ],
        precedents=[{"id": "prec-1", "path": "src/billing.py", "line": 1, "summary": "billing download"}],
    )
    monkeypatch.setattr("simplicio.plan_discovery.map_ask", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("simplicio.mapper.map_ask", lambda *_args, **_kwargs: [])
    code = intake_cmd.run(
        ns(
            text="""Feature: Download invoice
Type: Enhancement
AS A customer
I WANT to download an invoice
SO THAT I can archive it

Acceptance Criteria
Scenario 1: PDF download
  Given a paid invoice
  When I select download
  Then a PDF is returned [RN01]

Business Rules
RN01 - Only paid invoices are downloadable.
""",
            file=None,
            stdin=False,
            source_url=None,
            validate_only=False,
            contract=False,
            execution_mode=False,
            plan_only=True,
            json=True,
            root=str(tmp_path),
        )
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "blocked"
    assert any("ambiguous" in item for item in payload["blockers"])


def test_intake_plan_only_fails_closed_when_tests_for_evidence_is_missing(
    tmp_path, monkeypatch, capsys
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text(
        """def greet(name: str) -> str:
    return f'hello, {name}'
""",
        encoding="utf-8",
    )
    _write_mapper_artifacts(
        tmp_path,
        files=[
            {
                "path": "src/app.py",
                "language": "python",
                "file_hash": "0" * 64,
                "size_bytes": 64,
                "git_status": "clean",
                "roles": ["entry_point"],
                "exports": ["greet"],
                "importance": 0.95,
            }
        ],
        precedents=[{"id": "prec-1", "path": "src/app.py", "line": 1, "summary": "greet helper lives here"}],
    )

    def fake_map_ask(_root, verb, arg=""):
        if arg != "src/app.py":
            return []
        return {
            "impact": [{"caller": "src/app.py"}],
            "tests-for": [],
            "callers": [],
            "flows": [],
            "rules": [{"rule": "keep helper local"}],
        }[verb]

    monkeypatch.setattr("simplicio.plan_discovery.map_ask", fake_map_ask)
    monkeypatch.setattr("simplicio.mapper.map_ask", fake_map_ask)
    code = intake_cmd.run(
        ns(
            text="""Feature: Add farewell helper
Type: Enhancement
AS A maintainer
I WANT to add a farewell helper
SO THAT greetings and farewells live together

Acceptance Criteria
Scenario 1: helper exists
  Given the greetings module
  When I request a farewell
  Then a farewell helper is returned [RN01]

Business Rules
RN01 - Keep greeting and farewell helpers in the same module.

Impact Signals
Backend: ✓
""",
            file=None,
            stdin=False,
            source_url=None,
            validate_only=False,
            contract=False,
            execution_mode=False,
            plan_only=True,
            json=True,
            root=str(tmp_path),
        )
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "blocked"
    # orientation_plan.py's diagnostic renders the missing mapper "tests-for"
    # evidence with the human-readable label "tests" (see
    # build_execution_plan's `missing.append("tests")`), not the raw verb
    # name — assert on the label that's actually emitted.
    assert any("missing" in item and "tests" in item for item in payload["blockers"])


def test_intake_print_contract_example_names_required_schema(capsys) -> None:
    code = intake_cmd.run(ns(print_contract_example=True, json=True))

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["required_schema"] == TASK_SPEC_SCHEMA
    assert payload["contract_schema"] == "simplicio.execution-contract/v1"
    assert "simplicio.task-spec/v2" in payload["example"]
    assert payload["print_contract_example"] == "simplicio-py intake --print-contract-example"


def test_intake_rejects_conventional_story_with_required_schema(capsys) -> None:
    story = """Add logout button

AS A signed-in user,
I WANT a logout action,
SO THAT I can end my session.

Acceptance criteria
- The header shows a logout button
- Clicking it clears the session
"""
    code = intake_cmd.run(
        ns(
            text=story,
            file=None,
            stdin=False,
            source_url=None,
            validate_only=False,
            contract=True,
            execution_mode=True,
            plan_only=True,
            json=True,
        )
    )

    assert code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["valid"] is False
    assert payload["required_schema"] == TASK_SPEC_SCHEMA
    assert payload["contract_schema"] == "simplicio.execution-contract/v1"
    assert "System:" in " ".join(payload["accepted_syntax"])
    assert "simplicio.task-spec/v2" in payload["example"]
    assert any(
        item in payload["errors"]
        for item in ("missing-field-system", "missing-field-task-type", "missing-acceptance-criteria")
    )


def test_intake_rejects_plain_language_with_required_schema(capsys) -> None:
    code = intake_cmd.run(
        ns(
            text="please add a logout button to the header",
            file=None,
            stdin=False,
            source_url=None,
            validate_only=True,
            json=True,
        )
    )

    assert code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["valid"] is False
    assert payload["required_schema"] == TASK_SPEC_SCHEMA
    assert "no recognizable functionality" in " ".join(payload["errors"])
    assert payload["print_contract_example"] == "simplicio-py intake --print-contract-example"
