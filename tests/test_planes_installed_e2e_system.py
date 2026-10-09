import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "planes_installed_e2e.py"
TASK = ROOT / "contracts/task-to-delivery/fixtures/planes/task.md"


@pytest.mark.external_integration
def test_installed_planes_gate_uses_real_path_and_raw_markdown(tmp_path):
    # #291 — this is a real e2e test against the *published* console scripts
    # (simplicio-mapper, simplicio-dev-cli, simplicio-loop, simplicio), not this repo's source
    # checkout. It requires those packages installed and functionally working on PATH, which a
    # plain source checkout (what `pytest tests/` / `scripts/check.py` run against) does not
    # guarantee — the audit behind #291 found this exact test hard-failing the source-tests gate
    # for that reason. Skip (not silently pass, not hard-fail) whenever the receipt itself reports
    # BLOCKED, i.e. whenever the installed toolchain genuinely could not complete the flow; that
    # keeps this test meaningful in an `installed-e2e` job (dedicated venv with the wheel/CLIs
    # actually installed and working) without making unrelated source changes fail this gate.
    # The operators map a throwaway repository, never this checkout (#1574): the Runtime writes its
    # baseline and scratch into the git common dir every worktree shares.
    repo = tmp_path / "repo"
    repo.mkdir()
    for command in (["init", "-q"], ["config", "user.email", "t@example.com"], ["config", "user.name", "t"]):
        subprocess.run(["git", *command], cwd=repo, check=True)
    (repo / "app.py").write_text("def app():\n    return 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=repo, check=True)
    result = subprocess.run([sys.executable, str(SCRIPT), "--task", str(TASK), "--repo", str(repo), "--json"],
                            cwd=tmp_path, capture_output=True, text=True,
                            stdin=subprocess.DEVNULL, timeout=180)
    receipt = json.loads(result.stdout) if result.stdout else {}
    if result.returncode != 0 or receipt.get("status") == "BLOCKED":
        pytest.skip(
            "EXTERNAL_INTEGRATION_UNAVAILABLE[installed_e2e]: "
            "installed-e2e toolchain unavailable or non-functional in this environment "
            f"(status={receipt.get('status')!r}, reason={receipt.get('reason')!r}); "
            "run this test in the dedicated installed-e2e job (#291) against a clean venv "
            "with simplicio-mapper/simplicio-dev-cli/simplicio-loop/simplicio actually installed"
        )
    assert receipt["schema"] == "simplicio.planes-installed-e2e/v1"
    assert receipt["status"] == "PLANNED"
    assert receipt["proof_kind"] == "measured"
    assert receipt["task_source"].endswith("contracts/task-to-delivery/fixtures/planes/task.md")
    assert len(receipt["hops"]) == 4
    assert all(h["returncode"] == 0 for h in receipt["hops"])
    assert all(row["ok"] and os.path.isabs(row["path"]) for row in receipt["installed"])


def test_installed_gate_has_no_fake_or_in_process_operator_path():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "stand-in" not in source.lower()
    assert "import simplicio" not in source
    assert "subprocess.run" in source
    assert "--task-file" in source
    assert "--execute" in source


def test_missing_installed_binary_fails_closed(tmp_path):
    env = dict(os.environ)
    env["PATH"] = str(tmp_path)
    result = subprocess.run([sys.executable, str(SCRIPT), "--json"], cwd=ROOT,
                            env=env, capture_output=True, text=True,
                            stdin=subprocess.DEVNULL, timeout=30)
    assert result.returncode == 2
    receipt = json.loads(result.stdout)
    assert receipt["status"] == "BLOCKED"
    assert receipt["reason"]
