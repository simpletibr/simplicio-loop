"""scripts/doctor.py checks the Python it runs on against requires-python in pyproject.toml, and its row names that interpreter."""
from __future__ import annotations

import importlib.util
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def load_doctor():
    spec = importlib.util.spec_from_file_location("doctor_script_under_test", REPO / "scripts" / "doctor.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_minimum_python_of_the_check_is_the_one_pyproject_requires():
    declared = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]["requires-python"]
    assert declared == ">=%d.%d" % load_doctor().MIN_PYTHON


def test_a_python_older_than_the_minimum_fails_and_the_row_names_the_interpreter():
    doctor = load_doctor()
    row = doctor.chk_python(version=(3, 10, 12), executable="/opt/old/bin/python3")
    assert row["status"] == doctor.FAIL
    assert row["msg"] == "3.10.12 at /opt/old/bin/python3"


def test_the_minimum_python_passes_and_the_row_names_the_interpreter():
    doctor = load_doctor()
    row = doctor.chk_python(version=(3, 11, 0), executable="/opt/new/bin/python3")
    assert row["status"] == doctor.OK
    assert row["msg"] == "3.11.0 at /opt/new/bin/python3"
