"""Onboarding survey: the "new developer on day one" report (F1).

Consolidates project-map, architecture-inventory, flow-inventory (F2) and
business-rules (F3) into a single narrative document: what this project
is, how to run it, a suggested reading order, the main flows, the domain
rules/glossary, observed conventions, and where to ask for help.
Deterministic; every claim either has evidence or is explicitly reported
as "nothing detected" — this survey never invents.

Emits ``simplicio.onboarding/v1`` as documented in
``SIMPLICIO_INTEGRATION.md``.
"""

from __future__ import annotations

import json
import os
import re

ONBOARDING_SCHEMA = "simplicio.onboarding/v1"
ONBOARDING_VERSION = 1

_NPM_SCRIPT_KEYS = ("dev", "start", "build", "test", "lint")
_HELP_DOC_CANDIDATES = ("CODEOWNERS", ".github/CODEOWNERS", "CONTRIBUTING.md", ".specs/workflow/CONTRIBUTING.md")


def _read_json_safe(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def _read_text(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="ignore") as handle:
            return handle.read()
    except OSError:
        return ""


def _detect_run_commands(cwd: str) -> list[dict]:
    commands: list[dict] = []
    pkg = _read_json_safe(os.path.join(cwd, "package.json"))
    for key in _NPM_SCRIPT_KEYS:
        if key in (pkg.get("scripts") or {}):
            commands.append({"label": key, "command": f"npm run {key}", "source": "package.json"})

    pyproject_text = _read_text(os.path.join(cwd, "pyproject.toml"))
    if pyproject_text:
        in_scripts = False
        for line in pyproject_text.splitlines():
            stripped = line.strip()
            if stripped == "[project.scripts]":
                in_scripts = True
                continue
            if in_scripts:
                if stripped.startswith("["):
                    break
                match = re.match(r"^([\w.-]+)\s*=", stripped)
                if match:
                    commands.append({"label": match.group(1), "command": match.group(1), "source": "pyproject.toml"})

    makefile_text = _read_text(os.path.join(cwd, "Makefile"))
    if makefile_text:
        for match in re.finditer(r"^([a-zA-Z][\w-]*)\s*:", makefile_text, re.MULTILINE):
            commands.append({"label": match.group(1), "command": f"make {match.group(1)}", "source": "Makefile"})

    return commands


def _fan_in_by_module(call_graph: dict) -> dict[str, int]:
    fan_in: dict[str, int] = {}
    for edge in call_graph.get("edges") or []:
        if edge.get("type") != "imports":
            continue
        target = edge.get("target_file")
        if not target:
            continue
        module = target.split("/", 1)[0] if "/" in target else "."
        fan_in[module] = fan_in.get(module, 0) + 1
    return fan_in


def _reading_order(project_map: dict, architecture_inventory: dict, call_graph: dict) -> list[dict]:
    order: list[dict] = []
    for path in sorted(project_map.get("entry_points") or []):
        order.append({"path": path, "reason": "detected entry point (CLI/main/bin)"})

    fan_in = _fan_in_by_module(call_graph)
    modules = sorted(
        architecture_inventory.get("modules") or [],
        key=lambda m: (-fan_in.get(m["name"], 0), m["name"]),
    )
    for module in modules:
        count = fan_in.get(module["name"], 0)
        if count <= 0:
            continue
        order.append({"path": module["name"], "reason": f"module with {count} incoming cross-module reference(s)"})
        if len([o for o in order if "incoming cross-module" in o["reason"]]) >= 8:
            break

    for path in sorted(project_map.get("config_files") or [])[:5]:
        order.append({"path": path, "reason": "configuration file"})

    test_files = project_map.get("test_files") or []
    if test_files:
        order.append({"path": sorted(test_files)[0], "reason": f"representative test (of {len(test_files)} detected)"})

    return order


def _conventions(precedent_index: dict) -> list[dict]:
    tag_counts: dict[str, int] = {}
    for item in precedent_index.get("items") or []:
        for tag in item.get("tags") or []:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
    return [
        {"convention": tag, "occurrences": count}
        for tag, count in sorted(tag_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:15]
    ]


def _help_sources(cwd: str) -> list[dict]:
    sources = []
    for candidate in _HELP_DOC_CANDIDATES:
        if os.path.isfile(os.path.join(cwd, candidate)):
            sources.append({"path": candidate, "kind": "contact-doc"})
    adr_dir = os.path.join(cwd, ".specs", "architecture")
    if os.path.isdir(adr_dir):
        for name in sorted(os.listdir(adr_dir)):
            if name.startswith("ADR-") and name.endswith(".md"):
                sources.append({"path": f".specs/architecture/{name}", "kind": "adr"})
    return sources


def build_survey(cwd: str, artifacts: dict, flow_inventory: dict, business_rules: dict, top_n_flows: int = 5) -> dict:
    abs_cwd = os.path.abspath(cwd)
    project_map = artifacts["project_map"]
    architecture_inventory = artifacts["architecture_inventory"]
    call_graph = artifacts["call_graph"]
    precedent_index = artifacts["precedent_index"]

    top_flows = sorted(flow_inventory.get("flows") or [], key=lambda f: (-len(f["effects"]), f["id"]))[:top_n_flows]

    return {
        "schema": ONBOARDING_SCHEMA,
        "version": ONBOARDING_VERSION,
        "generated_at": project_map.get("generated_at"),
        "project": {
            "name": (project_map.get("product") or {}).get("name"),
            "stack": (project_map.get("product") or {}).get("stack"),
            "system_type": (project_map.get("architecture") or {}).get("system_type"),
        },
        "run_commands": _detect_run_commands(abs_cwd),
        "reading_order": _reading_order(project_map, architecture_inventory, call_graph),
        "top_flows": [
            {"id": flow["id"], "kind": flow["kind"], "effect_count": len(flow["effects"])}
            for flow in top_flows
        ],
        "business_rules_summary": {
            "rules": len(business_rules.get("rules") or []),
            "state_machines": len(business_rules.get("state_machines") or []),
            "glossary_terms": len(business_rules.get("glossary") or []),
        },
        "glossary": business_rules.get("glossary") or [],
        "conventions": _conventions(precedent_index),
        "help_sources": _help_sources(abs_cwd),
    }


def render_survey_markdown(survey: dict) -> str:
    project = survey["project"]
    lines = [
        f"# Onboarding — {project.get('name') or 'this project'}",
        "",
        "Generated by `simplicio-mapper survey`. This is the levantamento a new "
        "developer would otherwise spend days assembling by hand: what this is, "
        "how to run it, what to read first, the main flows, and the domain rules.",
        "",
        "## 1. What is this project",
        "",
        f"- Name: {project.get('name') or 'unknown'}",
        f"- Stack: {project.get('stack') or 'unknown'}",
        f"- System type: {project.get('system_type') or 'unknown'}",
        "",
        "## 2. How to run it",
        "",
    ]
    if survey["run_commands"]:
        lines += ["| Command | Source |", "| --- | --- |"]
        for command in survey["run_commands"]:
            lines.append(f"| `{command['command']}` | `{command['source']}` |")
        lines.append("")
        lines.append("> Commands are *detected* from manifests, not *validated* — confirm they work before relying on them.")
    else:
        lines.append("Nothing detected — no `package.json` scripts, `[project.scripts]` or `Makefile` targets found.")
    lines.append("")

    lines += [
        "## 3. Mental map",
        "",
        "_See `.simplicio/docs/architecture.md` for the full module dependency diagram._",
        "",
        "## 4. Suggested reading order",
        "",
    ]
    if survey["reading_order"]:
        for index, item in enumerate(survey["reading_order"], start=1):
            lines.append(f"{index}. `{item['path']}` — {item['reason']}")
    else:
        lines.append("Nothing detected.")
    lines.append("")

    lines += ["## 5. Main flows", ""]
    if survey["top_flows"]:
        lines += ["| Flow | Kind | Effects |", "| --- | --- | --- |"]
        for flow in survey["top_flows"]:
            lines.append(f"| `{flow['id']}` | {flow['kind']} | {flow['effect_count']} |")
        lines.append("")
        lines.append("_Full detail (steps, evidence, diagrams) in `.simplicio/docs/flows.md`._")
    else:
        lines.append("No flows detected.")
    lines.append("")

    lines += ["## 6. Business rules & glossary", ""]
    summary = survey["business_rules_summary"]
    lines.append(
        f"- {summary['rules']} observable rule(s), {summary['state_machines']} state machine(s), "
        f"{summary['glossary_terms']} glossary term(s)."
    )
    lines.append("_Full detail in `.simplicio/docs/business-flows.md`._")
    if survey["glossary"]:
        lines += ["", "| Term | Status |", "| --- | --- |"]
        for item in survey["glossary"][:20]:
            lines.append(f"| {item['term']} | {item['status']} |")
    lines.append("")

    lines += ["## 7. Observed conventions", ""]
    if survey["conventions"]:
        for item in survey["conventions"]:
            lines.append(f"- `{item['convention']}`: {item['occurrences']} occurrence(s)")
    else:
        lines.append("Nothing detected.")
    lines.append("")

    lines += ["## 8. Where to ask for help", ""]
    if survey["help_sources"]:
        for item in survey["help_sources"]:
            lines.append(f"- `{item['path']}` ({item['kind']})")
    else:
        lines.append("Nothing detected — no CODEOWNERS/CONTRIBUTING/ADRs found.")
    lines.append("")

    return "\n".join(lines)
