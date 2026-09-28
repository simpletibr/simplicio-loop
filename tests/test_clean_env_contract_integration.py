import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "scripts", "clean_env_contract.py")


def _run(*args):
    return subprocess.run([sys.executable, SCRIPT] + list(args), capture_output=True, text=True,
                          cwd=REPO, stdin=subprocess.DEVNULL, timeout=60)


def test_clean_env_contract_selftest():
    r = _run("selftest")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout, r.stdout


def test_clean_env_contract_check_reports_structured_checks():
    r = _run("check")
    assert r.returncode in (0, 1), r.stdout + r.stderr
    payload = json.loads(r.stdout)
    names = {row.get("name") for row in payload.get("checks", [])}
    assert payload.get("ok") in (True, False)
    assert {"dependency.no_external_operators", "entrypoint.cli", "bundle.skill.exists"} <= names
    # mapper and dev-cli are bundled in the single wheel: the per-operator dependency checks are gone
    assert not {"dependency.simplicio_cli", "dependency.simplicio_mapper"} & names
    no_external = next(
        row for row in payload["checks"] if row.get("name") == "dependency.no_external_operators"
    )
    assert no_external["ok"] is True, no_external


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _selfrun import run_module
    run_module(globals(), "test_clean_env_contract")
