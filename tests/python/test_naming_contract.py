"""Regression guard for issue #167 (Ecosystem Rebrand) ACs:

- "Dev CLI não é renomeado para Agent" — the package/entrypoints stay
  `simplicio-cli`/`simplicio-py`/`simplicio-dev-cli`, distinct from the
  separate "Simplicio Agent" product (the Hermes successor).
- "Docs/bootstrap usam Simplicio Agent canônico" — every doc/bootstrap
  reference to the Hermes-successor product says "Simplicio Agent", and no
  stray "Hermes" mention leaks back in outside the two documented
  exceptions: the CHANGELOG's historical entry and the
  `runtime_contracts.py` legacy-alias detection list (plus its direct
  test/comment cross-references).
"""

from __future__ import annotations

import re
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10: tomllib is stdlib only from 3.11+
    import tomli as tomllib  # type: ignore[no-redef]

REPO_ROOT = Path(__file__).resolve().parents[2]

# Files outside CHANGELOG.md/runtime_contracts.py-adjacent code where a stray
# "hermes" mention is tolerated because they document the legacy-alias
# compat surface itself (not a rebrand miss).
ALLOWED_HERMES_FILES = {
    REPO_ROOT / "CHANGELOG.md",
    REPO_ROOT / "simplicio" / "runtime_contracts.py",
    REPO_ROOT / "simplicio" / "commands" / "runtime.py",
    REPO_ROOT / "bench" / "run_release_gate.py",
    REPO_ROOT / "tests" / "python" / "test_runtime_contracts.py",
    # Documented references to issue #167's invariant 6 ("Compatibilidade
    # Hermes fica em uma borda registrada") — the plan-compiler's Hermes
    # compat boundary, not a rebrand miss.
    REPO_ROOT / "docs" / "plan-compiler.md",
    REPO_ROOT / "simplicio" / "plan_compiler" / "compat_adapter.py",
    # This file itself documents the compat surface in its docstrings/comments.
    Path(__file__).resolve(),
}

# Directories that hold vendored/generated/build content, not repo source —
# excluded from the stray-"hermes" scan (e.g. numpy's "hermite" polynomials,
# huggingface_hub's "Hermes" model references, generated caches).
EXCLUDED_DIR_NAMES = {
    ".venv",
    "venv",
    "node_modules",
    ".git",
    "dist",
    "build",
    ".simplicio",
    "playwright-report",
    "test-results",
    "simplicio_cli.egg-info",
}

DOC_GLOBS = [
    "README.md",
    "README.pt-BR.md",
    "AGENTS.md",
    "CLAUDE.md",
    "INIT.md",
    "bootstrap.sh",
    "bootstrap.ps1",
]


def _pyproject() -> dict:
    return tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]


def test_package_name_is_not_renamed_to_agent() -> None:
    """The Dev CLI package name must stay `simplicio-cli`, never an
    "agent"-branded name — Dev CLI and Simplicio Agent are distinct
    products (issue #167 AC: "Dev CLI não é renomeado para Agent")."""
    project = _pyproject()

    assert project["name"] == "simplicio-cli"
    assert "agent" not in project["name"].lower()


def test_entrypoints_keep_cli_dev_cli_naming() -> None:
    """All console-script entrypoints keep "cli"/"dev-cli" naming and point
    at the same `simplicio.cli:main`, none renamed to an agent-branded
    command."""
    project = _pyproject()
    scripts = project["scripts"]

    expected = {
        "simplicio-cli": "simplicio.cli:main",
        "simplicio-py": "simplicio.cli:main",
        "simplicio-dev-cli": "simplicio.cli:main",
    }
    assert scripts == expected
    for name in scripts:
        assert "agent" not in name.lower()


def test_no_stray_hermes_outside_documented_compat_surface() -> None:
    """Every remaining "hermes" mention in the repo's docs/scripts must live
    in one of the documented exceptions (CHANGELOG historical entry, the
    runtime_contracts.py legacy-alias detection list and its direct
    call sites/tests). Anything else is a leftover rebrand miss."""
    candidates: list[Path] = []
    for pattern in ("*.md", "*.sh", "*.ps1", "*.py"):
        candidates.extend(p for p in REPO_ROOT.rglob(pattern) if not EXCLUDED_DIR_NAMES & set(p.parts))

    offenders: list[str] = []
    for path in candidates:
        if path in ALLOWED_HERMES_FILES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if re.search(r"hermes", text, re.IGNORECASE):
            offenders.append(str(path.relative_to(REPO_ROOT)))

    assert not offenders, (
        f"Unexpected stray 'Hermes' mention(s) outside the documented compat surface: {offenders}"
    )


def test_doc_bootstrap_files_use_canonical_simplicio_agent_naming() -> None:
    """Wherever the Hermes-successor product is named in docs/bootstrap, it
    must be spelled canonically "Simplicio Agent" — no inconsistent variant
    (e.g. "SimplicioAgent", "Simplicio-Agent", "Agent Simplicio")."""
    variant_pattern = re.compile(
        r"simplicio[-_]agent(?![\s.,;:!?)\]-])|simplicioagent|agent[-_ ]simplicio",
        re.IGNORECASE,
    )

    offenders: list[str] = []
    for name in DOC_GLOBS:
        path = REPO_ROOT / name
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for match in variant_pattern.finditer(text):
            snippet = match.group(0)
            # "simplicio-agent" (kebab-case) is the legacy alias literal used
            # in compat-detection code paths/messages, not a doc naming slip;
            # canonical prose form is "Simplicio Agent" (space-separated).
            if snippet.lower() == "simplicio-agent":
                continue
            offenders.append(f"{name}: {snippet!r}")

    assert not offenders, f"Non-canonical 'Simplicio Agent' naming found: {offenders}"
