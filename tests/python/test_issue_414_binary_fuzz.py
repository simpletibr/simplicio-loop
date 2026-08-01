from __future__ import annotations

from importlib import util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "issue_414_binary_fuzz.py"


def _module():
    spec = util.spec_from_file_location("issue_414_binary_fuzz", SCRIPT)
    assert spec and spec.loader
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_binary_fuzz_corpus_fails_closed_without_mutation():
    report = _module().run_fuzz()
    assert report["schema"] == "simplicio.dev-cli.issue-414-binary-fuzz/v1"
    assert report["status"] in {"PASS", "UNAVAILABLE"}
    if report["status"] == "PASS":
        assert report["cases"] >= 32
        assert report["rejected"] == report["cases"]
        assert report["failures"] == []
