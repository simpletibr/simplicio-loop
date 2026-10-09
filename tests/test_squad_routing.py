"""Squad routing: first-worker role by task complexity (#1504)."""

from simplicio_loop.squad_routing import RouteDecision, route


def test_mechanical_single_module_is_execution():
    d = route({"files": ["a/x.py"], "modules": ["a"], "integrates": [], "touches_shared": False, "security": False})
    assert isinstance(d, RouteDecision)
    assert d.role == "execution"
    assert d.reasons


def test_integration_is_coordination():
    d = route({"files": ["a/x.py"], "modules": ["a"], "integrates": ["watcher"]})
    assert d.role == "coordination"
    assert any("integrat" in r for r in d.reasons)


def test_shared_file_is_coordination():
    d = route({"files": ["conftest.py"], "modules": ["a"], "touches_shared": True})
    assert d.role == "coordination"
    assert any("shared" in r for r in d.reasons)


def test_security_flag_is_coordination():
    assert route({"modules": ["a"], "security": True}).role == "coordination"


def test_security_label_is_coordination():
    assert route({"modules": ["a"], "labels": ["area:security"]}).role == "coordination"


def test_two_modules_is_coordination_boundary():
    assert route({"modules": ["a"]}).role == "execution"
    d = route({"modules": ["a", "b"]})
    assert d.role == "coordination"
    assert any("2" in r for r in d.reasons)


def test_modules_derived_from_files_when_absent():
    assert route({"files": ["a/x.py", "a/y.py"]}).role == "execution"
    assert route({"files": ["a/x.py", "b/y.py"]}).role == "coordination"


def test_duplicate_modules_count_once():
    assert route({"modules": ["a", "a"]}).role == "execution"


def test_deterministic_and_explain():
    task = {"modules": ["a", "b"], "security": True}
    assert route(task) == route(dict(task))
    text = route(task).explain()
    assert isinstance(text, str) and "coordination" in text and "security" in text
    assert "execution" in route({"modules": ["a"]}).explain()
