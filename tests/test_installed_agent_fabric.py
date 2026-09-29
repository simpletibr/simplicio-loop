import json
import os
from pathlib import Path
import subprocess
import sys


def test_single_cross_repo_installed_and_stress(tmp_path):
    installed = os.environ.get("SIMPLICIO_765_INSTALLED_TARGET")
    if not installed:
        return
    script = Path(__file__).parents[1] / "scripts" / "installed_agent_fabric_e2e_765.py"
    output = tmp_path / "receipt.json"
    subprocess.run(
        [sys.executable, str(script), "--root", str(tmp_path / "run"),
         "--output", str(output), "--repetitions", "3"],
        cwd=tmp_path, env=dict(os.environ, PYTHONPATH=installed), check=True,
    )
    receipt = json.loads(output.read_text())
    assert all(path.startswith(installed) for path in receipt["module_roots"].values())
    assert receipt["single_repo"]["ledger_valid"] and not receipt["single_repo"]["unresolved"]
    assert receipt["cross_repo"]["ledger_valid"] and not receipt["cross_repo"]["unresolved"]
    assert receipt["cross_repo"]["workers_materialized"] == 3
    assert all(item["zero_loss"] for item in receipt["stress"].values())
    assert receipt["stress"]["600"]["samples"][0]["receipts"] == 600
    assert receipt["local_llm"] is False
