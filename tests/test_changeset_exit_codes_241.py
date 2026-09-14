from __future__ import annotations

import json
import sys
from types import SimpleNamespace

from simplicio_fast import binary_changeset, cli


def test_materialize_cli_fails_closed_on_locked_receipt(monkeypatch, tmp_path, capsys):
    changeset = SimpleNamespace(
        changeset_id="changeset-241",
        worktree_id="worktree-241",
        lease_id="lease-241",
        fencing_token="fence-241",
    )

    class Selection:
        def receipt(self):
            return {"name": "python", "status": "ready"}

    monkeypatch.setattr(cli, "select_engine", lambda _mode: Selection())
    monkeypatch.setattr(cli, "_rust_bridge", lambda _selection, _args: None)
    monkeypatch.setattr(binary_changeset, "read_binary", lambda _path: changeset)
    monkeypatch.setattr(
        binary_changeset,
        "BinaryChangeJournal",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        binary_changeset,
        "materialize",
        lambda *_args, **_kwargs: {
            "schema": "simplicio.fast.binary-changeset-receipt/v1",
            "status": "locked",
            "reason_code": "unknown_effect",
            "reconcile_required": True,
        },
    )
    monkeypatch.setenv("SIMPLICIO_FAST_ALLOW_WRITE", "1")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "simplicio-fast",
            "changeset",
            "materialize",
            "changeset.sfc",
            "--root",
            str(tmp_path),
            "--journal",
            str(tmp_path / "journal"),
            "--write",
        ],
    )

    assert cli.main() == 1
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["status"] == "locked"
    assert receipt["reconcile_required"] is True
