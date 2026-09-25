from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

from simplicio_fast.binary_changeset import prepare_from_json


def test_standalone_cli_consumes_one_fast_binary_changeset_for_multiple_files(tmp_path):
    operations = [
        {
            "op": "create",
            "path": "alpha.txt",
            "content": "alpha\n",
            "after_sha256": hashlib.sha256(b"alpha\n").hexdigest(),
        },
        {
            "op": "create",
            "path": "nested/beta.txt",
            "content": "beta\n",
            "after_sha256": hashlib.sha256(b"beta\n").hexdigest(),
        },
    ]
    changeset = prepare_from_json(
        {"operations": operations},
        root=tmp_path,
        base_generation="mapper-generation-1",
        overlay_generation="fast-generation-2",
        attempt="attempt-419-cli",
        worktree_id="worktree-419-cli",
        lease_id="lease-419-cli",
        fencing_token="fence-419-cli",
    )
    plan = tmp_path / "changeset.sfb"
    plan.write_bytes(changeset.encode())

    repository = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment.update(
        {
            "PYTHONPATH": os.pathsep.join(
                part for part in (str(repository), environment.get("PYTHONPATH", "")) if part
            ),
            "SIMPLICIO_SKIP_AUTO_INIT": "1",
            "SIMPLICIO_ALLOW_STANDALONE_FALLBACK": "true",
            "NO_PROXY": "*",
            "no_proxy": "*",
        }
    )
    cli = shutil.which("simplicio-dev-cli") or shutil.which("simplicio-dev-cli.cmd")
    assert cli is not None, "required standalone simplicio-dev-cli entrypoint is not on PATH"
    result = subprocess.run(
        [
            cli,
            "changeset",
            "--root",
            str(tmp_path),
            "--plan",
            str(plan),
            "--apply",
            "--fast-engine",
            "python",
            "--json",
        ],
        cwd=tmp_path,
        env=environment,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert result.returncode == 1, f"stdout={result.stdout}\nstderr={result.stderr}"
    receipt = json.loads(result.stdout)
    assert receipt.get("status") == "ok", f"stdout={result.stdout}\nstderr={result.stderr}"
    assert receipt["applied"] is True
    assert receipt["input_format"] == "simplicio.fast.binary-changeset/v1"
    assert receipt["fast_engine"]["name"] == "python"
    assert receipt["fast_engine"]["metrics"]["subprocesses"] == 0
    assert receipt["fast_engine"]["metrics"]["serializations"] == 0
    assert receipt["refresh"]["status"] == "REFRESH_PENDING"
    assert receipt["refresh"]["paths"] == ["alpha.txt", "nested/beta.txt"]
    assert receipt["transaction"]["state"] == "COMMITTED"
    assert {effect["path"] for effect in receipt["effects"]} == {
        "alpha.txt",
        "nested/beta.txt",
    }
    assert (tmp_path / "alpha.txt").read_text(encoding="utf-8") == "alpha\n"
    assert (tmp_path / "nested" / "beta.txt").read_text(encoding="utf-8") == "beta\n"
