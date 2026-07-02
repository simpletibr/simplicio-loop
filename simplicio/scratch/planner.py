"""planner.py — generate a Plan from goal + stack via the planner provider.

DeepSeek-V4-Pro is the default (see simplicio.providers.planner_complete);
swappable via SIMPLICIO_PLANNER. Retries on schema validation failure with
the diff fed back as feedback, up to PLANNER_MAX_RETRIES.
"""

from __future__ import annotations

import json
import os
import re
from typing import Optional

from ..providers import planner_complete
from .plan_schema import Plan, PlanValidationError, validate_plan, EXAMPLE_PLAN
from .recipes import RecipeRegistry, RecipeSlotError
from .stack_registry import Stack


class PlannerError(RuntimeError):
    """The planner could not produce a schema-valid plan within retry budget."""


PLANNER_MAX_RETRIES = int(os.environ.get("SIMPLICIO_PLANNER_MAX_RETRIES", "3"))


PLAN_SYSTEM_PREAMBLE = """You are a senior software architect producing a strictly-formatted
project plan for a code-generation agent to execute. Your output is consumed
by a JSON parser + schema validator; any deviation breaks the pipeline.

Hard rules:
- Output ONLY a single JSON object. No prose before or after. No fences.
- Match the schema EXACTLY. Every required key must be present and well-typed.
- Tasks are ATOMIC — each task should edit ONE file and have a single concrete
  acceptance criterion. Decompose large work into many small tasks.
- Tasks have stable IDs: `T01-<slug>`, `T02-<slug>`, ... (two-digit zero-padded
  index, kebab-case slug, max 40 chars after the dash).
- `depends_on` lists IDs of tasks that must complete BEFORE this one. Use
  empty list for tasks with no prerequisite.
- If a task needs project-specific expertise not covered by the stack template,
  set optional `required_skill` to a short plain-English capability description.
  Omit it otherwise.
- `estimated_total_tasks` MUST equal the length of `tasks`.
- `project_name` MUST be lowercase kebab-case, starting with a letter.
- Do not invent fields. Do not nest extra structure. Do not add comments.
"""


PLAN_PROMPT_TEMPLATE = """{system}

[STACK CHOSEN]
slug: {stack_slug}
language: {language}
framework: {framework}
test_runner: {test_runner}
package_manager: {pkg_mgr}

[STACK README]
{stack_readme}

[STACK PRACTICES]
{stack_practices}

[USER GOAL]
{goal}

[PROJECT NAME]
{project_name}

[OUTPUT SCHEMA — example of a valid response]
```json
{schema_example}
```

Now produce the plan for the user goal above, targeting the chosen stack.
The first character of your response MUST be `{{` and the last `}}`."""


def _build_prompt(stack: Stack, goal: str, project_name: str) -> str:
    return PLAN_PROMPT_TEMPLATE.format(
        system=PLAN_SYSTEM_PREAMBLE,
        stack_slug=stack.slug,
        language=stack.language,
        framework=stack.framework,
        test_runner=stack.verify.get("test_runner", "?"),
        pkg_mgr=stack.meta.get("package_manager", "?"),
        stack_readme=stack.readme[:4000],
        stack_practices=stack.practices[:6000],
        goal=goal,
        project_name=project_name,
        # issue #88 quick win: pretty-printed (indent=2) was pure token
        # waste in a few-shot example embedded in the prompt — the model
        # doesn't need human-readable indentation, it needs the schema.
        schema_example=json.dumps(EXAMPLE_PLAN, separators=(",", ":")),
    )


def _extract_json(text: str) -> Optional[dict]:
    """Pull the first top-level JSON object out of a model response.
    Tolerates accidental code fences and leading/trailing prose, because that's
    what models occasionally do regardless of instructions."""
    if not text:
        return None
    # Strip fences if present
    fenced = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    # Find first { and the matching close }
    depth = 0
    start = None
    for i, ch in enumerate(text):
        if ch == "{":
            if start is None:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                blob = text[start : i + 1]
                try:
                    return json.loads(blob)
                except json.JSONDecodeError:
                    # Keep looking; this candidate isn't valid JSON
                    start = None
                    depth = 0
    return None


def generate_plan(
    stack: Stack,
    goal: str,
    project_name: str,
    slots: dict[str, str] | None = None,
) -> Plan:
    """Run the planner up to PLANNER_MAX_RETRIES + 1 times.
    Each retry feeds the previous validation diff back as additional context.
    """
    try:
        registry = RecipeRegistry()
        recipe_match = registry.match(goal, stack.slug, slot_overrides=slots)
        if recipe_match is not None:
            return registry.get(recipe_match.recipe_name, stack.slug).instantiate(
                recipe_match,
                project_name,
            )
    except RecipeSlotError as e:
        raise PlannerError(str(e)) from e

    prompt = _build_prompt(stack, goal, project_name)
    feedback: Optional[list[str]] = None
    last_raw_text = ""

    for attempt in range(1, PLANNER_MAX_RETRIES + 2):
        prompt_with_feedback = prompt
        if feedback:
            prompt_with_feedback = (
                prompt
                + "\n\n[RETRY — previous attempt failed schema validation]\n"
                + "Errors to fix:\n"
                + "\n".join(f"  - {e}" for e in feedback)
                + "\n\nReturn the corrected JSON. Output ONLY the object."
            )

        try:
            raw_text = planner_complete(
                prompt_with_feedback,
                template_version=stack.version,
            )
        except SystemExit as e:
            # Provider auth / config error — bubble up immediately, don't retry
            raise PlannerError(f"planner provider error: {e}") from e

        last_raw_text = raw_text or ""
        parsed = _extract_json(last_raw_text)
        if parsed is None:
            feedback = ["could not parse JSON from response"]
            continue

        try:
            plan = validate_plan(parsed)
            return plan
        except PlanValidationError as e:
            feedback = e.errors
            continue

    raise PlannerError(
        f"planner did not produce a schema-valid plan after "
        f"{PLANNER_MAX_RETRIES + 1} attempts. Last validation errors: "
        f"{feedback}\n\nLast raw output (first 500 chars):\n"
        f"{last_raw_text[:500]}"
    )
