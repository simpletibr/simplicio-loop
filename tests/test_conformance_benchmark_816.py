import json
import os
from pathlib import Path
import subprocess
import sys


def test_clean_install_conformance_raw_evidence(tmp_path):
    installed = os.environ.get("SIMPLICIO_816_INSTALLED_TARGET")
    if not installed:
        return
    script = Path(__file__).parents[1] / "scripts" / "conformance_benchmark_816.py"
    output = tmp_path / "raw.json"
    subprocess.run(
        [sys.executable, str(script), "--root", str(tmp_path / "run"),
         "--output", str(output), "--repetitions", "10",
         "--loop-wheel-sha256", "a" * 64,
         "--mapper-wheel-sha256", "b" * 64],
        cwd=tmp_path, env=dict(os.environ, PYTHONPATH=installed), check=True,
    )
    receipt = json.loads(output.read_text())
    assert receipt["classification"] == "MEASURED_CLEAN_INSTALL"
    assert all(len(item["samples"]) == 10 for item in receipt["lanes"].values())
    assert all(item["summary"]["quality_pass_rate"] == 1 for item in receipt["lanes"].values())
    assert receipt["fault_injection"]["all_faults_blocked_as_expected"]
    assert receipt["fault_injection"]["recovery_no_duplicate"]
    assert receipt["fault_injection"]["committed_effects"] == 1
    assert receipt["tokens"] is None and receipt["tokens_null_reason"]
    assert len(receipt["raw_data_sha256"]) == 64
    assert receipt["local_llm"] is False
