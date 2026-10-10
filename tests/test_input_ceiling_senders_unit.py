"""Every module that sends a prompt to an LLM goes through the input-token ceiling (#1608, part C).

The test finds senders by what they do (an LLM CLI argv or a chat-completions endpoint), so a NEW sender that does not call
``enforce_budget``/``check_budget`` fails here.
"""
from __future__ import annotations

import re
from pathlib import Path

from simplicio_loop import input_ceiling, model_probe

PACKAGE = Path(__file__).resolve().parent.parent / "simplicio_loop"
SKIP_DIRS = {"_bundle", "_contracts", "__pycache__"}

# An LLM CLI called with a prompt, or a chat-completions endpoint.
SENDER = re.compile(
    r"chat/completions"
    r"|\[\s*[\"'](?:claude|codex|gemini|grok|opencode|agy)[\"']\s*,\s*[\"'](?:-p|exec|run|--print)[\"']"
    r"|lambda\s+\w+:\s*\[\s*[\"'](?:claude|codex|gemini|grok|opencode|agy)[\"']"
)
GATED = re.compile(r"\b(?:enforce_budget|check_budget)\b")

# model_probe sends one constant, tiny prompt (asserted below); it has no context to bound.
EXEMPT = {"model_probe.py"}


def _modules() -> list[Path]:
    return [p for p in sorted(PACKAGE.rglob("*.py")) if not SKIP_DIRS.intersection(p.relative_to(PACKAGE).parts)]


def _senders() -> list[Path]:
    return [p for p in _modules() if SENDER.search(p.read_text(encoding="utf-8"))]


def test_the_scan_finds_the_known_senders():
    names = {p.name for p in _senders()}
    assert {"exec_planner.py", "author_flow.py", "turbo_provider.py", "provider_worker.py",
            "openrouter_operator.py", "model_probe.py"} <= names


def test_every_sender_calls_the_budget_decision():
    missing = [str(p.relative_to(PACKAGE)) for p in _senders()
               if p.name not in EXEMPT and not GATED.search(p.read_text(encoding="utf-8"))]
    assert missing == [], "these modules send a prompt to an LLM without check_budget/enforce_budget: %s" % missing


def test_a_sender_must_import_the_ceiling_module():
    missing = [str(p.relative_to(PACKAGE)) for p in _senders()
               if p.name not in EXEMPT and "input_ceiling" not in p.read_text(encoding="utf-8")]
    assert missing == []


def test_the_exempt_probe_prompt_is_tiny():
    projection = input_ceiling.Projection.estimated(model_probe.PROMPT)
    assert projection.tokens < 100
    assert input_ceiling.check_budget(projection, input_ceiling.DEFAULT_CEILING).status == input_ceiling.OK


def test_the_exemption_list_names_only_existing_senders():
    assert EXEMPT <= {p.name for p in _senders()}


def test_the_scan_catches_an_ungated_sender():
    ungated = 'argv = ["claude", "-p", prompt]\n'
    assert SENDER.search(ungated) and not GATED.search(ungated)
    assert GATED.search(ungated + "input_ceiling.enforce_budget(p, c)\n")
