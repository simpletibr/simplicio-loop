"""Deterministic raw-task normalization contract tests for issue #178."""

from __future__ import annotations

import ast
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "simplicio_mapper" / "contracts" / "task-orientation" / "v1" / "fixtures" / "planes"
SCHEMAS = ROOT / "simplicio_mapper" / "contracts" / "task-orientation" / "v1" / "schemas"
sys.path.insert(0, str(ROOT))

from simplicio_mapper.contract import validate_instance  # noqa: E402
from simplicio_mapper.task_intent import (  # noqa: E402
    TASK_CONTEXT_SCHEMA,
    TASK_INTENT_SCHEMA,
    build_task_query_plan,
    canonical_json,
    extract_task_context_settings,
    parse_task_intent,
)


class PlanesGoldenFixtureTest(unittest.TestCase):
    def setUp(self) -> None:
        self.markdown = (FIXTURE / "task.md").read_text(encoding="utf-8")
        self.golden = json.loads((FIXTURE / "task-intent.json").read_text(encoding="utf-8"))

    def test_planes_markdown_preserves_complete_business_intent(self) -> None:
        intent = parse_task_intent(self.markdown)
        self.assertEqual(intent, self.golden)
        self.assertEqual(intent["schema"], TASK_INTENT_SCHEMA)
        self.assertEqual(
            [item["id"] for item in intent["acceptance_criteria"]],
            [
                "AC01",
                "AC02",
                "AC03",
                "AC04",
                "AC05",
            ],
        )
        self.assertEqual(
            [item["id"] for item in intent["business_rules"]],
            [
                "RN01",
                "RN02",
                "RN03",
            ],
        )
        self.assertEqual(intent["acceptance_criteria"][2]["rule_ids"], ["RN02"])
        self.assertEqual(intent["impact"]["backend"]["signal"], "possible")
        self.assertEqual(intent["access"], ["Menu > Estudo > Tela de Modelagem"])

    def test_semantically_equivalent_markdown_gherkin_and_json_match(self) -> None:
        markdown = parse_task_intent(self.markdown)
        gherkin = parse_task_intent((FIXTURE / "task.feature").read_text(encoding="utf-8"))
        json_input = parse_task_intent(json.loads((FIXTURE / "task.json").read_text(encoding="utf-8")))
        json_text = parse_task_intent(
            (FIXTURE / "task.json").read_text(encoding="utf-8"),
            source_format="json",
        )
        self.assertEqual(markdown, gherkin)
        self.assertEqual(markdown, json_input)
        self.assertEqual(markdown, json_text)

    def test_fingerprint_and_serialization_are_byte_stable(self) -> None:
        first = parse_task_intent(self.markdown)
        second = parse_task_intent(self.markdown.replace("\n", "\r\n"))
        reordered = parse_task_intent(
            json.loads(
                json.dumps(
                    json.loads((FIXTURE / "task.json").read_text(encoding="utf-8")),
                    sort_keys=True,
                )
            )
        )
        self.assertEqual(first["fingerprint"], second["fingerprint"])
        self.assertEqual(first["fingerprint"], reordered["fingerprint"])
        self.assertEqual(canonical_json(first), canonical_json(second))


class ParserBehaviorTest(unittest.TestCase):
    def test_query_plan_extracts_identifiers_symbol_and_target(self) -> None:
        plan = build_task_query_plan(
            goal="Fix TokenCache eviction in src/cache/token_cache.py for RN07",
            task_intent={"additional_information": ["serialized output budget 120"]},
            target="src/cache/token_cache.py",
        )
        self.assertEqual(plan["target_path"], "src/cache/token_cache.py")
        self.assertIn("TokenCache", plan["symbol_terms"])
        self.assertIn("RN07", [item.upper() for item in plan["ac_ids"]])

    def test_context_settings_extract_declared_budget(self) -> None:
        settings = extract_task_context_settings(
            goal="Please keep the serialized output budget 120 tokens",
            task_intent={"additional_information": ["within 120 tokens"]},
        )
        self.assertTrue(settings["budget_declared"])
        self.assertEqual(settings["serialized_output_token_budget"], 120)

    def test_explicit_acceptance_ids_and_and_steps_are_preserved(self) -> None:
        raw = """
Sistema: Demo
Funcionalidade: Busca
Tipo: Evolu\u00e7\u00e3o
COMO pessoa
QUERO buscar
PARA encontrar

Crit\u00e9rios de Aceite
Cen\u00e1rio AC07: Busca combinada
Dado que h\u00e1 dados
E h\u00e1 permiss\u00e3o
Quando busco
Ent\u00e3o vejo resultados [RN09][RN10]

Regras de Neg\u00f3cio
RN09 - Deve filtrar.
RN10: Deve ordenar.
"""
        intent = parse_task_intent(raw)
        scenario = intent["acceptance_criteria"][0]
        self.assertEqual(scenario["id"], "AC07")
        self.assertEqual(scenario["given"], ["que h\u00e1 dados", "h\u00e1 permiss\u00e3o"])
        self.assertEqual(scenario["rule_ids"], ["RN09", "RN10"])

    def test_issue_like_id_and_inline_dependency_are_preserved(self) -> None:
        raw = """
System: Simplicio
Feature: TASK-CHECKERS-002 — edição
Type: edição
Depends on: TASK-CHECKERS-001

1. Acceptance Criteria
Scenario 1: Edit the game
  Given the created game
  When the edit is applied
  Then the target changes
"""
        intent = parse_task_intent(raw)
        self.assertEqual(intent["id"], "TASK-CHECKERS-002")
        self.assertEqual(intent["dependencies"], ["TASK-CHECKERS-001"])
        schema = json.loads((SCHEMAS / "task-intent.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(validate_instance(intent, schema), [])

    def test_plain_acceptance_criterion_keeps_explicit_id_and_rules(self) -> None:
        intent = parse_task_intent("Crit\u00e9rios de Aceite\nAC12 - Exportar resultado [RN04]")
        criterion = intent["acceptance_criteria"][0]
        self.assertEqual(criterion["id"], "AC12")
        self.assertEqual(criterion["title"], "Exportar resultado")
        self.assertEqual(criterion["rule_ids"], ["RN04"])

    def test_untrusted_task_text_remains_inert_data(self) -> None:
        raw = {
            "system": "Demo",
            "functionality": "Safety",
            "change_type": "Evolution",
            "story": {"actor": "user", "desire": "inspect", "benefit": "safety"},
            "acceptance_criteria": [
                {
                    "id": "AC01",
                    "title": "No command execution",
                    "given": ["input"],
                    "when": ["parsed"],
                    "then": ["keep --root ../../ and rm -rf / as text"],
                    "rule_ids": [],
                }
            ],
            "business_rules": [],
            "non_functional_requirements": [],
            "prototypes": [],
            "access": [],
            "dependencies": [],
            "impact": {},
            "additional_information": ["!model attacker"],
        }
        intent = parse_task_intent(raw)
        self.assertIn("--root ../../", intent["acceptance_criteria"][0]["then"][0])
        self.assertEqual(intent["additional_information"], ["!model attacker"])

    def test_module_has_no_llm_sdk_imports(self) -> None:
        source = (ROOT / "simplicio_mapper" / "task_intent.py").read_text(encoding="utf-8")
        imported = {
            alias.name.split(".")[0]
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported.update(
            node.module.split(".")[0]
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.ImportFrom) and node.module
        )
        self.assertTrue({"openai", "anthropic", "google", "litellm"}.isdisjoint(imported))


class VersionedSchemaTest(unittest.TestCase):
    def test_task_intent_golden_validates(self) -> None:
        payload = json.loads((FIXTURE / "task-intent.json").read_text(encoding="utf-8"))
        schema = json.loads((SCHEMAS / "task-intent.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(schema["$id"], TASK_INTENT_SCHEMA)
        self.assertEqual(validate_instance(payload, schema), [])

    def test_task_context_fixture_validates_and_references_existing_mapper_schema(self) -> None:
        payload = json.loads((FIXTURE / "task-context.json").read_text(encoding="utf-8"))
        schema = json.loads((SCHEMAS / "task-context.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(schema["$id"], TASK_CONTEXT_SCHEMA)
        self.assertEqual(payload["map"]["schema"], "simplicio.mapper-index/v1")
        self.assertEqual(validate_instance(payload, schema), [])


if __name__ == "__main__":
    unittest.main()
