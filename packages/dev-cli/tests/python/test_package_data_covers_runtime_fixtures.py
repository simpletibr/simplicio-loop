"""Regression guard for issue #167 ACs "Package instalado contem docs/schemas
esperados" and "Quickstart roda fora do checkout".

Bug this guards against: `simplicio/commands/score_skill.py` loads its
builtin scenario fixtures at runtime from
``Path(__file__).resolve().parent / "scenarios"`` (see
`_resolve_scenarios`), but `[tool.setuptools.package-data]` in pyproject.toml
only declared `templates/**` + `py.typed`. Any non-.py data file living
under `simplicio/` that isn't matched by a declared package-data glob is
present in the git checkout but silently absent from the built wheel/sdist —
so `pip install simplicio-cli` in a clean venv, run from a directory outside
the checkout, ships `score_skill.py` without its `commands/scenarios/*.json`
data and `simplicio-py score-skill` fails with "no scenarios found" (exit 2)
even though the same command works fine inside the repo.

This module does two orthogonal, fast local checks (no `python -m build`
needed — the explicit packaging gate documented in
`docs/ci-quality-gate.md` builds the wheel, checks it and smoke-tests the
CLI):

1. Static: every non-.py, non-cache file actually committed under
   `simplicio/` is matched by at least one glob declared in
   `[tool.setuptools.package-data]`. This is the generic version of the bug
   above — it fails loudly the next time someone adds a new runtime data
   file without wiring it into package-data, not just for this one
   scenarios/ directory.
2. Functional: `score_skill._resolve_scenarios` actually resolves a non-empty
   builtin scenario list from the real `commands/scenarios/` directory
   shipped alongside the module (exercises the same code path that the
   installed-wheel smoke test above hit).
"""

from __future__ import annotations

import fnmatch
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10: tomllib is stdlib only from 3.11+
    import tomli as tomllib  # type: ignore[no-redef]

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = REPO_ROOT / "simplicio"

# Directories that are never packaged (build/test artifacts, not product data).
_IGNORED_DIR_NAMES = {"__pycache__"}

# Files intentionally out of scope for this check:
# - `.gitkeep`: git plumbing to keep an otherwise-empty dir tracked; never
#   meaningful in a built wheel/sdist.
# - `commands/claims_scenarios.json`: unreferenced anywhere in
#   simplicio/, tests/, or docs/ (confirmed via repo-wide grep while
#   investigating #167) — an orphaned example fixture, not a runtime
#   dependency of any shipped command. Not this issue's scope to resolve
#   (delete vs. wire in); tracked here only so it doesn't produce a false
#   positive in the generic scan below.
_IGNORED_RELATIVE_PATHS = {
    "commands/scenarios/.gitkeep",
    "commands/claims_scenarios.json",
}


def _declared_package_data_globs() -> list[str]:
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return project["tool"]["setuptools"]["package-data"]["simplicio"]


def _committed_non_python_files() -> list[Path]:
    files = []
    for path in PACKAGE_ROOT.rglob("*"):
        if path.is_dir():
            continue
        if any(part in _IGNORED_DIR_NAMES for part in path.parts):
            continue
        if path.suffix == ".py":
            continue
        files.append(path)
    return files


def test_every_shipped_non_python_file_is_covered_by_package_data() -> None:
    """Guards the general shape of the bug: a data file under `simplicio/`
    that no package-data glob matches is invisible to the built wheel."""
    globs = _declared_package_data_globs()
    uncovered = []
    for path in _committed_non_python_files():
        rel = path.relative_to(PACKAGE_ROOT).as_posix()
        if rel in _IGNORED_RELATIVE_PATHS:
            continue
        if not any(fnmatch.fnmatch(rel, glob) for glob in globs):
            uncovered.append(rel)

    assert not uncovered, (
        "these simplicio/ data files are not matched by any "
        "[tool.setuptools.package-data] glob in pyproject.toml, so they will "
        f"be missing from the built wheel/sdist: {sorted(uncovered)}"
    )


def test_score_skill_builtin_scenarios_glob_is_declared_in_package_data() -> None:
    """Names the concrete file this issue found missing, so a future revert
    of the fix fails immediately and legibly (not just via the generic scan
    above)."""
    globs = _declared_package_data_globs()
    assert any(fnmatch.fnmatch("commands/scenarios/claims-gate.json", glob) for glob in globs)


def test_score_skill_resolves_nonempty_builtin_scenarios_from_shipped_directory() -> None:
    """Functional companion to the static checks: the real code path
    `score_skill.main` uses to find builtin scenarios (relative to the
    installed module's own location) must actually resolve fixtures."""
    from simplicio.commands.score_skill import _resolve_scenarios

    builtin_dir = PACKAGE_ROOT / "commands" / "scenarios"
    scenarios = _resolve_scenarios([], [], builtin_dir)

    assert scenarios, (
        "no builtin score-skill scenarios resolved from "
        f"{builtin_dir} — score-skill would fail with 'no scenarios found' "
        "for any installed user who doesn't pass --scenario"
    )
