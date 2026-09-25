import json
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
        "rust/simplicio-fast-core/Cargo.toml",
        "rust/Cargo.lock",
        ".github/workflows/native-release.yml",
        "docs/native-backend-support.md",
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


def test_rust_core_version_drift_fails_closed(tmp_path):
    root = _fixture(tmp_path)
    cargo = root / "rust/simplicio-fast-core/Cargo.toml"
    _replace_once(
        cargo, f'version = "{PROJECT_VERSION}"', f'version = "{DRIFT_VERSION}"'
    )
    receipt = evaluate(root)
    assert "rust_core_version" in receipt["failures"]


def test_rust_cargo_lock_version_drift_fails_closed(tmp_path):
    root = _fixture(tmp_path)
    lock = root / "rust/Cargo.lock"
    _replace_once(
        lock, f'version = "{PROJECT_VERSION}"', f'version = "{DRIFT_VERSION}"'
    )
    receipt = evaluate(root)
    assert "rust_cargo_lock_version" in receipt["failures"]


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


def test_native_ownership_and_platform_drift_fail_closed(tmp_path):
    root = _fixture(tmp_path)
    policy_path = root / "src/simplicio_fast/release_policy.json"
    policy = json.loads(policy_path.read_text())
    policy["native_execution_owner"] = "simplicio-fast"
    policy["supported_native_platforms"].append("plan9-mips")
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    receipt = evaluate(root)
    assert {"native_ownership", "native_platform_matrix"} <= set(receipt["failures"])


def test_check_mode_returns_nonzero_for_drift(tmp_path):
    root = _fixture(tmp_path)
    (root / "README.md").write_text("stale", encoding="utf-8")
    assert main(["--root", str(root), "--check", "--json"]) == 1
