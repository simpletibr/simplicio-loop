"""Regression guard for issue #1343: `simplicio-fast` was removed from the
`simplicio-loop` stack entirely (Mapper-only survey).

Scope note: this guard covers the `simplicio-fast` package itself, the
`simplicio_loop` package's own Fast integration modules, the
`simplicio-fast` skill, the survey/orient Mapper-only contract, the 5-arm
ablation benchmark, the packaging/tooling surfaces the issue names
explicitly (`scripts/check.py`, `pyproject.toml`, `scripts/dev_install.sh`)
and, via `test_loop_owned_code_has_no_fast_reference`, every loop-owned
code, hook, script, contract, catalog and fixture tree.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FAST_NAME = re.compile(r"simplicio[-_]fast", re.IGNORECASE)


def _text(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def test_fast_package_and_skill_directories_are_gone():
    assert not (REPO / "packages" / "fast").exists()
    assert not (REPO / ".claude" / "skills" / "simplicio-fast").exists()
    assert not (REPO / "plugin" / "skills" / "simplicio-fast").exists()
    assert not (REPO / "simplicio_loop" / "_bundle" / "skills" / "simplicio-fast").exists()


def test_fast_standalone_loop_modules_are_gone():
    for name in (
        "fast_integration", "fast_fanout", "fast_task_bridge", "fast_resident",
        "fast_receipt_audit", "fast_v3_delivery", "fast_v3_cli",
        "composed_fast_delivery", "local_first_path",
    ):
        assert not (REPO / "simplicio_loop" / f"{name}.py").exists(), name


def test_fast_dedicated_tests_and_benchmarks_are_gone():
    for name in (
        "test_fast_fanout.py", "test_fast_integration.py", "test_fast_task_bridge_897.py",
        "test_fast_receipt_audit_196.py", "test_fast_resident_804.py",
        "test_issue_1187_fast_auto_target.py", "test_fast_v3_delivery_760.py",
        "test_cli_fast_orient.py", "test_composed_fast_delivery_900.py",
        "test_issue_1266_fast_creation_corridor.py",
        "test_issue_1273_fast_creation_preparation.py", "test_local_first_path_901.py",
    ):
        assert not (REPO / "tests" / name).exists(), name
    assert not (REPO / "scripts" / "benchmark_fast_v3_760.py").exists()
    assert not (REPO / "scripts" / "benchmark_fast_fanout.py").exists()
    assert not (REPO / "docs" / "fast-fanout.md").exists()


def test_survey_operators_is_mapper_only():
    from simplicio_loop.survey import SURVEY_OPERATORS

    assert SURVEY_OPERATORS == frozenset({"simplicio-mapper"})


def test_prepare_missing_reason_has_no_fast_wording():
    from simplicio_loop.survey import MISSING_REASON

    assert not FAST_NAME.search(MISSING_REASON)
    assert MISSING_REASON == "mapper_provenance_missing"


def test_ablation_arms_is_exactly_the_5_arms_no_fast():
    import sys

    sys.path.insert(0, str(REPO / "bench" / "llm_ab"))
    import arms  # noqa: E402

    assert arms.ARM_NAMES == ("normal", "mapper", "devcli", "mapper-devcli", "simplicio")
    for name in arms.ARM_NAMES:
        assert not FAST_NAME.search(name)
    assert not any(FAST_NAME.search(b) for b in arms.ALL_BINS)


def test_check_py_has_no_fast_package_gate():
    text = _text("scripts/check.py")
    assert "\"fast\": os.path.join(REPO, \"packages\", \"fast\")" not in text
    assert 'PACKAGE_NAMES = ("mapper", "dev-cli", "loop")' in text
    assert "run_cross_package_e2e" not in text


def test_dev_install_sh_installs_one_editable_root_package():
    text = _text("scripts/dev_install.sh")
    assert "packages/fast" not in text
    # mapper + dev-cli are built into the root distribution, so the dev workspace is ONE
    # editable install of the root package (no per-package editable installs).
    editable_installs = [
        line.strip()
        for line in text.splitlines()
        if "pip install" in line and " -e " in line and not line.lstrip().startswith("#")
    ]
    assert editable_installs == ['"$VENV_PY" -m pip install -e "$REPO[dev]"']


def test_pyproject_has_no_simplicio_fast_dependency():
    text = _text("pyproject.toml")
    assert '"simplicio-fast' not in text


def test_llm_orientation_toon_has_no_fast_skill_entry():
    text = _text("docs/LLM_ORIENTATION.toon")
    assert "simplicio-fast/SKILL.md" not in text


# Loop-owned code/contract trees that must not reference the removed Fast
# operator.  Generated copies (`_bundle`) and historical benchmark evidence
# (`bench/llm_ab/results`, rendered `REPORT-*.html`) are not code.
_CODE_TREES = (
    "simplicio_loop", "hooks", "scripts", "contracts", "bench", "tests/fixtures",
)
_CODE_SUFFIXES = {".py", ".json", ".md", ".sh", ".ps1", ".toml", ".yaml", ".yml"}
_FAST_REFERENCE = re.compile(
    r"simplicio[-_]fast|SIMPLICIO_FAST|mapper_fast|fast_handoff|fast_link"
    r"|fast_backend|fast_certification|fast-context|fast-certification|fast-generation",
    re.IGNORECASE,
)


def _loop_owned_files():
    for tree in _CODE_TREES:
        for path in sorted((REPO / tree).rglob("*")):
            rel = path.relative_to(REPO).as_posix()
            if not path.is_file() or path.suffix not in _CODE_SUFFIXES:
                continue
            if "/_bundle/" in f"/{rel}" or "/__pycache__/" in f"/{rel}":
                continue
            if rel.startswith("bench/llm_ab/results/"):
                continue
            yield rel, path


def test_loop_owned_code_has_no_fast_reference():
    offenders = []
    for rel, path in _loop_owned_files():
        for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if _FAST_REFERENCE.search(line):
                offenders.append(f"{rel}:{number}: {line.strip()[:120]}")
    assert offenders == []


def test_pyproject_has_no_fast_reference():
    assert not _FAST_REFERENCE.search(_text("pyproject.toml"))


def test_fast_only_loop_surfaces_are_gone():
    assert not (REPO / "simplicio_loop" / "context_packet_consumer.py").exists()
    assert not (REPO / "scripts" / "installed_coverage_custodian_e2e_784.py").exists()
    for base in ("contracts", "simplicio_loop/_contracts"):
        assert not (REPO / base / "registry" / "v1" / "schemas" / "fast-generation.schema.json").exists()
