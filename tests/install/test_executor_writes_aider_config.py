"""The transactional installer (scripts/install_executor.py) writes `.aider.conf.yml` as the planner does: aider loads
CONVENTIONS.md only when that file names it under `read:`. The file is backed up and rolled back with the rest.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from simplicio_loop.install import entry

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


sys.path.insert(0, str(SCRIPTS))
_load("install_lib", "install_lib.py")
_load("install_plan", "install_plan.py")
install_executor = _load("install_executor", "install_executor.py")


def test_aider_install_writes_the_config_that_names_the_conventions(tmp_path):
    target = tmp_path / "project"
    target.mkdir()

    receipt = install_executor.apply("aider", target=str(target), is_global=False)

    assert receipt["status"] == "APPLIED"
    assert (target / "CONVENTIONS.md").is_file()
    assert (target / ".aider.conf.yml").read_text(encoding="utf-8") == entry.CONFIG[".aider.conf.yml"]


def test_aider_config_is_rolled_back_with_the_transaction(tmp_path):
    target = tmp_path / "project"
    target.mkdir()
    receipt = install_executor.apply("aider", target=str(target), is_global=False)

    install_executor.rollback(receipt["transaction_id"], str(target))

    assert not (target / ".aider.conf.yml").exists()
    assert not (target / "CONVENTIONS.md").exists()
