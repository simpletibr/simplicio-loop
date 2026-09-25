"""Declarative plan recipes for common scratch-mode goals.

Recipes are loaded from ``simplicio/templates/recipes/<stack>/*.yaml`` and
turn known goal patterns into schema-validated plans without a planner call.
The loader accepts JSON-compatible YAML with an optional PyYAML fallback so the
runtime stays dependency-free in the default install.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from re import Pattern
from typing import Any

from .plan_schema import Plan, validate_plan


class RecipeError(ValueError):
    """Base class for recipe loading, matching, and rendering failures."""


class RecipeLoadError(RecipeError):
    """Raised when a recipe template cannot be loaded."""


class RecipeSlotError(RecipeError):
    """Raised when a required slot is missing or cannot be rendered."""


@dataclass
class SlotSpec:
    required: bool = False
    default: str | None = None
    derived_from: str | None = None
    transform: str = "identity"


@dataclass
class RecipeMatch:
    recipe_name: str
    slots: dict[str, str]
    stack_slug: str


@dataclass
class Recipe:
    name: str
    description: str
    stack_slug: str
    applies_to: list[str]
    matches: list[Pattern[str]]
    slots_spec: dict[str, SlotSpec]
    tasks_template: list[dict[str, Any]]
    files_to_create_template: list[dict[str, str]] = field(default_factory=list)
    deps_to_install: list[str] = field(default_factory=list)
    deps_dev: list[str] = field(default_factory=list)
    test_command: str = ""
    lint_command: str = ""
    rationale: str = ""
    source_path: Path | None = None

    @classmethod
    def from_dict(
        cls,
        raw: dict[str, Any],
        stack_slug: str,
        source_path: Path | None = None,
    ) -> Recipe:
        name = _need_str(raw, "name", source_path)
        matches = [re.compile(pattern) for pattern in _need_list_of_str(raw, "matches", source_path)]
        slots_raw = raw.get("slots", {})
        if not isinstance(slots_raw, dict):
            raise RecipeLoadError(_where(source_path, "slots must be an object"))
        slots_spec = {
            str(slot): SlotSpec(
                required=bool(spec.get("required", False)),
                default=(None if spec.get("default") is None else str(spec.get("default"))),
                derived_from=(None if spec.get("derived_from") is None else str(spec.get("derived_from"))),
                transform=str(spec.get("transform", "identity")),
            )
            for slot, spec in slots_raw.items()
            if isinstance(spec, dict)
        }
        if len(slots_spec) != len(slots_raw):
            raise RecipeLoadError(_where(source_path, "every slot spec must be an object"))

        return cls(
            name=name,
            description=str(raw.get("description", "")),
            stack_slug=stack_slug,
            applies_to=_list_of_str(raw.get("applies_to", [stack_slug])),
            matches=matches,
            slots_spec=slots_spec,
            tasks_template=_need_list_of_dict(raw, "tasks", source_path),
            files_to_create_template=_list_of_dict(raw.get("files_to_create", [])),
            deps_to_install=_list_of_str(raw.get("deps_to_install", [])),
            deps_dev=_list_of_str(raw.get("deps_dev", [])),
            test_command=str(raw.get("test_command", "")),
            lint_command=str(raw.get("lint_command", "")),
            rationale=str(raw.get("rationale", "")),
            source_path=source_path,
        )

    def try_match(
        self,
        goal: str,
        stack_slug: str,
        slot_overrides: dict[str, str] | None = None,
    ) -> RecipeMatch | None:
        if stack_slug not in self.applies_to:
            return None
        for pattern in self.matches:
            found = pattern.search(goal)
            if not found:
                continue
            slots = {
                key: value.strip()
                for key, value in found.groupdict().items()
                if value is not None and value.strip()
            }
            if slot_overrides:
                slots.update(slot_overrides)
            slots = self._resolve_slots(slots)
            return RecipeMatch(
                recipe_name=self.name,
                slots=slots,
                stack_slug=stack_slug,
            )
        return None

    def instantiate(self, match: RecipeMatch, project_name: str) -> Plan:
        if match.recipe_name != self.name:
            raise RecipeError(
                f"match for recipe {match.recipe_name!r} cannot instantiate recipe {self.name!r}"
            )
        if match.stack_slug != self.stack_slug:
            raise RecipeError(
                f"recipe {self.name!r} is for stack {self.stack_slug!r}, got match stack {match.stack_slug!r}"
            )

        slots = dict(match.slots)
        context = {
            **slots,
            "project_name": project_name,
            "recipe_name": self.name,
            "stack_slug": self.stack_slug,
        }
        tasks = _render(self.tasks_template, context)
        raw_plan = {
            "version": "1.0",
            "stack": self.stack_slug,
            "project_name": project_name,
            "rationale": _render(self.rationale or self.description, context),
            "files_to_create": _render(self.files_to_create_template, context),
            "tasks": tasks,
            "deps_to_install": _render(self.deps_to_install, context),
            "deps_dev": _render(self.deps_dev, context),
            "test_command": _render(self.test_command, context),
            "lint_command": _render(self.lint_command, context),
            "estimated_total_tasks": len(tasks),
        }
        return validate_plan(raw_plan)

    def _resolve_slots(self, provided: dict[str, str]) -> dict[str, str]:
        slots = {key: str(value).strip() for key, value in provided.items()}
        for name, spec in self.slots_spec.items():
            if spec.derived_from:
                value = slots.get(spec.derived_from)
            else:
                value = slots.get(name)
            if not value and spec.default is not None:
                value = _render(spec.default, slots)
            if not value and spec.required:
                raise RecipeSlotError(
                    f"missing required slot {name!r} for recipe {self.name!r}; pass --slot {name}=VALUE"
                )
            if value:
                slots[name] = _transform(value, spec.transform)
        return slots


class RecipeRegistry:
    """Lazy registry for stack-specific declarative recipes."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or _recipes_root()
        self._cache: dict[tuple[str, str], Recipe] | None = None

    def load(self) -> None:
        self._load()

    def list(self, stack_slug: str | None = None) -> list[Recipe]:
        recipes = list(self._load().values())
        if stack_slug is not None:
            recipes = [recipe for recipe in recipes if stack_slug in recipe.applies_to]
        return sorted(recipes, key=lambda recipe: (recipe.stack_slug, recipe.name))

    def match(
        self,
        goal: str,
        stack_slug: str,
        slot_overrides: dict[str, str] | None = None,
    ) -> RecipeMatch | None:
        for recipe in self.list(stack_slug):
            match = recipe.try_match(goal, stack_slug, slot_overrides=slot_overrides)
            if match is not None:
                return match
        return None

    def get(self, name: str, stack_slug: str | None = None) -> Recipe:
        recipes = self._load()
        if stack_slug is not None:
            try:
                return recipes[(stack_slug, name)]
            except KeyError as exc:
                raise KeyError(f"recipe {name!r} not found for stack {stack_slug!r}") from exc

        matches = [recipe for (stack, recipe_name), recipe in recipes.items() if recipe_name == name]
        if not matches:
            raise KeyError(f"recipe {name!r} not found")
        return sorted(matches, key=lambda recipe: recipe.stack_slug)[0]

    def _load(self) -> dict[tuple[str, str], Recipe]:
        if self._cache is not None:
            return self._cache
        recipes: dict[tuple[str, str], Recipe] = {}
        if not self.root.is_dir():
            self._cache = recipes
            return recipes

        paths = [path for suffix in ("*.yaml", "*.yml", "*.json") for path in self.root.glob(f"*/{suffix}")]
        for path in sorted(paths):
            if not path.is_file():
                continue
            stack_slug = path.parent.name
            raw = _load_template(path)
            recipe = Recipe.from_dict(raw, stack_slug=stack_slug, source_path=path)
            key = (recipe.stack_slug, recipe.name)
            if key in recipes:
                raise RecipeLoadError(
                    _where(
                        path,
                        f"duplicate recipe {recipe.name!r} for stack {stack_slug!r}",
                    )
                )
            recipes[key] = recipe
        self._cache = recipes
        return recipes


def plan_from_recipe(
    goal: str,
    stack_slug: str,
    project_name: str,
    slot_overrides: dict[str, str] | None = None,
) -> Plan | None:
    """Return a validated recipe plan for a known goal, or None on a miss."""
    registry = RecipeRegistry()
    match = registry.match(goal, stack_slug, slot_overrides=slot_overrides)
    if match is None:
        return None
    return registry.get(match.recipe_name, match.stack_slug).instantiate(
        match,
        project_name,
    )


def _recipes_root() -> Path:
    override = os.environ.get("SIMPLICIO_RECIPES_DIR")
    if override:
        return Path(override)
    return Path(__file__).resolve().parent.parent / "templates" / "recipes"


def _load_template(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as json_error:
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            raise RecipeLoadError(
                _where(
                    path,
                    "template must be JSON-compatible YAML unless PyYAML is installed",
                )
            ) from exc
        try:
            raw = yaml.safe_load(text)
        except Exception as exc:  # pragma: no cover - depends on optional PyYAML
            raise RecipeLoadError(_where(path, f"invalid recipe YAML: {json_error}")) from exc
    if not isinstance(raw, dict):
        raise RecipeLoadError(_where(path, "recipe root must be an object"))
    return raw


def _need_str(raw: dict[str, Any], key: str, path: Path | None) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise RecipeLoadError(_where(path, f"{key} must be a non-empty string"))
    return value


def _need_list_of_str(
    raw: dict[str, Any],
    key: str,
    path: Path | None,
) -> list[str]:
    if key not in raw:
        raise RecipeLoadError(_where(path, f"{key} missing"))
    return _list_of_str(raw[key])


def _need_list_of_dict(
    raw: dict[str, Any],
    key: str,
    path: Path | None,
) -> list[dict[str, Any]]:
    if key not in raw:
        raise RecipeLoadError(_where(path, f"{key} missing"))
    return _list_of_dict(raw[key])


def _list_of_str(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise RecipeLoadError(f"expected list[str], got {type(value).__name__}")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise RecipeLoadError(f"expected list[str], got {type(item).__name__}")
        out.append(item)
    return out


def _list_of_dict(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise RecipeLoadError(f"expected list[object], got {type(value).__name__}")
    out: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise RecipeLoadError(f"expected list[object], got {type(item).__name__}")
        out.append(item)
    return out


def _where(path: Path | None, message: str) -> str:
    if path is None:
        return message
    return f"{path}: {message}"


_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def _render(value: Any, context: dict[str, str]) -> Any:
    if isinstance(value, str):

        def replace(found: re.Match[str]) -> str:
            key = found.group(1)
            if key not in context:
                raise RecipeSlotError(f"missing slot {key!r}; pass --slot {key}=VALUE")
            return context[key]

        return _PLACEHOLDER_RE.sub(replace, value)
    if isinstance(value, list):
        return [_render(item, context) for item in value]
    if isinstance(value, dict):
        return {str(key): _render(item, context) for key, item in value.items()}
    return value


def _transform(value: str, transform: str) -> str:
    if transform in ("", "identity"):
        return value.strip()
    if transform == "pascal_case":
        return "".join(word.capitalize() for word in _words(value))
    if transform == "lower_snake_case":
        return "_".join(word.lower() for word in _words(value))
    if transform in ("lower_kebab_case", "kebab_case"):
        return "-".join(word.lower() for word in _words(value))
    if transform == "lower":
        return value.lower()
    if transform == "plural_lower":
        return _pluralize("_".join(word.lower() for word in _words(value)))
    raise RecipeError(f"unknown slot transform {transform!r}")


def _words(value: str) -> list[str]:
    expanded = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value.strip())
    return re.findall(r"[A-Za-z0-9]+", expanded)


def _pluralize(value: str) -> str:
    if value.endswith("ss"):
        return value + "es"
    if value.endswith("s"):
        return value
    if value.endswith("x") or value.endswith(("ch", "sh")):
        return value + "es"
    if value.endswith("y") and len(value) > 1 and value[-2] not in "aeiou":
        return value[:-1] + "ies"
    return value + "s"
