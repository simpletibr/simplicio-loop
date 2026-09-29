"""The default gate runs only the tests a change can affect (scripts/impact_tests.py)."""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _repo(tmp_path: Path) -> Path:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "shop.py").write_text("def total():\n    return 1\n\n\ndef tax():\n    return 2\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_total.py").write_text("from pkg.shop import total\n", encoding="utf-8")
    (tmp_path / "tests" / "test_tax.py").write_text("from pkg.shop import tax\n", encoding="utf-8")
    (tmp_path / "tests" / "test_docs.py").write_text("README = 'README.md'\n", encoding="utf-8")
    (tmp_path / "tests" / "test_other.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("hello\n", encoding="utf-8")
    for args in (["init", "-q"], ["config", "user.email", "a@b.c"], ["config", "user.name", "a"],
                 ["add", "-A"], ["commit", "-qm", "seed"]):
        subprocess.run(["git", *args], cwd=tmp_path, check=True)
    return tmp_path


def test_only_the_tests_naming_the_changed_function_are_selected(tmp_path, monkeypatch):
    impact = _load("impact_tests")
    repo = _repo(tmp_path)
    monkeypatch.setattr(impact, "ROOT", repo)
    (repo / "pkg" / "shop.py").write_text("def total():\n    return 1\n\n\ndef tax():\n    return 3\n", encoding="utf-8")
    tests, symbols = impact.impacted_tests("HEAD")
    assert tests == ["tests/test_tax.py"] and symbols == {"tax": ["pkg/shop.py"]}


def test_a_changed_doc_selects_the_tests_that_read_it(tmp_path, monkeypatch):
    impact = _load("impact_tests")
    repo = _repo(tmp_path)
    monkeypatch.setattr(impact, "ROOT", repo)
    (repo / "README.md").write_text("changed\n", encoding="utf-8")
    assert impact.impacted_tests("HEAD")[0] == ["tests/test_docs.py"]


def test_a_changed_test_file_is_always_selected_and_nothing_else_runs_without_changes(tmp_path, monkeypatch):
    impact = _load("impact_tests")
    repo = _repo(tmp_path)
    monkeypatch.setattr(impact, "ROOT", repo)
    assert impact.impacted_tests("HEAD")[0] == []
    (repo / "tests" / "test_other.py").write_text("def test_x():\n    assert 1\n", encoding="utf-8")
    assert impact.impacted_tests("HEAD")[0] == ["tests/test_other.py"]


def test_check_runs_no_tests_when_nothing_is_impacted(monkeypatch):
    check = _load("check")
    monkeypatch.setattr(check, "_impacted_test_files", lambda base: [])
    result = check.run_tests(impact=True, base="HEAD")
    assert result.ok and result.reason_code == "no_impacted_tests"


def test_check_accepts_full_and_base_flags():
    text = (ROOT / "scripts" / "check.py").read_text(encoding="utf-8")
    assert '"--full"' in text and '"--base"' in text


def test_attribute_alias_and_dotted_string_references_select_the_test(tmp_path, monkeypatch):
    """A test reaches a symbol as `module.symbol`, `alias.symbol` or a dotted string, not only as a bare import."""
    impact = _load("impact_tests")
    repo = _repo(tmp_path)
    (repo / "tests" / "test_attr.py").write_text("import pkg.shop\n\n\ndef test_x():\n    assert pkg.shop.tax() == 2\n", encoding="utf-8")
    (repo / "tests" / "test_alias.py").write_text("from pkg import shop as s\n\n\ndef test_x():\n    assert s.tax() == 2\n", encoding="utf-8")
    (repo / "tests" / "test_string.py").write_text(
        "def test_x(monkeypatch):\n    monkeypatch.setattr('pkg.shop.tax', lambda: 2)\n", encoding="utf-8")
    (repo / "tests" / "test_unrelated.py").write_text("tax = 3\n\n\ndef test_x():\n    assert tax\n", encoding="utf-8")
    (repo / "tests" / "test_other_module.py").write_text("import json\n\n\ndef test_x():\n    assert json.tax\n", encoding="utf-8")
    monkeypatch.setattr(impact, "ROOT", repo)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "tests"], cwd=repo, check=True)
    (repo / "pkg" / "shop.py").write_text("def total():\n    return 1\n\n\ndef tax():\n    return 3\n", encoding="utf-8")
    tests, symbols = impact.impacted_tests("HEAD")
    assert tests == ["tests/test_alias.py", "tests/test_attr.py", "tests/test_string.py", "tests/test_tax.py"]
    assert symbols == {"tax": ["pkg/shop.py"]}


def test_a_test_that_runs_a_changed_file_by_path_is_selected_without_naming_a_symbol(tmp_path, monkeypatch):
    impact = _load("impact_tests")
    repo = _repo(tmp_path)
    (repo / "tests" / "test_blackbox.py").write_text(
        "import subprocess\nimport sys\n\n\ndef test_x():\n    subprocess.run([sys.executable, 'pkg/shop.py'])\n", encoding="utf-8")
    (repo / "tests" / "test_joined.py").write_text("import os\nSCRIPT = os.path.join('pkg', 'shop.py')\n", encoding="utf-8")
    monkeypatch.setattr(impact, "ROOT", repo)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "tests"], cwd=repo, check=True)
    (repo / "pkg" / "shop.py").write_text("def total():\n    return 1\n\n\ndef tax():\n    return 3\n", encoding="utf-8")
    assert impact.impacted_tests("HEAD")[0] == ["tests/test_blackbox.py", "tests/test_joined.py", "tests/test_tax.py"]


def test_a_changed_conftest_reaches_tests_by_fixture_name_and_an_autouse_fixture_reaches_all(tmp_path, monkeypatch):
    impact = _load("impact_tests")
    repo = _repo(tmp_path)
    conftest = repo / "tests" / "conftest.py"
    conftest.write_text("import pytest\n\n\n@pytest.fixture\ndef shop_env():\n    return 1\n\n\n"
                        "@pytest.fixture(autouse=True)\ndef quiet():\n    return 1\n", encoding="utf-8")
    (repo / "tests" / "test_uses_fixture.py").write_text("def test_x(shop_env):\n    assert shop_env\n", encoding="utf-8")
    monkeypatch.setattr(impact, "ROOT", repo)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "conftest"], cwd=repo, check=True)
    conftest.write_text(conftest.read_text(encoding="utf-8").replace("def shop_env():\n    return 1", "def shop_env():\n    return 2"),
                        encoding="utf-8")
    assert impact.impacted_tests("HEAD")[0] == ["tests/test_uses_fixture.py"]
    conftest.write_text(conftest.read_text(encoding="utf-8").replace("def quiet():\n    return 1", "def quiet():\n    return 2"),
                        encoding="utf-8")
    assert impact.impacted_tests("HEAD")[0] == sorted(
        f"tests/{name}" for name in ("test_docs.py", "test_other.py", "test_tax.py", "test_total.py", "test_uses_fixture.py"))
