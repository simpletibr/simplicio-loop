"""Unit tests for simplicio_mapper.business (F3 business rules + glossary).

Run with: python3 -m unittest discover -s tests/python
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from simplicio_mapper.business import (  # noqa: E402
    BUSINESS_RULES_SCHEMA,
    build_business_rules,
    render_business_rules_markdown,
)
from simplicio_mapper.cli import main  # noqa: E402
from simplicio_mapper.mapper import build_artifacts  # noqa: E402


def _write(base: Path, rel: str, content: str) -> None:
    target = base / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


class BusinessRulesTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _app(self) -> Path:
        app_dir = self.dir / "app"
        _write(app_dir, "package.json", json.dumps({"name": "biz-app"}))
        _write(
            app_dir,
            "src/orders.py",
            "\n".join([
                "REQUEST_TIMEOUT = 30",
                "",
                "class OrderStatus(Enum):",
                "    PENDING = 'pending'",
                "    SHIPPED = 'shipped'",
                "    CANCELLED = 'cancelled'",
                "",
                "def ship_order(order):",
                "    order.status = OrderStatus.PENDING",
                "    if elapsed > REQUEST_TIMEOUT:",
                "        raise ValueError('cannot ship after timeout')",
                "    order.status = OrderStatus.SHIPPED",
                "",
                "@login_required",
                "def cancel_order(order):",
                "    order.status = OrderStatus.CANCELLED",
                "    send_email(order.customer, 'cancelled')",
            ]),
        )
        return app_dir

    def test_detects_limit_permission_side_effect_invariant(self) -> None:
        app_dir = self._app()
        artifacts = build_artifacts(str(app_dir))
        payload = build_business_rules(str(app_dir), artifacts)

        self.assertEqual(payload["schema"], BUSINESS_RULES_SCHEMA)
        categories = {rule["category"] for rule in payload["rules"]}
        self.assertIn("limit", categories)
        self.assertIn("permission", categories)
        self.assertIn("side-effect", categories)
        self.assertIn("invariant", categories)
        for rule in payload["rules"]:
            self.assertIn("confidence", rule)
            for evidence in rule["evidence"]:
                self.assertIn("path", evidence)
                self.assertIn("line", evidence)

    def test_state_machine_and_transitions_detected(self) -> None:
        app_dir = self._app()
        artifacts = build_artifacts(str(app_dir))
        payload = build_business_rules(str(app_dir), artifacts)

        self.assertEqual(len(payload["state_machines"]), 1)
        machine = payload["state_machines"][0]
        self.assertEqual(machine["name"], "OrderStatus")
        self.assertEqual(set(machine["states"]), {"PENDING", "SHIPPED", "CANCELLED"})
        transition_pairs = {(t["from"], t["to"]) for t in machine["transitions"]}
        self.assertIn(("PENDING", "SHIPPED"), transition_pairs)

    def test_no_false_positive_limit_without_comparison(self) -> None:
        app_dir = self.dir / "clean-app"
        _write(app_dir, "package.json", json.dumps({"name": "clean-app"}))
        _write(app_dir, "src/config.py", "MAX_RETRIES = 3\nprint(MAX_RETRIES)\n")
        artifacts = build_artifacts(str(app_dir))
        payload = build_business_rules(str(app_dir), artifacts)
        limit_rules = [r for r in payload["rules"] if r["category"] == "limit"]
        self.assertEqual(limit_rules, [])

    def test_glossary_cross_references_domain_doc(self) -> None:
        app_dir = self._app()
        _write(app_dir, ".specs/product/DOMAIN.md", "## Order\n\nA customer purchase.\n")
        artifacts = build_artifacts(str(app_dir))
        payload = build_business_rules(str(app_dir), artifacts)
        documented = [g for g in payload["glossary"] if g["status"] == "documented"]
        self.assertTrue(any(g["term"] == "order" for g in documented))

    def test_markdown_render_includes_state_diagram(self) -> None:
        app_dir = self._app()
        artifacts = build_artifacts(str(app_dir))
        payload = build_business_rules(str(app_dir), artifacts)
        markdown = render_business_rules_markdown(payload)
        self.assertIn("```mermaid", markdown)
        self.assertIn("stateDiagram-v2", markdown)
        self.assertIn("## Glossary", markdown)

    def test_business_command_writes_json_and_doc(self) -> None:
        app_dir = self._app()
        out = StringIO()
        with redirect_stdout(out):
            code = main(["business", str(app_dir), "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["schema"], BUSINESS_RULES_SCHEMA)
        self.assertTrue((app_dir / ".simplicio" / "business-rules.json").exists())
        self.assertTrue((app_dir / ".simplicio" / "docs" / "business-flows.md").exists())


if __name__ == "__main__":
    unittest.main()
