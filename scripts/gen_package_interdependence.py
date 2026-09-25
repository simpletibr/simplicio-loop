#!/usr/bin/env python3
"""Generate docs/PYTHON_PACKAGE_INTERDEPENDENCE.md from pyproject.toml (#101).

The doc used to be hand-maintained and drifted from reality (it pinned
simplicio-cli 0.5.19 / simplicio-mapper 0.8.0 while pyproject.toml had long
since moved to 0.9.1 / >=0.14.0). This script is the single source of truth:
it reads the real version + dependency floors + optional-dependencies
extras straight out of pyproject.toml (plus the local-model default out of
simplicio/providers.py) and renders the doc deterministically — same input,
byte-identical output, no wall-clock timestamps that would make `--check`
flag "drift" just because time passed.

Usage:
    python3 scripts/gen_package_interdependence.py            # regenerate
    python3 scripts/gen_package_interdependence.py --check    # CI/pre-commit
        drift gate: exit 0 if docs/PYTHON_PACKAGE_INTERDEPENDENCE.md already
        matches what this script would generate, exit 1 (with an actionable
        diff-style message) otherwise. Writes nothing in --check mode.
"""

from __future__ import annotations

import argparse
import difflib
import re
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10: tomllib is stdlib only from 3.11+
    import tomli as tomllib  # type: ignore[no-redef]

REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"
PROVIDERS_PY = REPO_ROOT / "simplicio" / "providers.py"
DOC_PATH = REPO_ROOT / "docs" / "PYTHON_PACKAGE_INTERDEPENDENCE.md"


def _req_name(req: str) -> str:
    return re.match(r"\s*([A-Za-z0-9._-]+)", req).group(1)  # type: ignore[union-attr]


def _load_project() -> dict:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    return data["project"]


def _local_default_model() -> str:
    text = PROVIDERS_PY.read_text(encoding="utf-8")
    m = re.search(r'^LOCAL_DEFAULT_MODEL\s*=\s*["\'](.+?)["\']', text, re.MULTILINE)
    return m.group(1) if m else "unknown"


def _ecosystem_floor(dependencies: list[str], name: str) -> str:
    for req in dependencies:
        if _req_name(req) == name:
            return req[len(name) :].lstrip()
    return "(not a base dependency)"


def render(project: dict, local_default_model: str) -> str:
    version = project["version"]
    name = project["name"]
    dependencies = list(project.get("dependencies", []))
    extras = dict(project.get("optional-dependencies", {}))

    mapper_floor = _ecosystem_floor(dependencies, "simplicio-mapper")

    lines: list[str] = []
    w = lines.append

    w("# Python Package Interdependence")
    w("")
    w("<!-- GENERATED FILE — do not hand-edit (#101). Regenerate with:")
    w("       python3 scripts/gen_package_interdependence.py")
    w("     Check it hasn't drifted from pyproject.toml with:")
    w("       python3 scripts/gen_package_interdependence.py --check")
    w("-->")
    w("")
    w(f"Source of truth: this repo's `pyproject.toml` (`{name}` v{version}).")
    w("")
    w("## Current Graph")
    w("")
    w("```text")
    w(f"simplicio-mapper {mapper_floor}")
    w("  ^")
    w("  |")
    w(f"{name} {version}")
    w("  ^")
    w("  |")
    w("simplicio-sprint (downstream, depends on this package)")
    w("```")
    w("")
    w("## Real dependency floors (read from pyproject.toml)")
    w("")
    w("### Base (always installed — `pip install simplicio-cli`)")
    w("")
    for req in dependencies:
        w(f"- `{req}`")
    w("")
    w("### Optional extras (#99 — heavy ML/provider deps are opt-in)")
    w("")
    for extra_name, reqs in extras.items():
        rendered = ", ".join(f"`{r}`" for r in reqs)
        w(f"- **`{name}[{extra_name}]`**: {rendered}")
    w("")
    w("## Rules")
    w("")
    w("- `simplicio-prompt` is forbidden on the hot path (not a base dependency).")
    w("- `simplicio-mapper` stays independent from the executor and sprint packages.")
    w(f"- `{name}` may depend on `simplicio-mapper` (base), plus the optional extras above.")
    w("- `simplicio-sprint` may depend on `simplicio-cli` and `simplicio-mapper`.")
    w("- No package may depend on `simplicio-sprint`; this keeps the orchestration")
    w("  layer at the edge and prevents cycles.")
    w("")
    w("## Where simplicio-cli fits (mapper / loop)")
    w("")
    w("```text")
    w("simplicio-mapper   -- repo context (project-map.json, precedent-index.json)")
    w("       |")
    w("       v")
    w("simplicio-cli      -- THIS PACKAGE: edit --plan + test")
    w("       |               (no LLM; no Runtime; no simplicio-prompt)")
    w("       v")
    w("simplicio-loop     -- coordinator: lease, journal, watcher")
    w("```")
    w("")
    w("simplicio-cli is the mutator/verifier. It does not orchestrate multi-step")
    w("work. Runtime is not part of this stack.")
    w("")
    w("## Local LLM Standard")
    w("")
    w(f"- Default local model for this package: `{local_default_model}`, via")
    w("  `llama.cpp` / `llama-cpp-python` (the `local` extra —")
    w(f"  `pip install '{name}[local]'`).")
    w("- This is independent of any other Simplicio repo's local-model default;")
    w("  each repo pins its own via its own code (here: `simplicio/providers.py`'s")
    w("  `LOCAL_DEFAULT_MODEL`), which is what this doc reads to stay accurate.")
    w("- Ollama is not part of the local default path; it remains an explicit")
    w("  OpenAI-compatible provider option only when configured by the user")
    w("  (`SIMPLICIO_MODEL` / `SIMPLICIO_BASE_URL`).")
    w("")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit 1 (with an actionable diff) if the doc has drifted, write nothing",
    )
    args = parser.parse_args(argv)

    project = _load_project()
    generated = render(project, _local_default_model())

    if args.check:
        current = DOC_PATH.read_text(encoding="utf-8") if DOC_PATH.exists() else ""
        if current == generated:
            print(f"OK: {DOC_PATH.relative_to(REPO_ROOT)} matches pyproject.toml.")
            return 0
        diff = "".join(
            difflib.unified_diff(
                current.splitlines(keepends=True),
                generated.splitlines(keepends=True),
                fromfile=f"{DOC_PATH.relative_to(REPO_ROOT)} (on disk)",
                tofile=f"{DOC_PATH.relative_to(REPO_ROOT)} (generated from pyproject.toml)",
            )
        )
        print(
            "DRIFT: docs/PYTHON_PACKAGE_INTERDEPENDENCE.md is stale.\n"
            "Regenerate it with: python3 scripts/gen_package_interdependence.py\n\n" + diff,
            file=sys.stderr,
        )
        return 1

    DOC_PATH.write_text(generated, encoding="utf-8")
    print(f"wrote {DOC_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
