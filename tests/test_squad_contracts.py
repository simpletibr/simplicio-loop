"""Interfaces-first squad contracts (#1504)."""

import subprocess
import sys

from simplicio_loop.squad_contracts import contracts_for, write_contracts

EDGES = [
    {"producer": "watcher", "consumer": "wiring"},
    {"producer": "wiring", "consumer": "flow-tests", "signature": "def wire(src: str, dst: str) -> bool"},
]


def test_contracts_for_each_edge():
    cs = contracts_for(EDGES)
    assert len(cs) == 2
    c = cs[0]
    assert c.producer == "watcher" and c.consumer == "wiring"
    assert c.module_path == "simplicio_loop/squad_iface/watcher_to_wiring.py"
    assert c.signature == "def watcher_to_wiring(payload: dict) -> dict"
    assert "def test_" in c.test_template and "watcher_to_wiring" in c.test_template
    assert c.test_path == "tests/contracts/test_watcher_to_wiring.py"
    assert cs[1].signature == "def wire(src: str, dst: str) -> bool"
    assert cs[1].module_path == "simplicio_loop/squad_iface/wiring_to_flow_tests.py"


def test_contracts_accept_pairs_and_dedupe():
    cs = contracts_for([("a", "b"), ("a", "b"), ("b", "c")])
    assert [(c.producer, c.consumer) for c in cs] == [("a", "b"), ("b", "c")]


def test_write_contracts_creates_stub_and_tests(tmp_path):
    cs = contracts_for(EDGES)
    res = write_contracts(tmp_path, cs)
    stub = tmp_path / cs[0].module_path
    assert stub.is_file()
    assert (tmp_path / "simplicio_loop/squad_iface/__init__.py").is_file()
    assert 'raise NotImplementedError("contract: watcher")' in stub.read_text()
    assert (tmp_path / cs[1].test_path).is_file()
    assert len(res["written"]) == 5 and res["skipped"] == []


def test_write_contracts_never_overwrites(tmp_path):
    cs = contracts_for(EDGES[:1])
    stub = tmp_path / cs[0].module_path
    stub.parent.mkdir(parents=True)
    stub.write_text("# mine\n")
    res = write_contracts(tmp_path, cs)
    assert stub.read_text() == "# mine\n"
    assert cs[0].module_path in res["skipped"]
    assert write_contracts(tmp_path, cs)["written"] == []


def test_generated_contract_tests_are_valid_and_xfail_until_implemented(tmp_path):
    cs = contracts_for(EDGES[:1])
    (tmp_path / "simplicio_loop").mkdir()
    (tmp_path / "simplicio_loop/__init__.py").write_text("")
    write_contracts(tmp_path, cs)
    out = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", cs[0].test_path],
        cwd=tmp_path, capture_output=True, text=True, env={"PYTHONPATH": str(tmp_path), "PATH": "/usr/bin:/bin"},
    )
    assert out.returncode == 0, out.stdout + out.stderr
    assert "1 passed" in out.stdout and "1 xfailed" in out.stdout
