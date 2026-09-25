from pathlib import Path
import shutil
import tomllib

from scripts.check_release_integrity import SCHEMA, evaluate, main


ROOT = Path(__file__).resolve().parents[1]
PROJECT_VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
    "project"
]["version"]
DRIFT_VERSION = "999.0.0"


def _replace_once(path: Path, expected: str, replacement: str) -> None:
    before = path.read_text(encoding="utf-8")
    assert expected in before, f"fixture mutation target missing: {expected!r}"
    after = before.replace(expected, replacement, 1)
    assert after != before, "fixture mutation must change the content"
    path.write_text(after, encoding="utf-8")


def _fixture(tmp_path: Path) -> Path:
    for relative in (
        "src/simplicio_fast/release_policy.json",
        "release-policy.json",
        "pyproject.toml",
        "README.md",
        "CHANGELOG.md",
        "src/simplicio_fast/__init__.py",
    ):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    return tmp_path


def test_repository_release_metadata_is_consistent():
    receipt = evaluate(ROOT)
    assert receipt["schema"] == SCHEMA
    assert receipt["status"] == "pass", receipt
    assert receipt["version"] == PROJECT_VERSION
    assert receipt["runtime_dependencies"] == []
    assert len(receipt["integrated_dependencies"]) == 2


def test_version_drift_fails_closed(tmp_path):
    root = _fixture(tmp_path)
    init = root / "src/simplicio_fast/__init__.py"
    _replace_once(
        init,
        f'__version__ = "{PROJECT_VERSION}"',
        f'__version__ = "{DRIFT_VERSION}"',
    )
    receipt = evaluate(root)
    assert receipt["status"] == "fail"
    assert "package_version" in receipt["failures"]


def test_dependency_badge_drift_fails_closed(tmp_path):
    root = _fixture(tmp_path)
    readme = root / "README.md"
    readme.write_text(
        readme.read_text(encoding="utf-8").replace(
            "integrated_extra_dependencies-2-",
            "integrated_extra_dependencies-0-",
        ),
        encoding="utf-8",
    )
    receipt = evaluate(root)
    assert "readme_dependencies" in receipt["failures"]


def test_changelog_version_drift_fails_closed(tmp_path):
    root = _fixture(tmp_path)
    changelog = root / "CHANGELOG.md"
    _replace_once(
        changelog,
        f"## {PROJECT_VERSION} ",
        f"## {DRIFT_VERSION} ",
    )
    receipt = evaluate(root)
    assert "changelog_version" in receipt["failures"]


def test_check_mode_returns_nonzero_for_drift(tmp_path):
    root = _fixture(tmp_path)
    (root / "README.md").write_text("stale", encoding="utf-8")
    assert main(["--root", str(root), "--check", "--json"]) == 1
