"""Every flow goes through Mapper (issue #1318; issue #1343 removed Fast
from the stack entirely): the wave's `prepare` refuses to arm a run on a
repo `orient` has not surveyed."""
from __future__ import annotations

import json
import subprocess

from simplicio_loop import cli_impl


def test_prepare_without_mapper_survey_is_blocked(tmp_path, capsys):
    subprocess.run(["git", "init", "-q"], cwd=str(tmp_path), check=True)
    (tmp_path / "tasks.md").write_text("System: x\nFeature: y\nType: Docs\n", encoding="utf-8")
    rc = cli_impl.prepare(str(tmp_path), str(tmp_path / "tasks.md"), "verified", 3)
    out = json.loads(capsys.readouterr().out)
    assert rc == 2
    assert out["status"] == "blocked"
    assert out["reason_code"] == "mapper_provenance_missing"
    assert not (tmp_path / ".simplicio-loop" / "loop-runs").exists()
